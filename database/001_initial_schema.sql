-- Sherpa 1099 Database Schema
-- Migration 001: Initial Schema
-- Run this in Supabase SQL Editor

-- ============================================================================
-- OPERATING YEARS
-- Tracks tax years and their status (open for editing, closed/filed, etc.)
-- ============================================================================
CREATE TABLE operating_years (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tax_year INTEGER NOT NULL UNIQUE CHECK (tax_year >= 2020 AND tax_year <= 2050),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'archived')),
    is_current BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Ensure only one year can be marked as current
CREATE UNIQUE INDEX idx_operating_years_current ON operating_years (is_current) WHERE is_current = true;

-- ============================================================================
-- FILERS (Your Clients - The Payers)
-- These are the companies/individuals who pay contractors and need to file 1099s
-- ============================================================================
CREATE TABLE filers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Business Information
    name TEXT NOT NULL,
    dba_name TEXT,  -- "Doing Business As" name if different

    -- Tax Identification
    tin TEXT NOT NULL,  -- EIN or SSN (stored encrypted, see RLS policies)
    tin_type TEXT NOT NULL CHECK (tin_type IN ('EIN', 'SSN')),

    -- Address (required for 1099 filing)
    address1 TEXT NOT NULL,
    address2 TEXT,
    city TEXT NOT NULL,
    state TEXT NOT NULL CHECK (LENGTH(state) = 2),
    zip TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT 'US',

    -- Contact Information
    contact_name TEXT,
    phone TEXT,
    email TEXT,

    -- Status and Metadata
    is_active BOOLEAN NOT NULL DEFAULT true,
    notes TEXT,

    -- Audit Fields
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id),
    updated_by UUID REFERENCES auth.users(id)
);

CREATE INDEX idx_filers_name ON filers (name);
CREATE INDEX idx_filers_active ON filers (is_active) WHERE is_active = true;

-- ============================================================================
-- RECIPIENTS (People/Companies Receiving 1099s)
-- These are contractors, vendors, etc. who received payments
-- ============================================================================
CREATE TABLE recipients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filer_id UUID NOT NULL REFERENCES filers(id) ON DELETE CASCADE,

    -- Recipient Identification
    name TEXT NOT NULL,  -- Individual or business name
    name_line_2 TEXT,    -- Second name line if needed

    -- Tax Identification
    tin TEXT NOT NULL,
    tin_type TEXT NOT NULL CHECK (tin_type IN ('EIN', 'SSN', 'ITIN', 'ATIN')),

    -- TIN Matching Status (from IRS TIN Matching)
    tin_status TEXT CHECK (tin_status IN (
        'not_checked',      -- Never verified
        'matched',          -- TIN/Name combination matches IRS records
        'mismatched',       -- Does not match
        'pending',          -- Verification in progress
        'unavailable'       -- IRS system unavailable during check
    )) DEFAULT 'not_checked',
    tin_checked_at TIMESTAMPTZ,
    tin_match_code TEXT,  -- IRS response code for reference

    -- Address
    address1 TEXT NOT NULL,
    address2 TEXT,
    city TEXT NOT NULL,
    state TEXT NOT NULL CHECK (LENGTH(state) = 2),
    zip TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT 'US',

    -- Contact/Reference
    email TEXT,
    account_number TEXT,  -- Filer's internal account/vendor number

    -- Status
    is_active BOOLEAN NOT NULL DEFAULT true,

    -- Audit Fields
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id),
    updated_by UUID REFERENCES auth.users(id)
);

CREATE INDEX idx_recipients_filer ON recipients (filer_id);
CREATE INDEX idx_recipients_tin ON recipients (tin);
CREATE INDEX idx_recipients_name ON recipients (name);
CREATE INDEX idx_recipients_tin_status ON recipients (tin_status);

