-- Migration 011: ATS Submissions table
-- Stores original ATS test submission data so corrections can properly reference them

CREATE TABLE IF NOT EXISTS public.ats_submissions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,

    -- IRS Response Data
    receipt_id TEXT NOT NULL,                    -- IRS-assigned receipt ID (e.g., "2025-68698468914-b0b2da138")
    transmission_id TEXT NOT NULL,               -- Unique Transmission ID (UTID) (e.g., "49c5c09b...::A")

    -- Submission Details
    form_type TEXT NOT NULL,                     -- 1099NEC, 1099MISC, 1099S, 1098
    tax_year INTEGER NOT NULL,
    submission_count INTEGER NOT NULL DEFAULT 5, -- Number of issuers (usually 5 for ATS)
    recipient_count INTEGER NOT NULL DEFAULT 10, -- Number of recipients (usually 10 for ATS)

    -- CF/SF Details
    cfsf_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    cfsf_state TEXT,                             -- State code if CF/SF enabled

    -- Status tracking
    status TEXT NOT NULL DEFAULT 'submitted',    -- submitted, accepted, rejected, partially_accepted
    irs_message TEXT,                            -- IRS response message

    -- Submission type
    submission_type TEXT NOT NULL DEFAULT 'original', -- original or correction
    original_submission_id UUID,                 -- For corrections, references the original

    -- Record sequence info (for building UniqueRecordId in corrections)
    -- For ATS with 5 issuers x 2 recipients = 10 records
    -- Record format per IRS: {ReceiptId}|{SubmissionSequence}|{RecordSequence}
    record_map JSONB,                            -- Maps recipient_idx to submission_seq/record_seq

    -- Timestamps
    submitted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    status_checked_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Foreign key for corrections
    CONSTRAINT fk_original_submission
        FOREIGN KEY (original_submission_id)
        REFERENCES public.ats_submissions(id)
        ON DELETE SET NULL
);

-- Index for quick lookups
CREATE INDEX IF NOT EXISTS idx_ats_submissions_receipt_id ON public.ats_submissions(receipt_id);
CREATE INDEX IF NOT EXISTS idx_ats_submissions_status ON public.ats_submissions(status);
CREATE INDEX IF NOT EXISTS idx_ats_submissions_form_type ON public.ats_submissions(form_type);
CREATE INDEX IF NOT EXISTS idx_ats_submissions_tax_year ON public.ats_submissions(tax_year);

-- Grant permissions
GRANT SELECT, INSERT, UPDATE ON public.ats_submissions TO anon, authenticated, service_role;

-- Add comment
COMMENT ON TABLE public.ats_submissions IS 'Stores ATS test submission history for correction reference. Receipt ID and record mapping allow corrections to properly reference original submissions.';
