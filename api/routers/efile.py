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
    update_filing_status_on_submit,
    update_filing_status_on_check,
    # ATS submission tracking
    save_ats_submission,
    get_ats_submissions,
    get_ats_submission,
    get_accepted_ats_originals,
    update_ats_submission_status,
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
    Form1099SData,
    Form1098Data,
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
    form_type: str = Field(default="1099NEC", pattern="^(1099NEC|1099MISC|1099S|1098)$")
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
    message: str = ""
    record_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    errors: List[dict] = Field(default_factory=list)


class XMLPreviewResponse(BaseModel):
    """Response containing generated XML preview."""
    xml_content: str
    form_count: int
    total_amount: float


class FormValidationError(BaseModel):
    """A single validation error for a form."""
    row: int = Field(..., description="Row number in the data set (1-indexed)")
    field: str = Field(..., description="Field name with the issue")
    message: str = Field(..., description="User-friendly error message")
    severity: str = Field(default="error", description="error or warning")
    recipient_name: Optional[str] = Field(None, description="Recipient name for context")


class FormValidationResponse(BaseModel):
    """Response from form validation."""
    is_valid: bool
    form_count: int
    error_count: int
    warning_count: int
    errors: List[FormValidationError] = Field(default_factory=list)


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


def build_1099s_form(form: dict, recipient: RecipientInfo, record_id: str, tax_year: int) -> Form1099SData:
    """Build 1099-S form data from database record."""
    # Parse closing date
    closing_date = None
    closing_date_str = form.get("s_box1")
    if closing_date_str:
        try:
            if isinstance(closing_date_str, str):
                closing_date = date.fromisoformat(closing_date_str[:10])
            elif isinstance(closing_date_str, date):
                closing_date = closing_date_str
        except (ValueError, TypeError):
            pass

    return Form1099SData(
        record_id=record_id,
        tax_year=tax_year,
        recipient=recipient,
        closing_date=closing_date,
        gross_proceeds=Decimal(str(form.get("s_box2") or 0)),
        address_or_legal_desc=str(form.get("s_box3") or ""),
        transferor_received_consideration=bool(form.get("s_box4")),
        transferor_is_foreign_person=bool(form.get("s_box5")),
        buyers_real_estate_tax=Decimal(str(form.get("s_box6") or 0)),
        is_corrected=bool(form.get("is_correction")),
    )


def build_1098_form(form: dict, recipient: RecipientInfo, record_id: str, tax_year: int) -> Form1098Data:
    """Build 1098 form data from database record."""
    # Parse dates
    origination_date = None
    orig_date_str = form.get("mort_box3")
    if orig_date_str:
        try:
            if isinstance(orig_date_str, str):
                origination_date = date.fromisoformat(orig_date_str[:10])
            elif isinstance(orig_date_str, date):
                origination_date = orig_date_str
        except (ValueError, TypeError):
            pass

    acquisition_date = None
    acq_date_str = form.get("mort_box11")
    if acq_date_str:
        try:
            if isinstance(acq_date_str, str):
                acquisition_date = date.fromisoformat(acq_date_str[:10])
            elif isinstance(acq_date_str, date):
                acquisition_date = acq_date_str
        except (ValueError, TypeError):
            pass

    return Form1098Data(
        record_id=record_id,
        tax_year=tax_year,
        recipient=recipient,
        mortgage_interest_received=Decimal(str(form.get("mort_box1") or 0)),
        outstanding_mortgage_principal=Decimal(str(form.get("mort_box2") or 0)),
        mortgage_origination_date=origination_date,
        refund_of_overpaid_interest=Decimal(str(form.get("mort_box4") or 0)),
        mortgage_insurance_premiums=Decimal(str(form.get("mort_box5") or 0)),
        points_paid_on_purchase=Decimal(str(form.get("mort_box6") or 0)),
        property_address_same_as_borrower=bool(form.get("mort_box7")),
        property_address=str(form.get("mort_box8") or ""),
        properties_securing_mortgage_count=int(form.get("mort_box9") or 0),
        other_info=str(form.get("mort_box10") or ""),
        mortgage_acquisition_date=acquisition_date,
        is_corrected=bool(form.get("is_correction")),
    )


# Form type mapping from API to database
FORM_TYPE_DB_MAP = {
    "1099NEC": "1099-NEC",
    "1099MISC": "1099-MISC",
    "1099S": "1099-S",
    "1098": "1098",
}


# =============================================================================
# FORM VALIDATION HELPERS
# =============================================================================

# Valid US state codes (includes DC and territories)
VALID_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
    "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
    "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI",
    "WY", "AS", "GU", "MP", "PR", "VI", "FM", "MH", "PW",
}


def normalize_tin(tin: str) -> str:
    """Strip punctuation from TIN, return digits only."""
    if not tin:
        return ""
    return "".join(c for c in tin if c.isdigit())


def validate_tin_format(tin: str, tin_type: str = "SSN") -> tuple[bool, str]:
    """
    Validate TIN format.

    Returns (is_valid, error_message).
    """
    normalized = normalize_tin(tin)

    if not normalized:
        return False, "TIN is missing"

    if len(normalized) != 9:
        return False, f"TIN must be 9 digits (got {len(normalized)})"

    # Check for invalid patterns
    if normalized == "000000000":
        return False, "TIN cannot be all zeros"

    if tin_type == "SSN":
        # SSN format: XXX-XX-XXXX
        # Area number (first 3) cannot be 000, 666, or 900-999
        area = int(normalized[:3])
        if area == 0 or area == 666 or area >= 900:
            return False, f"Invalid SSN area number: {area:03d}"
        # Group number (middle 2) cannot be 00
        if normalized[3:5] == "00":
            return False, "Invalid SSN group number: 00"
        # Serial number (last 4) cannot be 0000
        if normalized[5:] == "0000":
            return False, "Invalid SSN serial number: 0000"

    return True, ""


def validate_zip_code(zip_code: str) -> tuple[bool, str]:
    """Validate ZIP code format."""
    if not zip_code:
        return False, "ZIP code is missing"

    # Remove any spaces or dashes
    cleaned = zip_code.replace("-", "").replace(" ", "")

    if not cleaned.isdigit():
        return False, "ZIP code must be numeric"

    if len(cleaned) not in (5, 9):
        return False, f"ZIP code must be 5 or 9 digits (got {len(cleaned)})"

    return True, ""


def validate_amount(amount, field_name: str, allow_zero: bool = True, max_amount: float = 99999999.99) -> tuple[bool, str]:
    """Validate a monetary amount."""
    if amount is None:
        return True, ""  # None amounts are OK (treated as 0)

    try:
        value = float(amount)
    except (ValueError, TypeError):
        return False, f"{field_name} must be a number"

    if value < 0:
        return False, f"{field_name} cannot be negative"

    if not allow_zero and value == 0:
        return False, f"{field_name} cannot be zero"

    if value > max_amount:
        return False, f"{field_name} exceeds maximum ({max_amount:,.2f})"

    return True, ""


