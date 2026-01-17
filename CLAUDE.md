# Sherpa 1099 - CLAUDE.md

## Project Overview
**Name:** Sherpa 1099 (Slipstream 1099 e-Filing)
**Port:** 8002
**Stack:** Python, FastAPI, Supabase (PostgreSQL), IRS IRIS API
**GitHub:** https://github.com/klill6506/sherpa-1099
**Production URL:** https://sherpa-1099.onrender.com
**Status:** ✅ LIVE - Deployed to Render.com

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
**Last session:** 2026-01-17
**Working on:** IRS IRIS e-filing integration - COMPLETE
**Completed:**
- IRIS XML Generator (`src/iris_xml_generator.py`) - generates IRS-compliant XML per TY2025 v1.2 schema
- Updated IRIS Client (`src/iris_client.py`) - XML submission, status checking, acknowledgment retrieval
- XML Validator (`src/iris_xml_validator.py`) - validates against IRS schema and business rules
- E-Filing API Router (`api/routers/efile.py`) - endpoints for preview, validate, submit, status, acknowledgment
**Next steps:** Test with IRS ATS (Assurance Testing System) when credentials are active
**Blockers:** Need to configure transmitter environment variables (TRANSMITTER_TIN, TRANSMITTER_TCC, etc.)

## Key Files
| File | Purpose |
|------|---------|
| `api/main.py` | FastAPI backend entry point |
| `api/schemas.py` | Pydantic models for API |
| `api/routers/` | API route handlers |
| `api/routers/efile.py` | IRS e-filing endpoints |
| `src/supabase_client.py` | Database operations |
| `src/iris_auth.py` | IRIS OAuth authentication |
| `src/iris_client.py` | IRIS API client (XML submission) |
| `src/iris_xml_generator.py` | IRS-compliant XML generation |
| `src/iris_xml_validator.py` | XML schema validation |
| `src/encryption.py` | TIN encryption (Fernet) |
| `Dockerfile` | Production container config |
| `docker-compose.yml` | Local Docker testing |
| `IRIS_KEYS/` | IRS API credentials (DO NOT COMMIT) |
| `Schemas/` | IRS IRIS XSD schemas (TY2025 v1.2) |

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
- **Schema Version:** TY2025 v1.2 (iris-a2a-schema-and-business-rules-ty2025-v1.2)

### E-Filing API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/efile/preview-xml` | POST | Generate XML preview (download) |
| `/api/efile/validate-xml` | POST | Validate XML without submitting |
| `/api/efile/submit` | POST | Submit to IRS IRIS |
| `/api/efile/status` | POST | Check submission status |
| `/api/efile/acknowledgment` | POST | Get detailed acknowledgment |
| `/api/efile/transmitter-config` | GET | View transmitter config (masked) |

### Required Environment Variables for E-Filing
```
TRANSMITTER_TIN=000000000          # Your transmitter TIN (9 digits)
TRANSMITTER_TIN_TYPE=EIN           # EIN or SSN
TRANSMITTER_TCC=DG5BW              # Transmitter Control Code
TRANSMITTER_BUSINESS_NAME=...      # Your business name
TRANSMITTER_ADDRESS1=...           # Street address
TRANSMITTER_CITY=...
TRANSMITTER_STATE=..               # 2-letter state code
TRANSMITTER_ZIP=...
TRANSMITTER_CONTACT_NAME=...
TRANSMITTER_CONTACT_EMAIL=...
TRANSMITTER_CONTACT_PHONE=...      # 10 digits
IRS_SOFTWARE_ID=...                # IRS-assigned software ID
```

## Deployment
**Production:** Render.com (auto-deploys from GitHub main branch)
**Workflow:** Edit locally → `git push origin main` → Render auto-deploys (~2 min)

**Environment Variables (set in Render dashboard):**
- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
- `TIN_ENCRYPTION_KEY`
- `ALLOWED_ORIGINS=https://sherpa-1099.onrender.com`

## Dev Notes
- Ken's workflow: FastAPI/Supabase/Jinja2/Tailwind CDN
- Can modify files freely; ask before deleting
- Port 8002 reserved for this app
- TINs are encrypted at rest (Fernet) with last-4 stored for display

## Related Docs
- `README_IRIS.md` - IRIS API documentation
- `README_HOTFIX.txt` - Recent fixes
- `IRS API Client ID Application Summary.pdf` - Registration info
