"""
IRIS XML Generator for IRS 1099 e-filing.

Generates IRS-compliant XML for IRIS A2A (Application-to-Application) submission.
Based on IRS IRIS Schema TY2025 v1.2 (iris-a2a-schema-and-business-rules-ty2025-v1.2).

Security notes:
- TINs are decrypted only during XML generation
- XML files should be transmitted securely and not stored long-term
- Never log XML content (contains PII)

XML Structure:
- IRTransmission
  - IRTransmissionManifest (header with transmitter info)
  - IRSubmission1Grp (one per issuer/form type combination)
    - IRSubmission1Header (issuer details, totals)
    - IRSubmission1Detail (individual form records)
"""

import uuid
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET
from xml.dom import minidom

logger = logging.getLogger(__name__)

# IRS IRIS XML Namespace
IRIS_NS = "urn:us:gov:treasury:irs:ir"
IRIS_NS_PREFIX = "irs"

# Current schema version (from IRS schema)
SCHEMA_VERSION = "2.0.3"


@dataclass
class TransmitterInfo:
    """Transmitter (software provider) information for IRIS submission."""
    tin: str  # Transmitter TIN (EIN or SSN, 9 digits)
    tin_type: str = "EIN"  # EIN or SSN
    tcc: str = ""  # Transmitter Control Code (5 chars)
    name: str = ""  # Person name for contact
    business_name: str = ""  # Company/business name
    business_name_2: Optional[str] = None  # DBA or second line
    address1: str = ""
    address2: Optional[str] = None
    city: str = ""
    state: str = ""
    zip_code: str = ""
    country: str = "US"
    contact_name: str = ""
    contact_email: str = ""
    contact_phone: str = ""  # 10 digits, no formatting
    is_foreign: bool = False


@dataclass
class VendorInfo:
    """Software vendor information (optional)."""
    business_name: str = ""
    business_name_2: Optional[str] = None
    address1: str = ""
    address2: Optional[str] = None
    city: str = ""
    state: str = ""
    zip_code: str = ""
    country: str = "US"
    contact_name: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    is_foreign: bool = False


@dataclass
class IssuerInfo:
    """Payer/Issuer information (the entity issuing 1099s)."""
    tin: str  # 9 digits
    tin_type: str = "EIN"  # EIN or SSN
    is_foreign: bool = False
    # For business
    business_name: Optional[str] = None
    business_name_2: Optional[str] = None
    business_name_control: Optional[str] = None  # 4 char name control
    # For individual
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    last_name: Optional[str] = None
    suffix: Optional[str] = None
    person_name_control: Optional[str] = None  # 4 char name control
    # Address
    address1: str = ""
    address2: Optional[str] = None
    city: str = ""
    state: str = ""
    zip_code: str = ""
    country: str = "US"
    phone: Optional[str] = None
    # Contact
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    contact_fax: Optional[str] = None


@dataclass
class RecipientInfo:
    """Recipient (payee) information."""
    tin: str  # 9 digits
    tin_type: str = "SSN"  # SSN, EIN, ITIN, ATIN
    # For individual
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    last_name: Optional[str] = None
    suffix: Optional[str] = None
    person_name_control: Optional[str] = None
    # For business
    business_name: Optional[str] = None
    business_name_2: Optional[str] = None
    business_name_control: Optional[str] = None
    # Address
    address1: str = ""
    address2: Optional[str] = None
    city: str = ""
    state: str = ""
    zip_code: str = ""
    country: str = "US"
    # Optional
    account_number: Optional[str] = None


@dataclass
class StateLocalTax:
    """State and local tax withholding information."""
    state_code: str  # 2-letter state code
    state_id_number: Optional[str] = None  # State ID/account number
    state_tax_withheld: Decimal = Decimal("0.00")
    state_income: Decimal = Decimal("0.00")
    local_tax_withheld: Decimal = Decimal("0.00")
    local_income: Decimal = Decimal("0.00")
    locality_name: Optional[str] = None


@dataclass
class Form1099NECData:
    """Data for a single 1099-NEC form."""
    record_id: str  # Unique ID within submission
    tax_year: int
    recipient: RecipientInfo
    # Box values
    nonemployee_compensation: Decimal = Decimal("0.00")  # Box 1
    direct_sales_indicator: bool = False  # Box 2
    federal_tax_withheld: Decimal = Decimal("0.00")  # Box 4
    # State/local (up to 2 states)
    state_local_taxes: List[StateLocalTax] = field(default_factory=list)
    # Flags
    is_void: bool = False
    is_corrected: bool = False
    second_tin_notice: bool = False
    # For corrections
    original_record_id: Optional[str] = None
    # CFSF (Combined Federal/State Filing) election states
    cfsf_states: List[str] = field(default_factory=list)


@dataclass
class Form1099MISCData:
    """Data for a single 1099-MISC form."""
    record_id: str
    tax_year: int
    recipient: RecipientInfo
    # Box values
    rents: Decimal = Decimal("0.00")  # Box 1
    royalties: Decimal = Decimal("0.00")  # Box 2
    other_income: Decimal = Decimal("0.00")  # Box 3
    federal_tax_withheld: Decimal = Decimal("0.00")  # Box 4
    fishing_boat_proceeds: Decimal = Decimal("0.00")  # Box 5
    medical_healthcare_payments: Decimal = Decimal("0.00")  # Box 6
    direct_sales_indicator: bool = False  # Box 7
    substitute_payments: Decimal = Decimal("0.00")  # Box 8
    crop_insurance_proceeds: Decimal = Decimal("0.00")  # Box 9
    gross_proceeds_attorney: Decimal = Decimal("0.00")  # Box 10
    fish_purchased_resale: Decimal = Decimal("0.00")  # Box 11
    section_409a_deferrals: Decimal = Decimal("0.00")  # Box 12
    excess_golden_parachute: Decimal = Decimal("0.00")  # Box 13
    nonqualified_deferred_comp: Decimal = Decimal("0.00")  # Box 14
    # State/local
    state_local_taxes: List[StateLocalTax] = field(default_factory=list)
    # Flags
    is_void: bool = False
    is_corrected: bool = False
    second_tin_notice: bool = False
    fatca_filing_requirement: bool = False
    original_record_id: Optional[str] = None
    cfsf_states: List[str] = field(default_factory=list)


@dataclass
class Form1099SData:
    """Data for a single 1099-S form (Proceeds from Real Estate Transactions)."""
    record_id: str
    tax_year: int
    recipient: RecipientInfo  # Transferor info
    # Box values
    closing_date: Optional[date] = None  # Box 1 - Date of closing
    gross_proceeds: Decimal = Decimal("0.00")  # Box 2 - Gross proceeds
    address_or_legal_desc: str = ""  # Box 3 - Address or legal description
    transferor_received_consideration: bool = False  # Box 4 - Transferor received or will receive property/services
    transferor_is_foreign_person: bool = False  # Box 5 - Transferor is a foreign person
    buyers_real_estate_tax: Decimal = Decimal("0.00")  # Box 6 - Buyer's part of real estate tax
    # Flags
    is_void: bool = False
    is_corrected: bool = False
    original_record_id: Optional[str] = None


