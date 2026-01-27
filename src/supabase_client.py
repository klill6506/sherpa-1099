"""
Supabase client for Sherpa 1099.

Provides database access through the Supabase REST API.

IMPORTANT: This module uses the SERVICE ROLE key for backend operations.
This key bypasses Row Level Security and should NEVER be exposed to the frontend.
"""

import os
from typing import Optional, Any, Dict
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

try:
    from supabase import create_client, Client
except ImportError:
    raise ImportError(
        "supabase-py is required. Install with: pip install supabase"
    )


@dataclass(frozen=True)
class SupabaseConfig:
    """Configuration for Supabase connection."""
    url: str
    anon_key: str
    service_role_key: str

    @classmethod
    def from_env(cls) -> "SupabaseConfig":
        """Load configuration from environment variables."""
        url = os.getenv("SUPABASE_URL")
        anon_key = os.getenv("SUPABASE_ANON_KEY")
        service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

        if not url:
            raise ValueError("SUPABASE_URL environment variable is required")
        if not anon_key:
            raise ValueError("SUPABASE_ANON_KEY environment variable is required")
        if not service_role_key:
            raise ValueError("SUPABASE_SERVICE_ROLE_KEY environment variable is required")

        return cls(url=url, anon_key=anon_key, service_role_key=service_role_key)


# Global client instances (lazy initialization)
_service_client: Optional[Client] = None
_anon_client: Optional[Client] = None


def get_supabase_client() -> Client:
    """
    Get the Supabase client with SERVICE ROLE privileges.

    This client bypasses RLS and should only be used in backend code.
    NEVER expose this client or its key to the frontend.
    """
    global _service_client

    if _service_client is None:
        config = SupabaseConfig.from_env()
        _service_client = create_client(config.url, config.service_role_key)

    return _service_client


def get_anon_client() -> Client:
    """
    Get the Supabase client with ANON (public) privileges.

    This client respects RLS policies and is safe for auth operations.
    Used primarily for user authentication flows.
    """
    global _anon_client

    if _anon_client is None:
        config = SupabaseConfig.from_env()
        _anon_client = create_client(config.url, config.anon_key)

    return _anon_client


def reset_clients() -> None:
    """Reset all clients (useful for testing)."""
    global _service_client, _anon_client
    _service_client = None
    _anon_client = None


# =============================================================================
# OPERATING YEARS
# =============================================================================

def get_operating_years():
    """Get all operating years, ordered by tax year descending."""
    client = get_supabase_client()
    response = client.table("operating_years").select("*").order("tax_year", desc=True).execute()
    return response.data


def get_current_operating_year():
    """Get the current operating year."""
    client = get_supabase_client()
    response = client.table("operating_years").select("*").eq("is_current", True).single().execute()
    return response.data


def set_current_operating_year(year_id: str):
    """Set the current operating year (unsets any existing current year)."""
    client = get_supabase_client()

    # First, unset all current flags
    client.table("operating_years").update({"is_current": False}).eq("is_current", True).execute()

    # Then set the new current year
    response = client.table("operating_years").update({"is_current": True}).eq("id", year_id).execute()
    return response.data


# =============================================================================
# FILERS
# =============================================================================

def get_filers(active_only: bool = True):
    """Get all filers."""
    client = get_supabase_client()
    query = client.table("filers").select("*").order("name")

    if active_only:
        query = query.eq("is_active", True)

    response = query.execute()
    return response.data


def get_filer(filer_id: str):
    """Get a single filer by ID."""
    client = get_supabase_client()
    response = client.table("filers").select("*").eq("id", filer_id).single().execute()
    return response.data


def create_filer(filer_data: dict):
    """Create a new filer."""
    client = get_supabase_client()
    response = client.table("filers").insert(filer_data).execute()
    return response.data[0] if response.data else None


def update_filer(filer_id: str, filer_data: dict):
    """Update an existing filer."""
    client = get_supabase_client()
    response = client.table("filers").update(filer_data).eq("id", filer_id).execute()
    return response.data[0] if response.data else None


def delete_filer(filer_id: str):
    """Soft-delete a filer (sets is_active to false)."""
    client = get_supabase_client()
    response = client.table("filers").update({"is_active": False}).eq("id", filer_id).execute()
    return response.data[0] if response.data else None


def hard_delete_filer(filer_id: str):
    """
    Permanently delete a filer and all associated data.

    Deletes in order: forms_1099, recipients, filer_filing_status, then filer.
    Returns True if successful.
    """
    client = get_supabase_client()

    # Delete forms first (they reference recipients)
    client.table("forms_1099").delete().eq("filer_id", filer_id).execute()

    # Delete recipients
    client.table("recipients").delete().eq("filer_id", filer_id).execute()

    # Delete filing status records
    client.table("filer_filing_status").delete().eq("filer_id", filer_id).execute()

    # Finally delete the filer
    response = client.table("filers").delete().eq("id", filer_id).execute()
    return len(response.data) > 0 if response.data else False


# =============================================================================
# RECIPIENTS
# =============================================================================

