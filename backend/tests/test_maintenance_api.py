from __future__ import annotations

import json
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import httpx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app.api.routes import maintenance
from app.api.routes import platform_connections
from app.infrastructure.database import (
    AuditEventRecord,
    Database,
    MaintenanceCheckRecord,
    MaintenanceRepairAuditRecord,
    PlatformConnectionRecord,
)
from app.infrastructure.maintenance import MaintenanceStore
from app.infrastructure.platform_connections import serialize_connection
from app.infrastructure.platforms import MaintenanceCheckResult, PlatformSettings
from app.main import create_app


ADMIN = {"X-Lyra-Admin-Token": "platform-admin-secret"}


class StubChecks:
    def __init__(self, results: list[MaintenanceCheckResult]) -> None:
        self.results = results
        self.calls = 0

    def run_all(self) -> list[MaintenanceCheckResult]:
        self.calls += 1
        return self.results


def _client(tmp_path, monkeypatch, checks: StubChecks | None = None, transport=None):
    monkeypatch.setenv("LYRA_HUB_ADMIN_TOKEN", "platform-admin-secret")
    db_url = f"sqlite:///{tmp_path / 'maintenance-api.db'}"
    settings = PlatformSettings(gateway_url="https://broken-gateway.example", gateway_token="old-token")
    app = create_app(
        database_url=db_url,
        platform_settings=settings,
        platform_transport=transport,
    )
    if checks is not None:
        app.dependency_overrides[maintenance.get_maintenance_checks] = lambda: checks
    database = Database(db_url)
    database.initialize()
    return TestClient(app), database


def test_maintenance_api_rejects_anonymous_requests(tmp_path, monkeypatch) -> None:
    client, _ = _client(tmp_path, monkeypatch)

    response = client.get("/api/v1/maintenance/overview")

    assert response.status_code == 403


def test_admin_can_read_local_overview_and_alerts(tmp_path, monkeypatch) -> None:
    client, database = _client(tmp_path, monkeypatch)
    store = MaintenanceStore(database)
    now = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)
    store.save_schedule(
        schedule_id="platform-health",
        service_id="platform",
        interval_seconds=300,
        enabled=True,
        next_run_at=now,
    )
    store.record_check(
        check_id="check-gateway",
        schedule_id="platform-health",
        service_id="gateway",
        check_name="gateway.models",
        status="unhealthy",
        error_code="TIMEOUT",
        checked_at=now,
    )
    store.upsert_alert(
        fingerprint="gateway:gateway.models:TIMEOUT",
        service_id="gateway",
        check_name="gateway.models",
        error_code="TIMEOUT",
        severity="error",
        check_id="check-gateway",
        occurred_at=now,
        consecutive_failures=2,
    )

    overview = client.get("/api/v1/maintenance/overview", headers=ADMIN)
    alerts = client.get("/api/v1/maintenance/alerts", headers=ADMIN)

    assert overview.status_code == 200
    assert overview.json()["data"]["schedule"]["interval_seconds"] == 300
    assert overview.json()["data"]["services"]["gateway"]["status"] == "unhealthy"
    assert overview.json()["data"]["open_alerts"] == 1
    assert alerts.status_code == 200
    assert alerts.json()["data"][0]["error_code"] == "TIMEOUT"


def test_admin_can_trigger_read_only_checks_and_acknowledge_alert(tmp_path, monkeypatch) -> None:
    results = [
        MaintenanceCheckResult("gateway", "gateway.models", "unhealthy", "TIMEOUT", {"catalog_count": None})
    ]
    checks = StubChecks(results)
    client, database = _client(tmp_path, monkeypatch, checks)
    store = MaintenanceStore(database)
    now = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)
    store.upsert_alert(
        fingerprint="gateway:gateway.models:TIMEOUT",
        service_id="gateway",
        check_name="gateway.models",
        error_code="TIMEOUT",
        severity="error",
        check_id="prior-check",
        occurred_at=now,
        consecutive_failures=2,
    )
    alert_id = store.list_alerts()[0].id

    checked = client.post("/api/v1/maintenance/checks", headers=ADMIN)
    acknowledged = client.post(f"/api/v1/maintenance/alerts/{alert_id}/acknowledge", headers=ADMIN)

    assert checked.status_code == 200
    assert checks.calls == 1
    assert checked.json()["data"][0]["status"] == "unhealthy"
    assert len(store.list_checks(service_id="gateway")) == 1
    assert acknowledged.status_code == 200
    alert = store.list_alerts()[0]
    assert alert.status == "acknowledged"
    assert alert.acknowledged_by == "platform-admin"
    assert alert.acknowledged_at is not None
    first_acknowledged_at = alert.acknowledged_at

    repeated = client.post(f"/api/v1/maintenance/alerts/{alert_id}/acknowledge", headers=ADMIN)

    assert repeated.status_code == 200
    assert repeated.json()["data"]["status"] == "acknowledged"
    assert store.list_alerts()[0].acknowledged_at == first_acknowledged_at
    with database.session() as session:
        acknowledgements = session.scalars(
            select(AuditEventRecord).where(AuditEventRecord.action == "maintenance.alert_acknowledged")
        ).all()
    assert len(acknowledgements) == 1