def validate_form_data(
    row_num: int,
    form: dict,
    recipient: dict,
    form_type: str,
) -> List[FormValidationError]:
    """
    Validate a single form and its recipient data.

    Returns list of validation errors.
    """
    errors = []
    recipient_name = recipient.get("name", "Unknown")

    def add_error(field: str, message: str, severity: str = "error"):
        errors.append(FormValidationError(
            row=row_num,
            field=field,
            message=f"Row {row_num}: {message}",
            severity=severity,
            recipient_name=recipient_name,
        ))

    def add_warning(field: str, message: str):
        add_error(field, message, severity="warning")

    # -----------------------------
    # Recipient Validation
    # -----------------------------

    # TIN validation
    tin = recipient.get("tin_encrypted") or recipient.get("tin", "")
    tin_type = recipient.get("tin_type", "SSN")

    # If TIN is encrypted, try to decrypt for validation
    if recipient.get("tin_encrypted"):
        try:
            tin = decrypt_tin(recipient["tin_encrypted"])
        except Exception:
            tin = ""  # Will fail validation

    tin_valid, tin_error = validate_tin_format(tin, tin_type)
    if not tin_valid:
        add_error("tin", tin_error)

    # Name validation
    if not recipient.get("name") or not recipient.get("name", "").strip():
        add_error("name", "Recipient name is missing")
    elif len(recipient.get("name", "")) > 80:
        add_error("name", "Recipient name too long (max 80 characters)")

    # Address validation
    if not recipient.get("address1") or not recipient.get("address1", "").strip():
        add_error("address1", "Street address is missing")
    elif len(recipient.get("address1", "")) > 40:
        add_error("address1", "Street address too long (max 40 characters)")

    if recipient.get("address2") and len(recipient.get("address2", "")) > 40:
        add_warning("address2", "Address line 2 too long (max 40 characters)")

    if not recipient.get("city") or not recipient.get("city", "").strip():
        add_error("city", "City is missing")
    elif len(recipient.get("city", "")) > 25:
        add_error("city", "City name too long (max 25 characters)")

    # State validation
    state = recipient.get("state", "").upper().strip()
    if not state:
        add_error("state", "State is missing")
    elif state not in VALID_STATE_CODES:
        add_error("state", f"Invalid state code: {state}")

    # ZIP validation
    zip_valid, zip_error = validate_zip_code(recipient.get("zip", ""))
    if not zip_valid:
        add_error("zip", zip_error)

    # -----------------------------
    # Amount Validation
    # -----------------------------

    if form_type == "1099-NEC":
        # NEC Box 1: Nonemployee compensation (required, cannot be zero for filing)
        nec_box1 = form.get("nec_box1")
        valid, msg = validate_amount(nec_box1, "Nonemployee compensation (Box 1)")
        if not valid:
            add_error("nec_box1", msg)
        elif nec_box1 is None or float(nec_box1 or 0) == 0:
            add_warning("nec_box1", "Nonemployee compensation (Box 1) is zero - form may not be required")

        # NEC Box 4: Federal tax withheld
        valid, msg = validate_amount(form.get("nec_box4"), "Federal tax withheld (Box 4)")
        if not valid:
            add_error("nec_box4", msg)

    elif form_type == "1099-MISC":
        # MISC has many boxes - validate the common ones
        amount_fields = [
            ("misc_box1", "Rents (Box 1)"),
            ("misc_box2", "Royalties (Box 2)"),
            ("misc_box3", "Other income (Box 3)"),
            ("misc_box4", "Federal tax withheld (Box 4)"),
            ("misc_box5", "Fishing boat proceeds (Box 5)"),
            ("misc_box6", "Medical payments (Box 6)"),
            ("misc_box8", "Substitute payments (Box 8)"),
            ("misc_box9", "Crop insurance (Box 9)"),
            ("misc_box10", "Attorney proceeds (Box 10)"),
            ("misc_box11", "Fish purchased (Box 11)"),
            ("misc_box12", "Section 409A deferrals (Box 12)"),
            ("misc_box14", "Nonqualified deferred comp (Box 14)"),
        ]

        has_any_amount = False
        for field, label in amount_fields:
            valid, msg = validate_amount(form.get(field), label)
            if not valid:
                add_error(field, msg)
            elif form.get(field) and float(form.get(field) or 0) > 0:
                has_any_amount = True

        if not has_any_amount:
            add_warning("amounts", "No amounts entered - form may not be required")

    elif form_type == "1099-S":
        # 1099-S: Real estate transaction
        # Box 2: Gross proceeds (required)
        s_box2 = form.get("s_box2")
        valid, msg = validate_amount(s_box2, "Gross proceeds (Box 2)")
        if not valid:
            add_error("s_box2", msg)
        elif s_box2 is None or float(s_box2 or 0) == 0:
            add_warning("s_box2", "Gross proceeds (Box 2) is zero - form may not be required")

        # Box 6: Buyer's real estate tax
        valid, msg = validate_amount(form.get("s_box6"), "Buyer's real estate tax (Box 6)")
        if not valid:
            add_error("s_box6", msg)

        # Box 3: Address or legal description
        if not form.get("s_box3") or not str(form.get("s_box3", "")).strip():
            add_warning("s_box3", "Property address/description (Box 3) is empty")

    elif form_type == "1098":
        # 1098: Mortgage interest statement
        # Box 1: Mortgage interest received (required)
        mort_box1 = form.get("mort_box1")
        valid, msg = validate_amount(mort_box1, "Mortgage interest received (Box 1)")
        if not valid:
            add_error("mort_box1", msg)
        elif mort_box1 is None or float(mort_box1 or 0) == 0:
            add_warning("mort_box1", "Mortgage interest (Box 1) is zero - form may not be required")

        # Box 2: Outstanding mortgage principal
        valid, msg = validate_amount(form.get("mort_box2"), "Outstanding principal (Box 2)")
        if not valid:
            add_error("mort_box2", msg)

        # Box 4: Refund of overpaid interest
        valid, msg = validate_amount(form.get("mort_box4"), "Refund of overpaid interest (Box 4)")
        if not valid:
            add_error("mort_box4", msg)

        # Box 5: Mortgage insurance premiums
        valid, msg = validate_amount(form.get("mort_box5"), "Mortgage insurance premiums (Box 5)")
        if not valid:
            add_error("mort_box5", msg)

        # Box 6: Points paid
        valid, msg = validate_amount(form.get("mort_box6"), "Points paid (Box 6)")
        if not valid:
            add_error("mort_box6", msg)

    # -----------------------------
    # State Withholding Validation (for NEC and MISC only)
    # -----------------------------

    # If state withholding is present, state info must be present
    if form.get("state1_withheld") and float(form.get("state1_withheld") or 0) > 0:
        if not form.get("state1_code"):
            add_error("state1_code", "State 1 withholding requires a state code")
        elif form.get("state1_code") not in VALID_STATE_CODES:
            add_error("state1_code", f"Invalid state code: {form.get('state1_code')}")

        valid, msg = validate_amount(form.get("state1_withheld"), "State 1 withholding")
        if not valid:
            add_error("state1_withheld", msg)

    if form.get("state2_withheld") and float(form.get("state2_withheld") or 0) > 0:
        if not form.get("state2_code"):
            add_error("state2_code", "State 2 withholding requires a state code")
        elif form.get("state2_code") not in VALID_STATE_CODES:
            add_error("state2_code", f"Invalid state code: {form.get('state2_code')}")

        valid, msg = validate_amount(form.get("state2_withheld"), "State 2 withholding")
        if not valid:
            add_error("state2_withheld", msg)

    # If state income is present, state code should be present
    if form.get("state1_income") and float(form.get("state1_income") or 0) > 0:
        if not form.get("state1_code"):
            add_warning("state1_code", "State 1 income without state code")

    if form.get("state2_income") and float(form.get("state2_income") or 0) > 0:
        if not form.get("state2_code"):
            add_warning("state2_code", "State 2 income without state code")

    # -----------------------------
    # Federal Withholding Validation (NEC and MISC only)
    # -----------------------------

    # Federal withholding shouldn't exceed income (for forms that have withholding)
    if form_type in ("1099-NEC", "1099-MISC"):
        federal_withheld = float(form.get("nec_box4") or form.get("misc_box4") or 0)
        if form_type == "1099-NEC":
            total_income = float(form.get("nec_box1") or 0)
        else:
            total_income = sum(
                float(form.get(f"misc_box{i}") or 0)
                for i in [1, 2, 3, 5, 6, 8, 9, 10, 11, 12, 14]
            )

        if federal_withheld > 0 and total_income > 0 and federal_withheld > total_income:
            add_warning("federal_withheld", f"Federal withholding (${federal_withheld:,.2f}) exceeds total income (${total_income:,.2f})")

    return errors


def validate_filer_data(filer: dict) -> List[FormValidationError]:
    """
    Validate filer/issuer data.

    Returns list of validation errors.
    """
    errors = []

    def add_error(field: str, message: str, severity: str = "error"):
        errors.append(FormValidationError(
            row=0,  # 0 indicates filer-level error
            field=f"filer.{field}",
            message=f"Filer: {message}",
            severity=severity,
            recipient_name=None,
        ))

    # TIN validation
    tin = filer.get("tin_encrypted") or filer.get("tin", "")
    if filer.get("tin_encrypted"):
        try:
            tin = decrypt_tin(filer["tin_encrypted"])
        except Exception:
            tin = ""

    tin_valid, tin_error = validate_tin_format(tin, filer.get("tin_type", "EIN"))
    if not tin_valid:
        add_error("tin", tin_error)

    # Name validation
    if not filer.get("name"):
        add_error("name", "Filer name is missing")

    # Address validation
    if not filer.get("address1"):
        add_error("address1", "Filer street address is missing")
    if not filer.get("city"):
        add_error("city", "Filer city is missing")

    state = filer.get("state", "").upper().strip()
    if not state:
        add_error("state", "Filer state is missing")
    elif state not in VALID_STATE_CODES:
        add_error("state", f"Invalid filer state code: {state}")

    zip_valid, zip_error = validate_zip_code(filer.get("zip", ""))
    if not zip_valid:
        add_error("zip", f"Filer {zip_error.lower()}")

    return errors


# =============================================================================
# API ENDPOINTS
# =============================================================================

