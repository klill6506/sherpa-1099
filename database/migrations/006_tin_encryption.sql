-- Migration 006: TIN Encryption
-- Adds encrypted TIN columns to filers and recipients tables
-- Run this in Supabase SQL Editor

-- =============================================================================
-- STEP 1: Add new columns for encrypted TIN storage
-- =============================================================================

-- Filers table
ALTER TABLE filers
ADD COLUMN IF NOT EXISTS tin_encrypted TEXT,
ADD COLUMN IF NOT EXISTS tin_last4 VARCHAR(4),
ADD COLUMN IF NOT EXISTS tin_hash VARCHAR(64),
ADD COLUMN IF NOT EXISTS tin_key_version INTEGER DEFAULT 1;

-- Recipients table
ALTER TABLE recipients
ADD COLUMN IF NOT EXISTS tin_encrypted TEXT,
ADD COLUMN IF NOT EXISTS tin_last4 VARCHAR(4),
ADD COLUMN IF NOT EXISTS tin_hash VARCHAR(64),
ADD COLUMN IF NOT EXISTS tin_key_version INTEGER DEFAULT 1;

-- =============================================================================
-- STEP 2: Create indexes for hash lookups (duplicate detection)
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_filers_tin_hash ON filers(tin_hash);
CREATE INDEX IF NOT EXISTS idx_recipients_tin_hash ON recipients(tin_hash);

-- =============================================================================
-- STEP 3: Add comments for documentation
-- =============================================================================

COMMENT ON COLUMN filers.tin_encrypted IS 'Fernet-encrypted TIN (base64 encoded)';
COMMENT ON COLUMN filers.tin_last4 IS 'Last 4 digits of TIN for display (e.g., 1234)';
COMMENT ON COLUMN filers.tin_hash IS 'SHA-256 hash of TIN for duplicate detection';
COMMENT ON COLUMN filers.tin_key_version IS 'Encryption key version used';

COMMENT ON COLUMN recipients.tin_encrypted IS 'Fernet-encrypted TIN (base64 encoded)';
COMMENT ON COLUMN recipients.tin_last4 IS 'Last 4 digits of TIN for display (e.g., 1234)';
COMMENT ON COLUMN recipients.tin_hash IS 'SHA-256 hash of TIN for duplicate detection';
COMMENT ON COLUMN recipients.tin_key_version IS 'Encryption key version used';

-- =============================================================================
-- MIGRATION NOTES
-- =============================================================================
--
-- After running this migration:
--
-- 1. Set the TIN_ENCRYPTION_KEY environment variable on the server:
--    Generate a key with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
--    Add to .env or server environment: TIN_ENCRYPTION_KEY=your-generated-key
--
-- 2. Run the Python migration script to encrypt existing TINs:
--    python scripts/migrate_tins.py
--
-- 3. After verifying encryption works, drop the old 'tin' column:
--    ALTER TABLE filers DROP COLUMN tin;
--    ALTER TABLE recipients DROP COLUMN tin;
--
-- DO NOT drop the old 'tin' column until you've verified the migration worked!
-- =============================================================================
