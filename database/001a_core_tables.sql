-- Sherpa 1099 Database Schema
-- Migration 001a: Core Tables (no forward references)
-- Run this FIRST in Supabase SQL Editor

-- ============================================================================
-- OPERATING YEARS
-- ============================================================================
CREATE TABLE operating_years (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tax_year INTEGER NOT NULL UNIQUE CHECK (tax_year >= 2020 AND tax_year <= 2050),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'archived')),
    is_current BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_operating_years_current ON operating_years (is_current) WHERE is_current = true;

-- ============================================================================
-- FILERS (Your Clients - The Payers)
-- ============================================================================
CREATE TABLE filers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    dba_name TEXT,
    tin TEXT NOT NULL,
    tin_type TEXT NOT NULL CHECK (tin_type IN ('EIN', 'SSN')),
    address1 TEXT NOT NULL,
    address2 TEXT,
    city TEXT NOT NULL,
    state TEXT NOT NULL CHECK (LENGTH(state) = 2),
    zip TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT 'US',
    contact_name TEXT,
    phone TEXT,
    email TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id),
    updated_by UUID REFERENCES auth.users(id)
);

CREATE INDEX idx_filers_name ON filers (name);
CREATE INDEX idx_filers_active ON filers (is_active) WHERE is_active = true;

-- ============================================================================
-- RECIPIENTS (People/Companies Receiving 1099s)
-- ============================================================================
CREATE TABLE recipients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filer_id UUID NOT NULL REFERENCES filers(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    name_line_2 TEXT,
    tin TEXT NOT NULL,
    tin_type TEXT NOT NULL CHECK (tin_type IN ('EIN', 'SSN', 'ITIN', 'ATIN')),
    tin_status TEXT CHECK (tin_status IN (
        'not_checked', 'matched', 'mismatched', 'pending', 'unavailable'
    )) DEFAULT 'not_checked',
    tin_checked_at TIMESTAMPTZ,
    tin_match_code TEXT,
    address1 TEXT NOT NULL,
    address2 TEXT,
    city TEXT NOT NULL,
    state TEXT NOT NULL CHECK (LENGTH(state) = 2),
    zip TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT 'US',
    email TEXT,
    account_number TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
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
-- SUBMISSIONS (Batch Submissions to IRS) - Must be created BEFORE forms_1099
-- ============================================================================
CREATE TABLE submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operating_year_id UUID NOT NULL REFERENCES operating_years(id),
    submission_type TEXT NOT NULL CHECK (submission_type IN ('original', 'correction', 'test')),
    form_type TEXT NOT NULL CHECK (form_type IN ('1099-NEC', '1099-MISC', '1099-INT', '1099-DIV')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'submitted', 'processing', 'accepted', 'partial', 'rejected', 'error'
    )),
    total_forms INTEGER NOT NULL DEFAULT 0,
    accepted_count INTEGER DEFAULT 0,
    rejected_count INTEGER DEFAULT 0,
    iris_submission_id TEXT,
    iris_receipt_id TEXT,
    iris_response JSONB,
    submitted_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id)
);

CREATE INDEX idx_submissions_year ON submissions (operating_year_id);
CREATE INDEX idx_submissions_status ON submissions (status);

-- ============================================================================
-- FORMS_1099 (The Actual 1099 Forms)
-- ============================================================================
CREATE TABLE forms_1099 (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filer_id UUID NOT NULL REFERENCES filers(id) ON DELETE CASCADE,
    recipient_id UUID NOT NULL REFERENCES recipients(id) ON DELETE CASCADE,
    operating_year_id UUID NOT NULL REFERENCES operating_years(id),
    form_type TEXT NOT NULL CHECK (form_type IN ('1099-NEC', '1099-MISC', '1099-INT', '1099-DIV')),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN (
        'draft', 'validated', 'validation_error', 'ready', 'submitted', 'accepted', 'rejected', 'corrected'
    )),
    validation_errors JSONB,
    validated_at TIMESTAMPTZ,

    -- 1099-NEC Boxes
    nec_box1 NUMERIC(12,2) DEFAULT 0,
    nec_box2 BOOLEAN DEFAULT false,
    nec_box4 NUMERIC(12,2) DEFAULT 0,

    -- 1099-MISC Boxes
    misc_box1 NUMERIC(12,2) DEFAULT 0,
    misc_box2 NUMERIC(12,2) DEFAULT 0,
    misc_box3 NUMERIC(12,2) DEFAULT 0,
    misc_box4 NUMERIC(12,2) DEFAULT 0,
    misc_box5 NUMERIC(12,2) DEFAULT 0,
    misc_box6 NUMERIC(12,2) DEFAULT 0,
    misc_box7 BOOLEAN DEFAULT false,
    misc_box8 NUMERIC(12,2) DEFAULT 0,
    misc_box9 NUMERIC(12,2) DEFAULT 0,
    misc_box10 NUMERIC(12,2) DEFAULT 0,
    misc_box11 NUMERIC(12,2) DEFAULT 0,
    misc_box12 NUMERIC(12,2) DEFAULT 0,
    misc_box14 NUMERIC(12,2) DEFAULT 0,

    -- State Filing
    state1_code TEXT CHECK (state1_code IS NULL OR LENGTH(state1_code) = 2),
    state1_id TEXT,
    state1_income NUMERIC(12,2) DEFAULT 0,
    state1_withheld NUMERIC(12,2) DEFAULT 0,
    state2_code TEXT CHECK (state2_code IS NULL OR LENGTH(state2_code) = 2),
    state2_id TEXT,
    state2_income NUMERIC(12,2) DEFAULT 0,
    state2_withheld NUMERIC(12,2) DEFAULT 0,

    -- IRS Submission Tracking
    submission_id UUID REFERENCES submissions(id),
    irs_record_id TEXT,
    irs_status TEXT,
    irs_response JSONB,

    -- Correction Tracking
    is_correction BOOLEAN NOT NULL DEFAULT false,
    corrects_form_id UUID REFERENCES forms_1099(id),
    corrected_by_form_id UUID,

    -- Audit Fields
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id),
    updated_by UUID REFERENCES auth.users(id)
);

CREATE UNIQUE INDEX idx_forms_1099_unique
    ON forms_1099 (filer_id, recipient_id, operating_year_id, form_type)
    WHERE is_correction = false;

CREATE INDEX idx_forms_1099_filer ON forms_1099 (filer_id);
CREATE INDEX idx_forms_1099_recipient ON forms_1099 (recipient_id);
CREATE INDEX idx_forms_1099_year ON forms_1099 (operating_year_id);
CREATE INDEX idx_forms_1099_status ON forms_1099 (status);
CREATE INDEX idx_forms_1099_form_type ON forms_1099 (form_type);

-- ============================================================================
-- INITIAL DATA
-- ============================================================================
INSERT INTO operating_years (tax_year, status, is_current) VALUES (2024, 'open', true);
INSERT INTO operating_years (tax_year, status, is_current) VALUES (2023, 'closed', false);
