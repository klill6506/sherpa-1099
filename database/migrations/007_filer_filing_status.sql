-- Sherpa 1099 Database Migration
-- Migration 007: Filer Filing Status Tracking
-- Run this in Supabase SQL Editor
--
-- This migration adds issuer-level filing status tracking so we can see:
-- - Who prepared each filer's returns (preparer)
-- - Filing status: NOT_FILED / SUBMITTED / PROCESSING / ACCEPTED / REJECTED
-- - Last receipt ID, transmission ID, and submission details
-- - Error details if rejected

-- ============================================================================
-- FILER_FILING_STATUS TABLE
-- One row per filer per tax year to track filing progress
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.filer_filing_status (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Tenant and filer relationship
    tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    filer_id UUID NOT NULL REFERENCES public.filers(id) ON DELETE CASCADE,

    -- Tax year this status applies to
    tax_year INT NOT NULL CHECK (tax_year >= 2020 AND tax_year <= 2050),

    -- Preparer tracking
    prepared_by_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    prepared_by_name TEXT,  -- Denormalized for display (in case user is deleted)

    -- Filing status
    status TEXT NOT NULL DEFAULT 'NOT_FILED'
        CHECK (status IN ('NOT_FILED', 'SUBMITTED', 'PROCESSING', 'ACCEPTED', 'ACCEPTED_WITH_ERRORS', 'REJECTED')),

    -- Last submission tracking
    last_submission_id UUID REFERENCES public.submissions(id) ON DELETE SET NULL,
    last_receipt_id TEXT,
    last_transmission_id TEXT,

    -- Timestamps
    last_submitted_at TIMESTAMPTZ,
    last_status_checked_at TIMESTAMPTZ,

    -- Error/response storage
    last_errors JSONB,
    last_ack_xml TEXT,

    -- Notes (for manual comments)
    notes TEXT,

    -- Audit timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Ensure one row per filer per tax year per tenant
    UNIQUE (tenant_id, filer_id, tax_year)
);

-- Indexes for common queries
CREATE INDEX idx_filer_filing_status_tenant ON filer_filing_status (tenant_id);
CREATE INDEX idx_filer_filing_status_filer ON filer_filing_status (filer_id);
CREATE INDEX idx_filer_filing_status_tax_year ON filer_filing_status (tax_year);
CREATE INDEX idx_filer_filing_status_status ON filer_filing_status (status);
CREATE INDEX idx_filer_filing_status_preparer ON filer_filing_status (prepared_by_user_id);

-- Composite index for dashboard queries
CREATE INDEX idx_filer_filing_status_tenant_year_status
    ON filer_filing_status (tenant_id, tax_year, status);

-- ============================================================================
-- AUTO-UPDATE TRIGGER FOR UPDATED_AT
-- ============================================================================

-- Reuse the existing function if it exists, or create it
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_filer_filing_status_updated ON public.filer_filing_status;
CREATE TRIGGER trg_filer_filing_status_updated
    BEFORE UPDATE ON public.filer_filing_status
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ============================================================================
-- BACKFILL FUNCTION: Create NOT_FILED rows for all filers with 1099 data
-- ============================================================================
-- This creates filing status rows only for filers that have forms for a given year

CREATE OR REPLACE FUNCTION public.backfill_filer_filing_status(p_tax_year INT)
RETURNS INT AS $$
DECLARE
    rows_inserted INT;
BEGIN
    WITH filers_with_forms AS (
        SELECT DISTINCT f.tenant_id, f.id AS filer_id
        FROM public.filers f
        JOIN public.forms_1099 fm ON fm.filer_id = f.id
        JOIN public.operating_years oy ON oy.id = fm.operating_year_id
        WHERE oy.tax_year = p_tax_year
          AND f.is_active = true
    )
    INSERT INTO public.filer_filing_status (tenant_id, filer_id, tax_year, status)
    SELECT tenant_id, filer_id, p_tax_year, 'NOT_FILED'
    FROM filers_with_forms
    ON CONFLICT (tenant_id, filer_id, tax_year) DO NOTHING;

    GET DIAGNOSTICS rows_inserted = ROW_COUNT;
    RETURN rows_inserted;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- UPSERT FUNCTION: Set preparer when work begins
-- Only sets preparer if not already set (first-touch attribution)
-- ============================================================================

CREATE OR REPLACE FUNCTION public.set_filer_preparer(
    p_tenant_id UUID,
    p_filer_id UUID,
    p_tax_year INT,
    p_user_id UUID,
    p_user_name TEXT
)
RETURNS public.filer_filing_status AS $$
DECLARE
    result public.filer_filing_status;
