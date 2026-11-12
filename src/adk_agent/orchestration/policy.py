"""Grant-based policy for agent-to-agent invocation."""

from __future__ import annotations

from ..core import Invocation, PolicyDecision


class AgentGrantPolicyEngine:
    def __init__(self, allowed_agents: list[str]) -> None:
        self._allowed = set(allowed_agents)

    async def decide(self, invocation: Invocation, action: str, target: str) -> PolicyDecision:
        if action == "agent.invoke" and target in self._allowed:
            return PolicyDecision(
                decision="allow", reason="agent granted", policy_version="agents-v1"
            )
        return PolicyDecision(
            decision="deny", reason="agent not granted", policy_version="agents-v1"
        )
