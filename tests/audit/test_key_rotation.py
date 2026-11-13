"""SLICE-060: audit signing keys rotate without breaking history."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from adk_agent import cli
from adk_agent.audit import (
    AuditPipeline,
    AuditSignatureInvalid,
    SigningKeyring,
    verify_audit_file,
)
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


def _keyring(**overrides) -> SigningKeyring:
    data = {"active": "k2", "keys": {"k1": "key-one", "k2": "key-two"}}
    data.update(overrides)
    return SigningKeyring(**data)


def test_records_carry_kid(tmp_path):
    path = tmp_path / "audit.jsonl"
    record = _append(AuditPipeline(path, keyring=_keyring()))

    assert record.kid == "k2"
    assert record.signature is not None
    assert len(record.signature) == 64
    assert verify_audit_file(path, keyring=_keyring()) == 1


def test_unknown_kid_rejected(tmp_path):
    path = tmp_path / "audit.jsonl"
    _append(AuditPipeline(path, keyring=_keyring()))

    with pytest.raises(AuditSignatureInvalid):
        verify_audit_file(path, keyring=SigningKeyring(active="k1", keys={"k1": "key-one"}))


def test_legacy_key_for_old_records(tmp_path):
    path = tmp_path / "audit.jsonl"
    _append(AuditPipeline(path, signing_key="key-one"))

    assert verify_audit_file(path, keyring=_keyring(legacy="k1")) == 1


def test_missing_legacy_rejected(tmp_path):
    path = tmp_path / "audit.jsonl"
    _append(AuditPipeline(path, signing_key="key-one"))

    with pytest.raises(AuditSignatureInvalid):
        verify_audit_file(path, keyring=_keyring())


def _rotate(tmp_path):
    path = tmp_path / "audit.jsonl"
    old = SigningKeyring(active="k1", keys={"k1": "key-one"})
    new = _keyring()
    _append(AuditPipeline(path, keyring=old), "e1")
    _append(AuditPipeline(path, keyring=old), "e2")
    _append(AuditPipeline(path, keyring=new), "e3")
    _append(AuditPipeline(path, keyring=new), "e4")
    return path, new


def test_rotation_keeps_both_keys(tmp_path):
    path, new = _rotate(tmp_path)

    assert verify_audit_file(path, keyring=new) == 4


def test_old_key_removal_detected(tmp_path):
    path, _ = _rotate(tmp_path)

    with pytest.raises(AuditSignatureInvalid):
        verify_audit_file(
            path,
            keyring=SigningKeyring(active="k2", keys={"k2": "key-two"}),
        )


def test_keyring_requires_active_key():
    with pytest.raises(ValidationError):
        SigningKeyring(active="k3", keys={"k1": "key-one"})


def test_keyring_rejects_empty_key():
    with pytest.raises(ValidationError):
        SigningKeyring(active="k1", keys={"k1": ""})


def test_keyring_rejects_bad_kid():
    with pytest.raises(ValidationError):
        SigningKeyring(active="bad id", keys={"bad id": "key-one"})


def test_pipeline_rejects_two_key_modes(tmp_path):
    with pytest.raises(ValueError):
        AuditPipeline(tmp_path / "audit.jsonl", signing_key="key-one", keyring=_keyring())


def test_cli_verify_with_keyring(tmp_path, monkeypatch, capsys):
    path = tmp_path / "audit.jsonl"
    _append(AuditPipeline(path, keyring=_keyring()))
    monkeypatch.setenv(
        "ADK_AUDIT_KEYRING",
        json.dumps({"active": "k2", "keys": {"k1": "key-one", "k2": "key-two"}}),
    )

    cli.main(["verify-audit", str(path)])

    assert "ok 1 records" in capsys.readouterr().out


def test_cli_keyring_unknown_kid_fails(tmp_path, monkeypatch, capsys):
    path = tmp_path / "audit.jsonl"
    _append(AuditPipeline(path, keyring=_keyring()))
    monkeypatch.setenv(
        "ADK_AUDIT_KEYRING",
        json.dumps({"active": "k1", "keys": {"k1": "key-one"}}),
    )

    with pytest.raises(SystemExit) as exc:
        cli.main(["verify-audit", str(path)])

    assert exc.value.code == 1
    assert "signature invalid" in capsys.readouterr().err


def test_cli_rejects_both_env(tmp_path, monkeypatch, capsys):
    path = tmp_path / "audit.jsonl"
    _append(AuditPipeline(path))
    monkeypatch.setenv("ADK_AUDIT_KEYRING", json.dumps({"active": "k1", "keys": {"k1": "x"}}))
    monkeypatch.setenv("ADK_AUDIT_SIGNING_KEY", "x")

    with pytest.raises(SystemExit) as exc:
        cli.main(["verify-audit", str(path)])

    assert exc.value.code == 1
    assert "ADK_AUDIT_KEYRING" in capsys.readouterr().err


def test_cli_rejects_bad_keyring_json(tmp_path, monkeypatch, capsys):
    path = tmp_path / "audit.jsonl"
    _append(AuditPipeline(path))
    monkeypatch.setenv("ADK_AUDIT_KEYRING", "{not json")

    with pytest.raises(SystemExit) as exc:
        cli.main(["verify-audit", str(path)])

    assert exc.value.code == 1
    assert "ADK_AUDIT_KEYRING" in capsys.readouterr().err
