"""Standalone tool gateway service (ADR-0004)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..auth import BearerAuthMiddleware, resolve_http_auth
from ..core import ToolGatewayRequest
from .gateway import FunctionToolGateway, ToolDenied
from .policy import GrantPolicyEngine

logger = logging.getLogger(__name__)


def build_tool_gateway_app(
    gateway: FunctionToolGateway,
    *,
    host: str = "127.0.0.1",
    auth_token: str | None = None,
    allow_unauthenticated: bool = False,
) -> FastAPI:
    """Build the tool gateway app. Every path except /healthz needs the token."""
    token = resolve_http_auth(host, auth_token, allow_unauthenticated)
    app = FastAPI(title="ADK Tool Gateway", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

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

        policy = GrantPolicyEngine(call.grants)
        try:
            response = await gateway.invoke(call.invocation, call.request, policy)
        except ToolDenied:
            return JSONResponse({"error": "tool_denied"}, status_code=403)
        except Exception:  # noqa: BLE001
            logger.exception("tool gateway execution failure")
            return JSONResponse({"error": "tool_call_failed"}, status_code=502)

        try:
            payload = response.model_dump(mode="json")
        except Exception:  # noqa: BLE001
            logger.exception("tool output is not JSON serializable")
            return JSONResponse({"error": "tool_output_invalid"}, status_code=502)
        return JSONResponse(payload)

    if token:
        app.add_middleware(BearerAuthMiddleware, token=token, open_paths=frozenset({"/healthz"}))
    return app


__all__ = ["build_tool_gateway_app"]
