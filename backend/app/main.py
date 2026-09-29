from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.routes import applications, audit, capabilities, page_configuration
from app.domain.applications.registry import ManifestRegistry
from app.infrastructure.database import Database
from app.infrastructure.platforms import PlatformServices, PlatformSettings


def create_app(
    repo_root: Path | None = None,
    database_url: str | None = None,
    platform_settings: PlatformSettings | None = None,
    platform_transport: httpx.BaseTransport | None = None,
) -> FastAPI:
    resolved_root = repo_root or Path(__file__).resolve().parents[2]
    registry = ManifestRegistry(resolved_root)
    database = Database(database_url)
    database.initialize()
    platform_services = PlatformServices(platform_settings, platform_transport)

    api = FastAPI(
        title="Lyra Hub API",
        version="0.1.0",
        description="Control plane API for the Lyra AI application hub.",
    )
    api.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api.dependency_overrides[applications.get_registry] = lambda: registry
    api.dependency_overrides[applications.get_database] = lambda: database
    api.dependency_overrides[audit.get_database] = lambda: database
    api.dependency_overrides[page_configuration.get_registry] = lambda: registry
    api.dependency_overrides[page_configuration.get_database] = lambda: database
    api.dependency_overrides[capabilities.get_platform_services] = lambda: platform_services

    @api.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "lyra-hub"}

    @api.get("/ready", tags=["system"])
    def ready() -> dict[str, str | int]:
        registered = len(registry.list())
        with database.session() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ready", "registered_applications": registered}

    api.include_router(applications.router, prefix="/api/v1")
    api.include_router(page_configuration.router, prefix="/api/v1")
    api.include_router(capabilities.router, prefix="/api/v1")
    api.include_router(audit.router, prefix="/api/v1")
    return api


app = create_app()
