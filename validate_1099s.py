import argparse
import re
import sys
from pathlib import Path
import pandas as pd

# Column name mappings for eFileMagic-style worksheets
HEADER_MAP = {
    # Recipient name
    "Recipient Name1": "recipient_name",
    "Recipient Name 1": "recipient_name",
    "Recipient Name": "recipient_name",
    "RecipientName": "recipient_name",
    "Name": "recipient_name",
    "Payee Name": "recipient_name",
    # Recipient name 2 (DBA / second line)
    "Recipient Name2": "recipient_name2",
    "Recipient Name 2": "recipient_name2",
    # TIN
    "RecipientTaxID": "tin",
    "Recipient TIN": "tin",
    "Recipient TaxID": "tin",
    "TIN": "tin",
    "SSN": "tin",
    "EIN": "tin",
    "Tax ID": "tin",
    # Address
    "Address1": "address1",
    "Address 1": "address1",
    "Street Address": "address1",
    "Address": "address1",
    "Address2": "address2",
    "Address 2": "address2",
    # Location
    "City": "city",
    "State": "state",
    "ZipCode": "zip",
    "ZIP": "zip",
    "Zip": "zip",
    "Zip Code": "zip",
    "Postal Code": "zip",
    # Country
    "ForeignCountry": "country",
    "Foreign Country": "country",
    "Country": "country",
    # Account
    "AccountNum": "account_number",
    "Account Number": "account_number",
    "AccountNumber": "account_number",
    # Email
    "EMailAddress": "email",
    "Email": "email",
    # 1099-NEC boxes
    "Box1_NEC": "nec_box1",
    "NEC Box 1": "nec_box1",
    "NEC Box1": "nec_box1",
    "Nonemployee Compensation": "nec_box1",
    "Box2_DirectSales": "nec_box2",
    "Box4_FedWithheld": "fed_withheld",
    "Box5_StateTaxWithheld": "state_tax_withheld",
    "Box6_State": "state_code",
    "Box6_StateID": "state_payer_id",
    "Box7_StateIncome": "state_income",
    # 1099-MISC boxes
    "Box1_RENTS": "misc_box1",
    "MISC Box 1": "misc_box1",
    "Rents": "misc_box1",
    "Box2_Royalties": "misc_box2",
    "Box3_OtherIncome": "misc_box3",
    "Box3_ OtherIncome": "misc_box3",
    "MISC Box 3": "misc_box3",
    "Other Income": "misc_box3",
    "Box7_NEC": "misc_box7",
    "MISC Box 7": "misc_box7",
    "Box15_StateTaxWithheld": "state_tax_withheld",
    "Box16_State": "state_code",
    "Box16_StateID": "state_payer_id",
    "Box17_StateIncome": "state_income",
    # Generic withholding
    "BOX4": "fed_withheld",
    # Form type (if present as column)
    "Form Type": "form_type",
    "FormType": "form_type",
    # Payer info
    "Payer Name": "payer_name",
    "PayerName": "payer_name",
    "Payer TIN": "payer_tin",
    "PayerTIN": "payer_tin",
    "Payer EIN": "payer_tin",
}

SUPPORTED_FORM_TYPES = {"1099-NEC", "1099-MISC"}

US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DC","DE","FL","GA","HI","IA","ID","IL","IN","KS","KY",
    "LA","MA","MD","ME","MI","MN","MO","MS","MT","NC","ND","NE","NH","NJ","NM","NV","NY","OH",
    "OK","OR","PA","RI","SC","SD","TN","TX","UT","VA","VT","WA","WI","WV","WY"
}

TIN_RE = re.compile(r"^\d{9}$")
ZIP5_RE = re.compile(r"^\d{5}$|^\d{5}-\d{4}$")


def normalize_headers(df):
    mapped = {}
    for c in df.columns:
        key = c.strip()
        if key in HEADER_MAP:
            mapped[c] = HEADER_MAP[key]
        else:
            mapped[c] = key.lower().strip().replace(" ", "_")
    return df.rename(columns=mapped)


