-- Sherpa 1099 Database Migration
-- Migration 004: Multi-Tenant Support
-- Run this in Supabase SQL Editor
--
-- This migration adds tenant isolation to support multiple client companies.
-- Each tenant (your customers) can have multiple users working on their data.

-- ============================================================================
-- TENANTS TABLE
-- These are your customers/client companies who use Sherpa 1099
-- ============================================================================
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,

    -- Optional business info
    contact_email TEXT,
    contact_phone TEXT,

    -- Subscription/billing (for future use)
    plan TEXT DEFAULT 'standard' CHECK (plan IN ('trial', 'standard', 'professional', 'enterprise')),
    is_active BOOLEAN NOT NULL DEFAULT true,

    -- Audit
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tenants_active ON tenants (is_active) WHERE is_active = true;

-- ============================================================================
-- TENANT_MEMBERS TABLE
-- Links users to tenants with role-based access
-- ============================================================================
CREATE TABLE tenant_members (
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- Role determines what the user can do
    role TEXT NOT NULL CHECK (role IN ('admin', 'staff', 'readonly')) DEFAULT 'staff',

    -- Audit
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    invited_by UUID REFERENCES auth.users(id),

    PRIMARY KEY (tenant_id, user_id)
);

CREATE INDEX idx_tenant_members_user ON tenant_members (user_id);
CREATE INDEX idx_tenant_members_tenant ON tenant_members (tenant_id);

-- ============================================================================
-- ADD TENANT_ID TO EXISTING TABLES
-- ============================================================================

-- Filers
ALTER TABLE filers ADD COLUMN tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE;
CREATE INDEX idx_filers_tenant ON filers (tenant_id);

-- Recipients (inherits tenant through filer, but adding for direct queries)
ALTER TABLE recipients ADD COLUMN tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE;
CREATE INDEX idx_recipients_tenant ON recipients (tenant_id);

-- Forms
ALTER TABLE forms_1099 ADD COLUMN tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE;
CREATE INDEX idx_forms_1099_tenant ON forms_1099 (tenant_id);

-- Submissions
ALTER TABLE submissions ADD COLUMN tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE;
CREATE INDEX idx_submissions_tenant ON submissions (tenant_id);

-- Import batches
ALTER TABLE import_batches ADD COLUMN tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE;
CREATE INDEX idx_import_batches_tenant ON import_batches (tenant_id);

-- Import history
ALTER TABLE import_history ADD COLUMN tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE;
CREATE INDEX idx_import_history_tenant ON import_history (tenant_id);

-- Activity log
ALTER TABLE activity_log ADD COLUMN tenant_id UUID REFERENCES tenants(id) ON DELETE SET NULL;
CREATE INDEX idx_activity_log_tenant ON activity_log (tenant_id);

-- ============================================================================
-- HELPER FUNCTION: Get user's tenant IDs
-- Used in RLS policies to check tenant membership
-- ============================================================================
CREATE OR REPLACE FUNCTION get_user_tenant_ids()
RETURNS SETOF UUID
LANGUAGE sql
SECURITY DEFINER
STABLE
AS $$
    SELECT tenant_id
    FROM tenant_members
    WHERE user_id = auth.uid()
$$;

-- ============================================================================
-- HELPER FUNCTION: Check if user is admin of a tenant
-- ============================================================================
CREATE OR REPLACE FUNCTION is_tenant_admin(check_tenant_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
STABLE
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM tenant_members
        WHERE tenant_id = check_tenant_id
        AND user_id = auth.uid()
        AND role = 'admin'
    )
$$;

-- ============================================================================
-- AUTO-UPDATE TRIGGER FOR TENANTS
-- ============================================================================
CREATE TRIGGER update_tenants_updated_at BEFORE UPDATE ON tenants
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- CREATE DEFAULT TENANT FOR EXISTING DATA
-- Run this section to migrate existing data to a default tenant
-- ============================================================================

-- Create a default tenant for The Tax Shelter (your company)
INSERT INTO tenants (id, name, contact_email, plan)
VALUES (
    'a0000000-0000-0000-0000-000000000001',  -- Fixed UUID for easy reference
    'The Tax Shelter',
    'admin@thetaxshelter.com',
    'professional'
);

-- Migrate existing filers to default tenant
UPDATE filers SET tenant_id = 'a0000000-0000-0000-0000-000000000001' WHERE tenant_id IS NULL;

-- Migrate existing recipients to default tenant
UPDATE recipients SET tenant_id = 'a0000000-0000-0000-0000-000000000001' WHERE tenant_id IS NULL;

-- Migrate existing forms to default tenant
UPDATE forms_1099 SET tenant_id = 'a0000000-0000-0000-0000-000000000001' WHERE tenant_id IS NULL;

-- Migrate existing submissions to default tenant
UPDATE submissions SET tenant_id = 'a0000000-0000-0000-0000-000000000001' WHERE tenant_id IS NULL;

-- Migrate existing import_batches to default tenant
UPDATE import_batches SET tenant_id = 'a0000000-0000-0000-0000-000000000001' WHERE tenant_id IS NULL;

-- Migrate existing import_history to default tenant
UPDATE import_history SET tenant_id = 'a0000000-0000-0000-0000-000000000001' WHERE tenant_id IS NULL;

-- ============================================================================
-- MAKE TENANT_ID NOT NULL AFTER MIGRATION
-- Only run this after verifying all data has been migrated
-- ============================================================================

-- Uncomment and run after migration is verified:
-- ALTER TABLE filers ALTER COLUMN tenant_id SET NOT NULL;
-- ALTER TABLE recipients ALTER COLUMN tenant_id SET NOT NULL;
-- ALTER TABLE forms_1099 ALTER COLUMN tenant_id SET NOT NULL;
-- ALTER TABLE submissions ALTER COLUMN tenant_id SET NOT NULL;
-- ALTER TABLE import_batches ALTER COLUMN tenant_id SET NOT NULL;
-- ALTER TABLE import_history ALTER COLUMN tenant_id SET NOT NULL;
