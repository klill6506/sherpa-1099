-- Import Staging Tables for Excel/CSV uploads
-- Migration: 002_import_staging.sql

-- Import batches track each file upload
CREATE TABLE IF NOT EXISTS import_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operating_year_id UUID NOT NULL REFERENCES operating_years(id),
    filer_id UUID REFERENCES filers(id),  -- NULL until mapped/created

    -- File info
    filename VARCHAR(255) NOT NULL,
    file_size INTEGER,
    file_hash VARCHAR(64),  -- SHA256 for dedup

    -- Status tracking
    status VARCHAR(50) NOT NULL DEFAULT 'uploaded',  -- uploaded, mapping, validating, validated, promoting, promoted, failed

    -- Counts
    total_rows INTEGER DEFAULT 0,
    valid_rows INTEGER DEFAULT 0,
    error_rows INTEGER DEFAULT 0,
    warning_rows INTEGER DEFAULT 0,

    -- Column mapping (JSON: {"source_col": "target_field", ...})
    column_mapping JSONB,

    -- Processing metadata
    uploaded_at TIMESTAMPTZ DEFAULT NOW(),
    validated_at TIMESTAMPTZ,
    promoted_at TIMESTAMPTZ,

    -- Audit
    created_by UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Import rows store raw + normalized data for each record
CREATE TABLE IF NOT EXISTS import_rows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL,  -- Original row in spreadsheet

    -- Raw data as uploaded (JSON preserves original)
    raw_data JSONB NOT NULL,

    -- Normalized/cleaned fields (populated after normalization)
    -- Recipient info
    recipient_name VARCHAR(255),
    recipient_name_line2 VARCHAR(255),
    recipient_tin VARCHAR(11),
    recipient_tin_type VARCHAR(3),  -- SSN or EIN
    recipient_address1 VARCHAR(255),
    recipient_address2 VARCHAR(255),
    recipient_city VARCHAR(100),
    recipient_state VARCHAR(2),
    recipient_zip VARCHAR(10),
    recipient_country VARCHAR(2) DEFAULT 'US',
    recipient_email VARCHAR(255),
    account_number VARCHAR(50),

    -- Form type detection
    form_type VARCHAR(20),  -- 1099-NEC, 1099-MISC, etc.

    -- 1099-NEC boxes
    nec_box1 NUMERIC(12,2),  -- Nonemployee compensation
    nec_box2 BOOLEAN,        -- Payer made direct sales
    nec_box4 NUMERIC(12,2),  -- Federal tax withheld

    -- 1099-MISC boxes
    misc_box1 NUMERIC(12,2),   -- Rents
    misc_box2 NUMERIC(12,2),   -- Royalties
    misc_box3 NUMERIC(12,2),   -- Other income
    misc_box4 NUMERIC(12,2),   -- Federal tax withheld
    misc_box5 NUMERIC(12,2),   -- Fishing boat proceeds
    misc_box6 NUMERIC(12,2),   -- Medical payments
    misc_box7 BOOLEAN,         -- Direct sales
    misc_box8 NUMERIC(12,2),   -- Substitute payments
    misc_box9 NUMERIC(12,2),   -- Crop insurance
    misc_box10 NUMERIC(12,2),  -- Attorney payments
    misc_box11 NUMERIC(12,2),  -- Fish purchased
    misc_box12 NUMERIC(12,2),  -- 409A deferrals
    misc_box14 NUMERIC(12,2),  -- Nonqualified deferred comp

    -- State withholding
    state1_code VARCHAR(2),
    state1_id VARCHAR(20),
    state1_income NUMERIC(12,2),
    state1_withheld NUMERIC(12,2),
    state2_code VARCHAR(2),
    state2_id VARCHAR(20),
    state2_income NUMERIC(12,2),
    state2_withheld NUMERIC(12,2),

    -- Validation status
    status VARCHAR(50) NOT NULL DEFAULT 'pending',  -- pending, valid, error, warning, skipped
    validation_errors JSONB,  -- [{field, code, message, severity}]

    -- TIN matching results (populated when TIN matching runs)
    tin_match_status VARCHAR(20),  -- pending, matched, mismatched, error
    tin_match_code VARCHAR(10),
    tin_checked_at TIMESTAMPTZ,

    -- Link to promoted record (after successful promotion)
    promoted_recipient_id UUID REFERENCES recipients(id),
    promoted_form_id UUID REFERENCES forms_1099(id),

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_import_batches_status ON import_batches(status);
CREATE INDEX IF NOT EXISTS idx_import_batches_operating_year ON import_batches(operating_year_id);
CREATE INDEX IF NOT EXISTS idx_import_rows_batch ON import_rows(batch_id);
CREATE INDEX IF NOT EXISTS idx_import_rows_status ON import_rows(status);
CREATE INDEX IF NOT EXISTS idx_import_rows_tin ON import_rows(recipient_tin);

