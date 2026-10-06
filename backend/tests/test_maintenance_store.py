from __future__ import annotations

from datetime import UTC, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event as ThreadEvent

import pytest
from sqlalchemy import event

from app.infrastructure.database import Database
from app.infrastructure.maintenance import MaintenanceStore


def test_maintenance_store_persists_schedules_and_check_results(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'maintenance.db'}")
    database.initialize()
    store = MaintenanceStore(database)
    now = datetime.now(UTC)

    store.save_schedule(
        schedule_id="default",
        service_id="gateway",
        interval_seconds=300,
        enabled=True,
        next_run_at=now + timedelta(minutes=5),
    )
    store.record_check(
        check_id="check-1",
        schedule_id="default",
        service_id="gateway",
        check_name="model_catalog",
        status="healthy",
        checked_at=now,
        details={"model_count": 2},
    )

    assert store.get_schedule("default").service_id == "gateway"
    checks = store.list_checks(service_id="gateway")
    assert len(checks) == 1
    assert checks[0].details == {"model_count": 2}
    assert checks[0].status == "healthy"


def test_alert_fingerprint_upserts_and_recovery_resolves_same_alert(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'alerts.db'}")
    database.initialize()
    store = MaintenanceStore(database)
    first_seen = datetime.now(UTC)

    first = store.upsert_alert(
        fingerprint="gateway:model_catalog:TIMEOUT",
        service_id="gateway",
        check_name="model_catalog",
        error_code="TIMEOUT",
        severity="warning",
        check_id="check-1",
        occurred_at=first_seen,
        consecutive_failures=2,
    )
    updated = store.upsert_alert(
        fingerprint="gateway:model_catalog:TIMEOUT",
        service_id="gateway",
        check_name="model_catalog",
        error_code="TIMEOUT",
        severity="critical",
        check_id="check-2",
        occurred_at=first_seen + timedelta(minutes=5),
        consecutive_failures=3,
    )

    assert updated.id == first.id
    assert updated.first_occurred_at == first_seen
    assert updated.last_check_id == "check-2"
    assert updated.consecutive_failures == 3
    assert len(store.list_alerts()) == 1

    recovered = store.resolve_alert(
        fingerprint="gateway:model_catalog:TIMEOUT",
        check_id="check-3",
        resolved_at=first_seen + timedelta(minutes=10),
    )
    assert recovered is not None
    assert recovered.status == "resolved"
    assert recovered.recovery_check_id == "check-3"
    assert len(store.list_alerts()) == 1


def test_concurrent_first_alert_insert_conflict_is_merged(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'concurrent-alerts.db'}")
    database.initialize()
    store = MaintenanceStore(database)
    first_insert_barrier = Barrier(2)

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:
        if statement.lstrip().upper().startswith("INSERT INTO MAINTENANCE_ALERT"):
            first_insert_barrier.wait(timeout=5)

    event.listen(database.engine, "before_cursor_execute", before_cursor_execute)
    occurred_at = datetime.now(UTC)

    def create(check_id: str, offset: int) -> None:
        store.upsert_alert(
            fingerprint="agents:agent_catalog:TIMEOUT",
            service_id="agents",
            check_name="agent_catalog",
            error_code="TIMEOUT",
            severity="warning",
            check_id=check_id,
            occurred_at=occurred_at + timedelta(seconds=offset),
            consecutive_failures=offset + 1,
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(create, "check-old", 0), executor.submit(create, "check-new", 1)]
            for future in futures:
                future.result(timeout=10)
    finally:
        event.remove(database.engine, "before_cursor_execute", before_cursor_execute)

    alerts = store.list_alerts()
    assert len(alerts) == 1
    assert alerts[0].last_check_id == "check-new"
    assert alerts[0].consecutive_failures == 2
    assert alerts[0].last_occurred_at == occurred_at + timedelta(seconds=1)


def test_stale_concurrent_failure_cannot_overwrite_newer_alert_state(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'concurrent-update-alerts.db'}")
    database.initialize()
    store = MaintenanceStore(database)
    happened = datetime.now(UTC)
    store.upsert_alert(
        fingerprint="gateway:models:TIMEOUT",
        service_id="gateway",
        check_name="models",
        error_code="TIMEOUT",
        severity="warning",
        check_id="check-initial",
        occurred_at=happened,
        consecutive_failures=1,
    )
    stale_update_waiting = ThreadEvent()
    newest_update_committed = ThreadEvent()

    def order_updates(conn, cursor, statement, parameters, context, executemany) -> None:
        if statement.lstrip().upper().startswith("UPDATE MAINTENANCE_ALERT") and "check-old" in str(parameters):
            stale_update_waiting.set()
            assert newest_update_committed.wait(timeout=5)

    event.listen(database.engine, "before_cursor_execute", order_updates)
    later = happened + timedelta(minutes=2)

    def old_failure() -> None:
        store.upsert_alert(
            fingerprint="gateway:models:TIMEOUT",
            service_id="gateway",
            check_name="models",
            error_code="TIMEOUT",
            severity="warning",
            check_id="check-old",
            occurred_at=happened + timedelta(minutes=1),
            consecutive_failures=2,
        )

    def new_failure() -> None:
        store.upsert_alert(
            fingerprint="gateway:models:TIMEOUT",
            service_id="gateway",
            check_name="models",
            error_code="TIMEOUT",
            severity="critical",
            check_id="check-new",
            occurred_at=later,
            consecutive_failures=3,
        )
        newest_update_committed.set()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            old_future = executor.submit(old_failure)
            assert stale_update_waiting.wait(timeout=5)
            executor.submit(new_failure).result(timeout=10)
            old_future.result(timeout=10)
    finally:
        event.remove(database.engine, "before_cursor_execute", order_updates)

    latest = store.list_alerts()[0]
    assert latest.last_occurred_at == later
    assert latest.last_check_id == "check-new"
    assert latest.consecutive_failures == 3