def get_recipients(filer_id: str, active_only: bool = True):
    """Get all recipients for a filer."""
    client = get_supabase_client()
    query = client.table("recipients").select("*").eq("filer_id", filer_id).order("name")

    if active_only:
        query = query.eq("is_active", True)

    response = query.execute()
    return response.data


def get_recipient(recipient_id: str):
    """Get a single recipient by ID."""
    client = get_supabase_client()
    response = client.table("recipients").select("*").eq("id", recipient_id).single().execute()
    return response.data


def create_recipient(recipient_data: dict):
    """Create a new recipient."""
    client = get_supabase_client()
    response = client.table("recipients").insert(recipient_data).execute()
    return response.data[0] if response.data else None


def update_recipient(recipient_id: str, recipient_data: dict):
    """Update an existing recipient."""
    client = get_supabase_client()
    response = client.table("recipients").update(recipient_data).eq("id", recipient_id).execute()
    return response.data[0] if response.data else None


def update_recipient_tin_status(recipient_id: str, status: str, match_code: Optional[str] = None):
    """Update the TIN matching status for a recipient."""
    from datetime import datetime

    client = get_supabase_client()
    update_data = {
        "tin_status": status,
        "tin_checked_at": datetime.utcnow().isoformat(),
    }
    if match_code:
        update_data["tin_match_code"] = match_code

    response = client.table("recipients").update(update_data).eq("id", recipient_id).execute()
    return response.data[0] if response.data else None


# =============================================================================
# FORMS 1099
# =============================================================================

def get_forms_1099(filer_id: str, operating_year_id: str):
    """Get all 1099 forms for a filer and year."""
    client = get_supabase_client()
    response = (
        client.table("forms_1099")
        .select("*, recipients(name, tin)")
        .eq("filer_id", filer_id)
        .eq("operating_year_id", operating_year_id)
        .order("created_at")
        .execute()
    )
    return response.data


def get_form_1099(form_id: str):
    """Get a single form by ID."""
    client = get_supabase_client()
    response = (
        client.table("forms_1099")
        .select("*, recipients(*), filers(*)")
        .eq("id", form_id)
        .single()
        .execute()
    )
    return response.data


def create_form_1099(form_data: dict):
    """Create a new 1099 form."""
    client = get_supabase_client()
    response = client.table("forms_1099").insert(form_data).execute()
    return response.data[0] if response.data else None


def update_form_1099(form_id: str, form_data: dict):
    """Update an existing 1099 form."""
    client = get_supabase_client()
    response = client.table("forms_1099").update(form_data).eq("id", form_id).execute()
    return response.data[0] if response.data else None


def delete_form_1099(form_id: str):
    """Delete a 1099 form (only if not submitted)."""
    client = get_supabase_client()
    # Only delete if status is draft or validation_error
    response = (
        client.table("forms_1099")
        .delete()
        .eq("id", form_id)
        .in_("status", ["draft", "validation_error"])
        .execute()
    )
    return len(response.data) > 0 if response.data else False


# =============================================================================
# DASHBOARD / VIEWS
# =============================================================================

def get_filer_status_summary(operating_year_id: Optional[str] = None):
    """Get filer status summary for the dashboard."""
    client = get_supabase_client()
    query = client.table("filer_status_summary").select("*")

    if operating_year_id:
        query = query.eq("operating_year_id", operating_year_id)

    response = query.execute()
    return response.data


def get_dashboard_stats(operating_year_id: Optional[str] = None):
    """Get dashboard statistics."""
    client = get_supabase_client()

    if operating_year_id:
        response = client.rpc("get_dashboard_stats", {"p_operating_year_id": operating_year_id}).execute()
    else:
        response = client.rpc("get_dashboard_stats").execute()

    return response.data


# =============================================================================
# ACTIVITY LOG
# =============================================================================

def log_activity(
    action: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    filer_id: Optional[str] = None,
    operating_year_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None
):
    """Log an activity to the activity log."""
    client = get_supabase_client()

    log_entry = {
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "filer_id": filer_id,
        "operating_year_id": operating_year_id,
        "details": details,
        "user_id": user_id,
    }

    # Remove None values
    log_entry = {k: v for k, v in log_entry.items() if v is not None}

    response = client.table("activity_log").insert(log_entry).execute()
    return response.data[0] if response.data else None


def get_recent_activity(limit: int = 50, filer_id: Optional[str] = None):
    """Get recent activity log entries."""
    client = get_supabase_client()
    query = client.table("activity_log").select("*").order("created_at", desc=True).limit(limit)

    if filer_id:
        query = query.eq("filer_id", filer_id)

    response = query.execute()
    return response.data


# =============================================================================
# TIN MATCHING LOG
# =============================================================================

def log_tin_match(
    recipient_id: str,
    tin_submitted: str,
    name_submitted: str,
    match_code: str,
    match_result: str,
    irs_response: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None
):
    """Log a TIN matching request/response."""
    client = get_supabase_client()

    log_entry = {
        "recipient_id": recipient_id,
        "tin_submitted": tin_submitted,
        "name_submitted": name_submitted,
        "match_code": match_code,
        "match_result": match_result,
        "irs_response": irs_response,
        "checked_by": user_id,
    }

    response = client.table("tin_match_log").insert(log_entry).execute()
    return response.data[0] if response.data else None


