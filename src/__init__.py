"""
IRIS 1099 E-Filing Module

Provides IRS IRIS API integration for 1099 form submission.

Modules:
    config: Configuration management via environment variables
    iris_auth: JWT-based A2A authentication
    iris_client: High-level IRIS API client

Usage:
    from src.config import load_config
    from src.iris_auth import IRISAuthenticator
    from src.iris_client import IRISClient

    config = load_config()
    client = IRISClient(config)
    client.test_connection()
"""

from config import IRISConfig, load_config, load_config_from_dotenv
from iris_auth import IRISAuthenticator, IRISAuthError, AccessToken
from iris_client import IRISClient, IRISClientError, SubmissionResult, SubmissionStatus

__all__ = [
    # Config
    "IRISConfig",
    "load_config",
    "load_config_from_dotenv",
    # Auth
    "IRISAuthenticator",
    "IRISAuthError",
    "AccessToken",
    # Client
    "IRISClient",
    "IRISClientError",
    "SubmissionResult",
    "SubmissionStatus",
]

__version__ = "0.1.0"
