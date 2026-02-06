"""
Pydantic models for API request/response validation.

These schemas match the Supabase database schema.
"""

from datetime import datetime
from typing import Optional, List, Any
from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# OPERATING YEARS
# =============================================================================

class OperatingYearBase(BaseModel):
    tax_year: int = Field(..., ge=2020, le=2030)
    status: str = Field(default="open", pattern="^(open|closed)$")
    is_current: bool = False


class OperatingYearCreate(OperatingYearBase):
    pass


class OperatingYearUpdate(BaseModel):
    status: Optional[str] = Field(None, pattern="^(open|closed)$")
    is_current: Optional[bool] = None


class OperatingYear(OperatingYearBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


# =============================================================================
# FILERS
# =============================================================================

class FilerBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    name_line_2: Optional[str] = Field(None, max_length=255)
    dba_name: Optional[str] = Field(None, max_length=255)
    tin: str = Field(..., min_length=9, max_length=11)
    tin_type: str = Field(default="EIN", pattern="^(EIN|SSN)$")
    address1: str = Field(..., max_length=255)
    address2: Optional[str] = Field(None, max_length=255)
    city: str = Field(..., max_length=100)
    state: str = Field(..., min_length=2, max_length=2)
    zip: str = Field(..., min_length=5, max_length=10)
    country: str = Field(default="US", max_length=2)
    contact_name: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None
    is_active: bool = Field(default=True)


class FilerCreate(FilerBase):
    model_config = ConfigDict(extra='ignore')  # Ignore extra fields from form

    # Allow form to send alternative field names
    name_line2: Optional[str] = Field(None, max_length=255)  # Form uses name_line2
    contact_phone: Optional[str] = Field(None, max_length=20)  # Form uses contact_phone
    contact_email: Optional[str] = Field(None, max_length=255)  # Form uses contact_email


class FilerUpdate(BaseModel):
    model_config = ConfigDict(extra='ignore')  # Ignore extra fields from form

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    name_line_2: Optional[str] = Field(None, max_length=255)
    name_line2: Optional[str] = Field(None, max_length=255)  # Form uses name_line2
    dba_name: Optional[str] = Field(None, max_length=255)
    tin: Optional[str] = Field(None, min_length=9, max_length=11)
    tin_type: Optional[str] = Field(None, pattern="^(EIN|SSN)$")
    address1: Optional[str] = Field(None, max_length=255)
    address2: Optional[str] = Field(None, max_length=255)
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, min_length=2, max_length=2)
    zip: Optional[str] = Field(None, min_length=5, max_length=10)
    country: Optional[str] = Field(None, max_length=2)
    contact_name: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    contact_phone: Optional[str] = Field(None, max_length=20)  # Form uses contact_phone
    email: Optional[str] = Field(None, max_length=255)
    contact_email: Optional[str] = Field(None, max_length=255)  # Form uses contact_email
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class Filer(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    name_line_2: Optional[str] = None
    dba_name: Optional[str] = None
    tin: str
    tin_type: str
    address1: str
    address2: Optional[str] = None
    city: str
    state: str
    zip: str
    country: str = "US"
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None


# =============================================================================
# RECIPIENTS
# =============================================================================

class RecipientBase(BaseModel):
    filer_id: str
    name: str = Field(..., min_length=1, max_length=255)
    name_line_2: Optional[str] = Field(None, max_length=255)
    tin: str = Field(..., min_length=9, max_length=11)
    tin_type: str = Field(default="SSN", pattern="^(EIN|SSN)$")
    address1: str = Field(..., max_length=255)
    address2: Optional[str] = Field(None, max_length=255)
    city: str = Field(..., max_length=100)
    state: str = Field(..., min_length=2, max_length=2)
    zip: str = Field(..., min_length=5, max_length=10)
    country: str = Field(default="US", max_length=2)
    email: Optional[str] = Field(None, max_length=255)
    account_number: Optional[str] = Field(None, max_length=50)


class RecipientCreate(RecipientBase):
    pass


class RecipientUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    name_line_2: Optional[str] = Field(None, max_length=255)
    tin: Optional[str] = Field(None, min_length=9, max_length=11)
    tin_type: Optional[str] = Field(None, pattern="^(EIN|SSN)$")
    address1: Optional[str] = Field(None, max_length=255)
    address2: Optional[str] = Field(None, max_length=255)
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, min_length=2, max_length=2)
    zip: Optional[str] = Field(None, min_length=5, max_length=10)
    country: Optional[str] = Field(None, max_length=2)
    email: Optional[str] = Field(None, max_length=255)
    account_number: Optional[str] = Field(None, max_length=50)
    is_active: Optional[bool] = None


