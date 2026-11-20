"""SLICE-201: audit chain hashes the stored event JSON (ADR-0037)."""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from adk_agent.audit.pipeline import (
    AuditChainBroken,
    AuditPipeline,
    canonical_event_json,
    record_hash,
    verify_audit_file,
)
from adk_agent.core import AgentRef, AuditEvent, Principal


def _event(**overrides) -> AuditEvent:
    base = {
        "event_id": "e1",
        "run_id": "r1",
        "trace_id": "t1",
        "tenant": "acme",
        "principal": Principal(tenant="acme", subject="alice", kind="human"),
        "agent_ref": AgentRef(id="a", version="1", digest="d" * 64),
        "action": "agent.run",
        "target": "a@1",
        "status": "ok",
        "timestamp": "2026-11-20T00:00:00+00:00",
    }
    base.update(overrides)
    return AuditEvent(**base)


def _legacy_event_object() -> dict:
    """An event as written before model_alias/fallback_count/rag_* existed."""
    return {
        "event_id": "legacy",
        "run_id": "r0",
        "trace_id": "t0",
        "tenant": "acme",
        "principal": {
            "tenant": "acme",
            "subject": "alice",
            "kind": "human",
            "roles": [],
            "attributes": {},
        },
        "approver": None,
        "agent_ref": {"id": "a", "version": "1", "digest": "d" * 64, "artifact_digest": None},
        "action": "agent.run",
        "target": "a@1",
        "args_hash": None,
        "result_hash": None,
        "policy_decision_id": None,
        "policy_version": None,
        "data_classes": [],
        "latency_ms": None,
        "tokens": None,
        "cost_usd": None,
        "egress": "none",
        "status": "ok",
        "error_code": None,
        "risk_level": None,
        "timestamp": "2026-11-19T00:00:00+00:00",
    }


def _write_record(path, event_obj: dict, prev_hash: str, *, tamper_hash: str | None = None):
    digest = hashlib.sha256(f"{prev_hash}\n{canonical_event_json(event_obj)}".encode()).hexdigest()
    line = json.dumps(
        {
            "event": event_obj,
            "prev_hash": prev_hash,
            "hash": tamper_hash or digest,
            "signature": None,
            "kid": None,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return digest


def test_record_hash_accepts_stored_event_json():
    event = _event()
    text = event.model_dump_json()
    assert record_hash(event, "p") == record_hash(text, "p")
    assert record_hash(json.loads(text), "p") == record_hash(text, "p")


def test_canonical_form_is_key_order_independent():
    left = '{"b":1,"a":{"d":2,"c":3}}'
    right = '{"a":{"c":3,"d":2},"b":1}'
    assert canonical_event_json(left) == canonical_event_json(right)


def test_legacy_record_without_new_fields_verifies(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write_record(path, _legacy_event_object(), "")
    assert verify_audit_file(path) == 1


def test_append_after_legacy_record_keeps_chain(tmp_path):
    path = tmp_path / "audit.jsonl"
    legacy_hash = _write_record(path, _legacy_event_object(), "")
    pipeline = AuditPipeline(path)
    asyncio.run(pipeline.append(_event()))
    assert verify_audit_file(path) == 2
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert records[1]["prev_hash"] == legacy_hash


def test_tampering_event_content_breaks_chain(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write_record(path, _legacy_event_object(), "")
    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["event"]["target"] = "a@2"
    path.write_text(json.dumps(tampered) + "\n", encoding="utf-8")
    with pytest.raises(AuditChainBroken):
        verify_audit_file(path)


def test_written_record_hashes_the_stored_event(tmp_path):
    path = tmp_path / "audit.jsonl"
    pipeline = AuditPipeline(path)
    record = asyncio.run(pipeline.append(_event()))
    stored = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert stored["hash"] == record_hash(stored["event"], "")
    assert record.hash == stored["hash"]
