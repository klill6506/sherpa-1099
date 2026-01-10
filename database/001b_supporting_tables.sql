-- Sherpa 1099 Database Schema
-- Migration 001b: Supporting Tables
-- Run this SECOND in Supabase SQL Editor (after 001a)

-- ============================================================================
-- TIN_MATCH_LOG (History of TIN Matching Requests)
-- ============================================================================
CREATE TABLE tin_match_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_id UUID NOT NULL REFERENCES recipients(id) ON DELETE CASCADE,
    tin_submitted TEXT NOT NULL,
    name_submitted TEXT NOT NULL,
    match_code TEXT NOT NULL,
    match_result TEXT NOT NULL CHECK (match_result IN ('matched', 'mismatched', 'unavailable')),
    irs_response JSONB,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    checked_by UUID REFERENCES auth.users(id)
);

CREATE INDEX idx_tin_match_log_recipient ON tin_match_log (recipient_id);
CREATE INDEX idx_tin_match_log_date ON tin_match_log (checked_at);

-- ============================================================================
-- ACTIVITY_LOG (Audit Trail)
-- ============================================================================
CREATE TABLE activity_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id),
    user_email TEXT,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id UUID,
    filer_id UUID REFERENCES filers(id) ON DELETE SET NULL,
    operating_year_id UUID REFERENCES operating_years(id) ON DELETE SET NULL,
    details JSONB,
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_activity_log_user ON activity_log (user_id);
CREATE INDEX idx_activity_log_action ON activity_log (action);
CREATE INDEX idx_activity_log_entity ON activity_log (entity_type, entity_id);
CREATE INDEX idx_activity_log_filer ON activity_log (filer_id);
CREATE INDEX idx_activity_log_date ON activity_log (created_at);

-- ============================================================================
-- IMPORT_HISTORY (Track Data Imports)
-- ============================================================================
CREATE TABLE import_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filer_id UUID NOT NULL REFERENCES filers(id) ON DELETE CASCADE,
    operating_year_id UUID NOT NULL REFERENCES operating_years(id),
    filename TEXT NOT NULL,
    file_hash TEXT,
    file_size INTEGER,
    records_imported INTEGER NOT NULL DEFAULT 0,
    records_updated INTEGER NOT NULL DEFAULT 0,
    records_skipped INTEGER NOT NULL DEFAULT 0,
    errors JSONB,
    status TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('completed', 'partial', 'failed', 'rolled_back')),
    rolled_back_at TIMESTAMPTZ,
    rolled_back_by UUID REFERENCES auth.users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id)
);

CREATE INDEX idx_import_history_filer ON import_history (filer_id);
CREATE INDEX idx_import_history_year ON import_history (operating_year_id);
CREATE INDEX idx_import_history_hash ON import_history (file_hash);

-- ============================================================================
-- USER PROFILES (Extends Supabase Auth)
-- ============================================================================
CREATE TABLE user_profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    full_name TEXT,
    avatar_url TEXT,
    default_operating_year_id UUID REFERENCES operating_years(id),
    preferences JSONB DEFAULT '{}'::jsonb,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user', 'readonly')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- TRIGGERS: Auto-update updated_at
-- ============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

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
-- FUNCTION: Create user profile on signup
-- ============================================================================
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.user_profiles (id, full_name, role)
    VALUES (
        NEW.id,
        COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.email),
        'user'
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
