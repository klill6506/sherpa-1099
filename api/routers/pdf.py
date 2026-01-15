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
import logging

import sys
sys.path.insert(0, "src")

from supabase_client import get_supabase_client
from pdf_1099_nec_overlay import generate_1099_nec_overlay
from pdf_1099_misc_overlay import generate_1099_misc_overlay
from pdf_1099_s_overlay import generate_1099s_copyb
from pdf_1098_overlay import generate_1098_copyb
from encryption import decrypt_tin, format_tin_full

logger = logging.getLogger(__name__)

router = APIRouter()


def get_decrypted_tin(record: dict, record_type: str = "recipient") -> str:
    """
    Get decrypted TIN from a filer or recipient record.

    Tries tin_encrypted first (Phase 4 encrypted), falls back to tin (legacy plain text).
    """
    tin_encrypted = record.get("tin_encrypted")
    tin_type = record.get("tin_type", "SSN")

    if tin_encrypted:
        try:
            # Decrypt and format with dashes
            decrypted = decrypt_tin(tin_encrypted, record.get("tin_key_version", 1))
            return format_tin_full(decrypted, tin_type)
        except Exception as e:
            logger.error(f"Failed to decrypt TIN for {record_type} {record.get('id')}: {e}")
            # Fall through to legacy tin field

    # Legacy: use plain text tin field if encryption not available
    plain_tin = record.get("tin", "")
    if plain_tin:
        return plain_tin

    # Last resort: show masked version
    tin_last4 = record.get("tin_last4", "0000")
    return f"XXX-XX-{tin_last4}" if tin_type == "SSN" else f"XX-XXX{tin_last4}"


