# Session Notes - 2026-01-17

## Summary
Fixed IRS IRIS ATS (Assurance Testing System) submission errors. Test submission now ACCEPTED.

## Problem
ATS test submissions were returning:
1. "Not Found" when checking status by UTID
2. "Rejected" with XML schema validation errors

## Root Causes Found & Fixed

### 1. Receipt ID Parsing (lowercase)
**Issue:** IRS returns `<receiptId>` (lowercase 'r') with no namespace, but we were looking for `<irs:ReceiptId>` (Pascal case with namespace).

**Fix:** `src/iris_client.py` - Look for `receiptId` first (line ~576)

### 2. UTID Suffix (A/U not T/P)
**Issue:** We used `::T` for test and `::P` for production, but IRS schema requires:
- `::A` = ATS (test)
- `::U` = Production

**Fix:** `src/iris_xml_generator.py` - `_generate_utid()` method (line ~1050)

### 3. TINSubmittedTypeCd (BUSINESS_TIN not EIN)
**Issue:** We sent `EIN` but IRS schema requires enumeration values:
- `BUSINESS_TIN` (for EIN)
- `INDIVIDUAL_TIN` (for SSN, ITIN, ATIN)
- `UNKNOWN`

**Fix:** `src/iris_xml_generator.py` - `_get_tin_type_code()` method (line ~347)

### 4. RecordId Format (integers only)
**Issue:** We used compound IDs like `1-1`, `2-1`, but IRS requires pattern `[1-9][0-9]*` (simple integers starting from 1).

**Fix:** `api/routers/efile.py` - ATS test endpoint, line ~1827

### 5. Status Response Parsing
**Issue:** IRS uses `TransmissionStatusCd` not `StatusCd`, and errors are in `ErrorInformationGrp` structure.

**Fix:** `src/iris_client.py` - `_parse_status_response()` and `_extract_form_errors()` methods

## Successful ATS Test Results

**Receipt ID:** `2025-68698468914-b0b2da138`
**Transmission ID:** `49c5c09b-c0c5-466f-9eb3-9b3921af09a9:IRIS:DG5BW::A`
**Status:** ACCEPTED

## New Debug Endpoints Added

- `GET /api/efile/ats-test/last-submit-response` - Raw IRS submit response (persisted to file)
- `GET /api/efile/check-ack-debug/{receipt_id}` - Raw IRS acknowledgment XML

## Files Modified

- `src/iris_client.py` - Response parsing, error extraction, persistent logging
- `src/iris_xml_generator.py` - UTID format, TIN type codes
- `api/routers/efile.py` - RecordId format, debug endpoints
- `logs/last_irs_response.json` - NEW (persisted debug data)

## Key Learnings

1. **Always check IRS schema** - The actual XML elements often differ from documentation examples
2. **Case sensitivity matters** - `receiptId` vs `ReceiptId`
3. **Namespaces vary** - Intake response has `xmlns=""` (empty), Status response uses `urn:us:gov:treasury:irs:ir`
4. **Enumeration values** - IRS uses specific strings, not abbreviations (BUSINESS_TIN not EIN)

## Next Steps for Production

1. IRS will confirm ATS certification passed
2. For production: set `is_test=False` (will use `::U` suffix)
3. Store Receipt ID as primary key for status tracking
4. UTID is internal reference; Receipt ID is what IRS indexes
