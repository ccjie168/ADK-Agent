"""Grant-based policy engine for tool calls."""

from __future__ import annotations

from ..core import (
    GrantStoreError,
    Invocation,
    PolicyDecision,
    RiskLevel,
    ToolGrant,
    ToolGrantStore,
)

_RISK_RANK = {"L1": 1, "L2": 2, "L3": 3, "L4": 4}


class GrantPolicyEngine:
    def __init__(self, grants: list[ToolGrant], *, overlay: ToolGrantStore | None = None) -> None:
        self._grants = list(grants)
        self._allowed = {grant.tool_id for grant in grants}
        self._risk = _highest_risk(grants)
        self._overlay = overlay

    @property
    def grants(self) -> list[ToolGrant]:
        return list(self._grants)

    async def decide(self, invocation: Invocation, action: str, target: str) -> PolicyDecision:
        if action == "tool.call" and target in self._allowed:
            if self._risk.get(target) == "L4":
                return PolicyDecision(
                    decision="deny",
                    reason="L4 default deny",
                    policy_version="grants-v1",
                    error_code="l4_default_deny",
                )
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


def _highest_risk(grants: list[ToolGrant]) -> dict[str, RiskLevel]:
    """The most restrictive risk level per tool, so a L4 grant always wins."""
    risk: dict[str, RiskLevel] = {}
    for grant in grants:
        level = grant.risk_level
        if level is None:
            continue
        current = risk.get(grant.tool_id)
        if current is None or _RISK_RANK[level] > _RISK_RANK[current]:
            risk[grant.tool_id] = level
    return risk
