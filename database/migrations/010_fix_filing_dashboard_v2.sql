-- Migration 010: Fix filing_dashboard view v2
-- Simplified view that doesn't require tenant_id matching
-- Works for single-tenant setups

DROP VIEW IF EXISTS public.filing_dashboard;

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
