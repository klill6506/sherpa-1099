"""
Web Pages Router.

Serves Jinja2 templates for the frontend UI.
All pages require authentication (except download-template for now).
"""

from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import sys
sys.path.insert(0, "src")

from supabase_client import get_supabase_client
from api.auth import require_auth_redirect, CurrentUser

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# US States for dropdowns
US_STATES = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
    'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware',
    'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii', 'ID': 'Idaho',
    'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas',
    'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
    'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
    'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
    'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
    'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma',
    'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
    'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah',
    'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia',
    'WI': 'Wisconsin', 'WY': 'Wyoming', 'DC': 'District of Columbia'
}


def get_operating_year():
    """Get the active operating year."""
    client = get_supabase_client()
    result = client.table('operating_years').select('*').eq('is_current', True).limit(1).execute()
    if result.data:
        # Map tax_year to year for template compatibility
        year_data = result.data[0]
        year_data['year'] = year_data.get('tax_year')
        return year_data
    return None


def get_dashboard_stats(operating_year_id: Optional[str] = None):
    """Compute dashboard statistics."""
    client = get_supabase_client()

    # Filers count
    filers = client.table('filers').select('id', count='exact').eq('is_active', True).execute()

    # Recipients count - recipients don't have operating_year_id, they're linked through forms
    recipients = client.table('recipients').select('id', count='exact').execute()

    # Forms count and breakdown
    forms_query = client.table('forms_1099').select('id, status, form_type')
    if operating_year_id:
        forms_query = forms_query.eq('operating_year_id', operating_year_id)
    forms = forms_query.execute()

    forms_by_status: dict[str, int] = {}
    forms_by_type: dict[str, int] = {}
    for form in forms.data:
        status = form.get('status', 'draft')
        form_type = form.get('form_type', 'Unknown')
        forms_by_status[status] = forms_by_status.get(status, 0) + 1
        forms_by_type[form_type] = forms_by_type.get(form_type, 0) + 1

    return {
        'filers_count': filers.count or 0,
        'recipients_count': recipients.count or 0,
        'forms_count': len(forms.data),
        'forms_by_status': forms_by_status,
        'forms_by_type': forms_by_type
    }


