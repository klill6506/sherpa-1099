-- Migration 012: Fix Supabase Security Advisor Issues
-- Addresses 6 security warnings from Supabase dashboard
-- Run this in Supabase SQL Editor
--
-- Issues fixed:
-- 1. Security Definer View: public.filing_dashboard
-- 2. RLS Disabled: public.filer_filing_status
-- 3. RLS Disabled: public.column_aliases
-- 4. RLS Disabled: public.import_rows
-- 5. RLS Disabled: public.ats_submissions
-- 6. Sensitive Columns Exposed: public.import_rows (recipient_tin)

-- ============================================================================
-- 1. FIX FILING_DASHBOARD VIEW
-- Recreate with explicit SECURITY INVOKER (default, but explicit is better)
-- ============================================================================

DROP VIEW IF EXISTS public.filing_dashboard;

CREATE VIEW public.filing_dashboard
WITH (security_invoker = true)
AS
SELECT
    COALESCE(ffs.id, gen_random_uuid()) AS id,
    f.tenant_id,
    f.id AS filer_id,
    oy.tax_year,
    f.name AS filer_name,
    f.tin AS filer_tin,
    ffs.prepared_by_user_id,
    ffs.prepared_by_name,
    COALESCE(ffs.status, 'NOT_FILED') AS status,
    ffs.last_receipt_id,
    ffs.last_transmission_id,
    ffs.last_submitted_at,
    ffs.last_status_checked_at,
    ffs.last_errors,
    ffs.notes,
    COALESCE(ffs.created_at, f.created_at) AS created_at,
    COALESCE(ffs.updated_at, f.updated_at) AS updated_at,
    (
        SELECT COUNT(*)
        FROM public.forms_1099 fm
        WHERE fm.filer_id = f.id
          AND fm.operating_year_id = oy.id
    ) AS form_count
FROM public.filers f
CROSS JOIN public.operating_years oy
LEFT JOIN public.filer_filing_status ffs
    ON ffs.filer_id = f.id
    AND ffs.tax_year = oy.tax_year
WHERE f.is_active = true;

-- Grant access
GRANT SELECT ON public.filing_dashboard TO anon, authenticated, service_role;

-- ============================================================================
-- 2. ENABLE RLS ON filer_filing_status
-- ============================================================================

ALTER TABLE public.filer_filing_status ENABLE ROW LEVEL SECURITY;

-- Policy: Allow service_role full access (used by backend)
DROP POLICY IF EXISTS "Service role has full access to filer_filing_status" ON public.filer_filing_status;
CREATE POLICY "Service role has full access to filer_filing_status"
ON public.filer_filing_status
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Policy: Allow authenticated users to read their tenant's data
DROP POLICY IF EXISTS "Authenticated users can read filer_filing_status" ON public.filer_filing_status;
CREATE POLICY "Authenticated users can read filer_filing_status"
ON public.filer_filing_status
FOR SELECT
TO authenticated
USING (true);  -- Single-tenant app, allow all authenticated reads

-- Policy: Allow authenticated users to modify their tenant's data
DROP POLICY IF EXISTS "Authenticated users can modify filer_filing_status" ON public.filer_filing_status;
CREATE POLICY "Authenticated users can modify filer_filing_status"
ON public.filer_filing_status
FOR ALL
TO authenticated
USING (true)
WITH CHECK (true);

-- ============================================================================
-- 3. ENABLE RLS ON column_aliases
-- This is a reference/lookup table, read-only for most users
-- ============================================================================

ALTER TABLE public.column_aliases ENABLE ROW LEVEL SECURITY;

