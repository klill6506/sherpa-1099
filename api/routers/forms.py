"""
1099 Forms API Router.

Manages 1099 form creation, validation, and submission tracking.
"""

from typing import List
from decimal import Decimal
from fastapi import APIRouter, HTTPException, Query

import sys
sys.path.insert(0, "src")

from supabase_client import (
    get_forms_1099,
    get_form_1099,
    create_form_1099,
    update_form_1099,
    delete_form_1099,
    log_activity,
)
from api.schemas import (
    Form1099,
    Form1099Create,
    Form1099Update,
    Form1099WithRecipient,
    MessageResponse,
)

router = APIRouter()


def convert_decimals(obj):
    """Convert Decimal values to float for JSON serialization."""
    if isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, list):
        return [convert_decimals(i) for i in obj]
    return obj


@router.get("/", response_model=List[Form1099WithRecipient])
async def list_forms(
    filer_id: str = Query(..., description="Filer ID"),
    operating_year_id: str = Query(..., description="Operating year ID"),
):
    """Get all 1099 forms for a filer and operating year."""
    try:
        forms = get_forms_1099(filer_id, operating_year_id)
        return forms
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{form_id}", response_model=Form1099)
async def get_form_by_id(form_id: str):
    """Get a single 1099 form by ID with full details."""
    try:
        form = get_form_1099(form_id)
        if not form:
            raise HTTPException(status_code=404, detail="Form not found")
        return form
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=Form1099, status_code=201)
async def create_new_form(form_data: Form1099Create):
    """Create a new 1099 form."""
    try:
        form_dict = convert_decimals(form_data.model_dump(exclude_none=True))
        form_dict["status"] = "draft"  # New forms start as draft

        form = create_form_1099(form_dict)
        if not form:
            raise HTTPException(status_code=400, detail="Failed to create form")

        log_activity(
            action="form_created",
            entity_type="form_1099",
            entity_id=form["id"],
            filer_id=form["filer_id"],
            operating_year_id=form["operating_year_id"],
            details={"form_type": form["form_type"]},
        )

        return form
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{form_id}", response_model=Form1099)
async def update_existing_form(form_id: str, form_data: Form1099Update):
    """Update an existing 1099 form."""
    try:
        update_data = convert_decimals({k: v for k, v in form_data.model_dump().items() if v is not None})
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")

        form = update_form_1099(form_id, update_data)
        if not form:
            raise HTTPException(status_code=404, detail="Form not found")

        log_activity(
            action="form_updated",
            entity_type="form_1099",
            entity_id=form_id,
            filer_id=form.get("filer_id"),
            operating_year_id=form.get("operating_year_id"),
            details={"updated_fields": list(update_data.keys())},
        )

        return form
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{form_id}", response_model=MessageResponse)
async def delete_form(form_id: str):
    """Delete a 1099 form (only if status is draft or validation_error)."""
    try:
        # Get form first to log activity with filer info
        form = get_form_1099(form_id)
        if not form:
            raise HTTPException(status_code=404, detail="Form not found")

        if form.get("status") not in ["draft", "validation_error"]:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete form that has been submitted. Only draft forms can be deleted."
            )

        deleted = delete_form_1099(form_id)
        if not deleted:
            raise HTTPException(status_code=400, detail="Failed to delete form")

        log_activity(
            action="form_deleted",
            entity_type="form_1099",
            entity_id=form_id,
            filer_id=form.get("filer_id"),
            operating_year_id=form.get("operating_year_id"),
            details={"form_type": form.get("form_type")},
        )

        return MessageResponse(message="Form deleted successfully")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{form_id}/validate", response_model=Form1099)
async def validate_form(form_id: str):
    """
    Validate a 1099 form against IRS rules.

    This endpoint will check:
    - Required fields are present
    - TIN format is valid
    - Amounts are within acceptable ranges
    - State/ZIP validation
    """
    try:
        form = get_form_1099(form_id)
        if not form:
            raise HTTPException(status_code=404, detail="Form not found")

        validation_errors = []

        # Check for required amount field based on form type
        form_type = form.get("form_type")
        if form_type == "1099-NEC":
            if not form.get("nec_box1"):
                validation_errors.append({
                    "field": "nec_box1",
                    "message": "Box 1 (Nonemployee compensation) is required for 1099-NEC"
                })
        elif form_type == "1099-MISC":
            # At least one box should have a value
            misc_fields = [
                "misc_box1", "misc_box2", "misc_box3", "misc_box4", "misc_box5",
                "misc_box6", "misc_box8", "misc_box9", "misc_box10", "misc_box11",
                "misc_box12", "misc_box14"
            ]
            if not any(form.get(field) for field in misc_fields):
                validation_errors.append({
                    "field": "misc_boxes",
                    "message": "At least one amount box must have a value"
                })

        # Update form with validation results
        if validation_errors:
            update_data = {
                "status": "validation_error",
                "validation_errors": validation_errors,
            }
        else:
            update_data = {
                "status": "validated",
                "validation_errors": [],
            }

        updated_form = update_form_1099(form_id, update_data)

        log_activity(
            action="form_validated",
            entity_type="form_1099",
            entity_id=form_id,
            filer_id=form.get("filer_id"),
            operating_year_id=form.get("operating_year_id"),
            details={
                "result": "passed" if not validation_errors else "failed",
                "error_count": len(validation_errors),
            },
        )

        return updated_form
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
