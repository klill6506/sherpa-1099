
# app_streamlit_1099.py — Slipstream supports BOTH layouts
import re
import pandas as pd
import streamlit as st

APP_TITLE = "Slipstream 1099"
APP_TAGLINE = "Fast, accurate 1099 validation (The Tax Shelter)"

st.set_page_config(page_title=APP_TITLE, page_icon="🧾", layout="centered")
st.title(f"🧾 {APP_TITLE}")
st.caption(APP_TAGLINE)

SUPPORTED_FORMS = ["1099-NEC","1099-MISC","1099-DIV","1099-INT","1099-B","1099-R","1098"]

def normalize_key(s: str) -> str:
    s = str(s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s

def canon(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())

FILER_MAP = {
    "Filer Name": "payer_name",
    "Payer Name": "payer_name",
    "Company Name": "payer_name",
    "Business Name": "payer_name",
    "Filer TIN": "payer_tin",
    "Payer TIN": "payer_tin",
    "FEIN": "payer_tin",
    "EIN": "payer_tin",
    "Federal EIN": "payer_tin",
    "Filer Address 1": "payer_address1",
    "Payer Address 1": "payer_address1",
    "Street Address": "payer_address1",
    "Address": "payer_address1",
    "Filer Address 2": "payer_address2",
    "Payer Address 2": "payer_address2",
    "City": "payer_city",
    "Filer City": "payer_city",
    "Payer City": "payer_city",
    "State": "payer_state",
    "Filer State": "payer_state",
    "Payer State": "payer_state",
    "ZIP": "payer_zip",
    "Zip": "payer_zip",
    "Zip Code": "payer_zip",
    "Filer ZIP": "payer_zip",
    "Payer ZIP": "payer_zip",
}

RECIPIENT_ALIASES = {
    "recipientname": "recipient_name",
    "payeename": "recipient_name",
    "name": "recipient_name",
    "firstlastname": "recipient_name",
    "recipienttin": "tin",
    "recipienttaxid": "tin",
    "ssn": "tin",
    "ein": "tin",
    "ssnein": "tin",
    "taxid": "tin",
    "tin": "tin",
    "address1": "address1",
    "address": "address1",
    "addressline1": "address1",
    "street": "address1",
    "address2": "address2",
    "addressline2": "address2",
    "city": "city",
    "town": "city",
    "state": "state",
    "stateprovince": "state",
    "zip": "zip",
    "zipcode": "zip",
    "postalcode": "zip",
    "country": "country",
    "accountnumber": "account_number",
    "acct": "account_number",
    "acctno": "account_number",
    "acctnumber": "account_number",
    "necbox1": "nec_box1",
    "nonemployeecomp": "nec_box1",
    "nonemployeecompensation": "nec_box1",
    "miscbox1": "misc_box1",
    "rentsbox1": "misc_box1",
    "rents": "misc_box1",
    "miscbox3": "misc_box3",
    "otherincomebox3": "misc_box3",
    "otherincome": "misc_box3",
    "miscbox7": "misc_box7",
    "box7nonemployeecompensationlegacy": "misc_box7",
    "dividends1a": "div_box1a",
    "qualifieddividends1b": "div_box1b",
    "capitalgaindist2a": "div_box2a",
    "taxexemptinterest8": "div_box8",
    "interestincome1": "int_box1",
    "federalincometaxwithheld4": "federal_tax_withheld",
    "grossproceeds1d": "b_box1d",
    "costorotherbasis1e": "b_box1e",
    "totaldistribution1": "r_box1",
    "taxableamount2a": "r_box2a",
    "mortgageinterestreceived1": "1098_box1",
    "points2": "1098_box2",
}

US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DC","DE","FL","GA","HI","IA","ID","IL","IN","KS","KY",
    "LA","MA","MD","ME","MI","MN","MO","MS","MT","NC","ND","NE","NH","NJ","NM","NV","NY","OH",
    "OK","OR","PA","RI","SC","SD","TN","TX","UT","VA","VT","WA","WI","WV","WY"
}
TIN_RE = re.compile(r"^\d{9}$")
ZIP5_RE = re.compile(r"^\d{5}$|^\d{5}-\d{4}$")

