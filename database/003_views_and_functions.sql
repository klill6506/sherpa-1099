-- Sherpa 1099 Database Schema
-- Migration 003: Views and Helper Functions
-- Run this AFTER 002_fix_references_and_rls.sql

-- ============================================================================
-- VIEW: Filer Status Summary (like E-File Magic dashboard)
-- Shows released/unreleased counts per filer for current year
-- ============================================================================
CREATE OR REPLACE VIEW filer_status_summary AS
SELECT
    f.id AS filer_id,
    f.name AS filer_name,
    f.tin AS filer_tin,
    oy.id AS operating_year_id,
    oy.tax_year,
    COUNT(DISTINCT r.id) AS total_recipients,
    COUNT(frm.id) AS total_forms,
    COUNT(frm.id) FILTER (WHERE frm.status IN ('submitted', 'accepted')) AS released_count,
    COUNT(frm.id) FILTER (WHERE frm.status NOT IN ('submitted', 'accepted')) AS unreleased_count,
    COUNT(frm.id) FILTER (WHERE frm.status = 'draft') AS draft_count,
    COUNT(frm.id) FILTER (WHERE frm.status = 'validated') AS validated_count,
    COUNT(frm.id) FILTER (WHERE frm.status = 'validation_error') AS error_count,
    COUNT(frm.id) FILTER (WHERE frm.status = 'accepted') AS accepted_count,
    COUNT(frm.id) FILTER (WHERE frm.status = 'rejected') AS rejected_count,
    CASE
        WHEN COUNT(frm.id) = 0 THEN 'no_forms'
        WHEN COUNT(frm.id) FILTER (WHERE frm.status = 'validation_error') > 0 THEN 'has_errors'
        WHEN COUNT(frm.id) = COUNT(frm.id) FILTER (WHERE frm.status = 'accepted') THEN 'complete'
        WHEN COUNT(frm.id) FILTER (WHERE frm.status IN ('submitted', 'accepted')) > 0 THEN 'in_progress'
        WHEN COUNT(frm.id) FILTER (WHERE frm.status = 'validated') = COUNT(frm.id) THEN 'ready_to_submit'
        ELSE 'draft'
    END AS overall_status
FROM filers f
CROSS JOIN operating_years oy
LEFT JOIN recipients r ON r.filer_id = f.id AND r.is_active = true
LEFT JOIN forms_1099 frm ON frm.filer_id = f.id AND frm.operating_year_id = oy.id
WHERE f.is_active = true
GROUP BY f.id, f.name, f.tin, oy.id, oy.tax_year
ORDER BY f.name, oy.tax_year DESC;

-- ============================================================================
-- VIEW: Recipient with TIN Status
-- Shows recipients with their TIN matching status for easy review
-- ============================================================================
CREATE OR REPLACE VIEW recipient_tin_status AS
SELECT
    r.id,
    r.filer_id,
    f.name AS filer_name,
    r.name AS recipient_name,
    r.tin,
    r.tin_type,
    r.tin_status,
    r.tin_checked_at,
    r.address1,
    r.city,
    r.state,
    r.zip,
    r.email,
    r.is_active,
    -- Days since TIN was checked (null if never checked)
    CASE
        WHEN r.tin_checked_at IS NOT NULL
        THEN EXTRACT(DAY FROM NOW() - r.tin_checked_at)::INTEGER
        ELSE NULL
    END AS days_since_tin_check
FROM recipients r
JOIN filers f ON f.id = r.filer_id;

-- ============================================================================
-- VIEW: Forms Ready for Submission
-- Shows all forms that are validated and ready to submit
-- ============================================================================
CREATE OR REPLACE VIEW forms_ready_for_submission AS
SELECT
    frm.id,
    frm.form_type,
    f.id AS filer_id,
    f.name AS filer_name,
    f.tin AS filer_tin,
    r.id AS recipient_id,
    r.name AS recipient_name,
    r.tin AS recipient_tin,
    r.tin_status,
    oy.tax_year,
    frm.nec_box1,
    frm.misc_box1,
    frm.misc_box2,
    frm.misc_box3,
    frm.status,
    frm.created_at,
    frm.validated_at
FROM forms_1099 frm
JOIN filers f ON f.id = frm.filer_id
JOIN recipients r ON r.id = frm.recipient_id
JOIN operating_years oy ON oy.id = frm.operating_year_id
WHERE frm.status IN ('validated', 'ready')
ORDER BY f.name, r.name;

-- ============================================================================
-- FUNCTION: Copy Filer Recipients to New Year
-- Safely copies recipients from one year to another (for year-over-year migration)
-- ============================================================================
CREATE OR REPLACE FUNCTION copy_filer_to_new_year(
    p_filer_id UUID,
    p_from_year INTEGER,
    p_to_year INTEGER,
    p_user_id UUID DEFAULT NULL
)
RETURNS TABLE (
    recipients_copied INTEGER,
    forms_created INTEGER
) AS $$
DECLARE
    v_from_year_id UUID;
    v_to_year_id UUID;
    v_recipients_copied INTEGER := 0;
    v_forms_created INTEGER := 0;
