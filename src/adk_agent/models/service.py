"""Standalone model gateway service (ADR-0004)."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Sequence
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
from ..core import IdentityProvider, ModelGatewayRequest, ModelProvider
from ..metrics import MetricsRegistry
from ..ratelimit import RateLimit, RateLimitMiddleware, build_rate_limiter
from .gateway import ModelDenied, ModelUnavailable, PolicyModelGateway
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
    oidc: IdentityProvider | None = None,
    metrics: MetricsRegistry | None = None,
    rate_limit: RateLimit | None = None,
) -> FastAPI:
    """Build the gateway app. Every path except /healthz needs the token."""
    token = resolve_http_auth(host, auth_token, allow_unauthenticated) if oidc is None else None
    metrics = metrics if metrics is not None else MetricsRegistry()
    app = FastAPI(title="ADK Model Gateway", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics_endpoint() -> PlainTextResponse:
        return PlainTextResponse(
            metrics.render(), media_type="text/plain; version=0.0.4; charset=utf-8"
        )

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

        invocation = call.invocation
        bound = bind_principal(request, invocation.principal)
        if bound is None:
            return JSONResponse({"error": "principal_mismatch"}, status_code=403)
        invocation = invocation.model_copy(update={"principal": bound})

        provider = call.request.provider
        started = time.perf_counter()
        try:
            response = await gateway.complete(invocation, call.request, call.policy)
        except ModelUnavailable:
            _record_model_call(metrics, provider, "error", started)
            return JSONResponse({"error": "model_unavailable"}, status_code=503)
        except ModelDenied:
            _record_model_call(metrics, provider, "denied", started)
            return JSONResponse({"error": "model_denied"}, status_code=403)
        except Exception:  # noqa: BLE001
            _record_model_call(metrics, provider, "error", started)
            logger.exception("model gateway provider failure")
            return JSONResponse({"error": "model_call_failed"}, status_code=502)
        _record_model_call(metrics, provider, "ok", started)

        return JSONResponse(response.model_dump(mode="json"))

    if rate_limit is not None:
        app.add_middleware(
            RateLimitMiddleware,
            limiter=build_rate_limiter(rate_limit, surface="model_gateway", metrics=metrics),
            surface="model_gateway",
            exempt=frozenset({"/healthz", "/metrics"}),
            metrics=metrics,
        )
    if oidc is not None:
        app.add_middleware(OidcAuthMiddleware, provider=oidc, open_paths=frozenset({"/healthz"}))
    elif token:
        app.add_middleware(BearerAuthMiddleware, token=token, open_paths=frozenset({"/healthz"}))
    return app


def _record_model_call(
    metrics: MetricsRegistry, provider: str, status: str, started: float
) -> None:
    metrics.inc("adk_model_calls_total", {"provider": provider, "status": status})
    metrics.observe(
        "adk_model_call_duration_seconds",
        time.perf_counter() - started,
        {"provider": provider},
    )


__all__ = ["build_model_gateway_app", "build_providers"]
