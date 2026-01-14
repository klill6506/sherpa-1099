-- Sherpa 1099 Database Migration
-- Migration 005: Tenant-Based RLS Policies
-- Run this in Supabase SQL Editor AFTER migration 004_tenants.sql
--
-- These policies ensure users can only see data belonging to their tenant(s).

-- ============================================================================
-- ENABLE RLS ON ALL TABLES
-- ============================================================================
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE filers ENABLE ROW LEVEL SECURITY;
ALTER TABLE recipients ENABLE ROW LEVEL SECURITY;
ALTER TABLE forms_1099 ENABLE ROW LEVEL SECURITY;
ALTER TABLE submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity_log ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- DROP EXISTING POLICIES (if any exist)
-- ============================================================================
DROP POLICY IF EXISTS "tenant_isolation" ON tenants;
DROP POLICY IF EXISTS "tenant_isolation" ON tenant_members;
DROP POLICY IF EXISTS "tenant_isolation" ON filers;
DROP POLICY IF EXISTS "tenant_isolation" ON recipients;
DROP POLICY IF EXISTS "tenant_isolation" ON forms_1099;
DROP POLICY IF EXISTS "tenant_isolation" ON submissions;
DROP POLICY IF EXISTS "tenant_isolation" ON import_batches;
DROP POLICY IF EXISTS "tenant_isolation" ON import_history;
DROP POLICY IF EXISTS "tenant_isolation" ON activity_log;

-- ============================================================================
-- TENANTS TABLE POLICIES
-- Users can only see tenants they belong to
-- ============================================================================
CREATE POLICY "tenant_isolation" ON tenants
FOR ALL TO authenticated
USING (
    id IN (SELECT get_user_tenant_ids())
);

-- ============================================================================
-- TENANT_MEMBERS TABLE POLICIES
-- Users can see members of tenants they belong to
-- Only admins can add/remove members
-- ============================================================================
CREATE POLICY "tenant_isolation" ON tenant_members
FOR SELECT TO authenticated
USING (
    tenant_id IN (SELECT get_user_tenant_ids())
);

CREATE POLICY "tenant_admin_manage_members" ON tenant_members
FOR INSERT TO authenticated
WITH CHECK (
    is_tenant_admin(tenant_id)
);

CREATE POLICY "tenant_admin_delete_members" ON tenant_members
FOR DELETE TO authenticated
USING (
    is_tenant_admin(tenant_id)
);

-- ============================================================================
-- FILERS TABLE POLICIES
-- Users can access filers belonging to their tenant(s)
-- ============================================================================
CREATE POLICY "tenant_isolation" ON filers
FOR ALL TO authenticated
USING (
    tenant_id IN (SELECT get_user_tenant_ids())
)
WITH CHECK (
    tenant_id IN (SELECT get_user_tenant_ids())
);

-- ============================================================================
-- RECIPIENTS TABLE POLICIES
-- Users can access recipients belonging to their tenant(s)
-- ============================================================================
CREATE POLICY "tenant_isolation" ON recipients
FOR ALL TO authenticated
USING (
    tenant_id IN (SELECT get_user_tenant_ids())
)
WITH CHECK (
    tenant_id IN (SELECT get_user_tenant_ids())
);

-- ============================================================================
-- FORMS_1099 TABLE POLICIES
-- Users can access forms belonging to their tenant(s)
-- ============================================================================
CREATE POLICY "tenant_isolation" ON forms_1099
FOR ALL TO authenticated
USING (
    tenant_id IN (SELECT get_user_tenant_ids())
)
WITH CHECK (
    tenant_id IN (SELECT get_user_tenant_ids())
);

-- ============================================================================
-- SUBMISSIONS TABLE POLICIES
-- Users can access submissions belonging to their tenant(s)
-- ============================================================================
CREATE POLICY "tenant_isolation" ON submissions
FOR ALL TO authenticated
USING (
    tenant_id IN (SELECT get_user_tenant_ids())
)
WITH CHECK (
    tenant_id IN (SELECT get_user_tenant_ids())
);

-- ============================================================================
-- IMPORT_BATCHES TABLE POLICIES
-- Users can access import batches belonging to their tenant(s)
-- ============================================================================
CREATE POLICY "tenant_isolation" ON import_batches
FOR ALL TO authenticated
USING (
    tenant_id IN (SELECT get_user_tenant_ids())
)
WITH CHECK (
    tenant_id IN (SELECT get_user_tenant_ids())
);

-- ============================================================================
-- IMPORT_HISTORY TABLE POLICIES
-- Users can access import history belonging to their tenant(s)
-- ============================================================================
CREATE POLICY "tenant_isolation" ON import_history
FOR ALL TO authenticated
USING (
    tenant_id IN (SELECT get_user_tenant_ids())
)
WITH CHECK (
    tenant_id IN (SELECT get_user_tenant_ids())
);

-- ============================================================================
-- ACTIVITY_LOG TABLE POLICIES
-- Users can view activity logs for their tenant(s)
-- Insert is allowed for logging (but must specify tenant_id)
-- ============================================================================
CREATE POLICY "tenant_isolation" ON activity_log
FOR SELECT TO authenticated
USING (
    tenant_id IN (SELECT get_user_tenant_ids())
);

CREATE POLICY "tenant_insert_log" ON activity_log
FOR INSERT TO authenticated
WITH CHECK (
    tenant_id IN (SELECT get_user_tenant_ids())
);

-- ============================================================================
-- OPERATING_YEARS TABLE POLICIES
-- Operating years are global (shared across all tenants)
-- All authenticated users can view them
-- ============================================================================
DROP POLICY IF EXISTS "authenticated_read_operating_years" ON operating_years;

CREATE POLICY "authenticated_read_operating_years" ON operating_years
FOR SELECT TO authenticated
USING (true);

-- Only service role can modify operating years
-- (No INSERT/UPDATE/DELETE policies for authenticated users)
