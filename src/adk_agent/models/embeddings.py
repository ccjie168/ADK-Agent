"""Embedding gateway: allowlist, per-tenant budget, and audit (ADR-0035)."""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Literal

from ..core import (
    AuditEvent,
    AuditSink,
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingResponse,
    Invocation,
    ModelPolicy,
)
from .budget import BudgetTracker
from .gateway import ModelDenied, check_provider


class EmbeddingGateway:
    """Check the provider allowlist and the tenant budget, embed, and audit."""

    def __init__(
        self,
        providers: Mapping[str, EmbeddingProvider],
        audit: AuditSink | None = None,
        *,
        budgets: BudgetTracker | None = None,
    ) -> None:
        for name, provider in providers.items():
            if name != provider.name:
                raise ValueError(
                    f"provider key {name!r} does not match provider.name {provider.name!r}"
                )
        self.providers = dict(providers)
        self.audit = audit
        self.budgets = budgets

    async def embed(
        self, invocation: Invocation, request: EmbeddingRequest, policy: ModelPolicy
    ) -> EmbeddingResponse:
        started = time.perf_counter()
        try:
            check_provider(request.provider, policy)
        except ModelDenied:
            await self._audit(
                invocation,
                request,
                status="denied",
                error_code="provider_not_allowed",
                egress="none",
                tokens=None,
                cost_usd=None,
                started=started,
            )
            raise

        provider = self.providers.get(request.provider)
        if provider is None:
            await self._audit(
                invocation,
                request,
                status="denied",
                error_code="provider_unavailable",
                egress="none",
                tokens=None,
                cost_usd=None,
                started=started,
            )
            raise ModelDenied(f"provider {request.provider!r} is not configured")

        tenant = invocation.principal.tenant
        if (
            self.budgets is not None
            and policy.budget_usd is not None
            and self.budgets.spent(tenant) >= policy.budget_usd
        ):
            await self._audit(
                invocation,
                request,
                status="denied",
                error_code="budget_exceeded",
                egress="none",
                tokens=None,
                cost_usd=None,
                started=started,
            )
            raise ModelDenied(f"tenant {tenant!r} has spent its model budget")

        try:
            response = await provider.embed(request)
        except Exception as exc:
            await self._audit(
                invocation,
                request,
                status="error",
                error_code=type(exc).__name__,
                egress=provider.egress,
                tokens=None,
                cost_usd=None,
                started=started,
            )
            raise

        if self.budgets is not None and response.cost_usd:
            self.budgets.add(tenant, response.cost_usd)
        await self._audit(
            invocation,
            request,
            status="ok",
            error_code=None,
            egress=response.egress,
            tokens=response.input_tokens,
            cost_usd=response.cost_usd,
            started=started,
        )
        return response

    async def _audit(
        self,
        invocation: Invocation,
        request: EmbeddingRequest,
        *,
        status: Literal["ok", "error", "denied"],
        error_code: str | None,
        egress: Literal["none", "third_party"],
        tokens: int | None,
        cost_usd: float | None,
        started: float,
    ) -> None:
        if self.audit is None:
            return
        await self.audit.emit(
            AuditEvent(
                event_id=uuid.uuid4().hex,
                run_id=invocation.run_id,
                trace_id=invocation.trace_id,
                tenant=invocation.principal.tenant,
                principal=invocation.principal,
                agent_ref=invocation.agent_ref,
                action="model.embed",
                target=f"{request.provider}:{request.model}",
                tokens=tokens,
                cost_usd=cost_usd,
                egress=egress,
                status=status,
                error_code=error_code,
                latency_ms=int((time.perf_counter() - started) * 1000),
                timestamp=datetime.now(timezone.utc),
            )
        )


__all__ = ["EmbeddingGateway"]
