from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator[datetime]):
    """Store timestamps in UTC and return timezone-aware values on every database."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)


class ApplicationStateRecord(Base):
    __tablename__ = "application_state"

    app_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ApplicationConfigRecord(Base):
    __tablename__ = "application_config"

    app_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name_override: Mapped[str | None] = mapped_column(String(120), nullable=True)
    navigation_group: Mapped[str | None] = mapped_column(String(80), nullable=True)
    navigation_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    visible_roles_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    default_launch_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="workspace")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    @property
    def visible_roles(self) -> list[str]:
        value = json.loads(self.visible_roles_json)
        return [str(item) for item in value] if isinstance(value, list) else []


class ApplicationPageItemRecord(Base):
    __tablename__ = "application_page_item"

    app_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    page_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    title_override: Mapped[str | None] = mapped_column(String(120), nullable=True)
    navigation_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    visible_roles_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    @property
    def visible_roles(self) -> list[str]:
        value = json.loads(self.visible_roles_json)
        return [str(item) for item in value] if isinstance(value, list) else []


class PluginStateRecord(Base):
    __tablename__ = "plugin_state"

    plugin_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    granted_permissions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    @property
    def granted_permissions(self) -> list[str]:
        value = json.loads(self.granted_permissions_json)
        return [str(item) for item in value] if isinstance(value, list) else []


class PlatformConnectionRecord(Base):
    __tablename__ = "platform_connection"

    service_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    current_json: Mapped[str] = mapped_column(Text, nullable=False)
    last_good_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class AuditEventRecord(Base):
    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json)


class EventRecord(Base):
    __tablename__ = "event_record"

    event_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    event_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(240), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    causation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    data_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )

    @property
    def data(self) -> dict[str, Any]:
        value = json.loads(self.data_json)
        return value if isinstance(value, dict) else {}


class EventSubscriptionRecord(Base):
    __tablename__ = "event_subscription"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscriber_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    endpoint_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    secret_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class EventDeliveryRecord(Base):
    __tablename__ = "event_delivery"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    subscription_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class MaintenanceScheduleRecord(Base):
    __tablename__ = "maintenance_schedule"

    schedule_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    service_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class MaintenanceCheckRecord(Base):
    __tablename__ = "maintenance_check"

    check_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    schedule_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    service_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    check_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)

    @property
    def details(self) -> dict[str, Any]:
        value = json.loads(self.details_json)
        return value if isinstance(value, dict) else {}


class MaintenanceAlertRecord(Base):
    __tablename__ = "maintenance_alert"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_maintenance_alert_fingerprint"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fingerprint: Mapped[str] = mapped_column(String(240), nullable=False)
    service_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    check_name: Mapped[str] = mapped_column(String(120), nullable=False)
    error_code: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open", index=True)
    first_check_id: Mapped[str] = mapped_column(String(120), nullable=False)
    last_check_id: Mapped[str] = mapped_column(String(120), nullable=False)
    recovery_check_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False)
    first_occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class MaintenanceRepairAuditRecord(Base):
    __tablename__ = "maintenance_repair_audit"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    service_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    target_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)

    @property
    def details(self) -> dict[str, Any]:
        value = json.loads(self.details_json)
        return value if isinstance(value, dict) else {}


class MaintenanceWorkerLeaseRecord(Base):
    __tablename__ = "maintenance_worker_lease"

    lease_name: Mapped[str] = mapped_column(String(120), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(120), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)


class Database:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.getenv("LYRA_HUB_DATABASE_URL", "sqlite:///./lyra-hub.db")
        connect_args: dict[str, Any] = {}
        if self.url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        self.engine = create_engine(self.url, connect_args=connect_args)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
        finally:
            session.close()


def record_audit(
    session: Session,
    *,
    action: str,
    target_type: str,
    target_id: str,
    payload: dict[str, Any] | None = None,
) -> AuditEventRecord:
    event = AuditEventRecord(
        action=action,
        target_type=target_type,
        target_id=target_id,
        payload_json=json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
    )
    session.add(event)
    return event
