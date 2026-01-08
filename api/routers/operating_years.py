"""
Operating Years API Router.

Manages tax year configuration.
"""

from typing import List
from fastapi import APIRouter, HTTPException

import sys
sys.path.insert(0, "src")

from supabase_client import (
    get_operating_years,
    get_current_operating_year,
    set_current_operating_year,
)
from api.schemas import OperatingYear, OperatingYearUpdate, MessageResponse

router = APIRouter()


@router.get("/", response_model=List[OperatingYear])
async def list_operating_years():
    """Get all operating years, ordered by tax year descending."""
    try:
        years = get_operating_years()
        return years
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/current", response_model=OperatingYear)
async def get_current_year():
    """Get the current operating year."""
    try:
        year = get_current_operating_year()
        if not year:
            raise HTTPException(status_code=404, detail="No current operating year set")
        return year
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{year_id}/set-current", response_model=MessageResponse)
async def set_current_year(year_id: str):
    """Set the specified year as the current operating year."""
    try:
        result = set_current_operating_year(year_id)
        if not result:
            raise HTTPException(status_code=404, detail="Operating year not found")
        return MessageResponse(message=f"Operating year set as current")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
