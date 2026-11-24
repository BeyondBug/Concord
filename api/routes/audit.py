"""Audit log query — reads the durable audit trail from core.persistence."""
from fastapi import APIRouter, Queryfrom pydantic import BaseModelfrom core.persistence import get_storerouter = APIRouter(prefix="/audit", tags=["audit"])


class AuditEntryOut(BaseModel):
    finding_id: str
    path: str
    reason: str
    agent: str | None
    correlation_id: str
    timestamp: str


class AuditList(BaseModel):
    entries: list[AuditEntryOut]
    total: int


@router.get("/", response_model=AuditList)
async def list_audit(limit: int = Query(100, ge=1, le=1000),
                     finding_id: str | None = Query(None, max_length=200)):
    store = get_store()
    entries = (store.audit_for_finding(finding_id)[::-1] if finding_id
               else store.list_audit(limit=limit))[:limit]
    return {"entries": entries, "total": len(entries)}
