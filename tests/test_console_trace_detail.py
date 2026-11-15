"""SLICE-119: trace nodes carry the audit fields behind the run drilldown."""

from __future__ import annotations

from datetime import datetime, timezone

from adk_agent.console import _trace_node, _trace_payload
from adk_agent.core import AgentRef, AuditEvent, Principal

TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
ARGS_HASH = "sha256:" + "a" * 64
RESULT_HASH = "sha256:" + "b" * 64


def _event(action: str = "tool.call", target: str = "crm.read", **overrides: object) -> AuditEvent:
    fields: dict[str, object] = {
        "event_id": "e1",
        "run_id": "r1",
        "trace_id": "trace-1",
        "tenant": "acme",
        "principal": Principal(tenant="acme", subject="alice", kind="human"),
        "agent_ref": AgentRef(id="support-bot", version="1.0.0", digest="d" * 64),
        "action": action,
        "target": target,
        "status": "ok",
        "timestamp": TS,
    }
    fields.update(overrides)
    return AuditEvent(**fields)


def test_node_carries_audit_fields():
    event = _event(
        approver="bob",
        args_hash=ARGS_HASH,
        result_hash=RESULT_HASH,
        policy_decision_id="d1",
        policy_version="rbac:3",
        data_classes=["internal", "confidential"],
        latency_ms=42,
        tokens=128,
        cost_usd=0.0015,
        egress="third_party",
    )

    assert _trace_node(event) == {
        "id": "crm.read",
        "kind": "tool",
        "status": "ok",
        "error_code": None,
        "latency_ms": 42,
        "cost_usd": 0.0015,
        "timestamp": TS.isoformat(),
        "event_id": "e1",
        "run_id": "r1",
        "action": "tool.call",
        "target": "crm.read",
        "tenant": "acme",
        "principal": {"subject": "alice", "kind": "human"},
        "agent": {"id": "support-bot", "version": "1.0.0"},
        "approver": "bob",
        "args_hash": ARGS_HASH,
        "result_hash": RESULT_HASH,
        "policy_decision_id": "d1",
        "policy_version": "rbac:3",
        "data_classes": ["internal", "confidential"],
        "tokens": 128,
        "egress": "third_party",
    }


def test_node_keeps_null_fields():
    node = _trace_node(_event())

    for field in (
        "error_code",
        "latency_ms",
        "cost_usd",
        "approver",
        "args_hash",
        "result_hash",
        "policy_decision_id",
        "policy_version",
        "tokens",
    ):
        assert node[field] is None, field
    assert node["data_classes"] == []
    assert isinstance(node["data_classes"], list)
    assert node["egress"] == "none"
    assert node["principal"] == {"subject": "alice", "kind": "human"}
    assert node["agent"] == {"id": "support-bot", "version": "1.0.0"}


def _keys(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _keys(child)


def test_payload_has_no_raw_content():
    root = _event("agent.run", "support-bot@1.0.0")
    child = _event(action="tool.call", target="crm.read", event_id="e2")

    payload = _trace_payload([root, child], "trace-1")

    assert set(_keys(payload)).isdisjoint({"prompt", "completion", "input", "args"})


def test_payload_propagates_fields_to_child():
    root = _event("agent.run", "support-bot@1.0.0")
    child = _event(
        action="tool.call",
        target="crm.read",
        event_id="e2",
        policy_version="rbac:3",
        args_hash=ARGS_HASH,
        tokens=7,
    )

    payload = _trace_payload([root, child], "trace-1")

    node = payload["root"]["children"][0]
    assert node["event_id"] == "e2"
    assert node["run_id"] == "r1"
    assert node["action"] == "tool.call"
    assert node["target"] == "crm.read"
    assert node["tenant"] == "acme"
    assert node["policy_version"] == "rbac:3"
    assert node["args_hash"] == ARGS_HASH
    assert node["tokens"] == 7
    assert node["principal"] == {"subject": "alice", "kind": "human"}
    assert node["agent"] == {"id": "support-bot", "version": "1.0.0"}
