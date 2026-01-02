"""
IRIS Authentication module for IRS A2A (Application-to-Application) OAuth.

Implements JWT-based client assertion flow for IRIS API authentication.
Uses RS256 signing with a pre-registered RSA key pair.

Security notes:
- Never log tokens or private key material
- Tokens are short-lived (5 minutes) per IRS requirements
- Private key must be loaded from disk, never committed to version control
"""

import time
import uuid
import logging
from typing import Optional
from dataclasses import dataclass

import jwt
import requests

from .config import IRISConfig

# Configure logger - NEVER log tokens or keys
logger = logging.getLogger(__name__)


class IRISAuthError(Exception):
    """Raised when IRIS authentication fails."""
    pass


@dataclass
class AccessToken:
    """Represents an IRIS API access token."""
    token: str
    expires_at: float  # Unix timestamp
    token_type: str = "Bearer"

    @property
    def is_expired(self) -> bool:
        """Check if token is expired (with 30-second buffer)."""
        return time.time() >= (self.expires_at - 30)

    def __repr__(self) -> str:
        """Safe repr that doesn't expose token value."""
        status = "expired" if self.is_expired else "valid"
        return f"<AccessToken type={self.token_type} status={status}>"


class IRISAuthenticator:
    """
    Handles IRIS A2A authentication using JWT client assertions.

    The IRS IRIS API uses OAuth 2.0 with JWT client assertions:
    1. Client creates a signed JWT assertion
    2. JWT is sent to token endpoint
    3. IRS validates JWT signature against registered JWKS
    4. IRS returns short-lived access token

    Usage:
        config = load_config()
        auth = IRISAuthenticator(config)
        token = auth.get_access_token()
        # Use token.token in Authorization header
    """

    def __init__(self, config: IRISConfig):
        """
        Initialize authenticator with configuration.

        Args:
            config: IRISConfig instance with credentials and endpoints
        """
        self.config = config
        self._private_key: Optional[str] = None
        self._cached_token: Optional[AccessToken] = None

    def _load_private_key(self) -> str:
        """
        Load RSA private key from disk.

        Returns:
            str: PEM-encoded private key

        Raises:
            IRISAuthError: If key cannot be loaded
        """
        if self._private_key is not None:
            return self._private_key

        try:
            with open(self.config.private_key_path, "r") as f:
                self._private_key = f.read()
            logger.debug("Private key loaded successfully")
            return self._private_key
        except Exception as e:
            # Don't log the actual error details - could leak path info
            raise IRISAuthError(f"Failed to load private key: {type(e).__name__}")

    def _create_client_assertion(self) -> str:
        """
        Create a signed JWT client assertion for OAuth token request.

        The JWT contains claims required by IRS IRIS A2A authentication:
        - iss (issuer): Client ID
        - sub (subject): Client ID
        - aud (audience): Token endpoint URL
        - exp (expiration): Current time + expiry
        - iat (issued at): Current time
        - jti (JWT ID): Unique identifier for this token

        Returns:
            str: Signed JWT assertion

        Raises:
            IRISAuthError: If JWT creation fails
        """
        now = int(time.time())
        expiry = now + self.config.jwt_expiry_seconds

        # JWT claims per IRS IRIS A2A specification
        # TODO: Verify exact claim requirements with IRS documentation
        claims = {
            "iss": self.config.client_id,  # Issuer = Client ID
            "sub": self.config.client_id,  # Subject = Client ID
            "aud": self.config.auth_endpoint,  # Audience = Token endpoint
            "exp": expiry,  # Expiration time
            "iat": now,  # Issued at
            "jti": str(uuid.uuid4()),  # Unique JWT ID
            # TODO: Add any additional claims required by IRS
            # Some implementations may require:
            # "scope": "iris.submit",  # Requested scope
        }

        # JWT headers
        headers = {
            "alg": self.config.jwt_algorithm,
            "typ": "JWT",
            "kid": self.config.key_id,  # Key ID matching JWKS registration
        }

        try:
            private_key = self._load_private_key()
            assertion = jwt.encode(
                claims,
                private_key,
                algorithm=self.config.jwt_algorithm,
                headers=headers,
            )
            logger.debug("Client assertion created successfully")
            return assertion
        except Exception as e:
            # Don't log JWT or key details
            raise IRISAuthError(f"Failed to create client assertion: {type(e).__name__}")

    def _request_token(self, assertion: str) -> AccessToken:
        """
        Exchange client assertion for access token.

        Makes POST request to IRS OAuth token endpoint with:
        - grant_type: client_credentials
        - client_assertion_type: urn:ietf:params:oauth:client-assertion-type:jwt-bearer
        - client_assertion: Signed JWT

        Args:
            assertion: Signed JWT client assertion

        Returns:
            AccessToken: Valid access token

        Raises:
            IRISAuthError: If token request fails
        """
        # OAuth 2.0 client credentials grant with JWT bearer assertion
        # TODO: Verify exact parameter names with IRS documentation
        payload = {
            "grant_type": "client_credentials",
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": assertion,
            # TODO: Add scope if required by IRS
            # "scope": "iris.submit",
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        try:
            logger.info(f"Requesting token from {self.config.auth_endpoint}")
            response = requests.post(
                self.config.auth_endpoint,
                data=payload,
                headers=headers,
                timeout=30,
            )

            if response.status_code != 200:
                # Log status but NOT response body (could contain sensitive info)
                logger.error(f"Token request failed: HTTP {response.status_code}")
                raise IRISAuthError(
                    f"Token request failed with status {response.status_code}"
                )

            data = response.json()

            # Parse token response
            # TODO: Verify exact response field names with IRS documentation
            access_token = data.get("access_token")
            if not access_token:
                raise IRISAuthError("No access_token in response")

            # Calculate expiration
            expires_in = data.get("expires_in", 300)  # Default 5 minutes
            expires_at = time.time() + expires_in

            token = AccessToken(
                token=access_token,
                expires_at=expires_at,
                token_type=data.get("token_type", "Bearer"),
            )

            logger.info(f"Token obtained successfully, expires in {expires_in}s")
            return token

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during token request: {type(e).__name__}")
            raise IRISAuthError(f"Token request failed: {type(e).__name__}")

    def get_access_token(self, force_refresh: bool = False) -> AccessToken:
        """
        Get a valid access token, refreshing if necessary.

        Uses cached token if still valid, otherwise requests new token.

        Args:
            force_refresh: If True, always request new token

        Returns:
            AccessToken: Valid access token

        Raises:
            IRISAuthError: If authentication fails
        """
        # Return cached token if still valid
        if not force_refresh and self._cached_token and not self._cached_token.is_expired:
            logger.debug("Using cached access token")
            return self._cached_token

        # Create new assertion and exchange for token
        logger.info("Obtaining new access token...")
        assertion = self._create_client_assertion()
        self._cached_token = self._request_token(assertion)
        return self._cached_token

    def test_authentication(self) -> bool:
        """
        Test authentication by requesting a token.

        Useful for validating configuration and connectivity.

        Returns:
            bool: True if authentication succeeds

        Raises:
            IRISAuthError: If authentication fails (with details)
        """
        logger.info("Testing IRIS authentication...")
        try:
            token = self.get_access_token(force_refresh=True)
            logger.info(f"Authentication test passed: {token}")
            return True
        except IRISAuthError:
            logger.error("Authentication test failed")
            raise
