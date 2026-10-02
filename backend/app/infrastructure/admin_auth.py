from __future__ import annotations

import os
import secrets

from fastapi.security import HTTPAuthorizationCredentials


class AdminTokenAuth:
    def __init__(self, token: str | None = None) -> None:
        self.token = token if token is not None else os.getenv("LYRA_HUB_ADMIN_TOKEN", "")

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def verify(self, credentials: HTTPAuthorizationCredentials | None) -> bool:
        if not self.token or credentials is None:
            return False
        if credentials.scheme.lower() != "bearer":
            return False
        return secrets.compare_digest(credentials.credentials, self.token)
