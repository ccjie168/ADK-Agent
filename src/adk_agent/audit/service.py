"""Standalone audit pipeline service (ADR-0006)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..auth import BearerAuthMiddleware, resolve_http_auth
from ..core import AuditEvent

logger = logging.getLogger(__name__)


def build_audit_pipeline_app(
    pipeline: Any,
    *,
    host: str = "127.0.0.1",
    auth_token: str | None = None,
    allow_unauthenticated: bool = False,
) -> FastAPI:
    """Build the audit service. Every path except /healthz needs the token."""
    token = resolve_http_auth(host, auth_token, allow_unauthenticated)
    app = FastAPI(title="ADK Audit Pipeline", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/events")
    async def emit(request: Request) -> JSONResponse:
        try:
            body: Any = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid json"}, status_code=400)
        try:
            event = AuditEvent.model_validate(body)
        except ValidationError:
            return JSONResponse({"error": "invalid event"}, status_code=400)

        try:
            record = await pipeline.append(event)
        except Exception:  # noqa: BLE001
            logger.exception("audit pipeline write failure")
            return JSONResponse({"error": "audit_write_failed"}, status_code=502)
        return JSONResponse({"hash": record.hash}, status_code=202)

    if token:
        app.add_middleware(BearerAuthMiddleware, token=token, open_paths=frozenset({"/healthz"}))
    return app


__all__ = ["build_audit_pipeline_app"]
