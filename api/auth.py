"""
Authentication middleware and dependencies.

Provides get_current_user dependency to protect routes.
Handles tenant membership and context.
"""

import os
from typing import Optional, List
from dataclasses import dataclass, field

from fastapi import Request, HTTPException, Depends
from fastapi.responses import RedirectResponse

from src.supabase_client import get_supabase_client

# Default tenant ID for The Tax Shelter (created in migration 004)
DEFAULT_TENANT_ID = "a0000000-0000-0000-0000-000000000001"

COOKIE_NAME = "sb-access-token"
REFRESH_COOKIE_NAME = "sb-refresh-token"


@dataclass
class TenantInfo:
    """Represents a tenant the user belongs to."""
    id: str
    name: str
    role: str  # admin, staff, readonly


@dataclass
class CurrentUser:
    """Represents the currently authenticated user."""
    id: str
    email: str
    name: str
    avatar_url: Optional[str] = None
    access_token: str = ""
    tenants: List[TenantInfo] = field(default_factory=list)
    current_tenant_id: Optional[str] = None

    @property
    def display_name(self) -> str:
        """Get display name, falling back to email."""
        return self.name or self.email.split("@")[0]

    @property
    def tenant_id(self) -> Optional[str]:
        """Get the current tenant ID (first tenant if not explicitly set)."""
        if self.current_tenant_id:
            return self.current_tenant_id
        if self.tenants:
            return self.tenants[0].id
        return None

    @property
    def is_admin(self) -> bool:
        """Check if user is admin of their current tenant."""
        tid = self.tenant_id
        if not tid:
            return False
        for t in self.tenants:
            if t.id == tid and t.role == 'admin':
                return True
        return False


def _get_user_tenants(user_id: str) -> List[TenantInfo]:
    """Get all tenants a user belongs to."""
    client = get_supabase_client()

    # Query tenant_members with tenant info
    result = client.table('tenant_members').select(
        'tenant_id, role, tenants(id, name)'
    ).eq('user_id', user_id).execute()

    tenants = []
    for row in result.data or []:
        tenant_data = row.get('tenants')
        if tenant_data:
            tenants.append(TenantInfo(
                id=tenant_data['id'],
                name=tenant_data['name'],
                role=row['role']
            ))

    return tenants


def _ensure_tenant_membership(user_id: str, email: str) -> List[TenantInfo]:
    """
    Ensure user has at least one tenant membership.

    For new users, automatically adds them to the default tenant.
    This keeps the app functional until proper tenant onboarding is built.
    """
    tenants = _get_user_tenants(user_id)

    if tenants:
        return tenants

    # New user - add to default tenant as staff
    client = get_supabase_client()
    try:
        client.table('tenant_members').insert({
            'tenant_id': DEFAULT_TENANT_ID,
            'user_id': user_id,
            'role': 'staff'
        }).execute()

        # Re-fetch to get full tenant info
        return _get_user_tenants(user_id)
    except Exception as e:
        # Log but don't fail - user can still use app without tenant
        print(f"Warning: Could not add user {email} to default tenant: {e}")
        return []


async def get_current_user(request: Request) -> CurrentUser:
    """
    FastAPI dependency to get the current authenticated user.

    Raises HTTPException 401 if not authenticated (for API routes).

    Usage:
        @router.get("/protected")
        async def protected_route(user: CurrentUser = Depends(get_current_user)):
            return {"message": f"Hello {user.name}"}
    """
    access_token = request.cookies.get(COOKIE_NAME)

    if not access_token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        client = get_supabase_client()
        user_response = client.auth.get_user(access_token)

        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        user = user_response.user
        email = user.email or ""

        # Get/ensure tenant membership
        tenants = _ensure_tenant_membership(user.id, email)

        return CurrentUser(
            id=user.id,
            email=email,
            name=user.user_metadata.get("full_name") or user.user_metadata.get("name") or "",
            avatar_url=user.user_metadata.get("avatar_url"),
            access_token=access_token,
            tenants=tenants,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication error: {e}")


async def get_optional_user(request: Request) -> Optional[CurrentUser]:
    """
    FastAPI dependency to optionally get the current user.

    Returns None if not authenticated (doesn't raise exception).

    Usage:
        @router.get("/maybe-protected")
        async def maybe_protected(user: Optional[CurrentUser] = Depends(get_optional_user)):
            if user:
                return {"message": f"Hello {user.name}"}
            return {"message": "Hello anonymous"}
    """
    try:
        return await get_current_user(request)
    except HTTPException:
        return None


def require_auth_redirect(request: Request) -> Optional[CurrentUser]:
    """
    Dependency for web pages that redirects to login if not authenticated.

    Unlike get_current_user (which raises 401), this returns a redirect response.
    Use this for HTML pages, not API endpoints.

    Note: This is used differently - check the return value in the route.
    """
    access_token = request.cookies.get(COOKIE_NAME)

    if not access_token:
        return None

    try:
        client = get_supabase_client()
        user_response = client.auth.get_user(access_token)

        if not user_response or not user_response.user:
            return None

        user = user_response.user
        email = user.email or ""

        # Get/ensure tenant membership
        tenants = _ensure_tenant_membership(user.id, email)

        return CurrentUser(
            id=user.id,
            email=email,
            name=user.user_metadata.get("full_name") or user.user_metadata.get("name") or "",
            avatar_url=user.user_metadata.get("avatar_url"),
            access_token=access_token,
            tenants=tenants,
        )
    except Exception:
        return None
