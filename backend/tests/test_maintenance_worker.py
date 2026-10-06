from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet

from app.infrastructure.database import Database, MaintenanceWorkerLeaseRecord, PlatformConnectionRecord
from app.infrastructure.maintenance import MaintenanceStore
from app.infrastructure.platform_connections import serialize_connection
from app.workers.maintenance import MaintenanceWorker, build_checks


@dataclass(frozen=True)
class Result:
    service_id: str
    check_name: str
    status: str
    error_code: str | None = None
    details: dict | None = None
    duration_ms: int = 1


class FakeChecks:
    def __init__(self, results: list[Result], on_run=None) -> None:
        self.results = results
        self.calls = 0
        self.on_run = on_run

    def run_all(self) -> list[Result]:
        self.calls += 1
        if self.on_run is not None:
            self.on_run()
        return self.results


def test_worker_persists_checks_and_only_opens_alert_after_two_failures(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'worker.db'}")
    database.initialize()
    store = MaintenanceStore(database)
    checks = FakeChecks([Result("gateway", "gateway.models", "unhealthy", "UPSTREAM_ERROR")])
    worker = MaintenanceWorker(store, checks, worker_id="worker-a", jitter_seconds=0)
    now = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)

    first = worker.run_once(now=now)
    assert first["checks"] == 1
    assert store.list_alerts() == []

    second = worker.run_once(now=now + timedelta(minutes=5, seconds=1))
    assert second["checks"] == 1
    alerts = store.list_alerts()
    assert len(alerts) == 1
    assert alerts[0].error_code == "UPSTREAM_ERROR"
    assert alerts[0].consecutive_failures == 2

    checks.results = [Result("gateway", "gateway.models", "healthy")]
    recovered = worker.run_once(now=now + timedelta(minutes=10, seconds=2))
    assert recovered["checks"] == 1
    alert = store.list_alerts()[0]
    assert alert.status == "resolved"
    assert alert.recovery_check_id


def test_worker_uses_database_lease_to_prevent_duplicate_cycles(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'lease-worker.db'}")
    database.initialize()
    store = MaintenanceStore(database)
    now = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)
    checks_b = FakeChecks([Result("hub", "hub.health", "healthy")])
    second = MaintenanceWorker(store, checks_b, worker_id="worker-b", jitter_seconds=0, lease_seconds=60)
    attempts: list[dict] = []
    checks_a = FakeChecks(
        [Result("hub", "hub.health", "healthy")],
        on_run=lambda: attempts.append(second.run_once(now=now)),
    )
    first = MaintenanceWorker(store, checks_a, worker_id="worker-a", jitter_seconds=0, lease_seconds=60)

    assert first.run_once(now=now)["checks"] == 1
    assert attempts == [{"acquired": False, "checks": 0, "alerts_opened": 0, "alerts_resolved": 0}]
    assert checks_a.calls == 1
    assert checks_b.calls == 0


def test_worker_renews_and_releases_its_own_active_lease(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'lease-renew.db'}")
    database.initialize()
    store = MaintenanceStore(database)
    now = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)

    assert store.acquire_worker_lease(lease_name="maintenance", owner_id="worker-a", now=now, lease_seconds=30)
    assert store.renew_worker_lease(lease_name="maintenance", owner_id="worker-a", now=now + timedelta(seconds=10), lease_seconds=30)
    assert not store.renew_worker_lease(lease_name="maintenance", owner_id="worker-b", now=now + timedelta(seconds=11), lease_seconds=30)
    assert not store.renew_worker_lease(lease_name="maintenance", owner_id="worker-a", now=now + timedelta(seconds=41), lease_seconds=30)
    assert store.release_worker_lease(lease_name="maintenance", owner_id="worker-a")


def test_empty_probe_result_still_advances_schedule(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'empty-worker.db'}")
    database.initialize()
    store = MaintenanceStore(database)
    checks = FakeChecks([])
    worker = MaintenanceWorker(store, checks, worker_id="worker-a", jitter_seconds=0)
    now = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)

    assert worker.run_once(now=now)["checks"] == 0
    assert worker.run_once(now=now + timedelta(seconds=10))["checks"] == 0
    assert checks.calls == 1


