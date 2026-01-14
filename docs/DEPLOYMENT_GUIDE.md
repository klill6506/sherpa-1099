# Sherpa 1099 - Deployment Guide

## Option 1: Railway.app (Recommended)

Railway is the simplest option - connect your GitHub repo and it auto-deploys.

### Step 1: Push to GitHub

```bash
git add .
git commit -m "Add deployment configuration"
git push origin main
```

### Step 2: Create Railway Account

1. Go to https://railway.app
2. Sign up with GitHub

### Step 3: Create New Project

1. Click "New Project"
2. Select "Deploy from GitHub repo"
3. Select your `sherpa-1099` repository
4. Railway will detect the Dockerfile automatically

### Step 4: Add Environment Variables

In Railway dashboard → Your project → Variables, add:

**Required:**
```
SUPABASE_URL=https://tmqypsbmswishqkngbrl.supabase.co
SUPABASE_ANON_KEY=<your-anon-key>
SUPABASE_SERVICE_ROLE_KEY=<your-service-role-key>
TIN_ENCRYPTION_KEY=<your-encryption-key>
ALLOWED_ORIGINS=https://your-railway-domain.railway.app
```

**Optional (for IRS IRIS):**
```
IRIS_CLIENT_ID=<your-iris-client-id>
IRIS_KEY_ID=<your-key-id>
IRIS_ENV=ATS
IRIS_AUTH_ENDPOINT=https://api.alt.www4.irs.gov/auth/oauth/v2/token
IRIS_API_BASE_URL=https://api.alt.www4.irs.gov
```

### Step 5: Generate Domain

1. Go to Settings → Domains
2. Click "Generate Domain" for a free `*.railway.app` domain
3. Or add your own custom domain

### Step 6: Update Supabase Auth Callback

After getting your Railway domain, update Supabase:
1. Go to Supabase Dashboard → Authentication → URL Configuration
2. Add your Railway domain to "Redirect URLs":
   - `https://your-app.railway.app/auth/callback`

### Step 7: Update Azure AD Redirect URI

1. Go to Azure Portal → App Registrations → Sherpa 1099
2. Add redirect URI: `https://tmqypsbmswishqkngbrl.supabase.co/auth/v1/callback`
   (This should already be set from Phase 1)

---

## Option 2: Render.com

Similar to Railway but with a free tier.

### render.yaml (create this file):
```yaml
services:
  - type: web
    name: sherpa-1099
    env: docker
    dockerfilePath: ./Dockerfile
    healthCheckPath: /health
    envVars:
      - key: SUPABASE_URL
        sync: false
      - key: SUPABASE_ANON_KEY
        sync: false
      - key: SUPABASE_SERVICE_ROLE_KEY
        sync: false
      - key: TIN_ENCRYPTION_KEY
        sync: false
```

---

## Option 3: Docker on VPS

For self-hosted deployment on a VPS (DigitalOcean, Linode, etc.)

### Prerequisites
- Docker and Docker Compose installed
- Domain pointing to your server
- SSL certificate (use Caddy or nginx as reverse proxy)

### Deploy

```bash
# Clone repo
git clone https://github.com/klill6506/sherpa-1099.git
cd sherpa-1099

# Create .env file with your secrets
cp .env.example .env
nano .env  # Edit with your values

# Build and start
docker-compose up -d --build

# Check logs
docker-compose logs -f
```

### Reverse Proxy with Caddy (for SSL)

Create `Caddyfile`:
```
yourdomain.com {
    reverse_proxy localhost:8002
}
```

Run Caddy:
```bash
caddy run
```

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_ANON_KEY` | Yes | Supabase anon/public key |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | Supabase service role key |
| `TIN_ENCRYPTION_KEY` | Yes | Fernet key for TIN encryption |
| `ALLOWED_ORIGINS` | Yes | CORS allowed origins (comma-separated) |
| `IRIS_CLIENT_ID` | No | IRS IRIS API client ID |
| `IRIS_KEY_ID` | No | IRS IRIS key ID |
| `IRIS_JWK` | No | IRS IRIS JWK (JSON string) |
| `IRIS_ENV` | No | IRS environment (ATS or PROD) |
| `IRIS_AUTH_ENDPOINT` | No | IRS OAuth endpoint |
| `IRIS_API_BASE_URL` | No | IRS API base URL |

---

## Post-Deployment Checklist

- [ ] App loads at your domain
- [ ] Microsoft login works
- [ ] Dashboard shows data
- [ ] Can import a test file
- [ ] Can generate PDF
- [ ] Health check passes (`/health` returns 200)

---

## Troubleshooting

### App won't start
- Check logs: `docker-compose logs` or Railway logs
- Verify all required env vars are set
- Check Supabase connection

### Auth not working
- Verify Supabase redirect URLs include your domain
- Check Azure AD redirect URI matches Supabase callback
- Ensure ALLOWED_ORIGINS includes your domain

### Database errors
- Verify SUPABASE_SERVICE_ROLE_KEY is correct
- Check RLS policies if getting permission errors
