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
        else:
            forms = [f for f in forms if f.get("status") == "validated"]

        if not forms:
            raise HTTPException(
                status_code=400,
                detail=f"No validated {form_type_filter} forms found to e-file"
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
# ATS CERTIFICATION TEST
# =============================================================================

class ATSTestRequest(BaseModel):
    """Request for ATS certification test submission."""
    form_type: str = Field(default="1099NEC", pattern="^(1099NEC|1099MISC|1099S|1098)$")
    tax_year: int = Field(default=2025, ge=2020, le=2030)


class ATSTestResponse(BaseModel):
    """Response from ATS test submission."""
    success: bool
    transmission_id: str
    status: str
    message: str
    submission_count: int = 0
    recipient_count: int = 0
    xml_preview: Optional[str] = None
    errors: List[dict] = Field(default_factory=list)


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


@router.post("/ats-test/preview-xml")
async def ats_test_preview_xml(request: ATSTestRequest) -> Response:
    """
    Generate ATS test XML for preview without submitting.

    Creates 5 submissions (issuers) with 2 payees each = 10 total records.
    All TINs start with 000 as required for IRS ATS testing.
    """
    try:
        batches = []
        recipient_idx = 0

        # Build 5 submission batches (one per issuer)
        for issuer_idx, issuer_data in enumerate(ATS_TEST_ISSUERS):
            issuer = build_ats_issuer(issuer_data)
            forms = []

            # 2 recipients per issuer
            for j in range(2):
                if recipient_idx >= len(ATS_TEST_RECIPIENTS):
                    break
                recipient_data = ATS_TEST_RECIPIENTS[recipient_idx]
                recipient = build_ats_recipient(recipient_data)
                record_id = f"{issuer_idx + 1}-{j + 1}"

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
                cfsf_election=False,
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

        return Response(
            content=xml_content,
            media_type="application/xml",
            headers={
                "Content-Disposition": f"attachment; filename=ats_test_{request.form_type}_{request.tax_year}.xml"
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

    This is a one-time process for IRS ATS certification.
    Production filings will be done one client at a time.
    """
    try:
        batches = []
        recipient_idx = 0
        total_recipients = 0

        # Build 5 submission batches (one per issuer)
        for issuer_idx, issuer_data in enumerate(ATS_TEST_ISSUERS):
            issuer = build_ats_issuer(issuer_data)
            forms = []

            # 2 recipients per issuer
            for j in range(2):
                if recipient_idx >= len(ATS_TEST_RECIPIENTS):
                    break
                recipient_data = ATS_TEST_RECIPIENTS[recipient_idx]
                recipient = build_ats_recipient(recipient_data)
                record_id = f"{issuer_idx + 1}-{j + 1}"

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
                cfsf_election=False,
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

        # Log activity
        log_activity(
            action="ats_test_submitted",
            entity_type="ats_certification",
            entity_id=result.receipt_id or "",
            filer_id=None,
            operating_year_id=None,
            details={
                "form_type": request.form_type,
                "tax_year": request.tax_year,
                "submission_count": len(batches),
                "recipient_count": total_recipients,
                "transmission_id": result.unique_transmission_id,
            },
        )

        return ATSTestResponse(
            success=result.is_success,
            transmission_id=result.unique_transmission_id,
            status=result.status.value,
            message=result.message,
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
        )

    except Exception as e:
        logger.exception("Error submitting ATS test to IRS")
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