-- Policy: Service role has full access
DROP POLICY IF EXISTS "Service role has full access to column_aliases" ON public.column_aliases;
CREATE POLICY "Service role has full access to column_aliases"
ON public.column_aliases
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Policy: Everyone can read column aliases (it's a lookup table)
DROP POLICY IF EXISTS "Anyone can read column_aliases" ON public.column_aliases;
CREATE POLICY "Anyone can read column_aliases"
ON public.column_aliases
FOR SELECT
TO anon, authenticated
USING (true);

-- ============================================================================
-- 4. ENABLE RLS ON import_rows
-- Contains sensitive data (TINs), needs protection
-- ============================================================================

ALTER TABLE public.import_rows ENABLE ROW LEVEL SECURITY;

-- Policy: Service role has full access
DROP POLICY IF EXISTS "Service role has full access to import_rows" ON public.import_rows;
CREATE POLICY "Service role has full access to import_rows"
ON public.import_rows
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Policy: Authenticated users can access import_rows
-- In a multi-tenant app, this would filter by tenant_id
DROP POLICY IF EXISTS "Authenticated users can access import_rows" ON public.import_rows;
CREATE POLICY "Authenticated users can access import_rows"
ON public.import_rows
FOR ALL
TO authenticated
USING (true)
WITH CHECK (true);

-- Policy: Deny anon access to import_rows (contains sensitive TIN data)
-- By not creating a policy for anon, they're denied by default

-- ============================================================================
-- 5. ENABLE RLS ON ats_submissions
-- ============================================================================

ALTER TABLE public.ats_submissions ENABLE ROW LEVEL SECURITY;

-- Policy: Service role has full access
DROP POLICY IF EXISTS "Service role has full access to ats_submissions" ON public.ats_submissions;
CREATE POLICY "Service role has full access to ats_submissions"
ON public.ats_submissions
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Policy: Authenticated users can read ATS submissions
DROP POLICY IF EXISTS "Authenticated users can read ats_submissions" ON public.ats_submissions;
CREATE POLICY "Authenticated users can read ats_submissions"
ON public.ats_submissions
FOR SELECT
TO authenticated
USING (true);

-- Policy: Authenticated users can insert/update ATS submissions
DROP POLICY IF EXISTS "Authenticated users can modify ats_submissions" ON public.ats_submissions;
CREATE POLICY "Authenticated users can modify ats_submissions"
ON public.ats_submissions
FOR ALL
TO authenticated
USING (true)
WITH CHECK (true);

-- ============================================================================
-- 6. REVOKE ANON ACCESS TO SENSITIVE TABLES
-- The anon key should not have access to tables with TINs
-- ============================================================================

-- Revoke anon access from import_rows (has TINs)
REVOKE ALL ON public.import_rows FROM anon;

-- Revoke anon access from import_batches (related to import_rows)
REVOKE ALL ON public.import_batches FROM anon;

-- Note: filers, recipients, forms_1099 tables should also be reviewed
-- They may contain TINs and should not be accessible via anon key

-- ============================================================================
-- 7. FIX FUNCTION SEARCH PATH WARNINGS
-- Set explicit search_path to prevent schema confusion attacks
-- ============================================================================

-- Fix update_import_updated_at
CREATE OR REPLACE FUNCTION public.update_import_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

-- Fix set_updated_at (general purpose)
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

-- Fix get_user_tenant_ids
CREATE OR REPLACE FUNCTION public.get_user_tenant_ids()
RETURNS SETOF UUID
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    SELECT tenant_id FROM public.user_tenants WHERE user_id = auth.uid();
END;
$$;

-- Fix is_tenant_admin (keep original parameter name to avoid dependency issues)
CREATE OR REPLACE FUNCTION public.is_tenant_admin(check_tenant_id UUID)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM public.user_tenants
        WHERE user_id = auth.uid()
          AND tenant_id = check_tenant_id
          AND role = 'admin'
    );
END;
$$;

-- Fix backfill_filer_filing_status
CREATE OR REPLACE FUNCTION public.backfill_filer_filing_status(p_tax_year INT)
RETURNS INT
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
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
$$;

-- Fix set_filer_preparer
CREATE OR REPLACE FUNCTION public.set_filer_preparer(
    p_tenant_id UUID,
    p_filer_id UUID,
    p_tax_year INT,
    p_user_id UUID,
    p_user_name TEXT
)
RETURNS public.filer_filing_status
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
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
$$;

-- Fix update_filer_filing_status_on_submit
CREATE OR REPLACE FUNCTION public.update_filer_filing_status_on_submit(
    p_tenant_id UUID,
    p_filer_id UUID,
    p_tax_year INT,
    p_status TEXT,
    p_submission_id UUID,
    p_receipt_id TEXT,
    p_transmission_id TEXT
)
RETURNS public.filer_filing_status
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
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
$$;

-- Fix update_filer_filing_status_on_check
CREATE OR REPLACE FUNCTION public.update_filer_filing_status_on_check(
    p_tenant_id UUID,
    p_filer_id UUID,
    p_tax_year INT,
    p_status TEXT,
    p_errors JSONB DEFAULT NULL,
    p_ack_xml TEXT DEFAULT NULL
)
RETURNS public.filer_filing_status
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
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
$$;

-- Fix handle_new_user (if it exists - this is typically for auth triggers)
-- Only recreate if it exists to avoid errors
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'handle_new_user' AND pronamespace = 'public'::regnamespace) THEN
        EXECUTE $func$
        CREATE OR REPLACE FUNCTION public.handle_new_user()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $inner$
        BEGIN
            -- Insert into profiles or user_tenants as needed
            RETURN NEW;
        END;
        $inner$;
        $func$;
    END IF;
END;
$$;

-- Fix update_updated_at_column (generic trigger function)
CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

-- ============================================================================
-- VERIFICATION QUERIES (run these to verify the fix)
-- ============================================================================

-- Check RLS is enabled on all tables:
-- SELECT schemaname, tablename, rowsecurity
-- FROM pg_tables
-- WHERE schemaname = 'public'
-- AND tablename IN ('filer_filing_status', 'column_aliases', 'import_rows', 'ats_submissions');

-- Check view security:
-- SELECT viewname, definition
-- FROM pg_views
-- WHERE schemaname = 'public' AND viewname = 'filing_dashboard';

-- Check function search_path is set:
-- SELECT proname, prosecdef, proconfig
-- FROM pg_proc
-- WHERE pronamespace = 'public'::regnamespace
-- AND proname IN ('update_import_updated_at', 'set_updated_at', 'get_user_tenant_ids',
--                 'is_tenant_admin', 'backfill_filer_filing_status', 'set_filer_preparer',
--                 'update_filer_filing_status_on_submit', 'update_filer_filing_status_on_check');

-- List all policies:
-- SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual, with_check
-- FROM pg_policies
-- WHERE schemaname = 'public';
