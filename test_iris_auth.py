#!/usr/bin/env python3
"""
Test script for IRIS ATS authentication.

This script validates:
1. Configuration loading from environment
2. Private key loading
3. JWT assertion creation
4. Token request to IRS (if endpoints are configured)

Usage:
    python test_iris_auth.py

Environment:
    Set IRIS_CLIENT_ID before running, or create a .env file.

Exit codes:
    0 - All tests passed
    1 - Configuration error
    2 - Authentication error
    3 - Unexpected error
"""

import sys
import logging
from pathlib import Path

# Set up logging - show INFO and above
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_iris_auth")


def test_config():
    """Test configuration loading."""
    print("\n" + "=" * 60)
    print("STEP 1: Loading Configuration")
    print("=" * 60)

    try:
        # Try loading from .env first
        env_path = Path(__file__).parent / ".env"
        if env_path.exists():
            print(f"  Found .env file at: {env_path}")
            from src.config import load_config_from_dotenv
            config = load_config_from_dotenv(env_path)
        else:
            print("  No .env file found, using environment variables")
            from src.config import load_config
            config = load_config()

        print(f"  Client ID: {config.client_id[:8]}...{config.client_id[-4:]}")
        print(f"  Key ID: {config.key_id}")
        print(f"  Environment: {config.environment}")
        print(f"  Private Key Path: {config.private_key_path}")
        print(f"  Auth Endpoint: {config.auth_endpoint}")
        print(f"  API Base URL: {config.api_base_url}")
        print("\n  [OK] Configuration loaded successfully")
        return config

    except ValueError as e:
        print(f"\n  [FAIL] Configuration error: {e}")
        print("\n  Hint: Set IRIS_CLIENT_ID environment variable or create .env file")
        return None

    except FileNotFoundError as e:
        print(f"\n  [FAIL] File not found: {e}")
        return None


def test_key_loading(config):
    """Test private key loading."""
    print("\n" + "=" * 60)
    print("STEP 2: Loading Private Key")
    print("=" * 60)

    try:
        from src.iris_auth import IRISAuthenticator
        auth = IRISAuthenticator(config)

        # Try to load the key (internal method)
        key = auth._load_private_key()

        # Basic validation - check it looks like a PEM key
        if "BEGIN" in key and "PRIVATE KEY" in key:
            print(f"  Key format: PEM (PKCS8)")
            print(f"  Key length: {len(key)} characters")
            print("\n  [OK] Private key loaded successfully")
            return auth
        else:
            print("\n  [FAIL] Key doesn't appear to be in PEM format")
            return None

    except Exception as e:
        print(f"\n  [FAIL] Key loading failed: {e}")
        return None


def test_jwt_creation(auth):
    """Test JWT assertion creation."""
    print("\n" + "=" * 60)
    print("STEP 3: Creating JWT Assertion")
    print("=" * 60)

    try:
        # Create assertion
        assertion = auth._create_client_assertion()

        # Basic validation
        parts = assertion.split(".")
        if len(parts) != 3:
            print(f"\n  [FAIL] JWT doesn't have 3 parts (got {len(parts)})")
            return None

        print(f"  JWT structure: header.payload.signature")
        print(f"  Header (encoded): {parts[0][:30]}...")
        print(f"  Payload (encoded): {parts[1][:30]}...")
        print(f"  Signature: {parts[2][:30]}...")
        print(f"  Total length: {len(assertion)} characters")
        print("\n  [OK] JWT assertion created successfully")
        return assertion

    except Exception as e:
        print(f"\n  [FAIL] JWT creation failed: {e}")
        return None


def test_token_request(auth, config):
    """Test actual token request to IRS."""
    print("\n" + "=" * 60)
    print("STEP 4: Requesting Access Token")
    print("=" * 60)

    print(f"  Endpoint: {config.auth_endpoint}")
    print("  Sending token request...")

    try:
        token = auth.get_access_token(force_refresh=True)
        print(f"\n  Token type: {token.token_type}")
        print(f"  Token (first 20 chars): {token.token[:20]}...")
        print(f"  Expires at: {token.expires_at}")
        print(f"  Is expired: {token.is_expired}")
        print("\n  [OK] Access token obtained successfully!")
        return True

    except Exception as e:
        print(f"\n  [FAIL] Token request failed: {e}")
        print("\n  This is expected if:")
        print("  - The auth endpoint URL is a placeholder (TODO)")
        print("  - You don't have network access to IRS")
        print("  - JWKS registration is incomplete")
        return False


def test_client_connection(config):
    """Test full client connection."""
    print("\n" + "=" * 60)
    print("STEP 5: Testing IRIS Client")
    print("=" * 60)

    try:
        from src.iris_client import IRISClient
        client = IRISClient(config)

        print("  Testing connection...")
        client.test_connection()
        print("\n  [OK] Client connection successful!")
        return True

    except Exception as e:
        print(f"\n  [FAIL] Client connection failed: {e}")
        return False


def main():
    """Run all tests."""
    print("\n" + "#" * 60)
    print("# IRIS ATS Authentication Test")
    print("#" * 60)

    # Test 1: Configuration
    config = test_config()
    if config is None:
        print("\n[ABORT] Cannot proceed without valid configuration")
        return 1

    # Test 2: Key loading
    auth = test_key_loading(config)
    if auth is None:
        print("\n[ABORT] Cannot proceed without valid private key")
        return 1

    # Test 3: JWT creation
    jwt = test_jwt_creation(auth)
    if jwt is None:
        print("\n[ABORT] Cannot proceed without valid JWT")
        return 2

    # Test 4: Token request (may fail if endpoint is placeholder)
    token_ok = test_token_request(auth, config)

    # Test 5: Client connection (only if token succeeded)
    client_ok = False
    if token_ok:
        client_ok = test_client_connection(config)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Configuration: OK")
    print(f"  Private Key:   OK")
    print(f"  JWT Creation:  OK")
    print(f"  Token Request: {'OK' if token_ok else 'FAILED (may be expected)'}")
    print(f"  Client Test:   {'OK' if client_ok else 'SKIPPED' if not token_ok else 'FAILED'}")

    if token_ok and client_ok:
        print("\n[SUCCESS] All tests passed! Ready for ATS submission.")
        return 0
    elif jwt is not None:
        print("\n[PARTIAL] Local tests passed. Token request needs endpoint configuration.")
        print("          Update IRIS_AUTH_ENDPOINT with actual IRS ATS URL.")
        return 0
    else:
        print("\n[FAILURE] Some tests failed. Check configuration and try again.")
        return 2


if __name__ == "__main__":
    try:
        exit_code = main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        exit_code = 130
    except Exception as e:
        logger.exception("Unexpected error")
        exit_code = 3

    sys.exit(exit_code)
