"""Standalone model gateway service (ADR-0004)."""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..auth import BearerAuthMiddleware, resolve_http_auth
from ..core import ModelGatewayRequest, ModelProvider
from .gateway import ModelDenied, PolicyModelGateway
from .providers import LiteLlmProvider, VllmProvider

logger = logging.getLogger(__name__)


def build_providers(
    names: Sequence[str], *, vllm_url: str | None = None
) -> dict[str, ModelProvider]:
    """Build the provider adapters the gateway process should serve."""
    if not names:
        raise ValueError("at least one --provider is required")
    providers: dict[str, ModelProvider] = {}
    for name in names:
        if name == "litellm":
            providers[name] = LiteLlmProvider(
                api_key=os.environ.get("LITELLM_API_KEY"),
                api_base=os.environ.get("LITELLM_API_BASE"),
            )
        elif name == "vllm":
            url = vllm_url or os.environ.get("VLLM_BASE_URL")
            if not url:
                raise ValueError("vllm needs --vllm-url or VLLM_BASE_URL")
            providers[name] = VllmProvider(url)
        else:
            raise ValueError(f"unknown provider {name!r}")
    return providers


def build_model_gateway_app(
    gateway: PolicyModelGateway,
    *,
    host: str = "127.0.0.1",
    auth_token: str | None = None,
    allow_unauthenticated: bool = False,
) -> FastAPI:
    """Build the gateway app. Every path except /healthz needs the token."""
    token = resolve_http_auth(host, auth_token, allow_unauthenticated)
    app = FastAPI(title="ADK Model Gateway", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/complete")
    async def complete(request: Request) -> JSONResponse:
        try:
            body: Any = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid json"}, status_code=400)
        try:
            call = ModelGatewayRequest.model_validate(body)
        except ValidationError:
            return JSONResponse({"error": "invalid request"}, status_code=400)

        try:
            response = await gateway.complete(call.invocation, call.request, call.policy)
        except ModelDenied:
            return JSONResponse({"error": "model_denied"}, status_code=403)
        except Exception:  # noqa: BLE001
            logger.exception("model gateway provider failure")
            return JSONResponse({"error": "model_call_failed"}, status_code=502)

        return JSONResponse(response.model_dump(mode="json"))

    if token:
        app.add_middleware(BearerAuthMiddleware, token=token, open_paths=frozenset({"/healthz"}))
    return app


__all__ = ["build_model_gateway_app", "build_providers"]
