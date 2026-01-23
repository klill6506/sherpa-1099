# ATS Certification Progress

## Status: COMPLETE ✅

Both original and corrected submissions have been accepted by the IRS ATS (Assurance Testing System).

---

## Successful Test Submissions

| Type | Receipt ID | Status |
|------|------------|--------|
| Original | `2025-68698468914-b0b2da138` | Accepted |
| Correction | `2025-68934943854-5e8e457a6` | Accepted |
| CF/SF (AZ) | `2025-69209066354-3c172e642` | Accepted |

---

## Issues Fixed During Certification

### 1. UniqueRecordId Format (Correction Submissions)

**Problem:** The `UniqueRecordId` field in correction submissions was using the UTID format instead of the Receipt ID format.

**Wrong format:**
```
49c5c09b-xxxx-xxxx-xxxx-xxxxxxxxxxxx::A|1|1
```

**Correct format:**
```
2025-68698468914-b0b2da138|1|1
```

**Fix location:** `server/tax_filing/irs_submission.py` in the `_build_form_1099nec_record()` method

**Fix:** Changed the `UniqueRecordId` construction to use `original_receipt_id` instead of building from submission UTID:
```python
if form.is_corrected and original_receipt_id:
    unique_record_id = f"{original_receipt_id}|1|1"
```

### 2. TransmissionTypeCd for Corrections

**Problem:** The `TransmissionTypeCd` was hardcoded to "O" (Original) even for correction submissions.

**Fix location:** `server/tax_filing/irs_submission.py` in the `build_irs_xml()` method

**Fix:** Added logic to detect if any form is a correction and set the appropriate transmission type:
```python
has_corrections = any(form.is_corrected for form in forms)
transmission_type = "C" if has_corrections else "O"
```

---

## Key Files Modified

- `server/tax_filing/irs_submission.py` - XML generation logic for IRS submissions

---

## CF/SF (Combined Federal/State Filing) Test

### Status: COMPLETE ✅

CF/SF test submission accepted! Receipt ID: `2025-69209066354-3c172e642`

### How CF/SF Testing Works

1. On the ATS Test page, check "Enable CF/SF Test (Combined Federal/State Filing)"
2. Select a CF/SF participating state (default: AZ - Arizona)
3. Submit the ATS test - Issuer #5 (Epsilon) will include:
   - `CFSFElectionInd = "1"` at the submission header level
   - `CFSFElectionStateCd` at the form detail level
   - `StateLocalTaxGrp` with state withholding/income data

### CF/SF Schema Elements

Per IRS IRIS TY2025 v1.2 schemas:

| Element | Level | Description |
|---------|-------|-------------|
| `CFSFElectionInd` | Submission Header | "0" or "1" indicating CF/SF participation |
| `CFSFElectionStateCd` | Form Detail | Array of 2-letter state codes (max 62) |
| `StateLocalTaxGrp` | Form Detail | Contains state/local tax withholding info |

### Supported Form Types for CF/SF

- **1099-NEC** ✅
- **1099-MISC** ✅
- 1099-S ❌ (does not participate in CF/SF)
- 1098 ❌ (does not participate in CF/SF)

### After CF/SF Acceptance

Per Pub 5719, the IRS Help Desk may request the "Submission ID for CF/SF, if applicable" when reviewing your certification. The CF/SF submission index (Issuer #5) is displayed in the submission results.

---

## Next Steps

1. **Production Filing** - With ATS certification complete, the system is ready for production 1099-NEC filings
2. **Documentation** - Update any internal documentation about the correction workflow
3. **Monitoring** - Set up monitoring for production submission status tracking

### Important Note on CF/SF States

Texas (TX) is **NOT** a CF/SF participating state. Valid states per IRS error SHAREDIRFORM019_002:
> AL, AZ, AR, CA, CT, CO, DC, DE, GA, HI, ID, IN, KS, LA, MA, MD, ME, MI, MN, MS, MT, NE, NJ, NM, NC, ND, OH, OK, OR, PA, RI, SC, WI

---

## Reference: IRS ATS Correction Requirements

For corrections to be accepted:
- `TransmissionTypeCd` must be "C" (not "O")
- `UniqueRecordId` must reference the original submission's Receipt ID in format: `{ReceiptId}|{SubmissionSeqNum}|{RecordSeqNum}`
- `CorrectedInd` must be "1" on the corrected form records

---

*Last updated: January 23, 2026*