def test_worker_stops_before_persisting_results_when_lease_is_lost(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'lost-lease.db'}")
    database.initialize()
    backing_store = MaintenanceStore(database)
    now = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)
    schedule = backing_store.save_schedule(
        schedule_id="platform-health",
        service_id="platform",
        interval_seconds=300,
        enabled=True,
        next_run_at=now,
    )

    class LoseLeaseOnPostProbe:
        def __init__(self) -> None:
            self.renewals = 0

        def __getattr__(self, name):
            return getattr(backing_store, name)

        def renew_worker_lease(self, **kwargs):
            self.renewals += 1
            if self.renewals == 2:
                return False
            return backing_store.renew_worker_lease(**kwargs)

    checks = FakeChecks([Result("gateway", "gateway.models", "unhealthy", "TIMEOUT")])
    worker = MaintenanceWorker(LoseLeaseOnPostProbe(), checks, worker_id="worker-a", jitter_seconds=0)

    summary = worker.run_once(now=now)

    assert summary["acquired"] is False
    assert backing_store.list_checks() == []
    assert backing_store.list_alerts() == []
    assert backing_store.get_schedule("platform-health").next_run_at == schedule.next_run_at


def test_worker_applies_changed_interval_and_enabled_configuration(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'schedule-config.db'}")
    database.initialize()
    store = MaintenanceStore(database)
    first_results = [Result("hub", "hub.health", "healthy")]
    checks = FakeChecks(first_results)
    first_worker = MaintenanceWorker(
        store, checks, worker_id="worker-a", interval_seconds=600, jitter_seconds=0
    )
    now = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)
    first_worker.run_once(now=now)

    updated_worker = MaintenanceWorker(
        store, checks, worker_id="worker-a", interval_seconds=120, enabled=False, jitter_seconds=0
    )
    updated_worker.run_once(now=now + timedelta(seconds=601))

    schedule = store.get_schedule("platform-health")
    assert schedule.interval_seconds == 120
    assert schedule.enabled is False
    assert schedule.next_run_at == now + timedelta(seconds=601 + 120)
    assert checks.calls == 1


def test_worker_rejects_a_lease_shorter_than_its_probe_budget(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'short-lease.db'}")
    database.initialize()
    checks = FakeChecks([])
    checks.max_run_seconds = 20

    with pytest.raises(ValueError, match="lease_seconds"):
        MaintenanceWorker(
            MaintenanceStore(database),
            checks,
            worker_id="worker-a",
            lease_seconds=10,
            jitter_seconds=0,
        )


def test_recovery_resolves_every_error_fingerprint_for_a_check(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'alert-error-change.db'}")
    database.initialize()
    store = MaintenanceStore(database)
    checks = FakeChecks([Result("gateway", "gateway.models", "unhealthy", "ERROR_A")])
    worker = MaintenanceWorker(store, checks, worker_id="worker-a", jitter_seconds=0)
    now = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)

    for minute in (0, 5):
        worker.run_once(now=now + timedelta(minutes=minute))
    checks.results = [Result("gateway", "gateway.models", "unhealthy", "ERROR_B")]
    for minute in (10, 15):
        worker.run_once(now=now + timedelta(minutes=minute))
    checks.results = [Result("gateway", "gateway.models", "healthy")]
    worker.run_once(now=now + timedelta(minutes=20))

    alerts = store.list_alerts()
    assert {alert.error_code for alert in alerts} == {"ERROR_A", "ERROR_B"}
    assert all(alert.status == "resolved" for alert in alerts)


def test_worker_fences_each_write_after_another_owner_takes_over(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'fenced-worker.db'}")
    database.initialize()
    now = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)

    class TakeoverAfterFirstCheck(MaintenanceStore):
        writes = 0

        def record_check(self, **kwargs):
            record = super().record_check(**kwargs)
            self.writes += 1
            if self.writes == 1:
                assert super().acquire_worker_lease(
                    lease_name="maintenance",
                    owner_id="worker-b",
                    now=now + timedelta(seconds=61),
                    lease_seconds=60,
                )
            return record

    store = TakeoverAfterFirstCheck(database)
    checks = FakeChecks(
        [
            Result("hub", "hub.health", "healthy"),
            Result("gateway", "gateway.models", "unhealthy", "TIMEOUT"),
        ]
    )
    worker = MaintenanceWorker(store, checks, worker_id="worker-a", jitter_seconds=0)

    summary = worker.run_once(now=now)

    assert summary == {"acquired": False, "checks": 1, "alerts_opened": 0, "alerts_resolved": 0}
    records = store.list_checks()
    assert len(records) == 1
    assert records[0].service_id == "hub"
    assert store.list_alerts() == []
    assert store.get_schedule("platform-health").next_run_at == now

    takeover_checks = FakeChecks([Result("hub", "hub.health", "healthy")])
    takeover_worker = MaintenanceWorker(store, takeover_checks, worker_id="worker-b", jitter_seconds=0)
    takeover_summary = takeover_worker.run_once(now=now + timedelta(seconds=61))
    assert takeover_summary["acquired"] is True
    assert takeover_summary["checks"] == 1