def test_overview_groups_checks_and_aggregates_worst_service_status(tmp_path, monkeypatch) -> None:
    client, database = _client(tmp_path, monkeypatch)
    store = MaintenanceStore(database)
    checked_at = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)
    store.record_check(
        check_id="gateway-health",
        schedule_id=None,
        service_id="gateway",
        check_name="gateway.health",
        status="healthy",
        checked_at=checked_at,
    )
    store.record_check(
        check_id="gateway-models",
        schedule_id=None,
        service_id="gateway",
        check_name="gateway.models",
        status="unhealthy",
        error_code="TIMEOUT",
        checked_at=checked_at,
    )

    response = client.get("/api/v1/maintenance/overview", headers=ADMIN)

    gateway = response.json()["data"]["services"]["gateway"]
    assert gateway["status"] == "unhealthy"
    assert gateway["checks"]["gateway.health"]["status"] == "healthy"
    assert gateway["checks"]["gateway.models"]["status"] == "unhealthy"


def test_concurrent_alert_acknowledgements_are_idempotent_and_audited_once(tmp_path, monkeypatch) -> None:
    client, database = _client(tmp_path, monkeypatch)
    store = MaintenanceStore(database)
    now = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)
    store.upsert_alert(
        fingerprint="gateway:gateway.models:TIMEOUT",
        service_id="gateway",
        check_name="gateway.models",
        error_code="TIMEOUT",
        severity="error",
        check_id="prior-check",
        occurred_at=now,
        consecutive_failures=2,
    )
    alert_id = store.list_alerts()[0].id
    start_together = threading.Barrier(2)

    def synchronize_alert_access(connection, cursor, statement, parameters, context, executemany):
        if "maintenance_alert" in statement.lower() and (
            statement.lstrip().lower().startswith("select")
            or statement.lstrip().lower().startswith("update")
        ):
            start_together.wait(timeout=5)

    event.listen(database.engine, "before_cursor_execute", synchronize_alert_access)
    client = TestClient(client.app, raise_server_exceptions=False)

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda _: client.post(
                    f"/api/v1/maintenance/alerts/{alert_id}/acknowledge", headers=ADMIN
                ),
                range(2),
            )
        )

    event.remove(database.engine, "before_cursor_execute", synchronize_alert_access)
    assert [response.status_code for response in responses] == [200, 200]
    assert all(response.json()["data"]["status"] == "acknowledged" for response in responses)
    assert store.list_alerts()[0].status == "acknowledged"
    with database.session() as session:
        acknowledgements = session.scalars(
            select(AuditEventRecord).where(AuditEventRecord.action == "maintenance.alert_acknowledged")
        ).all()
    assert len(acknowledgements) == 1


