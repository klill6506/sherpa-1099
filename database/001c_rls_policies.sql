-- Sherpa 1099 Database Schema
-- Migration 001c: Row Level Security Policies
-- Run this THIRD in Supabase SQL Editor (after 001b)

-- ============================================================================
-- ENABLE RLS ON ALL TABLES
-- ============================================================================
ALTER TABLE operating_years ENABLE ROW LEVEL SECURITY;
ALTER TABLE filers ENABLE ROW LEVEL SECURITY;
ALTER TABLE recipients ENABLE ROW LEVEL SECURITY;
ALTER TABLE forms_1099 ENABLE ROW LEVEL SECURITY;
ALTER TABLE submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE tin_match_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- POLICIES: Operating Years - All authenticated users can access
-- ============================================================================
CREATE POLICY "Users can view operating years" ON operating_years FOR SELECT TO authenticated USING (true);
CREATE POLICY "Users can insert operating years" ON operating_years FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "Users can update operating years" ON operating_years FOR UPDATE TO authenticated USING (true);

-- ============================================================================
-- POLICIES: Filers - All authenticated users have full access
-- ============================================================================
CREATE POLICY "Users can view filers" ON filers FOR SELECT TO authenticated USING (true);
CREATE POLICY "Users can create filers" ON filers FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "Users can update filers" ON filers FOR UPDATE TO authenticated USING (true);
CREATE POLICY "Users can delete filers" ON filers FOR DELETE TO authenticated USING (true);

-- ============================================================================
-- POLICIES: Recipients
-- ============================================================================
CREATE POLICY "Users can view recipients" ON recipients FOR SELECT TO authenticated USING (true);
CREATE POLICY "Users can create recipients" ON recipients FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "Users can update recipients" ON recipients FOR UPDATE TO authenticated USING (true);
CREATE POLICY "Users can delete recipients" ON recipients FOR DELETE TO authenticated USING (true);

-- ============================================================================
-- POLICIES: Forms 1099
-- ============================================================================
CREATE POLICY "Users can view forms" ON forms_1099 FOR SELECT TO authenticated USING (true);
CREATE POLICY "Users can create forms" ON forms_1099 FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "Users can update forms" ON forms_1099 FOR UPDATE TO authenticated USING (true);
CREATE POLICY "Users can delete forms" ON forms_1099 FOR DELETE TO authenticated USING (true);

-- ============================================================================
-- POLICIES: Submissions
-- ============================================================================
CREATE POLICY "Users can view submissions" ON submissions FOR SELECT TO authenticated USING (true);
CREATE POLICY "Users can create submissions" ON submissions FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "Users can update submissions" ON submissions FOR UPDATE TO authenticated USING (true);

-- ============================================================================
-- POLICIES: TIN Match Log
-- ============================================================================
CREATE POLICY "Users can view tin match log" ON tin_match_log FOR SELECT TO authenticated USING (true);
CREATE POLICY "Users can create tin match entries" ON tin_match_log FOR INSERT TO authenticated WITH CHECK (true);

-- ============================================================================
-- POLICIES: Activity Log
-- ============================================================================
CREATE POLICY "Users can view activity log" ON activity_log FOR SELECT TO authenticated USING (true);
CREATE POLICY "Users can create activity entries" ON activity_log FOR INSERT TO authenticated WITH CHECK (true);

-- ============================================================================
-- POLICIES: Import History
-- ============================================================================
CREATE POLICY "Users can view import history" ON import_history FOR SELECT TO authenticated USING (true);
CREATE POLICY "Users can create import entries" ON import_history FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "Users can update import entries" ON import_history FOR UPDATE TO authenticated USING (true);

-- ============================================================================
-- POLICIES: User Profiles - Users can only see/edit their own
-- ============================================================================
CREATE POLICY "Users can view own profile" ON user_profiles FOR SELECT TO authenticated USING (auth.uid() = id);
CREATE POLICY "Users can update own profile" ON user_profiles FOR UPDATE TO authenticated USING (auth.uid() = id);
CREATE POLICY "Users can insert own profile" ON user_profiles FOR INSERT TO authenticated WITH CHECK (auth.uid() = id);
