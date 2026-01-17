"""
IRIS XML Schema Validator.

Validates IRIS XML transmissions against IRS XSD schemas before submission.
Based on IRS IRIS Schema TY2025 v1.2.

Usage:
    from iris_xml_validator import IRISXMLValidator

    validator = IRISXMLValidator()
    is_valid, errors = validator.validate(xml_content)

    if not is_valid:
        for error in errors:
            print(f"Line {error['line']}: {error['message']}")
"""

import os
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any
from xml.etree import ElementTree as ET
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Try to import lxml for full XSD validation
# Falls back to basic validation if not available
try:
    from lxml import etree as lxml_etree
    HAS_LXML = True
except ImportError:
    HAS_LXML = False
    logger.warning("lxml not installed. Full XSD validation not available. Install with: pip install lxml")


@dataclass
class ValidationError:
    """Represents a validation error."""
    line: Optional[int]
    column: Optional[int]
    message: str
    error_type: str = "error"  # error, warning
    element: Optional[str] = None
    field: Optional[str] = None


class IRISXMLValidator:
    """
    Validates IRIS XML transmissions against IRS schemas.

    Supports two validation modes:
    1. Full XSD validation (requires lxml)
    2. Basic structure validation (ElementTree only)
    """

    # Expected schema location relative to project
    SCHEMA_BASE_PATH = Path("Schemas/1099 Efiling Shema iris-a2a-schema-and-business-rules-ty2025-v1.2")
    SCHEMA_INTAKE_PATH = SCHEMA_BASE_PATH / "IRIS A2A INTAKE XML LIBRARY 2025"
    MAIN_SCHEMA_FILE = "MSG/IRS-IRIntakeTransmissionMessage.xsd"

    # IRS namespace
    IRIS_NS = "urn:us:gov:treasury:irs:ir"

    # Required elements for validation
    REQUIRED_MANIFEST_ELEMENTS = [
        "SchemaVersionNum",
        "UniqueTransmissionId",
        "TaxYr",
        "PriorYearDataInd",
        "TransmissionTypeCd",
        "TestCd",
        "TransmitterGrp",
        "VendorCd",
        "SoftwareId",
        "TotalIssuerFormCnt",
        "TotalRecipientFormCnt",
        "PaperSubmissionInd",
        "MediaSourceCd",
        "SubmissionChannelCd",
    ]

    REQUIRED_TRANSMITTER_ELEMENTS = [
        "TIN",
        "TINSubmittedTypeCd",
        "TransmitterControlCd",
        "ForeignEntityInd",
    ]

    REQUIRED_ISSUER_ELEMENTS = [
        "ForeignEntityInd",
        "TIN",
        "TINSubmittedTypeCd",
        "MailingAddressGrp",
    ]

    def __init__(self, schema_base_path: Optional[Path] = None):
        """
        Initialize validator.

        Args:
            schema_base_path: Path to schema directory. If not provided,
                             looks in project directory.
        """
        if schema_base_path:
            self._schema_base = schema_base_path
        else:
            # Try to find schema relative to this file or project root
            project_root = Path(__file__).parent.parent
            self._schema_base = project_root / self.SCHEMA_INTAKE_PATH

        self._xsd_schema = None
        self._load_attempted = False

    def _load_xsd_schema(self) -> bool:
        """
        Load XSD schema for validation.

        Returns:
            bool: True if schema loaded successfully
        """
        if self._load_attempted:
            return self._xsd_schema is not None

        self._load_attempted = True

        if not HAS_LXML:
            logger.warning("lxml not available - XSD validation disabled")
            return False

        schema_path = self._schema_base / self.MAIN_SCHEMA_FILE
        if not schema_path.exists():
            logger.warning(f"Schema file not found: {schema_path}")
            return False

        try:
            # Parse schema with lxml
            with open(schema_path, "rb") as f:
                schema_doc = lxml_etree.parse(f)

            self._xsd_schema = lxml_etree.XMLSchema(schema_doc)
            logger.info("XSD schema loaded successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to load XSD schema: {e}")
            return False

    def validate(
        self,
        xml_content: bytes,
        validate_xsd: bool = True,
    ) -> Tuple[bool, List[ValidationError]]:
        """
        Validate XML content.

        Args:
            xml_content: XML document as bytes
            validate_xsd: If True and lxml available, validate against XSD

        Returns:
            Tuple of (is_valid, list of errors)
        """
        errors: List[ValidationError] = []

        # First, check if XML is well-formed
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            errors.append(ValidationError(
                line=getattr(e, "lineno", None),
                column=getattr(e, "offset", None),
                message=f"XML parse error: {e}",
                error_type="error",
            ))
            return False, errors

        # Basic structure validation (always performed)
        structure_errors = self._validate_structure(root)
        errors.extend(structure_errors)

        # XSD validation (if available and requested)
        if validate_xsd and HAS_LXML and self._load_xsd_schema():
            xsd_errors = self._validate_xsd(xml_content)
            errors.extend(xsd_errors)

        # Business rule validation
        rule_errors = self._validate_business_rules(root)
        errors.extend(rule_errors)

        is_valid = len([e for e in errors if e.error_type == "error"]) == 0
        return is_valid, errors

    def _validate_structure(self, root: ET.Element) -> List[ValidationError]:
        """Validate basic XML structure."""
        errors = []
        ns = {"irs": self.IRIS_NS}

        # Check root element
        expected_root = f"{{{self.IRIS_NS}}}IRTransmission"
        if root.tag != expected_root:
            errors.append(ValidationError(
                line=None,
                column=None,
                message=f"Invalid root element. Expected 'IRTransmission', got '{root.tag}'",
                element="IRTransmission",
            ))
            return errors

        # Check for manifest
        manifest = root.find("irs:IRTransmissionManifest", ns)
        if manifest is None:
            errors.append(ValidationError(
                line=None,
                column=None,
                message="Missing required element: IRTransmissionManifest",
                element="IRTransmissionManifest",
            ))
            return errors

        # Check required manifest elements
        for elem_name in self.REQUIRED_MANIFEST_ELEMENTS:
            elem = manifest.find(f"irs:{elem_name}", ns)
            if elem is None:
                errors.append(ValidationError(
                    line=None,
                    column=None,
                    message=f"Missing required manifest element: {elem_name}",
                    element=elem_name,
                    field=elem_name,
                ))

        # Check transmitter group
        transmitter = manifest.find("irs:TransmitterGrp", ns)
        if transmitter is not None:
            for elem_name in self.REQUIRED_TRANSMITTER_ELEMENTS:
                elem = transmitter.find(f"irs:{elem_name}", ns)
                if elem is None:
                    errors.append(ValidationError(
                        line=None,
                        column=None,
                        message=f"Missing required transmitter element: {elem_name}",
                        element=f"TransmitterGrp/{elem_name}",
                        field=elem_name,
                    ))

        # Check for at least one submission group
        submission_grps = (
            root.findall("irs:IRSubmission1Grp", ns) +
            root.findall("irs:IRSubmission2Grp", ns) +
            root.findall("irs:IRSubmission3Grp", ns)
        )
        if not submission_grps:
            errors.append(ValidationError(
                line=None,
                column=None,
                message="No submission groups found. At least one IRSubmission1Grp, IRSubmission2Grp, or IRSubmission3Grp is required.",
                element="IRSubmission*Grp",
            ))

        # Validate submission groups
        for sub_grp in root.findall("irs:IRSubmission1Grp", ns):
            sub_errors = self._validate_submission1_group(sub_grp, ns)
            errors.extend(sub_errors)

        return errors

    def _validate_submission1_group(
        self,
        sub_grp: ET.Element,
        ns: Dict[str, str],
    ) -> List[ValidationError]:
        """Validate IRSubmission1Grp structure."""
        errors = []

        # Check header
        header = sub_grp.find("irs:IRSubmission1Header", ns)
        if header is None:
            errors.append(ValidationError(
                line=None,
                column=None,
                message="Missing required element: IRSubmission1Header",
                element="IRSubmission1Header",
            ))
            return errors

        # Required header elements
        required_header = [
            "SubmissionId",
            "TaxYr",
            "IssuerDetail",
            "FormTypeCd",
            "ParentFormTypeCd",
            "CFSFElectionInd",
            "TotalReportedRcpntFormCnt",
        ]

        for elem_name in required_header:
            elem = header.find(f"irs:{elem_name}", ns)
            if elem is None:
                errors.append(ValidationError(
                    line=None,
                    column=None,
                    message=f"Missing required header element: {elem_name}",
                    element=f"IRSubmission1Header/{elem_name}",
                    field=elem_name,
                ))

        # Validate issuer detail
        issuer = header.find("irs:IssuerDetail", ns)
        if issuer is not None:
            for elem_name in self.REQUIRED_ISSUER_ELEMENTS:
                elem = issuer.find(f"irs:{elem_name}", ns)
                if elem is None:
                    errors.append(ValidationError(
                        line=None,
                        column=None,
                        message=f"Missing required issuer element: {elem_name}",
                        element=f"IssuerDetail/{elem_name}",
                        field=elem_name,
                    ))

            # Check for either business name or person name
            has_business = issuer.find("irs:BusinessName", ns) is not None
            has_person = issuer.find("irs:PersonName", ns) is not None
            if not has_business and not has_person:
                errors.append(ValidationError(
                    line=None,
                    column=None,
                    message="Issuer must have either BusinessName or PersonName",
                    element="IssuerDetail",
                ))

        # Validate form type matches detail elements
        form_type_elem = header.find("irs:FormTypeCd", ns)
        if form_type_elem is not None and form_type_elem.text:
            form_type = form_type_elem.text
            detail = sub_grp.find("irs:IRSubmission1Detail", ns)

            if detail is not None:
                detail_element_map = {
                    "1099NEC": "Form1099NECDetail",
                    "1099MISC": "Form1099MISCDetail",
                    "1099DIV": "Form1099DIVDetail",
                    "1099INT": "Form1099INTDetail",
                    "1099B": "Form1099BDetail",
                    "1099R": "Form1099RDetail",
                }
                expected_detail = detail_element_map.get(form_type)
                if expected_detail:
                    details = detail.findall(f"irs:{expected_detail}", ns)
                    if not details:
                        errors.append(ValidationError(
                            line=None,
                            column=None,
                            message=f"FormTypeCd is {form_type} but no {expected_detail} elements found",
                            element="IRSubmission1Detail",
                        ))

        return errors

    def _validate_xsd(self, xml_content: bytes) -> List[ValidationError]:
        """Validate against XSD schema using lxml."""
        errors = []

        if not self._xsd_schema:
            return errors

        try:
            doc = lxml_etree.fromstring(xml_content)
            if not self._xsd_schema.validate(doc):
                for error in self._xsd_schema.error_log:
                    errors.append(ValidationError(
                        line=error.line,
                        column=error.column,
                        message=error.message,
                        error_type="error" if error.level_name == "ERROR" else "warning",
                    ))
        except Exception as e:
            errors.append(ValidationError(
                line=None,
                column=None,
                message=f"XSD validation error: {e}",
                error_type="error",
            ))

        return errors

    def _validate_business_rules(self, root: ET.Element) -> List[ValidationError]:
        """Validate IRS business rules."""
        errors = []
        ns = {"irs": self.IRIS_NS}

        manifest = root.find("irs:IRTransmissionManifest", ns)
        if manifest is None:
            return errors

        # Validate TIN format (9 digits)
        for tin_elem in root.iter(f"{{{self.IRIS_NS}}}TIN"):
            if tin_elem.text:
                tin = tin_elem.text.replace("-", "")
                if not tin.isdigit() or len(tin) != 9:
                    errors.append(ValidationError(
                        line=None,
                        column=None,
                        message=f"Invalid TIN format: must be 9 digits",
                        element="TIN",
                        error_type="error",
                    ))

        # Validate TCC format (5 alphanumeric)
        tcc_elem = manifest.find(".//irs:TransmitterControlCd", ns)
        if tcc_elem is not None and tcc_elem.text:
            tcc = tcc_elem.text
            if not tcc.isalnum() or len(tcc) != 5:
                errors.append(ValidationError(
                    line=None,
                    column=None,
                    message=f"Invalid TCC format: must be 5 alphanumeric characters",
                    element="TransmitterControlCd",
                    error_type="error",
                ))

        # Validate counts match actual content
        issuer_count_elem = manifest.find("irs:TotalIssuerFormCnt", ns)
        recipient_count_elem = manifest.find("irs:TotalRecipientFormCnt", ns)

        if issuer_count_elem is not None and issuer_count_elem.text:
            declared_issuers = int(issuer_count_elem.text)
            actual_issuers = len(root.findall(".//irs:IRSubmission1Grp", ns))
            if declared_issuers != actual_issuers:
                errors.append(ValidationError(
                    line=None,
                    column=None,
                    message=f"TotalIssuerFormCnt ({declared_issuers}) does not match actual submission groups ({actual_issuers})",
                    element="TotalIssuerFormCnt",
                    error_type="error",
                ))

        # Count total recipient forms across all submissions
        if recipient_count_elem is not None and recipient_count_elem.text:
            declared_recipients = int(recipient_count_elem.text)
            actual_recipients = 0
            for sub in root.findall(".//irs:IRSubmission1Detail", ns):
                # Count all form detail elements
                for child in sub:
                    if "Detail" in child.tag:
                        actual_recipients += 1

            if declared_recipients != actual_recipients:
                errors.append(ValidationError(
                    line=None,
                    column=None,
                    message=f"TotalRecipientFormCnt ({declared_recipients}) does not match actual forms ({actual_recipients})",
                    element="TotalRecipientFormCnt",
                    error_type="warning",  # Warning because detail elements might be named differently
                ))

        # Validate state codes
        valid_states = {
            "AL", "AK", "AS", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
            "GA", "GU", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
            "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
            "NM", "NY", "NC", "ND", "MP", "OH", "OK", "OR", "PA", "PR", "RI",
            "SC", "SD", "TN", "TX", "UT", "VT", "VA", "VI", "WA", "WV", "WI",
            "WY", "FM", "MH", "PW",
        }
        for state_elem in root.iter(f"{{{self.IRIS_NS}}}StateAbbreviationCd"):
            if state_elem.text and state_elem.text.upper() not in valid_states:
                errors.append(ValidationError(
                    line=None,
                    column=None,
                    message=f"Invalid state code: {state_elem.text}",
                    element="StateAbbreviationCd",
                    error_type="error",
                ))

        # Validate ZIP codes
        import re
        zip_pattern = re.compile(r"^\d{5}(\d{4})?$")
        for zip_elem in root.iter(f"{{{self.IRIS_NS}}}ZIPCd"):
            if zip_elem.text:
                zip_code = zip_elem.text.replace("-", "")
                if not zip_pattern.match(zip_code):
                    errors.append(ValidationError(
                        line=None,
                        column=None,
                        message=f"Invalid ZIP code format: {zip_elem.text}",
                        element="ZIPCd",
                        error_type="error",
                    ))

        # Validate amounts are non-negative
        amount_elements = [
            "NonemployeeCompensationAmt",
            "FederalIncomeTaxWithheldAmt",
            "StateTaxWithheldAmt",
            "RentAmt",
            "RoyaltyAmt",
            "OtherIncomeAmt",
        ]
        for amt_name in amount_elements:
            for amt_elem in root.iter(f"{{{self.IRIS_NS}}}{amt_name}"):
                if amt_elem.text:
                    try:
                        value = float(amt_elem.text)
                        if value < 0:
                            errors.append(ValidationError(
                                line=None,
                                column=None,
                                message=f"{amt_name} cannot be negative: {amt_elem.text}",
                                element=amt_name,
                                error_type="error",
                            ))
                    except ValueError:
                        errors.append(ValidationError(
                            line=None,
                            column=None,
                            message=f"Invalid amount format for {amt_name}: {amt_elem.text}",
                            element=amt_name,
                            error_type="error",
                        ))

        return errors

    def validate_file(self, file_path: Path) -> Tuple[bool, List[ValidationError]]:
        """
        Validate an XML file.

        Args:
            file_path: Path to XML file

        Returns:
            Tuple of (is_valid, list of errors)
        """
        if not file_path.exists():
            return False, [ValidationError(
                line=None,
                column=None,
                message=f"File not found: {file_path}",
                error_type="error",
            )]

        with open(file_path, "rb") as f:
            xml_content = f.read()

        return self.validate(xml_content)


def validate_iris_xml(xml_content: bytes) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Convenience function to validate IRIS XML.

    Args:
        xml_content: XML document as bytes

    Returns:
        Tuple of (is_valid, list of error dicts)
    """
    validator = IRISXMLValidator()
    is_valid, errors = validator.validate(xml_content)

    error_dicts = [
        {
            "line": e.line,
            "column": e.column,
            "message": e.message,
            "type": e.error_type,
            "element": e.element,
            "field": e.field,
        }
        for e in errors
    ]

    return is_valid, error_dicts
