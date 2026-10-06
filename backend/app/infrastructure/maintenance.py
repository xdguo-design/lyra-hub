from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.database import (
    Database,
    MaintenanceAlertRecord,
    MaintenanceCheckRecord,
    MaintenanceRepairAuditRecord,
    MaintenanceScheduleRecord,
    MaintenanceWorkerLeaseRecord,
)


class LeaseLostError(RuntimeError):
    """Raised when a worker attempts to write after losing its lease."""


def _json(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


class MaintenanceStore:
    """Persistence boundary for Hub maintenance schedules, outcomes, alerts and leases."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def save_schedule(
        self,
        *,
        schedule_id: str,
        service_id: str,
        interval_seconds: int,
        enabled: bool,
        next_run_at: datetime,
        lease_name: str | None = None,
        owner_id: str | None = None,
        lease_now: datetime | None = None,
    ) -> MaintenanceScheduleRecord:
        if interval_seconds < 1:
            raise ValueError("interval_seconds must be positive")
        _validate_lease_fence(lease_name, owner_id)
        with self.database.session() as session, session.begin():
            if lease_name is not None:
                self._fence_worker_lease(session, lease_name, owner_id, lease_now)
            record = session.get(MaintenanceScheduleRecord, schedule_id)
            if record is None:
                record = MaintenanceScheduleRecord(
                    schedule_id=schedule_id,
                    service_id=service_id,
                    interval_seconds=interval_seconds,
                    enabled=enabled,
                    next_run_at=next_run_at,
                )
                session.add(record)
            else:
                record.service_id = service_id
                record.interval_seconds = interval_seconds
                record.enabled = enabled
                record.next_run_at = next_run_at
            session.flush()
            return record

    def get_schedule(self, schedule_id: str) -> MaintenanceScheduleRecord | None:
        with self.database.session() as session:
            return session.get(MaintenanceScheduleRecord, schedule_id)

    def list_schedules(self, *, enabled: bool | None = None) -> list[MaintenanceScheduleRecord]:
        with self.database.session() as session:
            statement = select(MaintenanceScheduleRecord).order_by(MaintenanceScheduleRecord.schedule_id)
            if enabled is not None:
                statement = statement.where(MaintenanceScheduleRecord.enabled.is_(enabled))
            return list(session.scalars(statement))

    def record_check(
        self,
        *,
        check_id: str,
        schedule_id: str | None,
        service_id: str,
        check_name: str,
        status: str,
        checked_at: datetime,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
        lease_name: str | None = None,
        owner_id: str | None = None,
        lease_now: datetime | None = None,
        advance_schedule: bool = True,
    ) -> MaintenanceCheckRecord:
        _validate_lease_fence(lease_name, owner_id)
        with self.database.session() as session, session.begin():
            if lease_name is not None:
                self._fence_worker_lease(session, lease_name, owner_id, lease_now)
            record = MaintenanceCheckRecord(
                check_id=check_id,
                schedule_id=schedule_id,
                service_id=service_id,
                check_name=check_name,
                status=status,
                error_code=error_code,
                details_json=_json(details),
                checked_at=checked_at,
            )
            session.add(record)
            session.flush()
            if schedule_id is not None and advance_schedule:
                schedule = session.get(MaintenanceScheduleRecord, schedule_id)
                if schedule is not None:
                    schedule.last_run_at = checked_at
                    schedule.next_run_at = checked_at + timedelta(seconds=schedule.interval_seconds)
            return record

    def complete_schedule_cycle(
        self,
        *,
        schedule_id: str,
        completed_at: datetime,
        lease_name: str | None = None,
        owner_id: str | None = None,
        lease_now: datetime | None = None,
    ) -> MaintenanceScheduleRecord | None:
        """Advance a schedule only after its entire maintenance cycle commits."""
        _validate_lease_fence(lease_name, owner_id)
        with self.database.session() as session, session.begin():
            if lease_name is not None:
                self._fence_worker_lease(session, lease_name, owner_id, lease_now)
            schedule = session.get(MaintenanceScheduleRecord, schedule_id)
            if schedule is None:
                return None
            schedule.last_run_at = completed_at
            schedule.next_run_at = completed_at + timedelta(seconds=schedule.interval_seconds)
            session.flush()
            return schedule

    def list_checks(
        self,
        *,
        service_id: str | None = None,
        limit: int = 100,
    ) -> list[MaintenanceCheckRecord]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        with self.database.session() as session:
            statement = select(MaintenanceCheckRecord).order_by(MaintenanceCheckRecord.checked_at.desc())
            if service_id is not None:
                statement = statement.where(MaintenanceCheckRecord.service_id == service_id)
            return list(session.scalars(statement.limit(limit)))

    def upsert_alert(
        self,
        *,
        fingerprint: str,
        service_id: str,
        check_name: str,
        error_code: str,
        severity: str,
        check_id: str,
        occurred_at: datetime,
        consecutive_failures: int,
        lease_name: str | None = None,
        owner_id: str | None = None,
        lease_now: datetime | None = None,
    ) -> MaintenanceAlertRecord:
        if consecutive_failures < 1:
            raise ValueError("consecutive_failures must be positive")
        _validate_lease_fence(lease_name, owner_id)
        try:
            with self.database.session() as session, session.begin():
                if lease_name is not None:
                    self._fence_worker_lease(session, lease_name, owner_id, lease_now)
                record = session.scalar(
                    select(MaintenanceAlertRecord).where(MaintenanceAlertRecord.fingerprint == fingerprint)
                )
                if record is None:
                    record = MaintenanceAlertRecord(
                        fingerprint=fingerprint,
                        service_id=service_id,
                        check_name=check_name,
                        error_code=error_code,
                        severity=severity,
                        status="open",
                        first_check_id=check_id,
                        last_check_id=check_id,
                        consecutive_failures=consecutive_failures,
                        first_occurred_at=occurred_at,
                        last_occurred_at=occurred_at,
                    )
                    session.add(record)
                    session.flush()
                else:
                    record = self._atomic_merge_alert(
                        session,
                        fingerprint=fingerprint,
                        service_id=service_id,
                        check_name=check_name,
                        error_code=error_code,
                        severity=severity,
                        check_id=check_id,
                        occurred_at=occurred_at,
                        consecutive_failures=consecutive_failures,
                    )
                return record
        except IntegrityError:
            # Another worker inserted this fingerprint after our read. The failed
            # transaction is rolled back before re-reading and merging the result.
            with self.database.session() as session, session.begin():
                if lease_name is not None:
                    self._fence_worker_lease(session, lease_name, owner_id, lease_now)
                record = self._atomic_merge_alert(
                    session,
                    fingerprint=fingerprint,
                    service_id=service_id,
                    check_name=check_name,
                    error_code=error_code,
                    severity=severity,
                    check_id=check_id,
                    occurred_at=occurred_at,
                    consecutive_failures=consecutive_failures,
                )
                if record is None:
                    raise
                return record

    @staticmethod
    def _atomic_merge_alert(
        session: Session,
        *,
        fingerprint: str,
        service_id: str,
        check_name: str,
        error_code: str,
        severity: str,
        check_id: str,
        occurred_at: datetime,
        consecutive_failures: int,
    ) -> MaintenanceAlertRecord | None:
        alert = MaintenanceAlertRecord
        was_resolved = alert.status == "resolved"
        session.execute(
            update(alert)
            .where(
                and_(
                    alert.fingerprint == fingerprint,
                    alert.last_occurred_at <= occurred_at,
                    or_(alert.status != "resolved", alert.resolved_at.is_(None), alert.resolved_at < occurred_at),
                )
            )
            .values(
                status=case((was_resolved, "open"), else_=alert.status),
                first_check_id=case((was_resolved, check_id), else_=alert.first_check_id),
                first_occurred_at=case((was_resolved, occurred_at), else_=alert.first_occurred_at),
                acknowledged_by=case((was_resolved, None), else_=alert.acknowledged_by),
                acknowledged_at=case((was_resolved, None), else_=alert.acknowledged_at),
                resolved_at=case((was_resolved, None), else_=alert.resolved_at),
                service_id=service_id,
                check_name=check_name,
                error_code=error_code,
                severity=severity,
                last_check_id=check_id,
                recovery_check_id=None,
                consecutive_failures=consecutive_failures,
                last_occurred_at=occurred_at,
            )
            .execution_options(synchronize_session=False)
        )
        return session.scalar(
            select(alert)
            .where(alert.fingerprint == fingerprint)
            .execution_options(populate_existing=True)
        )

    def resolve_alert(
        self,
        *,
        fingerprint: str,
        check_id: str,
        resolved_at: datetime,
        lease_name: str | None = None,
        owner_id: str | None = None,
        lease_now: datetime | None = None,
    ) -> MaintenanceAlertRecord | None:
        _validate_lease_fence(lease_name, owner_id)
        with self.database.session() as session, session.begin():
            if lease_name is not None:
                self._fence_worker_lease(session, lease_name, owner_id, lease_now)
            alert = MaintenanceAlertRecord
            session.execute(
                update(alert)
                .where(
                    alert.fingerprint == fingerprint,
                    alert.status != "resolved",
                    alert.last_occurred_at <= resolved_at,
                )
                .values(status="resolved", recovery_check_id=check_id, resolved_at=resolved_at)
                .execution_options(synchronize_session=False)
            )
            return session.scalar(select(alert).where(alert.fingerprint == fingerprint))

    def list_alerts(self, *, status: str | None = None, limit: int = 100) -> list[MaintenanceAlertRecord]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        with self.database.session() as session:
            statement = select(MaintenanceAlertRecord).order_by(MaintenanceAlertRecord.last_occurred_at.desc())
            if status is not None:
                statement = statement.where(MaintenanceAlertRecord.status == status)
            return list(session.scalars(statement.limit(limit)))

    def record_repair_audit(
        self,
        *,
        audit_id: str,
        actor_id: str,
        action: str,
        service_id: str,
        target_revision: int | None,
        result: str,
        occurred_at: datetime,
        details: dict[str, Any] | None = None,
    ) -> MaintenanceRepairAuditRecord:
        with self.database.session() as session, session.begin():
            record = MaintenanceRepairAuditRecord(
                id=audit_id,
                actor_id=actor_id,
                action=action,
                service_id=service_id,
                target_revision=target_revision,
                result=result,
                details_json=_json(details),
                occurred_at=occurred_at,
            )
            session.add(record)
            session.flush()
            return record

    def list_repair_audits(self, *, limit: int = 100) -> list[MaintenanceRepairAuditRecord]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        with self.database.session() as session:
            statement = select(MaintenanceRepairAuditRecord).order_by(
                MaintenanceRepairAuditRecord.occurred_at.desc(), MaintenanceRepairAuditRecord.id.desc()
            )
            return list(session.scalars(statement.limit(limit)))

    def acquire_worker_lease(
        self,
        *,
        lease_name: str,
        owner_id: str,
        now: datetime | None = None,
        lease_seconds: int = 60,
    ) -> bool:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        now = now or datetime.now(UTC)
        expires_at = now + timedelta(seconds=lease_seconds)
        with self.database.session() as session:
            try:
                with session.begin():
                    result = session.execute(
                        update(MaintenanceWorkerLeaseRecord)
                        .where(
                            MaintenanceWorkerLeaseRecord.lease_name == lease_name,
                            or_(
                                MaintenanceWorkerLeaseRecord.expires_at <= now,
                                MaintenanceWorkerLeaseRecord.owner_id == owner_id,
                            ),
                        )
                        .values(owner_id=owner_id, acquired_at=now, expires_at=expires_at)
                    )
                    if result.rowcount:
                        return True
                    if session.get(MaintenanceWorkerLeaseRecord, lease_name) is not None:
                        return False
                    session.add(
                        MaintenanceWorkerLeaseRecord(
                            lease_name=lease_name,
                            owner_id=owner_id,
                            acquired_at=now,
                            expires_at=expires_at,
                        )
                    )
                    session.flush()
                    return True
            except IntegrityError:
                # Another worker created the lease after our initial conditional update.
                return False

    def release_worker_lease(self, *, lease_name: str, owner_id: str) -> bool:
        with self.database.session() as session, session.begin():
            result = session.execute(
                update(MaintenanceWorkerLeaseRecord)
                .where(
                    MaintenanceWorkerLeaseRecord.lease_name == lease_name,
                    MaintenanceWorkerLeaseRecord.owner_id == owner_id,
                )
                .values(expires_at=datetime.now(UTC))
            )
            return bool(result.rowcount)

    def renew_worker_lease(
        self,
        *,
        lease_name: str,
        owner_id: str,
        now: datetime | None = None,
        lease_seconds: int = 60,
    ) -> bool:
        """Extend an active lease held by owner_id; expired leases require reacquisition."""
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        now = now or datetime.now(UTC)
        with self.database.session() as session, session.begin():
            result = session.execute(
                update(MaintenanceWorkerLeaseRecord)
                .where(
                    MaintenanceWorkerLeaseRecord.lease_name == lease_name,
                    MaintenanceWorkerLeaseRecord.owner_id == owner_id,
                    MaintenanceWorkerLeaseRecord.expires_at > now,
                )
                .values(expires_at=now + timedelta(seconds=lease_seconds))
            )
            return bool(result.rowcount)

    @staticmethod
    def _fence_worker_lease(
        session: Session,
        lease_name: str,
        owner_id: str | None,
        now: datetime | None,
    ) -> None:
        # SQLite acquires its write lock on this conditional UPDATE and holds it
        # until the business write in the same transaction commits.
        statement = update(MaintenanceWorkerLeaseRecord).where(
            MaintenanceWorkerLeaseRecord.lease_name == lease_name,
            MaintenanceWorkerLeaseRecord.owner_id == owner_id,
        )
        if now is None:
            from sqlalchemy import func

            statement = statement.where(MaintenanceWorkerLeaseRecord.expires_at > func.current_timestamp())
        else:
            statement = statement.where(MaintenanceWorkerLeaseRecord.expires_at > now)
        result = session.execute(statement.values(expires_at=MaintenanceWorkerLeaseRecord.expires_at))
        if result.rowcount != 1:
            raise LeaseLostError(f"worker lease {lease_name!r} is no longer active for this owner")


def _validate_lease_fence(lease_name: str | None, owner_id: str | None) -> None:
    if (lease_name is None) != (owner_id is None):
        raise ValueError("lease_name and owner_id must be provided together")
