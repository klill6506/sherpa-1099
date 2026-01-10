"""
PDF Generation Router.

Endpoints for generating and downloading 1099 PDFs.
Uses the new template-layer PDF generator for IRS-compliant layout.
"""

from typing import Optional, List
from decimal import Decimal
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from io import BytesIO

import sys
sys.path.insert(0, "src")

from supabase_client import get_supabase_client
from pdf_1099_nec_overlay import generate_1099_nec_overlay
from pdf_1099_misc_overlay import generate_1099_misc_overlay
from pdf_1099_s_overlay import generate_1099s_copyb
from pdf_1098_overlay import generate_1098_copyb

router = APIRouter()


def get_form_with_relations(form_id: str) -> dict:
    """Get form with filer and recipient data."""
    client = get_supabase_client()

    # Get form
    form_result = client.table("forms_1099").select("*").eq("id", form_id).execute()
    if not form_result.data:
        raise HTTPException(status_code=404, detail="Form not found")
    form = form_result.data[0]

    # Get filer
    filer_result = client.table("filers").select("*").eq("id", form["filer_id"]).execute()
    if not filer_result.data:
        raise HTTPException(status_code=404, detail="Filer not found")
    filer = filer_result.data[0]

    # Get recipient
    recipient_result = client.table("recipients").select("*").eq("id", form["recipient_id"]).execute()
    if not recipient_result.data:
        raise HTTPException(status_code=404, detail="Recipient not found")
    recipient = recipient_result.data[0]

    # Get tax year from operating_year
    year_result = client.table("operating_years").select("tax_year").eq("id", form["operating_year_id"]).execute()
    form["tax_year"] = year_result.data[0]["tax_year"] if year_result.data else 2024

    return {"form": form, "filer": filer, "recipient": recipient}


