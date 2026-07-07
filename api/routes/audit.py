"""Audit log query."""
from fastapi import APIRouter

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/")
async def list_audit(limit: int = 50):
    # TODO Phase 1: query PostgreSQL audit table
    return {"entries": [], "total": 0}