BEGIN
    INSERT INTO public.filer_filing_status (
        tenant_id, filer_id, tax_year,
        prepared_by_user_id, prepared_by_name
    )
    VALUES (
        p_tenant_id, p_filer_id, p_tax_year,
        p_user_id, p_user_name
    )
    ON CONFLICT (tenant_id, filer_id, tax_year)
    DO UPDATE SET
        prepared_by_user_id = COALESCE(
            filer_filing_status.prepared_by_user_id,
            EXCLUDED.prepared_by_user_id
        ),
        prepared_by_name = COALESCE(
            filer_filing_status.prepared_by_name,
            EXCLUDED.prepared_by_name
        )
    RETURNING * INTO result;

    RETURN result;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- UPDATE FUNCTION: Update status after IRS submission
-- ============================================================================

CREATE OR REPLACE FUNCTION public.update_filer_filing_status_on_submit(
    p_tenant_id UUID,
    p_filer_id UUID,
    p_tax_year INT,
    p_status TEXT,
    p_submission_id UUID,
    p_receipt_id TEXT,
    p_transmission_id TEXT
)
RETURNS public.filer_filing_status AS $$
DECLARE
    result public.filer_filing_status;
BEGIN
    INSERT INTO public.filer_filing_status (
        tenant_id, filer_id, tax_year,
        status, last_submission_id, last_receipt_id,
        last_transmission_id, last_submitted_at, last_errors
    )
    VALUES (
        p_tenant_id, p_filer_id, p_tax_year,
        p_status, p_submission_id, p_receipt_id,
        p_transmission_id, NOW(), NULL
    )
    ON CONFLICT (tenant_id, filer_id, tax_year)
    DO UPDATE SET
        status = EXCLUDED.status,
        last_submission_id = EXCLUDED.last_submission_id,
        last_receipt_id = EXCLUDED.last_receipt_id,
        last_transmission_id = EXCLUDED.last_transmission_id,
        last_submitted_at = NOW(),
        last_errors = NULL
    RETURNING * INTO result;

    RETURN result;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- UPDATE FUNCTION: Update status after checking IRS status
-- ============================================================================

CREATE OR REPLACE FUNCTION public.update_filer_filing_status_on_check(
    p_tenant_id UUID,
    p_filer_id UUID,
    p_tax_year INT,
    p_status TEXT,
    p_errors JSONB DEFAULT NULL,
    p_ack_xml TEXT DEFAULT NULL
)
RETURNS public.filer_filing_status AS $$
DECLARE
    result public.filer_filing_status;
BEGIN
    UPDATE public.filer_filing_status
    SET
        status = p_status,
        last_status_checked_at = NOW(),
        last_errors = p_errors,
        last_ack_xml = p_ack_xml
    WHERE tenant_id = p_tenant_id
      AND filer_id = p_filer_id
      AND tax_year = p_tax_year
    RETURNING * INTO result;

    RETURN result;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- VIEW: Filing Dashboard with filer details
-- ============================================================================

CREATE OR REPLACE VIEW public.filing_dashboard AS
SELECT
    ffs.id,
    ffs.tenant_id,
    ffs.filer_id,
    ffs.tax_year,
    f.name AS filer_name,
    f.tin AS filer_tin,
    ffs.prepared_by_user_id,
    ffs.prepared_by_name,
    ffs.status,
    ffs.last_receipt_id,
    ffs.last_transmission_id,
    ffs.last_submitted_at,
    ffs.last_status_checked_at,
    ffs.last_errors,
    ffs.notes,
    ffs.created_at,
    ffs.updated_at,
    -- Count forms for this filer/year
    (
        SELECT COUNT(*)
        FROM public.forms_1099 fm
        JOIN public.operating_years oy ON oy.id = fm.operating_year_id
        WHERE fm.filer_id = ffs.filer_id AND oy.tax_year = ffs.tax_year
    ) AS form_count
FROM public.filer_filing_status ffs
JOIN public.filers f ON f.id = ffs.filer_id;

-- ============================================================================
-- RUN BACKFILL FOR TAX YEAR 2025
-- ============================================================================

-- Backfill status rows for all filers with 2025 data
SELECT public.backfill_filer_filing_status(2025);

-- ============================================================================
-- OPTIONAL: Set default preparer for existing data
-- Uncomment and modify if you want to assign a default preparer
-- ============================================================================

-- Example: Set Ken as preparer for all unassigned 2025 filings
-- UPDATE public.filer_filing_status
-- SET
--     prepared_by_name = 'Ken',
--     prepared_by_user_id = 'your-ken-user-uuid-here'
-- WHERE tax_year = 2025
--   AND prepared_by_user_id IS NULL;