def load_filer_info(xl: pd.ExcelFile, sheet_name="Filer Information") -> dict:
    try:
        df = xl.parse(sheet_name, header=None)
    except Exception:
        return {}
    non_empty_cols = [i for i in range(min(5, df.shape[1])) if df.iloc[:, i].notna().any()]
    if len(non_empty_cols) < 2:
        return {}
    c_key, c_val = non_empty_cols[:2]
    slim = df.iloc[:, [c_key, c_val]].copy()
    slim.columns = ["key", "value"]
    slim["key"] = slim["key"].astype(str).map(normalize_key)
    slim = slim.dropna(subset=["key"])
    slim = slim[slim["value"].astype(str).str.strip() != ""]
    kv = dict(zip(slim["key"], slim["value"]))
    out = {}
    for k, v in kv.items():
        k2 = normalize_key(k)
        if k2 in FILER_MAP:
            out[FILER_MAP[k2]] = v
    return out

# ---------- Layout 1: Row-per-payee (headers across the top) ----------
def rows_mode_from_sheet(xl: pd.ExcelFile, sheet_name: str, mapped_filer: dict) -> pd.DataFrame:
    df = xl.parse(sheet_name, dtype=str)
    if df.empty:
        return pd.DataFrame()

    # map headers like "Recipient TIN" / "ZipCode" -> internal names
    headers = [canon(normalize_key(c)) for c in df.columns]
    mapped_cols = {}
    for i, h in enumerate(headers):
        tgt = RECIPIENT_ALIASES.get(h)
        if tgt:
            mapped_cols[df.columns[i]] = tgt

    # rename + attach metadata
    tidy = df.rename(columns=mapped_cols).copy()
    tidy["form_type"] = sheet_name
    for fk, fv in mapped_filer.items():
        tidy[fk] = fv

    # prevent "nan" strings showing up
    tidy = tidy.where(pd.notna(tidy), "")
    for c in tidy.columns:
        if tidy[c].dtype == object:
            tidy[c] = (
                tidy[c]
                .astype(str)
                .replace({"nan": "", "NaN": "", "None": ""})
                .str.strip()
            )

    return tidy


# ---------- Layout 2: Label-in-first-column + payees across ----------
def guess_label_col(df: pd.DataFrame, max_scan_cols=6) -> int:
    best_col = 0
    best_score = -1
    for c in range(min(max_scan_cols, df.shape[1])):
        series = df.iloc[:, c].dropna().astype(str).str.strip()
        if series.empty:
            continue
        tokens = series.head(120).tolist()
        score = 0
        for t in tokens:
            t_norm = normalize_key(t); t_can = canon(t_norm)
            if t_can in RECIPIENT_ALIASES:
                score += 3
            elif not re.fullmatch(r"[0-9\-\s\.,/()]+", t_norm) and len(t_norm) <= 40:
                score += 1
        if score > best_score:
            best_score = score; best_col = c
    return best_col

