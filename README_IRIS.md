# IRIS API Integration Setup

This document explains how to configure and use the IRIS API integration for 1099 e-filing.

## Overview

The IRIS (Information Returns Intake System) integration allows automated submission of 1099 forms to the IRS. This implementation supports:

- **ATS (Assurance Testing System)** - Test environment for development
- **JWT-based A2A (Application-to-Application) authentication**
- **Batch submission of validated 1099 forms**

## Prerequisites

Before using the IRIS integration, ensure you have:

1. **IRS API Client ID** - Obtained through IRS e-Services application
2. **Approved A2A TCC** (Transmitter Control Code) - Software developer authorization
3. **RSA Key Pair** - Registered with IRS via JWKS
4. **ATS Access** - Approved for testing environment

## Directory Structure

```
sherpa-1099/
├── src/
│   ├── __init__.py      # Module exports
│   ├── config.py        # Configuration management
│   ├── iris_auth.py     # JWT authentication
│   └── iris_client.py   # IRIS API client
├── IRIS_KEYS/
│   ├── iris_private.key # RSA private key (DO NOT COMMIT)
│   └── iris_cert.pem    # Certificate
├── .env                 # Environment variables (DO NOT COMMIT)
└── test_iris_auth.py    # Authentication test script
```

## Configuration

### Environment Variables

Create a `.env` file in the project root (or set these as system environment variables):

```bash
# Required
IRIS_CLIENT_ID=your-client-id-uuid

# Optional (with defaults)
IRIS_PRIVATE_KEY_PATH=./IRIS_KEYS/iris_private.key
IRIS_KEY_ID=iris-a2a-2025
IRIS_ENVIRONMENT=ATS

# Override endpoints (usually not needed)
# IRIS_AUTH_ENDPOINT=https://ats-api.irs.gov/oauth/token
# IRIS_API_BASE_URL=https://ats-api.irs.gov/iris/v1
```

### Private Key Setup

1. Your RSA private key should be in PEM format (PKCS8)
2. Place it at `IRIS_KEYS/iris_private.key` or specify path via `IRIS_PRIVATE_KEY_PATH`
3. **NEVER commit the private key to version control**

The public key (JWK format) must be registered with IRS through their JWKS registration process.

## Installation

Install the required dependencies:

```bash
pip install -r requirements.txt
```

New dependencies for IRIS integration:
- `requests` - HTTP client
- `PyJWT` - JWT token generation
- `python-dotenv` - Environment variable management
- `cryptography` - RSA key handling

## Usage

### Test Authentication

Run the authentication test script:

```bash
python test_iris_auth.py
```

This will:
1. Load configuration from environment
2. Generate a JWT client assertion
3. Request an access token from IRS
4. Report success or failure

### Using the API Client

```python
from src import load_config, IRISClient

# Load configuration
config = load_config()

# Create client
client = IRISClient(config)

# Test connection
client.test_connection()

# Submit a batch (after validation)
from pathlib import Path
result = client.submit_batch(
    csv_path=Path("validated_1099s.csv"),
    form_type="1099-NEC",
    tax_year=2025,
    is_test=True
)
print(f"Submission ID: {result.submission_id}")

# Check status
status = client.get_submission_status(result.submission_id)
print(f"Status: {status.status}")
```

## Authentication Flow

The IRIS API uses OAuth 2.0 with JWT client assertions:

```
┌─────────────────┐                        ┌─────────────────┐
│  Sherpa 1099    │                        │   IRS IRIS      │
│                 │                        │                 │
│  1. Create JWT  │                        │                 │
│     assertion   │                        │                 │
│     (signed w/  │                        │                 │
│     private key)│                        │                 │
│                 │                        │                 │
│  2. Send to     │ ──────────────────────>│  3. Validate    │
│     token       │   POST /oauth/token    │     JWT against │
│     endpoint    │   client_assertion=... │     JWKS        │
│                 │                        │                 │
│                 │ <──────────────────────│  4. Return      │
│  5. Use token   │   access_token=...     │     access      │
│     for API     │                        │     token       │
│     requests    │                        │                 │
└─────────────────┘                        └─────────────────┘
```

### JWT Claims

The client assertion JWT includes:

| Claim | Description |
|-------|-------------|
| `iss` | Issuer - Your Client ID |
| `sub` | Subject - Your Client ID |
| `aud` | Audience - Token endpoint URL |
| `exp` | Expiration - 5 minutes from now |
| `iat` | Issued at - Current time |
| `jti` | JWT ID - Unique identifier |

### JWT Headers

| Header | Description |
|--------|-------------|
| `alg` | Algorithm - RS256 |
| `typ` | Type - JWT |
| `kid` | Key ID - Matches JWKS registration |

## Troubleshooting

### Authentication Errors

**"Private key not found"**
- Verify `IRIS_PRIVATE_KEY_PATH` points to the correct file
- Ensure the key file exists and is readable

**"Token request failed with status 401"**
- Verify `IRIS_CLIENT_ID` is correct
- Ensure JWKS is properly registered with IRS
- Check that key ID (`kid`) matches your JWKS registration

**"Token request failed with status 400"**
- JWT claims may be incorrect
- Check token endpoint URL is correct

### Connection Errors

**"Connection refused" or timeout**
- Verify you have network access to IRS endpoints
- Check if VPN is required
- Ensure ATS environment is accessible

## Security Notes

1. **Never log tokens or private keys** - The code is designed to avoid this
2. **Keep private key secure** - Use file permissions, never commit to git
3. **Use environment variables** - Don't hardcode credentials
4. **ATS only** - This implementation is for testing; production requires additional review
5. **Token expiry** - Tokens are valid for 5 minutes; the client handles refresh automatically

## TODO Items

The following require verification against IRS documentation:

- [ ] Actual ATS OAuth token endpoint URL
- [ ] Actual ATS API base URL
- [ ] Required JWT claims (scope, additional claims)
- [ ] Submission endpoint path and request format
- [ ] Status check endpoint and response format
- [ ] Any required custom headers (TCC, etc.)

## References

- [IRS IRIS Information](https://www.irs.gov/iris)
- [IRS A2A Authentication](https://www.irs.gov/e-file-providers/a2a-authentication)
- [IRS e-Services](https://la1.www4.irs.gov/e-services/)
