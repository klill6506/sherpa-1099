-- Sherpa 1099 Database Migration
-- Migration 003: Add 1099-S and 1098 Form Support
-- Run this in Supabase SQL Editor after existing migrations

-- ============================================================================
-- UPDATE FORM TYPE CONSTRAINTS
-- ============================================================================

-- Update forms_1099 form_type constraint to include new types
ALTER TABLE forms_1099 DROP CONSTRAINT IF EXISTS forms_1099_form_type_check;
ALTER TABLE forms_1099 ADD CONSTRAINT forms_1099_form_type_check
    CHECK (form_type IN ('1099-NEC', '1099-MISC', '1099-INT', '1099-DIV', '1099-S', '1098'));

-- Update submissions form_type constraint
ALTER TABLE submissions DROP CONSTRAINT IF EXISTS submissions_form_type_check;
ALTER TABLE submissions ADD CONSTRAINT submissions_form_type_check
    CHECK (form_type IN ('1099-NEC', '1099-MISC', '1099-INT', '1099-DIV', '1099-S', '1098'));

-- ============================================================================
-- 1099-S COLUMNS (Proceeds From Real Estate Transactions)
-- ============================================================================

-- Box 1: Date of closing (date format)
ALTER TABLE forms_1099 ADD COLUMN IF NOT EXISTS s_box1_date_closing DATE;

-- Box 2: Gross proceeds
ALTER TABLE forms_1099 ADD COLUMN IF NOT EXISTS s_box2_gross_proceeds NUMERIC(12,2) DEFAULT 0;

-- Box 3: Address or legal description of property (multi-line text)
ALTER TABLE forms_1099 ADD COLUMN IF NOT EXISTS s_box3_property_address TEXT;

-- Box 4: Transferor received property or services (checkbox)
ALTER TABLE forms_1099 ADD COLUMN IF NOT EXISTS s_box4_property_services BOOLEAN DEFAULT false;

-- Box 5: Buyer is foreign person (checkbox)
ALTER TABLE forms_1099 ADD COLUMN IF NOT EXISTS s_box5_foreign_person BOOLEAN DEFAULT false;

-- Box 6: Buyer's part of real estate tax
ALTER TABLE forms_1099 ADD COLUMN IF NOT EXISTS s_box6_buyers_tax NUMERIC(12,2) DEFAULT 0;

-- ============================================================================
-- 1098 COLUMNS (Mortgage Interest Statement)
-- ============================================================================

-- Box 1: Mortgage interest received from payer/borrower
ALTER TABLE forms_1099 ADD COLUMN IF NOT EXISTS f1098_box1_mortgage_interest NUMERIC(12,2) DEFAULT 0;

-- Box 2: Outstanding mortgage principal
ALTER TABLE forms_1099 ADD COLUMN IF NOT EXISTS f1098_box2_outstanding_principal NUMERIC(12,2) DEFAULT 0;

-- Box 3: Mortgage origination date
ALTER TABLE forms_1099 ADD COLUMN IF NOT EXISTS f1098_box3_origination_date DATE;

-- Box 4: Refund of overpaid interest
ALTER TABLE forms_1099 ADD COLUMN IF NOT EXISTS f1098_box4_refund_interest NUMERIC(12,2) DEFAULT 0;

-- Box 5: Mortgage insurance premiums
ALTER TABLE forms_1099 ADD COLUMN IF NOT EXISTS f1098_box5_mortgage_insurance NUMERIC(12,2) DEFAULT 0;

-- Box 6: Points paid on purchase of principal residence
ALTER TABLE forms_1099 ADD COLUMN IF NOT EXISTS f1098_box6_points_paid NUMERIC(12,2) DEFAULT 0;

-- Box 8: Property address if different from payer address
ALTER TABLE forms_1099 ADD COLUMN IF NOT EXISTS f1098_box8_property_address TEXT;

