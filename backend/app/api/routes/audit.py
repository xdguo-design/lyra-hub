from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.domain.applications.models import AuditEvent
from app.infrastructure.database import AuditEventRecord, Database

router = APIRouter(prefix="/audit", tags=["audit"])


def get_database() -> Database:
    raise RuntimeError("Database dependency was not configured")


@router.get("/events", response_model=list[AuditEvent])
def list_audit_events(
    limit: int = Query(default=50, ge=1, le=200),
    database: Database = Depends(get_database),
) -> list[AuditEvent]:
    with database.session() as session:
        records = session.scalars(
            select(AuditEventRecord).order_by(AuditEventRecord.id.desc()).limit(limit)
        ).all()
        return [
            AuditEvent(
                id=record.id,
                action=record.action,
                target_type=record.target_type,
                target_id=record.target_id,
                payload=record.payload,
                created_at=record.created_at,
            )
            for record in records
        ]
