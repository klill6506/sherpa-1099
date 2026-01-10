# Sherpa 1099 Database Schema

## Overview

This directory contains the SQL migration files for the Sherpa 1099 Supabase database.

## Migration Files

Run these in order in the Supabase SQL Editor:

1. **001_initial_schema.sql** - Core tables, indexes, and triggers
2. **002_fix_references_and_rls.sql** - Foreign key fixes and Row Level Security policies
3. **003_views_and_functions.sql** - Views, helper functions, and dashboard stats

## Entity Relationship Diagram

```
┌─────────────────┐       ┌──────────────────┐
│ operating_years │       │  user_profiles   │
│─────────────────│       │──────────────────│
│ id (PK)         │       │ id (PK, FK→auth) │
│ tax_year        │       │ full_name        │
│ status          │       │ role             │
│ is_current      │       │ preferences      │
└────────┬────────┘       └──────────────────┘
         │
         │ 1:N
         ▼
┌─────────────────┐
│     filers      │ ◄──────────────────────────────────────┐
│─────────────────│                                         │
│ id (PK)         │                                         │
│ name            │                                         │
│ tin             │      ┌──────────────────┐               │
│ address...      │      │   submissions    │               │
│ is_active       │      │──────────────────│               │
└────────┬────────┘      │ id (PK)          │               │
         │               │ operating_year_id │◄──────────────┤
         │ 1:N           │ form_type        │               │
         ▼               │ status           │               │
┌─────────────────┐      │ total_forms      │               │
│   recipients    │      │ iris_submission_id│              │
│─────────────────│      └────────┬─────────┘               │
│ id (PK)         │               │                         │
│ filer_id (FK)   │───────────────┼─────────────────────────┘
│ name            │               │
│ tin             │               │ N:1
│ tin_status      │               │
│ address...      │      ┌────────▼─────────┐
│ is_active       │      │   forms_1099     │
└────────┬────────┘      │──────────────────│
         │               │ id (PK)          │
         │ 1:N           │ filer_id (FK)    │◄─── filers
         │               │ recipient_id (FK)│◄─── recipients
         └──────────────►│ operating_year_id│◄─── operating_years
                         │ form_type        │
                         │ status           │
                         │ nec_box1...      │
                         │ misc_box1...     │
                         │ submission_id(FK)│───► submissions
                         └──────────────────┘

Supporting Tables:
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  tin_match_log  │  │  activity_log   │  │ import_history  │
│─────────────────│  │─────────────────│  │─────────────────│
│ recipient_id(FK)│  │ user_id (FK)    │  │ filer_id (FK)   │
│ match_code      │  │ action          │  │ filename        │
│ match_result    │  │ entity_type     │  │ file_hash       │
│ checked_at      │  │ entity_id       │  │ records_imported│
└─────────────────┘  │ details (JSONB) │  │ status          │
                     └─────────────────┘  └─────────────────┘
```

## Key Tables

### operating_years
Tracks tax years (2024, 2025, etc.) and their status.
- Only one year can be `is_current = true`
- Status: `open`, `closed`, `archived`

### filers
Your clients - the companies/people who pay contractors and need to file 1099s.
- Contains payer information for the 1099 forms
- `is_active` allows soft-delete

### recipients
People/companies receiving 1099s (contractors, vendors, etc.)
- Linked to a filer (your client)
- TIN matching status tracked here
- Same recipient can have forms across multiple years

### forms_1099
The actual 1099 forms - one record per form per year.
- Links filer → recipient → operating_year
- Supports 1099-NEC and 1099-MISC (expandable)
- Status workflow: draft → validated → ready → submitted → accepted/rejected
- Unique constraint prevents duplicate forms (same recipient/year/type)

### submissions
Batch submissions to IRS IRIS.
- Groups forms submitted together
- Tracks IRS response and acceptance counts

### tin_match_log
Audit trail of all TIN matching requests.
- Keeps history even if recipient TIN changes
- Stores IRS response codes

### activity_log
Comprehensive audit trail of all actions.
- Who did what, when, to what entity
- Useful for compliance and debugging

### import_history
Tracks file imports to prevent accidental overwrites.
- Stores file hash to detect duplicate imports
- Can roll back imports if needed

## Views

### filer_status_summary
Dashboard view showing:
- Total recipients and forms per filer per year
- Released vs unreleased counts
- Overall status (draft, has_errors, ready_to_submit, complete)

### recipient_tin_status
Recipients with their TIN matching status and days since last check.

### forms_ready_for_submission
All validated forms ready to submit to IRS.

## Functions

### copy_filer_to_new_year(filer_id, from_year, to_year)
Safely creates draft forms for a new tax year based on previous year.
- Prevents duplicates
- Logs the action

### validate_form_1099(form_id)
Validates a single form and updates its status.
- Checks required fields
- Validates TIN format, state codes, ZIP codes
- Form-specific amount validation

### get_dashboard_stats(operating_year_id)
Returns summary statistics for the dashboard as JSONB:
- Total filers, recipients, forms
- Forms by status and type
- TIN match summary
- Recent submissions

### can_delete_filer(filer_id)
Checks if a filer can be safely deleted.
- Blocks deletion if submitted/accepted forms exist
- Warns about draft forms that will be deleted

## Row Level Security

All tables have RLS enabled. Current policies allow all authenticated users full access (single-tenant mode).

For multi-tenant SaaS, update policies to filter by organization/tenant ID.

## Triggers

- `update_*_updated_at` - Automatically updates `updated_at` timestamp on all tables
- `on_auth_user_created` - Creates user_profile when new user signs up

## Initial Data

Migration 001 creates:
- Tax year 2024 (current, open)
- Tax year 2023 (closed)
