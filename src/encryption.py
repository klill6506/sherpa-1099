"""
TIN Encryption Module for Sherpa 1099.

Provides Fernet-based encryption for sensitive TIN data (SSN/EIN).
Stores three values for each TIN:
- tin_encrypted: Fernet-encrypted full TIN
- tin_last4: Plain text last 4 digits (for display: XXX-XX-1234)
- tin_hash: SHA-256 hash (for duplicate detection without decryption)

Key versioning supports rotation without re-encrypting all data immediately.
"""

import os
import re
import hashlib
import base64
from typing import Optional, Tuple
from cryptography.fernet import Fernet, InvalidToken


# Environment variable for the encryption key
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY_ENV = "TIN_ENCRYPTION_KEY"

# Current key version (increment when rotating keys)
CURRENT_KEY_VERSION = 1


def get_encryption_key() -> bytes:
    """
    Get the encryption key from environment variable.

    Raises:
        ValueError: If key is not set or invalid.
    """
    key = os.getenv(ENCRYPTION_KEY_ENV)
    if not key:
        raise ValueError(
            f"Encryption key not configured. Set {ENCRYPTION_KEY_ENV} environment variable. "
            f"Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )

    # Validate key format
    try:
        key_bytes = key.encode() if isinstance(key, str) else key
        Fernet(key_bytes)  # Validates key format
        return key_bytes
    except Exception as e:
        raise ValueError(f"Invalid encryption key format: {e}")


def normalize_tin(tin: str) -> str:
    """
    Normalize TIN to 9 digits only (remove dashes/spaces).

    Args:
        tin: TIN string, may contain dashes (123-45-6789 or 12-3456789)

    Returns:
        9-digit string

    Raises:
        ValueError: If TIN doesn't contain exactly 9 digits
    """
    digits = re.sub(r'\D', '', tin)
    if len(digits) != 9:
        raise ValueError(f"TIN must contain exactly 9 digits, got {len(digits)}")
    return digits


def encrypt_tin(tin: str) -> Tuple[str, str, str, int]:
    """
    Encrypt a TIN and return all storage values.

    Args:
        tin: Plain text TIN (with or without dashes)

    Returns:
        Tuple of (tin_encrypted, tin_last4, tin_hash, key_version)
        - tin_encrypted: Base64-encoded Fernet encrypted value
        - tin_last4: Last 4 digits for display (e.g., "6789")
        - tin_hash: SHA-256 hash for duplicate detection
        - key_version: Version of key used for encryption
    """
    # Normalize to 9 digits
    normalized = normalize_tin(tin)

    # Get encryption key
    key = get_encryption_key()
    fernet = Fernet(key)

    # Encrypt the normalized TIN
    encrypted = fernet.encrypt(normalized.encode())
    tin_encrypted = base64.urlsafe_b64encode(encrypted).decode()

    # Extract last 4 digits
    tin_last4 = normalized[-4:]

    # Create hash for duplicate detection
    tin_hash = hashlib.sha256(normalized.encode()).hexdigest()

    return tin_encrypted, tin_last4, tin_hash, CURRENT_KEY_VERSION


def decrypt_tin(tin_encrypted: str, key_version: int = CURRENT_KEY_VERSION) -> str:
    """
    Decrypt an encrypted TIN.

    Args:
        tin_encrypted: Base64-encoded Fernet encrypted value
        key_version: Version of key used for encryption (for future rotation support)

    Returns:
        Plain text 9-digit TIN

    Raises:
        ValueError: If decryption fails
    """
    # TODO: Support multiple key versions for rotation
    if key_version != CURRENT_KEY_VERSION:
        raise ValueError(f"Unsupported key version: {key_version}. Only version {CURRENT_KEY_VERSION} is supported.")

    key = get_encryption_key()
    fernet = Fernet(key)

    try:
        # Decode from our base64 wrapper, then decrypt
        encrypted_bytes = base64.urlsafe_b64decode(tin_encrypted.encode())
        decrypted = fernet.decrypt(encrypted_bytes)
        return decrypted.decode()
    except InvalidToken:
        raise ValueError("Failed to decrypt TIN - invalid token or wrong key")
    except Exception as e:
        raise ValueError(f"Failed to decrypt TIN: {e}")


def format_tin_display(tin_last4: str, tin_type: str = "SSN") -> str:
    """
    Format TIN for display with masked digits.

    Args:
        tin_last4: Last 4 digits of TIN
        tin_type: "SSN" or "EIN"

    Returns:
        Masked TIN string (e.g., "XXX-XX-1234" for SSN, "XX-XXX1234" for EIN)
    """
    if tin_type == "SSN":
        return f"XXX-XX-{tin_last4}"
    else:  # EIN
        return f"XX-XXX{tin_last4}"


def format_tin_full(tin: str, tin_type: str = "SSN") -> str:
    """
    Format a full 9-digit TIN with proper dashes.

    Args:
        tin: 9-digit TIN string
        tin_type: "SSN" or "EIN"

    Returns:
        Formatted TIN (e.g., "123-45-6789" for SSN, "12-3456789" for EIN)
    """
    normalized = normalize_tin(tin)
    if tin_type == "SSN":
        return f"{normalized[:3]}-{normalized[3:5]}-{normalized[5:]}"
    else:  # EIN
        return f"{normalized[:2]}-{normalized[2:]}"


def hash_tin(tin: str) -> str:
    """
    Create a hash of a TIN for duplicate detection.

    Args:
        tin: Plain text TIN (with or without dashes)

    Returns:
        SHA-256 hash string
    """
    normalized = normalize_tin(tin)
    return hashlib.sha256(normalized.encode()).hexdigest()


def generate_encryption_key() -> str:
    """
    Generate a new Fernet encryption key.

    Returns:
        Base64-encoded key string suitable for environment variable
    """
    return Fernet.generate_key().decode()


# =============================================================================
# Migration helpers
# =============================================================================

def migrate_plain_tin(plain_tin: str, tin_type: str = "SSN") -> dict:
    """
    Migrate a plain text TIN to encrypted format.

    Args:
        plain_tin: Existing plain text TIN
        tin_type: "SSN" or "EIN"

    Returns:
        Dict with keys: tin_encrypted, tin_last4, tin_hash, tin_key_version
    """
    tin_encrypted, tin_last4, tin_hash, key_version = encrypt_tin(plain_tin)
    return {
        "tin_encrypted": tin_encrypted,
        "tin_last4": tin_last4,
        "tin_hash": tin_hash,
        "tin_key_version": key_version,
    }