@router.post("/validate-forms", response_model=FormValidationResponse)
async def validate_forms(request: EFileRequest):
    """
    Validate form data before XML generation.

    This is step 1 of the pre-transmit validation flow:
    1. validate-forms - Check row-level business rules (TIN format, required fields, amounts)
    2. validate-xml - Check generated XML against IRS schema (XSD validation)

    Returns user-friendly error messages identifying specific rows and fields.
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

        # Get forms
        all_forms = get_forms_1099(request.filer_id, request.operating_year_id)

        form_type_filter = FORM_TYPE_DB_MAP.get(request.form_type, request.form_type)
        forms = [f for f in all_forms if f.get("form_type") == form_type_filter]

        if request.form_ids:
            forms = [f for f in forms if f.get("id") in request.form_ids]
        elif request.include_drafts:
            pass  # Include all forms
        else:
            forms = [f for f in forms if f.get("status") in ("validated", "draft")]

        if not forms:
            raise HTTPException(
                status_code=400,
                detail=f"No {form_type_filter} forms found to validate"
            )

        all_errors: List[FormValidationError] = []

        # Validate filer first
        filer_errors = validate_filer_data(filer)
        all_errors.extend(filer_errors)

        # Validate each form
        for i, form in enumerate(forms, 1):
            recipient = get_recipient(form.get("recipient_id"))
            if not recipient:
                all_errors.append(FormValidationError(
                    row=i,
                    field="recipient_id",
                    message=f"Row {i}: Recipient not found",
                    severity="error",
                    recipient_name=None,
                ))
                continue

            form_errors = validate_form_data(i, form, recipient, form_type_filter)
            all_errors.extend(form_errors)

        # Count errors and warnings
        error_count = len([e for e in all_errors if e.severity == "error"])
        warning_count = len([e for e in all_errors if e.severity == "warning"])

        return FormValidationResponse(
            is_valid=error_count == 0,
            form_count=len(forms),
            error_count=error_count,
            warning_count=warning_count,
            errors=all_errors,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error validating forms")
        raise HTTPException(status_code=500, detail=str(e))


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
        form_type_filter = FORM_TYPE_DB_MAP.get(request.form_type, request.form_type)
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
                detail=f"No validated {form_type_filter} forms found to e-file{status_hint}"
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
            elif request.form_type == "1099MISC":
                form_data = build_misc_form(form, recipient, str(i), tax_year)
            elif request.form_type == "1099S":
                form_data = build_1099s_form(form, recipient, str(i), tax_year)
            elif request.form_type == "1098":
                form_data = build_1098_form(form, recipient, str(i), tax_year)
            else:
                continue  # Skip unknown form types

            form_data_list.append(form_data)

        # Determine CFSF election - only for forms that support state withholding
        has_cfsf = False
        if request.form_type in ("1099NEC", "1099MISC") and form_data_list:
            has_cfsf = any(hasattr(f, 'state_local_taxes') and len(f.state_local_taxes) > 0 for f in form_data_list)

        batch = SubmissionBatch(
            issuer=issuer,
            form_type=request.form_type,
            tax_year=tax_year,
            forms=form_data_list,
            signature_pin=request.signature_pin,
            signer_name=request.signer_name,
            signature_title=request.signer_title,
            signature_date=date.today(),
            cfsf_election=has_cfsf,
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

        form_type_filter = FORM_TYPE_DB_MAP.get(request.form_type, request.form_type)
        forms = [f for f in all_forms if f.get("form_type") == form_type_filter]

        if request.form_ids:
            forms = [f for f in forms if f.get("id") in request.form_ids]
        elif request.include_drafts:
            pass  # Include all forms (for testing/initial filing)
        else:
            forms = [f for f in forms if f.get("status") == "validated"]

        if not forms:
            raise HTTPException(
                status_code=400,
                detail=f"No {form_type_filter} forms found to e-file. Make sure forms are imported and validated."
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
            db_form_id = form.get("id")
            form_id_map[record_id] = db_form_id
            logger.info(f"Mapping record_id={record_id} to form_id={db_form_id}")

            if request.form_type == "1099NEC":
                form_data = build_nec_form(form, recipient, record_id, tax_year)
            elif request.form_type == "1099MISC":
                form_data = build_misc_form(form, recipient, record_id, tax_year)
            elif request.form_type == "1099S":
                form_data = build_1099s_form(form, recipient, record_id, tax_year)
            elif request.form_type == "1098":
                form_data = build_1098_form(form, recipient, record_id, tax_year)
            else:
                continue  # Skip unknown form types

            form_data_list.append(form_data)

        # Determine CFSF election - only for forms that support state withholding
        has_cfsf = False
        if request.form_type in ("1099NEC", "1099MISC") and form_data_list:
            has_cfsf = any(hasattr(f, 'state_local_taxes') and len(f.state_local_taxes) > 0 for f in form_data_list)

        batch = SubmissionBatch(
            issuer=issuer,
            form_type=request.form_type,
            tax_year=tax_year,
            forms=form_data_list,
            signature_pin=request.signature_pin,
            signer_name=request.signer_name,
            signature_title=request.signer_title,
            signature_date=date.today(),
            cfsf_election=has_cfsf,
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
            logger.info(f"Updating form record_id={record_id}, form_id={form_id}, receipt_id={result.receipt_id}")
            try:
                update_form_1099(form_id, {
                    "status": "submitted",
                    "submission_id": result.receipt_id,
                    "irs_status": result.status.value,
                })
            except Exception as e:
                logger.error(f"Failed to update form {form_id}: {e}")

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

        # Update filer filing status (for production filings)
        if not request.is_test:
            # Map IRS status to filing status
            filing_status = "SUBMITTED"
            if result.status == SubmissionStatus.PROCESSING:
                filing_status = "PROCESSING"
            elif result.status == SubmissionStatus.ACCEPTED:
                filing_status = "ACCEPTED"
            elif result.status == SubmissionStatus.ACCEPTED_WITH_ERRORS:
                filing_status = "ACCEPTED_WITH_ERRORS"
            elif result.status == SubmissionStatus.REJECTED:
                filing_status = "REJECTED"

            try:
                # Get tenant_id from filer
                tenant_id = filer.get("tenant_id")
                if tenant_id:
                    update_filing_status_on_submit(
                        tenant_id=tenant_id,
                        filer_id=request.filer_id,
                        tax_year=tax_year,
                        status=filing_status,
                        submission_id=None,  # We don't track submission_id table here
                        receipt_id=result.receipt_id,
                        transmission_id=result.unique_transmission_id,
                    )
            except Exception as e:
                # Don't fail the submission if filing status update fails
                logger.warning(f"Failed to update filing status: {e}")

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

        # Generate helpful message based on status
        status_messages = {
            "pending": "Submission received by IRS. Processing has not yet begun.",
            "processing": "IRS is actively processing this submission.",
            "accepted": "All forms in this submission were accepted by the IRS.",
            "accepted_with_errors": "Submission was accepted but some forms had errors.",
            "partially_accepted": "Some forms were accepted, others were rejected.",
            "rejected": "This submission was rejected by the IRS.",
            "not_found": "The IRS has not yet processed this submission. This is normal - it may take some time for new submissions to appear in the system. Please try again later.",
            "unknown": "Unable to determine submission status.",
        }
        message = status_messages.get(result.status.value, "")

        return StatusResponse(
            receipt_id=result.receipt_id,
            transmission_id=result.unique_transmission_id,
            status=result.status.value,
            message=message,
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

        form_type_filter = FORM_TYPE_DB_MAP.get(request.form_type, request.form_type)
        forms = [f for f in all_forms if f.get("form_type") == form_type_filter]

        if request.form_ids:
            forms = [f for f in forms if f.get("id") in request.form_ids]
        else:
            forms = [f for f in forms if f.get("status") == "validated"]

        if not forms:
            raise HTTPException(
                status_code=400,
                detail=f"No validated {form_type_filter} forms found to validate"
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
            elif request.form_type == "1099MISC":
                form_data = build_misc_form(form, recipient, str(i), tax_year)
            elif request.form_type == "1099S":
                form_data = build_1099s_form(form, recipient, str(i), tax_year)
            elif request.form_type == "1098":
                form_data = build_1098_form(form, recipient, str(i), tax_year)
            else:
                continue  # Skip unknown form types

            form_data_list.append(form_data)

        # Determine CFSF election - only for forms that support state withholding
        has_cfsf = False
        if request.form_type in ("1099NEC", "1099MISC") and form_data_list:
            has_cfsf = any(hasattr(f, 'state_local_taxes') and len(f.state_local_taxes) > 0 for f in form_data_list)

        batch = SubmissionBatch(
            issuer=issuer,
            form_type=request.form_type,
            tax_year=tax_year,
            forms=form_data_list,
            signature_pin=request.signature_pin,
            signer_name=request.signer_name,
            signature_title=request.signer_title,
            signature_date=date.today(),
            cfsf_election=has_cfsf,
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
    software_id = get_software_id()

    # Mask sensitive data
    tin_masked = f"***-**-{config.tin[-4:]}" if len(config.tin) >= 4 else "***"

    # Check if all required fields are configured
    is_configured = bool(
        config.tin and
        config.tcc and
        config.business_name and
        software_id
    )

    return {
        "tin_masked": tin_masked,
        "tin_type": config.tin_type,
        "tcc": config.tcc,
        "software_id": software_id if software_id else "(not configured)",
        "business_name": config.business_name,
        "city": config.city,
        "state": config.state,
        "contact_name": config.contact_name,
        "contact_email": config.contact_email,
        "is_configured": is_configured,
    }


# =============================================================================
# FILING STATUS DASHBOARD
# =============================================================================

class FilingStatusResponse(BaseModel):
    """Single filer's filing status."""
    id: str
    filer_id: str
    filer_name: str
    filer_tin: Optional[str] = None
    tax_year: int
    status: str
    prepared_by_name: Optional[str] = None
    prepared_by_user_id: Optional[str] = None
    last_receipt_id: Optional[str] = None
    last_transmission_id: Optional[str] = None
    last_submitted_at: Optional[str] = None
    last_status_checked_at: Optional[str] = None
    last_errors: Optional[dict] = None
    notes: Optional[str] = None
    form_count: int = 0


class FilingDashboardResponse(BaseModel):
    """Filing dashboard data."""
    items: List[FilingStatusResponse]
    summary: dict


class FilingStatusUpdateRequest(BaseModel):
    """Request to update filing status (e.g., after status check)."""
    filer_id: str
    tax_year: int = 2025
    status: str = Field(..., pattern="^(NOT_FILED|SUBMITTED|PROCESSING|ACCEPTED|ACCEPTED_WITH_ERRORS|REJECTED)$")
    errors: Optional[dict] = None


class SetPreparerRequest(BaseModel):
    """Request to set/update preparer for a filer."""
    filer_id: str
    tax_year: int = 2025
    prepared_by_name: str


@router.get("/filing-dashboard")
async def get_filing_dashboard_endpoint(
    tax_year: int = Query(default=2025, ge=2020, le=2050),
    status: Optional[str] = Query(default=None, description="Filter by status"),
    preparer: Optional[str] = Query(default=None, description="Filter by preparer user ID"),
):
    """
    Get filing dashboard for all filers.

    Returns list of filers with their filing status, preparer, and form counts.
    """
    from supabase_client import get_filing_dashboard, get_filing_status_summary

    # Use default tenant for now (The Tax Shelter)
    from api.auth import DEFAULT_TENANT_ID
    tenant_id = DEFAULT_TENANT_ID

    try:
        items = get_filing_dashboard(
            tenant_id=tenant_id,
            tax_year=tax_year,
            status_filter=status,
            preparer_filter=preparer,
        )

        summary = get_filing_status_summary(tenant_id, tax_year)

        return FilingDashboardResponse(
            items=[
                FilingStatusResponse(
                    id=item.get("id", ""),
                    filer_id=item.get("filer_id", ""),
                    filer_name=item.get("filer_name", ""),
                    filer_tin=item.get("filer_tin"),
                    tax_year=item.get("tax_year", tax_year),
                    status=item.get("status", "NOT_FILED"),
                    prepared_by_name=item.get("prepared_by_name"),
                    prepared_by_user_id=item.get("prepared_by_user_id"),
                    last_receipt_id=item.get("last_receipt_id"),
                    last_transmission_id=item.get("last_transmission_id"),
                    last_submitted_at=str(item.get("last_submitted_at")) if item.get("last_submitted_at") else None,
                    last_status_checked_at=str(item.get("last_status_checked_at")) if item.get("last_status_checked_at") else None,
                    last_errors=item.get("last_errors"),
                    notes=item.get("notes"),
                    form_count=item.get("form_count", 0),
                )
                for item in (items or [])
            ],
            summary=summary,
        )

    except Exception as e:
        logger.exception("Error getting filing dashboard")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/filing-status/{filer_id}")