-- ============================================================================
-- FORMS_1099 (The Actual 1099 Forms)
-- Each record represents one 1099 form for one recipient for one tax year
-- ============================================================================
CREATE TABLE forms_1099 (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Relationships
    filer_id UUID NOT NULL REFERENCES filers(id) ON DELETE CASCADE,
    recipient_id UUID NOT NULL REFERENCES recipients(id) ON DELETE CASCADE,
    operating_year_id UUID NOT NULL REFERENCES operating_years(id),

    -- Form Type
    form_type TEXT NOT NULL CHECK (form_type IN ('1099-NEC', '1099-MISC', '1099-INT', '1099-DIV')),

    -- Status Workflow
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN (
        'draft',            -- Being edited
        'validated',        -- Passed validation
        'validation_error', -- Failed validation
        'ready',            -- Ready to submit to IRS
        'submitted',        -- Sent to IRS
        'accepted',         -- IRS accepted
        'rejected',         -- IRS rejected
        'corrected'         -- A correction was filed
    )),

    -- Validation
    validation_errors JSONB,  -- Array of error messages if validation failed
    validated_at TIMESTAMPTZ,

    -- 1099-NEC Specific Boxes
    nec_box1 NUMERIC(12,2) DEFAULT 0,   -- Nonemployee compensation
    nec_box2 BOOLEAN DEFAULT false,      -- Payer made direct sales of $5,000+
    nec_box4 NUMERIC(12,2) DEFAULT 0,   -- Federal income tax withheld

    -- 1099-MISC Specific Boxes
    misc_box1 NUMERIC(12,2) DEFAULT 0,   -- Rents
    misc_box2 NUMERIC(12,2) DEFAULT 0,   -- Royalties
    misc_box3 NUMERIC(12,2) DEFAULT 0,   -- Other income
    misc_box4 NUMERIC(12,2) DEFAULT 0,   -- Federal income tax withheld
    misc_box5 NUMERIC(12,2) DEFAULT 0,   -- Fishing boat proceeds
    misc_box6 NUMERIC(12,2) DEFAULT 0,   -- Medical and health care payments
    misc_box7 BOOLEAN DEFAULT false,      -- Payer made direct sales of $5,000+
    misc_box8 NUMERIC(12,2) DEFAULT 0,   -- Substitute payments in lieu of dividends
    misc_box9 NUMERIC(12,2) DEFAULT 0,   -- Crop insurance proceeds
    misc_box10 NUMERIC(12,2) DEFAULT 0,  -- Gross proceeds paid to attorney
    misc_box11 NUMERIC(12,2) DEFAULT 0,  -- Fish purchased for resale
    misc_box12 NUMERIC(12,2) DEFAULT 0,  -- Section 409A deferrals
    misc_box14 NUMERIC(12,2) DEFAULT 0,  -- Nonqualified deferred compensation

    -- State Filing (up to 2 states per form)
    state1_code TEXT CHECK (state1_code IS NULL OR LENGTH(state1_code) = 2),
    state1_id TEXT,              -- State ID number
    state1_income NUMERIC(12,2) DEFAULT 0,
    state1_withheld NUMERIC(12,2) DEFAULT 0,

    state2_code TEXT CHECK (state2_code IS NULL OR LENGTH(state2_code) = 2),
    state2_id TEXT,
    state2_income NUMERIC(12,2) DEFAULT 0,
    state2_withheld NUMERIC(12,2) DEFAULT 0,

    -- IRS Submission Tracking
    submission_id UUID REFERENCES submissions(id),  -- Which batch submission
    irs_record_id TEXT,          -- ID assigned by IRS
    irs_status TEXT,             -- Status from IRS
    irs_response JSONB,          -- Full IRS response for this record

    -- Correction Tracking
    is_correction BOOLEAN NOT NULL DEFAULT false,
    corrects_form_id UUID REFERENCES forms_1099(id),  -- Points to original if this is a correction
    corrected_by_form_id UUID,   -- Points to correction if this was corrected

    -- Audit Fields
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id),
    updated_by UUID REFERENCES auth.users(id)
);

-- Prevent duplicate forms (same recipient, same year, same form type, unless correction)
CREATE UNIQUE INDEX idx_forms_1099_unique
    ON forms_1099 (filer_id, recipient_id, operating_year_id, form_type)
    WHERE is_correction = false;

CREATE INDEX idx_forms_1099_filer ON forms_1099 (filer_id);
CREATE INDEX idx_forms_1099_recipient ON forms_1099 (recipient_id);
CREATE INDEX idx_forms_1099_year ON forms_1099 (operating_year_id);
CREATE INDEX idx_forms_1099_status ON forms_1099 (status);
CREATE INDEX idx_forms_1099_form_type ON forms_1099 (form_type);

-- ============================================================================
-- SUBMISSIONS (Batch Submissions to IRS)
-- Tracks batches of forms submitted together
-- ============================================================================
CREATE TABLE submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operating_year_id UUID NOT NULL REFERENCES operating_years(id),

    -- Submission Details
    submission_type TEXT NOT NULL CHECK (submission_type IN ('original', 'correction', 'test')),
    form_type TEXT NOT NULL CHECK (form_type IN ('1099-NEC', '1099-MISC', '1099-INT', '1099-DIV')),

    -- Status
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending',      -- Not yet submitted
        'submitted',    -- Sent to IRS, awaiting response
        'processing',   -- IRS is processing
        'accepted',     -- All records accepted
        'partial',      -- Some records accepted, some rejected
        'rejected',     -- All records rejected
        'error'         -- System error during submission
    )),

    -- Counts
    total_forms INTEGER NOT NULL DEFAULT 0,
    accepted_count INTEGER DEFAULT 0,
    rejected_count INTEGER DEFAULT 0,

    -- IRS Response
    iris_submission_id TEXT,     -- ID from IRS IRIS system
    iris_receipt_id TEXT,        -- Receipt ID from IRS
    iris_response JSONB,         -- Full response from IRS

    -- Timestamps
    submitted_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    -- Audit Fields
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id)
);

