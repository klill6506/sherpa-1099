# app_streamlit_1099.py - Slipstream 1099 Validator
import pandas as pd
import streamlit as st
from pathlib import Path
import tempfile

# Import validation functions from the shared module
from validate_1099s import (
    normalize_headers,
    validate_dataframe,
    extract_filer_info,
    SUPPORTED_FORM_TYPES,
)

APP_TITLE = "Slipstream 1099"
APP_TAGLINE = "Fast, accurate 1099 validation (The Tax Shelter)"

st.set_page_config(page_title=APP_TITLE, page_icon="", layout="centered")
st.title(f"{APP_TITLE}")
st.caption(APP_TAGLINE)

# ---------------- UI ----------------
st.subheader("Upload workbook (Excel) or a flat CSV")
uploaded = st.file_uploader("Upload Excel (.xlsx/.xls) or CSV", type=["xlsx", "xls", "csv"])

if uploaded:
    # Save uploaded file to temp location so we can use ExcelFile
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded.name).suffix) as tmp:
        tmp.write(uploaded.getvalue())
        tmp_path = Path(tmp.name)

    try:
        if uploaded.name.lower().endswith(".csv"):
            # CSV mode - single flat file
            df = pd.read_csv(tmp_path, dtype=str)
            df = normalize_headers(df)
            filer_info = {}

            st.info("CSV detected - processing as flat file.")
            st.subheader("Data preview")
            st.dataframe(df.head(60), use_container_width=True)

            # Validate
            ok_df, err_df = validate_dataframe(df, filer_info=filer_info)
            normalized = df

        else:
            # Excel workbook mode - use functions from validate_1099s
            xlsx = pd.ExcelFile(tmp_path)
            filer_info = extract_filer_info(xlsx)

            # Show filer info
            if filer_info.get("payer_name"):
                payer_tin_display = filer_info.get("payer_tin", "")[:4] + "..." if filer_info.get("payer_tin") else "N/A"
                st.success(f"**Payer:** {filer_info.get('payer_name')} (TIN: {payer_tin_display})")

            # Find available form sheets
            available_sheets = []
            for sheet in xlsx.sheet_names:
                sheet_upper = sheet.upper()
                if sheet_upper in ("1099-NEC", "1099NEC"):
                    available_sheets.append(sheet)
                elif sheet_upper in ("1099-MISC", "1099MISC"):
                    available_sheets.append(sheet)

            if not available_sheets:
                st.warning("No supported form sheets found (1099-NEC, 1099-MISC). Check your workbook.")
                st.stop()

            chosen = st.multiselect(
                "Select form sheets to process",
                options=available_sheets,
                default=available_sheets
            )

            if not chosen:
                st.warning("Select at least one sheet to process.")
                st.stop()

            # Process selected sheets
            all_valid = []
            all_errors = []

            for sheet_name in chosen:
                form_type = sheet_name.upper()
                if form_type in ("1099NEC", "1099-NEC"):
                    form_type = "1099-NEC"
                elif form_type in ("1099MISC", "1099-MISC"):
                    form_type = "1099-MISC"

                df = pd.read_excel(xlsx, sheet_name=sheet_name, dtype=str)
                if df.empty:
                    continue

                ok_df_sheet, err_df_sheet = validate_dataframe(df, form_type=form_type, filer_info=filer_info)

                if not ok_df_sheet.empty:
                    ok_df_sheet["__source_sheet"] = sheet_name
                    all_valid.append(ok_df_sheet)
                if not err_df_sheet.empty:
                    err_df_sheet["__source_sheet"] = sheet_name
                    all_errors.append(err_df_sheet)

            normalized = pd.concat(all_valid + all_errors, ignore_index=True) if (all_valid or all_errors) else pd.DataFrame()
            ok_df = pd.concat(all_valid, ignore_index=True) if all_valid else pd.DataFrame()
            err_df = pd.concat(all_errors, ignore_index=True) if all_errors else pd.DataFrame()

            # Show preview
            st.subheader("Normalized data (preview)")
            preview_df = ok_df if not ok_df.empty else normalized
            if not preview_df.empty:
                # Select key columns for display
                display_cols = ["tin", "recipient_name", "address1", "city", "state", "zip", "form_type"]
                if "nec_box1" in preview_df.columns:
                    display_cols.append("nec_box1")
                display_cols = [c for c in display_cols if c in preview_df.columns]
                st.dataframe(preview_df[display_cols].head(60), use_container_width=True)

        # Show validation results
        if "ok_df" in dir() or "ok_df" in locals():
            st.download_button(
                "Download normalized_1099s.csv",
                normalized.to_csv(index=False).encode(),
                "normalized_1099s.csv"
            )

            st.subheader("Validation")
            c1, c2 = st.columns(2)
            with c1:
                st.metric("Valid rows", len(ok_df))
            with c2:
                st.metric("Invalid rows", len(err_df))

            if len(err_df):
                with st.expander("View errors"):
                    error_display_cols = ["__row_index", "error_reason"]
                    if "__source_sheet" in err_df.columns:
                        error_display_cols.insert(1, "__source_sheet")
                    available_cols = [c for c in error_display_cols if c in err_df.columns]
                    st.dataframe(err_df[available_cols], use_container_width=True)
                st.download_button(
                    "Download Error Log CSV",
                    err_df.to_csv(index=False).encode(),
                    "error_log.csv"
                )

            if len(ok_df):
                st.download_button(
                    "Download validated_1099s.csv",
                    ok_df.to_csv(index=False).encode(),
                    "validated_1099s.csv"
                )

            st.info("Next: upload the validated CSV to IRIS (manual) or use the IRIS API integration.")
        else:
            st.warning("No rows detected. Check your file format.")

    finally:
        # Clean up temp file
        try:
            tmp_path.unlink()
        except:
            pass
else:
    st.info("Upload a file to begin.")