BEGIN
    -- Get operating year IDs
    SELECT id INTO v_from_year_id FROM operating_years WHERE tax_year = p_from_year;
    SELECT id INTO v_to_year_id FROM operating_years WHERE tax_year = p_to_year;

    IF v_from_year_id IS NULL THEN
        RAISE EXCEPTION 'Source year % not found', p_from_year;
    END IF;

    IF v_to_year_id IS NULL THEN
        RAISE EXCEPTION 'Target year % not found', p_to_year;
    END IF;

    -- Recipients are not year-specific, so we don't need to copy them
    -- They belong to the filer and can have forms in any year

    -- Count active recipients for this filer
    SELECT COUNT(*) INTO v_recipients_copied
    FROM recipients
    WHERE filer_id = p_filer_id AND is_active = true;

    -- Create draft forms for the new year based on previous year's forms
    INSERT INTO forms_1099 (
        filer_id,
        recipient_id,
        operating_year_id,
        form_type,
        status,
        created_by
    )
    SELECT
        frm.filer_id,
        frm.recipient_id,
        v_to_year_id,
        frm.form_type,
        'draft',
        p_user_id
    FROM forms_1099 frm
    WHERE frm.filer_id = p_filer_id
      AND frm.operating_year_id = v_from_year_id
      AND frm.is_correction = false
      AND NOT EXISTS (
          -- Don't create if form already exists for this recipient/year/type
          SELECT 1 FROM forms_1099 existing
          WHERE existing.filer_id = frm.filer_id
            AND existing.recipient_id = frm.recipient_id
            AND existing.operating_year_id = v_to_year_id
            AND existing.form_type = frm.form_type
            AND existing.is_correction = false
      );

    GET DIAGNOSTICS v_forms_created = ROW_COUNT;

    -- Log the activity
    INSERT INTO activity_log (user_id, action, entity_type, entity_id, filer_id, operating_year_id, details)
    VALUES (
        p_user_id,
        'copy_filer_to_new_year',
        'filer',
        p_filer_id,
        p_filer_id,
        v_to_year_id,
        jsonb_build_object(
            'from_year', p_from_year,
            'to_year', p_to_year,
            'recipients_available', v_recipients_copied,
            'forms_created', v_forms_created
        )
    );

    RETURN QUERY SELECT v_recipients_copied, v_forms_created;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================================
-- FUNCTION: Validate Form 1099
-- Validates a single form and updates its status
-- ============================================================================
CREATE OR REPLACE FUNCTION validate_form_1099(p_form_id UUID)
RETURNS JSONB AS $$
DECLARE
    v_form RECORD;
    v_recipient RECORD;
    v_errors TEXT[] := '{}';
    v_result JSONB;
BEGIN
    -- Get form with related data
    SELECT frm.*, f.tin AS filer_tin, f.name AS filer_name
    INTO v_form
    FROM forms_1099 frm
    JOIN filers f ON f.id = frm.filer_id
    WHERE frm.id = p_form_id;

    IF NOT FOUND THEN
        RETURN jsonb_build_object('success', false, 'error', 'Form not found');
    END IF;

    -- Get recipient
    SELECT * INTO v_recipient FROM recipients WHERE id = v_form.recipient_id;

    -- Required field validation
    IF v_recipient.name IS NULL OR LENGTH(TRIM(v_recipient.name)) = 0 THEN
        v_errors := array_append(v_errors, 'Recipient name is required');
    END IF;

    IF v_recipient.tin IS NULL OR LENGTH(REGEXP_REPLACE(v_recipient.tin, '[^0-9]', '', 'g')) != 9 THEN
        v_errors := array_append(v_errors, 'Recipient TIN must be 9 digits');
    END IF;

    IF v_recipient.address1 IS NULL OR LENGTH(TRIM(v_recipient.address1)) = 0 THEN
        v_errors := array_append(v_errors, 'Recipient address is required');
    END IF;

    IF v_recipient.city IS NULL OR LENGTH(TRIM(v_recipient.city)) = 0 THEN
        v_errors := array_append(v_errors, 'Recipient city is required');
    END IF;

    IF v_recipient.state IS NULL OR LENGTH(v_recipient.state) != 2 THEN
        v_errors := array_append(v_errors, 'Recipient state must be 2-letter code');
    END IF;

    IF v_recipient.zip IS NULL OR NOT (v_recipient.zip ~ '^\d{5}(-\d{4})?$') THEN
        v_errors := array_append(v_errors, 'Recipient ZIP must be 5 or 9 digits');
    END IF;

    -- Form-specific validation
    IF v_form.form_type = '1099-NEC' THEN
        IF COALESCE(v_form.nec_box1, 0) <= 0 THEN
            v_errors := array_append(v_errors, '1099-NEC Box 1 (compensation) must be greater than 0');
        END IF;
    ELSIF v_form.form_type = '1099-MISC' THEN
        IF COALESCE(v_form.misc_box1, 0) + COALESCE(v_form.misc_box2, 0) +
           COALESCE(v_form.misc_box3, 0) + COALESCE(v_form.misc_box10, 0) <= 0 THEN
            v_errors := array_append(v_errors, '1099-MISC must have at least one box with amount > 0');
        END IF;
    END IF;

    -- Update form status
    IF array_length(v_errors, 1) > 0 THEN
        UPDATE forms_1099
        SET status = 'validation_error',
            validation_errors = to_jsonb(v_errors),
            validated_at = NOW()
        WHERE id = p_form_id;

        v_result := jsonb_build_object(
            'success', false,
            'status', 'validation_error',
            'errors', v_errors
        );
    ELSE
        UPDATE forms_1099
        SET status = 'validated',
            validation_errors = NULL,
            validated_at = NOW()
        WHERE id = p_form_id;

        v_result := jsonb_build_object(
            'success', true,
            'status', 'validated',
            'errors', '[]'::jsonb
        );
    END IF;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================================
