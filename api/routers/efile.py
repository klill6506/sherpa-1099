"""
IRS E-Filing API Router.

Handles 1099 e-filing to IRS IRIS system:
- Generate IRIS-compliant XML
- Submit to IRS
- Check submission status
- Retrieve acknowledgments

Based on IRS IRIS Schema TY2025 v1.2.
"""

import logging
from typing import List, Optional
from datetime import date
from decimal import Decimal
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import Response

import sys
sys.path.insert(0, "src")

from supabase_client import (
    get_filer,
    get_forms_1099,
    get_form_1099,
    get_recipient,
    update_form_1099,
    log_activity,
    get_operating_years,
)
from encryption import decrypt_tin
from iris_xml_generator import (
    IRISXMLGenerator,
    TransmitterInfo,
    VendorInfo,
    IssuerInfo,
    RecipientInfo,
    StateLocalTax,
    Form1099NECData,
    Form1099MISCData,
    SubmissionBatch,
)
from iris_xml_validator import IRISXMLValidator, validate_iris_xml
from iris_client import IRISClient, IRISClientError, SubmissionStatus
from config import load_config

logger = logging.getLogger(__name__)

router = APIRouter()


def get_operating_year(operating_year_id: str) -> dict:
    """Get a single operating year by ID."""
    all_years = get_operating_years()
    for year in all_years:
        if year.get("id") == operating_year_id:
            return year
    return None


# =============================================================================
# SCHEMAS
# =============================================================================

class TransmitterConfig(BaseModel):
    """Transmitter information for e-filing."""
    tin: str = Field(..., description="Transmitter TIN (9 digits)")
    tin_type: str = Field(default="EIN", pattern="^(EIN|SSN)$")
    tcc: str = Field(..., description="Transmitter Control Code (5 chars)")
    name: str = Field(..., description="Contact person name")
    business_name: str = Field(..., description="Business name")
    business_name_2: Optional[str] = None
    address1: str
    address2: Optional[str] = None
    city: str
    state: str = Field(..., min_length=2, max_length=2)
    zip_code: str
    contact_name: str
    contact_email: str
    contact_phone: str = Field(..., description="10-digit phone number")


class EFileRequest(BaseModel):
    """Request to e-file forms for a filer."""
    filer_id: str
    operating_year_id: str
    form_type: str = Field(default="1099NEC", pattern="^(1099NEC|1099MISC)$")
    form_ids: Optional[List[str]] = Field(None, description="Specific form IDs to file. If not provided, all validated forms are filed.")
    is_test: bool = Field(default=True, description="Submit to ATS (test) or production")
    include_drafts: bool = Field(default=False, description="Include draft forms (for preview/testing only)")
    signature_pin: Optional[str] = Field(None, description="5-digit signature PIN")
    signer_name: Optional[str] = None
    signer_title: Optional[str] = None


class EFileResponse(BaseModel):
    """Response from e-file submission."""
    success: bool
    receipt_id: Optional[str] = None
    transmission_id: str
    status: str
    message: str
    record_count: int = 0
    errors: List[dict] = Field(default_factory=list)


class StatusCheckRequest(BaseModel):
    """Request to check submission status."""
    receipt_id: Optional[str] = None
    transmission_id: Optional[str] = None


class StatusResponse(BaseModel):
    """Submission status response."""
    receipt_id: str
    transmission_id: str
    status: str
    record_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    errors: List[dict] = Field(default_factory=list)


