"""Standalone tool gateway service (ADR-0004)."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import ValidationError

from ..auth import (
    BearerAuthMiddleware,
    OidcAuthMiddleware,
    bind_principal,
    resolve_http_auth,
)
from ..core import IdentityProvider, ToolGatewayRequest
from ..metrics import MetricsRegistry
from .gateway import FunctionToolGateway, ToolDenied
from .policy import GrantPolicyEngine

logger = logging.getLogger(__name__)


def build_tool_gateway_app(
    gateway: FunctionToolGateway,
    *,
    host: str = "127.0.0.1",
    auth_token: str | None = None,
    allow_unauthenticated: bool = False,
    oidc: IdentityProvider | None = None,
    metrics: MetricsRegistry | None = None,
) -> FastAPI:
    """Build the tool gateway app. Every path except /healthz needs the token."""
    token = resolve_http_auth(host, auth_token, allow_unauthenticated) if oidc is None else None
    metrics = metrics if metrics is not None else MetricsRegistry()
    app = FastAPI(title="ADK Tool Gateway", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics_endpoint() -> PlainTextResponse:
        return PlainTextResponse(
            metrics.render(), media_type="text/plain; version=0.0.4; charset=utf-8"
        )

    @app.post("/v1/invoke")
    async def invoke(request: Request) -> JSONResponse:
        try:
            body: Any = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid json"}, status_code=400)
        try:
            call = ToolGatewayRequest.model_validate(body)
        except ValidationError:
            return JSONResponse({"error": "invalid request"}, status_code=400)

        invocation = call.invocation
        bound = bind_principal(request, invocation.principal)
        if bound is None:
            return JSONResponse({"error": "principal_mismatch"}, status_code=403)
        invocation = invocation.model_copy(update={"principal": bound})

        policy = GrantPolicyEngine(call.grants)
        tool_id = call.request.tool_id
        started = time.perf_counter()
        try:
            response = await gateway.invoke(invocation, call.request, policy)
        except ToolDenied:
            _record_tool_call(metrics, tool_id, "denied", started)
            return JSONResponse({"error": "tool_denied"}, status_code=403)
        except Exception:  # noqa: BLE001
            _record_tool_call(metrics, tool_id, "error", started)
            logger.exception("tool gateway execution failure")
            return JSONResponse({"error": "tool_call_failed"}, status_code=502)
        _record_tool_call(metrics, tool_id, "ok", started)

        try:
            payload = response.model_dump(mode="json")
        except Exception:  # noqa: BLE001
            logger.exception("tool output is not JSON serializable")
            return JSONResponse({"error": "tool_output_invalid"}, status_code=502)
        return JSONResponse(payload)

    if oidc is not None:
        app.add_middleware(OidcAuthMiddleware, provider=oidc, open_paths=frozenset({"/healthz"}))
    elif token:
        app.add_middleware(BearerAuthMiddleware, token=token, open_paths=frozenset({"/healthz"}))
    return app


def _record_tool_call(metrics: MetricsRegistry, tool: str, status: str, started: float) -> None:
    metrics.inc("adk_tool_calls_total", {"tool": tool, "status": status})
    metrics.observe(
        "adk_tool_call_duration_seconds",
        time.perf_counter() - started,
        {"tool": tool},
    )


__all__ = ["build_tool_gateway_app"]
