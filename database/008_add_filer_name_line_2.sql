-- Migration 008: Add name_line_2 column to filers table
-- This allows filers to have a second name line (e.g., DBA or attention line)
-- Run this in Supabase SQL Editor

-- Add name_line_2 column to filers table
ALTER TABLE filers ADD COLUMN IF NOT EXISTS name_line_2 TEXT;

-- Add comment for documentation
COMMENT ON COLUMN filers.name_line_2 IS 'Second line of filer name (e.g., DBA, attention, or continuation of name)';
