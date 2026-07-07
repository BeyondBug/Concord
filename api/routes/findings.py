"""Findings endpoints."""
from fastapi import APIRouter

router = APIRouter(prefix="/findings", tags=["findings"])


@router.get("/")
async def list_findings():
    # TODO Phase 1: query PostgreSQL findings table
    return {"findings": [], "total": 0}