def columns_mode_from_sheet(xl: pd.ExcelFile, sheet_name: str, mapped_filer: dict) -> pd.DataFrame:
    df = xl.parse(sheet_name, header=None)
    df = df.dropna(how="all")
    if df.shape[1] < 2: return pd.DataFrame()
    label_col = guess_label_col(df)
    keys = df.iloc[:, label_col].astype(str).map(normalize_key)
    mask = keys.str.len().gt(0) & (~keys.str.lower().str.contains("instruction|example|leave blank"))
    df = df[mask].copy()
    keys = df.iloc[:, label_col].astype(str).map(normalize_key)
    payee_cols = [c for c in range(df.shape[1]) if c != label_col]
    rows = []
    for col_idx in payee_cols:
        col_vals = df.iloc[:, col_idx]
        if col_vals.dropna().astype(str).str.strip().eq("").all(): continue
        row_dict = {}
        for k_raw, v in zip(keys, col_vals):
            if pd.isna(v) or str(v).strip() == "": continue
            k_norm = normalize_key(k_raw)
            if re.fullmatch(r"[0-9\-\s]{5,}", k_norm): continue
            tgt = RECIPIENT_ALIASES.get(canon(k_norm))
            if tgt: row_dict[tgt] = v
            else:   row_dict[f"raw::{k_norm}"] = v
        if not row_dict: continue
        row_dict["form_type"] = sheet_name
        for fk, fv in mapped_filer.items(): row_dict[fk] = fv
        rows.append(row_dict)
    if not rows: return pd.DataFrame()
    tidy = pd.DataFrame(rows)

    # >>> prevent "nan" strings
    tidy = tidy.where(pd.notna(tidy), "")
    for c in tidy.columns:
        if tidy[c].dtype == object:
            tidy[c] = (
                tidy[c]
                .astype(str)
                .replace({"nan": "", "NaN": "", "None": ""})
                .str.strip()
            )

    st.caption(...)
    return tidy

# ---------- Validation ----------
US_STATES = set(US_STATES)  # ensure set
def _add_error(errs, msg):
    if msg not in errs: errs.append(msg)

def _form_specific_rules(row, errs):
    f = (row.get("form_type") or "").upper()
    if f == "1099-NEC":
        nec = row.get("nec_box1")
        try:
            nec_val = float(nec) if nec not in (None, "", "nan") else None
        except:
            nec_val = None
        if nec_val is None or nec_val <= 0:
            _add_error(errs, "For 1099-NEC, NEC Box 1 must be > 0.")
        for c in ["misc_box1","misc_box3","misc_box7"]:
            v = row.get(c)
            try:
                vval = float(v) if v not in (None, "", "nan") else 0.0
            except:
                vval = 0.0
            if vval != 0.0:
                _add_error(errs, f"For 1099-NEC, {c} must be blank/0.")
    elif f == "1099-MISC":
        nec = row.get("nec_box1")
        try:
            nec_val = float(nec) if nec not in (None, "", "nan") else 0.0
        except:
            nec_val = 0.0
        if nec_val != 0.0:
            _add_error(errs, "For 1099-MISC, NEC Box 1 must be blank/0.")
        if all((float(row.get(c) or 0) == 0.0) for c in ["misc_box1","misc_box3","misc_box7"]):
            _add_error(errs, "For 1099-MISC, at least one MISC box must be > 0.")