class RecipientTINUpdate(BaseModel):
    tin_status: str = Field(..., pattern="^(pending|matched|mismatched|error)$")
    tin_match_code: Optional[str] = None


class Recipient(RecipientBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    is_active: bool
    tin_status: Optional[str] = None
    tin_match_code: Optional[str] = None
    tin_checked_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None


# =============================================================================
# 1099 FORMS
# =============================================================================

class Form1099Base(BaseModel):
    filer_id: str
    recipient_id: str
    operating_year_id: str
    form_type: str = Field(..., pattern="^(1099-NEC|1099-MISC|1099-DIV|1099-INT|1099-B|1099-R|1099-S|1098)$")

    # 1099-NEC boxes
    nec_box1: Optional[Decimal] = None  # Nonemployee compensation
    nec_box2: Optional[bool] = None  # Payer made direct sales
    nec_box3: Optional[Decimal] = None  # Other income (golden parachute payments)
    nec_box4: Optional[Decimal] = None  # Federal income tax withheld

    # 1099-MISC boxes
    misc_box1: Optional[Decimal] = None  # Rents
    misc_box2: Optional[Decimal] = None  # Royalties
    misc_box3: Optional[Decimal] = None  # Other income
    misc_box4: Optional[Decimal] = None  # Federal income tax withheld
    misc_box5: Optional[Decimal] = None  # Fishing boat proceeds
    misc_box6: Optional[Decimal] = None  # Medical and health care payments
    misc_box7: Optional[bool] = None  # Payer made direct sales
    misc_box8: Optional[Decimal] = None  # Substitute payments
    misc_box9: Optional[Decimal] = None  # Crop insurance proceeds
    misc_box10: Optional[Decimal] = None  # Gross proceeds paid to attorney
    misc_box11: Optional[Decimal] = None  # Fish purchased for resale
    misc_box12: Optional[Decimal] = None  # Section 409A deferrals
    misc_box14: Optional[Decimal] = None  # Nonqualified deferred compensation

    # 1099-S boxes (Proceeds From Real Estate Transactions)
    s_box1_date_closing: Optional[str] = None  # Date of closing (MM/DD/YYYY)
    s_box2_gross_proceeds: Optional[Decimal] = None  # Gross proceeds
    s_box3_property_address: Optional[str] = None  # Address or legal description
    s_box4_property_services: Optional[bool] = None  # Transferor received property/services
    s_box5_foreign_person: Optional[bool] = None  # Buyer is foreign person
    s_box6_buyers_tax: Optional[Decimal] = None  # Buyer's part of real estate tax

    # 1098 boxes (Mortgage Interest Statement)
    f1098_box1_mortgage_interest: Optional[Decimal] = None  # Mortgage interest received
    f1098_box2_outstanding_principal: Optional[Decimal] = None  # Outstanding mortgage principal
    f1098_box3_origination_date: Optional[str] = None  # Mortgage origination date
    f1098_box4_refund_interest: Optional[Decimal] = None  # Refund of overpaid interest
    f1098_box5_mortgage_insurance: Optional[Decimal] = None  # Mortgage insurance premiums
    f1098_box6_points_paid: Optional[Decimal] = None  # Points paid on purchase
    f1098_box8_property_address: Optional[str] = None  # Property address if different
    f1098_box9_num_properties: Optional[int] = None  # Number of mortgaged properties
    f1098_box10_other: Optional[Decimal] = None  # Other
    f1098_box11_acquisition_date: Optional[str] = None  # Mortgage acquisition date

    # State info
    state1_code: Optional[str] = Field(None, max_length=2)
    state1_id: Optional[str] = Field(None, max_length=20)
    state1_income: Optional[Decimal] = None
    state1_withheld: Optional[Decimal] = None
    state2_code: Optional[str] = Field(None, max_length=2)
    state2_id: Optional[str] = Field(None, max_length=20)
    state2_income: Optional[Decimal] = None
    state2_withheld: Optional[Decimal] = None

    # Correction tracking
    is_correction: bool = False
    corrects_form_id: Optional[str] = None


class Form1099Create(Form1099Base):
    pass


class Form1099Update(BaseModel):
    # 1099-NEC boxes
    nec_box1: Optional[Decimal] = None
    nec_box2: Optional[bool] = None
    nec_box3: Optional[Decimal] = None
    nec_box4: Optional[Decimal] = None

    # 1099-MISC boxes
    misc_box1: Optional[Decimal] = None
    misc_box2: Optional[Decimal] = None
    misc_box3: Optional[Decimal] = None
    misc_box4: Optional[Decimal] = None
    misc_box5: Optional[Decimal] = None
    misc_box6: Optional[Decimal] = None
    misc_box7: Optional[bool] = None
    misc_box8: Optional[Decimal] = None
    misc_box9: Optional[Decimal] = None
    misc_box10: Optional[Decimal] = None
    misc_box11: Optional[Decimal] = None
    misc_box12: Optional[Decimal] = None
    misc_box14: Optional[Decimal] = None

    # 1099-S boxes
    s_box1_date_closing: Optional[str] = None
    s_box2_gross_proceeds: Optional[Decimal] = None
    s_box3_property_address: Optional[str] = None
    s_box4_property_services: Optional[bool] = None
    s_box5_foreign_person: Optional[bool] = None
    s_box6_buyers_tax: Optional[Decimal] = None

    # 1098 boxes
    f1098_box1_mortgage_interest: Optional[Decimal] = None
    f1098_box2_outstanding_principal: Optional[Decimal] = None
    f1098_box3_origination_date: Optional[str] = None
    f1098_box4_refund_interest: Optional[Decimal] = None
    f1098_box5_mortgage_insurance: Optional[Decimal] = None
    f1098_box6_points_paid: Optional[Decimal] = None
    f1098_box8_property_address: Optional[str] = None
    f1098_box9_num_properties: Optional[int] = None
    f1098_box10_other: Optional[Decimal] = None
    f1098_box11_acquisition_date: Optional[str] = None

    # State info
    state1_code: Optional[str] = Field(None, max_length=2)
    state1_id: Optional[str] = Field(None, max_length=20)
    state1_income: Optional[Decimal] = None
    state1_withheld: Optional[Decimal] = None
    state2_code: Optional[str] = Field(None, max_length=2)
    state2_id: Optional[str] = Field(None, max_length=20)
    state2_income: Optional[Decimal] = None
    state2_withheld: Optional[Decimal] = None

    # Correction tracking
    is_correction: Optional[bool] = None

    status: Optional[str] = Field(None, pattern="^(draft|validated|submitted|accepted|rejected|corrected)$")


class Form1099(Form1099Base):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    validation_errors: Optional[List[dict]] = None
    validated_at: Optional[datetime] = None
    submission_id: Optional[str] = None
    irs_record_id: Optional[str] = None
    irs_status: Optional[str] = None
    irs_response: Optional[dict] = None
    corrected_by_form_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None

    # Joined data (optional)
    recipients: Optional[dict] = None
    filers: Optional[dict] = None


class Form1099WithRecipient(Form1099):
    """Form with recipient info joined."""
    pass


# =============================================================================
# DASHBOARD
# =============================================================================

class FilerStatusSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    filer_id: str
    filer_name: str
    operating_year_id: str
    tax_year: int
    total_forms: int
    draft_count: int
    validated_count: int
    submitted_count: int
    accepted_count: int
    rejected_count: int
    total_amount: Decimal


class DashboardStats(BaseModel):
    total_filers: int = 0
    total_recipients: int = 0
    total_forms: int = 0
    forms_by_status: dict = Field(default_factory=dict)
    forms_by_type: dict = Field(default_factory=dict)
    recent_activity: List[dict] = Field(default_factory=list)


# =============================================================================
# ACTIVITY LOG
# =============================================================================

class ActivityLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    filer_id: Optional[str] = None
    operating_year_id: Optional[str] = None
    details: Optional[dict] = None
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime


# =============================================================================
# COMMON RESPONSES
# =============================================================================

class MessageResponse(BaseModel):
    message: str
    success: bool = True


class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None
