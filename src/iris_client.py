"""
IRIS API Client for 1099 form submission.

Provides high-level interface for interacting with IRS IRIS API:
- Submit 1099 batches via XML
- Check submission status
- Retrieve acknowledgments and results

This module implements the IRIS A2A (Application-to-Application) integration.
Based on IRS IRIS Schema TY2025 v1.2.

Security notes:
- Never log request/response bodies (may contain PII)
- Use authenticated requests for all API calls
- Handle errors gracefully without exposing sensitive data
- XML transmissions contain TINs - handle securely
"""

import logging
import uuid
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from datetime import datetime
from xml.etree import ElementTree as ET

import requests

from config import IRISConfig
from iris_auth import IRISAuthenticator, IRISAuthError, AccessToken

# Configure logger - be careful about what gets logged
logger = logging.getLogger(__name__)

# IRS IRIS endpoints (based on IRS documentation)
# ATS (Assurance Testing System) endpoints for testing
ATS_BASE_URL = "https://la.www4.irs.gov"
# Production endpoints
PROD_BASE_URL = "https://la.irs.gov"

# IRIS API paths
IRIS_SUBMIT_PATH = "/irservice/efile"
IRIS_STATUS_PATH = "/irservice/status"
IRIS_ACK_PATH = "/irservice/ack"


class IRISClientError(Exception):
    """Raised when IRIS API operations fail."""
    pass


class SubmissionStatus(Enum):
    """Possible statuses for a submission."""
    PENDING = "pending"
    PROCESSING = "processing"
    PARTIALLY_ACCEPTED = "partially_accepted"
    ACCEPTED = "accepted"
    ACCEPTED_WITH_ERRORS = "accepted_with_errors"
    REJECTED = "rejected"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class FormError:
    """Error details for a specific form in submission."""
    record_id: str
    error_code: str
    error_message: str
    field_name: Optional[str] = None
    severity: str = "error"  # error, warning


@dataclass
class SubmissionResult:
    """Result of a batch submission operation."""
    receipt_id: str  # IRS-assigned receipt ID
    unique_transmission_id: str  # Our transmission ID
    status: SubmissionStatus
    message: str = ""
    timestamp: Optional[datetime] = None
    record_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    warning_count: int = 0
    errors: List[FormError] = field(default_factory=list)
    warnings: List[FormError] = field(default_factory=list)
    raw_response: Optional[Dict[str, Any]] = None

    def __repr__(self) -> str:
        return (
            f"<SubmissionResult receipt={self.receipt_id} "
            f"status={self.status.value} "
            f"accepted={self.accepted_count}/{self.record_count}>"
        )

    @property
    def is_success(self) -> bool:
        """Check if submission was successful (fully or partially accepted)."""
        return self.status in (
            SubmissionStatus.ACCEPTED,
            SubmissionStatus.ACCEPTED_WITH_ERRORS,
            SubmissionStatus.PARTIALLY_ACCEPTED,
        )


@dataclass
class AcknowledgmentResult:
    """Acknowledgment data from IRS."""
    receipt_id: str
    transmission_id: str
    status: SubmissionStatus
    timestamp: Optional[datetime] = None
    form_results: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[FormError] = field(default_factory=list)


