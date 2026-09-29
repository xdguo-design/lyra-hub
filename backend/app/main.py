from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import applications
from app.domain.applications.registry import ManifestRegistry


def create_app(repo_root: Path | None = None) -> FastAPI:
    resolved_root = repo_root or Path(__file__).resolve().parents[2]
    registry = ManifestRegistry(resolved_root)

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

    @api.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "lyra-hub"}

    api.include_router(applications.router, prefix="/api/v1")
    return api


app = create_app()
