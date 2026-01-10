# Sherpa 1099 - CLAUDE.md

## Project Overview
**Name:** Sherpa 1099 (Slipstream 1099 e-Filing)
**Port:** 8002
**Stack:** Python, FastAPI, Supabase (PostgreSQL), IRS IRIS API
**GitHub:** https://github.com/klill6506/sherpa-1099
**Status:** 🔨 Active Development - Target completion: Tax Season 2025

## What This App Does
Converts client 1099 workbooks into IRS-compliant format and submits via IRIS e-file system.
- Imports horizontal Excel workbooks, normalizes to rows
- Validates TIN, state/ZIP, NEC/MISC rules
- Generates IRS-compliant XML for IRIS submission
- Handles 1099-NEC, MISC, DIV, INT, B, R, 1098

## Quick Start
```powershell
cd "T:\sherpa-1099"
.\.venv\Scripts\activate
python -m uvicorn api.main:app --port 8002 --host 0.0.0.0
```
Or double-click: `run_api.bat`

## Current State / What I Was Working On
<!-- UPDATE THIS SECTION BEFORE CLOSING CLAUDE CODE -->
**Last session:** 2026-01-09
**Working on:** Deployed to server (T:\sherpa-1099) for employee access
**Next steps:** IRS IRIS integration when credentials are ready
**Blockers:** Waiting on IRS

## Key Files
| File | Purpose |
|------|---------|
| `api/main.py` | FastAPI backend entry point |
| `api/schemas.py` | Pydantic models for API |
| `api/routers/` | API route handlers |
| `src/supabase_client.py` | Database operations |
| `src/iris_auth.py` | IRIS OAuth authentication |
| `src/iris_client.py` | IRIS API client |
| `app_streamlit_1099.py` | Main Streamlit UI (legacy) |
| `IRIS_KEYS/` | IRS API credentials (DO NOT COMMIT) |
| `Schemas/` | IRS XML schema files |

## Running the App
```powershell
# FastAPI Backend (port 8002) - SERVER DEPLOYMENT
cd "T:\sherpa-1099"
.\.venv\Scripts\activate
python -m uvicorn api.main:app --port 8002 --host 0.0.0.0
# Or double-click: run_api.bat
# API Docs: http://127.0.0.1:8002/docs
```

## IRS IRIS Integration
- **TCC:** DG5BW (Software Developer A2A)
- **Auth:** OAuth 2.0 with client certificate
- **Test endpoint:** https://la.www4.irs.gov/
- **Prod endpoint:** https://la.irs.gov/

## Dev Notes
- Ken's workflow: FastAPI/SQLite/Jinja2/Tailwind CDN
- Can modify files freely; ask before deleting
- Port 8002 reserved for this app
- Supabase integration explored but SQLite preferred for local

## Known Issues
- psycopg2-binary won't install on Python 3.14 (not needed for SQLite)

## Related Docs
- `README_IRIS.md` - IRIS API documentation
- `README_HOTFIX.txt` - Recent fixes
- `IRS API Client ID Application Summary.pdf` - Registration info