async def get_filer_filing_status(
    filer_id: str,
    tax_year: int = Query(default=2025, ge=2020, le=2050),
):
    """Get filing status for a specific filer."""
    from supabase_client import get_filing_status

    try:
        status = get_filing_status(filer_id, tax_year)
        if not status:
            # Return NOT_FILED if no status record exists
            return {
                "filer_id": filer_id,
                "tax_year": tax_year,
                "status": "NOT_FILED",
                "prepared_by_name": None,
                "last_receipt_id": None,
            }
        return status

    except Exception as e:
        logger.exception("Error getting filing status")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/filing-status/update")
async def update_filer_filing_status(request: FilingStatusUpdateRequest):
    """
    Update filing status for a filer.

    Called after checking IRS status to update the filer's filing status.
    """
    from api.auth import DEFAULT_TENANT_ID

    try:
        result = update_filing_status_on_check(
            tenant_id=DEFAULT_TENANT_ID,
            filer_id=request.filer_id,
            tax_year=request.tax_year,
            status=request.status,
            errors=request.errors,
        )
        return {"success": True, "data": result}

    except Exception as e:
        logger.exception("Error updating filing status")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/filing-status/set-preparer")
async def set_filer_preparer_endpoint(request: SetPreparerRequest):
    """
    Set the preparer for a filer.

    Only sets if preparer is not already assigned (first-touch attribution).
    """
    from supabase_client import set_filer_preparer
    from api.auth import DEFAULT_TENANT_ID

    try:
        # For now, we just use the name (no user_id linkage)
        result = set_filer_preparer(
            tenant_id=DEFAULT_TENANT_ID,
            filer_id=request.filer_id,
            tax_year=request.tax_year,
            user_id=None,  # Could be passed from auth context
            user_name=request.prepared_by_name,
        )
        return {"success": True, "data": result}

    except Exception as e:
        logger.exception("Error setting preparer")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/filing-status/backfill")
async def backfill_filing_status_endpoint(tax_year: int = 2025):
    """
    Backfill filing status rows for all filers with forms in a given year.

    Creates NOT_FILED status entries for any filers that don't have one yet.
    """
    from supabase_client import backfill_filing_status

    try:
        rows_inserted = backfill_filing_status(tax_year)
        return {
            "success": True,
            "rows_inserted": rows_inserted,
            "message": f"Created {rows_inserted} filing status rows for tax year {tax_year}",
        }

    except Exception as e:
        logger.exception("Error backfilling filing status")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ATS CERTIFICATION TEST
# =============================================================================

class ATSTestRequest(BaseModel):
    """Request for ATS certification test submission."""
    form_type: str = Field(default="1099NEC", pattern="^(1099NEC|1099MISC|1099S|1098)$")
    tax_year: int = Field(default=2025, ge=2020, le=2030)
    # CF/SF (Combined Federal/State Filing) test mode
    # When enabled, one submission (issuer #5) will include CF/SF state data
    cfsf_enabled: bool = Field(default=False, description="Enable CF/SF test for issuer #5")
    # Note: TX is NOT a CF/SF participating state. Valid states per IRS SHAREDIRFORM019_002:
    # AL, AZ, AR, CA, CT, CO, DC, DE, GA, HI, ID, IN, KS, LA, MA, MD, ME, MI, MN, MS, MT, NE, NJ, NM, NC, ND, OH, OK, OR, PA, RI, SC, WI
    cfsf_state: str = Field(default="AZ", description="State code for CF/SF election (2-letter)")


class ATSTestResponse(BaseModel):
    """Response from ATS test submission."""
    success: bool
    receipt_id: Optional[str] = None  # IRS-assigned receipt ID for status queries
    transmission_id: str
    status: str
    message: str
    submission_count: int = 0
    recipient_count: int = 0
    xml_preview: Optional[str] = None
    errors: List[dict] = Field(default_factory=list)
    # CF/SF specific fields
    cfsf_enabled: bool = Field(default=False, description="Whether CF/SF was included")
    cfsf_submission_index: Optional[int] = Field(None, description="Which submission (1-5) has CF/SF")
    cfsf_state: Optional[str] = Field(None, description="State code used for CF/SF")


# ATS Test Data: 5 fake issuers with 2 recipients each
# All TINs start with 000 as required for IRS ATS testing
ATS_TEST_ISSUERS = [
    {
        "name": "ATS Test Company Alpha",
        "tin": "000111111",
        "tin_type": "EIN",
        "address1": "100 Test Street",
        "city": "Austin",
        "state": "TX",
        "zip": "78701",
        "contact_name": "Alpha Contact",
        "email": "alpha@test.com",
        "phone": "5125550101",
    },
    {
        "name": "ATS Test Company Beta",
        "tin": "000222222",
        "tin_type": "EIN",
        "address1": "200 Sample Avenue",
        "city": "Dallas",
        "state": "TX",
        "zip": "75201",
        "contact_name": "Beta Contact",
        "email": "beta@test.com",
        "phone": "2145550102",
    },
    {
        "name": "ATS Test Company Gamma",
        "tin": "000333333",
        "tin_type": "EIN",
        "address1": "300 Example Boulevard",
        "city": "Houston",
        "state": "TX",
        "zip": "77001",
        "contact_name": "Gamma Contact",
        "email": "gamma@test.com",
        "phone": "7135550103",
    },
    {
        "name": "ATS Test Company Delta",
        "tin": "000444444",
        "tin_type": "EIN",
        "address1": "400 Demo Drive",
        "city": "San Antonio",
        "state": "TX",
        "zip": "78201",
        "contact_name": "Delta Contact",
        "email": "delta@test.com",
        "phone": "2105550104",
    },
    {
        "name": "ATS Test Company Epsilon",
        "tin": "000555555",
        "tin_type": "EIN",
        "address1": "500 Test Lane",
        "city": "Fort Worth",
        "state": "TX",
        "zip": "76101",
        "contact_name": "Epsilon Contact",
        "email": "epsilon@test.com",
        "phone": "8175550105",
    },
]

# 10 test recipients (2 per issuer)
ATS_TEST_RECIPIENTS = [
    # Issuer 1 recipients
    {
        "name": "John A TestRecipient",
        "tin": "000010001",
        "tin_type": "SSN",
        "address1": "101 Recipient Road",
        "city": "Austin",
        "state": "TX",
        "zip": "78702",
    },
    {
        "name": "Jane B TestRecipient",
        "tin": "000010002",
        "tin_type": "SSN",
        "address1": "102 Recipient Road",
        "city": "Austin",
        "state": "TX",
        "zip": "78703",
    },
    # Issuer 2 recipients
    {
        "name": "Robert C TestRecipient",
        "tin": "000020001",
        "tin_type": "SSN",
        "address1": "201 Payee Place",
        "city": "Dallas",
        "state": "TX",
        "zip": "75202",
    },
    {
        "name": "Mary D TestRecipient",
        "tin": "000020002",
        "tin_type": "SSN",
        "address1": "202 Payee Place",
        "city": "Dallas",
        "state": "TX",
        "zip": "75203",
    },
    # Issuer 3 recipients
    {
        "name": "William E TestRecipient",
        "tin": "000030001",
        "tin_type": "SSN",
        "address1": "301 Vendor View",
        "city": "Houston",
        "state": "TX",
        "zip": "77002",
    },
    {
        "name": "Elizabeth F TestRecipient",
        "tin": "000030002",
        "tin_type": "SSN",
        "address1": "302 Vendor View",
        "city": "Houston",
        "state": "TX",
        "zip": "77003",
    },
    # Issuer 4 recipients
    {
        "name": "David G TestRecipient",
        "tin": "000040001",
        "tin_type": "SSN",
        "address1": "401 Contractor Court",
        "city": "San Antonio",
        "state": "TX",
        "zip": "78202",
    },
    {
        "name": "Susan H TestRecipient",
        "tin": "000040002",
        "tin_type": "SSN",
        "address1": "402 Contractor Court",
        "city": "San Antonio",
        "state": "TX",
        "zip": "78203",
    },
    # Issuer 5 recipients
    {
        "name": "Michael I TestRecipient",
        "tin": "000050001",
        "tin_type": "SSN",
        "address1": "501 Worker Way",
        "city": "Fort Worth",
        "state": "TX",
        "zip": "76102",
    },
    {
        "name": "Patricia J TestRecipient",
        "tin": "000050002",
        "tin_type": "SSN",
        "address1": "502 Worker Way",
        "city": "Fort Worth",
        "state": "TX",
        "zip": "76103",
    },
]


def build_ats_issuer(issuer_data: dict) -> IssuerInfo:
    """Build IssuerInfo from ATS test data."""
    return IssuerInfo(
        tin=issuer_data["tin"],
        tin_type=issuer_data["tin_type"],
        business_name=issuer_data["name"],
        address1=issuer_data["address1"],
        city=issuer_data["city"],
        state=issuer_data["state"],
        zip_code=issuer_data["zip"],
        contact_name=issuer_data.get("contact_name"),
        contact_email=issuer_data.get("email"),
        phone=issuer_data.get("phone"),
    )


