"""SLICE-029: role-based access policy engine and file store."""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

from adk_agent.core import (
    AccessPolicy,
    AgentRef,
    Invocation,
    Principal,
    RoleBinding,
)
from adk_agent.rbac import FilePolicyStore, RolePolicyEngine


def _policy(
    *,
    allow=("agent.run:*",),
    deny=(),
    role: str = "ops",
    tenant: str = "t1",
    version: str = "1",
) -> AccessPolicy:
    return AccessPolicy(
        version=version,
        bindings=[RoleBinding(role=role, tenant=tenant, allow=list(allow), deny=list(deny))],
    )


def _invocation(*, roles=("ops",), tenant: str = "t1") -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant=tenant, subject="alice", kind="human", roles=list(roles)),
        agent_ref=AgentRef(id="flow", version="1.0.0", digest="d" * 64),
        input="hello",
    )


def _decide(engine: RolePolicyEngine, invocation: Invocation, action: str, target: str):
    return asyncio.run(engine.decide(invocation, action, target))


def test_role_allows_action():
    decision = _decide(RolePolicyEngine(_policy()), _invocation(), "agent.run", "probe")
    assert decision.decision == "allow"
    assert decision.policy_version == "rbac:1"


def test_unknown_role_is_denied():
    decision = _decide(
        RolePolicyEngine(_policy()), _invocation(roles=("guest",)), "agent.run", "probe"
    )
    assert decision.decision == "deny"


def test_deny_overrides_allow():
    policy = _policy(allow=("agent.run:*",), deny=("agent.run:probe",))
    decision = _decide(RolePolicyEngine(policy), _invocation(), "agent.run", "probe")
    assert decision.decision == "deny"


def test_binding_is_tenant_scoped():
    decision = _decide(RolePolicyEngine(_policy()), _invocation(tenant="t2"), "agent.run", "probe")
    assert decision.decision == "deny"


def test_wildcard_action_allows_all_targets():
    engine = RolePolicyEngine(_policy(allow=("*",)))
    assert _decide(engine, _invocation(), "tool.call", "crm.read").decision == "allow"
    assert _decide(engine, _invocation(), "policy.update", "2").decision == "allow"


def test_update_swaps_policy():
    engine = RolePolicyEngine(_policy(role="ops"))
    assert _decide(engine, _invocation(roles=("ops",)), "agent.run", "probe").decision == "allow"

    engine.update(_policy(role="admin", version="2"))
    assert _decide(engine, _invocation(roles=("ops",)), "agent.run", "probe").decision == "deny"
    decision = _decide(engine, _invocation(roles=("admin",)), "agent.run", "probe")
    assert decision.decision == "allow"
    assert decision.policy_version == "rbac:2"


def test_file_store_roundtrip(tmp_path):
    store = FilePolicyStore(tmp_path / "policy.json")
    policy = _policy()
    store.save(policy)

    assert store.load() == policy
    assert json.loads((tmp_path / "policy.json").read_text())["version"] == "1"


def test_invalid_policy_rejected():
    with pytest.raises(ValidationError):
        RoleBinding(role="../evil", tenant="t1")
    with pytest.raises(ValidationError):
        RoleBinding(role="ops", tenant="")
    with pytest.raises(ValidationError):
        AccessPolicy(version="")
    with pytest.raises(ValidationError):
        AccessPolicy(version="1", bindings=[], extra=True)