@dataclass
class Form1098Data:
    """Data for a single 1098 form (Mortgage Interest Statement)."""
    record_id: str
    tax_year: int
    recipient: RecipientInfo  # Payer/Borrower info
    # Box values
    mortgage_interest_received: Decimal = Decimal("0.00")  # Box 1 - Mortgage interest received
    outstanding_mortgage_principal: Decimal = Decimal("0.00")  # Box 2 - Outstanding mortgage principal
    mortgage_origination_date: Optional[date] = None  # Box 3 - Mortgage origination date
    refund_of_overpaid_interest: Decimal = Decimal("0.00")  # Box 4 - Refund of overpaid interest
    mortgage_insurance_premiums: Decimal = Decimal("0.00")  # Box 5 - Mortgage insurance premiums
    points_paid_on_purchase: Decimal = Decimal("0.00")  # Box 6 - Points paid on purchase of principal residence
    property_address_same_as_borrower: bool = False  # Box 7 - Property address same as borrower
    property_address: str = ""  # Box 8 - Address or description of property
    properties_securing_mortgage_count: int = 0  # Box 9 - Number of properties securing mortgage
    other_info: str = ""  # Box 10 - Other information
    mortgage_acquisition_date: Optional[date] = None  # Box 11 - Mortgage acquisition date
    # Flags
    is_void: bool = False
    is_corrected: bool = False
    original_record_id: Optional[str] = None


@dataclass
class SubmissionBatch:
    """A batch of forms for a single issuer and form type."""
    issuer: IssuerInfo
    form_type: str  # "1099NEC", "1099MISC", etc.
    tax_year: int
    forms: List[Any]  # Form1099NECData or Form1099MISCData
    # Optional signature info
    signature_pin: Optional[str] = None
    signature_date: Optional[date] = None
    signature_title: Optional[str] = None
    signer_name: Optional[str] = None
    # CFSF election at submission level
    cfsf_election: bool = False


