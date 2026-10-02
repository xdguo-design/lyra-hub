from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select

from app.infrastructure.database import (
    Database,
    EventDeliveryRecord,
    EventRecord,
    EventSubscriptionRecord,
)


@dataclass(frozen=True)
class EventPublishResult:
    event: EventRecord
    duplicate: bool
    delivery_count: int


class WebhookSecretRegistry:
    def __init__(self, secrets: dict[str, str] | None = None) -> None:
        self._secrets = {
            str(key): str(value)
            for key, value in (secrets or {}).items()
            if str(key).strip() and str(value)
        }

    @classmethod
    def from_env(cls) -> WebhookSecretRegistry:
        raw = os.getenv("LYRA_WEBHOOK_SECRETS_JSON", "").strip()
        if not raw:
            return cls()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("LYRA_WEBHOOK_SECRETS_JSON must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("LYRA_WEBHOOK_SECRETS_JSON must be a JSON object")
        return cls({str(key): str(value) for key, value in payload.items()})

    def get(self, secret_ref: str | None) -> str | None:
        if not secret_ref:
            return None
        return self._secrets.get(secret_ref)


class EventService:
    def __init__(
        self,
        database: Database,
        *,
        secrets: WebhookSecretRegistry | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.database = database
        self.secrets = secrets or WebhookSecretRegistry.from_env()
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    def create_subscription(
        self,
        *,
        subscriber_id: str,
        event_type: str,
        endpoint_url: str,
        secret_ref: str | None,
        enabled: bool,
        max_attempts: int,
    ) -> EventSubscriptionRecord:
        record = EventSubscriptionRecord(
            subscriber_id=subscriber_id,
            event_type=event_type,
            endpoint_url=endpoint_url,
            secret_ref=secret_ref,
            enabled=enabled,
            max_attempts=max_attempts,
        )
        with self.database.session() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def list_subscriptions(self) -> list[EventSubscriptionRecord]:
        with self.database.session() as session:
            return list(
                session.scalars(
                    select(EventSubscriptionRecord).order_by(EventSubscriptionRecord.id)
                ).all()
            )

    def set_subscription_enabled(
        self,
        subscription_id: int,
        enabled: bool,
    ) -> EventSubscriptionRecord:
        with self.database.session() as session:
            record = session.get(EventSubscriptionRecord, subscription_id)
            if record is None:
                raise KeyError("subscription_not_found")
            record.enabled = enabled
            record.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(record)
            return record

    def publish(
        self,
        *,
        event_id: str,
        event_type: str,
        event_version: str,
        occurred_at: datetime,
        source_type: str,
        source_id: str,
        tenant_id: str | None,
        actor_id: str | None,
        subject: str | None,
        correlation_id: str | None,
        causation_id: str | None,
        data: dict[str, Any],
    ) -> EventPublishResult:
        with self.database.session() as session:
            existing = session.get(EventRecord, event_id)
            if existing is not None:
                same_event = (
                    existing.event_type == event_type
                    and existing.event_version == event_version
                    and existing.source_type == source_type
                    and existing.source_id == source_id
                    and existing.tenant_id == tenant_id
                    and existing.actor_id == actor_id
                    and existing.subject == subject
                    and existing.correlation_id == correlation_id
                    and existing.causation_id == causation_id
                    and existing.data == data
                )
                if not same_event:
                    raise ValueError("event_id_conflict")
                delivery_count = len(
                    session.scalars(
                        select(EventDeliveryRecord).where(
                            EventDeliveryRecord.event_id == event_id
                        )
                    ).all()
                )
                return EventPublishResult(existing, True, delivery_count)

            event = EventRecord(
                event_id=event_id,
                event_type=event_type,
                event_version=event_version,
                occurred_at=occurred_at,
                source_type=source_type,
                source_id=source_id,
                tenant_id=tenant_id,
                actor_id=actor_id,
                subject=subject,
                correlation_id=correlation_id,
                causation_id=causation_id,
                data_json=json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            )
            session.add(event)
            subscriptions = session.scalars(
                select(EventSubscriptionRecord).where(
                    EventSubscriptionRecord.enabled.is_(True)
                )
            ).all()
            matching = [
                item for item in subscriptions if _event_type_matches(item.event_type, event_type)
            ]
            for subscription in matching:
                session.add(
                    EventDeliveryRecord(
                        event_id=event_id,
                        subscription_id=subscription.id,
                        status="pending",
                        attempt_count=0,
                        next_attempt_at=datetime.now(UTC),
                    )
                )
            session.commit()
            session.refresh(event)
            return EventPublishResult(event, False, len(matching))

    def list_events(self, *, limit: int = 100) -> list[EventRecord]:
        with self.database.session() as session:
            return list(
                session.scalars(
                    select(EventRecord)
                    .order_by(EventRecord.created_at.desc())
                    .limit(limit)
                ).all()
            )

    def list_deliveries(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[EventDeliveryRecord]:
        query = select(EventDeliveryRecord).order_by(EventDeliveryRecord.id.desc()).limit(limit)
        if status:
            query = query.where(EventDeliveryRecord.status == status)
        with self.database.session() as session:
            return list(session.scalars(query).all())

    def attempt_delivery(self, delivery_id: int) -> EventDeliveryRecord:
        with self.database.session() as session:
            delivery = session.get(EventDeliveryRecord, delivery_id)
            if delivery is None:
                raise KeyError("delivery_not_found")
            if delivery.status == "delivered":
                return delivery

            event = session.get(EventRecord, delivery.event_id)
            subscription = session.get(EventSubscriptionRecord, delivery.subscription_id)
            if event is None or subscription is None:
                delivery.status = "dead"
                delivery.last_error = "event_or_subscription_not_found"
                delivery.updated_at = datetime.now(UTC)
                session.commit()
                session.refresh(delivery)
                return delivery
            if not subscription.enabled:
                delivery.status = "dead"
                delivery.last_error = "subscription_disabled"
                delivery.updated_at = datetime.now(UTC)
                session.commit()
                session.refresh(delivery)
                return delivery

            envelope = event_envelope(event)
            body = json.dumps(
                envelope,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "X-Lyra-Event-Id": event.event_id,
            }
            secret = self.secrets.get(subscription.secret_ref)
            if subscription.secret_ref:
                if not secret:
                    return self._record_failure(
                        session,
                        delivery,
                        subscription,
                        error="webhook_secret_not_configured",
                    )
                digest = hmac.new(
                    secret.encode("utf-8"),
                    body,
                    hashlib.sha256,
                ).hexdigest()
                headers["X-Lyra-Signature"] = f"sha256={digest}"

            try:
                with httpx.Client(
                    timeout=self.timeout_seconds,
                    transport=self.transport,
                ) as client:
                    response = client.post(
                        subscription.endpoint_url,
                        headers=headers,
                        content=body,
                    )
                if 200 <= response.status_code < 300:
                    delivery.attempt_count += 1
                    delivery.status = "delivered"
                    delivery.last_status_code = response.status_code
                    delivery.last_error = None
                    delivery.next_attempt_at = None
                    delivery.delivered_at = datetime.now(UTC)
                    delivery.updated_at = datetime.now(UTC)
                    session.commit()
                    session.refresh(delivery)
                    return delivery
                return self._record_failure(
                    session,
                    delivery,
                    subscription,
                    status_code=response.status_code,
                    error=f"webhook_http_{response.status_code}",
                )
            except httpx.HTTPError as exc:
                return self._record_failure(
                    session,
                    delivery,
                    subscription,
                    error=f"{type(exc).__name__}: {exc}",
                )

    @staticmethod
    def _record_failure(
        session,
        delivery: EventDeliveryRecord,
        subscription: EventSubscriptionRecord,
        *,
        error: str,
        status_code: int | None = None,
    ) -> EventDeliveryRecord:
        attempt = delivery.attempt_count + 1
        delivery.attempt_count = attempt
        delivery.last_status_code = status_code
        delivery.last_error = error[:2000]
        delivery.updated_at = datetime.now(UTC)
        if attempt >= subscription.max_attempts:
            delivery.status = "dead"
            delivery.next_attempt_at = None
        else:
            delay_seconds = min(3600, 30 * (2 ** (attempt - 1)))
            delivery.status = "retry"
            delivery.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
        session.commit()
        session.refresh(delivery)
        return delivery


def event_envelope(event: EventRecord) -> dict[str, Any]:
    occurred_at = event.occurred_at
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    return {
        "schemaVersion": "1.0",
        "eventId": event.event_id,
        "eventType": event.event_type,
        "eventVersion": event.event_version,
        "occurredAt": occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "source": {"type": event.source_type, "id": event.source_id},
        "tenantId": event.tenant_id,
        "actorId": event.actor_id,
        "subject": event.subject,
        "correlationId": event.correlation_id,
        "causationId": event.causation_id,
        "data": event.data,
    }


def _event_type_matches(pattern: str, event_type: str) -> bool:
    normalized = pattern.strip().lower()
    candidate = event_type.strip().lower()
    if normalized == "*":
        return True
    if normalized.endswith(".*"):
        prefix = normalized[:-2]
        return candidate.startswith(prefix + ".")
    return normalized == candidate
