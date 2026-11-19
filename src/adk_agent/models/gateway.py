"""Policy-enforcing model gateway with audit."""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Literal

from ..audit.hashing import hash_json, hash_text
from ..core import (
    AuditEvent,
    AuditSink,
    DataClass,
    Invocation,
    ModelPolicy,
    ModelProvider,
    ModelRequest,
    ModelResponse,
)
from ..guardrails import GuardrailPipeline
from ..observability import model_span, record_error, record_usage


class ModelDenied(Exception):
    """The request is not allowed by the agent's model policy."""


class ModelUnavailable(RuntimeError):
    """The provider's circuit is open, so the call was not attempted."""


def egress_for(provider: str) -> Literal["none", "third_party"]:
    return "none" if provider == "vllm" else "third_party"


def check_provider(provider: str, policy: ModelPolicy) -> None:
    if provider not in policy.provider_allowlist:
        raise ModelDenied(f"provider {provider!r} is not allowed by policy")


def hash_messages(request: ModelRequest) -> str:
    return hash_json([message.model_dump() for message in request.messages])


async def emit_model_audit(
    audit: AuditSink | None,
    invocation: Invocation,
    *,
    provider: str,
    model: str,
    args_hash: str,
    result_hash: str | None,
    tokens: int | None,
    cost_usd: float | None,
    egress: Literal["none", "third_party"],
    status: Literal["ok", "error", "denied"],
    error_code: str | None,
    started: float,
) -> None:
    if audit is None:
        return
    event = AuditEvent(
        event_id=uuid.uuid4().hex,
        run_id=invocation.run_id,
        trace_id=invocation.trace_id,
        tenant=invocation.principal.tenant,
        principal=invocation.principal,
        agent_ref=invocation.agent_ref,
        action="model.call",
        target=f"{provider}:{model}",
        args_hash=args_hash,
        result_hash=result_hash,
        data_classes=[],
        latency_ms=int((time.perf_counter() - started) * 1000),
        tokens=tokens,
        cost_usd=cost_usd,
        egress=egress,
        status=status,
        error_code=error_code,
        timestamp=datetime.now(timezone.utc),
    )
    await audit.emit(event)


class PolicyModelGateway:
    """Check the provider allowlist, call the provider, and audit the outcome."""

    def __init__(
        self,
        providers: Mapping[str, ModelProvider],
        audit: AuditSink | None = None,
        *,
        guardrails: GuardrailPipeline | None = None,
    ) -> None:
        for name, provider in providers.items():
            if name != provider.name:
                raise ValueError(
                    f"provider key {name!r} does not match provider.name {provider.name!r}"
                )
        self.providers = dict(providers)
        self.audit = audit
        self.guardrails = guardrails

    async def complete(
        self,
        invocation: Invocation,
        request: ModelRequest,
        policy: ModelPolicy,
        *,
        alias: str | None = None,
        data_classes: list[DataClass] | None = None,
    ) -> ModelResponse:
        """Complete through the direct provider/model, or through an alias's candidates.

        With an alias, candidates are tried in order and a failed candidate falls
        over to the next one; only a policy denial stops routing (ADR-0033).
        """
        if alias is None:
            return await self._complete_once(invocation, request, policy)
        # Imported here: routing imports ModelDenied from this module.
        from .routing import resolve_candidates

        candidates = resolve_candidates(policy, alias, data_classes or [])
        last_error: Exception | None = None
        for candidate in candidates:
            routed = request.model_copy(
                update={"provider": candidate.provider, "model": candidate.model}
            )
            try:
                return await self._complete_once(invocation, routed, policy)
            except ModelDenied:
                raise
            except Exception as exc:
                last_error = exc
        raise ModelUnavailable(f"every candidate for alias {alias!r} failed") from last_error

    async def _complete_once(
        self,
        invocation: Invocation,
        request: ModelRequest,
        policy: ModelPolicy,
    ) -> ModelResponse:
        started = time.perf_counter()
        if self.guardrails is not None:
            request = await self._guard_input(invocation, request)
        args_hash = hash_messages(request)
        try:
            check_provider(request.provider, policy)
        except ModelDenied:
            await emit_model_audit(
                self.audit,
                invocation,
                provider=request.provider,
                model=request.model,
                args_hash=args_hash,
                result_hash=None,
                tokens=None,
                cost_usd=None,
                egress="none",
                status="denied",
                error_code="provider_not_allowed",
                started=started,
            )
            raise

        provider = self.providers.get(request.provider)
        if provider is None:
            await emit_model_audit(
                self.audit,
                invocation,
                provider=request.provider,
                model=request.model,
                args_hash=args_hash,
                result_hash=None,
                tokens=None,
                cost_usd=None,
                egress="none",
                status="denied",
                error_code="provider_unavailable",
                started=started,
            )
            raise ModelDenied(f"provider {request.provider!r} is not configured")

        try:
            with model_span(invocation, provider=request.provider, model=request.model) as span:
                try:
                    response = await provider.complete(request)
                except Exception as exc:
                    record_error(span, getattr(exc, "error_code", type(exc).__name__))
                    raise
        except Exception as exc:
            await emit_model_audit(
                self.audit,
                invocation,
                provider=request.provider,
                model=request.model,
                args_hash=args_hash,
                result_hash=None,
                tokens=None,
                cost_usd=None,
                egress=provider.egress,
                status="error",
                error_code=type(exc).__name__,
                started=started,
            )
            raise

        if self.guardrails is not None:
            response = await self._guard_output(invocation, response)
        record_usage(
            span,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
        )
        await emit_model_audit(
            self.audit,
            invocation,
            provider=request.provider,
            model=request.model,
            args_hash=args_hash,
            result_hash=hash_text(response.text),
            tokens=response.input_tokens + response.output_tokens,
            cost_usd=response.cost_usd,
            egress=provider.egress,
            status="ok",
            error_code=None,
            started=started,
        )
        return response

    async def _guard_input(self, invocation: Invocation, request: ModelRequest) -> ModelRequest:
        guardrails = self.guardrails
        if guardrails is None:
            return request
        messages = []
        for message in request.messages:
            result = guardrails.check(message.content, direction="input")
            if result.blocked_by is not None:
                await self._emit_guardrail(
                    invocation, "input", [result.blocked_by], True, message.content
                )
                raise ModelDenied(f"guardrail blocked input at {result.blocked_by}")
            if result.redacted_by:
                await self._emit_guardrail(
                    invocation, "input", result.redacted_by, False, message.content
                )
            messages.append(message.model_copy(update={"content": result.text}))
        return request.model_copy(update={"messages": messages})

    async def _guard_output(self, invocation: Invocation, response: ModelResponse) -> ModelResponse:
        guardrails = self.guardrails
        if guardrails is None:
            return response
        result = guardrails.check(response.text, direction="output")
        if result.blocked_by is not None:
            await self._emit_guardrail(
                invocation, "output", [result.blocked_by], True, response.text
            )
            raise ModelDenied(f"guardrail blocked output at {result.blocked_by}")
        if result.redacted_by:
            await self._emit_guardrail(
                invocation, "output", result.redacted_by, False, response.text
            )
            return response.model_copy(update={"text": result.text})
        return response

    async def _emit_guardrail(
        self,
        invocation: Invocation,
        direction: str,
        rules: list[str],
        blocked: bool,
        text: str,
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
                action=f"guardrail.{direction}",
                target=",".join(rules),
                args_hash=hash_text(text),
                status="denied" if blocked else "ok",
                error_code="guardrail_blocked" if blocked else None,
                timestamp=datetime.now(timezone.utc),
            )
        )