class IRISClient:
    """
    Client for IRS IRIS 1099 API operations.

    Handles authenticated API requests for:
    - Batch XML submission of 1099 forms
    - Status checking
    - Acknowledgment retrieval

    Usage:
        config = load_config()
        client = IRISClient(config)

        # Test authentication
        client.test_connection()

        # Submit XML batch
        result = client.submit_xml(xml_content)
        print(f"Receipt ID: {result.receipt_id}")

        # Check status
        status = client.get_status(result.receipt_id)

        # Get acknowledgment
        ack = client.get_acknowledgment(result.receipt_id)
    """

    def __init__(self, config: IRISConfig):
        """
        Initialize IRIS client.

        Args:
            config: IRISConfig instance with credentials and endpoints
        """
        self.config = config
        self._auth = IRISAuthenticator(config)
        self._session = requests.Session()

        # Set base URL based on environment
        if config.environment == "ATS":
            self._base_url = ATS_BASE_URL
        else:
            self._base_url = PROD_BASE_URL

    def _get_headers(
        self,
        token: Optional[AccessToken] = None,
        content_type: str = "application/xml",
    ) -> Dict[str, str]:
        """
        Build request headers with authentication.

        Args:
            token: Access token (fetches new one if not provided)
            content_type: Content type for the request

        Returns:
            Dict with Authorization and other required headers
        """
        if token is None:
            token = self._auth.get_access_token()

        return {
            "Authorization": f"{token.token_type} {token.token}",
            "Content-Type": content_type,
            "Accept": "application/xml",
            "User-Agent": f"Sherpa1099/{self.config.environment}",
        }

    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[bytes] = None,
        params: Optional[Dict[str, str]] = None,
        content_type: str = "application/xml",
    ) -> requests.Response:
        """
        Make authenticated request to IRIS API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            data: Request body (bytes for XML)
            params: Query parameters
            content_type: Content type header

        Returns:
            Response object

        Raises:
            IRISClientError: If request fails
        """
        url = f"{self._base_url}{endpoint}"
        headers = self._get_headers(content_type=content_type)

        try:
            logger.info(f"Making {method} request to {endpoint}")
            response = self._session.request(
                method=method,
                url=url,
                headers=headers,
                data=data,
                params=params,
                timeout=120,  # XML submissions can take time
            )

            # Log status but NOT response body
            logger.debug(f"Response status: {response.status_code}")

            return response

        except requests.exceptions.Timeout:
            logger.error("Request timed out")
            raise IRISClientError("IRIS API request timed out")
        except requests.exceptions.ConnectionError:
            logger.error("Connection error")
            raise IRISClientError("Failed to connect to IRIS API")
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {type(e).__name__}")
            raise IRISClientError(f"IRIS API request failed: {type(e).__name__}")

    def test_connection(self) -> bool:
        """
        Test API connectivity and authentication.

        Returns:
            bool: True if connection test passes

        Raises:
            IRISClientError: If connection test fails
        """
        logger.info(f"Testing connection to IRIS API ({self.config.environment})...")

        try:
            # Test authentication
            self._auth.test_authentication()
            logger.info("Authentication successful")

            # Note: IRS may not have a health endpoint
            # Authentication success is our primary test

            logger.info("Connection test passed")
            return True

        except IRISAuthError as e:
            raise IRISClientError(f"Authentication failed: {e}")

    def submit_xml(
        self,
        xml_content: bytes,
        transmission_id: Optional[str] = None,
    ) -> SubmissionResult:
        """
        Submit 1099 forms to IRS via XML.

        Args:
            xml_content: Complete IRIS XML transmission (UTF-8 encoded bytes)
            transmission_id: Optional unique ID for tracking (extracted from XML if not provided)

        Returns:
            SubmissionResult with IRS receipt ID and initial status

        Raises:
            IRISClientError: If submission fails
        """
        # Extract transmission ID from XML if not provided
        if not transmission_id:
            try:
                root = ET.fromstring(xml_content)
                ns = {"irs": "urn:us:gov:treasury:irs:ir"}
                utid_elem = root.find(".//irs:UniqueTransmissionId", ns)
                if utid_elem is not None and utid_elem.text:
                    transmission_id = utid_elem.text
                else:
                    transmission_id = str(uuid.uuid4())
            except ET.ParseError:
                transmission_id = str(uuid.uuid4())

        logger.info(f"Submitting XML transmission: {transmission_id[:36]}...")

        try:
            response = self._request(
                method="POST",
                endpoint=IRIS_SUBMIT_PATH,
                data=xml_content,
                content_type="application/xml",
            )

            # Handle response
            if response.status_code in (200, 201, 202):
                return self._parse_submission_response(response, transmission_id)
            elif response.status_code == 400:
                # Bad request - likely schema validation error
                error_msg = self._extract_error_message(response)
                raise IRISClientError(f"XML validation failed: {error_msg}")
            elif response.status_code == 401:
                raise IRISClientError("Authentication failed - token may be expired")
            elif response.status_code == 403:
                raise IRISClientError("Access denied - check TCC authorization")
            elif response.status_code == 503:
                raise IRISClientError("IRIS service temporarily unavailable")
            else:
                raise IRISClientError(
                    f"Submission failed with HTTP status {response.status_code}"
                )

        except IRISClientError:
            raise
        except Exception as e:
            logger.error(f"Submission error: {type(e).__name__}")
            raise IRISClientError(f"Submission failed: {type(e).__name__}")

    def _parse_submission_response(
        self,
        response: requests.Response,
        transmission_id: str,
    ) -> SubmissionResult:
        """Parse IRS submission response XML."""
        try:
            # IRS returns XML response
            root = ET.fromstring(response.content)
            ns = {"irs": "urn:us:gov:treasury:irs:ir"}

            # Extract receipt ID
            receipt_elem = root.find(".//irs:ReceiptId", ns)
            receipt_id = receipt_elem.text if receipt_elem is not None else "unknown"

            # Extract status
            status_elem = root.find(".//irs:StatusCd", ns)
            status_text = status_elem.text.lower() if status_elem is not None else "pending"

            status_map = {
                "accepted": SubmissionStatus.ACCEPTED,
                "rejected": SubmissionStatus.REJECTED,
                "pending": SubmissionStatus.PENDING,
                "processing": SubmissionStatus.PROCESSING,
                "partially_accepted": SubmissionStatus.PARTIALLY_ACCEPTED,
                "accepted_with_errors": SubmissionStatus.ACCEPTED_WITH_ERRORS,
            }
            status = status_map.get(status_text, SubmissionStatus.UNKNOWN)

            # Extract counts
            record_count = self._get_xml_int(root, ".//irs:TotalRecordCnt", ns, 0)
            accepted_count = self._get_xml_int(root, ".//irs:AcceptedCnt", ns, 0)
            rejected_count = self._get_xml_int(root, ".//irs:RejectedCnt", ns, 0)

            # Extract errors
            errors = self._extract_form_errors(root, ns)

            return SubmissionResult(
                receipt_id=receipt_id,
                unique_transmission_id=transmission_id,
                status=status,
                message=f"Submission received by IRS",
                timestamp=datetime.utcnow(),
                record_count=record_count,
                accepted_count=accepted_count,
                rejected_count=rejected_count,
                errors=errors,
            )

        except ET.ParseError as e:
            logger.warning(f"Failed to parse XML response: {e}")
            # Return basic result even if parsing fails
            return SubmissionResult(
                receipt_id="parse_error",
                unique_transmission_id=transmission_id,
                status=SubmissionStatus.UNKNOWN,
                message="Response received but could not be parsed",
                timestamp=datetime.utcnow(),
            )

    def _get_xml_int(
        self,
        root: ET.Element,
        xpath: str,
        ns: Dict[str, str],
        default: int = 0,
    ) -> int:
        """Safely extract integer from XML element."""
        elem = root.find(xpath, ns)
        if elem is not None and elem.text:
            try:
                return int(elem.text)
            except ValueError:
                pass
        return default

    def _extract_form_errors(
        self,
        root: ET.Element,
        ns: Dict[str, str],
    ) -> List[FormError]:
        """Extract form-level errors from response."""
        errors = []
        for error_elem in root.findall(".//irs:Error", ns):
            record_id = ""
            record_elem = error_elem.find("irs:RecordId", ns)
            if record_elem is not None:
                record_id = record_elem.text or ""

            code_elem = error_elem.find("irs:ErrorCd", ns)
            code = code_elem.text if code_elem is not None else "UNKNOWN"

            msg_elem = error_elem.find("irs:ErrorMessageTxt", ns)
            message = msg_elem.text if msg_elem is not None else "Unknown error"

            field_elem = error_elem.find("irs:FieldNm", ns)
            field_name = field_elem.text if field_elem is not None else None

            errors.append(FormError(
                record_id=record_id,
                error_code=code,
                error_message=message,
                field_name=field_name,
            ))

        return errors

    def _extract_error_message(self, response: requests.Response) -> str:
        """Extract error message from error response."""
        try:
            root = ET.fromstring(response.content)
            ns = {"irs": "urn:us:gov:treasury:irs:ir"}
            msg_elem = root.find(".//irs:ErrorMessageTxt", ns)
            if msg_elem is not None and msg_elem.text:
                return msg_elem.text
        except:
            pass
        return f"HTTP {response.status_code}"

    def get_status(
        self,
        receipt_id: Optional[str] = None,
        transmission_id: Optional[str] = None,
    ) -> SubmissionResult:
        """
        Check the status of a previous submission.

        Args:
            receipt_id: IRS-assigned receipt ID
            transmission_id: Our unique transmission ID

        Returns:
            SubmissionResult with current status

        Raises:
            IRISClientError: If status check fails
        """
        if not receipt_id and not transmission_id:
            raise IRISClientError("Either receipt_id or transmission_id is required")

        logger.info(f"Checking status for: {receipt_id or transmission_id}")

        # Build status request XML
        request_xml = self._build_status_request(receipt_id, transmission_id)

        try:
            response = self._request(
                method="POST",
                endpoint=IRIS_STATUS_PATH,
                data=request_xml,
                content_type="application/xml",
            )

            if response.status_code == 200:
                return self._parse_status_response(response, receipt_id or "", transmission_id or "")
            elif response.status_code == 404:
                raise IRISClientError(f"Submission not found")
            else:
                raise IRISClientError(
                    f"Status check failed with HTTP status {response.status_code}"
                )

        except IRISClientError:
            raise
        except Exception as e:
            logger.error(f"Status check error: {type(e).__name__}")
            raise IRISClientError(f"Status check failed: {type(e).__name__}")

    def _build_status_request(
        self,
        receipt_id: Optional[str],
        transmission_id: Optional[str],
    ) -> bytes:
        """Build status request XML per IRS schema."""
        ns = "urn:us:gov:treasury:irs:ir"
        ET.register_namespace("", ns)

        root = ET.Element(f"{{{ns}}}StatusOrAckRequest")

        if receipt_id:
            self._add_elem(root, "ReceiptId", receipt_id, ns)
            self._add_elem(root, "RequestTypeCd", "STATUS", ns)
        else:
            self._add_elem(root, "UniqueTransmissionId", transmission_id, ns)
            self._add_elem(root, "RequestTypeCd", "STATUS", ns)

        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _add_elem(self, parent: ET.Element, tag: str, text: str, ns: str) -> ET.Element:
        """Add element with namespace."""
        elem = ET.SubElement(parent, f"{{{ns}}}{tag}")
        elem.text = text
        return elem

    def _parse_status_response(
        self,
        response: requests.Response,
        receipt_id: str,
        transmission_id: str,
    ) -> SubmissionResult:
        """Parse status response XML."""
        try:
            root = ET.fromstring(response.content)
            ns = {"irs": "urn:us:gov:treasury:irs:ir"}

            status_elem = root.find(".//irs:StatusCd", ns)
            status_text = status_elem.text.lower() if status_elem is not None else "unknown"

            status_map = {
                "accepted": SubmissionStatus.ACCEPTED,
                "rejected": SubmissionStatus.REJECTED,
                "pending": SubmissionStatus.PENDING,
                "processing": SubmissionStatus.PROCESSING,
                "partially_accepted": SubmissionStatus.PARTIALLY_ACCEPTED,
                "accepted_with_errors": SubmissionStatus.ACCEPTED_WITH_ERRORS,
            }
            status = status_map.get(status_text, SubmissionStatus.UNKNOWN)

            # Extract receipt ID if not provided
            if not receipt_id:
                rid_elem = root.find(".//irs:ReceiptId", ns)
                receipt_id = rid_elem.text if rid_elem is not None else ""

            record_count = self._get_xml_int(root, ".//irs:TotalRecordCnt", ns, 0)
            accepted_count = self._get_xml_int(root, ".//irs:AcceptedCnt", ns, 0)
            rejected_count = self._get_xml_int(root, ".//irs:RejectedCnt", ns, 0)
            errors = self._extract_form_errors(root, ns)

            return SubmissionResult(
                receipt_id=receipt_id,
                unique_transmission_id=transmission_id,
                status=status,
                timestamp=datetime.utcnow(),
                record_count=record_count,
                accepted_count=accepted_count,
                rejected_count=rejected_count,
                errors=errors,
            )

        except ET.ParseError as e:
            logger.warning(f"Failed to parse status response: {e}")
            raise IRISClientError("Failed to parse status response")

    def get_acknowledgment(
        self,
        receipt_id: Optional[str] = None,
        transmission_id: Optional[str] = None,
    ) -> AcknowledgmentResult:
        """
        Retrieve detailed acknowledgment for a submission.

        The acknowledgment contains form-by-form acceptance/rejection details.

        Args:
            receipt_id: IRS-assigned receipt ID
            transmission_id: Our unique transmission ID

        Returns:
            AcknowledgmentResult with detailed results

        Raises:
            IRISClientError: If acknowledgment retrieval fails
        """
        if not receipt_id and not transmission_id:
            raise IRISClientError("Either receipt_id or transmission_id is required")

        logger.info(f"Retrieving acknowledgment for: {receipt_id or transmission_id}")

        # Build acknowledgment request XML
        request_xml = self._build_ack_request(receipt_id, transmission_id)

        try:
            response = self._request(
                method="POST",
                endpoint=IRIS_ACK_PATH,
                data=request_xml,
                content_type="application/xml",
            )

            if response.status_code == 200:
                return self._parse_ack_response(response, receipt_id or "", transmission_id or "")
            elif response.status_code == 202:
                raise IRISClientError("Acknowledgment not yet available - still processing")
            elif response.status_code == 404:
                raise IRISClientError(f"Submission not found")
            else:
                raise IRISClientError(
                    f"Acknowledgment retrieval failed with HTTP status {response.status_code}"
                )

        except IRISClientError:
            raise
        except Exception as e:
            logger.error(f"Acknowledgment error: {type(e).__name__}")
            raise IRISClientError(f"Acknowledgment retrieval failed: {type(e).__name__}")

    def _build_ack_request(
        self,
        receipt_id: Optional[str],
        transmission_id: Optional[str],
    ) -> bytes:
        """Build acknowledgment request XML."""
        ns = "urn:us:gov:treasury:irs:ir"
        ET.register_namespace("", ns)

        root = ET.Element(f"{{{ns}}}StatusOrAckRequest")

        if receipt_id:
            self._add_elem(root, "ReceiptId", receipt_id, ns)
            self._add_elem(root, "RequestTypeCd", "ACK", ns)
        else:
            self._add_elem(root, "UniqueTransmissionId", transmission_id, ns)
            self._add_elem(root, "RequestTypeCd", "ACK", ns)

        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _parse_ack_response(
        self,
        response: requests.Response,
        receipt_id: str,
        transmission_id: str,
    ) -> AcknowledgmentResult:
        """Parse acknowledgment response XML."""
        try:
            root = ET.fromstring(response.content)
            ns = {"irs": "urn:us:gov:treasury:irs:ir"}

            # Extract receipt ID
            if not receipt_id:
                rid_elem = root.find(".//irs:ReceiptId", ns)
                receipt_id = rid_elem.text if rid_elem is not None else ""

            # Extract transmission ID
            if not transmission_id:
                tid_elem = root.find(".//irs:UniqueTransmissionId", ns)
                transmission_id = tid_elem.text if tid_elem is not None else ""

            # Extract status
            status_elem = root.find(".//irs:StatusCd", ns)
            status_text = status_elem.text.lower() if status_elem is not None else "unknown"

            status_map = {
                "accepted": SubmissionStatus.ACCEPTED,
                "rejected": SubmissionStatus.REJECTED,
                "pending": SubmissionStatus.PENDING,
                "processing": SubmissionStatus.PROCESSING,
                "partially_accepted": SubmissionStatus.PARTIALLY_ACCEPTED,
                "accepted_with_errors": SubmissionStatus.ACCEPTED_WITH_ERRORS,
            }
            status = status_map.get(status_text, SubmissionStatus.UNKNOWN)

            # Extract form-level results
            form_results = []
            for form_elem in root.findall(".//irs:FormAck", ns):
                form_result = {
                    "record_id": "",
                    "status": "",
                    "errors": [],
                }

                rid_elem = form_elem.find("irs:RecordId", ns)
                if rid_elem is not None:
                    form_result["record_id"] = rid_elem.text or ""

                fstatus_elem = form_elem.find("irs:StatusCd", ns)
                if fstatus_elem is not None:
                    form_result["status"] = fstatus_elem.text or ""

                for error_elem in form_elem.findall("irs:Error", ns):
                    error = {
                        "code": "",
                        "message": "",
                        "field": None,
                    }
                    code_elem = error_elem.find("irs:ErrorCd", ns)
                    if code_elem is not None:
                        error["code"] = code_elem.text or ""

                    msg_elem = error_elem.find("irs:ErrorMessageTxt", ns)
                    if msg_elem is not None:
                        error["message"] = msg_elem.text or ""

                    field_elem = error_elem.find("irs:FieldNm", ns)
                    if field_elem is not None:
                        error["field"] = field_elem.text

                    form_result["errors"].append(error)

                form_results.append(form_result)

            # Extract transmission-level errors
            errors = self._extract_form_errors(root, ns)

            return AcknowledgmentResult(
                receipt_id=receipt_id,
                transmission_id=transmission_id,
                status=status,
                timestamp=datetime.utcnow(),
                form_results=form_results,
                errors=errors,
            )

        except ET.ParseError as e:
            logger.warning(f"Failed to parse acknowledgment response: {e}")
            raise IRISClientError("Failed to parse acknowledgment response")

    # Legacy method for backwards compatibility
    def submit_batch(
        self,
        csv_path: Path,
        form_type: str = "1099-NEC",
        tax_year: int = 2025,
        is_test: bool = True,
    ) -> SubmissionResult:
        """
        DEPRECATED: Use submit_xml() instead.

        This method is kept for backwards compatibility but will raise an error.
        """
        raise NotImplementedError(
            "CSV submission is no longer supported. "
            "Use submit_xml() with IRIS-compliant XML generated by IRISXMLGenerator."
        )

    def get_submission_status(self, submission_id: str) -> SubmissionResult:
        """
        DEPRECATED: Use get_status() instead.

        Wrapper for backwards compatibility.
        """
        # Determine if it's a receipt ID or transmission ID by format
        if "-" in submission_id and len(submission_id.split("-")) == 5:
            # Looks like a UUID - treat as transmission ID
            return self.get_status(transmission_id=submission_id)
        else:
            # Treat as receipt ID
            return self.get_status(receipt_id=submission_id)

    def get_submission_results(self, submission_id: str) -> Dict[str, Any]:
        """
        DEPRECATED: Use get_acknowledgment() instead.

        Wrapper for backwards compatibility.
        """
        if "-" in submission_id and len(submission_id.split("-")) == 5:
            ack = self.get_acknowledgment(transmission_id=submission_id)
        else:
            ack = self.get_acknowledgment(receipt_id=submission_id)

        return {
            "receipt_id": ack.receipt_id,
            "transmission_id": ack.transmission_id,
            "status": ack.status.value,
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
