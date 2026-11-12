"""SLICE-035: per-tenant audit hash chains."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from adk_agent import cli
from adk_agent.audit import AuditChainBroken, AuditPipeline, verify_audit_file
from adk_agent.core import AgentRef, AuditEvent, AuditRecord, Principal


def _event(
    *,
    event_id: str = "e1",
    tenant: str = "t1",
    action: str = "model.call",
    target: str = "litellm:deepseek",
) -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        run_id="r1",
        trace_id="tr1",
        tenant=tenant,
        principal=Principal(tenant=tenant, subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        action=action,
        target=target,
        status="ok",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _append(pipeline: AuditPipeline, event: AuditEvent) -> AuditRecord:
    return asyncio.run(pipeline.append(event))


def test_record_contract_roundtrip():
    record = AuditRecord(event=_event(), prev_hash="", hash="a" * 64)
    assert AuditRecord.model_validate_json(record.model_dump_json()) == record


def test_record_rejects_bad_hash():
    with pytest.raises(ValidationError):
        AuditRecord(event=_event(), prev_hash="", hash="not-a-hash")
    with pytest.raises(ValidationError):
        AuditRecord(event=_event(), prev_hash="xyz", hash="a" * 64)


def test_same_tenant_links_records(tmp_path):
    pipeline = AuditPipeline(tmp_path / "audit.jsonl")
    first = _append(pipeline, _event(event_id="e1"))
    second = _append(pipeline, _event(event_id="e2"))

    assert first.prev_hash == ""
    assert second.prev_hash == first.hash
    assert len(first.hash) == 64


def test_tenants_have_separate_chains(tmp_path):
    pipeline = AuditPipeline(tmp_path / "audit.jsonl")
    a1 = _append(pipeline, _event(event_id="a1", tenant="t1"))
    _append(pipeline, _event(event_id="b1", tenant="t2"))
    a2 = _append(pipeline, _event(event_id="a2", tenant="t1"))

    assert a2.prev_hash == a1.hash


def test_restart_resumes_chain(tmp_path):
    path = tmp_path / "audit.jsonl"
    first = _append(AuditPipeline(path), _event(event_id="e1"))

    resumed = AuditPipeline(path)
    second = _append(resumed, _event(event_id="e2"))

    assert second.prev_hash == first.hash


def test_verify_accepts_valid_file(tmp_path):
    path = tmp_path / "audit.jsonl"
    pipeline = AuditPipeline(path)
    for index in range(3):
        _append(pipeline, _event(event_id=f"e{index}"))

    assert verify_audit_file(path) == 3


def test_verify_detects_tampering(tmp_path):
    path = tmp_path / "audit.jsonl"
    pipeline = AuditPipeline(path)
    _append(pipeline, _event(event_id="e1"))
    _append(pipeline, _event(event_id="e2"))

    lines = path.read_text(encoding="utf-8").splitlines()
    data = json.loads(lines[0])
    data["event"]["target"] = "tampered"
    lines[0] = json.dumps(data)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(AuditChainBroken) as exc:
        verify_audit_file(path)
    assert exc.value.index == 0
    assert exc.value.tenant == "t1"


def test_verify_command(tmp_path, capsys):
    path = tmp_path / "audit.jsonl"
    pipeline = AuditPipeline(path)
    _append(pipeline, _event(event_id="e1"))
    _append(pipeline, _event(event_id="e2"))

    cli.main(["verify-audit", str(path)])
    assert "ok 2 records" in capsys.readouterr().out

    lines = path.read_text(encoding="utf-8").splitlines()
    data = json.loads(lines[1])
    data["event"]["status"] = "denied"
    lines[1] = json.dumps(data)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        cli.main(["verify-audit", str(path)])
    assert exc.value.code == 1
    assert "broken" in capsys.readouterr().err
