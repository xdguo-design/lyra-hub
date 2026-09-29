from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


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
