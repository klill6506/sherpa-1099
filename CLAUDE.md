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
**Last session:** 2026-01-14
**Working on:** Successfully deployed to internet via Render.com
**Completed:** All 5 phases of internet deployment:
- Phase 0: Security headers (CSP, HSTS, etc.)
- Phase 1: Microsoft OAuth authentication via Supabase
- Phase 2: Multi-tenant isolation with RLS policies
- Phase 3: Rate limiting with SlowAPI
- Phase 4: TIN encryption (Fernet) - 80 records migrated
- Phase 5: Docker containerization & Render deployment
**Next steps:** IRS IRIS integration when credentials are approved
**Blockers:** Waiting on IRS IRIS access

## Key Files
| File | Purpose |
|------|---------|
| `api/main.py` | FastAPI backend entry point |
| `api/schemas.py` | Pydantic models for API |
| `api/routers/` | API route handlers |
| `src/supabase_client.py` | Database operations |
| `src/iris_auth.py` | IRIS OAuth authentication |
| `src/iris_client.py` | IRIS API client |
| `src/encryption.py` | TIN encryption (Fernet) |
| `Dockerfile` | Production container config |
| `docker-compose.yml` | Local Docker testing |
| `IRIS_KEYS/` | IRS API credentials (DO NOT COMMIT) |

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