def test_scheduled_checks_load_saved_platform_connections(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LYRA_HUB_SECRET_KEY", Fernet.generate_key().decode("ascii"))
    database = Database(f"sqlite:///{tmp_path / 'worker-connections.db'}")
    database.initialize()
    with database.session() as session, session.begin():
        session.add(
            PlatformConnectionRecord(
                service_id="gateway",
                current_json=serialize_connection("gateway", "http://gateway.local", "gateway-token"),
                revision=1,
            )
        )
        session.add(
            PlatformConnectionRecord(
                service_id="agent-os",
                current_json=serialize_connection("agent-os", "http://agents.local", "agents-token"),
                revision=1,
            )
        )

    checks = build_checks(database, timeout_seconds=3, retries=0, max_concurrency=2)

    assert checks.settings.gateway_url == "http://gateway.local"
    assert checks.settings.gateway_token == "gateway-token"
    assert checks.settings.agent_os_url == "http://agents.local"
    assert checks.settings.agent_os_token == "agents-token"


def test_worker_crash_mid_cycle_keeps_schedule_due_for_takeover_retry(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'crash-mid-cycle.db'}")
    database.initialize()
    now = datetime.now(UTC)

    class CrashAfterFirstCheck(MaintenanceStore):
        should_crash = True

        def record_check(self, **kwargs):
            record = super().record_check(**kwargs)
            if self.should_crash:
                self.should_crash = False
                raise RuntimeError("simulated worker crash after first committed check")
            return record

    store = CrashAfterFirstCheck(database)
    partial_checks = FakeChecks(
        [
            Result("hub", "hub.health", "healthy"),
            Result("gateway", "gateway.models", "healthy"),
        ]
    )
    worker = MaintenanceWorker(store, partial_checks, worker_id="worker-a", jitter_seconds=0)

    with pytest.raises(RuntimeError, match="simulated worker crash"):
        worker.run_once(now=now)

    assert len(store.list_checks()) == 1
    assert store.get_schedule("platform-health").next_run_at == now

    takeover_checks = FakeChecks([Result("hub", "hub.health", "healthy")])
    takeover_worker = MaintenanceWorker(store, takeover_checks, worker_id="worker-b", jitter_seconds=0)
    summary = takeover_worker.run_once(now=now + timedelta(seconds=1))

    assert summary["acquired"] is True
    assert summary["checks"] == 1
    assert takeover_checks.calls == 1


def test_worker_uses_current_time_for_pre_probe_lease_renewal(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'expired-before-probe.db'}")
    database.initialize()
    base_store = MaintenanceStore(database)
    base_store.save_schedule(
        schedule_id="platform-health",
        service_id="platform",
        interval_seconds=300,
        enabled=True,
        next_run_at=datetime(2020, 1, 1, tzinfo=UTC),
    )

    class ControlledClockStore(MaintenanceStore):
        acquired_at: datetime
        current_time: datetime

        def acquire_worker_lease(self, **kwargs):
            self.acquired_at = kwargs["now"]
            self.current_time = self.acquired_at
            return super().acquire_worker_lease(**kwargs)

        def get_schedule(self, schedule_id):
            schedule = super().get_schedule(schedule_id)
            # Simulate the worker being paused until after expiry between lease
            # acquisition and its pre-probe renewal.
            self.current_time = self.acquired_at + timedelta(seconds=2)
            with self.database.session() as session, session.begin():
                lease = session.get(MaintenanceWorkerLeaseRecord, "maintenance")
                lease.expires_at = self.acquired_at + timedelta(seconds=1)
            return schedule

        def renew_worker_lease(self, **kwargs):
            if kwargs.get("now") is None:
                kwargs["now"] = self.current_time
            return super().renew_worker_lease(**kwargs)

    store = ControlledClockStore(database)
    checks = FakeChecks([Result("hub", "hub.health", "healthy")])
    worker = MaintenanceWorker(store, checks, worker_id="worker-a", jitter_seconds=0, lease_seconds=10)

    summary = worker.run_once()

    assert summary["acquired"] is False
    assert checks.calls == 0
    assert store.list_checks() == []