-- Box 9: Number of mortgaged properties
ALTER TABLE forms_1099 ADD COLUMN IF NOT EXISTS f1098_box9_num_properties INTEGER;

-- Box 10: Other
ALTER TABLE forms_1099 ADD COLUMN IF NOT EXISTS f1098_box10_other NUMERIC(12,2) DEFAULT 0;

-- Box 11: Mortgage acquisition date
ALTER TABLE forms_1099 ADD COLUMN IF NOT EXISTS f1098_box11_acquisition_date DATE;

-- ============================================================================
-- UPDATE IMPORT_ROWS FOR NEW FORM FIELDS (if table exists)
-- ============================================================================

DO $$
BEGIN
    -- 1099-S fields
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'import_rows') THEN
        ALTER TABLE import_rows ADD COLUMN IF NOT EXISTS s_box1_date_closing DATE;
        ALTER TABLE import_rows ADD COLUMN IF NOT EXISTS s_box2_gross_proceeds NUMERIC(12,2);
        ALTER TABLE import_rows ADD COLUMN IF NOT EXISTS s_box3_property_address TEXT;
        ALTER TABLE import_rows ADD COLUMN IF NOT EXISTS s_box4_property_services BOOLEAN;
        ALTER TABLE import_rows ADD COLUMN IF NOT EXISTS s_box5_foreign_person BOOLEAN;
        ALTER TABLE import_rows ADD COLUMN IF NOT EXISTS s_box6_buyers_tax NUMERIC(12,2);

        -- 1098 fields
        ALTER TABLE import_rows ADD COLUMN IF NOT EXISTS f1098_box1_mortgage_interest NUMERIC(12,2);
        ALTER TABLE import_rows ADD COLUMN IF NOT EXISTS f1098_box2_outstanding_principal NUMERIC(12,2);
        ALTER TABLE import_rows ADD COLUMN IF NOT EXISTS f1098_box3_origination_date DATE;
        ALTER TABLE import_rows ADD COLUMN IF NOT EXISTS f1098_box4_refund_interest NUMERIC(12,2);
        ALTER TABLE import_rows ADD COLUMN IF NOT EXISTS f1098_box5_mortgage_insurance NUMERIC(12,2);
        ALTER TABLE import_rows ADD COLUMN IF NOT EXISTS f1098_box6_points_paid NUMERIC(12,2);
        ALTER TABLE import_rows ADD COLUMN IF NOT EXISTS f1098_box8_property_address TEXT;
        ALTER TABLE import_rows ADD COLUMN IF NOT EXISTS f1098_box9_num_properties INTEGER;
        ALTER TABLE import_rows ADD COLUMN IF NOT EXISTS f1098_box10_other NUMERIC(12,2);
        ALTER TABLE import_rows ADD COLUMN IF NOT EXISTS f1098_box11_acquisition_date DATE;
    END IF;
END $$;

-- ============================================================================
-- ADD COLUMN ALIASES FOR NEW FORM TYPES
-- ============================================================================

