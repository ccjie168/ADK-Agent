"""Grant-based policy engine for tool calls."""

from __future__ import annotations

from ..core import (
    GrantStoreError,
    Invocation,
    PolicyDecision,
    ToolGrant,
    ToolGrantStore,
)


class GrantPolicyEngine:
    def __init__(self, grants: list[ToolGrant], *, overlay: ToolGrantStore | None = None) -> None:
        self._grants = list(grants)
        self._allowed = {grant.tool_id for grant in grants}
        self._overlay = overlay

    @property
    def grants(self) -> list[ToolGrant]:
        return list(self._grants)

    async def decide(self, invocation: Invocation, action: str, target: str) -> PolicyDecision:
        if action == "tool.call" and target in self._allowed:
            return PolicyDecision(
                decision="allow", reason="tool granted", policy_version="grants-v1"
            )
        if action == "tool.call" and self._overlay is not None:
            agent_ref = invocation.agent_ref
            try:
                active = await self._overlay.active(
                    invocation.principal.tenant,
                    agent_ref.id,
                    agent_ref.version,
                    agent_ref.digest,
                    target,
                )
            except GrantStoreError:
                return PolicyDecision(
                    decision="deny",
                    reason="grant store unavailable",
                    policy_version="grants-v2",
                    error_code="grant_store_unavailable",
                )
            if active:
                return PolicyDecision(
                    decision="allow", reason="temporary grant", policy_version="grants-v2"
                )
        return PolicyDecision(
            decision="deny", reason="tool not granted", policy_version="grants-v1"
        )