def build_ats_recipient(recipient_data: dict) -> RecipientInfo:
    """Build RecipientInfo from ATS test data."""
    name_parts = recipient_data["name"].split(" ")
    return RecipientInfo(
        tin=recipient_data["tin"],
        tin_type=recipient_data["tin_type"],
        first_name=name_parts[0] if len(name_parts) > 0 else "",
        middle_name=name_parts[1] if len(name_parts) > 2 else None,
        last_name=name_parts[-1] if len(name_parts) > 1 else name_parts[0],
        address1=recipient_data["address1"],
        city=recipient_data["city"],
        state=recipient_data["state"],
        zip_code=recipient_data["zip"],
    )


def build_ats_form_data(
    form_type: str,
    recipient: RecipientInfo,
    record_id: str,
    tax_year: int,
    amount_base: int,
):
    """Build test form data based on form type."""
    # Vary amounts slightly for each recipient
    amount = Decimal(str(1000 + amount_base * 100))

    if form_type == "1099NEC":
        return Form1099NECData(
            record_id=record_id,
            tax_year=tax_year,
            recipient=recipient,
            nonemployee_compensation=amount,
            direct_sales_indicator=False,
            federal_tax_withheld=Decimal("0.00"),
            state_local_taxes=[],
            is_corrected=False,
            cfsf_states=[],
        )
    elif form_type == "1099MISC":
        return Form1099MISCData(
            record_id=record_id,
            tax_year=tax_year,
            recipient=recipient,
            rents=amount,
            royalties=Decimal("0.00"),
            other_income=Decimal("0.00"),
            federal_tax_withheld=Decimal("0.00"),
            state_local_taxes=[],
            is_corrected=False,
            cfsf_states=[],
        )
    elif form_type == "1099S":
        return Form1099SData(
            record_id=record_id,
            tax_year=tax_year,
            recipient=recipient,
            closing_date=date(tax_year, 6, 15),
            gross_proceeds=amount * 100,  # Real estate uses larger amounts
            address_or_legal_desc=f"Test Property {record_id}, TX",
            transferor_received_consideration=False,
            transferor_is_foreign_person=False,
            buyers_real_estate_tax=Decimal("0.00"),
            is_corrected=False,
        )
    elif form_type == "1098":
        return Form1098Data(
            record_id=record_id,
            tax_year=tax_year,
            recipient=recipient,
            mortgage_interest_received=amount * 10,
            outstanding_mortgage_principal=amount * 100,
            mortgage_origination_date=date(tax_year - 5, 1, 15),
            refund_of_overpaid_interest=Decimal("0.00"),
            mortgage_insurance_premiums=Decimal("0.00"),
            points_paid_on_purchase=Decimal("0.00"),
            property_address_same_as_borrower=True,
            property_address="",
            properties_securing_mortgage_count=1,
            other_info="",
            mortgage_acquisition_date=None,
            is_corrected=False,
        )
    else:
        raise ValueError(f"Unknown form type: {form_type}")


def build_ats_form_data_cfsf(
    form_type: str,
    recipient: RecipientInfo,
    record_id: str,
    tax_year: int,
    amount_base: int,
    cfsf_state: str = "TX",
):
    """
    Build test form data with CF/SF (Combined Federal/State Filing) state information.

    Per IRS schema, CF/SF forms need:
    - CFSFElectionStateCd at form level (array of state codes)
    - StateLocalTaxGrp with state withholding/income info

    Args:
        form_type: Type of form (1099NEC, 1099MISC, etc.)
        recipient: RecipientInfo for the form
        record_id: Record ID string
        tax_year: Tax year
        amount_base: Base amount multiplier (1-10)
        cfsf_state: 2-letter state code for CF/SF election

    Returns:
        Form data object with CF/SF state info populated
    """
    # Vary amounts slightly for each recipient
    amount = Decimal(str(1000 + amount_base * 100))

    # Calculate state withholding (use 5% of income for testing)
    state_income = amount
    state_withheld = (amount * Decimal("0.05")).quantize(Decimal("0.01"))

    # Build state/local tax info for CF/SF
    state_tax = StateLocalTax(
        state_code=cfsf_state.upper(),
        state_id_number=f"0000{amount_base:05d}",  # Test state ID
        state_tax_withheld=state_withheld,
        state_income=state_income,
        local_tax_withheld=Decimal("0.00"),
        local_income=Decimal("0.00"),
        locality_name=None,
    )

    if form_type == "1099NEC":
        return Form1099NECData(
            record_id=record_id,
            tax_year=tax_year,
            recipient=recipient,
            nonemployee_compensation=amount,
            direct_sales_indicator=False,
            federal_tax_withheld=Decimal("0.00"),
            state_local_taxes=[state_tax],  # Include state tax info
            is_corrected=False,
            cfsf_states=[cfsf_state.upper()],  # CF/SF election states
        )
    elif form_type == "1099MISC":
        return Form1099MISCData(
            record_id=record_id,
            tax_year=tax_year,
            recipient=recipient,
            rents=amount,
            royalties=Decimal("0.00"),
            other_income=Decimal("0.00"),
            federal_tax_withheld=Decimal("0.00"),
            state_local_taxes=[state_tax],  # Include state tax info
            is_corrected=False,
            cfsf_states=[cfsf_state.upper()],  # CF/SF election states
        )
    elif form_type == "1099S":
        # 1099-S does not participate in CF/SF program
        # Return standard form without state info
        return Form1099SData(
            record_id=record_id,
            tax_year=tax_year,
            recipient=recipient,
            closing_date=date(tax_year, 6, 15),
            gross_proceeds=amount * 100,
            address_or_legal_desc=f"Test Property {record_id}, {cfsf_state}",
            transferor_received_consideration=False,
            transferor_is_foreign_person=False,
            buyers_real_estate_tax=Decimal("0.00"),
            is_corrected=False,
        )
    elif form_type == "1098":
        # 1098 does not participate in CF/SF program
        # Return standard form without state info
        return Form1098Data(
            record_id=record_id,
            tax_year=tax_year,
            recipient=recipient,
            mortgage_interest_received=amount * 10,
            outstanding_mortgage_principal=amount * 100,
            mortgage_origination_date=date(tax_year - 5, 1, 15),
            refund_of_overpaid_interest=Decimal("0.00"),
            mortgage_insurance_premiums=Decimal("0.00"),
            points_paid_on_purchase=Decimal("0.00"),
            property_address_same_as_borrower=True,
            property_address="",
            properties_securing_mortgage_count=1,
            other_info="",
            mortgage_acquisition_date=None,
            is_corrected=False,
        )
    else:
        raise ValueError(f"Unknown form type: {form_type}")


@router.post("/ats-test/preview-xml")
async def ats_test_preview_xml(request: ATSTestRequest) -> Response:
    """
    Generate ATS test XML for preview without submitting.

    Creates 5 submissions (issuers) with 2 payees each = 10 total records.
    All TINs start with 000 as required for IRS ATS testing.

    If cfsf_enabled=True, issuer #5 will include CF/SF state filing data.
    """
    try:
        batches = []
        recipient_idx = 0
        # Per Pub 5719, CF/SF test can be one of the 5 submissions
        # We use issuer #5 (index 4) for CF/SF when enabled
        cfsf_issuer_index = 4

        # Build 5 submission batches (one per issuer)
        for issuer_idx, issuer_data in enumerate(ATS_TEST_ISSUERS):
            issuer = build_ats_issuer(issuer_data)
            forms = []

            # Check if this issuer should use CF/SF
            is_cfsf_issuer = request.cfsf_enabled and issuer_idx == cfsf_issuer_index

            # 2 recipients per issuer
            for j in range(2):
                if recipient_idx >= len(ATS_TEST_RECIPIENTS):
                    break
                recipient_data = ATS_TEST_RECIPIENTS[recipient_idx]
                recipient = build_ats_recipient(recipient_data)
                # IRS RecordId must be simple integer pattern [1-9][0-9]* - NOT "1-1" format!
                record_id = str(recipient_idx + 1)

                # Use CF/SF builder for the CF/SF issuer
                if is_cfsf_issuer and request.form_type in ("1099NEC", "1099MISC"):
                    form_data = build_ats_form_data_cfsf(
                        request.form_type,
                        recipient,
                        record_id,
                        request.tax_year,
                        recipient_idx + 1,
                        cfsf_state=request.cfsf_state,
                    )
                else:
                    form_data = build_ats_form_data(
                        request.form_type,
                        recipient,
                        record_id,
                        request.tax_year,
                        recipient_idx + 1,
                    )
                forms.append(form_data)
                recipient_idx += 1

            batch = SubmissionBatch(
                issuer=issuer,
                form_type=request.form_type,
                tax_year=request.tax_year,
                forms=forms,
                # Set CF/SF election at submission level
                cfsf_election=is_cfsf_issuer and request.form_type in ("1099NEC", "1099MISC"),
            )
            batches.append(batch)

        # Generate XML
        transmitter = get_transmitter_config()
        software_id = get_software_id()

        generator = IRISXMLGenerator(
            transmitter=transmitter,
            software_id=software_id,
            is_test=True,  # Always test mode for ATS
        )

        xml_content = generator.generate_transmission(
            batches=batches,
            tax_year=request.tax_year,
        )

        # Include CF/SF indicator in filename
        filename_suffix = "_cfsf" if request.cfsf_enabled else ""
        return Response(
            content=xml_content,
            media_type="application/xml",
            headers={
                "Content-Disposition": f"attachment; filename=ats_test_{request.form_type}_{request.tax_year}{filename_suffix}.xml"
            }
        )

    except Exception as e:
        logger.exception("Error generating ATS test XML preview")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ats-test/submit", response_model=ATSTestResponse)