class IRISXMLGenerator:
    """
    Generates IRS-compliant XML for IRIS A2A submission.

    Usage:
        generator = IRISXMLGenerator(
            transmitter=transmitter_info,
            software_id="YOUR_SOFTWARE_ID",
            is_test=True,
        )

        xml_content = generator.generate_transmission(
            batches=[submission_batch],
            tax_year=2025,
        )
    """

    def __init__(
        self,
        transmitter: TransmitterInfo,
        software_id: str,
        vendor: Optional[VendorInfo] = None,
        is_test: bool = True,
        is_prior_year: bool = False,
    ):
        """
        Initialize XML generator.

        Args:
            transmitter: Transmitter information (your company)
            software_id: IRS-assigned software ID (10 alphanumeric)
            vendor: Optional vendor information
            is_test: True for ATS test submissions, False for production
            is_prior_year: True if submitting for prior tax year
        """
        self.transmitter = transmitter
        self.software_id = software_id
        self.vendor = vendor
        self.is_test = is_test
        self.is_prior_year = is_prior_year

    def _create_element(self, tag: str, text: Optional[str] = None, parent: Optional[ET.Element] = None) -> ET.Element:
        """Create an XML element with optional text content."""
        elem = ET.Element(f"{{{IRIS_NS}}}{tag}")
        if text is not None:
            elem.text = str(text)
        if parent is not None:
            parent.append(elem)
        return elem

    def _add_element(self, parent: ET.Element, tag: str, text: Optional[str] = None) -> ET.Element:
        """Add a child element to parent with optional text."""
        elem = ET.SubElement(parent, f"{{{IRIS_NS}}}{tag}")
        if text is not None:
            elem.text = str(text)
        return elem

    def _format_tin(self, tin: str) -> str:
        """Format TIN as 9 digits (remove any dashes)."""
        return tin.replace("-", "").replace(" ", "")[:9].zfill(9)

    def _format_amount(self, amount: Optional[Decimal]) -> str:
        """Format decimal amount for IRS (2 decimal places)."""
        if amount is None:
            return "0.00"
        return f"{amount:.2f}"

    def _format_phone(self, phone: Optional[str]) -> Optional[str]:
        """Format phone as 10 digits."""
        if not phone:
            return None
        digits = "".join(c for c in phone if c.isdigit())
        return digits[:10] if len(digits) >= 10 else None

    def _bool_to_indicator(self, value: bool) -> str:
        """Convert boolean to IRS indicator (0 or 1)."""
        return "1" if value else "0"

    def _get_tin_type_code(self, tin_type: str) -> str:
        """Convert TIN type to IRS schema code.

        IRS IRIS schema requires:
        - BUSINESS_TIN (for EIN)
        - INDIVIDUAL_TIN (for SSN, ITIN, ATIN)
        - UNKNOWN

        NOT 'EIN' or 'SSN' directly!
        """
        type_map = {
            "EIN": "BUSINESS_TIN",
            "SSN": "INDIVIDUAL_TIN",
            "ITIN": "INDIVIDUAL_TIN",
            "ATIN": "INDIVIDUAL_TIN",
            "BUSINESS_TIN": "BUSINESS_TIN",
            "INDIVIDUAL_TIN": "INDIVIDUAL_TIN",
        }
        return type_map.get(tin_type.upper(), "INDIVIDUAL_TIN")

    def _derive_name_control(self, name: str, is_business: bool = False) -> str:
        """
        Derive 4-character name control from name.

        For individuals: First 4 chars of last name
        For businesses: First 4 chars of business name (excluding articles)
        """
        if not name:
            return "XXXX"

        # Remove common prefixes for businesses
        if is_business:
            prefixes = ["THE ", "A ", "AN "]
            upper_name = name.upper()
            for prefix in prefixes:
                if upper_name.startswith(prefix):
                    name = name[len(prefix):]
                    break

        # Get first 4 alphanumeric characters
        chars = [c.upper() for c in name if c.isalnum()]
        control = "".join(chars[:4])
        return control.ljust(4, "X")[:4]

    def _add_us_address(self, parent: ET.Element, address1: str, address2: Optional[str],
                        city: str, state: str, zip_code: str) -> ET.Element:
        """Add US address group to parent element."""
        addr_grp = self._add_element(parent, "MailingAddressGrp")
        us_addr = self._add_element(addr_grp, "USAddress")
        self._add_element(us_addr, "AddressLine1Txt", address1[:35] if address1 else "")
        if address2:
            self._add_element(us_addr, "AddressLine2Txt", address2[:35])
        self._add_element(us_addr, "CityNm", city[:40] if city else "")
        self._add_element(us_addr, "StateAbbreviationCd", state[:2].upper() if state else "")
        self._add_element(us_addr, "ZIPCd", zip_code.replace("-", "")[:9] if zip_code else "")
        return addr_grp

    def _add_foreign_address(self, parent: ET.Element, address1: str, address2: Optional[str],
                             city: str, province: str, postal_code: str, country: str) -> ET.Element:
        """Add foreign address group to parent element."""
        addr_grp = self._add_element(parent, "MailingAddressGrp")
        foreign_addr = self._add_element(addr_grp, "ForeignAddress")
        self._add_element(foreign_addr, "AddressLine1Txt", address1[:35] if address1 else "")
        if address2:
            self._add_element(foreign_addr, "AddressLine2Txt", address2[:35])
        self._add_element(foreign_addr, "CityNm", city[:40] if city else "")
        self._add_element(foreign_addr, "ProvinceOrStateNm", province[:35] if province else "")
        self._add_element(foreign_addr, "ForeignPostalCd", postal_code[:16] if postal_code else "")
        self._add_element(foreign_addr, "CountryCd", country[:2].upper() if country else "US")
        return addr_grp

    def _build_transmitter_group(self) -> ET.Element:
        """Build the TransmitterGrp element."""
        t = self.transmitter
        grp = ET.Element(f"{{{IRIS_NS}}}TransmitterGrp")

        self._add_element(grp, "TIN", self._format_tin(t.tin))
        self._add_element(grp, "TINSubmittedTypeCd", self._get_tin_type_code(t.tin_type))
        self._add_element(grp, "TransmitterControlCd", t.tcc[:5].upper())
        self._add_element(grp, "ForeignEntityInd", self._bool_to_indicator(t.is_foreign))

        if t.name:
            self._add_element(grp, "PersonNm", t.name[:35])

        # Company group
        company_grp = self._add_element(grp, "CompanyGrp")
        bus_name = self._add_element(company_grp, "BusinessName")
        self._add_element(bus_name, "BusinessNameLine1Txt", t.business_name[:75] if t.business_name else "")
        if t.business_name_2:
            self._add_element(bus_name, "BusinessNameLine2Txt", t.business_name_2[:75])

        if t.country == "US" or not t.is_foreign:
            self._add_us_address(company_grp, t.address1, t.address2, t.city, t.state, t.zip_code)
        else:
            self._add_foreign_address(company_grp, t.address1, t.address2, t.city, t.state, t.zip_code, t.country)

        # Contact info
        contact_grp = self._add_element(grp, "ContactNameGrp")
        self._add_element(contact_grp, "PersonNm", t.contact_name[:35] if t.contact_name else t.name[:35])

        if t.contact_email:
            self._add_element(grp, "ContactEmailAddressTxt", t.contact_email[:50])

        phone = self._format_phone(t.contact_phone)
        if phone:
            self._add_element(grp, "ContactPhoneNum", phone)

        return grp

    def _build_vendor_group(self) -> Optional[ET.Element]:
        """Build the optional VendorGrp element."""
        if not self.vendor:
            return None

        v = self.vendor
        grp = ET.Element(f"{{{IRIS_NS}}}VendorGrp")

        self._add_element(grp, "ForeignEntityInd", self._bool_to_indicator(v.is_foreign))

        bus_name = self._add_element(grp, "BusinessName")
        self._add_element(bus_name, "BusinessNameLine1Txt", v.business_name[:75] if v.business_name else "")
        if v.business_name_2:
            self._add_element(bus_name, "BusinessNameLine2Txt", v.business_name_2[:75])

        if v.country == "US" or not v.is_foreign:
            self._add_us_address(grp, v.address1, v.address2, v.city, v.state, v.zip_code)
        else:
            self._add_foreign_address(grp, v.address1, v.address2, v.city, v.state, v.zip_code, v.country)

        contact_grp = self._add_element(grp, "ContactNameGrp")
        self._add_element(contact_grp, "PersonNm", v.contact_name[:35] if v.contact_name else "")

        if v.contact_email:
            self._add_element(grp, "ContactEmailAddressTxt", v.contact_email[:50])

        phone = self._format_phone(v.contact_phone)
        if phone:
            self._add_element(grp, "ContactPhoneNum", phone)

        return grp

    def _build_issuer_detail(self, issuer: IssuerInfo) -> ET.Element:
        """Build IssuerDetail element."""
        detail = ET.Element(f"{{{IRIS_NS}}}IssuerDetail")

        self._add_element(detail, "ForeignEntityInd", self._bool_to_indicator(issuer.is_foreign))
        self._add_element(detail, "TIN", self._format_tin(issuer.tin))
        self._add_element(detail, "TINSubmittedTypeCd", self._get_tin_type_code(issuer.tin_type))

        # Either business or person name
        if issuer.business_name:
            name_control = issuer.business_name_control or self._derive_name_control(issuer.business_name, is_business=True)
            self._add_element(detail, "BusinessNameControlTxt", name_control)
            bus_name = self._add_element(detail, "BusinessName")
            self._add_element(bus_name, "BusinessNameLine1Txt", issuer.business_name[:75])
            if issuer.business_name_2:
                self._add_element(bus_name, "BusinessNameLine2Txt", issuer.business_name_2[:75])
        else:
            name_control = issuer.person_name_control or self._derive_name_control(issuer.last_name or "", is_business=False)
            self._add_element(detail, "PersonNameControlTxt", name_control)
            person_name = self._add_element(detail, "PersonName")
            if issuer.first_name:
                self._add_element(person_name, "PersonFirstNm", issuer.first_name[:35])
            if issuer.middle_name:
                self._add_element(person_name, "PersonMiddleNm", issuer.middle_name[:35])
            if issuer.last_name:
                self._add_element(person_name, "PersonLastNm", issuer.last_name[:35])
            if issuer.suffix:
                self._add_element(person_name, "SuffixNm", issuer.suffix[:10])

        # Address
        if issuer.country == "US" or not issuer.is_foreign:
            self._add_us_address(detail, issuer.address1, issuer.address2, issuer.city, issuer.state, issuer.zip_code)
        else:
            self._add_foreign_address(detail, issuer.address1, issuer.address2, issuer.city, issuer.state, issuer.zip_code, issuer.country)

        if issuer.phone:
            phone = self._format_phone(issuer.phone)
            if phone:
                self._add_element(detail, "PhoneNum", phone)

        return detail

    def _build_recipient_detail(self, recipient: RecipientInfo) -> ET.Element:
        """Build RecipientDetail element."""
        detail = ET.Element(f"{{{IRIS_NS}}}RecipientDetail")

        self._add_element(detail, "TIN", self._format_tin(recipient.tin))
        self._add_element(detail, "TINSubmittedTypeCd", self._get_tin_type_code(recipient.tin_type))

        # Either business or person name
        if recipient.business_name:
            name_control = recipient.business_name_control or self._derive_name_control(recipient.business_name, is_business=True)
            self._add_element(detail, "BusinessNameControlTxt", name_control)
            bus_name = self._add_element(detail, "BusinessName")
            self._add_element(bus_name, "BusinessNameLine1Txt", recipient.business_name[:75])
            if recipient.business_name_2:
                self._add_element(bus_name, "BusinessNameLine2Txt", recipient.business_name_2[:75])
        else:
            name_control = recipient.person_name_control or self._derive_name_control(recipient.last_name or "", is_business=False)
            self._add_element(detail, "PersonNameControlTxt", name_control)
            person_name = self._add_element(detail, "PersonName")
            if recipient.first_name:
                self._add_element(person_name, "PersonFirstNm", recipient.first_name[:35])
            if recipient.middle_name:
                self._add_element(person_name, "PersonMiddleNm", recipient.middle_name[:35])
            if recipient.last_name:
                self._add_element(person_name, "PersonLastNm", recipient.last_name[:35])
            if recipient.suffix:
                self._add_element(person_name, "SuffixNm", recipient.suffix[:10])

        # Address
        self._add_us_address(detail, recipient.address1, recipient.address2,
                           recipient.city, recipient.state, recipient.zip_code)

        return detail

    def _build_state_local_tax_group(self, state_tax: StateLocalTax) -> ET.Element:
        """Build StateLocalTaxGrp element."""
        grp = ET.Element(f"{{{IRIS_NS}}}StateLocalTaxGrp")

        self._add_element(grp, "StateAbbreviationCd", state_tax.state_code[:2].upper())

        state_grp = self._add_element(grp, "StateTaxGrp")
        if state_tax.state_id_number:
            self._add_element(state_grp, "StateIdNum", state_tax.state_id_number[:20])
        self._add_element(state_grp, "StateTaxWithheldAmt", self._format_amount(state_tax.state_tax_withheld))
        self._add_element(state_grp, "StateIncomeAmt", self._format_amount(state_tax.state_income))
        self._add_element(state_grp, "StateDistributionAmt", "0")

        if state_tax.local_tax_withheld > 0 or state_tax.locality_name:
            local_grp = self._add_element(grp, "LocalTaxGrp")
            if state_tax.locality_name:
                self._add_element(local_grp, "LocalityNm", state_tax.locality_name[:20])
            self._add_element(local_grp, "LocalTaxWithheldAmt", self._format_amount(state_tax.local_tax_withheld))
            self._add_element(local_grp, "LocalIncomeAmt", self._format_amount(state_tax.local_income))

        return grp

    def _build_1099nec_detail(self, form: Form1099NECData) -> ET.Element:
        """Build Form1099NECDetail element."""
        detail = ET.Element(f"{{{IRIS_NS}}}Form1099NECDetail")

        self._add_element(detail, "TaxYr", str(form.tax_year))
        self._add_element(detail, "RecordId", form.record_id[:20])

        # CFSF election states
        for state in form.cfsf_states:
            self._add_element(detail, "CFSFElectionStateCd", state[:2].upper())

        self._add_element(detail, "VoidInd", "0")  # Always 0 for electronic filing
        self._add_element(detail, "CorrectedInd", self._bool_to_indicator(form.is_corrected))

        # Original record reference for corrections
        if form.is_corrected and form.original_record_id:
            prev_grp = self._add_element(detail, "PrevSubmittedRecRecipientGrp")
            self._add_element(prev_grp, "UniqueRecordId", form.original_record_id)

        # Recipient detail
        detail.append(self._build_recipient_detail(form.recipient))

        # Account number (optional)
        if form.recipient.account_number:
            self._add_element(detail, "RecipientAccountNum", form.recipient.account_number[:30])

        self._add_element(detail, "SecondTINNoticeInd", self._bool_to_indicator(form.second_tin_notice))

        # Box 1 - Nonemployee compensation
        if form.nonemployee_compensation > 0:
            self._add_element(detail, "NonemployeeCompensationAmt", self._format_amount(form.nonemployee_compensation))

        # Box 2 - Direct sales indicator
        self._add_element(detail, "DirectSaleAboveThresholdInd", self._bool_to_indicator(form.direct_sales_indicator))

        # Box 4 - Federal income tax withheld
        if form.federal_tax_withheld > 0:
            self._add_element(detail, "FederalIncomeTaxWithheldAmt", self._format_amount(form.federal_tax_withheld))

        # State/local tax groups
        for state_tax in form.state_local_taxes:
            detail.append(self._build_state_local_tax_group(state_tax))

        return detail

    def _build_1099misc_detail(self, form: Form1099MISCData) -> ET.Element:
        """Build Form1099MISCDetail element."""
        detail = ET.Element(f"{{{IRIS_NS}}}Form1099MISCDetail")

        self._add_element(detail, "TaxYr", str(form.tax_year))
        self._add_element(detail, "RecordId", form.record_id[:20])

        for state in form.cfsf_states:
            self._add_element(detail, "CFSFElectionStateCd", state[:2].upper())

        self._add_element(detail, "VoidInd", "0")
        self._add_element(detail, "CorrectedInd", self._bool_to_indicator(form.is_corrected))

        if form.is_corrected and form.original_record_id:
            prev_grp = self._add_element(detail, "PrevSubmittedRecRecipientGrp")
            self._add_element(prev_grp, "UniqueRecordId", form.original_record_id)

        detail.append(self._build_recipient_detail(form.recipient))

        if form.recipient.account_number:
            self._add_element(detail, "RecipientAccountNum", form.recipient.account_number[:30])

        self._add_element(detail, "SecondTINNoticeInd", self._bool_to_indicator(form.second_tin_notice))
        self._add_element(detail, "FATCAFilingRequirementInd", self._bool_to_indicator(form.fatca_filing_requirement))

        # Box amounts
        if form.rents > 0:
            self._add_element(detail, "RentAmt", self._format_amount(form.rents))
        if form.royalties > 0:
            self._add_element(detail, "RoyaltyAmt", self._format_amount(form.royalties))
        if form.other_income > 0:
            self._add_element(detail, "OtherIncomeAmt", self._format_amount(form.other_income))
        if form.federal_tax_withheld > 0:
            self._add_element(detail, "FederalIncomeTaxWithheldAmt", self._format_amount(form.federal_tax_withheld))
        if form.fishing_boat_proceeds > 0:
            self._add_element(detail, "FishingBoatProceedsAmt", self._format_amount(form.fishing_boat_proceeds))
        if form.medical_healthcare_payments > 0:
            self._add_element(detail, "MedicalHealthCarePaymentAmt", self._format_amount(form.medical_healthcare_payments))

        self._add_element(detail, "DirectSaleAboveThresholdInd", self._bool_to_indicator(form.direct_sales_indicator))

        if form.substitute_payments > 0:
            self._add_element(detail, "SubstitutePaymentAmt", self._format_amount(form.substitute_payments))
        if form.crop_insurance_proceeds > 0:
            self._add_element(detail, "CropInsuranceProceedAmt", self._format_amount(form.crop_insurance_proceeds))
        if form.gross_proceeds_attorney > 0:
            self._add_element(detail, "GrossProceedsPaidToAttorneyAmt", self._format_amount(form.gross_proceeds_attorney))
        if form.fish_purchased_resale > 0:
            self._add_element(detail, "FishPurchasedForResaleAmt", self._format_amount(form.fish_purchased_resale))
        if form.section_409a_deferrals > 0:
            self._add_element(detail, "Section409ADeferralAmt", self._format_amount(form.section_409a_deferrals))
        if form.nonqualified_deferred_comp > 0:
            self._add_element(detail, "NonqualifiedDeferredCompensationAmt", self._format_amount(form.nonqualified_deferred_comp))

        for state_tax in form.state_local_taxes:
            detail.append(self._build_state_local_tax_group(state_tax))

        return detail

    def _build_1099s_detail(self, form: Form1099SData) -> ET.Element:
        """Build Form1099SDetail element for real estate transactions."""
        detail = ET.Element(f"{{{IRIS_NS}}}Form1099SDetail")

        self._add_element(detail, "TaxYr", str(form.tax_year))
        self._add_element(detail, "RecordId", form.record_id[:20])

        self._add_element(detail, "VoidInd", "0")
        self._add_element(detail, "CorrectedInd", self._bool_to_indicator(form.is_corrected))

        if form.is_corrected and form.original_record_id:
            prev_grp = self._add_element(detail, "PrevSubmittedRecRecipientGrp")
            self._add_element(prev_grp, "UniqueRecordId", form.original_record_id)

        # Recipient (Transferor) detail
        detail.append(self._build_recipient_detail(form.recipient))

        # Account number (optional)
        if form.recipient.account_number:
            self._add_element(detail, "RecipientAccountNum", form.recipient.account_number[:30])

        # Box 1 - Date of closing
        if form.closing_date:
            self._add_element(detail, "ClosingDt", form.closing_date.isoformat())

        # Box 2 - Gross proceeds
        if form.gross_proceeds > 0:
            self._add_element(detail, "GrossProceedsAmt", self._format_amount(form.gross_proceeds))

        # Box 3 - Address or legal description of property
        if form.address_or_legal_desc:
            self._add_element(detail, "AddressOrLegalDescTxt", form.address_or_legal_desc[:100])

        # Box 4 - Transferor received or will receive property or services
        self._add_element(detail, "TransferorRcvdConsiderationInd", self._bool_to_indicator(form.transferor_received_consideration))

        # Box 5 - Transferor is a foreign person
        self._add_element(detail, "TransferorForeignPersonInd", self._bool_to_indicator(form.transferor_is_foreign_person))

        # Box 6 - Buyer's part of real estate tax
        if form.buyers_real_estate_tax > 0:
            self._add_element(detail, "BuyerRealEstateTaxAmt", self._format_amount(form.buyers_real_estate_tax))

        return detail

    def _build_1098_detail(self, form: Form1098Data) -> ET.Element:
        """Build Form1098Detail element for mortgage interest statements."""
        detail = ET.Element(f"{{{IRIS_NS}}}Form1098Detail")

        self._add_element(detail, "TaxYr", str(form.tax_year))
        self._add_element(detail, "RecordId", form.record_id[:20])

        self._add_element(detail, "VoidInd", "0")
        self._add_element(detail, "CorrectedInd", self._bool_to_indicator(form.is_corrected))

        if form.is_corrected and form.original_record_id:
            prev_grp = self._add_element(detail, "PrevSubmittedRecRecipientGrp")
            self._add_element(prev_grp, "UniqueRecordId", form.original_record_id)

        # Recipient (Payer/Borrower) detail
        detail.append(self._build_recipient_detail(form.recipient))

        # Account number (optional)
        if form.recipient.account_number:
            self._add_element(detail, "RecipientAccountNum", form.recipient.account_number[:30])

        # Box 1 - Mortgage interest received from payer(s)/borrower(s)
        if form.mortgage_interest_received > 0:
            self._add_element(detail, "MortgageInterestReceivedAmt", self._format_amount(form.mortgage_interest_received))

        # Box 2 - Outstanding mortgage principal
        if form.outstanding_mortgage_principal > 0:
            self._add_element(detail, "OutstandingMortgPrincipalAmt", self._format_amount(form.outstanding_mortgage_principal))

        # Box 3 - Mortgage origination date
        if form.mortgage_origination_date:
            self._add_element(detail, "MortgageOriginationDt", form.mortgage_origination_date.isoformat())

        # Box 4 - Refund of overpaid interest
        if form.refund_of_overpaid_interest > 0:
            self._add_element(detail, "OverpaidInterestRefundAmt", self._format_amount(form.refund_of_overpaid_interest))

        # Box 5 - Mortgage insurance premiums
        if form.mortgage_insurance_premiums > 0:
            self._add_element(detail, "MortgageInsurancePremiumsAmt", self._format_amount(form.mortgage_insurance_premiums))

        # Box 6 - Points paid on purchase of principal residence
        if form.points_paid_on_purchase > 0:
            self._add_element(detail, "PrinResPurchasePointsPaidAmt", self._format_amount(form.points_paid_on_purchase))

        # Box 7 - Property address same as borrower address indicator
        self._add_element(detail, "PropAddrSameBorrowerAddrInd", self._bool_to_indicator(form.property_address_same_as_borrower))

        # Box 8 - Address or description of property securing mortgage
        if form.property_address and not form.property_address_same_as_borrower:
            prop_grp = self._add_element(detail, "PropertyAddressGrp")
            self._add_element(prop_grp, "PropertyDesc", form.property_address[:100])

        # Box 9 - Number of properties securing the mortgage
        if form.properties_securing_mortgage_count > 0:
            self._add_element(detail, "PropertiesSecuringMortgageCnt", str(form.properties_securing_mortgage_count))

        # Box 10 - Other information
        if form.other_info:
            self._add_element(detail, "OtherTxt", form.other_info[:100])

        # Box 11 - Mortgage acquisition date
        if form.mortgage_acquisition_date:
            self._add_element(detail, "MortgageAcquisitionDt", form.mortgage_acquisition_date.isoformat())

        return detail

    def _calculate_nec_totals(self, forms: List[Form1099NECData]) -> Tuple[ET.Element, List[ET.Element]]:
        """Calculate totals for 1099-NEC forms."""
        total_compensation = Decimal("0.00")
        total_fed_withheld = Decimal("0.00")
        state_totals: Dict[str, Dict[str, Decimal]] = {}

        for form in forms:
            total_compensation += form.nonemployee_compensation
            total_fed_withheld += form.federal_tax_withheld

            for st in form.state_local_taxes:
                if st.state_code not in state_totals:
                    state_totals[st.state_code] = {
                        "count": Decimal("0"),
                        "fed_withheld": Decimal("0.00"),
                        "state_withheld": Decimal("0.00"),
                        "local_withheld": Decimal("0.00"),
                        "compensation": Decimal("0.00"),
                    }
                state_totals[st.state_code]["count"] += 1
                state_totals[st.state_code]["fed_withheld"] += form.federal_tax_withheld
                state_totals[st.state_code]["state_withheld"] += st.state_tax_withheld
                state_totals[st.state_code]["local_withheld"] += st.local_tax_withheld
                state_totals[st.state_code]["compensation"] += form.nonemployee_compensation

        # Total amounts group
        totals_grp = ET.Element(f"{{{IRIS_NS}}}Form1099NECTotalAmtGrp")
        if total_fed_withheld > 0:
            self._add_element(totals_grp, "FederalIncomeTaxWithheldAmt", self._format_amount(total_fed_withheld))
        if total_compensation > 0:
            self._add_element(totals_grp, "NonemployeeCompensationAmt", self._format_amount(total_compensation))

        # State totals
        state_grps = []
        for state_code, totals in state_totals.items():
            state_grp = ET.Element(f"{{{IRIS_NS}}}Form1099NECTotalByStateGrp")
            self._add_element(state_grp, "StateAbbreviationCd", state_code)
            self._add_element(state_grp, "TotalReportedRcpntFormCnt", str(int(totals["count"])))
            self._add_element(state_grp, "FederalIncomeTaxWithheldAmt", self._format_amount(totals["fed_withheld"]))
            self._add_element(state_grp, "StateTaxWithheldAmt", self._format_amount(totals["state_withheld"]))
            self._add_element(state_grp, "LocalTaxWithheldAmt", self._format_amount(totals["local_withheld"]))
            self._add_element(state_grp, "NonemployeeCompensationAmt", self._format_amount(totals["compensation"]))
            state_grps.append(state_grp)

        return totals_grp, state_grps

    def _calculate_misc_totals(self, forms: List[Form1099MISCData]) -> Tuple[ET.Element, List[ET.Element]]:
        """Calculate totals for 1099-MISC forms."""
        totals = {
            "fed_withheld": Decimal("0.00"),
            "rents": Decimal("0.00"),
            "royalties": Decimal("0.00"),
            "other_income": Decimal("0.00"),
            "fishing_boat": Decimal("0.00"),
            "medical": Decimal("0.00"),
            "substitute": Decimal("0.00"),
            "crop_insurance": Decimal("0.00"),
            "attorney": Decimal("0.00"),
            "fish_resale": Decimal("0.00"),
            "409a": Decimal("0.00"),
            "nonqual_deferred": Decimal("0.00"),
        }
        state_totals: Dict[str, Dict[str, Decimal]] = {}

        for form in forms:
            totals["fed_withheld"] += form.federal_tax_withheld
            totals["rents"] += form.rents
            totals["royalties"] += form.royalties
            totals["other_income"] += form.other_income
            totals["fishing_boat"] += form.fishing_boat_proceeds
            totals["medical"] += form.medical_healthcare_payments
            totals["substitute"] += form.substitute_payments
            totals["crop_insurance"] += form.crop_insurance_proceeds
            totals["attorney"] += form.gross_proceeds_attorney
            totals["fish_resale"] += form.fish_purchased_resale
            totals["409a"] += form.section_409a_deferrals
            totals["nonqual_deferred"] += form.nonqualified_deferred_comp

            for st in form.state_local_taxes:
                if st.state_code not in state_totals:
                    state_totals[st.state_code] = {
                        "count": Decimal("0"),
                        "fed_withheld": Decimal("0.00"),
                        "state_withheld": Decimal("0.00"),
                        "local_withheld": Decimal("0.00"),
                        "rents": Decimal("0.00"),
                        "royalties": Decimal("0.00"),
                        "other_income": Decimal("0.00"),
                    }
                state_totals[st.state_code]["count"] += 1
                state_totals[st.state_code]["fed_withheld"] += form.federal_tax_withheld
                state_totals[st.state_code]["state_withheld"] += st.state_tax_withheld
                state_totals[st.state_code]["local_withheld"] += st.local_tax_withheld
                state_totals[st.state_code]["rents"] += form.rents
                state_totals[st.state_code]["royalties"] += form.royalties
                state_totals[st.state_code]["other_income"] += form.other_income

        totals_grp = ET.Element(f"{{{IRIS_NS}}}Form1099MISCTotalAmtGrp")
        if totals["fed_withheld"] > 0:
            self._add_element(totals_grp, "FederalIncomeTaxWithheldAmt", self._format_amount(totals["fed_withheld"]))
        if totals["rents"] > 0:
            self._add_element(totals_grp, "RentAmt", self._format_amount(totals["rents"]))
        if totals["royalties"] > 0:
            self._add_element(totals_grp, "RoyaltyAmt", self._format_amount(totals["royalties"]))
        if totals["other_income"] > 0:
            self._add_element(totals_grp, "OtherIncomeAmt", self._format_amount(totals["other_income"]))
        if totals["fishing_boat"] > 0:
            self._add_element(totals_grp, "FishingBoatProceedsAmt", self._format_amount(totals["fishing_boat"]))
        if totals["medical"] > 0:
            self._add_element(totals_grp, "MedicalHealthCarePaymentAmt", self._format_amount(totals["medical"]))

        state_grps = []
        for state_code, st_totals in state_totals.items():
            state_grp = ET.Element(f"{{{IRIS_NS}}}Form1099MISCTotalByStateGrp")
            self._add_element(state_grp, "StateAbbreviationCd", state_code)
            self._add_element(state_grp, "TotalReportedRcpntFormCnt", str(int(st_totals["count"])))
            self._add_element(state_grp, "FederalIncomeTaxWithheldAmt", self._format_amount(st_totals["fed_withheld"]))
            self._add_element(state_grp, "StateTaxWithheldAmt", self._format_amount(st_totals["state_withheld"]))
            self._add_element(state_grp, "LocalTaxWithheldAmt", self._format_amount(st_totals["local_withheld"]))
            self._add_element(state_grp, "RentAmt", self._format_amount(st_totals["rents"]))
            self._add_element(state_grp, "RoyaltyAmt", self._format_amount(st_totals["royalties"]))
            self._add_element(state_grp, "OtherIncomeAmt", self._format_amount(st_totals["other_income"]))
            state_grps.append(state_grp)

        return totals_grp, state_grps

    def _calculate_1099s_totals(self, forms: List[Form1099SData]) -> ET.Element:
        """Calculate totals for 1099-S forms."""
        total_gross_proceeds = Decimal("0.00")
        total_buyers_re_tax = Decimal("0.00")

        for form in forms:
            total_gross_proceeds += form.gross_proceeds
            total_buyers_re_tax += form.buyers_real_estate_tax

        totals_grp = ET.Element(f"{{{IRIS_NS}}}Form1099STotalAmtGrp")
        if total_gross_proceeds > 0:
            self._add_element(totals_grp, "GrossProceedsAmt", self._format_amount(total_gross_proceeds))
        if total_buyers_re_tax > 0:
            self._add_element(totals_grp, "BuyerRealEstateTaxAmt", self._format_amount(total_buyers_re_tax))

        return totals_grp

    def _calculate_1098_totals(self, forms: List[Form1098Data]) -> ET.Element:
        """Calculate totals for 1098 forms."""
        total_interest = Decimal("0.00")
        total_principal = Decimal("0.00")
        total_refund = Decimal("0.00")
        total_insurance = Decimal("0.00")
        total_points = Decimal("0.00")

        for form in forms:
            total_interest += form.mortgage_interest_received
            total_principal += form.outstanding_mortgage_principal
            total_refund += form.refund_of_overpaid_interest
            total_insurance += form.mortgage_insurance_premiums
            total_points += form.points_paid_on_purchase

        totals_grp = ET.Element(f"{{{IRIS_NS}}}Form1098TotalAmtGrp")
        if total_interest > 0:
            self._add_element(totals_grp, "MortgageInterestReceivedAmt", self._format_amount(total_interest))
        if total_principal > 0:
            self._add_element(totals_grp, "OutstandingMortgPrincipalAmt", self._format_amount(total_principal))
        if total_refund > 0:
            self._add_element(totals_grp, "OverpaidInterestRefundAmt", self._format_amount(total_refund))
        if total_insurance > 0:
            self._add_element(totals_grp, "MortgageInsurancePremiumsAmt", self._format_amount(total_insurance))
        if total_points > 0:
            self._add_element(totals_grp, "PrinResPurchasePointsPaidAmt", self._format_amount(total_points))

        return totals_grp

    def _build_submission_1_group(self, batch: SubmissionBatch, submission_id: str) -> ET.Element:
        """Build IRSubmission1Grp for a batch of forms."""
        grp = ET.Element(f"{{{IRIS_NS}}}IRSubmission1Grp")

        # Header
        header = self._add_element(grp, "IRSubmission1Header")
        self._add_element(header, "SubmissionId", submission_id)
        self._add_element(header, "TaxYr", str(batch.tax_year))

        # Issuer detail
        header.append(self._build_issuer_detail(batch.issuer))

        # Contact info (optional)
        if batch.issuer.contact_name or batch.issuer.contact_phone:
            contact_grp = self._add_element(header, "ContactPersonInformationGrp")
            if batch.issuer.contact_name:
                self._add_element(contact_grp, "ContactPersonNm", batch.issuer.contact_name[:35])
            if batch.issuer.contact_phone:
                phone = self._format_phone(batch.issuer.contact_phone)
                if phone:
                    self._add_element(contact_grp, "ContactPhoneNum", phone)
            if batch.issuer.contact_email:
                self._add_element(contact_grp, "ContactEmailAddressTxt", batch.issuer.contact_email[:50])
            if batch.issuer.contact_fax:
                fax = self._format_phone(batch.issuer.contact_fax)
                if fax:
                    self._add_element(contact_grp, "ContactFaxNum", fax)

        # Form type
        self._add_element(header, "FormTypeCd", batch.form_type)
        self._add_element(header, "ParentFormTypeCd", "1096")
        self._add_element(header, "CFSFElectionInd", self._bool_to_indicator(batch.cfsf_election))

        # Signature group (optional but recommended)
        if batch.signature_pin:
            sig_grp = self._add_element(header, "JuratSignatureGrp")
            self._add_element(sig_grp, "SignatureIntentInd", "1")
            self._add_element(sig_grp, "JuratSignaturePIN", batch.signature_pin[:5])
            sig_date = batch.signature_date or date.today()
            self._add_element(sig_grp, "SignatureDt", sig_date.isoformat())
            if batch.signature_title:
                self._add_element(sig_grp, "JuratPersonTitleTxt", batch.signature_title[:35])
            if batch.signer_name:
                self._add_element(sig_grp, "PersonNm", batch.signer_name[:35])

        # Recipient count
        self._add_element(header, "TotalReportedRcpntFormCnt", str(len(batch.forms)))

        # Form totals
        form_totals = self._add_element(header, "IRSubmission1FormTotals")

        if batch.form_type == "1099NEC":
            totals_grp, state_grps = self._calculate_nec_totals(batch.forms)
            form_totals.append(totals_grp)
            for sg in state_grps:
                form_totals.append(sg)
        elif batch.form_type == "1099MISC":
            totals_grp, state_grps = self._calculate_misc_totals(batch.forms)
            form_totals.append(totals_grp)
            for sg in state_grps:
                form_totals.append(sg)
        elif batch.form_type == "1099S":
            totals_grp = self._calculate_1099s_totals(batch.forms)
            form_totals.append(totals_grp)
        elif batch.form_type == "1098":
            totals_grp = self._calculate_1098_totals(batch.forms)
            form_totals.append(totals_grp)

        # Detail section with individual forms
        if batch.forms:
            detail = self._add_element(grp, "IRSubmission1Detail")
            for form in batch.forms:
                if batch.form_type == "1099NEC":
                    detail.append(self._build_1099nec_detail(form))
                elif batch.form_type == "1099MISC":
                    detail.append(self._build_1099misc_detail(form))
                elif batch.form_type == "1099S":
                    detail.append(self._build_1099s_detail(form))
                elif batch.form_type == "1098":
                    detail.append(self._build_1098_detail(form))

        return grp

    def _generate_utid(self) -> str:
        """
        Generate a Unique Transmission ID (UTID) per IRS Pub 5718/5719 requirements.

        Format: {UUID}:IRIS:{TCC}::{ChannelIndicator}
        - UUID: Random UUID (with dashes)
        - IRIS: Literal string
        - TCC: Transmitter Control Code (must match TransmitterControlCd in manifest)
        - ChannelIndicator: MUST be "A" for A2A (Application-to-Application) channel
          NOTE: IRS requires "A" for all A2A submissions regardless of test/prod!
          The TestCd element (T/P) indicates test vs production, not the UTID suffix.

        The TCC portion of UTID MUST match TransmitterControlCd or transmission will reject.
        """
        # IRS A2A channel requires "A" suffix (not U, T, or P)
        # Test vs Production is indicated by TestCd element, not UTID suffix
        tcc = self.transmitter.tcc[:5].upper() if self.transmitter.tcc else "XXXXX"
        return f"{uuid.uuid4()}:IRIS:{tcc}::A"

    def generate_transmission(
        self,
        batches: List[SubmissionBatch],
        tax_year: int,
        transmission_id: Optional[str] = None,
    ) -> str:
        """
        Generate complete IRIS transmission XML.

        Args:
            batches: List of submission batches (one per issuer/form type)
            tax_year: Tax year for the transmission
            transmission_id: Optional unique transmission ID (UUID generated if not provided)

        Returns:
            str: Complete XML document as string
        """
        if not transmission_id:
            transmission_id = self._generate_utid()

        # Calculate totals
        total_issuers = len(batches)
        total_recipients = sum(len(b.forms) for b in batches)

        # Determine transmission type based on whether any forms are corrections
        # O=Original, C=Corrected, R=Replacement
        has_corrections = any(
            getattr(form, 'is_corrected', False)
            for batch in batches
            for form in batch.forms
        )
        transmission_type = "C" if has_corrections else "O"

        # Register namespace
        ET.register_namespace("", IRIS_NS)

        # Root element
        root = ET.Element(
            f"{{{IRIS_NS}}}IRTransmission",
            {
                "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                "xsi:schemaLocation": f"{IRIS_NS} ../MSG/IRS-IRIntakeTransmissionMessage.xsd",
            }
        )

        # Transmission manifest
        manifest = self._add_element(root, "IRTransmissionManifest")
        self._add_element(manifest, "SchemaVersionNum", SCHEMA_VERSION)
        self._add_element(manifest, "UniqueTransmissionId", transmission_id)
        self._add_element(manifest, "TaxYr", str(tax_year))
        self._add_element(manifest, "PriorYearDataInd", self._bool_to_indicator(self.is_prior_year))
        self._add_element(manifest, "TransmissionTypeCd", transmission_type)
        self._add_element(manifest, "TestCd", "T" if self.is_test else "P")

        # Transmitter group
        manifest.append(self._build_transmitter_group())

        # Vendor info
        self._add_element(manifest, "VendorCd", "V" if self.vendor else "I")  # V=Vendor, I=In-house
        self._add_element(manifest, "SoftwareId", self.software_id[:10])

        vendor_grp = self._build_vendor_group()
        if vendor_grp is not None:
            manifest.append(vendor_grp)

        # Counts
        self._add_element(manifest, "TotalIssuerFormCnt", str(total_issuers))
        self._add_element(manifest, "TotalRecipientFormCnt", str(total_recipients))
        self._add_element(manifest, "PaperSubmissionInd", "0")
        self._add_element(manifest, "MediaSourceCd", "M")  # M=Magnetic media
        self._add_element(manifest, "SubmissionChannelCd", "A2A")

        # Add submission groups
        for i, batch in enumerate(batches, 1):
            root.append(self._build_submission_1_group(batch, str(i)))

        # Convert to string with pretty printing
        xml_str = ET.tostring(root, encoding="unicode")

        # Pretty print
        dom = minidom.parseString(xml_str)
        pretty_xml = dom.toprettyxml(indent="\t", encoding="UTF-8")

        # Remove extra blank lines and fix XML declaration
        lines = pretty_xml.decode("utf-8").split("\n")
        cleaned_lines = [line for line in lines if line.strip()]

        return "\n".join(cleaned_lines)

    def generate_transmission_bytes(
        self,
        batches: List[SubmissionBatch],
        tax_year: int,
        transmission_id: Optional[str] = None,
    ) -> bytes:
        """Generate transmission XML as bytes (UTF-8 encoded)."""
        xml_str = self.generate_transmission(batches, tax_year, transmission_id)
        return xml_str.encode("utf-8")