def test_repair_requires_confirmation_and_rejects_stale_revision(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LYRA_HUB_SECRET_KEY", Fernet.generate_key().decode("ascii"))
    client, database = _client(tmp_path, monkeypatch)
    with database.session() as session, session.begin():
        session.add(
            PlatformConnectionRecord(
                service_id="gateway",
                current_json=serialize_connection("gateway", "https://broken.example", "secret-token"),
                last_good_json=serialize_connection("gateway", "https://good.example", "last-good-token"),
                revision=4,
            )
        )

    unconfirmed = client.post(
        "/api/v1/maintenance/repairs/gateway/confirm",
        headers={**ADMIN, "Idempotency-Key": "repair-unconfirmed"},
        json={"action": "restore_last_good", "expected_revision": 4, "confirmed": False},
    )
    stale = client.post(
        "/api/v1/maintenance/repairs/gateway/confirm",
        headers={**ADMIN, "Idempotency-Key": "repair-stale"},
        json={"action": "restore_last_good", "expected_revision": 3, "confirmed": True},
    )

    assert unconfirmed.status_code == 422
    assert stale.status_code == 409
    with database.session() as session:
        connection = session.get(PlatformConnectionRecord, "gateway")
        assert connection.revision == 4
        assert "broken.example" in connection.current_json
        assert session.scalars(select(MaintenanceRepairAuditRecord)).all() == []


def test_confirmed_restore_is_revisioned_audited_and_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LYRA_HUB_SECRET_KEY", Fernet.generate_key().decode("ascii"))
    database_ref: dict[str, Database] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        database = database_ref["database"]
        with database.session() as session:
            current = session.get(PlatformConnectionRecord, "gateway")
            activated = current.current_json == current.last_good_json
        if request.url.path == "/health":
            return httpx.Response(200 if activated else 503, json={"status": "ok" if activated else "down"})
        if request.url.path == "/v1/models":
            return httpx.Response(200 if activated else 503, json={"data": [{"id": "safe-model"}]})
        return httpx.Response(404)

    client, database = _client(tmp_path, monkeypatch, transport=httpx.MockTransport(handler))
    database_ref["database"] = database
    with database.session() as session, session.begin():
        session.add(
            PlatformConnectionRecord(
                service_id="gateway",
                current_json=serialize_connection("gateway", "https://broken.example", "secret-token"),
                last_good_json=serialize_connection("gateway", "https://good.example", "restore-secret"),
                revision=4,
            )
        )
    headers = {**ADMIN, "Idempotency-Key": "repair-success-1"}
    payload = {"action": "restore_last_good", "expected_revision": 4, "confirmed": True}

    missing_key = client.post("/api/v1/maintenance/repairs/gateway/confirm", headers=ADMIN, json=payload)
    restored = client.post("/api/v1/maintenance/repairs/gateway/confirm", headers=headers, json=payload)
    replay = client.post("/api/v1/maintenance/repairs/gateway/confirm", headers=headers, json=payload)
    reused_key = client.post(
        "/api/v1/maintenance/repairs/gateway/confirm",
        headers=headers,
        json={"action": "restore_last_good", "expected_revision": 5, "confirmed": True},
    )

    assert missing_key.status_code == 422
    assert restored.status_code == 200
    assert restored.json()["data"]["revision"] == 5
    assert restored.json()["data"]["check"]["catalog_access"] is True
    assert replay.status_code == 200
    assert replay.json()["data"]["revision"] == 5
    assert replay.json()["data"]["replayed"] is True
    assert reused_key.status_code == 409
    with database.session() as session:
        connection = session.get(PlatformConnectionRecord, "gateway")
        audits = session.scalars(select(MaintenanceRepairAuditRecord)).all()
        assert connection.revision == 5
        assert connection.current_json == connection.last_good_json
        assert len(audits) == 1
        assert "restore-secret" not in json.dumps(audits[0].details)
        assert audits[0].target_revision == 4


def test_restore_audit_distinguishes_committed_config_from_failed_verification(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LYRA_HUB_SECRET_KEY", Fernet.generate_key().decode("ascii"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"status": "down"})

    client, database = _client(tmp_path, monkeypatch, transport=httpx.MockTransport(handler))
    with database.session() as session, session.begin():
        session.add(
            PlatformConnectionRecord(
                service_id="gateway",
                current_json=serialize_connection("gateway", "https://broken.example", "secret-token"),
                last_good_json=serialize_connection("gateway", "https://good.example", "restore-secret"),
                revision=4,
            )
        )
    headers = {**ADMIN, "Idempotency-Key": "restore-but-offline"}
    payload = {"action": "restore_last_good", "expected_revision": 4, "confirmed": True}

    restored = client.post("/api/v1/maintenance/repairs/gateway/confirm", headers=headers, json=payload)
    replay = client.post("/api/v1/maintenance/repairs/gateway/confirm", headers=headers, json=payload)

    assert restored.status_code == 200
    assert restored.json()["data"]["configuration_status"] == "restored"
    assert restored.json()["data"]["verification_status"] == "unhealthy"
    assert restored.json()["data"]["check"]["catalog_access"] is False
    assert replay.status_code == 200
    assert replay.json()["data"]["verification_status"] == "unhealthy"
    with database.session() as session:
        audit = session.scalars(select(MaintenanceRepairAuditRecord)).one()
        connection = session.get(PlatformConnectionRecord, "gateway")
        assert connection.revision == 5
        assert audit.result == "restored_unhealthy"
        assert audit.details["check"]["catalog_access"] is False


def test_pending_idempotent_repair_verification_is_safe_under_concurrency(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LYRA_HUB_SECRET_KEY", Fernet.generate_key().decode("ascii"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "safe-model"}]})
        return httpx.Response(404)

    client, database = _client(tmp_path, monkeypatch, transport=httpx.MockTransport(handler))
    key = "pending-repair-concurrent"
    request_hash = hashlib.sha256(
        json.dumps(
            {"service_id": "gateway", "action": "restore_last_good", "expected_revision": 4},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    with database.session() as session, session.begin():
        session.add(
            PlatformConnectionRecord(
                service_id="gateway",
                current_json=serialize_connection("gateway", "https://good.example", "restore-secret"),
                last_good_json=serialize_connection("gateway", "https://good.example", "restore-secret"),
                revision=5,
            )
        )
        session.add(
            MaintenanceRepairAuditRecord(
                id=maintenance._repair_identity(key, "gateway"),
                actor_id="platform-admin",
                action="restore_last_good",
                service_id="gateway",
                target_revision=4,
                result="pending",
                details_json=json.dumps({"request_hash": request_hash, "result_revision": 5}),
                occurred_at=datetime.now(UTC),
            )
        )

    barrier = threading.Barrier(2)
    original_record_check = MaintenanceStore.record_check

    def concurrent_record_check(self, **kwargs):
        if str(kwargs["check_id"]).startswith("repair-check-"):
            barrier.wait(timeout=5)
        return original_record_check(self, **kwargs)

    monkeypatch.setattr(MaintenanceStore, "record_check", concurrent_record_check)
    client = TestClient(client.app, raise_server_exceptions=False)
    headers = {**ADMIN, "Idempotency-Key": key}
    payload = {"action": "restore_last_good", "expected_revision": 4, "confirmed": True}

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda _: client.post("/api/v1/maintenance/repairs/gateway/confirm", headers=headers, json=payload),
                range(2),
            )
        )

    assert [response.status_code for response in responses] == [200, 200]
    assert all(response.json()["data"]["verification_status"] == "healthy" for response in responses)
    with database.session() as session:
        checks = session.scalars(select(MaintenanceCheckRecord)).all()
    assert len(checks) == 1


def test_repair_activation_does_not_overwrite_a_newer_saved_revision(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LYRA_HUB_SECRET_KEY", Fernet.generate_key().decode("ascii"))
    restore_entered = threading.Event()
    release_restore = threading.Event()
    save_probe_finished = threading.Event()
    save_finished = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "newer.example" and request.url.path == "/health":
            save_probe_finished.set()
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "safe-model"}]})
        return httpx.Response(404)

    client, database = _client(tmp_path, monkeypatch, transport=httpx.MockTransport(handler))
    with database.session() as session, session.begin():
        session.add(
            PlatformConnectionRecord(
                service_id="gateway",
                current_json=serialize_connection("gateway", "https://broken.example", "secret-token"),
                last_good_json=serialize_connection("gateway", "https://good.example", "restore-secret"),
                revision=4,
            )
        )
    services = client.app.dependency_overrides[platform_connections.get_platform_services]()
    original_configure = services.configure

    def pause_restore_activation(settings):
        if settings.gateway_url == "https://good.example":
            restore_entered.set()
            assert release_restore.wait(timeout=5)
        original_configure(settings)

    services.configure = pause_restore_activation
    client = TestClient(client.app, raise_server_exceptions=False)

    def restore():
        return client.post(
            "/api/v1/maintenance/repairs/gateway/confirm",
            headers={**ADMIN, "Idempotency-Key": "restore-racing-save"},
            json={"action": "restore_last_good", "expected_revision": 4, "confirmed": True},
        )

    def save_newer():
        try:
            return client.put(
                "/api/v1/platform/connections/gateway",
                headers=ADMIN,
                json={
                    "base_url": "https://newer.example",
                    "credential": "new-secret",
                    "expected_revision": 5,
                },
            )
        finally:
            save_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        restore_future = executor.submit(restore)
        assert restore_entered.wait(timeout=5)
        save_future = executor.submit(save_newer)
        assert save_probe_finished.wait(timeout=5)
        # A connection update must wait until the restoring revision is activated.
        save_was_blocked = not save_finished.wait(timeout=0.1)
        release_restore.set()
        restore_response = restore_future.result(timeout=5)
        save_response = save_future.result(timeout=5)

    assert save_was_blocked is True
    assert restore_response.status_code == 200
    assert save_response.status_code == 200
    with database.session() as session:
        connection = session.get(PlatformConnectionRecord, "gateway")
    assert connection.revision == 6
    assert services.settings.gateway_url == "https://newer.example"


def test_agents_offline_break_glass_reads_only_local_maintenance_data(tmp_path, monkeypatch) -> None:
    client, database = _client(tmp_path, monkeypatch)
    MaintenanceStore(database).save_schedule(
        schedule_id="platform-health",
        service_id="platform",
        interval_seconds=300,
        enabled=True,
        next_run_at=datetime(2026, 10, 3, 8, 0, tzinfo=UTC),
    )

    response = client.get("/api/v1/maintenance/overview", headers=ADMIN)

    assert response.status_code == 200
    assert response.json()["data"]["agents_available"] is None
    proxy_attempt = client.get("/api/v1/agents/tenants", headers=ADMIN)
    assert proxy_attempt.status_code == 404
