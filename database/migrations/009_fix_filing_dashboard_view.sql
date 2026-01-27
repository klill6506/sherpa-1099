-- Migration 009: Fix filing_dashboard view to show all filers
-- The previous view used INNER JOIN which excluded new filers without status rows
-- This version uses LEFT JOIN and starts from filers table

-- ============================================================================
-- FIX: Filing Dashboard should show ALL active filers
-- ============================================================================

-- Drop the existing view first
DROP VIEW IF EXISTS public.filing_dashboard;

-- Create improved view that shows all filers, even those without status records
CREATE OR REPLACE VIEW public.filing_dashboard AS
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
    -- Count forms for this filer/year
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
    AND ffs.tenant_id = f.tenant_id
WHERE f.is_active = true;

-- Add a comment explaining the view
COMMENT ON VIEW public.filing_dashboard IS 'Shows all active filers with their filing status. Uses CROSS JOIN with operating_years and LEFT JOIN with filer_filing_status to include filers without status records. Filter by tax_year in your query.';
