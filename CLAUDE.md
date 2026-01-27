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
**Last session:** 2026-01-27
**Working on:** Bug fixes for filer management + UI polish

### What's Working:
- ATS certification testing complete (CF/SF test accepted)
- IRS e-filing submissions working
- Filing status tracking per filer (filer_filing_status table)
- Preparer assignment tracking
- Dark/Light mode toggle with localStorage persistence
- Winter-themed UI with mountain background (light mode)

### Bug Fixes This Session:

**1. Name 2 Import Error (FIXED)**
- Problem: Import tried to save `name_line_2` but filers table didn't have the column
- Fix: Added migration 008 to add `name_line_2` column to filers table
- Files: `database/008_add_filer_name_line_2.sql`

**2. Add Filer "Failed to Fetch" (FIXED)**
- Problem: Form field names didn't match API schema
  - Form sends: `name_line2`, `contact_phone`, `contact_email`, `is_active`
  - API expected: `name_line_2`, `phone`, `email`
- Fix: Added field name normalization in API router + updated Pydantic schemas
- Files: `api/schemas.py`, `api/routers/filers.py`, `templates/filers/form.html`

**3. Dashboard Not Showing All Filers (FIXED)**
- Problem: `filing_dashboard` view used INNER JOIN, excluding filers without status rows
- Fix: Changed to LEFT JOIN, added COALESCE for default 'NOT_FILED' status
- Files: `database/migrations/009_fix_filing_dashboard_view.sql`, `database/migrations/010_fix_filing_dashboard_v2.sql`

### UI Redesign Completed:

**Design Features:**
- Winter gradient background with external SVG mountains (`static/mountains.svg`)
- Readability scrim overlay for text clarity
- Dark mode: Charcoal gray theme (#2d3142 background)
- Frosted glass cards using `.glass` and `.glass-light` CSS classes
- Updated Yeti mascot with sunglasses in header
- Semantic colors: Blue=good, Green=start, Amber=pending, Red=errors

**Home Page (dashboard.html):**
- All filers table with action buttons (Transmit, Check Status, View Errors, Open)
- Summary cards showing filing status counts
- Search and status filter

**Filers Page (filers/list.html):**
- Same data as home page (unified view)

### Database Migrations to Run:
If starting fresh or issues persist, run these in order:
1. `database/008_add_filer_name_line_2.sql` - Adds name_line_2 to filers
2. `database/migrations/010_fix_filing_dashboard_v2.sql` - Fixes the view

### Files Modified This Session:
- `templates/base.html` - Dark/light mode, mountain background, charcoal theme
- `templates/filers/form.html` - Fixed field name mappings
- `api/schemas.py` - Added name_line_2, field aliases, extra='ignore'
- `api/routers/filers.py` - Added _normalize_filer_data() helper
- `api/main.py` - Enabled static file serving for mountains.svg
- `src/supabase_client.py` - Made tenant_id filter optional
- `static/mountains.svg` - New external mountain graphic

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

## File Operations

**Allowed without asking:**
- Create new files
- Modify existing files
- Run dev commands (pip install, uvicorn, pytest)
- Create/modify within the current project folder

**Ask before:**
- Deleting any files
- Bulk renames
- Operations affecting folders outside the project
- Changing port assignments
- Major architectural changes

---