class XMLPreviewResponse(BaseModel):
    """Response containing generated XML preview."""
    xml_content: str
    form_count: int
    total_amount: float


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_transmitter_config() -> TransmitterInfo:
    """
    Get transmitter configuration.

    In production, this should come from database or environment variables.
    For now, returns placeholder that must be configured.
    """
    # TODO: Load from database or environment
    # These values should be configured per deployment
    import os

    return TransmitterInfo(
        tin=os.environ.get("TRANSMITTER_TIN", "000000000"),
        tin_type=os.environ.get("TRANSMITTER_TIN_TYPE", "EIN"),
        tcc=os.environ.get("TRANSMITTER_TCC", "DG5BW"),  # Your TCC
        name=os.environ.get("TRANSMITTER_CONTACT_NAME", ""),
        business_name=os.environ.get("TRANSMITTER_BUSINESS_NAME", ""),
        business_name_2=os.environ.get("TRANSMITTER_BUSINESS_NAME_2"),
        address1=os.environ.get("TRANSMITTER_ADDRESS1", ""),
        address2=os.environ.get("TRANSMITTER_ADDRESS2"),
        city=os.environ.get("TRANSMITTER_CITY", ""),
        state=os.environ.get("TRANSMITTER_STATE", ""),
        zip_code=os.environ.get("TRANSMITTER_ZIP", ""),
        contact_name=os.environ.get("TRANSMITTER_CONTACT_NAME", ""),
        contact_email=os.environ.get("TRANSMITTER_CONTACT_EMAIL", ""),
        contact_phone=os.environ.get("TRANSMITTER_CONTACT_PHONE", ""),
    )


def get_software_id() -> str:
    """Get IRS-assigned software ID."""
    import os
    return os.environ.get("IRS_SOFTWARE_ID", "")


def build_issuer_from_filer(filer: dict) -> IssuerInfo:
    """Convert filer database record to IssuerInfo."""
    # Decrypt TIN if encrypted
    tin = filer.get("tin", "")
    if filer.get("tin_encrypted"):
        try:
            tin = decrypt_tin(filer["tin_encrypted"])
        except Exception:
            pass  # Use plain TIN as fallback

    return IssuerInfo(
        tin=tin,
        tin_type=filer.get("tin_type", "EIN"),
        business_name=filer.get("name"),
        business_name_2=filer.get("dba_name"),
        address1=filer.get("address1", ""),
        address2=filer.get("address2"),
        city=filer.get("city", ""),
        state=filer.get("state", ""),
        zip_code=filer.get("zip", ""),
        country=filer.get("country", "US"),
        phone=filer.get("phone"),
        contact_name=filer.get("contact_name"),
        contact_email=filer.get("email"),
    )


def build_recipient_from_record(recipient: dict) -> RecipientInfo:
    """Convert recipient database record to RecipientInfo."""
    # Decrypt TIN if encrypted
    tin = recipient.get("tin", "")
    if recipient.get("tin_encrypted"):
        try:
            tin = decrypt_tin(recipient["tin_encrypted"])
        except Exception:
            pass

    tin_type = recipient.get("tin_type", "SSN")
    is_business = tin_type == "EIN"

    # Parse name into components
    name = recipient.get("name", "")
    name_parts = name.split(" ", 2)

    if is_business:
        return RecipientInfo(
            tin=tin,
            tin_type=tin_type,
            business_name=name,
            business_name_2=recipient.get("name_line_2"),
            address1=recipient.get("address1", ""),
            address2=recipient.get("address2"),
            city=recipient.get("city", ""),
            state=recipient.get("state", ""),
            zip_code=recipient.get("zip", ""),
            account_number=recipient.get("account_number"),
        )
    else:
        first_name = name_parts[0] if len(name_parts) > 0 else ""
        middle_name = name_parts[1] if len(name_parts) > 2 else ""
        last_name = name_parts[-1] if len(name_parts) > 1 else name_parts[0]

        return RecipientInfo(
            tin=tin,
            tin_type=tin_type,
            first_name=first_name,
            middle_name=middle_name if middle_name else None,
            last_name=last_name,
            address1=recipient.get("address1", ""),
            address2=recipient.get("address2"),
            city=recipient.get("city", ""),
            state=recipient.get("state", ""),
            zip_code=recipient.get("zip", ""),
            account_number=recipient.get("account_number"),
        )