def convert_db_records_to_submission(
    filer: Dict[str, Any],
    recipients_forms: List[Tuple[Dict[str, Any], Dict[str, Any]]],
    tax_year: int,
    form_type: str = "1099NEC",
) -> SubmissionBatch:
    """
    Convert database records to SubmissionBatch for XML generation.

    Args:
        filer: Filer record from database
        recipients_forms: List of (recipient, form) tuples
        tax_year: Tax year
        form_type: Form type (1099NEC, 1099MISC)

    Returns:
        SubmissionBatch ready for XML generation
    """
    # Build issuer info
    issuer = IssuerInfo(
        tin=filer["tin"],
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

    forms = []
    for i, (recipient, form_data) in enumerate(recipients_forms, 1):
        # Parse recipient name
        name_parts = recipient.get("name", "").split(" ", 2)
        first_name = name_parts[0] if len(name_parts) > 0 else ""
        middle_name = name_parts[1] if len(name_parts) > 2 else ""
        last_name = name_parts[-1] if len(name_parts) > 1 else name_parts[0]

        # Check if recipient is a business (EIN) or individual (SSN)
        is_business = recipient.get("tin_type", "SSN") == "EIN"

        recipient_info = RecipientInfo(
            tin=recipient["tin"],
            tin_type=recipient.get("tin_type", "SSN"),
            first_name=None if is_business else first_name,
            middle_name=None if is_business else middle_name,
            last_name=None if is_business else last_name,
            business_name=recipient.get("name") if is_business else None,
            business_name_2=recipient.get("name_line_2") if is_business else None,
            address1=recipient.get("address1", ""),
            address2=recipient.get("address2"),
            city=recipient.get("city", ""),
            state=recipient.get("state", ""),
            zip_code=recipient.get("zip", ""),
            account_number=recipient.get("account_number"),
        )

        # Build state/local tax info
        state_taxes = []
        if form_data.get("state1_code"):
            state_taxes.append(StateLocalTax(
                state_code=form_data["state1_code"],
                state_id_number=form_data.get("state1_id"),
                state_tax_withheld=Decimal(str(form_data.get("state1_withheld") or 0)),
                state_income=Decimal(str(form_data.get("state1_income") or 0)),
            ))
        if form_data.get("state2_code"):
            state_taxes.append(StateLocalTax(
                state_code=form_data["state2_code"],
                state_id_number=form_data.get("state2_id"),
                state_tax_withheld=Decimal(str(form_data.get("state2_withheld") or 0)),
                state_income=Decimal(str(form_data.get("state2_income") or 0)),
            ))

        if form_type == "1099NEC":
            form = Form1099NECData(
                record_id=str(i),
                tax_year=tax_year,
                recipient=recipient_info,
                nonemployee_compensation=Decimal(str(form_data.get("nec_box1") or 0)),
                direct_sales_indicator=bool(form_data.get("nec_box2")),
                federal_tax_withheld=Decimal(str(form_data.get("nec_box4") or 0)),
                state_local_taxes=state_taxes,
                is_corrected=bool(form_data.get("is_correction")),
                cfsf_states=[st.state_code for st in state_taxes],
            )
            forms.append(form)
        elif form_type == "1099MISC":
            form = Form1099MISCData(
                record_id=str(i),
                tax_year=tax_year,
                recipient=recipient_info,
                rents=Decimal(str(form_data.get("misc_box1") or 0)),
                royalties=Decimal(str(form_data.get("misc_box2") or 0)),
                other_income=Decimal(str(form_data.get("misc_box3") or 0)),
                federal_tax_withheld=Decimal(str(form_data.get("misc_box4") or 0)),
                fishing_boat_proceeds=Decimal(str(form_data.get("misc_box5") or 0)),
                medical_healthcare_payments=Decimal(str(form_data.get("misc_box6") or 0)),
                direct_sales_indicator=bool(form_data.get("misc_box7")),
                substitute_payments=Decimal(str(form_data.get("misc_box8") or 0)),
                crop_insurance_proceeds=Decimal(str(form_data.get("misc_box9") or 0)),
                gross_proceeds_attorney=Decimal(str(form_data.get("misc_box10") or 0)),
                fish_purchased_resale=Decimal(str(form_data.get("misc_box11") or 0)),
                section_409a_deferrals=Decimal(str(form_data.get("misc_box12") or 0)),
                nonqualified_deferred_comp=Decimal(str(form_data.get("misc_box14") or 0)),
                state_local_taxes=state_taxes,
                is_corrected=bool(form_data.get("is_correction")),
                cfsf_states=[st.state_code for st in state_taxes],
            )
            forms.append(form)
        elif form_type == "1099S":
            # Parse closing date
            closing_date = None
            closing_date_str = form_data.get("s_box1")
            if closing_date_str:
                try:
                    if isinstance(closing_date_str, str):
                        closing_date = date.fromisoformat(closing_date_str[:10])
                    elif isinstance(closing_date_str, date):
                        closing_date = closing_date_str
                except (ValueError, TypeError):
                    pass

            form = Form1099SData(
                record_id=str(i),
                tax_year=tax_year,
                recipient=recipient_info,
                closing_date=closing_date,
                gross_proceeds=Decimal(str(form_data.get("s_box2") or 0)),
                address_or_legal_desc=str(form_data.get("s_box3") or ""),
                transferor_received_consideration=bool(form_data.get("s_box4")),
                transferor_is_foreign_person=bool(form_data.get("s_box5")),
                buyers_real_estate_tax=Decimal(str(form_data.get("s_box6") or 0)),
                is_corrected=bool(form_data.get("is_correction")),
            )
            forms.append(form)
        elif form_type == "1098":
            # Parse dates
            origination_date = None
            orig_date_str = form_data.get("mort_box3")
            if orig_date_str:
                try:
                    if isinstance(orig_date_str, str):
                        origination_date = date.fromisoformat(orig_date_str[:10])
                    elif isinstance(orig_date_str, date):
                        origination_date = orig_date_str
                except (ValueError, TypeError):
                    pass

            acquisition_date = None
            acq_date_str = form_data.get("mort_box11")
            if acq_date_str:
                try:
                    if isinstance(acq_date_str, str):
                        acquisition_date = date.fromisoformat(acq_date_str[:10])
                    elif isinstance(acq_date_str, date):
                        acquisition_date = acq_date_str
                except (ValueError, TypeError):
                    pass

            form = Form1098Data(
                record_id=str(i),
                tax_year=tax_year,
                recipient=recipient_info,
                mortgage_interest_received=Decimal(str(form_data.get("mort_box1") or 0)),
                outstanding_mortgage_principal=Decimal(str(form_data.get("mort_box2") or 0)),
                mortgage_origination_date=origination_date,
                refund_of_overpaid_interest=Decimal(str(form_data.get("mort_box4") or 0)),
                mortgage_insurance_premiums=Decimal(str(form_data.get("mort_box5") or 0)),
                points_paid_on_purchase=Decimal(str(form_data.get("mort_box6") or 0)),
                property_address_same_as_borrower=bool(form_data.get("mort_box7")),
                property_address=str(form_data.get("mort_box8") or ""),
                properties_securing_mortgage_count=int(form_data.get("mort_box9") or 0),
                other_info=str(form_data.get("mort_box10") or ""),
                mortgage_acquisition_date=acquisition_date,
                is_corrected=bool(form_data.get("is_correction")),
            )
            forms.append(form)

    # Determine CFSF election based on form type
    has_cfsf = False
    if form_type in ("1099NEC", "1099MISC") and len(forms) > 0:
        has_cfsf = hasattr(forms[0], 'state_local_taxes') and len(forms[0].state_local_taxes) > 0

    return SubmissionBatch(
        issuer=issuer,
        form_type=form_type,
        tax_year=tax_year,
        forms=forms,
        cfsf_election=has_cfsf,
    )
