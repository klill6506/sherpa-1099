# Sherpa 1099 - Internet Deployment Plan

**Created:** 2026-01-13
**Status:** In Progress - Phase 0 complete (CORS + security headers)

## Overview
Move sherpa-1099 from LAN-only to commercial multi-tenant SaaS for selling to clients.

## Key Design Decisions

### Multi-Tenant Architecture
Instead of simple `created_by = auth.uid()` (user-only silos), use proper tenant isolation:
- **Tenants** = client companies (your customers)
- **Users** = people who log in (can belong to a tenant)
- **Roles** = admin, staff, client (controls what they can do)

This allows:
- Multiple employees working the same client file
- Future: giving clients read-only access to their own data
- No accidental "personal silos"

### Authentication Approach
- **Microsoft OAuth** via Supabase Auth (employees have M365 accounts)
- **httpOnly secure cookies** for web UI (not localStorage tokens)
- Can add email/password later when selling to external clients

---

## Database Schema Additions

### New Tables
```sql
-- Tenants (your customers/client companies)
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Tenant membership with roles
CREATE TABLE tenant_members (
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('admin', 'staff', 'client')),
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id)
);
```

### Modify Existing Tables
Add `tenant_id` to: `filers`, `recipients`, `forms_1099`, `submissions`, `import_batches`

### RLS Policy Pattern
```sql
-- Users can access records belonging to tenants they're members of
CREATE POLICY "Tenant isolation" ON filers
FOR ALL TO authenticated
USING (
    tenant_id IN (
        SELECT tenant_id FROM tenant_members
        WHERE user_id = auth.uid()
    )
);
```

---

## TIN Encryption Strategy

Store three values for each TIN:
- `tin_encrypted` - Fernet-encrypted full TIN
- `tin_last4` - Plain text last 4 digits (for display: XXX-XX-1234)
- `tin_hash` - SHA-256 hash (for duplicate detection without decryption)

Key rotation: version the encryption key, store key version with encrypted data.

---

## Implementation Phases

### Phase 0: Immediate Security ✅ COMPLETE
- [x] CORS lockdown (allow LAN + future domain)
- [x] Security headers (X-Content-Type-Options, X-Frame-Options, etc.)
- [ ] Upload size limits (deferred)

### Phase 1: Authentication ✅ COMPLETE
- [x] Set up Microsoft OAuth in Azure Portal
- [x] Configure Supabase Azure provider
- [x] Create auth middleware (api/auth.py)
- [x] httpOnly cookie sessions
- [x] Login page with Microsoft sign-in button
- [x] `get_current_user` dependency on all routes
- [x] Test authentication flow
- [ ] CSRF protection (deferred - needed for forms)

**Azure Portal Setup:**
1. Azure Portal → Azure Active Directory → App registrations → New registration
2. Name: "Sherpa 1099"
3. Supported account types: "Accounts in this organizational directory only"
4. Redirect URI: `https://tmqypsbmswishqkngbrl.supabase.co/auth/v1/callback`
5. Certificates & secrets → New client secret → Copy value
6. Note: Application (client) ID, Directory (tenant) ID

**Supabase Setup:**
1. Authentication → Providers → Azure (Microsoft)
2. Enable and enter Client ID, Client Secret, Tenant ID

### Phase 2: Tenant Isolation ✅ COMPLETE
- [x] Create `tenants` and `tenant_members` tables
- [x] Add `tenant_id` to all business tables
- [x] Migration to assign existing data to a default tenant
- [x] RLS policies based on tenant membership
- [x] Role-based access (admin vs staff vs readonly)
- [x] Auto-add new users to default tenant

**Migration files created:**
- `database/migrations/004_tenants.sql` - Creates tenant tables, adds tenant_id columns
- `database/migrations/005_tenant_rls.sql` - RLS policies for tenant isolation

**To apply:** Run both SQL files in Supabase SQL Editor in order.

### Phase 3: Rate Limiting ✅ COMPLETE
- [x] SlowAPI integration (added to requirements.txt)
- [x] Per-IP limits for login (prevent credential stuffing)
  - /login: 10/minute
  - /auth/microsoft: 5/minute
  - /auth/callback: 10/minute
  - /auth/me: 30/minute