def build_state_taxes(form: dict) -> List[StateLocalTax]:
    """Build state/local tax info from form record."""
    taxes = []

    if form.get("state1_code"):
        taxes.append(StateLocalTax(
            state_code=form["state1_code"],
            state_id_number=form.get("state1_id"),
            state_tax_withheld=Decimal(str(form.get("state1_withheld") or 0)),
            state_income=Decimal(str(form.get("state1_income") or 0)),
        ))

    if form.get("state2_code"):
        taxes.append(StateLocalTax(
            state_code=form["state2_code"],
            state_id_number=form.get("state2_id"),
            state_tax_withheld=Decimal(str(form.get("state2_withheld") or 0)),
            state_income=Decimal(str(form.get("state2_income") or 0)),
        ))

    return taxes


def build_nec_form(form: dict, recipient: RecipientInfo, record_id: str, tax_year: int) -> Form1099NECData:
    """Build 1099-NEC form data from database record."""
    state_taxes = build_state_taxes(form)

    return Form1099NECData(
        record_id=record_id,
        tax_year=tax_year,
        recipient=recipient,
        nonemployee_compensation=Decimal(str(form.get("nec_box1") or 0)),
        direct_sales_indicator=bool(form.get("nec_box2")),
        federal_tax_withheld=Decimal(str(form.get("nec_box4") or 0)),
        state_local_taxes=state_taxes,
        is_corrected=bool(form.get("is_correction")),
        cfsf_states=[st.state_code for st in state_taxes],
    )


def build_misc_form(form: dict, recipient: RecipientInfo, record_id: str, tax_year: int) -> Form1099MISCData:
    """Build 1099-MISC form data from database record."""
    state_taxes = build_state_taxes(form)

    return Form1099MISCData(
        record_id=record_id,
        tax_year=tax_year,
        recipient=recipient,
        rents=Decimal(str(form.get("misc_box1") or 0)),
        royalties=Decimal(str(form.get("misc_box2") or 0)),
        other_income=Decimal(str(form.get("misc_box3") or 0)),
        federal_tax_withheld=Decimal(str(form.get("misc_box4") or 0)),
        fishing_boat_proceeds=Decimal(str(form.get("misc_box5") or 0)),
        medical_healthcare_payments=Decimal(str(form.get("misc_box6") or 0)),
        direct_sales_indicator=bool(form.get("misc_box7")),
        substitute_payments=Decimal(str(form.get("misc_box8") or 0)),
        crop_insurance_proceeds=Decimal(str(form.get("misc_box9") or 0)),
        gross_proceeds_attorney=Decimal(str(form.get("misc_box10") or 0)),
        fish_purchased_resale=Decimal(str(form.get("misc_box11") or 0)),
        section_409a_deferrals=Decimal(str(form.get("misc_box12") or 0)),
        nonqualified_deferred_comp=Decimal(str(form.get("misc_box14") or 0)),
        state_local_taxes=state_taxes,
        is_corrected=bool(form.get("is_correction")),
        cfsf_states=[st.state_code for st in state_taxes],
    )


# =============================================================================
# API ENDPOINTS
# =============================================================================

