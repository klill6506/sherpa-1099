"""
Filers API Router.

Manages payer/filer entities (companies filing 1099s).
"""

from typing import List
from fastapi import APIRouter, HTTPException, Query

import sys
sys.path.insert(0, "src")

from supabase_client import (
    get_filers,
    get_filer,
    create_filer,
    update_filer,
    delete_filer,
    log_activity,
)
from api.schemas import Filer, FilerCreate, FilerUpdate, MessageResponse

router = APIRouter()


@router.get("/", response_model=List[Filer])
async def list_filers(active_only: bool = Query(True, description="Filter to active filers only")):
    """Get all filers."""
    try:
        filers = get_filers(active_only=active_only)
        return filers
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{filer_id}", response_model=Filer)
async def get_filer_by_id(filer_id: str):
    """Get a single filer by ID."""
    try:
        filer = get_filer(filer_id)
        if not filer:
            raise HTTPException(status_code=404, detail="Filer not found")
        return filer
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _normalize_filer_data(data: dict) -> dict:
    """Normalize form field names to database column names."""
    # Fields to map from form names to DB names
    field_mappings = {
        'name_line2': 'name_line_2',
        'contact_phone': 'phone',
        'contact_email': 'email',
    }
    # Fields to skip (form aliases that shouldn't be passed to DB)
    skip_fields = set(field_mappings.keys())

    result = {}
    for k, v in data.items():
        # Skip None and empty strings
        if v is None or v == '':
            continue
        # Map form field names to DB column names
        if k in field_mappings:
            result[field_mappings[k]] = v
        elif k not in skip_fields:
            result[k] = v
    return result


@router.post("/", response_model=Filer, status_code=201)
async def create_new_filer(filer_data: FilerCreate):
    """Create a new filer."""
    try:
        # Normalize field names from form to database
        data = _normalize_filer_data(filer_data.model_dump())

        # Debug: log what we're sending to the database
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Creating filer with data: {data}")

        filer = create_filer(data)
        if not filer:
            raise HTTPException(status_code=400, detail="Failed to create filer - no data returned")

        # Log activity
        log_activity(
            action="filer_created",
            entity_type="filer",
            entity_id=filer["id"],
            filer_id=filer["id"],
            details={"name": filer["name"]},
        )

        return filer
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.exception(f"Error creating filer: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{filer_id}", response_model=Filer)
async def update_existing_filer(filer_id: str, filer_data: FilerUpdate):
    """Update an existing filer."""
    try:
        # Normalize field names and filter out None values
        update_data = _normalize_filer_data(filer_data.model_dump())
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")

        filer = update_filer(filer_id, update_data)
        if not filer:
            raise HTTPException(status_code=404, detail="Filer not found")

        log_activity(
            action="filer_updated",
            entity_type="filer",
            entity_id=filer_id,
            filer_id=filer_id,
            details={"updated_fields": list(update_data.keys())},
        )

        return filer
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{filer_id}", response_model=MessageResponse)
async def deactivate_filer(filer_id: str):
    """Soft-delete a filer (sets is_active to false)."""
    try:
        filer = delete_filer(filer_id)
        if not filer:
            raise HTTPException(status_code=404, detail="Filer not found")

        log_activity(
            action="filer_deactivated",
            entity_type="filer",
            entity_id=filer_id,
            filer_id=filer_id,
        )

        return MessageResponse(message="Filer deactivated successfully")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