- [x] Per-user limits for API (file uploads)
  - /api/imports/*: 10/minute per IP
- [x] Server venv setup (no longer depends on user's local Python)
- [x] Favicon added (yeti icon)

**Files modified:**
- `requirements.txt` - Added slowapi>=0.1.9, pymupdf>=1.26.0
- `api/main.py` - Rate limiter setup, favicon route
- `api/routers/auth.py` - Rate limits on all auth endpoints
- `api/routers/imports.py` - Rate limits on file upload endpoints
- `run_api.bat` - Uses server venv (C:\sherpa-1099\.venv)
- `templates/base.html` - Added favicon link tag
- `static/favicon.ico` - Yeti icon

### Phase 4: TIN Protection ✅ COMPLETE
- [x] `src/encryption.py` with Fernet - CREATED
- [x] Database migration `006_tin_encryption.sql` - APPLIED
- [x] Migration script `scripts/migrate_tins.py` - RAN
- [x] TIN_ENCRYPTION_KEY added to .env
- [x] All 80 records encrypted (3 filers, 77 recipients)
- [x] Decryption verified working

**Files created:**
- `src/encryption.py` - Encryption module with Fernet
- `database/migrations/006_tin_encryption.sql` - Adds encrypted columns
- `scripts/migrate_tins.py` - Migrates existing plain-text TINs

**Database now has both columns (transitional):**
- `tin` - Original plain text (app still uses this)
- `tin_encrypted` - Fernet encrypted value
- `tin_last4` - Last 4 digits for display (XXX-XX-1234)
- `tin_hash` - SHA-256 for duplicate detection

**Future cleanup (after verifying everything works):**
```sql
ALTER TABLE filers DROP COLUMN tin;
ALTER TABLE recipients DROP COLUMN tin;
```

### Phase 5: Deployment - READY TO DEPLOY
- [x] Dockerfile created
- [x] .dockerignore created
- [x] docker-compose.yml for local testing
- [x] railway.toml for Railway.app
- [x] Deployment guide created (`docs/DEPLOYMENT_GUIDE.md`)
- [ ] Push to GitHub
- [ ] Deploy to Railway.app
- [ ] Configure environment variables
- [ ] Update auth redirect URLs
- [ ] Test production deployment

**Files created:**
- `Dockerfile` - Production container
- `.dockerignore` - Excludes secrets and dev files
- `docker-compose.yml` - Local testing
- `railway.toml` - Railway.app config
- `docs/DEPLOYMENT_GUIDE.md` - Step-by-step instructions

---

## Two Supabase Clients

1. **User-scoped client** - passes user JWT, RLS enforced
   - Used for all normal API requests

2. **Admin client** - service role key, bypasses RLS
   - Only for: migrations, admin tools, scheduled jobs
   - Never exposed to user requests

---

## Files to Create/Modify

### New Files
- `api/auth.py` - Auth middleware, cookie handling
- `api/routers/auth.py` - Auth callback endpoints
- `src/encryption.py` - TIN encryption with versioning
- `database/004_tenants.sql` - Tenant tables
- `database/005_tenant_columns.sql` - Add tenant_id to existing tables
- `database/006_tenant_rls.sql` - New RLS policies
- `templates/auth/login.html` - Microsoft sign-in button
- `Dockerfile`

### Modified Files
- `api/main.py` - CORS ✅, security headers ✅, rate limiting
- `api/routers/*.py` - Add auth dependency
- `src/supabase_client.py` - User-scoped + admin clients
- `requirements.txt` - Add slowapi

---

## Environment Variables (New)

```env
ENCRYPTION_KEY=<generate-fernet-key>
ALLOWED_ORIGINS=https://yourdomain.com
AZURE_CLIENT_ID=<from-azure-portal>
AZURE_CLIENT_SECRET=<from-azure-portal>
AZURE_TENANT_ID=<from-azure-portal>
```

---

## Hosting Decision

**Recommended: Railway.app**
- Simplest deployment (connect GitHub, done)
- Automatic SSL certificates (Let's Encrypt)
- ~$10-20/month for this app size
- Easy environment variable management
- Auto-deploys on git push

**Required**: Set up staging environment first, deploy to prod after testing.

---

## Resume Instructions

To continue this work:
1. Open this file: `T:\sherpa-1099\docs\INTERNET_DEPLOYMENT_PLAN.md`
2. Check the phases above to see what's complete
3. **Next step: Phase 4 (TIN Protection) or Phase 5 (Deployment)**

**Completed so far:**
- Phase 0: Security headers ✅
- Phase 1: Authentication ✅
- Phase 2: Tenant Isolation ✅
- Phase 3: Rate Limiting ✅

**To install new dependencies:**
```powershell
pip install slowapi
```