@router.post("/preview-xml")
async def preview_xml(request: EFileRequest) -> Response:
    """
    Generate and preview IRIS XML without submitting.

    Returns the XML content that would be submitted to IRS.
    Useful for validation and debugging.
    """
    try:
        # Get filer
        filer = get_filer(request.filer_id)
        if not filer:
            raise HTTPException(status_code=404, detail="Filer not found")

        # Get operating year for tax year
        op_year = get_operating_year(request.operating_year_id)
        if not op_year:
            raise HTTPException(status_code=404, detail="Operating year not found")
        tax_year = op_year.get("tax_year", 2025)

        # Get forms
        all_forms = get_forms_1099(request.filer_id, request.operating_year_id)

        # Filter by form type and IDs
        form_type_filter = "1099-NEC" if request.form_type == "1099NEC" else "1099-MISC"
        forms = [f for f in all_forms if f.get("form_type") == form_type_filter]

        if request.form_ids:
            forms = [f for f in forms if f.get("id") in request.form_ids]
        elif request.include_drafts:
            # Include all forms (draft, validated, etc.) for preview/testing
            pass  # Keep all forms
        else:
            # Only include validated forms
            forms = [f for f in forms if f.get("status") == "validated"]

        if not forms:
            status_hint = " (try include_drafts=true for testing)" if not request.include_drafts else ""
            raise HTTPException(
                status_code=400,
                detail=f"No validated forms found to e-file{status_hint}"
            )

        # Build submission batch
        issuer = build_issuer_from_filer(filer)
        form_data_list = []

        for i, form in enumerate(forms, 1):
            # Get recipient
            recipient_record = get_recipient(form.get("recipient_id"))
            if not recipient_record:
                continue

            recipient = build_recipient_from_record(recipient_record)

            if request.form_type == "1099NEC":
                form_data = build_nec_form(form, recipient, str(i), tax_year)
            else:
                form_data = build_misc_form(form, recipient, str(i), tax_year)

            form_data_list.append(form_data)

        batch = SubmissionBatch(
            issuer=issuer,
            form_type=request.form_type,
            tax_year=tax_year,
            forms=form_data_list,
            signature_pin=request.signature_pin,
            signer_name=request.signer_name,
            signature_title=request.signer_title,
            signature_date=date.today(),
            cfsf_election=any(len(f.state_local_taxes) > 0 for f in form_data_list),
        )

        # Generate XML
        transmitter = get_transmitter_config()
        software_id = get_software_id()

        generator = IRISXMLGenerator(
            transmitter=transmitter,
            software_id=software_id,
            is_test=request.is_test,
        )

        xml_content = generator.generate_transmission(
            batches=[batch],
            tax_year=tax_year,
        )

        return Response(
            content=xml_content,
            media_type="application/xml",
            headers={
                "Content-Disposition": f"attachment; filename=iris_submission_{request.filer_id}_{tax_year}.xml"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error generating XML preview")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/submit", response_model=EFileResponse)
async def submit_efile(
    request: EFileRequest,
    background_tasks: BackgroundTasks,
):
    """
    Submit 1099 forms to IRS IRIS.

    This endpoint:
    1. Generates IRIS-compliant XML
    2. Submits to IRS (ATS for test, production otherwise)
    3. Returns receipt ID for status tracking
    4. Updates form records with submission info
    """
    try:
        # Get filer
        filer = get_filer(request.filer_id)
        if not filer:
            raise HTTPException(status_code=404, detail="Filer not found")

        # Get operating year
        op_year = get_operating_year(request.operating_year_id)
        if not op_year:
            raise HTTPException(status_code=404, detail="Operating year not found")
        tax_year = op_year.get("tax_year", 2025)

        # Get forms
        all_forms = get_forms_1099(request.filer_id, request.operating_year_id)

        form_type_filter = "1099-NEC" if request.form_type == "1099NEC" else "1099-MISC"
        forms = [f for f in all_forms if f.get("form_type") == form_type_filter]

        if request.form_ids:
            forms = [f for f in forms if f.get("id") in request.form_ids]
        else:
            forms = [f for f in forms if f.get("status") == "validated"]

        if not forms:
            raise HTTPException(
                status_code=400,
                detail="No validated forms found to e-file"
            )

        # Build submission
        issuer = build_issuer_from_filer(filer)
        form_data_list = []
        form_id_map = {}  # Map record_id to form database id

        for i, form in enumerate(forms, 1):
            recipient_record = get_recipient(form.get("recipient_id"))
            if not recipient_record:
                continue

            recipient = build_recipient_from_record(recipient_record)
            record_id = str(i)
            form_id_map[record_id] = form.get("id")

            if request.form_type == "1099NEC":
                form_data = build_nec_form(form, recipient, record_id, tax_year)
            else:
                form_data = build_misc_form(form, recipient, record_id, tax_year)

            form_data_list.append(form_data)

        batch = SubmissionBatch(
            issuer=issuer,
            form_type=request.form_type,
            tax_year=tax_year,
            forms=form_data_list,
            signature_pin=request.signature_pin,
            signer_name=request.signer_name,
            signature_title=request.signer_title,
            signature_date=date.today(),
            cfsf_election=any(len(f.state_local_taxes) > 0 for f in form_data_list),
        )

        # Generate XML
        transmitter = get_transmitter_config()
        software_id = get_software_id()

        generator = IRISXMLGenerator(
            transmitter=transmitter,
            software_id=software_id,
            is_test=request.is_test,
        )

        xml_bytes = generator.generate_transmission_bytes(
            batches=[batch],
            tax_year=tax_year,
        )

        # Validate XML before submission
        is_valid, validation_errors = validate_iris_xml(xml_bytes)
        if not is_valid:
            error_messages = [e["message"] for e in validation_errors if e.get("type") == "error"]
            logger.error(f"XML validation failed: {error_messages[:5]}")
            return EFileResponse(
                success=False,
                transmission_id="",
                status="validation_error",
                message=f"XML validation failed: {error_messages[0] if error_messages else 'Unknown error'}",
                record_count=len(form_data_list),
                errors=validation_errors[:10],  # Limit errors returned
            )

        # Submit to IRS
        try:
            config = load_config()
            client = IRISClient(config)
            result = client.submit_xml(xml_bytes)
        except IRISClientError as e:
            logger.error(f"IRIS submission failed: {e}")
            return EFileResponse(
                success=False,
                transmission_id="",
                status="error",
                message=str(e),
                record_count=len(form_data_list),
            )
        except Exception as e:
            logger.error(f"IRIS submission error: {e}")
            return EFileResponse(
                success=False,
                transmission_id="",
                status="error",
                message=f"Submission error: {type(e).__name__}",
                record_count=len(form_data_list),
            )

        # Update form records with submission info
        for record_id, form_id in form_id_map.items():
            update_form_1099(form_id, {
                "status": "submitted",
                "submission_id": result.receipt_id,
                "irs_status": result.status.value,
            })

        # Log activity
        log_activity(
            action="forms_submitted_to_irs",
            entity_type="efile_submission",
            entity_id=result.receipt_id,
            filer_id=request.filer_id,
            operating_year_id=request.operating_year_id,
            details={
                "form_type": request.form_type,
                "form_count": len(form_data_list),
                "transmission_id": result.unique_transmission_id,
                "is_test": request.is_test,
            },
        )

        return EFileResponse(
            success=result.is_success,
            receipt_id=result.receipt_id,
            transmission_id=result.unique_transmission_id,
            status=result.status.value,
            message=result.message,
            record_count=result.record_count,
            errors=[
                {
                    "record_id": e.record_id,
                    "code": e.error_code,
                    "message": e.error_message,
                    "field": e.field_name,
                }
                for e in result.errors
            ],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error submitting to IRS")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/status", response_model=StatusResponse)
async def check_status(request: StatusCheckRequest):
    """
    Check the status of a previous submission.

    Provide either receipt_id (from IRS) or transmission_id (our ID).
    """
    if not request.receipt_id and not request.transmission_id:
        raise HTTPException(
            status_code=400,
            detail="Either receipt_id or transmission_id is required"
        )

    try:
        config = load_config()
        client = IRISClient(config)

        result = client.get_status(
            receipt_id=request.receipt_id,
            transmission_id=request.transmission_id,
        )

        return StatusResponse(
            receipt_id=result.receipt_id,
            transmission_id=result.unique_transmission_id,
            status=result.status.value,
            record_count=result.record_count,
            accepted_count=result.accepted_count,
            rejected_count=result.rejected_count,
            errors=[
                {
                    "record_id": e.record_id,
                    "code": e.error_code,
                    "message": e.error_message,
                    "field": e.field_name,
                }
                for e in result.errors
            ],
        )

    except IRISClientError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error checking status")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/acknowledgment")