def test_stale_recovery_cannot_resolve_concurrent_newer_failure(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'interleaved-recovery-alert.db'}")
    database.initialize()
    store = MaintenanceStore(database)
    happened = datetime.now(UTC)
    store.upsert_alert(
        fingerprint="agents:catalog:UNAVAILABLE",
        service_id="agents",
        check_name="catalog",
        error_code="UNAVAILABLE",
        severity="warning",
        check_id="check-initial",
        occurred_at=happened,
        consecutive_failures=1,
    )
    recovery_waiting = ThreadEvent()
    newest_failure_committed = ThreadEvent()

    def order_updates(conn, cursor, statement, parameters, context, executemany) -> None:
        if statement.lstrip().upper().startswith("UPDATE MAINTENANCE_ALERT") and "check-late-recovery" in str(
            parameters
        ):
            recovery_waiting.set()
            assert newest_failure_committed.wait(timeout=5)

    event.listen(database.engine, "before_cursor_execute", order_updates)
    latest_failure_at = happened + timedelta(minutes=2)

    def stale_recovery() -> None:
        store.resolve_alert(
            fingerprint="agents:catalog:UNAVAILABLE",
            check_id="check-late-recovery",
            resolved_at=happened + timedelta(minutes=1),
        )

    def new_failure() -> None:
        store.upsert_alert(
            fingerprint="agents:catalog:UNAVAILABLE",
            service_id="agents",
            check_name="catalog",
            error_code="UNAVAILABLE",
            severity="critical",
            check_id="check-new-failure",
            occurred_at=latest_failure_at,
            consecutive_failures=2,
        )
        newest_failure_committed.set()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            recovery_future = executor.submit(stale_recovery)
            assert recovery_waiting.wait(timeout=5)
            executor.submit(new_failure).result(timeout=10)
            recovery_future.result(timeout=10)
    finally:
        event.remove(database.engine, "before_cursor_execute", order_updates)

    latest = store.list_alerts()[0]
    assert latest.status == "open"
    assert latest.last_check_id == "check-new-failure"
    assert latest.last_occurred_at == latest_failure_at
    assert latest.recovery_check_id is None


@pytest.mark.parametrize("status", ["acknowledged", "action_pending", "ignored"])
def test_repeated_failure_preserves_active_alert_status_and_acknowledgement(tmp_path, status: str) -> None:
    database = Database(f"sqlite:///{tmp_path / f'{status}.db'}")
    database.initialize()
    store = MaintenanceStore(database)
    happened = datetime.now(UTC)
    alert = store.upsert_alert(
        fingerprint="print:health:UNAVAILABLE",
        service_id="print",
        check_name="health",
        error_code="UNAVAILABLE",
        severity="warning",
        check_id="check-1",
        occurred_at=happened,
        consecutive_failures=2,
    )
    with database.session() as session, session.begin():
        persisted = session.get(type(alert), alert.id)
        persisted.status = status
        persisted.acknowledged_by = "operator-1"
        persisted.acknowledged_at = happened

    updated = store.upsert_alert(
        fingerprint="print:health:UNAVAILABLE",
        service_id="print",
        check_name="health",
        error_code="UNAVAILABLE",
        severity="critical",
        check_id="check-2",
        occurred_at=happened + timedelta(minutes=1),
        consecutive_failures=3,
    )

    assert updated.status == status
    assert updated.acknowledged_by == "operator-1"
    assert updated.acknowledged_at == happened
    assert updated.last_check_id == "check-2"


