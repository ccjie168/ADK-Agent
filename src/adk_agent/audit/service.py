"""Standalone audit pipeline service (ADR-0006)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..auth import (
    BearerAuthMiddleware,
    OidcAuthMiddleware,
    bind_principal,
    resolve_http_auth,
)
from ..core import AuditEvent, IdentityProvider
from ..ratelimit import RateLimit, RateLimitMiddleware, build_rate_limiter
from .pipeline import query_events

logger = logging.getLogger(__name__)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone required")
    return parsed


def build_audit_pipeline_app(
    pipeline: Any,
    *,
    query: Callable[..., Awaitable[list[AuditEvent]]] | None = None,
    host: str = "127.0.0.1",
    auth_token: str | None = None,
    allow_unauthenticated: bool = False,
    oidc: IdentityProvider | None = None,
    rate_limit: RateLimit | None = None,
) -> FastAPI:
    """Build the audit service. Every path except /healthz needs the token."""
    token = resolve_http_auth(host, auth_token, allow_unauthenticated) if oidc is None else None
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

        bound = bind_principal(request, event.principal)
        if bound is None:
            return JSONResponse({"error": "principal_mismatch"}, status_code=403)
        event = event.model_copy(update={"principal": bound})

        try:
            record = await pipeline.append(event)
        except Exception:  # noqa: BLE001
            logger.exception("audit pipeline write failure")
            return JSONResponse({"error": "audit_write_failed"}, status_code=502)
        return JSONResponse({"hash": record.hash}, status_code=202)

    @app.get("/v1/events")
    async def read_events(
        request: Request,
        tenant: str | None = None,
        trace_id: str | None = None,
        run_id: str | None = None,
        action: str | None = None,
        status: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: str | None = None,
        order: str = "desc",
        before_timestamp: str | None = None,
        before_event_id: str | None = None,
    ) -> JSONResponse:
        try:
            parsed_limit = 100 if limit is None else int(limit)
        except ValueError:
            return JSONResponse({"error": "invalid_limit"}, status_code=400)
        if not 1 <= parsed_limit <= 1000:
            return JSONResponse({"error": "invalid_limit"}, status_code=400)
        if order not in {"asc", "desc"}:
            return JSONResponse({"error": "invalid_order"}, status_code=400)
        if status is not None and status not in {"ok", "error", "denied"}:
            return JSONResponse({"error": "invalid_status"}, status_code=400)
        try:
            since_time = _parse_time(since) if since is not None else None
            until_time = _parse_time(until) if until is not None else None
        except ValueError:
            return JSONResponse({"error": "invalid_time"}, status_code=400)
        if (before_timestamp is None) != (before_event_id is None):
            return JSONResponse({"error": "invalid_cursor"}, status_code=400)
        before: tuple[datetime, str] | None = None
        if before_timestamp is not None and before_event_id is not None:
            if order != "desc" or not before_event_id:
                return JSONResponse({"error": "invalid_cursor"}, status_code=400)
            try:
                before = (_parse_time(before_timestamp), before_event_id)
            except ValueError:
                return JSONResponse({"error": "invalid_cursor"}, status_code=400)

        principal = getattr(request.state, "principal", None)
        if principal is not None:
            if tenant is None:
                tenant = principal.tenant
            elif tenant != principal.tenant and "admin" not in principal.roles:
                return JSONResponse({"error": "tenant_forbidden"}, status_code=403)

        try:
            if query is not None:
                events = await query(
                    tenant=tenant,
                    trace_id=trace_id,
                    run_id=run_id,
                    action=action,
                    status=status,
                    since=since_time,
                    until=until_time,
                    limit=parsed_limit,
                    order=order,
                    before=before,
                )
            else:
                events = query_events(
                    pipeline.path,
                    tenant=tenant,
                    trace_id=trace_id,
                    run_id=run_id,
                    action=action,
                    status=status,
                    since=since_time,
                    until=until_time,
                    limit=parsed_limit,
                    order=order,
                    before=before,
                )
        except Exception:  # noqa: BLE001
            logger.exception("audit query read failure")
            return JSONResponse({"error": "audit_read_failed"}, status_code=502)
        return JSONResponse(
            {"events": [event.model_dump(mode="json") for event in events], "count": len(events)}
        )

    if rate_limit is not None:
        app.add_middleware(
            RateLimitMiddleware,
            limiter=build_rate_limiter(rate_limit, surface="audit"),
            surface="audit",
        )
    if oidc is not None:
        app.add_middleware(OidcAuthMiddleware, provider=oidc, open_paths=frozenset({"/healthz"}))
    elif token:
        app.add_middleware(BearerAuthMiddleware, token=token, open_paths=frozenset({"/healthz"}))
    return app


__all__ = ["build_audit_pipeline_app"]