-- Column alias mapping table (for common variations)
CREATE TABLE IF NOT EXISTS column_aliases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_field VARCHAR(100) NOT NULL,  -- Our normalized field name
    alias VARCHAR(255) NOT NULL,         -- Common variation (case-insensitive match)
    priority INTEGER DEFAULT 0,          -- Higher = prefer this mapping
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(target_field, alias)
);

-- Seed common column aliases
INSERT INTO column_aliases (target_field, alias, priority) VALUES
    -- Recipient name variations
    ('recipient_name', 'name', 10),
    ('recipient_name', 'payee', 10),
    ('recipient_name', 'payee name', 10),
    ('recipient_name', 'recipient', 10),
    ('recipient_name', 'vendor', 10),
    ('recipient_name', 'vendor name', 10),
    ('recipient_name', 'contractor', 10),
    ('recipient_name', 'contractor name', 10),
    ('recipient_name', 'first name', 5),

    -- TIN variations
    ('recipient_tin', 'tin', 10),
    ('recipient_tin', 'ssn', 10),
    ('recipient_tin', 'ein', 10),
    ('recipient_tin', 'tax id', 10),
    ('recipient_tin', 'taxid', 10),
    ('recipient_tin', 'social', 10),
    ('recipient_tin', 'social security', 10),
    ('recipient_tin', 'fed id', 10),
    ('recipient_tin', 'federal id', 10),

    -- Address variations
    ('recipient_address1', 'address', 10),
    ('recipient_address1', 'address1', 10),
    ('recipient_address1', 'address 1', 10),
    ('recipient_address1', 'street', 10),
    ('recipient_address1', 'street address', 10),
    ('recipient_address2', 'address2', 10),
    ('recipient_address2', 'address 2', 10),
    ('recipient_address2', 'suite', 5),
    ('recipient_address2', 'apt', 5),

    -- City/State/ZIP
    ('recipient_city', 'city', 10),
    ('recipient_state', 'state', 10),
    ('recipient_state', 'st', 10),
    ('recipient_zip', 'zip', 10),
    ('recipient_zip', 'zipcode', 10),
    ('recipient_zip', 'zip code', 10),
    ('recipient_zip', 'postal', 10),
    ('recipient_zip', 'postal code', 10),

    -- Amount variations (NEC)
    ('nec_box1', 'amount', 10),
    ('nec_box1', 'compensation', 10),
    ('nec_box1', 'nonemployee compensation', 10),
    ('nec_box1', 'payment', 10),
    ('nec_box1', 'total', 10),
    ('nec_box1', 'box 1', 10),
    ('nec_box1', 'box1', 10),
    ('nec_box4', 'federal withheld', 10),
    ('nec_box4', 'fed withheld', 10),
    ('nec_box4', 'withheld', 5),

    -- MISC boxes
    ('misc_box1', 'rents', 10),
    ('misc_box1', 'rent', 10),
    ('misc_box2', 'royalties', 10),
    ('misc_box3', 'other income', 10),
    ('misc_box6', 'medical', 10),
    ('misc_box10', 'attorney', 10),
    ('misc_box10', 'legal', 10)
ON CONFLICT (target_field, alias) DO NOTHING;

-- Update trigger for updated_at
CREATE OR REPLACE FUNCTION update_import_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS import_batches_updated_at ON import_batches;
CREATE TRIGGER import_batches_updated_at
    BEFORE UPDATE ON import_batches
    FOR EACH ROW
    EXECUTE FUNCTION update_import_updated_at();

DROP TRIGGER IF EXISTS import_rows_updated_at ON import_rows;
CREATE TRIGGER import_rows_updated_at
    BEFORE UPDATE ON import_rows
    FOR EACH ROW
    EXECUTE FUNCTION update_import_updated_at();