-- FUNCTION: Get Dashboard Stats
-- Returns summary statistics for the dashboard
-- ============================================================================
CREATE OR REPLACE FUNCTION get_dashboard_stats(p_operating_year_id UUID DEFAULT NULL)
RETURNS JSONB AS $$
DECLARE
    v_year_id UUID;
    v_result JSONB;
BEGIN
    -- Use current year if not specified
    IF p_operating_year_id IS NULL THEN
        SELECT id INTO v_year_id FROM operating_years WHERE is_current = true;
    ELSE
        v_year_id := p_operating_year_id;
    END IF;

    SELECT jsonb_build_object(
        'operating_year_id', v_year_id,
        'tax_year', (SELECT tax_year FROM operating_years WHERE id = v_year_id),
        'total_filers', (SELECT COUNT(*) FROM filers WHERE is_active = true),
        'total_recipients', (SELECT COUNT(*) FROM recipients WHERE is_active = true),
        'total_forms', (SELECT COUNT(*) FROM forms_1099 WHERE operating_year_id = v_year_id),
        'forms_by_status', (
            SELECT jsonb_object_agg(status, cnt)
            FROM (
                SELECT status, COUNT(*) as cnt
                FROM forms_1099
                WHERE operating_year_id = v_year_id
                GROUP BY status
            ) s
        ),
        'forms_by_type', (
            SELECT jsonb_object_agg(form_type, cnt)
            FROM (
                SELECT form_type, COUNT(*) as cnt
                FROM forms_1099
                WHERE operating_year_id = v_year_id
                GROUP BY form_type
            ) t
        ),
        'tin_match_summary', (
            SELECT jsonb_build_object(
                'not_checked', COUNT(*) FILTER (WHERE tin_status = 'not_checked'),
                'matched', COUNT(*) FILTER (WHERE tin_status = 'matched'),
                'mismatched', COUNT(*) FILTER (WHERE tin_status = 'mismatched'),
                'pending', COUNT(*) FILTER (WHERE tin_status = 'pending')
            )
            FROM recipients
            WHERE is_active = true
        ),
        'recent_submissions', (
            SELECT COALESCE(jsonb_agg(s ORDER BY s.created_at DESC), '[]'::jsonb)
            FROM (
                SELECT id, status, form_type, total_forms, accepted_count, rejected_count, submitted_at
                FROM submissions
                WHERE operating_year_id = v_year_id
                LIMIT 5
            ) s
        )
    ) INTO v_result;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================================
-- FUNCTION: Safe Delete Check
-- Checks if a filer/recipient can be safely deleted
-- ============================================================================
CREATE OR REPLACE FUNCTION can_delete_filer(p_filer_id UUID)
RETURNS JSONB AS $$
DECLARE
    v_submitted_forms INTEGER;
    v_total_forms INTEGER;
BEGIN
    SELECT
        COUNT(*) FILTER (WHERE status IN ('submitted', 'accepted')),
        COUNT(*)
    INTO v_submitted_forms, v_total_forms
    FROM forms_1099
    WHERE filer_id = p_filer_id;

    IF v_submitted_forms > 0 THEN
        RETURN jsonb_build_object(
            'can_delete', false,
            'reason', 'Filer has ' || v_submitted_forms || ' submitted/accepted forms that cannot be deleted',
            'submitted_forms', v_submitted_forms,
            'total_forms', v_total_forms
        );
    ELSIF v_total_forms > 0 THEN
        RETURN jsonb_build_object(
            'can_delete', true,
            'warning', 'Deleting will also remove ' || v_total_forms || ' draft forms',
            'total_forms', v_total_forms
        );
    ELSE
        RETURN jsonb_build_object(
            'can_delete', true,
            'total_forms', 0
        );
    END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
