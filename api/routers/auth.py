"""
Authentication router for Microsoft OAuth via Supabase.

Handles login, logout, and OAuth callback.
"""

import os
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Request, Response, HTTPException, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.supabase_client import get_anon_client, get_supabase_client

router = APIRouter()

# Rate limiter for auth endpoints (stricter per-IP limits)
limiter = Limiter(key_func=get_remote_address)
templates = Jinja2Templates(directory="templates")

# Cookie settings
COOKIE_NAME = "sb-access-token"
REFRESH_COOKIE_NAME = "sb-refresh-token"
COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 days
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", None)

# Get Supabase URL for OAuth redirect
SUPABASE_URL = os.getenv("SUPABASE_URL", "")


def set_auth_cookies(response: Response, access_token: str, refresh_token: str):
    """Set httpOnly secure cookies for authentication."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=access_token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        domain=COOKIE_DOMAIN,
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        domain=COOKIE_DOMAIN,
    )


def clear_auth_cookies(response: Response):
    """Clear authentication cookies."""
    response.delete_cookie(key=COOKIE_NAME, domain=COOKIE_DOMAIN)
    response.delete_cookie(key=REFRESH_COOKIE_NAME, domain=COOKIE_DOMAIN)


@router.get("/login")
@limiter.limit("10/minute")  # 10 login page views per minute per IP
async def login_page(request: Request):
    """Display login page with Microsoft sign-in button."""
    # Check if already logged in
    access_token = request.cookies.get(COOKIE_NAME)
    if access_token:
        # Verify token is still valid
        try:
            client = get_supabase_client()
            user = client.auth.get_user(access_token)
            if user:
                return RedirectResponse(url="/", status_code=302)
        except Exception:
            pass  # Token invalid, show login page

    return templates.TemplateResponse("auth/login.html", {
        "request": request,
    })


@router.get("/auth/microsoft")
@limiter.limit("5/minute")  # 5 OAuth initiations per minute per IP (prevent abuse)
async def auth_microsoft(request: Request):
    """Initiate Microsoft OAuth flow via Supabase."""
    client = get_anon_client()

    # Get the redirect URL back to our app after Supabase auth
    # This should be our /auth/callback endpoint
    redirect_to = str(request.url_for("auth_callback"))

    # Get OAuth URL from Supabase
    # Request email scope explicitly for Azure/Microsoft
    response = client.auth.sign_in_with_oauth({
        "provider": "azure",
        "options": {
            "redirect_to": redirect_to,
            "scopes": "email openid profile User.Read",
        }
    })

    if response and response.url:
        return RedirectResponse(url=response.url, status_code=302)

    raise HTTPException(status_code=500, detail="Failed to initiate OAuth flow")


@router.get("/auth/callback")
@limiter.limit("10/minute")  # 10 callbacks per minute per IP
async def auth_callback(request: Request):
    """Handle OAuth callback from Supabase."""
    # Get the access token and refresh token from query params
    # Supabase sends these after successful OAuth
    access_token = request.query_params.get("access_token")
    refresh_token = request.query_params.get("refresh_token")

    # Sometimes Supabase sends a code instead that needs to be exchanged
    code = request.query_params.get("code")

    if code and not access_token:
        # Exchange code for session
        try:
            client = get_anon_client()
            response = client.auth.exchange_code_for_session({"auth_code": code})
            if response and response.session:
                access_token = response.session.access_token
                refresh_token = response.session.refresh_token
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to exchange code: {e}")

    if not access_token:
        # Check for error
        error = request.query_params.get("error")
        error_description = request.query_params.get("error_description", "Unknown error")
        if error:
            raise HTTPException(status_code=400, detail=f"OAuth error: {error_description}")
        raise HTTPException(status_code=400, detail="No access token received")

    # Set cookies and redirect to home
    response = RedirectResponse(url="/", status_code=302)
    set_auth_cookies(response, access_token, refresh_token or "")

    return response


@router.get("/logout")
async def logout(request: Request):
    """Log out the user."""
    # Clear cookies
    response = RedirectResponse(url="/login", status_code=302)
    clear_auth_cookies(response)

    # Optionally sign out from Supabase (invalidates refresh token)
    access_token = request.cookies.get(COOKIE_NAME)
    if access_token:
        try:
            client = get_supabase_client()
            client.auth.sign_out()
        except Exception:
            pass  # Ignore errors during sign out

    return response


@router.get("/auth/me")
@limiter.limit("30/minute")  # 30 user info requests per minute per IP
async def get_current_user_info(request: Request):
    """Get current user info (for debugging/display)."""
    access_token = request.cookies.get(COOKIE_NAME)

    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        client = get_supabase_client()
        user_response = client.auth.get_user(access_token)

        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid token")

        user = user_response.user
        return {
            "id": user.id,
            "email": user.email,
            "name": user.user_metadata.get("full_name") or user.user_metadata.get("name") or user.email,
            "avatar": user.user_metadata.get("avatar_url"),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication error: {e}")
