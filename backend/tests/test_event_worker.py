from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import update

from app.infrastructure.database import Database, EventDeliveryRecord
from app.infrastructure.events import EventService, WebhookSecretRegistry
from app.workers.event_delivery import run_once


def _service(tmp_path, handler) -> tuple[Database, EventService]:
    database = Database(f"sqlite:///{tmp_path / 'worker.db'}")
    database.initialize()
    service = EventService(
        database,
        secrets=WebhookSecretRegistry({"worker-secret": "secret"}),
        transport=httpx.MockTransport(handler),
    )
    service.create_subscription(
        subscriber_id="worker-test",
        event_type="workflow.*",
        endpoint_url="https://receiver.local/events",
        secret_ref="worker-secret",
        enabled=True,
        max_attempts=3,
    )
    return database, service


def _publish(service: EventService, event_id: str) -> None:
    service.publish(
        event_id=event_id,
        event_type="workflow.completed",
        event_version="1.0",
        occurred_at=datetime.now(UTC),
        source_type="application",
        source_id="lyra-narrative",
        tenant_id=None,
        actor_id=None,
        subject=None,
        correlation_id=None,
        causation_id=None,
        data={"status": "succeeded"},
    )


def test_worker_delivers_due_outbox_items(tmp_path) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(204)

    _database, service = _service(tmp_path, handler)
    _publish(service, "evt-worker-1")

    summary = run_once(service, batch_size=10, lease_seconds=60)

    assert summary == {
        "selected": 1,
        "delivered": 1,
        "retry": 0,
        "dead": 0,
        "skipped": 0,
    }
    assert calls == 1
    assert service.list_deliveries()[0].status == "delivered"


def test_worker_respects_retry_schedule(tmp_path) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    _database, service = _service(tmp_path, handler)
    _publish(service, "evt-worker-retry")

    first = run_once(service, batch_size=10, lease_seconds=60)
    second = run_once(service, batch_size=10, lease_seconds=60)

    assert first["selected"] == 1
    assert first["retry"] == 1
    assert second["selected"] == 0
    assert calls == 1


def test_worker_reclaims_stale_delivery_lease(tmp_path) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(204)

    database, service = _service(tmp_path, handler)
    _publish(service, "evt-worker-stale")
    delivery = service.list_deliveries()[0]

    with database.session() as session:
        session.execute(
            update(EventDeliveryRecord)
            .where(EventDeliveryRecord.id == delivery.id)
            .values(
                status="delivering",
                updated_at=datetime.now(UTC) - timedelta(seconds=120),
            )
        )
        session.commit()

    summary = run_once(service, batch_size=10, lease_seconds=60)

    assert summary["selected"] == 1
    assert summary["delivered"] == 1
    assert calls == 1


def test_fresh_delivery_lease_is_not_double_sent(tmp_path) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(204)

    database, service = _service(tmp_path, handler)
    _publish(service, "evt-worker-fresh")
    delivery = service.list_deliveries()[0]

    with database.session() as session:
        session.execute(
            update(EventDeliveryRecord)
            .where(EventDeliveryRecord.id == delivery.id)
            .values(status="delivering", updated_at=datetime.now(UTC))
        )
        session.commit()

    summary = run_once(service, batch_size=10, lease_seconds=60)

    assert summary["selected"] == 0
    assert calls == 0
