from __future__ import annotations

import json
import os
import secrets


class IntegrationTokenRegistry:
    def __init__(self, tokens: dict[str, str] | None = None) -> None:
        self._tokens = {
            str(app_id): str(token)
            for app_id, token in (tokens or {}).items()
            if str(app_id).strip() and str(token)
        }

    @classmethod
    def from_env(cls) -> IntegrationTokenRegistry:
        raw = os.getenv("LYRA_APP_TOKENS_JSON", "").strip()
        if not raw:
            return cls()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("LYRA_APP_TOKENS_JSON must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("LYRA_APP_TOKENS_JSON must be a JSON object")
        return cls({str(key): str(value) for key, value in payload.items()})

    def is_configured(self, app_id: str) -> bool:
        return app_id in self._tokens

    def verify_bearer(self, app_id: str, authorization: str | None) -> bool:
        expected = self._tokens.get(app_id)
        if expected is None or not authorization:
            return False
        scheme, _, credential = authorization.partition(" ")
        if scheme.lower() != "bearer" or not credential:
            return False
        return secrets.compare_digest(credential, expected)