def validate_df(df: pd.DataFrame):
    # 1) Coerce likely money fields
    money_cols = [c for c in df.columns if any(x in c for x in ["box", "amount", "withheld"])]
    for c in money_cols:
        df[c] = (
            df[c].astype(str)
            .str.replace(",", "", regex=False)
            .str.strip()
            .replace({"": None, "nan": None})
        )
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # 2) Clean object cells so optional fields don't show "nan"
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = (
                df[col]
                .fillna("")
                .astype(str)
                .replace({"nan": "", "NaN": "", "None": ""})
                .str.strip()
            )

    # 3) Standardize TINs (remove ANY non-digits: hyphens, spaces, weird dashes, etc.)
    for c in ["tin", "payer_tin"]:
        if c in df.columns:
            df[c] = (
                df[c]
                .astype(str)
                .str.replace(r"\D", "", regex=True)  # keep only digits
                .str.strip()
            )

    errors = []
    required = ["recipient_name", "tin", "address1", "city", "state", "zip", "form_type"]

    for idx, row in df.iterrows():
        row_errs = []

        # Required checks
        for req in required:
            if req not in df.columns or str(row.get(req) or "").strip() == "":
                _add_error(row_errs, f"Missing required field: {req}")

        # Recipient TIN format
        if "tin" in df.columns and not TIN_RE.match(str(row.get("tin") or "")):
            _add_error(row_errs, "Recipient TIN must be exactly 9 digits.")

        # Payer TIN format (optional but, if present, must be 9 digits)
        if "payer_tin" in df.columns and str(row.get("payer_tin") or "").strip():
            if not TIN_RE.match(str(row.get("payer_tin") or "")):
                _add_error(row_errs, "Payer TIN must be exactly 9 digits.")  # <-- uses row_errs

        # State/ZIP
        stval = (row.get("state") or "").upper()
        if stval and stval not in US_STATES:
            _add_error(row_errs, f"State must be 2-letter US code; got '{stval}'.")
        zp = str(row.get("zip") or "")
        if zp and not ZIP5_RE.match(zp):
            _add_error(row_errs, "ZIP must be 12345 or 12345-6789.")

        # Form-specific rules
        _form_specific_rules(row, row_errs)

        if row_errs:
            errors.append({"__row_index": idx, **row.to_dict(), "error_reason": " | ".join(row_errs)})

    err_df = pd.DataFrame(errors)
    ok_df = df.drop(index=err_df["__row_index"].values) if not err_df.empty else df.copy()
    return ok_df, err_df


# ---------------- UI ----------------
st.subheader("Upload workbook (Excel) or a flat CSV")
uploaded = st.file_uploader("Upload Excel (.xlsx/.xls) or CSV", type=["xlsx","xls","csv"])

layout_choice = st.radio(
    "Workbook layout",
    ["Row per payee (headers across the top)", "Label column on the left (payees across)"],
    index=0
)

if uploaded:
    if uploaded.name.lower().endswith(".csv"):
        normalized = normalized.where(pd.notna(normalized), "")
        st.info("CSV detected — assuming it's already one row per payee.")
    else:
        xl = pd.ExcelFile(uploaded)
        mapped_filer = load_filer_info(xl)
        st.write(f"**Filer fields detected:** {', '.join(mapped_filer.keys()) if mapped_filer else '(none)'}")
        available_sheets = [s for s in xl.sheet_names if s in SUPPORTED_FORMS]
        chosen = st.multiselect("Select form sheets to process", options=available_sheets, default=available_sheets)
        frames = []
        for s in chosen:
            if layout_choice.startswith("Row per payee"):
                tdf = rows_mode_from_sheet(xl, s, mapped_filer)
            else:
                tdf = columns_mode_from_sheet(xl, s, mapped_filer)
            if not tdf.empty:
                frames.append(tdf.assign(_source_sheet=s))
        normalized = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

        st.subheader("Normalized data (preview)")
        st.dataframe(normalized.head(60), use_container_width=True)

    if 'normalized' in locals() and not normalized.empty:
        st.download_button("Download normalized_1099s.csv", normalized.to_csv(index=False).encode(), "normalized_1099s.csv")

        st.subheader("Validation")
        ok_df, err_df = validate_df(normalized.copy())

        c1, c2 = st.columns(2)
        with c1: st.metric("Valid rows", len(ok_df))
        with c2: st.metric("Invalid rows", len(err_df))

        if len(err_df):
            with st.expander("View errors"):
                st.dataframe(err_df[["__row_index","error_reason"]], use_container_width=True)
            st.download_button("Download Error Log CSV", err_df.to_csv(index=False).encode(), "error_log.csv")
        if len(ok_df):
            st.download_button("Download validated_1099s.csv", ok_df.to_csv(index=False).encode(), "validated_1099s.csv")

        st.info("Next: upload the validated CSV to IRIS (manual) or we can add the API later.")
    else:
        st.warning("No rows detected. If the sheet looks off, double-check the layout selection above.")
else:
    st.info("Upload a file to begin.")
