"""
Recipients API Router.

Manages payees (individuals/companies receiving 1099s).
"""

from typing import List
from fastapi import APIRouter, HTTPException, Query

import sys
sys.path.insert(0, "src")

from supabase_client import (
    get_recipients,
    get_recipient,
    create_recipient,
    update_recipient,
    update_recipient_tin_status,
    log_activity,
)
from api.schemas import (
    Recipient,
    RecipientCreate,
    RecipientUpdate,
    RecipientTINUpdate,
    MessageResponse,
)

router = APIRouter()


@router.get("/", response_model=List[Recipient])
async def list_recipients(
    filer_id: str = Query(..., description="Filer ID to get recipients for"),
    active_only: bool = Query(True, description="Filter to active recipients only"),
):
    """Get all recipients for a filer."""
    try:
        recipients = get_recipients(filer_id, active_only=active_only)
        return recipients
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{recipient_id}", response_model=Recipient)
async def get_recipient_by_id(recipient_id: str):
    """Get a single recipient by ID."""
    try:
        recipient = get_recipient(recipient_id)
        if not recipient:
            raise HTTPException(status_code=404, detail="Recipient not found")
        return recipient
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=Recipient, status_code=201)
async def create_new_recipient(recipient_data: RecipientCreate):
    """Create a new recipient."""
    try:
        recipient = create_recipient(recipient_data.model_dump())
        if not recipient:
            raise HTTPException(status_code=400, detail="Failed to create recipient")

        log_activity(
            action="recipient_created",
            entity_type="recipient",
            entity_id=recipient["id"],
            filer_id=recipient["filer_id"],
            details={"name": recipient["name"]},
        )

        return recipient
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{recipient_id}", response_model=Recipient)
async def update_existing_recipient(recipient_id: str, recipient_data: RecipientUpdate):
    """Update an existing recipient."""
    try:
        update_data = {k: v for k, v in recipient_data.model_dump().items() if v is not None}
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")

        recipient = update_recipient(recipient_id, update_data)
        if not recipient:
            raise HTTPException(status_code=404, detail="Recipient not found")

        log_activity(
            action="recipient_updated",
            entity_type="recipient",
            entity_id=recipient_id,
            filer_id=recipient.get("filer_id"),
            details={"updated_fields": list(update_data.keys())},
        )

        return recipient
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{recipient_id}/tin-status", response_model=Recipient)
async def update_tin_status(recipient_id: str, tin_data: RecipientTINUpdate):
    """Update TIN matching status for a recipient."""
    try:
        recipient = update_recipient_tin_status(
            recipient_id,
            status=tin_data.tin_status,
            match_code=tin_data.tin_match_code,
        )
        if not recipient:
            raise HTTPException(status_code=404, detail="Recipient not found")

        log_activity(
            action="tin_status_updated",
            entity_type="recipient",
            entity_id=recipient_id,
            details={"status": tin_data.tin_status, "match_code": tin_data.tin_match_code},
        )

        return recipient
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{recipient_id}", response_model=MessageResponse)
async def deactivate_recipient(recipient_id: str):
    """Soft-delete a recipient (sets is_active to false)."""
    try:
        update_data = {"is_active": False}
        recipient = update_recipient(recipient_id, update_data)
        if not recipient:
            raise HTTPException(status_code=404, detail="Recipient not found")

        log_activity(
            action="recipient_deactivated",
            entity_type="recipient",
            entity_id=recipient_id,
            filer_id=recipient.get("filer_id"),
        )

        return MessageResponse(message="Recipient deactivated successfully")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