def test_failure_after_recovery_reopens_alert_and_resets_acknowledgement(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'reopen-alert.db'}")
    database.initialize()
    store = MaintenanceStore(database)
    happened = datetime.now(UTC)
    alert = store.upsert_alert(
        fingerprint="narrative:health:TIMEOUT",
        service_id="narrative",
        check_name="health",
        error_code="TIMEOUT",
        severity="warning",
        check_id="check-1",
        occurred_at=happened,
        consecutive_failures=2,
    )
    with database.session() as session, session.begin():
        persisted = session.get(type(alert), alert.id)
        persisted.status = "acknowledged"
        persisted.acknowledged_by = "operator-1"
        persisted.acknowledged_at = happened
    store.resolve_alert(
        fingerprint="narrative:health:TIMEOUT",
        check_id="check-recovery",
        resolved_at=happened + timedelta(minutes=1),
    )

    reopened = store.upsert_alert(
        fingerprint="narrative:health:TIMEOUT",
        service_id="narrative",
        check_name="health",
        error_code="TIMEOUT",
        severity="warning",
        check_id="check-again",
        occurred_at=happened + timedelta(minutes=2),
        consecutive_failures=2,
    )

    assert reopened.status == "open"
    assert reopened.acknowledged_by is None
    assert reopened.acknowledged_at is None
    assert reopened.first_check_id == "check-again"


@pytest.mark.parametrize("late_failure_offset", [0, -1])
def test_late_failure_does_not_reopen_resolved_alert(tmp_path, late_failure_offset: int) -> None:
    database = Database(f"sqlite:///{tmp_path / f'late-failure-{late_failure_offset}.db'}")
    database.initialize()
    store = MaintenanceStore(database)
    happened = datetime.now(UTC)
    recovery_at = happened + timedelta(minutes=2)
    store.upsert_alert(
        fingerprint="gateway:models:TIMEOUT",
        service_id="gateway",
        check_name="models",
        error_code="TIMEOUT",
        severity="warning",
        check_id="check-failure",
        occurred_at=happened,
        consecutive_failures=2,
    )
    store.resolve_alert(
        fingerprint="gateway:models:TIMEOUT",
        check_id="check-recovery",
        resolved_at=recovery_at,
    )

    late = store.upsert_alert(
        fingerprint="gateway:models:TIMEOUT",
        service_id="gateway",
        check_name="models",
        error_code="TIMEOUT",
        severity="warning",
        check_id="check-late-failure",
        occurred_at=recovery_at + timedelta(seconds=late_failure_offset),
        consecutive_failures=3,
    )

    assert late.status == "resolved"
    assert late.recovery_check_id == "check-recovery"
    assert late.resolved_at == recovery_at


def test_late_recovery_does_not_resolve_newer_failure(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'late-recovery.db'}")
    database.initialize()
    store = MaintenanceStore(database)
    happened = datetime.now(UTC)
    latest_failure_at = happened + timedelta(minutes=2)
    alert = store.upsert_alert(
        fingerprint="agents:catalog:UNAVAILABLE",
        service_id="agents",
        check_name="catalog",
        error_code="UNAVAILABLE",
        severity="warning",
        check_id="check-failure-1",
        occurred_at=happened,
        consecutive_failures=2,
    )
    store.upsert_alert(
        fingerprint="agents:catalog:UNAVAILABLE",
        service_id="agents",
        check_name="catalog",
        error_code="UNAVAILABLE",
        severity="critical",
        check_id="check-failure-2",
        occurred_at=latest_failure_at,
        consecutive_failures=3,
    )

    unchanged = store.resolve_alert(
        fingerprint="agents:catalog:UNAVAILABLE",
        check_id="check-late-recovery",
        resolved_at=latest_failure_at - timedelta(seconds=1),
    )

    assert unchanged is not None
    assert unchanged.id == alert.id
    assert unchanged.status == "open"
    assert unchanged.last_check_id == "check-failure-2"
    assert unchanged.recovery_check_id is None
    assert unchanged.resolved_at is None

def test_repair_audits_are_returned_newest_first(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'repairs.db'}")
    database.initialize()
    store = MaintenanceStore(database)
    first = datetime.now(UTC)

    store.record_repair_audit(
        audit_id="repair-1",
        actor_id="admin-1",
        action="restore_last_good",
        service_id="agents",
        target_revision=2,
        result="succeeded",
        occurred_at=first,
    )
    store.record_repair_audit(
        audit_id="repair-2",
        actor_id="admin-2",
        action="restore_last_good",
        service_id="gateway",
        target_revision=4,
        result="conflict",
        occurred_at=first + timedelta(seconds=1),
    )

    assert [audit.id for audit in store.list_repair_audits()] == ["repair-2", "repair-1"]


def test_expired_worker_lease_can_be_taken_over(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'leases.db'}")
    database.initialize()
    store = MaintenanceStore(database)
    now = datetime.now(UTC)

    assert store.acquire_worker_lease(
        lease_name="maintenance", owner_id="worker-a", now=now, lease_seconds=30
    ) is True
    assert store.acquire_worker_lease(
        lease_name="maintenance", owner_id="worker-b", now=now + timedelta(seconds=10), lease_seconds=30
    ) is False
    assert store.acquire_worker_lease(
        lease_name="maintenance", owner_id="worker-b", now=now + timedelta(seconds=31), lease_seconds=30
    ) is True