async def ats_test_submit(request: ATSTestRequest):
    """
    Submit ATS certification test to IRS.

    Creates and submits 1 transmission with 5 submissions (issuers),
    each with 2 payees = 10 total records.

    All TINs start with 000 as required for IRS ATS testing.
    Test File Indicator is set to "T".

    If cfsf_enabled=True, issuer #5 will include CF/SF state filing data.
    Per Pub 5719, the CF/SF test can be included as one of the five submissions.

    This is a one-time process for IRS ATS certification.
    Production filings will be done one client at a time.
    """
    try:
        batches = []
        recipient_idx = 0
        total_recipients = 0
        # Per Pub 5719, CF/SF test can be one of the 5 submissions
        # We use issuer #5 (index 4) for CF/SF when enabled
        cfsf_issuer_index = 4

        # Build 5 submission batches (one per issuer)
        for issuer_idx, issuer_data in enumerate(ATS_TEST_ISSUERS):
            issuer = build_ats_issuer(issuer_data)
            forms = []

            # Check if this issuer should use CF/SF
            is_cfsf_issuer = request.cfsf_enabled and issuer_idx == cfsf_issuer_index

            # 2 recipients per issuer
            for j in range(2):
                if recipient_idx >= len(ATS_TEST_RECIPIENTS):
                    break
                recipient_data = ATS_TEST_RECIPIENTS[recipient_idx]
                recipient = build_ats_recipient(recipient_data)
                # IRS RecordId must be simple integer pattern [1-9][0-9]* - NOT "1-1" format!
                record_id = str(recipient_idx + 1)

                # Use CF/SF builder for the CF/SF issuer
                if is_cfsf_issuer and request.form_type in ("1099NEC", "1099MISC"):
                    form_data = build_ats_form_data_cfsf(
                        request.form_type,
                        recipient,
                        record_id,
                        request.tax_year,
                        recipient_idx + 1,
                        cfsf_state=request.cfsf_state,
                    )
                else:
                    form_data = build_ats_form_data(
                        request.form_type,
                        recipient,
                        record_id,
                        request.tax_year,
                        recipient_idx + 1,
                    )
                forms.append(form_data)
                recipient_idx += 1
                total_recipients += 1

            batch = SubmissionBatch(
                issuer=issuer,
                form_type=request.form_type,
                tax_year=request.tax_year,
                forms=forms,
                # Set CF/SF election at submission level
                cfsf_election=is_cfsf_issuer and request.form_type in ("1099NEC", "1099MISC"),
            )
            batches.append(batch)

        # Generate XML
        transmitter = get_transmitter_config()
        software_id = get_software_id()

        generator = IRISXMLGenerator(
            transmitter=transmitter,
            software_id=software_id,
            is_test=True,  # Always test mode for ATS
        )

        xml_bytes = generator.generate_transmission_bytes(
            batches=batches,
            tax_year=request.tax_year,
        )

        # Validate XML before submission
        is_valid, validation_errors = validate_iris_xml(xml_bytes)
        if not is_valid:
            error_messages = [e["message"] for e in validation_errors if e.get("type") == "error"]
            logger.error(f"ATS test XML validation failed: {error_messages[:5]}")
            return ATSTestResponse(
                success=False,
                transmission_id="",
                status="validation_error",
                message=f"XML validation failed: {error_messages[0] if error_messages else 'Unknown error'}",
                submission_count=len(batches),
                recipient_count=total_recipients,
                errors=validation_errors[:10],
            )

        # Submit to IRS ATS
        try:
            config = load_config()
            client = IRISClient(config)
            result = client.submit_xml(xml_bytes)
        except IRISClientError as e:
            logger.error(f"ATS test IRIS submission failed: {e}")
            return ATSTestResponse(
                success=False,
                transmission_id="",
                status="error",
                message=str(e),
                submission_count=len(batches),
                recipient_count=total_recipients,
            )
        except Exception as e:
            logger.error(f"ATS test IRIS submission error: {e}")
            return ATSTestResponse(
                success=False,
                transmission_id="",
                status="error",
                message=f"Submission error: {type(e).__name__}: {str(e)}",
                submission_count=len(batches),
                recipient_count=total_recipients,
            )

        # Log activity (entity_id must be UUID or None, so store receipt_id in details)
        log_activity(
            action="ats_test_submitted",
            entity_type="ats_certification",
            entity_id=None,
            filer_id=None,
            operating_year_id=None,
            details={
                "form_type": request.form_type,
                "tax_year": request.tax_year,
                "submission_count": len(batches),
                "recipient_count": total_recipients,
                "transmission_id": result.unique_transmission_id,
                "receipt_id": result.receipt_id,
                "status": result.status.value,
                "cfsf_enabled": request.cfsf_enabled,
                "cfsf_state": request.cfsf_state if request.cfsf_enabled else None,
            },
        )

        # Save to ats_submissions table for correction reference
        # Build record_map: maps recipient index (1-10) to submission/record sequence
        # ATS format: 5 issuers x 2 recipients
        # Recipient 1,2 -> Issuer 1 (submission 1), record 1,2
        # Recipient 3,4 -> Issuer 2 (submission 2), record 3,4
        # etc.
        record_map = {}
        for i in range(1, total_recipients + 1):
            issuer_idx = (i - 1) // 2  # 0-4
            submission_seq = issuer_idx + 1  # 1-5
            record_seq = i  # 1-10 (global record sequence)
            record_map[str(i)] = {
                "submission_seq": submission_seq,
                "record_seq": record_seq,
            }

        if result.receipt_id:
            try:
                save_ats_submission(
                    receipt_id=result.receipt_id,
                    transmission_id=result.unique_transmission_id,
                    form_type=request.form_type,
                    tax_year=request.tax_year,
                    submission_count=len(batches),
                    recipient_count=total_recipients,
                    status="submitted",  # Will be updated when we check status
                    irs_message=result.message,
                    cfsf_enabled=request.cfsf_enabled and request.form_type in ("1099NEC", "1099MISC"),
                    cfsf_state=request.cfsf_state if request.cfsf_enabled else None,
                    submission_type="original",
                    record_map=record_map,
                )
                logger.info(f"Saved ATS submission to database: {result.receipt_id}")
            except Exception as save_err:
                logger.warning(f"Failed to save ATS submission to database: {save_err}")

        # Build response message, noting CF/SF if enabled
        response_message = result.message
        if request.cfsf_enabled and request.form_type in ("1099NEC", "1099MISC"):
            response_message += f" [CF/SF enabled for Issuer #5 ({request.cfsf_state})]"

        return ATSTestResponse(
            success=result.is_success,
            receipt_id=result.receipt_id,
            transmission_id=result.unique_transmission_id,
            status=result.status.value,
            message=response_message,
            submission_count=len(batches),
            recipient_count=total_recipients,
            errors=[
                {
                    "record_id": e.record_id,
                    "code": e.error_code,
                    "message": e.error_message,
                    "field": e.field_name,
                }
                for e in result.errors
            ],
            # CF/SF tracking fields
            cfsf_enabled=request.cfsf_enabled and request.form_type in ("1099NEC", "1099MISC"),
            cfsf_submission_index=5 if (request.cfsf_enabled and request.form_type in ("1099NEC", "1099MISC")) else None,
            cfsf_state=request.cfsf_state if (request.cfsf_enabled and request.form_type in ("1099NEC", "1099MISC")) else None,
        )

    except Exception as e:
        logger.exception("Error submitting ATS test to IRS")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ats-test/last-submit-response")
async def get_last_submit_response_endpoint():
    """
    Returns the last raw IRS submit response for debugging.
    Submit first, then call this to see what IRS returned.
    """
    from src.iris_client import get_last_submit_response
    return get_last_submit_response()


# =============================================================================
# ATS SUBMISSION HISTORY
# =============================================================================

class ATSSubmissionRecord(BaseModel):
    """ATS submission record for history tracking."""
    id: str
    receipt_id: str
    transmission_id: str
    form_type: str
    tax_year: int
    submission_count: int
    recipient_count: int
    status: str
    irs_message: Optional[str] = None
    cfsf_enabled: bool = False
    cfsf_state: Optional[str] = None
    submission_type: str  # original or correction
    original_submission_id: Optional[str] = None
    record_map: Optional[dict] = None
    submitted_at: Optional[str] = None
    status_checked_at: Optional[str] = None


@router.get("/ats-test/submissions", response_model=List[ATSSubmissionRecord])
async def list_ats_submissions(
    form_type: Optional[str] = Query(None, description="Filter by form type"),
    tax_year: Optional[int] = Query(None, description="Filter by tax year"),
    status: Optional[str] = Query(None, description="Filter by status"),
    submission_type: Optional[str] = Query(None, description="Filter by type: original or correction"),
    limit: int = Query(20, ge=1, le=100, description="Max results"),
):
    """
    List ATS submission history.

    Returns all stored ATS submissions, ordered by most recent first.
    Use filters to narrow results.
    """
    try:
        submissions = get_ats_submissions(
            form_type=form_type,
            tax_year=tax_year,
            status=status,
            submission_type=submission_type,
            limit=limit,
        )
        return submissions
    except Exception as e:
        logger.exception("Error listing ATS submissions")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ats-test/submissions/originals", response_model=List[ATSSubmissionRecord])
async def list_accepted_originals(
    form_type: Optional[str] = Query(None, description="Filter by form type"),
    tax_year: Optional[int] = Query(None, description="Filter by tax year"),
):
    """
    List only ACCEPTED original ATS submissions.

    These are the submissions that can have corrections filed against them.
    Use this endpoint to populate the correction form's original selection dropdown.
    """
    try:
        submissions = get_accepted_ats_originals(
            form_type=form_type,
            tax_year=tax_year,
        )
        return submissions
    except Exception as e:
        logger.exception("Error listing accepted ATS originals")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ats-test/submissions/{submission_id}", response_model=ATSSubmissionRecord)