async def get_acknowledgment(request: StatusCheckRequest):
    """
    Retrieve detailed acknowledgment for a submission.

    Returns form-by-form acceptance/rejection details.
    """
    if not request.receipt_id and not request.transmission_id:
        raise HTTPException(
            status_code=400,
            detail="Either receipt_id or transmission_id is required"
        )

    try:
        config = load_config()
        client = IRISClient(config)

        ack = client.get_acknowledgment(
            receipt_id=request.receipt_id,
            transmission_id=request.transmission_id,
        )

        return {
            "receipt_id": ack.receipt_id,
            "transmission_id": ack.transmission_id,
            "status": ack.status.value,
            "timestamp": ack.timestamp.isoformat() if ack.timestamp else None,
            "form_results": ack.form_results,
            "errors": [
                {
                    "record_id": e.record_id,
                    "code": e.error_code,
                    "message": e.error_message,
                    "field": e.field_name,
                }
                for e in ack.errors
            ],
        }

    except IRISClientError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error retrieving acknowledgment")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/validate-xml")
async def validate_xml_submission(request: EFileRequest):
    """
    Validate XML that would be generated for submission.

    Performs schema validation without actually submitting to IRS.
    Returns validation errors if any.
    """
    try:
        # Get filer
        filer = get_filer(request.filer_id)
        if not filer:
            raise HTTPException(status_code=404, detail="Filer not found")

        # Get operating year
        op_year = get_operating_year(request.operating_year_id)
        if not op_year:
            raise HTTPException(status_code=404, detail="Operating year not found")
        tax_year = op_year.get("tax_year", 2025)

        # Get forms
        all_forms = get_forms_1099(request.filer_id, request.operating_year_id)

        form_type_filter = "1099-NEC" if request.form_type == "1099NEC" else "1099-MISC"
        forms = [f for f in all_forms if f.get("form_type") == form_type_filter]

        if request.form_ids:
            forms = [f for f in forms if f.get("id") in request.form_ids]
        else:
            forms = [f for f in forms if f.get("status") == "validated"]

        if not forms:
            raise HTTPException(
                status_code=400,
                detail="No validated forms found to validate"
            )

        # Build submission
        issuer = build_issuer_from_filer(filer)
        form_data_list = []

        for i, form in enumerate(forms, 1):
            recipient_record = get_recipient(form.get("recipient_id"))
            if not recipient_record:
                continue

            recipient = build_recipient_from_record(recipient_record)

            if request.form_type == "1099NEC":
                form_data = build_nec_form(form, recipient, str(i), tax_year)
            else:
                form_data = build_misc_form(form, recipient, str(i), tax_year)

            form_data_list.append(form_data)

        batch = SubmissionBatch(
            issuer=issuer,
            form_type=request.form_type,
            tax_year=tax_year,
            forms=form_data_list,
            signature_pin=request.signature_pin,
            signer_name=request.signer_name,
            signature_title=request.signer_title,
            signature_date=date.today(),
            cfsf_election=any(len(f.state_local_taxes) > 0 for f in form_data_list),
        )

        # Generate XML
        transmitter = get_transmitter_config()
        software_id = get_software_id()

        generator = IRISXMLGenerator(
            transmitter=transmitter,
            software_id=software_id,
            is_test=request.is_test,
        )

        xml_bytes = generator.generate_transmission_bytes(
            batches=[batch],
            tax_year=tax_year,
        )

        # Validate
        is_valid, errors = validate_iris_xml(xml_bytes)

        return {
            "is_valid": is_valid,
            "form_count": len(form_data_list),
            "error_count": len([e for e in errors if e.get("type") == "error"]),
            "warning_count": len([e for e in errors if e.get("type") == "warning"]),
            "errors": errors,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error validating XML")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/transmitter-config")
async def get_current_transmitter_config():
    """
    Get current transmitter configuration (masked).

    Used to verify transmitter setup before filing.
    """
    config = get_transmitter_config()

    # Mask sensitive data
    tin_masked = f"***-**-{config.tin[-4:]}" if len(config.tin) >= 4 else "***"

    return {
        "tin_masked": tin_masked,
        "tin_type": config.tin_type,
        "tcc": config.tcc,
        "business_name": config.business_name,
        "city": config.city,
        "state": config.state,
        "contact_name": config.contact_name,
        "contact_email": config.contact_email,
        "is_configured": bool(config.tin and config.tcc and config.business_name),
    }
