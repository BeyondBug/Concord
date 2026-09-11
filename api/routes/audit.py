"""Audit log query — reads the durable audit trail from core.persistence."""
from fastapi import APIRouter

from core.persistence import get_store

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/")
async def list_audit(limit: int = 100):
    entries = get_store().list_audit(limit=limit)
    return {"entries": entries, "total": len(entries)}