
import argparse
import re
import sys
from pathlib import Path
import pandas as pd

HEADER_MAP = {
    "Recipient Name": "recipient_name",
    "Recipient TIN": "tin",
    "Address 1": "address1",
    "Address 2": "address2",
    "City": "city",
    "State": "state",
    "ZIP": "zip",
    "Country": "country",
    "Form Type": "form_type",
    "Payer Name": "payer_name",
    "Payer TIN": "payer_tin",
    "Account Number": "account_number",
    "NEC Box 1": "nec_box1",
    "MISC Box 1": "misc_box1",
    "MISC Box 3": "misc_box3",
    "MISC Box 7": "misc_box7",
    "State Income": "state_income",
    "State Tax Withheld": "state_tax_withheld",
    "State Payer Number": "state_payer_number",
}

ALLOWED_FORM_TYPES = {"1099-NEC", "1099-MISC"}

US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DC","DE","FL","GA","HI","IA","ID","IL","IN","KS","KY",
    "LA","MA","MD","ME","MI","MN","MO","MS","MT","NC","ND","NE","NH","NJ","NM","NV","NY","OH",
    "OK","OR","PA","RI","SC","SD","TN","TX","UT","VA","VT","WA","WI","WV","WY"
}

TIN_RE = re.compile(r"^\d{9}$")
ZIP5_RE = re.compile(r"^\d{5}$|^\d{5}-\d{4}$")

def normalize_headers(df: pd.DataFrame) -> pd.DataFrame:
    mapped = {}
    for c in df.columns:
        key = c.strip()
        if key in HEADER_MAP:
            mapped[c] = HEADER_MAP[key]
        else:
            mapped[c] = key.lower().strip().replace(" ", "_")
    return df.rename(columns=mapped)

def coerce_numeric(df: pd.DataFrame, cols):
    for c in cols:
        if c in df.columns:
            df[c] = (
                df[c]
                .astype(str)
                .str.replace(",", "", regex=False)
                .str.strip()
                .replace({"": None, "nan": None})
            )
            df[c] = pd.to_numeric(df[c], errors="coerce")

def clean_text(df: pd.DataFrame, cols):
    for c in cols:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()

def add_error(row_errors, msg):
    if msg not in row_errors:
        row_errors.append(msg)

def form_specific_rules(row, errors):
    f = (row.get("form_type") or "").upper()
    if f == "1099-NEC":
        nec = row.get("nec_box1")
        if pd.isna(nec) or float(nec) <= 0:
            add_error(errors, "For 1099-NEC, NEC Box 1 must be > 0.")
        for c in ["misc_box1", "misc_box3", "misc_box7"]:
            v = row.get(c)
            if pd.notna(v) and float(v) != 0.0:
                add_error(errors, f"For 1099-NEC, {c} must be blank/0.")
    elif f == "1099-MISC":
        nec = row.get("nec_box1")
        if pd.notna(nec) and float(nec) != 0.0:
            add_error(errors, "For 1099-MISC, NEC Box 1 must be blank/0.")
        if all(
            pd.isna(row.get(c)) or float(row.get(c) or 0) == 0.0
            for c in ["misc_box1", "misc_box3", "misc_box7"]
        ):
            add_error(errors, "For 1099-MISC, at least one MISC box must be > 0.")
    else:
        add_error(errors, f"Unsupported form_type '{row.get('form_type')}'. Allowed: {sorted(ALLOWED_FORM_TYPES)}")

def validate_dataframe(df: pd.DataFrame):
    df = normalize_headers(df)
    text_like = [c for c in df.columns if c not in {"nec_box1","misc_box1","misc_box3","misc_box7","state_income","state_tax_withheld"}]
    clean_text(df, text_like)
    coerce_numeric(df, ["nec_box1","misc_box1","misc_box3","misc_box7","state_income","state_tax_withheld"])

    if "tin" in df.columns:
        df["tin"] = df["tin"].str.replace("-", "", regex=False).str.strip()
    if "payer_tin" in df.columns:
        df["payer_tin"] = df["payer_tin"].str.replace("-", "", regex=False).str.strip()

    errors = []
    required = ["recipient_name","tin","address1","city","state","zip","form_type","payer_name","payer_tin"]
    for idx, row in df.iterrows():
        row_errs = []
        for req in required:
            if req not in df.columns or pd.isna(row.get(req)) or str(row.get(req)).strip() == "":
                add_error(row_errs, f"Missing required field: {req}")
        if not TIN_RE.match(str(row.get("tin") or "")):
            add_error(row_errs, "Recipient TIN must be exactly 9 digits.")
        if not TIN_RE.match(str(row.get("payer_tin") or "")):
            add_error(row_errs, "Payer TIN must be exactly 9 digits.")
        st = (row.get("state") or "").upper()
        if st and st not in US_STATES:
            add_error(row_errs, f"State must be 2-letter US code; got '{st}'.")
        zp = str(row.get("zip") or "")
        if zp and not ZIP5_RE.match(zp):
            add_error(row_errs, "ZIP must be 12345 or 12345-6789.")
        form_specific_rules(row, row_errs)
        if row_errs:
            errors.append({"__row_index": idx, **row.to_dict(), "error_reason": " | ".join(row_errs)})
    err_df = pd.DataFrame(errors)
    ok_df = df.drop(index=err_df["__row_index"].values) if not err_df.empty else df.copy()
    return ok_df, err_df

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("excel_path", help="Path to Excel/CSV")
    ap.add_argument("--sheet", default=0, help="Sheet name or index (Excel only)")
    ap.add_argument("--out_ok", default="validated_1099s.csv")
    ap.add_argument("--out_err", default="error_log.csv")
    args = ap.parse_args()

    p = Path(args.excel_path)
    if not p.exists():
        print(f"File not found: {p}")
        sys.exit(1)

    if p.suffix.lower() == ".csv":
        df = pd.read_csv(p, dtype=str)
    else:
        df = pd.read_excel(p, sheet_name=args.sheet, dtype=str)

    ok_df, err_df = validate_dataframe(df)
    ok_df.to_csv(args.out_ok, index=False)
    err_df.to_csv(args.out_err, index=False)

    print(f"Total rows: {len(df)}  |  Valid: {len(ok_df)}  |  Invalid: {len(err_df)}")
    if len(err_df):
        print(f"See {args.out_err} for details.")

if __name__ == "__main__":
    main()
