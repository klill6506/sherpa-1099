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
from pdf_generator import generate_1099_misc_pdf  # Keep old MISC generator for now

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
            box6_state_payer_no=f"{form_data.get('state1_code', '')} {form_data.get('state1_id', '')}".strip(),
            box7_state_income=Decimal(str(form_data.get("state1_income", 0) or 0)),
            corrected=form_data.get("is_correction", False),
        )

    elif form_type == "1099-MISC":
        # Use old generator for MISC (to be updated later)
        filer_address = filer_data.get("address1", "")
        if filer_data.get("address2"):
            filer_address += f", {filer_data['address2']}"
        filer_city_state_zip = f"{filer_data.get('city', '')}, {filer_data.get('state', '')} {filer_data.get('zip', '')}"

        recipient_address = recipient_data.get("address1", "")
        if recipient_data.get("address2"):
            recipient_address += f", {recipient_data['address2']}"
        recipient_city_state_zip = f"{recipient_data.get('city', '')}, {recipient_data.get('state', '')} {recipient_data.get('zip', '')}"

        return generate_1099_misc_pdf(
            payer_name=filer_data.get("name", ""),
            payer_address=filer_address,
            payer_city_state_zip=filer_city_state_zip,
            payer_tin=filer_data.get("tin", ""),
            recipient_name=recipient_data.get("name", ""),
            recipient_address=recipient_address,
            recipient_city_state_zip=recipient_city_state_zip,
            recipient_tin=recipient_data.get("tin", ""),
            payer_phone=filer_data.get("phone", ""),
            recipient_tin_type=recipient_data.get("tin_type", "SSN"),
            recipient_account=recipient_data.get("account_number", ""),
            tax_year=tax_year,
            box1_rents=Decimal(str(form_data.get("misc_box1", 0) or 0)),
            box2_royalties=Decimal(str(form_data.get("misc_box2", 0) or 0)),
            box3_other_income=Decimal(str(form_data.get("misc_box3", 0) or 0)),
            box4_federal_withheld=Decimal(str(form_data.get("misc_box4", 0) or 0)),
            box5_fishing_boat=Decimal(str(form_data.get("misc_box5", 0) or 0)),
            box6_medical=Decimal(str(form_data.get("misc_box6", 0) or 0)),
            box7_payer_direct_sales=form_data.get("misc_box7", False),
            box8_substitute_payments=Decimal(str(form_data.get("misc_box8", 0) or 0)),
            box9_crop_insurance=Decimal(str(form_data.get("misc_box9", 0) or 0)),
            box10_gross_proceeds=Decimal(str(form_data.get("misc_box10", 0) or 0)),
            box11_fish_purchased=Decimal(str(form_data.get("misc_box11", 0) or 0)),
            box12_section_409a=Decimal(str(form_data.get("misc_box12", 0) or 0)),
            box14_excess_golden=Decimal(str(form_data.get("misc_box14", 0) or 0)),
            box15_state_withheld=Decimal(str(form_data.get("state1_withheld", 0) or 0)),
            box16_state_id=form_data.get("state1_id", "") or "",
            box17_state_income=Decimal(str(form_data.get("state1_income", 0) or 0)),
            state_code=form_data.get("state1_code", "") or "",
            copy_type=copy_type,
            corrected=form_data.get("is_correction", False),
        )

    else:
        raise ValueError(f"Unsupported form type: {form_type}")


@router.get("/{form_id}")
async def download_form_pdf(form_id: str):
    """
    Download a single 1099 form as PDF (Copy B for Recipient).

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
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/{form_id}/view")
async def view_form_pdf(form_id: str):
    """
    View a single 1099 form as PDF (inline, opens in browser for viewing/printing).
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
        headers={
            "Content-Disposition": f"inline; filename=\"{filename}\"",
            "Content-Type": "application/pdf"
        }
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
    view: bool = Query(False, description="View inline instead of download")
):
    """
    Download or view all 1099 forms for a specific filer (Copy B).
    Use ?view=true to open inline for printing.
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

    # If view=true, return inline for viewing/printing in browser
    if view:
        return StreamingResponse(
            output,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename=\"{filename}\"",
                "Content-Type": "application/pdf"
            }
        )

    # Default: download
    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
    )
