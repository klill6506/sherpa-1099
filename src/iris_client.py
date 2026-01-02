"""
IRIS API Client for 1099 form submission.

Provides high-level interface for interacting with IRS IRIS API:
- Submit 1099 batches
- Check submission status
- Retrieve submission results

This module focuses on ATS (Assurance Testing System) integration.
TIN Matching is NOT implemented here.

Security notes:
- Never log request/response bodies (may contain PII)
- Use authenticated requests for all API calls
- Handle errors gracefully without exposing sensitive data
"""

import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import requests

from .config import IRISConfig
from .iris_auth import IRISAuthenticator, IRISAuthError, AccessToken

# Configure logger - be careful about what gets logged
logger = logging.getLogger(__name__)


class IRISClientError(Exception):
    """Raised when IRIS API operations fail."""
    pass


class SubmissionStatus(Enum):
    """Possible statuses for a submission."""
    PENDING = "pending"
    PROCESSING = "processing"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class SubmissionResult:
    """Result of a batch submission operation."""
    submission_id: str
    status: SubmissionStatus
    message: str = ""
    record_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"<SubmissionResult id={self.submission_id} "
            f"status={self.status.value} "
            f"accepted={self.accepted_count}/{self.record_count}>"
        )


class IRISClient:
    """
    Client for IRS IRIS 1099 API operations.

    Handles authenticated API requests for:
    - Batch submission of 1099 forms
    - Status checking
    - Result retrieval

    Usage:
        config = load_config()
        client = IRISClient(config)

        # Test authentication
        client.test_connection()

        # Submit batch
        result = client.submit_batch(csv_path)
        print(f"Submission ID: {result.submission_id}")

        # Check status
        status = client.get_submission_status(result.submission_id)
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

    def _get_headers(self, token: Optional[AccessToken] = None) -> Dict[str, str]:
        """
        Build request headers with authentication.

        Args:
            token: Access token (fetches new one if not provided)

        Returns:
            Dict with Authorization and other required headers
        """
        if token is None:
            token = self._auth.get_access_token()

        return {
            "Authorization": f"{token.token_type} {token.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            # TODO: Add any additional headers required by IRS
            # "X-Transmitter-TCC": self.config.tcc_code,  # If required
        }

    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        files: Optional[Dict] = None,
    ) -> requests.Response:
        """
        Make authenticated request to IRIS API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path (appended to base URL)
            data: Form data (for multipart requests)
            json_data: JSON body data
            files: File uploads

        Returns:
            Response object

        Raises:
            IRISClientError: If request fails
        """
        url = f"{self.config.api_base_url}/{endpoint.lstrip('/')}"
        headers = self._get_headers()

        # Adjust content-type for file uploads
        if files:
            del headers["Content-Type"]  # Let requests set multipart boundary

        try:
            logger.info(f"Making {method} request to {endpoint}")
            response = self._session.request(
                method=method,
                url=url,
                headers=headers,
                data=data,
                json=json_data,
                files=files,
                timeout=60,
            )

            # Log status but NOT response body
            logger.debug(f"Response status: {response.status_code}")

            return response

        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {type(e).__name__}")
            raise IRISClientError(f"API request failed: {type(e).__name__}")

    def test_connection(self) -> bool:
        """
        Test API connectivity and authentication.

        Attempts to authenticate and optionally ping a health endpoint.

        Returns:
            bool: True if connection test passes

        Raises:
            IRISClientError: If connection test fails
        """
        logger.info(f"Testing connection to IRIS API ({self.config.environment})...")

        try:
            # First test authentication
            self._auth.test_authentication()
            logger.info("Authentication successful")

            # TODO: If IRS provides a health/ping endpoint, test it here
            # response = self._request("GET", "/health")
            # if response.status_code != 200:
            #     raise IRISClientError("Health check failed")

            logger.info("Connection test passed")
            return True

        except IRISAuthError as e:
            raise IRISClientError(f"Authentication failed: {e}")

    def submit_batch(
        self,
        csv_path: Path,
        form_type: str = "1099-NEC",
        tax_year: int = 2025,
        is_test: bool = True,
    ) -> SubmissionResult:
        """
        Submit a batch of 1099 forms to IRIS.

        IMPORTANT: This is a SKELETON implementation. The actual API
        endpoint, request format, and response handling must be
        verified against IRS documentation.

        Args:
            csv_path: Path to validated CSV file
            form_type: Type of 1099 form (1099-NEC, 1099-MISC, etc.)
            tax_year: Tax year for the forms
            is_test: If True, submit to ATS (test) environment

        Returns:
            SubmissionResult with submission ID and initial status

        Raises:
            IRISClientError: If submission fails
            FileNotFoundError: If CSV file doesn't exist
        """
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        logger.info(f"Submitting batch: {csv_path.name} ({form_type}, TY{tax_year})")

        # TODO: Verify actual submission endpoint and format with IRS docs
        # The IRS may require:
        # - XML format instead of CSV
        # - Specific file naming conventions
        # - Metadata in request body vs headers
        # - Different endpoints per form type

        # Placeholder endpoint - MUST be replaced with actual IRS endpoint
        endpoint = "/submissions"  # TODO: Verify actual endpoint

        # Read CSV content
        with open(csv_path, "rb") as f:
            csv_content = f.read()

        # Build submission payload
        # TODO: Adjust based on actual IRS API requirements
        submission_metadata = {
            "form_type": form_type,
            "tax_year": tax_year,
            "is_test_submission": is_test,
            "environment": self.config.environment,
            # TODO: Add required fields:
            # "transmitter_control_code": "...",
            # "payer_tin": "...",
            # "submission_type": "original" or "correction",
        }

        files = {
            "file": (csv_path.name, csv_content, "text/csv"),
        }

        try:
            response = self._request(
                method="POST",
                endpoint=endpoint,
                data=submission_metadata,
                files=files,
            )

            if response.status_code in (200, 201, 202):
                # Parse response
                # TODO: Adjust based on actual IRS response format
                data = response.json()

                return SubmissionResult(
                    submission_id=data.get("submission_id", data.get("id", "unknown")),
                    status=SubmissionStatus.PENDING,
                    message=data.get("message", "Submission accepted"),
                    record_count=data.get("record_count", 0),
                )
            else:
                # Don't log response body - could contain sensitive data
                logger.error(f"Submission failed: HTTP {response.status_code}")
                raise IRISClientError(
                    f"Submission failed with status {response.status_code}"
                )

        except IRISClientError:
            raise
        except Exception as e:
            logger.error(f"Submission error: {type(e).__name__}")
            raise IRISClientError(f"Submission failed: {type(e).__name__}")

    def get_submission_status(self, submission_id: str) -> SubmissionResult:
        """
        Check the status of a previous submission.

        Args:
            submission_id: ID returned from submit_batch()

        Returns:
            SubmissionResult with current status

        Raises:
            IRISClientError: If status check fails
        """
        logger.info(f"Checking status for submission: {submission_id}")

        # TODO: Verify actual status endpoint with IRS docs
        endpoint = f"/submissions/{submission_id}/status"

        try:
            response = self._request("GET", endpoint)

            if response.status_code == 200:
                data = response.json()

                # Map IRS status to our enum
                # TODO: Adjust based on actual IRS status values
                status_map = {
                    "pending": SubmissionStatus.PENDING,
                    "processing": SubmissionStatus.PROCESSING,
                    "accepted": SubmissionStatus.ACCEPTED,
                    "rejected": SubmissionStatus.REJECTED,
                    "error": SubmissionStatus.ERROR,
                }
                status_str = data.get("status", "unknown").lower()
                status = status_map.get(status_str, SubmissionStatus.UNKNOWN)

                return SubmissionResult(
                    submission_id=submission_id,
                    status=status,
                    message=data.get("message", ""),
                    record_count=data.get("record_count", 0),
                    accepted_count=data.get("accepted_count", 0),
                    rejected_count=data.get("rejected_count", 0),
                    errors=data.get("errors", []),
                )
            elif response.status_code == 404:
                raise IRISClientError(f"Submission not found: {submission_id}")
            else:
                raise IRISClientError(
                    f"Status check failed with status {response.status_code}"
                )

        except IRISClientError:
            raise
        except Exception as e:
            logger.error(f"Status check error: {type(e).__name__}")
            raise IRISClientError(f"Status check failed: {type(e).__name__}")

    def get_submission_results(self, submission_id: str) -> Dict[str, Any]:
        """
        Retrieve detailed results for a completed submission.

        Only available after submission processing is complete.

        Args:
            submission_id: ID returned from submit_batch()

        Returns:
            Dict containing detailed results (format TBD by IRS)

        Raises:
            IRISClientError: If retrieval fails
        """
        logger.info(f"Retrieving results for submission: {submission_id}")

        # TODO: Verify actual results endpoint with IRS docs
        endpoint = f"/submissions/{submission_id}/results"

        try:
            response = self._request("GET", endpoint)

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                raise IRISClientError(f"Results not found: {submission_id}")
            elif response.status_code == 202:
                # Processing not yet complete
                raise IRISClientError("Submission still processing, results not ready")
            else:
                raise IRISClientError(
                    f"Results retrieval failed with status {response.status_code}"
                )

        except IRISClientError:
            raise
        except Exception as e:
            logger.error(f"Results retrieval error: {type(e).__name__}")
            raise IRISClientError(f"Results retrieval failed: {type(e).__name__}")