# =============================================================================
# FILER FILING STATUS
# =============================================================================

def get_filing_status(filer_id: str, tax_year: int):
    """Get filing status for a specific filer and tax year."""
    client = get_supabase_client()
    response = (
        client.table("filer_filing_status")
        .select("*")
        .eq("filer_id", filer_id)
        .eq("tax_year", tax_year)
        .single()
        .execute()
    )
    return response.data


def get_filing_dashboard(
    tenant_id: str,
    tax_year: int,
    status_filter: Optional[str] = None,
    preparer_filter: Optional[str] = None
):
    """
    Get filing dashboard data for all filers in a tenant/year.

    Returns list of filers with their filing status, preparer, and form counts.
    Note: tenant_id filter disabled for single-tenant deployment.
    """
    client = get_supabase_client()
    query = (
        client.table("filing_dashboard")
        .select("*")
        .eq("tax_year", tax_year)
        .order("filer_name")
    )

    # tenant_id filter disabled - single-tenant deployment
    # if tenant_id:
    #     query = query.eq("tenant_id", tenant_id)

    if status_filter:
        query = query.eq("status", status_filter)

    if preparer_filter:
        query = query.eq("prepared_by_user_id", preparer_filter)

    response = query.execute()
    return response.data


def set_filer_preparer(
    tenant_id: str,
    filer_id: str,
    tax_year: int,
    user_id: str,
    user_name: str
):
    """
    Set the preparer for a filer (first-touch attribution).

    Only sets preparer if not already assigned.
    Creates the filing status row if it doesn't exist.
    """
    client = get_supabase_client()
    response = client.rpc(
        "set_filer_preparer",
        {
            "p_tenant_id": tenant_id,
            "p_filer_id": filer_id,
            "p_tax_year": tax_year,
            "p_user_id": user_id,
            "p_user_name": user_name,
        }
    ).execute()
    return response.data


def update_filing_status_on_submit(
    tenant_id: str,
    filer_id: str,
    tax_year: int,
    status: str,
    submission_id: Optional[str] = None,
    receipt_id: Optional[str] = None,
    transmission_id: Optional[str] = None
):
    """
    Update filing status when forms are submitted to IRS.

    Called after successful IRS submission to record the receipt ID
    and update status to SUBMITTED/PROCESSING.
    """
    client = get_supabase_client()
    response = client.rpc(
        "update_filer_filing_status_on_submit",
        {
            "p_tenant_id": tenant_id,
            "p_filer_id": filer_id,
            "p_tax_year": tax_year,
            "p_status": status,
            "p_submission_id": submission_id,
            "p_receipt_id": receipt_id,
            "p_transmission_id": transmission_id,
        }
    ).execute()
    return response.data


def update_filing_status_on_check(
    tenant_id: str,
    filer_id: str,
    tax_year: int,
    status: str,
    errors: Optional[Dict[str, Any]] = None,
    ack_xml: Optional[str] = None
):
    """
    Update filing status after checking IRS status.

    Called after status check to update status to ACCEPTED/REJECTED/etc.
    """
    client = get_supabase_client()
    response = client.rpc(
        "update_filer_filing_status_on_check",
        {
            "p_tenant_id": tenant_id,
            "p_filer_id": filer_id,
            "p_tax_year": tax_year,
            "p_status": status,
            "p_errors": errors,
            "p_ack_xml": ack_xml,
        }
    ).execute()
    return response.data


def backfill_filing_status(tax_year: int):
    """
    Backfill filing status rows for all filers with forms in a given year.

    Creates NOT_FILED status entries for any filers that don't have one yet.
    Returns the number of rows inserted.
    """
    client = get_supabase_client()
    response = client.rpc(
        "backfill_filer_filing_status",
        {"p_tax_year": tax_year}
    ).execute()
    return response.data


def get_filing_status_summary(tenant_id: str, tax_year: int):
    """
    Get summary counts of filing statuses for a tenant/year.

    Returns dict with counts per status: {NOT_FILED: 10, SUBMITTED: 5, ACCEPTED: 3, ...}
    Note: Uses filing_dashboard view to include all active filers.
    Note: tenant_id filter disabled for single-tenant deployment.
    """
    client = get_supabase_client()
    # Query from filing_dashboard view to include all filers (even those without status rows)
    response = (
        client.table("filing_dashboard")
        .select("status")
        .eq("tax_year", tax_year)
        .execute()
    )

    # Count by status
    summary = {
        "NOT_FILED": 0,
        "SUBMITTED": 0,
        "PROCESSING": 0,
        "ACCEPTED": 0,
        "ACCEPTED_WITH_ERRORS": 0,
        "REJECTED": 0,
    }

    for row in response.data or []:
        status = row.get("status") or "NOT_FILED"
        if status in summary:
            summary[status] += 1

    summary["total"] = sum(summary.values())
    return summary
