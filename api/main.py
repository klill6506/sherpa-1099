"""
Sherpa 1099 FastAPI Backend.

Main application entry point.
Run with: uvicorn api.main:app --reload --port 8002
"""

import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .routers import operating_years, filers, recipients, forms, dashboard, imports, web, pdf, auth, efile, email
from .auth import get_optional_user


def get_rate_limit_key(request: Request) -> str:
    """
    Get rate limit key based on user or IP.

    Authenticated users get per-user limits (more generous).
    Anonymous users get per-IP limits (stricter for login abuse prevention).
    """
    # For auth endpoints, always use IP-based limiting
    if request.url.path.startswith("/auth") or request.url.path == "/login":
        return get_remote_address(request)

    # For API endpoints, try to get user ID
    access_token = request.cookies.get("sb-access-token")
    if access_token:
        # Use token hash as key (avoids DB lookup in limiter)
        return f"user:{hash(access_token)}"

    return get_remote_address(request)


# Initialize rate limiter
limiter = Limiter(key_func=get_rate_limit_key)

# Logger for startup info
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    # === STARTUP ===
    logger.info("=" * 60)
    logger.info("Sherpa 1099 starting up...")

    # Log IRIS configuration (for debugging auth issues)
    try:
        # Import here to avoid circular imports
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
        from config import load_config
        config = load_config()
        logger.info(f"IRIS Environment: {config.environment}")
        logger.info(f"IRIS Auth Endpoint: {config.auth_endpoint}")
        logger.info(f"IRIS Intake Endpoint: {config.intake_endpoint}")
        logger.info(f"IRIS Status Endpoint: {config.status_endpoint}")
        logger.info(f"IRIS Client ID: {config.client_id[:8]}...{config.client_id[-4:] if len(config.client_id) > 12 else ''}")
        # Determine key source for logging
        key_source = "NOT CONFIGURED"
        if config.private_key_pem:
            if os.environ.get("IRIS_PRIVATE_KEY_B64"):
                key_source = "configured (base64)"
            else:
                key_source = "configured (PEM)"
        elif config.private_key_path:
            key_source = "configured (file)"
        logger.info(f"IRIS Private Key: {key_source}")
    except Exception as e:
        logger.warning(f"Could not load IRIS config on startup: {e}")

    logger.info("=" * 60)

    yield

    # === SHUTDOWN ===
    logger.info("Sherpa 1099 shutting down...")


app = FastAPI(
    title="Sherpa 1099 API",
    description="Backend API for 1099 e-filing with IRS IRIS",
    version="0.1.0",
    lifespan=lifespan,
)

# Attach limiter to app state (required by SlowAPI)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Allowed origins for CORS
# In production, set ALLOWED_ORIGINS env var to your domain(s)
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "").split(",") if os.getenv("ALLOWED_ORIGINS") else [
    "http://localhost:8002",
    "https://localhost:8002",
    "http://127.0.0.1:8002",
    "https://127.0.0.1:8002",
    "http://192.168.0.131:8002",
    "https://192.168.0.131:8002",
    "http://taxwise-server:8002",
    "https://taxwise-server:8002",
]

# CORS middleware for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # Enable HSTS once HTTPS is confirmed working in production
        # response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


app.add_middleware(SecurityHeadersMiddleware)


# =============================================================================
# RATE LIMITING CONFIGURATION
# =============================================================================
# Rate limits are applied via decorators on individual routes.
# See api/routers/auth.py for auth endpoint limits.
#
# Default limits (per IP for anonymous, per user for authenticated):
# - Auth endpoints: 5-10/minute (prevent brute force)
# - File uploads: 10/minute (prevent DoS)
# - API reads: 200/minute (generous for normal use)
# - API writes: 60/minute (moderate for data entry)
#
# To add rate limits to a route, use:
#   from slowapi import Limiter
#   from slowapi.util import get_remote_address
#   limiter = Limiter(key_func=get_remote_address)
#
#   @router.get("/endpoint")
#   @limiter.limit("100/minute")
#   async def my_endpoint(request: Request):
#       ...
# =============================================================================

# Static files (if needed)
# app.mount("/static", StaticFiles(directory="static"), name="static")

# Include API routers
app.include_router(operating_years.router, prefix="/api/operating-years", tags=["Operating Years"])
app.include_router(filers.router, prefix="/api/filers", tags=["Filers"])
app.include_router(recipients.router, prefix="/api/recipients", tags=["Recipients"])
app.include_router(forms.router, prefix="/api/forms", tags=["1099 Forms"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(imports.router, prefix="/api/imports", tags=["Imports"])
app.include_router(pdf.router, prefix="/api/pdf", tags=["PDF Generation"])
app.include_router(email.router, prefix="/api/email", tags=["Email"])
app.include_router(efile.router, prefix="/api/efile", tags=["IRS E-Filing"])

# Include Auth router (login, logout, callback)
app.include_router(auth.router, tags=["Authentication"])

# Include Web UI router (must be last to not override API routes)
app.include_router(web.router, tags=["Web UI"])


@app.get("/health")
async def health():
    """Health check for monitoring."""
    return {"status": "healthy"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Serve the favicon."""
    favicon_path = os.path.join(os.path.dirname(__file__), "..", "static", "favicon.ico")
    return FileResponse(favicon_path, media_type="image/x-icon")
