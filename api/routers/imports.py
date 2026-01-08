"""
Imports API Router.

Handles Excel/CSV file uploads, column mapping, validation, and promotion.
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel

import sys
sys.path.insert(0, "src")

from import_service import ImportService, auto_map_columns

router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class ImportBatch(BaseModel):
    id: str
    operating_year_id: str
    filer_id: Optional[str]
    filename: str
    file_size: Optional[int]
    status: str
    total_rows: int
    valid_rows: int
    error_rows: int
    warning_rows: int
    column_mapping: Optional[dict]
    uploaded_at: str
    validated_at: Optional[str]
    promoted_at: Optional[str]


class ImportRow(BaseModel):
    id: str
    batch_id: str
    row_number: int
    raw_data: dict
    recipient_name: Optional[str]
    recipient_tin: Optional[str]
    recipient_tin_type: Optional[str]
    recipient_city: Optional[str]
    recipient_state: Optional[str]
    recipient_zip: Optional[str]
    form_type: Optional[str]
    nec_box1: Optional[float]
    status: str
    validation_errors: Optional[List[dict]]


class ColumnMappingRequest(BaseModel):
    mapping: dict  # {source_column: target_field}


class PromoteRequest(BaseModel):
    filer_id: str


class BatchStats(BaseModel):
    valid: int
    errors: int
    warnings: int


class PromoteStats(BaseModel):
    recipients_created: int
    forms_created: int
    skipped: int


class AutoMapResponse(BaseModel):
    suggested_mapping: dict
    unmapped_columns: List[str]
    available_targets: List[str]


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/upload", response_model=ImportBatch, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    operating_year_id: str = Form(...),
    filer_id: Optional[str] = Form(None),
):
    """
    Upload an Excel or CSV file for import.

    Accepts .xlsx, .xls, or .csv files.
    Returns the created batch with auto-detected column mapping suggestions.
    """
    # Validate file type
    filename = file.filename or "upload"
    if not filename.lower().endswith(('.xlsx', '.xls', '.csv')):
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Please upload .xlsx, .xls, or .csv"
        )

    try:
        content = await file.read()
        service = ImportService()

        # Create batch
        batch = service.create_batch(
            operating_year_id=operating_year_id,
            filename=filename,
            file_content=content,
            filer_id=filer_id
        )

        if not batch:
            raise HTTPException(status_code=500, detail="Failed to create import batch")

        # Parse and store raw rows
        df = service.parse_file(content, filename)
        service.store_raw_rows(batch['id'], df)

        # Auto-detect column mapping
        mapping = auto_map_columns(list(df.columns))
        service.apply_column_mapping(batch['id'], mapping)

        # Return updated batch
        return service.get_batch(batch['id'])

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/batches", response_model=List[ImportBatch])
async def list_batches(
    operating_year_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    """List import batches with optional filtering."""
    try:
        service = ImportService()
        query = service.client.table('import_batches').select('*')

        if operating_year_id:
            query = query.eq('operating_year_id', operating_year_id)
        if status:
            query = query.eq('status', status)

        query = query.order('uploaded_at', desc=True).limit(limit)
        return query.execute().data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/batches/{batch_id}", response_model=ImportBatch)
async def get_batch(batch_id: str):
    """Get a single import batch."""
    try:
        service = ImportService()
        batch = service.get_batch(batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")
        return batch
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/batches/{batch_id}/rows", response_model=List[ImportRow])
async def get_batch_rows(
    batch_id: str,
    status: Optional[str] = Query(None, description="Filter by status: pending, valid, error, warning"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Get rows for an import batch."""
    try:
        service = ImportService()
        rows = service.get_batch_rows(batch_id, status=status, limit=limit, offset=offset)
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/batches/{batch_id}/auto-map", response_model=AutoMapResponse)
async def auto_map_batch(batch_id: str):
    """
    Get auto-detected column mapping for a batch.

    Returns suggested mapping, unmapped source columns, and available target fields.
    """
    try:
        service = ImportService()
        batch = service.get_batch(batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")

        # Get first row to see columns
        rows = service.get_batch_rows(batch_id, limit=1)
        if not rows:
            raise HTTPException(status_code=400, detail="Batch has no rows")

        source_columns = list(rows[0]['raw_data'].keys())
        suggested = auto_map_columns(source_columns)

        mapped_sources = set(suggested.keys())
        unmapped = [col for col in source_columns if col not in mapped_sources]

        available_targets = [
            'recipient_name', 'recipient_name_line2', 'recipient_tin',
            'recipient_address1', 'recipient_address2', 'recipient_city',
            'recipient_state', 'recipient_zip', 'recipient_email', 'account_number',
            'nec_box1', 'nec_box2', 'nec_box4',
            'misc_box1', 'misc_box2', 'misc_box3', 'misc_box4', 'misc_box5',
            'misc_box6', 'misc_box7', 'misc_box8', 'misc_box9', 'misc_box10',
            'misc_box11', 'misc_box12', 'misc_box14',
            'state1_code', 'state1_id', 'state1_income', 'state1_withheld',
            'state2_code', 'state2_id', 'state2_income', 'state2_withheld',
        ]

        return AutoMapResponse(
            suggested_mapping=suggested,
            unmapped_columns=unmapped,
            available_targets=available_targets
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/batches/{batch_id}/mapping")
async def set_column_mapping(batch_id: str, request: ColumnMappingRequest):
    """Set or update column mapping for a batch."""
    try:
        service = ImportService()
        batch = service.get_batch(batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")

        service.apply_column_mapping(batch_id, request.mapping)
        return {"message": "Column mapping updated", "mapping": request.mapping}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batches/{batch_id}/validate", response_model=BatchStats)
async def validate_batch(batch_id: str):
    """
    Run validation on all rows in a batch.

    Normalizes data and checks for errors/warnings.
    """
    try:
        service = ImportService()
        batch = service.get_batch(batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")

        if not batch.get('column_mapping'):
            raise HTTPException(status_code=400, detail="Column mapping must be set before validation")

        stats = service.normalize_batch(batch_id)
        return BatchStats(**stats)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batches/{batch_id}/promote", response_model=PromoteStats)
async def promote_batch(batch_id: str, request: PromoteRequest):
    """
    Promote valid rows to recipients and forms_1099 tables.

    Only rows with status='valid' will be promoted.
    """
    try:
        service = ImportService()
        batch = service.get_batch(batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")

        if batch['status'] not in ['validated', 'promoting']:
            raise HTTPException(
                status_code=400,
                detail=f"Batch must be validated before promotion. Current status: {batch['status']}"
            )

        if batch['valid_rows'] == 0:
            raise HTTPException(status_code=400, detail="No valid rows to promote")

        stats = service.promote_batch(batch_id, request.filer_id)
        return PromoteStats(**stats)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/rows/{row_id}")
async def update_row(row_id: str, updates: dict):
    """
    Update a single import row.

    Use this to manually fix validation errors.
    After updating, re-run validation on the batch.
    """
    try:
        service = ImportService()
        # Only allow updating certain fields
        allowed_fields = {
            'recipient_name', 'recipient_tin', 'recipient_address1', 'recipient_address2',
            'recipient_city', 'recipient_state', 'recipient_zip', 'form_type',
            'nec_box1', 'nec_box4', 'misc_box1', 'misc_box2', 'misc_box3', 'misc_box4',
            'misc_box5', 'misc_box6', 'misc_box8', 'misc_box9', 'misc_box10',
            'misc_box11', 'misc_box12', 'misc_box14', 'status'
        }

        filtered = {k: v for k, v in updates.items() if k in allowed_fields}
        if not filtered:
            raise HTTPException(status_code=400, detail="No valid fields to update")

        # Reset status to pending so it gets re-validated
        if 'status' not in filtered:
            filtered['status'] = 'pending'
            filtered['validation_errors'] = None

        result = service.update_row(row_id, filtered)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/batches/{batch_id}")
async def delete_batch(batch_id: str):
    """Delete an import batch and all its rows."""
    try:
        service = ImportService()
        batch = service.get_batch(batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")

        if batch['status'] == 'promoted':
            raise HTTPException(
                status_code=400,
                detail="Cannot delete a promoted batch. The data has already been moved to production tables."
            )

        # Delete rows first (CASCADE should handle this, but be explicit)
        service.client.table('import_rows').delete().eq('batch_id', batch_id).execute()
        service.client.table('import_batches').delete().eq('id', batch_id).execute()

        return {"message": "Batch deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
