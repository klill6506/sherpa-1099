
Slipstream 1099 — v2 (Workbook Converter + Validator)
====================================================

1) Copy all files into your "Slipstream 1099" folder:
   - app_streamlit_1099.py
   - run_1099_app.bat
   - requirements.txt
   - README_START_HERE.txt

2) Double-click run_1099_app.bat
   - Installs Streamlit/pandas/openpyxl if needed
   - Opens the app in your browser

3) Upload your workbook (.xlsx), select forms (NEC/MISC/DIV/INT/B/R/1098)
   - App converts horizontal columns into rows
   - Shows a preview
   - Runs validation (TIN, state/ZIP, NEC/MISC rules)

4) Download:
   - normalized_1099s.csv (tidy table)
   - validated_1099s.csv (ready for IRS conversion)
