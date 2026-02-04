-- Migration 013: Add nec_box3 (Golden Parachute Payments) to forms_1099
-- Box 3 is rarely used but required for commercial release
-- Run this in Supabase SQL Editor

-- Add nec_box3 column to forms_1099 table
ALTER TABLE forms_1099 ADD COLUMN IF NOT EXISTS nec_box3 NUMERIC(12,2) DEFAULT 0;

-- Add comment for documentation
COMMENT ON COLUMN forms_1099.nec_box3 IS 'Box 3: Other income (Golden parachute payments, excess golden parachute payments)';