def get_forms_batch(form_ids: list) -> list:
    """
    Fetch multiple forms with their relations in optimized batch queries.
    Returns list of dicts with form, filer, recipient data.
    """
    import logging
    import copy

    logger = logging.getLogger(__name__)

    if not form_ids:
        return []

    # Deduplicate input form_ids while preserving order
    seen_ids = set()
    unique_form_ids = []
    for fid in form_ids:
        if fid not in seen_ids:
            seen_ids.add(fid)
            unique_form_ids.append(fid)

    if len(form_ids) != len(unique_form_ids):
        logger.warning(f"get_forms_batch: Input had {len(form_ids)} IDs, {len(unique_form_ids)} unique")

    client = get_supabase_client()

    # Fetch all forms in one query
    forms_result = client.table("forms_1099").select("*").in_("id", unique_form_ids).execute()
    if not forms_result.data:
        return []

    # Use copy to avoid mutating cached objects
    forms_by_id = {f["id"]: copy.deepcopy(f) for f in forms_result.data}

    # Collect unique filer and recipient IDs
    filer_ids = list(set(f["filer_id"] for f in forms_result.data if f.get("filer_id")))
    recipient_ids = list(set(f["recipient_id"] for f in forms_result.data if f.get("recipient_id")))
    operating_year_ids = list(set(f["operating_year_id"] for f in forms_result.data if f.get("operating_year_id")))

    # Batch fetch filers
    filers_by_id = {}
    if filer_ids:
        filers_result = client.table("filers").select("*").in_("id", filer_ids).execute()
        filers_by_id = {f["id"]: copy.deepcopy(f) for f in filers_result.data} if filers_result.data else {}

    # Batch fetch recipients
    recipients_by_id = {}
    if recipient_ids:
        recipients_result = client.table("recipients").select("*").in_("id", recipient_ids).execute()
        recipients_by_id = {r["id"]: copy.deepcopy(r) for r in recipients_result.data} if recipients_result.data else {}

    # Batch fetch operating years for tax_year
    years_by_id = {}
    if operating_year_ids:
        years_result = client.table("operating_years").select("id, tax_year").in_("id", operating_year_ids).execute()
        years_by_id = {y["id"]: y["tax_year"] for y in years_result.data} if years_result.data else {}

    # Assemble results in original order (using deduplicated IDs)
    results = []
    for form_id in unique_form_ids:
        form = forms_by_id.get(form_id)
        if not form:
            continue

        filer = filers_by_id.get(form.get("filer_id"))
        recipient = recipients_by_id.get(form.get("recipient_id"))

        if not filer or not recipient:
            continue

        # Add tax year to form
        form["tax_year"] = years_by_id.get(form.get("operating_year_id"), 2024)

        results.append({
            "form": form,
            "filer": filer,
            "recipient": recipient
        })

    return results


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

    # Decrypt TINs for PDF generation
    filer_tin = get_decrypted_tin(filer_data, "filer")
    recipient_tin = get_decrypted_tin(recipient_data, "recipient")

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
            payer_tin=filer_tin,
            recipient_name=recipient_data.get("name", ""),
            recipient_address_lines=recipient_address_lines,
            recipient_tin=recipient_tin,
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
            payer_tin=filer_tin,
            recipient_name=recipient_data.get("name", ""),
            recipient_address_lines=recipient_address_lines,
            recipient_tin=recipient_tin,
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
            filer_tin=filer_tin,
            transferor_name=recipient_data.get("name", ""),
            transferor_address_lines=recipient_address_lines,
            transferor_tin=recipient_tin,
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
            recipient_tin=filer_tin,
            payer_name=recipient_data.get("name", ""),  # Borrower
            payer_address_lines=recipient_address_lines,
            payer_tin=recipient_tin,
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

    # Use optimized batch fetch - reduces N*4 queries to just 4 queries total
    forms_data = get_forms_batch(form_ids)

    if not forms_data:
        raise HTTPException(status_code=400, detail="No valid forms found")

    writer = PdfWriter()
    processed = 0
    errors = []

    for data in forms_data:
        try:
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
            # Track failed forms for debugging
            form_id = data["form"].get("id", "unknown")
            errors.append(f"{form_id}: {str(e)}")
            continue

    if processed == 0:
        detail = "No valid forms to generate"
        if errors:
            detail += f". Errors: {'; '.join(errors[:5])}"  # Show first 5 errors
        raise HTTPException(status_code=400, detail=detail)

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
    import logging

    logger = logging.getLogger(__name__)

    client = get_supabase_client()

    # Get all form IDs for this filer
    query = client.table("forms_1099").select("id").eq("filer_id", filer_id)
    if form_type:
        query = query.eq("form_type", form_type)
    forms_result = query.execute()

    if not forms_result.data:
        raise HTTPException(status_code=404, detail="No forms found for this filer")

    form_ids = [f["id"] for f in forms_result.data]

    # Check for duplicate form IDs from database query
    if len(form_ids) != len(set(form_ids)):
        logger.error(f"DUPLICATE FORM IDS from database query! Total: {len(form_ids)}, Unique: {len(set(form_ids))}")

    # Use optimized batch fetch
    forms_data = get_forms_batch(form_ids)

    if not forms_data:
        raise HTTPException(status_code=400, detail="No valid forms to generate")

    writer = PdfWriter()
    processed = 0

    # Track processed forms to detect duplicates
    processed_form_ids = set()
    processed_recipient_keys = set()  # (recipient_id, form_type) to catch same person twice
    duplicates_detected = []

    for data in forms_data:
        form_id = data["form"].get("id")
        recipient_id = data["recipient"].get("id")
        recipient_name = data["recipient"].get("name", "Unknown")
        form_type_val = data["form"].get("form_type", "Unknown")

        # Check for duplicate form ID
        if form_id in processed_form_ids:
            duplicates_detected.append(f"DUPLICATE FORM ID: {form_id} for {recipient_name}")
            logger.error(f"DUPLICATE FORM ID detected: {form_id} for {recipient_name}")
            continue

        # Check for duplicate recipient+form_type combo
        recipient_key = (recipient_id, form_type_val)
        if recipient_key in processed_recipient_keys:
            duplicates_detected.append(f"DUPLICATE RECIPIENT: {recipient_name} ({form_type_val})")
            logger.error(f"DUPLICATE RECIPIENT detected: {recipient_name} ({form_type_val})")
            continue

        processed_form_ids.add(form_id)
        processed_recipient_keys.add(recipient_key)

        try:
            pdf_bytes = generate_1099_pdf(
                form_data=data["form"],
                filer_data=data["filer"],
                recipient_data=data["recipient"],
                copy_type="B"
            )
            reader = PdfReader(BytesIO(pdf_bytes))
            pages_before = len(writer.pages)
            for page in reader.pages:
                writer.add_page(page)
            pages_after = len(writer.pages)
            pages_added = pages_after - pages_before
            if pages_added != 1:
                print(f"WARNING: Added {pages_added} pages for {recipient_name} (expected 1)")
            processed += 1
            print(f"  [{processed}] {recipient_name}: {pages_added} page(s) added, total now {pages_after}")
        except Exception as e:
            logger.error(f"Error generating PDF for {recipient_name}: {e}")
            print(f"  ERROR generating PDF for {recipient_name}: {e}")
            continue

    # Log if duplicates were found
    if duplicates_detected:
        logger.error(f"PDF GENERATION DUPLICATES DETECTED ({len(duplicates_detected)}): {duplicates_detected}")
        print(f"*** PDF DUPLICATES DETECTED ({len(duplicates_detected)}): {duplicates_detected} ***")

    # Always print summary for debugging
    print(f"PDF Generation: {processed} forms processed, {len(duplicates_detected)} duplicates skipped")

    if processed == 0:
        raise HTTPException(status_code=400, detail="No valid forms to generate")

    output = BytesIO()
    writer.write(output)
    output.seek(0)

    # Get filer name for filename
    filer_result = client.table("filers").select("name").eq("id", filer_id).execute()
    filer_name = filer_result.data[0]["name"].replace(" ", "_")[:20] if filer_result.data else "Unknown"

    filename = f"1099s_{filer_name}_{processed}_forms.pdf"

    # Build response headers
    disposition = "attachment" if download else "inline"
    headers = {"Content-Disposition": f'{disposition}; filename="{filename}"'}

    # Add warning header if duplicates were detected
    if duplicates_detected:
        headers["X-Duplicates-Warning"] = f"{len(duplicates_detected)} duplicates detected and skipped"
        # Return error response instead of PDF if duplicates found
        raise HTTPException(
            status_code=409,
            detail=f"Duplicate detection error: {len(duplicates_detected)} duplicates found and skipped. "
                   f"Details: {'; '.join(duplicates_detected[:5])}"
                   f"{' (and more...)' if len(duplicates_detected) > 5 else ''}. "
                   f"PDF was generated with {processed} unique forms. Please check server logs and re-import data if needed."
        )

    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers=headers
    )


