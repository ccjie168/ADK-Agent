"""SLICE-053: audit records are signed with an HMAC key."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from adk_agent import cli
from adk_agent.audit import AuditPipeline, AuditSignatureInvalid, verify_audit_file
from adk_agent.core import AgentRef, AuditEvent, AuditRecord, Principal


def _event(event_id: str = "e1") -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        run_id="r1",
        trace_id="tr1",
        tenant="t1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        action="model.call",
        target="litellm:deepseek",
        status="ok",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _append(pipeline: AuditPipeline, event_id: str = "e1") -> AuditRecord:
    return asyncio.run(pipeline.append(_event(event_id)))


def test_signed_records_verify(tmp_path):
    path = tmp_path / "audit.jsonl"
    record = _append(AuditPipeline(path, signing_key="k1"))

    assert record.signature is not None
    assert len(record.signature) == 64
    assert verify_audit_file(path, signing_key="k1") == 1


def test_wrong_key_fails(tmp_path):
    path = tmp_path / "audit.jsonl"
    _append(AuditPipeline(path, signing_key="k1"))

    with pytest.raises(AuditSignatureInvalid):
        verify_audit_file(path, signing_key="k2")


def test_missing_signature_fails(tmp_path):
    path = tmp_path / "audit.jsonl"
    _append(AuditPipeline(path))

    with pytest.raises(AuditSignatureInvalid):
        verify_audit_file(path, signing_key="k1")


def test_signature_tamper_fails(tmp_path):
    path = tmp_path / "audit.jsonl"
    _append(AuditPipeline(path, signing_key="k1"))

    lines = path.read_text(encoding="utf-8").splitlines()
    data = json.loads(lines[0])
    data["signature"] = "0" * 64
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")

    with pytest.raises(AuditSignatureInvalid):
        verify_audit_file(path, signing_key="k1")


def test_unsigned_verify_without_key(tmp_path):
    path = tmp_path / "audit.jsonl"
    _append(AuditPipeline(path))

    assert verify_audit_file(path) == 1


def test_verify_command_uses_env_key(tmp_path, monkeypatch, capsys):
    path = tmp_path / "audit.jsonl"
    _append(AuditPipeline(path, signing_key="k1"))
    monkeypatch.setenv("ADK_AUDIT_SIGNING_KEY", "k1")

    cli.main(["verify-audit", str(path)])
    assert "ok 1 records" in capsys.readouterr().out

    monkeypatch.setenv("ADK_AUDIT_SIGNING_KEY", "wrong")
    with pytest.raises(SystemExit) as exc:
        cli.main(["verify-audit", str(path)])
    assert exc.value.code == 1
    assert "signature" in capsys.readouterr().err