def generate_1099_pdf(form_data: dict, filer_data: dict, recipient_data: dict, copy_type: str = "B") -> bytes:
    """
    Generate appropriate 1099 PDF based on form type.
    Uses new template-layer generator for 1099-NEC.
    """
    form_type = form_data.get("form_type", "1099-NEC")
    tax_year = form_data.get("tax_year", 2024)

    # Build filer address lines
    filer_address_lines = []
    if filer_data.get("address1"):
        filer_address_lines.append(filer_data["address1"])
    if filer_data.get("address2"):
        filer_address_lines.append(filer_data["address2"])
    city_state_zip = f"{filer_data.get('city', '')}, {filer_data.get('state', '')} {filer_data.get('zip', '')}"
    filer_address_lines.append(city_state_zip)

    # Build recipient address lines
    recipient_address_lines = []
    if recipient_data.get("address1"):
        recipient_address_lines.append(recipient_data["address1"])
    if recipient_data.get("address2"):
        recipient_address_lines.append(recipient_data["address2"])
    city_state_zip = f"{recipient_data.get('city', '')}, {recipient_data.get('state', '')} {recipient_data.get('zip', '')}"
    recipient_address_lines.append(city_state_zip)

    if form_type == "1099-NEC":
        # Use official IRS template overlay generator
        return generate_1099_nec_overlay(
            payer_name=filer_data.get("name", ""),
            payer_address_lines=filer_address_lines,
            payer_tin=filer_data.get("tin", ""),
            recipient_name=recipient_data.get("name", ""),
            recipient_address_lines=recipient_address_lines,
            recipient_tin=recipient_data.get("tin", ""),
            payer_phone=filer_data.get("phone", ""),
            recipient_account=recipient_data.get("account_number", ""),
            tax_year=tax_year,
            box1_compensation=Decimal(str(form_data.get("nec_box1", 0) or 0)),
            box3_golden_parachute=Decimal(str(form_data.get("nec_box3", 0) or 0)),
            box4_federal_withheld=Decimal(str(form_data.get("nec_box4", 0) or 0)),
            box5_state_withheld=Decimal(str(form_data.get("state1_withheld", 0) or 0)),
            box6_state_payer_no=f"{form_data.get('state1_code') or ''} {form_data.get('state1_id') or ''}".strip(),
            box7_state_income=Decimal(str(form_data.get("state1_income", 0) or 0)),
            corrected=form_data.get("is_correction", False),
        )

    elif form_type == "1099-MISC":
        # Use official IRS template overlay generator (same approach as NEC)
        return generate_1099_misc_overlay(
            payer_name=filer_data.get("name", ""),
            payer_address_lines=filer_address_lines,
            payer_tin=filer_data.get("tin", ""),
            recipient_name=recipient_data.get("name", ""),
            recipient_address_lines=recipient_address_lines,
            recipient_tin=recipient_data.get("tin", ""),
            payer_phone=filer_data.get("phone", ""),
            recipient_account=recipient_data.get("account_number", ""),
            tax_year=tax_year,
            box1_rents=Decimal(str(form_data.get("misc_box1", 0) or 0)),
            box4_federal_withheld=Decimal(str(form_data.get("misc_box4", 0) or 0)),
            box15_state_withheld=Decimal(str(form_data.get("state1_withheld", 0) or 0)),
            box16_state_payer_no=f"{form_data.get('state1_code') or ''} {form_data.get('state1_id') or ''}".strip(),
            box17_state_income=Decimal(str(form_data.get("state1_income", 0) or 0)),
            corrected=form_data.get("is_correction", False),
        )

    elif form_type == "1099-S":
        # 1099-S: Proceeds From Real Estate Transactions
        return generate_1099s_copyb(
            filer_name=filer_data.get("name", ""),
            filer_address_lines=filer_address_lines,
            filer_tin=filer_data.get("tin", ""),
            transferor_name=recipient_data.get("name", ""),
            transferor_address_lines=recipient_address_lines,
            transferor_tin=recipient_data.get("tin", ""),
            filer_phone=filer_data.get("phone", ""),
            account_number=recipient_data.get("account_number", ""),
            tax_year=tax_year,
            box1_date_of_closing=form_data.get("s_box1_date_closing") or "",
            box2_gross_proceeds=Decimal(str(form_data.get("s_box2_gross_proceeds", 0) or 0)),
            box3_property_description=form_data.get("s_box3_property_address") or "",
            box4_property_services=form_data.get("s_box4_property_services") or False,
            box5_foreign=form_data.get("s_box5_foreign_person") or False,
            box6_buyers_tax=Decimal(str(form_data.get("s_box6_buyers_tax", 0) or 0)),
            corrected=form_data.get("is_correction", False),
        )

    elif form_type == "1098":
        # 1098: Mortgage Interest Statement
        # Note: For 1098, filer = recipient/lender, recipient = payer/borrower
        return generate_1098_copyb(
            recipient_name=filer_data.get("name", ""),  # Lender
            recipient_address_lines=filer_address_lines,
            recipient_tin=filer_data.get("tin", ""),
            payer_name=recipient_data.get("name", ""),  # Borrower
            payer_address_lines=recipient_address_lines,
            payer_tin=recipient_data.get("tin", ""),
            recipient_phone=filer_data.get("phone", ""),
            account_number=recipient_data.get("account_number", ""),
            tax_year=tax_year,
            box1_mortgage_interest=Decimal(str(form_data.get("f1098_box1_mortgage_interest", 0) or 0)),
            box2_outstanding_principal=Decimal(str(form_data.get("f1098_box2_outstanding_principal", 0) or 0)),
            box3_origination_date=form_data.get("f1098_box3_origination_date") or "",
            box4_refund_interest=Decimal(str(form_data.get("f1098_box4_refund_interest", 0) or 0)),
            box5_mortgage_insurance=Decimal(str(form_data.get("f1098_box5_mortgage_insurance", 0) or 0)),
            box6_points_paid=Decimal(str(form_data.get("f1098_box6_points_paid", 0) or 0)),
            box8_property_address=form_data.get("f1098_box8_property_address") or "",
            box9_num_properties=str(form_data.get("f1098_box9_num_properties") or "") if form_data.get("f1098_box9_num_properties") else "",
            box10_other=Decimal(str(form_data.get("f1098_box10_other", 0) or 0)),
            box11_acquisition_date=form_data.get("f1098_box11_acquisition_date") or "",
            corrected=form_data.get("is_correction", False),
        )

    else:
        raise ValueError(f"Unsupported form type: {form_type}")


