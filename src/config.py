"""
Configuration module for IRIS 1099 e-filing.

Loads settings from environment variables with sensible defaults for ATS (test) environment.
Never logs or exposes sensitive values like tokens or private keys.
"""

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class IRISConfig:
    """Immutable configuration for IRIS API integration."""

    # IRS Client ID (provided via env var or .env file)
    client_id: str

    # IRIS API base URLs
    # ATS (Assurance Testing System) endpoints - TEST environment
    # Production endpoints would be different
    auth_endpoint: str
    api_base_url: str

    # Private key - either path to file OR the PEM content directly
    private_key_path: Optional[Path] = None
    private_key_pem: Optional[str] = None

    # JWT settings
    jwt_algorithm: str = "RS256"
    jwt_expiry_seconds: int = 300  # 5 minutes per IRS spec

    # Key ID - must match what's registered in JWKS with IRS
    key_id: str = "iris-a2a-2025"

    # Environment identifier
    environment: str = "ATS"

    def __post_init__(self):
        """Validate configuration on creation."""
        if not self.client_id:
            raise ValueError("IRIS_CLIENT_ID environment variable is required")
        # Must have either private_key_path or private_key_pem
        if not self.private_key_pem and not self.private_key_path:
            raise ValueError(
                "Either IRIS_PRIVATE_KEY (PEM content) or IRIS_PRIVATE_KEY_PATH must be set"
            )
        if self.private_key_path and not self.private_key_path.exists():
            raise FileNotFoundError(
                f"Private key not found at {self.private_key_path}. "
                "Ensure IRIS_PRIVATE_KEY_PATH points to a valid PEM file."
            )

    def get_private_key(self) -> str:
        """Get the private key PEM content."""
        if self.private_key_pem:
            return self.private_key_pem
        if self.private_key_path:
            return self.private_key_path.read_text()
        raise ValueError("No private key configured")


def load_config() -> IRISConfig:
    """
    Load IRIS configuration from environment variables.

    Required environment variables:
        IRIS_CLIENT_ID: IRS-issued client ID (UUID format)

    Private key (one of these required):
        IRIS_PRIVATE_KEY: RSA private key PEM content (recommended for cloud deployment)
        IRIS_PRIVATE_KEY_PATH: Path to RSA private key file (for local development)

    Optional environment variables:
        IRIS_KEY_ID: Key ID matching JWKS registration (default: iris-a2a-2025)
        IRIS_ENVIRONMENT: "ATS" for test, "PROD" for production (default: ATS)
        IRIS_AUTH_ENDPOINT: OAuth token endpoint (default: ATS endpoint)
        IRIS_API_BASE_URL: IRIS API base URL (default: ATS URL)

    Returns:
        IRISConfig: Validated configuration object

    Raises:
        ValueError: If required environment variables are missing
        FileNotFoundError: If private key file doesn't exist
    """
    # Determine base directory (project root)
    base_dir = Path(__file__).parent.parent

    # Load client ID (required)
    client_id = os.environ.get("IRIS_CLIENT_ID", "")

    # Load private key - prefer PEM content from env var, fall back to file path
    private_key_pem = os.environ.get("IRIS_PRIVATE_KEY", "")
    private_key_path = None

    if not private_key_pem:
        # No PEM content in env var, check for file path
        private_key_path_str = os.environ.get(
            "IRIS_PRIVATE_KEY_PATH",
            str(base_dir / "IRIS_KEYS" / "iris_private.key")
        )
        private_key_path = Path(private_key_path_str)

    # Load key ID
    key_id = os.environ.get("IRIS_KEY_ID", "iris-a2a-2025")

    # Determine environment
    environment = os.environ.get("IRIS_ENVIRONMENT", "ATS").upper()

    # Set endpoints based on environment
    # TODO: These are placeholder URLs. Replace with actual IRS IRIS endpoints
    # when documentation is available. The IRS provides different base URLs
    # for ATS (test) vs Production environments.
    if environment == "ATS":
        # ATS (Assurance Testing System) - Test environment
        # TODO: Replace with actual IRS ATS OAuth endpoint
        default_auth_endpoint = os.environ.get(
            "IRIS_AUTH_ENDPOINT",
            "https://ats-api.irs.gov/oauth/token"  # TODO: Verify actual endpoint
        )
        # TODO: Replace with actual IRS ATS API base URL
        default_api_base = os.environ.get(
            "IRIS_API_BASE_URL",
            "https://ats-api.irs.gov/iris/v1"  # TODO: Verify actual endpoint
        )
    elif environment == "PROD":
        # Production - NOT YET IMPLEMENTED
        raise ValueError(
            "Production environment not yet configured. "
            "Use IRIS_ENVIRONMENT=ATS for testing."
        )
    else:
        raise ValueError(
            f"Invalid IRIS_ENVIRONMENT: {environment}. Must be 'ATS' or 'PROD'."
        )

    return IRISConfig(
        client_id=client_id,
        auth_endpoint=default_auth_endpoint,
        api_base_url=default_api_base,
        private_key_path=private_key_path,
        private_key_pem=private_key_pem if private_key_pem else None,
        key_id=key_id,
        environment=environment,
    )


def load_config_from_dotenv(dotenv_path: Optional[Path] = None) -> IRISConfig:
    """
    Load configuration after reading from .env file.

    Args:
        dotenv_path: Path to .env file. Defaults to project root/.env

    Returns:
        IRISConfig: Validated configuration object
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        raise ImportError(
            "python-dotenv is required for .env file support. "
            "Install with: pip install python-dotenv"
        )

    if dotenv_path is None:
        dotenv_path = Path(__file__).parent.parent / ".env"

    load_dotenv(dotenv_path)
    return load_config()
