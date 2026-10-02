from __future__ import annotations

import hashlib
import hmac
import json

import httpx
from fastapi.testclient import TestClient

from app.main import create_app


def test_application_event_publish_and_signed_webhook_delivery(tmp_path) -> None:
    received: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["url"] = str(request.url)
        received["body"] = request.content
        received["event_id"] = request.headers.get("X-Lyra-Event-Id")
        received["signature"] = request.headers.get("X-Lyra-Signature")
        return httpx.Response(204)

    client = TestClient(
        create_app(
            database_url=f"sqlite:///{tmp_path / 'events.db'}",
            integration_tokens={"lyra-narrative": "narrative-token"},
            webhook_secrets={"receiver-secret": "signing-key"},
            event_transport=httpx.MockTransport(handler),
        )
    )

    subscription = client.post(
        "/api/v1/events/subscriptions",
        json={
            "subscriber_id": "test-receiver",
            "event_type": "workflow.*",
            "endpoint_url": "https://receiver.local/hooks/lyra",
            "secret_ref": "receiver-secret",
            "max_attempts": 3,
        },
    )
    assert subscription.status_code == 201

    event = {
        "eventId": "evt-001",
        "eventType": "workflow.completed",
        "eventVersion": "1.0",
        "subject": "workflow/run-1",
        "correlationId": "corr-1",
        "data": {"workflow_id": "novel", "status": "succeeded"},
    }
    published = client.post(
        "/api/v1/integration/apps/lyra-narrative/events",
        json=event,
        headers={"Authorization": "Bearer narrative-token"},
    )
    assert published.status_code == 200
    payload = published.json()
    assert payload["duplicate"] is False
    assert payload["delivery_count"] == 1
    assert payload["event"]["source"] == {
        "type": "application",
        "id": "lyra-narrative",
    }

    deliveries = client.get("/api/v1/events/deliveries").json()
    assert len(deliveries) == 1
    assert deliveries[0]["status"] == "pending"

    attempted = client.post(
        f"/api/v1/events/deliveries/{deliveries[0]['id']}/attempt"
    )
    assert attempted.status_code == 200
    assert attempted.json()["status"] == "delivered"
    assert attempted.json()["attempt_count"] == 1

    body = received["body"]
    assert isinstance(body, bytes)
    envelope = json.loads(body.decode("utf-8"))
    assert envelope["eventId"] == "evt-001"
    assert received["event_id"] == "evt-001"
    expected = hmac.new(b"signing-key", body, hashlib.sha256).hexdigest()
    assert received["signature"] == f"sha256={expected}"

    duplicate = client.post(
        "/api/v1/integration/apps/lyra-narrative/events",
        json=event,
        headers={"Authorization": "Bearer narrative-token"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["delivery_count"] == 1
    assert len(client.get("/api/v1/events/deliveries").json()) == 1

    conflict = client.post(
        "/api/v1/integration/apps/lyra-narrative/events",
        json={
            "eventId": "evt-001",
            "eventType": "workflow.failed",
            "data": {"workflow_id": "novel", "status": "failed"},
        },
        headers={"Authorization": "Bearer narrative-token"},
    )
    assert conflict.status_code == 409

    subscription_id = subscription.json()["id"]
    disabled = client.patch(
        f"/api/v1/events/subscriptions/{subscription_id}",
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    ignored = client.post(
        "/api/v1/integration/apps/lyra-narrative/events",
        json={
            "eventId": "evt-disabled",
            "eventType": "workflow.completed",
            "data": {"status": "succeeded"},
        },
        headers={"Authorization": "Bearer narrative-token"},
    )
    assert ignored.status_code == 200
    assert ignored.json()["delivery_count"] == 0


def test_failed_webhook_moves_from_retry_to_dead_letter(tmp_path) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"detail": "unavailable"})

    client = TestClient(
        create_app(
            database_url=f"sqlite:///{tmp_path / 'events-retry.db'}",
            integration_tokens={"lyra-narrative": "narrative-token"},
            webhook_secrets={"retry-secret": "retry-signing-key"},
            event_transport=httpx.MockTransport(handler),
        )
    )
    created = client.post(
        "/api/v1/events/subscriptions",
        json={
            "subscriber_id": "failing-receiver",
            "event_type": "chapter.completed",
            "endpoint_url": "https://receiver.local/events",
            "secret_ref": "retry-secret",
            "max_attempts": 2,
        },
    )
    assert created.status_code == 201

    published = client.post(
        "/api/v1/integration/apps/lyra-narrative/events",
        json={
            "eventId": "evt-retry",
            "eventType": "chapter.completed",
            "data": {"chapter": 2},
        },
        headers={"Authorization": "Bearer narrative-token"},
    )
    assert published.status_code == 200

    delivery_id = client.get("/api/v1/events/deliveries").json()[0]["id"]

    first = client.post(f"/api/v1/events/deliveries/{delivery_id}/attempt")
    assert first.status_code == 200
    assert first.json()["status"] == "retry"
    assert first.json()["attempt_count"] == 1
    assert first.json()["next_attempt_at"] is not None

    second = client.post(f"/api/v1/events/deliveries/{delivery_id}/attempt")
    assert second.status_code == 200
    assert second.json()["status"] == "dead"
    assert second.json()["attempt_count"] == 2
    assert second.json()["next_attempt_at"] is None
    assert calls == 2


def test_event_publish_requires_application_identity(tmp_path) -> None:
    client = TestClient(
        create_app(
            database_url=f"sqlite:///{tmp_path / 'events-auth.db'}",
            integration_tokens={"lyra-narrative": "narrative-token"},
        )
    )

    denied = client.post(
        "/api/v1/integration/apps/lyra-narrative/events",
        json={
            "eventId": "evt-denied",
            "eventType": "workflow.completed",
            "data": {},
        },
    )
    assert denied.status_code == 401

    invalid_type = client.post(
        "/api/v1/integration/apps/lyra-narrative/events",
        json={
            "eventId": "evt-invalid",
            "eventType": "Not Valid",
            "data": {},
        },
        headers={"Authorization": "Bearer narrative-token"},
    )
    assert invalid_type.status_code == 422
