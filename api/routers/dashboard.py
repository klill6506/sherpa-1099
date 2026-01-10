"""
Dashboard API Router.

Provides summary statistics and activity logs.
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query

import sys
sys.path.insert(0, "src")

from supabase_client import (
    get_filer_status_summary,
    get_recent_activity,
    get_current_operating_year,
    get_filers,
    get_supabase_client,
)
from api.schemas import FilerStatusSummary, DashboardStats, ActivityLogEntry

router = APIRouter()


def compute_dashboard_stats(operating_year_id: Optional[str] = None) -> dict:
    """Compute dashboard stats from database tables."""
    client = get_supabase_client()

    # Get counts
    filers = client.table("filers").select("id", count="exact").eq("is_active", True).execute()
    total_filers = filers.count or 0

    recipients = client.table("recipients").select("id", count="exact").eq("is_active", True).execute()
    total_recipients = recipients.count or 0

    # Get forms with optional year filter
    forms_query = client.table("forms_1099").select("status, form_type")
    if operating_year_id:
        forms_query = forms_query.eq("operating_year_id", operating_year_id)
    forms = forms_query.execute()

    forms_data = forms.data or []
    total_forms = len(forms_data)

    # Count by status
    forms_by_status: dict[str, int] = {}
    forms_by_type: dict[str, int] = {}
    for form in forms_data:
        status = form.get("status", "unknown")
        forms_by_status[status] = forms_by_status.get(status, 0) + 1

        form_type = form.get("form_type", "unknown")
        forms_by_type[form_type] = forms_by_type.get(form_type, 0) + 1

    return {
        "total_filers": total_filers,
        "total_recipients": total_recipients,
        "total_forms": total_forms,
        "forms_by_status": forms_by_status,
        "forms_by_type": forms_by_type,
        "recent_activity": [],
    }


@router.get("/stats", response_model=DashboardStats)
async def get_stats(
    operating_year_id: Optional[str] = Query(None, description="Operating year ID (defaults to current)"),
):
    """Get dashboard statistics for an operating year."""
    try:
        # Use current year if not specified
        if not operating_year_id:
            current_year = get_current_operating_year()
            if current_year:
                operating_year_id = current_year.get("id")

        stats = compute_dashboard_stats(operating_year_id)
        return DashboardStats(**stats)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/filer-summary", response_model=List[FilerStatusSummary])
async def get_filer_summary(
    operating_year_id: Optional[str] = Query(None, description="Operating year ID (defaults to current)"),
):
    """Get filing status summary per filer."""
    try:
        # Use current year if not specified
        if not operating_year_id:
            current_year = get_current_operating_year()
            if current_year:
                operating_year_id = current_year.get("id")

        summary = get_filer_status_summary(operating_year_id)
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/activity", response_model=List[ActivityLogEntry])
async def get_activity_log(
    limit: int = Query(50, ge=1, le=500, description="Number of entries to return"),
    filer_id: Optional[str] = Query(None, description="Filter by filer ID"),
):
    """Get recent activity log entries."""
    try:
        activity = get_recent_activity(limit=limit, filer_id=filer_id)
        return activity
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
