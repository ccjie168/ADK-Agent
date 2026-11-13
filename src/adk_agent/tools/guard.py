"""ADK tool callbacks that enforce policy and audit tool calls."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, cast

from google.adk.tools import BaseTool

from ..audit.hashing import safe_hash_json
from ..core import AuditEvent, AuditSink, DataClass, Invocation, PolicyEngine
from ..core.context import current_invocation
from .gateway import ToolDenied

_DATA_CLASSES = frozenset({"public", "internal", "confidential", "restricted"})


def _call_key(context: Any) -> str:
    call_id = getattr(context, "function_call_id", None)
    return str(call_id) if call_id else str(id(context))


def _data_classes(tool: BaseTool) -> list[DataClass]:
    metadata = getattr(tool, "custom_metadata", None)
    if not isinstance(metadata, dict):
        return []
    values = metadata.get("data_classes")
    if not isinstance(values, (list, tuple)):
        return []
    allowed = [value for value in values if isinstance(value, str) and value in _DATA_CLASSES]
    return cast(list[DataClass], allowed)


class ToolGuard:
    """The ADK tool loop calls these before, after, and on error."""

    def __init__(self, policy: PolicyEngine, audit: AuditSink | None = None) -> None:
        self.policy = policy
        self.audit = audit
        self._started: dict[str, float] = {}
        self._denied: set[str] = set()
        self._policies: dict[str, str] = {}

    async def before(
        self, tool: BaseTool, args: dict[str, Any], context: Any
    ) -> dict[str, Any] | None:
        invocation = current_invocation()
        if invocation is None:
            raise ToolDenied("tool call outside an invocation context")

        key = _call_key(context)
        self._started[key] = time.perf_counter()
        decision = await self.policy.decide(invocation, "tool.call", tool.name)
        if decision.decision == "allow":
            self._policies[key] = decision.policy_version
            return None

        self._denied.add(key)
        await self._audit(
            invocation,
            tool,
            args,
            response=None,
            status="denied",
            error_code=decision.error_code or "policy_denied",
            policy_version=decision.policy_version,
            key=key,
        )
        return {"error": "tool_denied", "reason": decision.reason, "tool": tool.name}

    async def after(
        self, tool: BaseTool, args: dict[str, Any], context: Any, response: Any
    ) -> None:
        invocation = current_invocation()
        if invocation is None:
            return

        key = _call_key(context)
        if key in self._denied:
            self._denied.discard(key)
            self._started.pop(key, None)
            return

        await self._audit(
            invocation,
            tool,
            args,
            response=response,
            status="ok",
            error_code=None,
            policy_version=self._policies.pop(key, None),
            key=key,
        )

    async def on_error(
        self, tool: BaseTool, args: dict[str, Any], context: Any, error: Exception
    ) -> None:
        invocation = current_invocation()
        if invocation is None:
            return

        key = _call_key(context)
        await self._audit(
            invocation,
            tool,
            args,
            response=None,
            status="error",
            error_code=type(error).__name__,
            policy_version=self._policies.pop(key, None),
            key=key,
        )

    async def _audit(
        self,
        invocation: Invocation,
        tool: BaseTool,
        args: dict[str, Any],
        *,
        response: Any,
        status: Literal["ok", "error", "denied"],
        error_code: str | None,
        key: str,
        policy_version: str | None = None,
    ) -> None:
        if self.audit is None:
            return
        started = self._started.pop(key, None)
        event = AuditEvent(
            event_id=uuid.uuid4().hex,
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            tenant=invocation.principal.tenant,
            principal=invocation.principal,
            agent_ref=invocation.agent_ref,
            action="tool.call",
            target=tool.name,
            args_hash=safe_hash_json(args),
            result_hash=safe_hash_json(response)
            if status == "ok" and response is not None
            else None,
            data_classes=_data_classes(tool),
            latency_ms=int((time.perf_counter() - started) * 1000) if started is not None else None,
            egress="none",
            status=status,
            error_code=error_code,
            policy_version=policy_version,
            timestamp=datetime.now(timezone.utc),
        )
        await self.audit.emit(event)


def _prepend(existing: Any, callback: Any) -> list[Any]:
    if existing is None:
        return [callback]
    if isinstance(existing, (list, tuple)):
        return [callback, *existing]
    return [callback, existing]


def install_tool_guard(agent: Any, guard: ToolGuard) -> None:
    """Put the guard first on every agent in the tree, keeping existing callbacks."""
    agent.before_tool_callback = _prepend(agent.before_tool_callback, guard.before)
    agent.after_tool_callback = _prepend(agent.after_tool_callback, guard.after)
    agent.on_tool_error_callback = _prepend(agent.on_tool_error_callback, guard.on_error)
    for sub in getattr(agent, "sub_agents", None) or ():
        install_tool_guard(sub, guard)