CREATE INDEX idx_submissions_year ON submissions (operating_year_id);
CREATE INDEX idx_submissions_status ON submissions (status);

-- ============================================================================
-- TIN_MATCH_LOG (History of TIN Matching Requests)
-- Audit trail for all TIN matching attempts
-- ============================================================================
CREATE TABLE tin_match_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_id UUID NOT NULL REFERENCES recipients(id) ON DELETE CASCADE,

    -- Request Details
    tin_submitted TEXT NOT NULL,      -- TIN that was submitted (for audit if TIN changes)
    name_submitted TEXT NOT NULL,     -- Name that was submitted

    -- Response from IRS
    match_code TEXT NOT NULL,         -- IRS response code (0-8)
    match_result TEXT NOT NULL CHECK (match_result IN ('matched', 'mismatched', 'unavailable')),
    irs_response JSONB,               -- Full response for debugging

    -- Audit
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    checked_by UUID REFERENCES auth.users(id)
);

CREATE INDEX idx_tin_match_log_recipient ON tin_match_log (recipient_id);
CREATE INDEX idx_tin_match_log_date ON tin_match_log (checked_at);

-- ============================================================================
-- ACTIVITY_LOG (Audit Trail)
-- Tracks all significant actions for compliance and debugging
-- ============================================================================
CREATE TABLE activity_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Who
    user_id UUID REFERENCES auth.users(id),
    user_email TEXT,  -- Denormalized for easier querying

    -- What
    action TEXT NOT NULL,  -- e.g., 'create_filer', 'update_recipient', 'submit_forms'
    entity_type TEXT,      -- e.g., 'filer', 'recipient', 'form_1099', 'submission'
    entity_id UUID,        -- ID of the affected entity

    -- Context
    filer_id UUID REFERENCES filers(id) ON DELETE SET NULL,
    operating_year_id UUID REFERENCES operating_years(id) ON DELETE SET NULL,

    -- Details
    details JSONB,         -- Action-specific details
    ip_address INET,
    user_agent TEXT,

    -- When
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_activity_log_user ON activity_log (user_id);
CREATE INDEX idx_activity_log_action ON activity_log (action);
CREATE INDEX idx_activity_log_entity ON activity_log (entity_type, entity_id);
CREATE INDEX idx_activity_log_filer ON activity_log (filer_id);
CREATE INDEX idx_activity_log_date ON activity_log (created_at);

-- ============================================================================
-- IMPORT_HISTORY (Track Data Imports)
-- Prevents accidental overwrites by tracking what was imported where
-- ============================================================================
CREATE TABLE import_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- What was imported
    filer_id UUID NOT NULL REFERENCES filers(id) ON DELETE CASCADE,
    operating_year_id UUID NOT NULL REFERENCES operating_years(id),

    -- File details
    filename TEXT NOT NULL,
    file_hash TEXT,           -- SHA-256 hash to detect duplicate imports
    file_size INTEGER,

    -- Results
    records_imported INTEGER NOT NULL DEFAULT 0,
    records_updated INTEGER NOT NULL DEFAULT 0,
    records_skipped INTEGER NOT NULL DEFAULT 0,
    errors JSONB,             -- Any errors during import

    -- Status
    status TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('completed', 'partial', 'failed', 'rolled_back')),
    rolled_back_at TIMESTAMPTZ,
    rolled_back_by UUID REFERENCES auth.users(id),

    -- Audit
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id)
);

CREATE INDEX idx_import_history_filer ON import_history (filer_id);
CREATE INDEX idx_import_history_year ON import_history (operating_year_id);
CREATE INDEX idx_import_history_hash ON import_history (file_hash);

-- ============================================================================
-- USER PROFILES (Extends Supabase Auth)
-- Additional user information beyond what Supabase Auth provides
-- ============================================================================
CREATE TABLE user_profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,

    -- Display info
    full_name TEXT,
    avatar_url TEXT,

    -- Preferences
    default_operating_year_id UUID REFERENCES operating_years(id),
    preferences JSONB DEFAULT '{}'::jsonb,

    -- Role (for future multi-tenant support)
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user', 'readonly')),

    -- Audit
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to all tables with updated_at
CREATE TRIGGER update_operating_years_updated_at BEFORE UPDATE ON operating_years
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_filers_updated_at BEFORE UPDATE ON filers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_recipients_updated_at BEFORE UPDATE ON recipients
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_forms_1099_updated_at BEFORE UPDATE ON forms_1099
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_submissions_updated_at BEFORE UPDATE ON submissions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_profiles_updated_at BEFORE UPDATE ON user_profiles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- INITIAL DATA
-- ============================================================================

-- Create current tax year
INSERT INTO operating_years (tax_year, status, is_current)
VALUES (2024, 'open', true);

-- Create previous year for migration testing
INSERT INTO operating_years (tax_year, status, is_current)
VALUES (2023, 'closed', false);