# =============================================================================
# DASHBOARD
# =============================================================================

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Dashboard page - shows filers list."""
    # Check authentication
    user = require_auth_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    client = get_supabase_client()
    operating_year = get_operating_year()

    # Get all filers alphabetically
    filers = client.table('filers').select('*').eq('is_active', True).order('name').execute().data

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active_page": "dashboard",
        "operating_year": operating_year,
        "filers": filers,
        "user": user
    })


# =============================================================================
# IMPORTS
# =============================================================================

@router.get("/imports", response_class=HTMLResponse)
async def imports_list(request: Request):
    """Import batches list page."""
    user = require_auth_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    client = get_supabase_client()
    operating_year = get_operating_year()

    batches = client.table('import_batches').select('*').order(
        'uploaded_at', desc=True
    ).limit(50).execute().data

    return templates.TemplateResponse("imports/list.html", {
        "request": request,
        "active_page": "imports",
        "operating_year": operating_year,
        "batches": batches,
        "user": user
    })


@router.get("/imports/upload", response_class=HTMLResponse)
async def imports_upload(request: Request):
    """Import upload page."""
    user = require_auth_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    client = get_supabase_client()
    operating_year = get_operating_year()

    # Get operating years for dropdown
    operating_years_data = client.table('operating_years').select('*').order(
        'tax_year', desc=True
    ).execute().data
    # Map tax_year to year for template compatibility
    operating_years = []
    for oy in operating_years_data:
        oy['year'] = oy.get('tax_year')
        oy['is_active'] = oy.get('is_current')
        operating_years.append(oy)

    # Get filers for dropdown
    filers = client.table('filers').select('id, name, tin').eq(
        'is_active', True
    ).order('name').execute().data

    return templates.TemplateResponse("imports/upload.html", {
        "request": request,
        "active_page": "imports",
        "operating_year": operating_year,
        "operating_years": operating_years,
        "current_year_id": operating_year['id'] if operating_year else None,
        "filers": filers,
        "user": user
    })


@router.get("/imports/{batch_id}", response_class=HTMLResponse)
async def imports_review(request: Request, batch_id: str):
    """Import review page."""
    user = require_auth_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    client = get_supabase_client()
    operating_year = get_operating_year()

    # Get batch
    batch_result = client.table('import_batches').select('*').eq('id', batch_id).execute()
    if not batch_result.data:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Import batch not found"
        }, status_code=404)

    batch = batch_result.data[0]

    # Get filers for promote dropdown
    filers = client.table('filers').select('id, name, tin').eq(
        'is_active', True
    ).order('name').execute().data

    return templates.TemplateResponse("imports/review.html", {
        "request": request,
        "active_page": "imports",
        "operating_year": operating_year,
        "batch": batch,
        "filers": filers,
        "user": user
    })


# =============================================================================
# FILERS
# =============================================================================

@router.get("/filers", response_class=HTMLResponse)
async def filers_list(request: Request):
    """Filers list page."""
    user = require_auth_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    client = get_supabase_client()
    operating_year = get_operating_year()

    filers = client.table('filers').select('*').order('name').execute().data

    return templates.TemplateResponse("filers/list.html", {
        "request": request,
        "active_page": "filers",
        "operating_year": operating_year,
        "filers": filers,
        "user": user
    })


@router.get("/filers/new", response_class=HTMLResponse)
async def filers_new(request: Request):
    """New filer form page."""
    user = require_auth_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    operating_year = get_operating_year()

    return templates.TemplateResponse("filers/form.html", {
        "request": request,
        "active_page": "filers",
        "operating_year": operating_year,
        "filer": None,
        "states": US_STATES,
        "user": user
    })


@router.get("/filers/{filer_id}", response_class=HTMLResponse)
async def filers_detail(request: Request, filer_id: str):
    """Filer detail page with recipients and forms."""
    user = require_auth_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    client = get_supabase_client()
    operating_year = get_operating_year()

    # Get filer
    filer_result = client.table('filers').select('*').eq('id', filer_id).execute()
    if not filer_result.data:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Filer not found"
        }, status_code=404)

    filer = filer_result.data[0]

    # Get recipients for this filer
    recipients = client.table('recipients').select('*').eq('filer_id', filer_id).order('name').execute().data

    # Get forms for this filer (with recipient info)
    forms_query = client.table('forms_1099').select('*, recipients(name, tin)').eq('filer_id', filer_id)
    if operating_year:
        forms_query = forms_query.eq('operating_year_id', operating_year['id'])
    forms = forms_query.order('created_at', desc=True).execute().data

    # Calculate totals by form type
    nec_total = sum(float(f.get('nec_box1') or 0) for f in forms if f.get('form_type') == '1099-NEC')
    misc_total = sum(float(f.get('misc_box1') or 0) for f in forms if f.get('form_type') == '1099-MISC')
    s_total = sum(float(f.get('s_box2_gross_proceeds') or 0) for f in forms if f.get('form_type') == '1099-S')
    f1098_total = sum(float(f.get('f1098_box1_mortgage_interest') or 0) for f in forms if f.get('form_type') == '1098')

    # Count forms by type
    nec_count = sum(1 for f in forms if f.get('form_type') == '1099-NEC')
    misc_count = sum(1 for f in forms if f.get('form_type') == '1099-MISC')
    s_count = sum(1 for f in forms if f.get('form_type') == '1099-S')
    f1098_count = sum(1 for f in forms if f.get('form_type') == '1098')

    return templates.TemplateResponse("filers/detail.html", {
        "request": request,
        "active_page": "filers",
        "operating_year": operating_year,
        "filer": filer,
        "recipients": recipients,
        "forms": forms,
        "nec_total": nec_total,
        "misc_total": misc_total,
        "s_total": s_total,
        "f1098_total": f1098_total,
        "nec_count": nec_count,
        "misc_count": misc_count,
        "s_count": s_count,
        "f1098_count": f1098_count,
        "user": user
    })


@router.get("/filers/{filer_id}/edit", response_class=HTMLResponse)
async def filers_edit(request: Request, filer_id: str):
    """Edit filer form page."""
    user = require_auth_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    client = get_supabase_client()
    operating_year = get_operating_year()

    filer_result = client.table('filers').select('*').eq('id', filer_id).execute()
    if not filer_result.data:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Filer not found"
        }, status_code=404)

    return templates.TemplateResponse("filers/form.html", {
        "request": request,
        "active_page": "filers",
        "operating_year": operating_year,
        "filer": filer_result.data[0],
        "states": US_STATES,
        "user": user
    })


@router.get("/filers/{filer_id}/tin-match", response_class=HTMLResponse)
async def filers_tin_match(request: Request, filer_id: str):
    """TIN matching page for a filer's recipients."""
    user = require_auth_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    client = get_supabase_client()
    operating_year = get_operating_year()

    # Get filer
    filer_result = client.table('filers').select('*').eq('id', filer_id).execute()
    if not filer_result.data:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Filer not found"
        }, status_code=404)

    filer = filer_result.data[0]

    # Get recipients for this filer
    recipients = client.table('recipients').select('*').eq('filer_id', filer_id).order('name').execute().data

    return templates.TemplateResponse("filers/tin_match.html", {
        "request": request,
        "active_page": "filers",
        "operating_year": operating_year,
        "filer": filer,
        "recipients": recipients,
        "user": user
    })


# =============================================================================
# RECIPIENTS
# =============================================================================

@router.get("/recipients", response_class=HTMLResponse)
async def recipients_list(request: Request):
    """Recipients list page (placeholder)."""
    user = require_auth_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    client = get_supabase_client()
    operating_year = get_operating_year()

    recipients = client.table('recipients').select('*').order('name').limit(100).execute().data

    return templates.TemplateResponse("recipients/list.html", {
        "request": request,
        "active_page": "recipients",
        "operating_year": operating_year,
        "recipients": recipients,
        "user": user
    })


# =============================================================================
# FORMS
# =============================================================================

@router.get("/forms", response_class=HTMLResponse)
async def forms_list(request: Request):
    """1099 Forms list page (placeholder)."""
    user = require_auth_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    client = get_supabase_client()
    operating_year = get_operating_year()

    forms = client.table('forms_1099').select(
        '*, recipients(name, tin)'
    ).order('created_at', desc=True).limit(100).execute().data

    return templates.TemplateResponse("forms/list.html", {
        "request": request,
        "active_page": "forms",
        "operating_year": operating_year,
        "forms": forms,
        "user": user
    })


# =============================================================================
# DOWNLOADS
# =============================================================================

@router.get("/download-template")
async def download_template():
    """Download the 1099 import template Excel file."""
    template_path = Path(__file__).parent.parent.parent / "1099-Template .xlsx"

    if not template_path.exists():
        # Try alternate name without trailing space
        template_path = Path(__file__).parent.parent.parent / "1099-Template.xlsx"

    return FileResponse(
        path=template_path,
        filename="1099-Template.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
