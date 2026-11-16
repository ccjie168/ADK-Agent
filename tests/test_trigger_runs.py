"""SLICE-125: trigger fire records, single-winner claim, and terminal states."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from adk_agent.core import TriggerFire, TriggerFireConflict
from adk_agent.registry import FileTriggerFireStore

_NOW = datetime(2026, 11, 17, 9, 0, tzinfo=timezone.utc)


def _fire(**overrides) -> TriggerFire:
    data = {
        "tenant": "acme",
        "trigger_id": "nightly",
        "idempotency_key": "key-1",
        "run_id": "run-1",
        "trace_id": "trace-1",
        "status": "running",
        "created_at": _NOW,
    }
    data.update(overrides)
    return TriggerFire(**data)


def test_claim_has_a_single_winner(tmp_path):
    store = FileTriggerFireStore(tmp_path)

    first = asyncio.run(store.claim(_fire(run_id="run-1")))
    second = asyncio.run(store.claim(_fire(run_id="run-2")))

    assert first.run_id == "run-1"
    assert second == first
    assert asyncio.run(store.get("acme", "nightly", "key-1")) == first


def test_terminal_statuses_need_a_finish_time():
    with pytest.raises(ValidationError):
        _fire(status="ok")
    with pytest.raises(ValidationError):
        _fire(status="error")
    with pytest.raises(ValidationError):
        _fire(status="denied")
    with pytest.raises(ValidationError):
        _fire(status="running", finished_at=_NOW)

    finished = _fire(status="ok", finished_at=_NOW)
    assert finished.status == "ok"


def test_finish_updates_the_record(tmp_path):
    store = FileTriggerFireStore(tmp_path)
    asyncio.run(store.claim(_fire()))

    finished = asyncio.run(store.finish("acme", "nightly", "key-1", status="ok"))

    assert finished.status == "ok"
    assert finished.finished_at is not None
    assert finished.error_code is None
    assert asyncio.run(store.get("acme", "nightly", "key-1")) == finished


def test_finish_unknown_key_is_a_conflict(tmp_path):
    store = FileTriggerFireStore(tmp_path)

    with pytest.raises(TriggerFireConflict):
        asyncio.run(store.finish("acme", "nightly", "missing", status="ok"))


def test_unsafe_paths_are_rejected(tmp_path):
    store = FileTriggerFireStore(tmp_path)

    with pytest.raises(ValueError):
        asyncio.run(store.get("../escape", "nightly", "key-1"))
    with pytest.raises(ValueError):
        asyncio.run(store.get("acme", "../escape", "key-1"))
