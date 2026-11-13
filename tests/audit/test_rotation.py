"""SLICE-053: audit segments rotate and the chain spans them."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from adk_agent.audit import AuditChainBroken, AuditPipeline, load_records, verify_audit_file
from adk_agent.core import AgentRef, AuditEvent, AuditRecord, Principal


def _event(event_id: str) -> AuditEvent:
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


def _append(pipeline: AuditPipeline, event_id: str) -> AuditRecord:
    return asyncio.run(pipeline.append(_event(event_id)))


def test_rotates_segments(tmp_path):
    path = tmp_path / "audit.jsonl"
    pipeline = AuditPipeline(path, max_records=2)
    for index in range(5):
        _append(pipeline, f"e{index}")

    assert (tmp_path / "audit.jsonl.000001").exists()
    assert (tmp_path / "audit.jsonl.000002").exists()
    assert path.exists()
    assert verify_audit_file(path) == 5
    assert [record.event.event_id for record in load_records(path)] == [
        f"e{index}" for index in range(5)
    ]


def test_rotates_only_when_full(tmp_path):
    path = tmp_path / "audit.jsonl"
    pipeline = AuditPipeline(path, max_records=2)
    _append(pipeline, "e1")
    _append(pipeline, "e2")

    assert not (tmp_path / "audit.jsonl.000001").exists()

    _append(pipeline, "e3")

    assert (tmp_path / "audit.jsonl.000001").exists()
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_chain_continues_across_segments(tmp_path):
    path = tmp_path / "audit.jsonl"
    pipeline = AuditPipeline(path, max_records=2)
    records = [_append(pipeline, f"e{index}") for index in range(5)]

    assert records[2].prev_hash == records[1].hash
    assert records[4].prev_hash == records[3].hash


def test_restart_reads_all_segments(tmp_path):
    path = tmp_path / "audit.jsonl"
    pipeline = AuditPipeline(path, max_records=2)
    first = [_append(pipeline, f"e{index}") for index in range(3)]

    resumed = AuditPipeline(path, max_records=2)
    fourth = _append(resumed, "e3")

    assert fourth.prev_hash == first[-1].hash
    assert verify_audit_file(path) == 4


def test_no_rotation_by_default(tmp_path):
    path = tmp_path / "audit.jsonl"
    pipeline = AuditPipeline(path)
    for index in range(5):
        _append(pipeline, f"e{index}")

    assert not list(tmp_path.glob("audit.jsonl.*"))
    assert verify_audit_file(path) == 5


def test_verify_spans_segments(tmp_path):
    path = tmp_path / "audit.jsonl"
    pipeline = AuditPipeline(path, max_records=2)
    for index in range(5):
        _append(pipeline, f"e{index}")

    segment = tmp_path / "audit.jsonl.000001"
    lines = segment.read_text(encoding="utf-8").splitlines()
    data = json.loads(lines[0])
    data["event"]["target"] = "tampered"
    lines[0] = json.dumps(data)
    segment.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(AuditChainBroken) as exc:
        verify_audit_file(path)
    assert exc.value.index == 0
