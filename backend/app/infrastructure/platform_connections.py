from __future__ import annotations

import json
import os
from dataclasses import replace
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status
from sqlalchemy import select

from app.infrastructure.database import Database, PlatformConnectionRecord
from app.infrastructure.platforms import PlatformSettings

SERVICE_FIELDS = {
    "gateway": ("gateway_url", "gateway_token"),
    "agent-os": ("agent_os_url", "agent_os_token"),
}


def _fernet(*, required: bool = False) -> Fernet | None:
    key = os.getenv("LYRA_HUB_SECRET_KEY", "").strip()
    if not key:
        if required:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="LYRA_HUB_SECRET_KEY must be configured before saving platform credentials",
            )
        return None
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LYRA_HUB_SECRET_KEY is invalid",
        ) from exc


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    cipher = _fernet(required=True)
    assert cipher is not None
    return cipher.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    cipher = _fernet(required=True)
    assert cipher is not None
    try:
        return cipher.decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeEncodeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Saved platform credential cannot be decrypted; verify LYRA_HUB_SECRET_KEY",
        ) from exc


def serialize_connection(service_id: str, base_url: str, token: str) -> str:
    return json.dumps(
        {"base_url": base_url.rstrip("/"), "token_encrypted": encrypt_secret(token)},
        separators=(",", ":"),
        sort_keys=True,
    )


def deserialize_connection(serialized: str) -> tuple[str, str]:
    data = json.loads(serialized)
    return str(data["base_url"]).rstrip("/"), decrypt_secret(str(data.get("token_encrypted", "")))


def load_saved_settings(database: Database, settings: PlatformSettings) -> PlatformSettings:
    updates: dict[str, str] = {}
    with database.session() as session:
        records = session.scalars(select(PlatformConnectionRecord)).all()
        for record in records:
            fields = SERVICE_FIELDS.get(record.service_id)
            if not fields:
                continue
            base_url, token = deserialize_connection(record.current_json)
            updates[fields[0]] = base_url
            updates[fields[1]] = token
    return replace(settings, **updates)


def connection_snapshot(service_id: str, base_url: str, token: str, revision: int, *, source: str) -> dict[str, Any]:
    return {
        "service_id": service_id,
        "base_url": base_url,
        "credential_configured": bool(token),
        "revision": revision,
        "source": source,
    }