@router.get("/filer/{filer_id}/invoice")
async def generate_filer_invoice(
    filer_id: str,
    download: bool = Query(True, description="Download as attachment instead of opening inline")
):
    """
    Generate a PDF invoice for 1099 preparation services.

    Pricing:
    - Setup fee: $150
    - Per form: $7

    Invoice number format: 26XXX (derived from filer ID)
    """
    from invoice_generator import generate_invoice_pdf

    client = get_supabase_client()

    # Get filer info
    filer_result = client.table("filers").select("name").eq("id", filer_id).execute()
    if not filer_result.data:
        raise HTTPException(status_code=404, detail="Filer not found")

    filer_name = filer_result.data[0]["name"]

    # Count forms for this filer (current operating year)
    forms_result = client.table("forms_1099").select("id").eq("filer_id", filer_id).execute()
    form_count = len(forms_result.data) if forms_result.data else 0

    if form_count == 0:
        raise HTTPException(status_code=400, detail="No forms found for this filer")

    # Generate invoice PDF
    pdf_bytes = generate_invoice_pdf(
        filer_name=filer_name,
        filer_id=filer_id,
        form_count=form_count,
    )

    # Build filename
    safe_name = filer_name.replace(" ", "_").replace(",", "")[:30]
    filename = f"Invoice_{safe_name}.pdf"

    disposition = "attachment" if download else "inline"

    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'}
    )