@router.get("/{form_id}")
async def get_form_pdf(form_id: str):
    """
    View a single 1099 form as PDF (opens inline in browser for viewing/printing).

    - **form_id**: UUID of the form
    """
    data = get_form_with_relations(form_id)

    try:
        pdf_bytes = generate_1099_pdf(
            form_data=data["form"],
            filer_data=data["filer"],
            recipient_data=data["recipient"],
            copy_type="B"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Build filename
    recipient_name = data["recipient"]["name"].replace(" ", "_").replace(",", "")[:30]
    form_type = data["form"]["form_type"].replace("-", "")
    tax_year = data["form"]["tax_year"]
    filename = f"{form_type}_{tax_year}_{recipient_name}.pdf"

    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'}
    )


@router.get("/{form_id}/download")
async def download_form_pdf(form_id: str):
    """
    Download a single 1099 form as PDF (attachment, triggers browser download).
    """
    data = get_form_with_relations(form_id)

    try:
        pdf_bytes = generate_1099_pdf(
            form_data=data["form"],
            filer_data=data["filer"],
            recipient_data=data["recipient"],
            copy_type="B"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Build filename
    recipient_name = data["recipient"]["name"].replace(" ", "_").replace(",", "")[:30]
    form_type = data["form"]["form_type"].replace("-", "")
    tax_year = data["form"]["tax_year"]
    filename = f"{form_type}_{tax_year}_{recipient_name}.pdf"

    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.post("/batch")
async def download_batch_pdf(form_ids: List[str]):
    """
    Download multiple 1099 forms as a combined PDF (Copy B).

    Request body: list of form IDs
    """
    from PyPDF2 import PdfReader, PdfWriter

    if not form_ids:
        raise HTTPException(status_code=400, detail="No form IDs provided")

    writer = PdfWriter()
    processed = 0

    for form_id in form_ids:
        try:
            data = get_form_with_relations(form_id)
            pdf_bytes = generate_1099_pdf(
                form_data=data["form"],
                filer_data=data["filer"],
                recipient_data=data["recipient"],
                copy_type="B"
            )
            reader = PdfReader(BytesIO(pdf_bytes))
            for page in reader.pages:
                writer.add_page(page)
            processed += 1
        except Exception as e:
            # Skip failed forms, continue with others
            print(f"Failed to generate PDF for form {form_id}: {e}")
            continue

    if processed == 0:
        raise HTTPException(status_code=400, detail="No valid forms to generate")

    output = BytesIO()
    writer.write(output)
    output.seek(0)

    filename = f"1099_Batch_{processed}_forms.pdf"

    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/filer/{filer_id}/all")
async def download_all_filer_forms(
    filer_id: str,
    form_type: Optional[str] = Query(None, description="Filter by form type (1099-NEC, 1099-MISC)"),
    download: bool = Query(False, description="Download as attachment instead of opening inline")
):
    """
    View or download all 1099 forms for a specific filer (Copy B).
    Default behavior: opens inline for viewing/printing.
    Use ?download=true to download as attachment.
    """
    from PyPDF2 import PdfReader, PdfWriter

    client = get_supabase_client()

    # Get all forms for this filer
    query = client.table("forms_1099").select("id").eq("filer_id", filer_id)
    if form_type:
        query = query.eq("form_type", form_type)
    forms_result = query.execute()

    if not forms_result.data:
        raise HTTPException(status_code=404, detail="No forms found for this filer")

    form_ids = [f["id"] for f in forms_result.data]

    # Reuse batch endpoint logic
    writer = PdfWriter()
    processed = 0

    for form_id in form_ids:
        try:
            data = get_form_with_relations(form_id)
            pdf_bytes = generate_1099_pdf(
                form_data=data["form"],
                filer_data=data["filer"],
                recipient_data=data["recipient"],
                copy_type="B"
            )
            reader = PdfReader(BytesIO(pdf_bytes))
            for page in reader.pages:
                writer.add_page(page)
            processed += 1
        except Exception:
            continue

    if processed == 0:
        raise HTTPException(status_code=400, detail="No valid forms to generate")

    output = BytesIO()
    writer.write(output)
    output.seek(0)

    # Get filer name for filename
    filer_result = client.table("filers").select("name").eq("id", filer_id).execute()
    filer_name = filer_result.data[0]["name"].replace(" ", "_")[:20] if filer_result.data else "Unknown"

    filename = f"1099s_{filer_name}_{processed}_forms.pdf"

    # If download=true, return as attachment
    if download:
        return StreamingResponse(
            output,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    # Default: inline (open for viewing/printing)
    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'}
    )
