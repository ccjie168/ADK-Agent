"""Role-based policy engine and the file-backed policy store."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .core import AccessPolicy, Invocation, PolicyDecision


class RolePolicyEngine:
    """Tenant-scoped role bindings. Deny wins, and the default is deny."""

    def __init__(self, policy: AccessPolicy) -> None:
        self._policy = policy

    @property
    def policy(self) -> AccessPolicy:
        return self._policy

    def update(self, policy: AccessPolicy) -> None:
        self._policy = policy

    async def decide(self, invocation: Invocation, action: str, target: str) -> PolicyDecision:
        policy = self._policy
        permission = f"{action}:{target}"
        allowed = False
        for binding in policy.bindings:
            if binding.tenant != invocation.principal.tenant:
                continue
            if binding.role not in invocation.principal.roles:
                continue
            if _matches(binding.deny, action, permission):
                return PolicyDecision(
                    decision="deny",
                    reason="denied by role binding",
                    policy_version=f"rbac:{policy.version}",
                )
            if _matches(binding.allow, action, permission):
                allowed = True
        if allowed:
            return PolicyDecision(
                decision="allow",
                reason="allowed by role binding",
                policy_version=f"rbac:{policy.version}",
            )
        return PolicyDecision(
            decision="deny",
            reason="no role binding allows this action",
            policy_version=f"rbac:{policy.version}",
        )


def _matches(patterns: list[str], action: str, permission: str) -> bool:
    return any(pattern in ("*", permission, f"{action}:*") for pattern in patterns)


class FilePolicyStore:
    """Read and atomically replace an ``AccessPolicy`` JSON file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> AccessPolicy:
        return AccessPolicy.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, policy: AccessPolicy) -> None:
        payload = json.dumps(policy.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as tmp:
            tmp.write(payload)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        try:
            os.replace(tmp_path, self.path)
        finally:
            tmp_path.unlink(missing_ok=True)


__all__ = ["FilePolicyStore", "RolePolicyEngine"]
