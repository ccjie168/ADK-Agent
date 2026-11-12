"""Grant-based policy engine for tool calls."""

from __future__ import annotations

from ..core import Invocation, PolicyDecision, ToolGrant


class GrantPolicyEngine:
    def __init__(self, grants: list[ToolGrant]) -> None:
        self._grants = list(grants)
        self._allowed = {grant.tool_id for grant in grants}

    @property
    def grants(self) -> list[ToolGrant]:
        return list(self._grants)

    async def decide(self, invocation: Invocation, action: str, target: str) -> PolicyDecision:
        if action == "tool.call" and target in self._allowed:
            return PolicyDecision(
                decision="allow", reason="tool granted", policy_version="grants-v1"
            )
        return PolicyDecision(
            decision="deny", reason="tool not granted", policy_version="grants-v1"
        )