async def get_ats_submission_detail(submission_id: str):
    """Get details of a specific ATS submission."""
    try:
        submission = get_ats_submission(submission_id)
        if not submission:
            raise HTTPException(status_code=404, detail="Submission not found")
        return submission
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting ATS submission")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/ats-test/submissions/{submission_id}/status")
async def update_submission_status(
    submission_id: str,
    status: str = Query(..., description="New status: submitted, accepted, rejected, partially_accepted"),
    irs_message: Optional[str] = Query(None, description="IRS message/reason"),
):
    """
    Manually update the status of an ATS submission.

    Use this after checking status with IRS to mark submissions as accepted/rejected.
    """
    valid_statuses = ["submitted", "accepted", "rejected", "partially_accepted"]
    if status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {valid_statuses}"
        )

    try:
        result = update_ats_submission_status(submission_id, status, irs_message)
        if not result:
            raise HTTPException(status_code=404, detail="Submission not found")
        return {"success": True, "submission_id": submission_id, "status": status}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating ATS submission status")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ATS CORRECTION TEST
# =============================================================================

class ATSCorrectionRequest(BaseModel):
    """Request for ATS correction test submission."""
    form_type: str = Field(default="1099NEC", pattern="^(1099NEC|1099MISC|1099S|1098)$")
    tax_year: int = Field(default=2025, ge=2020, le=2030)
    original_receipt_id: str = Field(..., description="Receipt ID from original accepted submission")
    original_utid: str = Field(..., description="Unique Transmission ID from original (e.g., 49c5c09b...::A)")
    # Which recipients to correct (by 1-based index, default is just recipient 1)
    recipients_to_correct: List[int] = Field(default=[1], description="Which recipient indices to correct (1-10)")
    # Amount adjustment for correction
    amount_adjustment: float = Field(default=50.00, description="Amount to add to original compensation")


class ATSCorrectionResponse(BaseModel):
    """Response from ATS correction test submission."""
    success: bool
    receipt_id: Optional[str] = None
    transmission_id: str
    status: str
    message: str
    submission_count: int = 0
    recipient_count: int = 0
    corrected_records: List[dict] = Field(default_factory=list)
    errors: List[dict] = Field(default_factory=list)


def build_ats_form_data_corrected(
    form_type: str,
    recipient: RecipientInfo,
    record_id: str,
    tax_year: int,
    recipient_idx: int,
    original_receipt_id: str,
    amount_adjustment: Decimal,
) -> Form1099NECData | Form1099MISCData | Form1099SData | Form1098Data:
    """
    Build corrected ATS form data - same as original but with:
    - is_corrected = True
    - original_record_id = UniqueRecordId from original submission
    - Adjusted amount (original + adjustment)
    """
    # Original base amount per recipient (same formula as build_ats_form_data)
    base_amount = Decimal(str(1000 + (recipient_idx * 100)))
    corrected_amount = base_amount + amount_adjustment

    # Build the UniqueRecordId for referencing the original
    # IRS UniqueRecordId format: {ReceiptId}|{SubmissionSequence}|{RecordSequence}
    # where ReceiptId is the IRS-assigned receipt ID (format: YYYY-11digits-9chars)
    # For ATS test with 5 issuers, 2 recipients each:
    # - Issuer 1 (submission 1): recipients 1,2 -> record_ids 1,2
    # - Issuer 2 (submission 2): recipients 3,4 -> record_ids 3,4
    # - etc.
    issuer_idx = (recipient_idx - 1) // 2  # 0-based issuer index
    submission_seq = issuer_idx + 1  # 1-based submission sequence
    record_seq = record_id  # This is the record_id within submission

    # IRS UniqueRecordId pattern: [1-9][0-9]{3}\-[0-9]{11}\-[0-9a-zA-Z]{9}\|[1-9][0-9]{0,7}\|[1-9][0-9]{0,7}
    # Example: 2025-68698468914-b0b2da138|1|1
    original_unique_record_id = f"{original_receipt_id}|{submission_seq}|{record_seq}"

    if form_type == "1099NEC":
        return Form1099NECData(
            record_id=record_id,
            tax_year=tax_year,
            recipient=recipient,
            nonemployee_compensation=corrected_amount,
            direct_sales_indicator=False,
            federal_tax_withheld=Decimal("0.00"),
            state_local_taxes=[],
            is_corrected=True,
            original_record_id=original_unique_record_id,
            cfsf_states=[],
        )
    elif form_type == "1099MISC":
        return Form1099MISCData(
            record_id=record_id,
            tax_year=tax_year,
            recipient=recipient,
            rents=corrected_amount,
            royalties=Decimal("0.00"),
            other_income=Decimal("0.00"),
            federal_tax_withheld=Decimal("0.00"),
            fishing_boat_proceeds=Decimal("0.00"),
            medical_healthcare_payments=Decimal("0.00"),
            direct_sales_indicator=False,
            substitute_payments=Decimal("0.00"),
            crop_insurance_proceeds=Decimal("0.00"),
            gross_proceeds_attorney=Decimal("0.00"),
            fish_purchased_resale=Decimal("0.00"),
            section_409a_deferrals=Decimal("0.00"),
            nonqualified_deferred_comp=Decimal("0.00"),
            state_local_taxes=[],
            is_corrected=True,
            original_record_id=original_unique_record_id,
            cfsf_states=[],
        )
    elif form_type == "1099S":
        return Form1099SData(
            record_id=record_id,
            tax_year=tax_year,
            recipient=recipient,
            closing_date=date(tax_year, 6, 15),
            gross_proceeds=corrected_amount * Decimal("100"),
            address_or_legal_desc="123 Test Property, Austin TX 78701",
            transferor_received_consideration=False,
            transferor_is_foreign_person=False,
            buyers_real_estate_tax=Decimal("0.00"),
            is_corrected=True,
            original_record_id=original_unique_record_id,
        )
    elif form_type == "1098":
        return Form1098Data(
            record_id=record_id,
            tax_year=tax_year,
            recipient=recipient,
            mortgage_interest_received=corrected_amount * Decimal("10"),
            outstanding_mortgage_principal=corrected_amount * Decimal("100"),
            mortgage_origination_date=date(tax_year - 5, 1, 15),
            refund_of_overpaid_interest=Decimal("0.00"),
            mortgage_insurance_premiums=Decimal("0.00"),
            points_paid_on_purchase=Decimal("0.00"),
            property_address_same_as_borrower=True,
            property_address="",
            properties_securing_mortgage_count=1,
            other_info="",
            mortgage_acquisition_date=None,
            is_corrected=True,
            original_record_id=original_unique_record_id,
        )
    else:
        raise ValueError(f"Unknown form type: {form_type}")