def coerce_numeric(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = df[c].astype(str).str.replace(",", "", regex=False).str.strip()
            df[c] = df[c].replace({"": None, "nan": None, "NaN": None, "None": None})
            df[c] = pd.to_numeric(df[c], errors="coerce")


def clean_text(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip().replace({"nan": "", "NaN": "", "None": ""})


def add_error(row_errors, msg):
    if msg not in row_errors:
        row_errors.append(msg)


def extract_filer_info(xlsx):
    filer_info = {"payer_name": "", "payer_tin": "", "filing_year": ""}
    if "Filer Information" not in xlsx.sheet_names:
        return filer_info
    df = pd.read_excel(xlsx, sheet_name="Filer Information", dtype=str, header=None)
    for idx, row in df.iterrows():
        label = str(row.iloc[0] if pd.notna(row.iloc[0]) else "").strip().lower()
        value = str(row.iloc[1] if len(row) > 1 and pd.notna(row.iloc[1]) else "").strip()
        if "filer taxid" in label or "company / filer taxid" in label:
            filer_info["payer_tin"] = value.replace("-", "")
        elif "filer name1" in label or "company / filer name1" in label:
            filer_info["payer_name"] = value
        elif "filing year" in label and value.isdigit():
            filer_info["filing_year"] = value
    return filer_info


def form_specific_rules(row, form_type, errors):
    f = form_type.upper()
    if f == "1099-NEC":
        nec = row.get("nec_box1")
        if pd.isna(nec) or float(nec or 0) <= 0:
            add_error(errors, "For 1099-NEC, Box 1 (compensation) must be > 0.")
    elif f == "1099-MISC":
        misc_boxes = ["misc_box1", "misc_box2", "misc_box3", "misc_box7"]
        has_amount = any(pd.notna(row.get(c)) and float(row.get(c) or 0) > 0 for c in misc_boxes)
        if not has_amount:
            add_error(errors, "For 1099-MISC, at least one box must be > 0.")


def validate_dataframe(df, form_type=None, filer_info=None):
    if filer_info is None:
        filer_info = {}
    df = normalize_headers(df.copy())
    if "form_type" not in df.columns and form_type:
        df["form_type"] = form_type
    if "payer_name" not in df.columns and filer_info.get("payer_name"):
        df["payer_name"] = filer_info["payer_name"]
    if "payer_tin" not in df.columns and filer_info.get("payer_tin"):
        df["payer_tin"] = filer_info["payer_tin"]

    numeric_cols = ["nec_box1", "nec_box2", "misc_box1", "misc_box2", "misc_box3", "misc_box7",
                    "fed_withheld", "state_tax_withheld", "state_income"]
    text_cols = [c for c in df.columns if c not in numeric_cols]
    clean_text(df, text_cols)
    coerce_numeric(df, numeric_cols)

    if "tin" in df.columns:
        df["tin"] = df["tin"].str.replace("-", "", regex=False).str.strip()
    if "payer_tin" in df.columns:
        df["payer_tin"] = df["payer_tin"].astype(str).str.replace("-", "", regex=False).str.strip()

    errors = []
    required = ["recipient_name", "tin", "address1", "city", "state", "zip"]
    for idx, row in df.iterrows():
        row_errs = []
        for req in required:
            val = row.get(req)
            if req not in df.columns or pd.isna(val) or str(val).strip() == "":
                add_error(row_errs, f"Missing required field: {req}")
        tin_val = str(row.get("tin") or "")
        if not TIN_RE.match(tin_val):
            add_error(row_errs, "Recipient TIN must be exactly 9 digits.")
        payer_tin = str(row.get("payer_tin") or "")
        if payer_tin and not TIN_RE.match(payer_tin):
            add_error(row_errs, "Payer TIN must be exactly 9 digits.")
        st = (row.get("state") or "").upper()
        if st and st not in US_STATES:
            add_error(row_errs, f"State must be 2-letter US code; got '{st}'.")
        zp = str(row.get("zip") or "")
        if zp and not ZIP5_RE.match(zp):
            add_error(row_errs, "ZIP must be 12345 or 12345-6789.")
        row_form = (row.get("form_type") or form_type or "").upper()
        if row_form in SUPPORTED_FORM_TYPES:
            form_specific_rules(row, row_form, row_errs)
        if row_errs:
            errors.append({"__row_index": idx, **row.to_dict(), "error_reason": " | ".join(row_errs)})

    err_df = pd.DataFrame(errors)
    ok_df = df.drop(index=err_df["__row_index"].values) if not err_df.empty else df.copy()
    return ok_df, err_df


def process_workbook(xlsx_path):
    xlsx = pd.ExcelFile(xlsx_path)
    filer_info = extract_filer_info(xlsx)
    all_valid, all_errors = [], []
    for sheet_name in xlsx.sheet_names:
        if sheet_name in ("Filer Information",):
            continue
        form_type = sheet_name.upper()
        if form_type in ("1099NEC", "1099-NEC"):
            form_type = "1099-NEC"
        elif form_type in ("1099MISC", "1099-MISC"):
            form_type = "1099-MISC"
        elif form_type not in SUPPORTED_FORM_TYPES:
            continue
        df = pd.read_excel(xlsx, sheet_name=sheet_name, dtype=str)
        if df.empty:
            continue
        ok_df, err_df = validate_dataframe(df, form_type=form_type, filer_info=filer_info)
        if not ok_df.empty:
            ok_df["__source_sheet"] = sheet_name
            all_valid.append(ok_df)
        if not err_df.empty:
            err_df["__source_sheet"] = sheet_name
            all_errors.append(err_df)
    valid_df = pd.concat(all_valid, ignore_index=True) if all_valid else pd.DataFrame()
    error_df = pd.concat(all_errors, ignore_index=True) if all_errors else pd.DataFrame()
    return valid_df, error_df, filer_info


def main():
    ap = argparse.ArgumentParser(description="Validate 1099 worksheets for IRIS submission")
    ap.add_argument("excel_path", help="Path to Excel workbook or CSV file")
    ap.add_argument("--sheet", default=None, help="Sheet name (Excel only)")
    ap.add_argument("--out_ok", default="validated_1099s.csv")
    ap.add_argument("--out_err", default="error_log.csv")
    args = ap.parse_args()
    p = Path(args.excel_path)
    if not p.exists():
        print(f"File not found: {p}")
        sys.exit(1)
    if p.suffix.lower() == ".csv":
        df = pd.read_csv(p, dtype=str)
        ok_df, err_df = validate_dataframe(df)
        filer_info = {}
    elif args.sheet:
        xlsx = pd.ExcelFile(p)
        filer_info = extract_filer_info(xlsx)
        df = pd.read_excel(xlsx, sheet_name=args.sheet, dtype=str)
        form_type = args.sheet.upper()
        if form_type in ("1099NEC", "1099-NEC"):
            form_type = "1099-NEC"
        elif form_type in ("1099MISC", "1099-MISC"):
            form_type = "1099-MISC"
        ok_df, err_df = validate_dataframe(df, form_type=form_type, filer_info=filer_info)
    else:
        ok_df, err_df, filer_info = process_workbook(p)
    ok_df.to_csv(args.out_ok, index=False)
    err_df.to_csv(args.out_err, index=False)
    payer_tin_display = filer_info.get("payer_tin", "")[:4] + "..." if filer_info.get("payer_tin") else "N/A"
    print(f"Payer: {filer_info.get('payer_name', 'N/A')} (TIN: {payer_tin_display})")
    print(f"Total valid: {len(ok_df)}  |  Total invalid: {len(err_df)}")
    if len(err_df):
        print(f"See {args.out_err} for error details.")

if __name__ == "__main__":
    main()