-- 1099-S Aliases
INSERT INTO column_aliases (target_field, alias, priority) VALUES
    -- Date of closing
    ('s_box1_date_closing', 'date of closing', 100),
    ('s_box1_date_closing', 'closing date', 90),
    ('s_box1_date_closing', 'date closing', 80),
    ('s_box1_date_closing', 's_box1', 70),
    ('s_box1_date_closing', 'box 1', 60),
    -- Gross proceeds
    ('s_box2_gross_proceeds', 'gross proceeds', 100),
    ('s_box2_gross_proceeds', 'proceeds', 90),
    ('s_box2_gross_proceeds', 'sale amount', 80),
    ('s_box2_gross_proceeds', 's_box2', 70),
    ('s_box2_gross_proceeds', 'box 2', 60),
    -- Property address/description
    ('s_box3_property_address', 'property address', 100),
    ('s_box3_property_address', 'property description', 90),
    ('s_box3_property_address', 'legal description', 80),
    ('s_box3_property_address', 's_box3', 70),
    ('s_box3_property_address', 'box 3', 60),
    -- Property/services checkbox
    ('s_box4_property_services', 'property services', 100),
    ('s_box4_property_services', 'received property', 90),
    ('s_box4_property_services', 's_box4', 70),
    ('s_box4_property_services', 'box 4', 60),
    -- Foreign person checkbox
    ('s_box5_foreign_person', 'foreign person', 100),
    ('s_box5_foreign_person', 'foreign buyer', 90),
    ('s_box5_foreign_person', 's_box5', 70),
    ('s_box5_foreign_person', 'box 5', 60),
    -- Buyer's tax
    ('s_box6_buyers_tax', 'buyers tax', 100),
    ('s_box6_buyers_tax', 'buyer tax', 90),
    ('s_box6_buyers_tax', 'real estate tax', 80),
    ('s_box6_buyers_tax', 's_box6', 70),
    ('s_box6_buyers_tax', 'box 6', 60)
ON CONFLICT DO NOTHING;

-- 1098 Aliases
INSERT INTO column_aliases (target_field, alias, priority) VALUES
    -- Box 1: Mortgage interest
    ('f1098_box1_mortgage_interest', 'mortgage interest', 100),
    ('f1098_box1_mortgage_interest', 'interest received', 90),
    ('f1098_box1_mortgage_interest', 'interest paid', 80),
    ('f1098_box1_mortgage_interest', '1098_box1', 70),
    ('f1098_box1_mortgage_interest', 'box 1 mortgage', 60),
    -- Box 2: Outstanding principal
    ('f1098_box2_outstanding_principal', 'outstanding principal', 100),
    ('f1098_box2_outstanding_principal', 'principal balance', 90),
    ('f1098_box2_outstanding_principal', 'mortgage principal', 80),
    ('f1098_box2_outstanding_principal', '1098_box2', 70),
    -- Box 3: Origination date
    ('f1098_box3_origination_date', 'origination date', 100),
    ('f1098_box3_origination_date', 'mortgage origination', 90),
    ('f1098_box3_origination_date', 'loan origination', 80),
    ('f1098_box3_origination_date', '1098_box3', 70),
    -- Box 4: Refund
    ('f1098_box4_refund_interest', 'refund interest', 100),
    ('f1098_box4_refund_interest', 'overpaid interest', 90),
    ('f1098_box4_refund_interest', '1098_box4', 70),
    -- Box 5: Mortgage insurance
    ('f1098_box5_mortgage_insurance', 'mortgage insurance', 100),
    ('f1098_box5_mortgage_insurance', 'pmi', 90),
    ('f1098_box5_mortgage_insurance', 'insurance premiums', 80),
    ('f1098_box5_mortgage_insurance', '1098_box5', 70),
    -- Box 6: Points paid
    ('f1098_box6_points_paid', 'points paid', 100),
    ('f1098_box6_points_paid', 'points', 90),
    ('f1098_box6_points_paid', '1098_box6', 70),
    -- Box 8: Property address
    ('f1098_box8_property_address', 'property address', 100),
    ('f1098_box8_property_address', '1098_box8', 70),
    -- Box 9: Num properties
    ('f1098_box9_num_properties', 'number of properties', 100),
    ('f1098_box9_num_properties', 'num properties', 90),
    ('f1098_box9_num_properties', '1098_box9', 70),
    -- Box 10: Other
    ('f1098_box10_other', '1098 other', 100),
    ('f1098_box10_other', '1098_box10', 70),
    -- Box 11: Acquisition date
    ('f1098_box11_acquisition_date', 'acquisition date', 100),
    ('f1098_box11_acquisition_date', 'property acquisition', 90),
    ('f1098_box11_acquisition_date', '1098_box11', 70)
ON CONFLICT DO NOTHING;

-- ============================================================================
-- DONE
-- ============================================================================