@router.post("/ats-test/correction/preview-xml")
async def ats_correction_preview_xml(request: ATSCorrectionRequest) -> Response:
    """
    Generate ATS correction test XML for preview without submitting.

    Creates corrected versions of specified recipients from the original ATS test.
    The CorrectedInd will be set to "1" and PrevSubmittedRecRecipientGrp will
    reference the original UniqueRecordId.
    """
    try:
        batches = []
        corrected_records = []
        amount_adjustment = Decimal(str(request.amount_adjustment))

        # For correction test, we only include the issuers/recipients that are being corrected
        # Group recipients by issuer
        recipients_by_issuer = {}
        for recipient_idx in request.recipients_to_correct:
            if recipient_idx < 1 or recipient_idx > 10:
                continue
            issuer_idx = (recipient_idx - 1) // 2  # 0-based
            if issuer_idx not in recipients_by_issuer:
                recipients_by_issuer[issuer_idx] = []
            recipients_by_issuer[issuer_idx].append(recipient_idx)

        # Build batches for each affected issuer
        for issuer_idx, recipient_indices in recipients_by_issuer.items():
            issuer_data = ATS_TEST_ISSUERS[issuer_idx]
            issuer = build_ats_issuer(issuer_data)
            forms = []

            for recipient_idx in recipient_indices:
                recipient_data = ATS_TEST_RECIPIENTS[recipient_idx - 1]  # Convert to 0-based
                recipient = build_ats_recipient(recipient_data)
                record_id = str(recipient_idx)  # Keep same record_id as original

                form_data = build_ats_form_data_corrected(
                    request.form_type,
                    recipient,
                    record_id,
                    request.tax_year,
                    recipient_idx,
                    request.original_receipt_id,
                    amount_adjustment,
                )
                forms.append(form_data)

                corrected_records.append({
                    "record_id": record_id,
                    "recipient_name": recipient_data["name"],
                    "original_amount": float(1000 + (recipient_idx * 100)),
                    "corrected_amount": float(1000 + (recipient_idx * 100) + request.amount_adjustment),
                    "original_unique_record_id": form_data.original_record_id,
                })

            batch = SubmissionBatch(
                issuer=issuer,
                form_type=request.form_type,
                tax_year=request.tax_year,
                forms=forms,
                cfsf_election=False,
            )
            batches.append(batch)

        if not batches:
            raise HTTPException(status_code=400, detail="No valid recipients to correct")

        # Generate XML
        transmitter = get_transmitter_config()
        software_id = get_software_id()

        generator = IRISXMLGenerator(
            transmitter=transmitter,
            software_id=software_id,
            is_test=True,
        )

        xml_content = generator.generate_transmission(
            batches=batches,
            tax_year=request.tax_year,
        )

        return Response(
            content=xml_content,
            media_type="application/xml",
            headers={
                "Content-Disposition": f"attachment; filename=ats_correction_{request.form_type}_{request.tax_year}.xml"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error generating ATS correction XML preview")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ats-test/correction/submit", response_model=ATSCorrectionResponse)
async def ats_correction_submit(request: ATSCorrectionRequest):
    """
    Submit ATS correction test to IRS.

    This creates corrected versions of forms from a previously accepted original submission.
    The corrected forms will have:
    - CorrectedInd = "1"
    - PrevSubmittedRecRecipientGrp/UniqueRecordId referencing the original

    Required inputs:
    - original_receipt_id: The Receipt ID from the original accepted submission
    - original_utid: The Unique Transmission ID (UTID) from the original (ends with ::A for ATS)
    - recipients_to_correct: Which recipients (1-10) to include in correction
    - amount_adjustment: How much to add/subtract from original amount

    The goal is to get this corrected submission Accepted by IRS ATS.
    """
    try:
        batches = []
        corrected_records = []
        total_recipients = 0
        amount_adjustment = Decimal(str(request.amount_adjustment))

        # Validate UTID format (should end with ::A for ATS)
        if not request.original_utid.endswith("::A"):
            logger.warning(f"Original UTID doesn't end with ::A: {request.original_utid}")

        # Group recipients by issuer
        recipients_by_issuer = {}
        for recipient_idx in request.recipients_to_correct:
            if recipient_idx < 1 or recipient_idx > 10:
                continue
            issuer_idx = (recipient_idx - 1) // 2
            if issuer_idx not in recipients_by_issuer:
                recipients_by_issuer[issuer_idx] = []
            recipients_by_issuer[issuer_idx].append(recipient_idx)

        # Build batches for each affected issuer
        for issuer_idx, recipient_indices in recipients_by_issuer.items():
            issuer_data = ATS_TEST_ISSUERS[issuer_idx]
            issuer = build_ats_issuer(issuer_data)
            forms = []

            for recipient_idx in recipient_indices:
                recipient_data = ATS_TEST_RECIPIENTS[recipient_idx - 1]
                recipient = build_ats_recipient(recipient_data)
                record_id = str(recipient_idx)

                form_data = build_ats_form_data_corrected(
                    request.form_type,
                    recipient,
                    record_id,
                    request.tax_year,
                    recipient_idx,
                    request.original_receipt_id,
                    amount_adjustment,
                )
                forms.append(form_data)
                total_recipients += 1

                corrected_records.append({
                    "record_id": record_id,
                    "recipient_name": recipient_data["name"],
                    "original_amount": float(1000 + (recipient_idx * 100)),
                    "corrected_amount": float(1000 + (recipient_idx * 100) + request.amount_adjustment),
                    "original_unique_record_id": form_data.original_record_id,
                })

            batch = SubmissionBatch(
                issuer=issuer,
                form_type=request.form_type,
                tax_year=request.tax_year,
                forms=forms,
                cfsf_election=False,
            )
            batches.append(batch)

        if not batches:
            raise HTTPException(status_code=400, detail="No valid recipients to correct")

        # Generate XML
        transmitter = get_transmitter_config()
        software_id = get_software_id()

        generator = IRISXMLGenerator(
            transmitter=transmitter,
            software_id=software_id,
            is_test=True,
        )

        xml_bytes = generator.generate_transmission_bytes(
            batches=batches,
            tax_year=request.tax_year,
        )

        # Validate XML before submission
        is_valid, validation_errors = validate_iris_xml(xml_bytes)
        if not is_valid:
            error_messages = [e["message"] for e in validation_errors if e.get("type") == "error"]
            logger.error(f"ATS correction XML validation failed: {error_messages[:5]}")
            return ATSCorrectionResponse(
                success=False,
                transmission_id="",
                status="validation_error",
                message=f"XML validation failed: {error_messages[0] if error_messages else 'Unknown error'}",
                submission_count=len(batches),
                recipient_count=total_recipients,
                corrected_records=corrected_records,
                errors=validation_errors[:10],
            )

        # Submit to IRS ATS
        try:
            config = load_config()
            client = IRISClient(config)
            result = client.submit_xml(xml_bytes)
        except IRISClientError as e:
            logger.error(f"ATS correction IRIS submission failed: {e}")
            return ATSCorrectionResponse(
                success=False,
                transmission_id="",
                status="error",
                message=str(e),
                submission_count=len(batches),
                recipient_count=total_recipients,
                corrected_records=corrected_records,
            )
        except Exception as e:
            logger.error(f"ATS correction IRIS submission error: {e}")
            return ATSCorrectionResponse(
                success=False,
                transmission_id="",
                status="error",
                message=f"Submission error: {type(e).__name__}: {str(e)}",
                submission_count=len(batches),
                recipient_count=total_recipients,
                corrected_records=corrected_records,
            )

        # Log activity
        log_activity(
            action="ats_correction_submitted",
            entity_type="ats_certification",
            entity_id=None,
            filer_id=None,
            operating_year_id=None,
            details={
                "form_type": request.form_type,
                "tax_year": request.tax_year,
                "original_receipt_id": request.original_receipt_id,
                "original_utid": request.original_utid,
                "submission_count": len(batches),
                "recipient_count": total_recipients,
                "corrected_records": corrected_records,
                "transmission_id": result.unique_transmission_id,
                "receipt_id": result.receipt_id,
                "status": result.status.value,
            },
        )

        # Save correction to ats_submissions table
        if result.receipt_id:
            try:
                # Find the original submission ID by receipt_id
                originals = get_accepted_ats_originals(
                    form_type=request.form_type,
                    tax_year=request.tax_year,
                )
                original_submission_id = None
                for orig in originals:
                    if orig.get("receipt_id") == request.original_receipt_id:
                        original_submission_id = orig.get("id")
                        break

                save_ats_submission(
                    receipt_id=result.receipt_id,
                    transmission_id=result.unique_transmission_id,
                    form_type=request.form_type,
                    tax_year=request.tax_year,
                    submission_count=len(batches),
                    recipient_count=total_recipients,
                    status="submitted",
                    irs_message=result.message,
                    cfsf_enabled=False,
                    cfsf_state=None,
                    submission_type="correction",
                    original_submission_id=original_submission_id,
                    record_map=None,  # Corrections don't need record_map
                )
                logger.info(f"Saved ATS correction to database: {result.receipt_id}")
            except Exception as save_err:
                logger.warning(f"Failed to save ATS correction to database: {save_err}")

        return ATSCorrectionResponse(
            success=result.is_success,
            receipt_id=result.receipt_id,
            transmission_id=result.unique_transmission_id,
            status=result.status.value,
            message=result.message,
            submission_count=len(batches),
            recipient_count=total_recipients,
            corrected_records=corrected_records,
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
        logger.exception("Error submitting ATS correction to IRS")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# SUBMISSION STATUS CHECK
# =============================================================================

class StatusCheckRequest(BaseModel):
    """Request to check submission status."""
    receipt_id: Optional[str] = None
    transmission_id: Optional[str] = None


class StatusCheckResponse(BaseModel):
    """Response from status check."""
    success: bool
    receipt_id: str
    transmission_id: str
    status: str
    message: str
    errors: List[dict] = Field(default_factory=list)
    form_results: List[dict] = Field(default_factory=list)


@router.post("/check-status", response_model=StatusCheckResponse)
async def check_submission_status(request: StatusCheckRequest):
    """
    Check the status of a previously submitted transmission.

    Provide either receipt_id (from IRS response) or transmission_id (your UTID).
    The IRS may take time to process - check back if status is 'pending'.
    """
    if not request.receipt_id and not request.transmission_id:
        raise HTTPException(
            status_code=400,
            detail="Either receipt_id or transmission_id is required"
        )

    try:
        config = load_config()
        client = IRISClient(config)

        # Try to get acknowledgment first (more detailed)
        try:
            result = client.get_acknowledgment(
                receipt_id=request.receipt_id,
                transmission_id=request.transmission_id
            )
        except IRISClientError:
            # Fall back to basic status check
            result = client.get_status(
                receipt_id=request.receipt_id,
                transmission_id=request.transmission_id
            )

        return StatusCheckResponse(
            success=result.is_success,
            receipt_id=result.receipt_id,
            transmission_id=result.unique_transmission_id,
            status=result.status.value,
            message=result.message,
            errors=[
                {
                    "record_id": e.record_id,
                    "code": e.error_code,
                    "message": e.error_message,
                    "field": e.field_name,
                }
                for e in result.errors
            ],
            form_results=getattr(result, 'form_results', []),
        )

    except IRISClientError as e:
        logger.error(f"Status check failed: {e}")
        return StatusCheckResponse(
            success=False,
            receipt_id=request.receipt_id or "",
            transmission_id=request.transmission_id or "",
            status="error",
            message=str(e),
        )
    except Exception as e:
        logger.exception("Error checking submission status")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/check-status-debug")
async def check_status_debug(request: StatusCheckRequest):
    """
    Debug endpoint - returns raw IRS response XML.
    For troubleshooting status check parsing issues.
    """
    if not request.transmission_id:
        raise HTTPException(status_code=400, detail="transmission_id required")

    try:
        config = load_config()
        client = IRISClient(config)

        # Build the status request XML
        request_xml = client._build_status_request(
            receipt_id=request.receipt_id,
            transmission_id=request.transmission_id,
        )

        # Make the request directly
        response = client._request_url(
            method="POST",
            url=client.config.status_endpoint,
            data=request_xml,
            content_type="application/xml",
        )

        return {
            "request_xml": request_xml.decode("utf-8"),
            "response_status": response.status_code,
            "response_xml": response.text,
        }

    except Exception as e:
        return {
            "error": str(e),
            "error_type": type(e).__name__,
        }


@router.get("/check-ack-debug/{receipt_id}")
async def check_ack_debug(receipt_id: str):
    """
    Debug endpoint - returns raw IRS acknowledgment response XML for a receipt ID.
    Use this to see the actual error details from IRS.
    """
    try:
        config = load_config()
        client = IRISClient(config)

        # Build the acknowledgment request XML (type "A" not "S")
        request_xml = client._build_status_request(
            receipt_id=receipt_id,
            transmission_id=None,
            request_type="A",  # Acknowledgment has more details than Status
        )

        # Make the request directly
        response = client._request_url(
            method="POST",
            url=client.config.status_endpoint,
            data=request_xml,
            content_type="application/xml",
        )

        return {
            "receipt_id": receipt_id,
            "request_xml": request_xml.decode("utf-8"),
            "response_status": response.status_code,
            "response_xml": response.text,
        }

    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc(),
        }
