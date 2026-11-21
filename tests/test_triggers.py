"""SLICE-124: trigger definitions, webhook token hashing, and the file store."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from adk_agent.core import (
    AgentTrigger,
    TriggerConflict,
    TriggerNotFound,
    hash_webhook_token,
)
from adk_agent.registry import FileTriggerStore

_DIGEST = "sha256:" + "a" * 64
_TOKEN = "webhook-token-0123456789"


def _schedule(**overrides) -> AgentTrigger:
    data = {
        "trigger_id": "nightly-summary",
        "tenant": "acme",
        "agent_id": "assistant",
        "version": "1.0.0",
        "digest": _DIGEST,
        "kind": "schedule",
        "every_seconds": 3600,
        "input": "Summarize yesterday.",
        "created_by": "admin",
        "created_at": datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc),
    }
    data.update(overrides)
    return AgentTrigger(**data)


def _webhook(**overrides) -> AgentTrigger:
    data = {
        **_schedule().model_dump(),
        "kind": "webhook",
        "every_seconds": None,
        "webhook_token_hash": hash_webhook_token(_TOKEN),
    }
    data.update(overrides)
    return AgentTrigger(**data)


def test_schedule_requires_interval():
    with pytest.raises(ValidationError):
        _schedule(every_seconds=None)
    with pytest.raises(ValidationError):
        _schedule(every_seconds=59)

    assert _schedule(every_seconds=60).every_seconds == 60


def test_webhook_requires_token_hash():
    with pytest.raises(ValidationError):
        _webhook(webhook_token_hash=None)
    with pytest.raises(ValidationError):
        _schedule(webhook_token_hash=hash_webhook_token(_TOKEN))
    with pytest.raises(ValidationError):
        _webhook(every_seconds=3600)


def test_trigger_digest_normalizes_bare_hex():
    trigger = _schedule(digest="c" * 64)
    assert trigger.digest == "sha256:" + "c" * 64
    assert _schedule(digest=_DIGEST).digest == _DIGEST


def test_invalid_fields_are_rejected():
    with pytest.raises(ValidationError):
        _schedule(digest="sha256:" + "A" * 64)
    with pytest.raises(ValueError):
        hash_webhook_token("short-token")
    with pytest.raises(ValidationError):
        _schedule(input="x" * 8001)
    with pytest.raises(ValidationError):
        _schedule(trigger_id="../escape")
    with pytest.raises(ValidationError):
        _schedule(tenant="acme/other")
    with pytest.raises(ValidationError):
        _schedule(agent_id="bad/id")
    with pytest.raises(ValidationError):
        _schedule(version="-1.0.0")
    with pytest.raises(ValidationError):
        _webhook(webhook_token_hash="nothex")


def test_token_is_hashed_and_not_stored(tmp_path):
    first = hash_webhook_token(_TOKEN)
    assert first == hash_webhook_token(_TOKEN)
    assert len(first) == 64
    assert all(character in "0123456789abcdef" for character in first)

    store = FileTriggerStore(tmp_path)
    trigger = _webhook()
    assert asyncio.run(store.add(trigger)) == trigger

    text = (tmp_path / "acme" / "nightly-summary.json").read_text(encoding="utf-8")
    assert _TOKEN not in text
    assert first in text


def test_repeated_registration_is_idempotent(tmp_path):
    store = FileTriggerStore(tmp_path)
    first = _schedule()
    assert asyncio.run(store.add(first)) == first

    again = _schedule(
        created_at=datetime(2026, 11, 17, 9, 0, tzinfo=timezone.utc),
        created_by="ops",
    )
    stored = asyncio.run(store.add(again))

    assert stored == first
    assert asyncio.run(store.list("acme")) == [first]


def test_file_store_roundtrip_and_disable(tmp_path):
    store = FileTriggerStore(tmp_path)
    acme = _schedule()
    other = _schedule(tenant="other")

    assert asyncio.run(store.add(acme)) == acme
    assert asyncio.run(store.add(acme)) == acme
    assert asyncio.run(store.add(other)) == other
    assert asyncio.run(store.get("acme", "nightly-summary")) == acme
    assert asyncio.run(store.get("other", "nightly-summary")) == other
    assert asyncio.run(store.get("acme", "missing")) is None

    with pytest.raises(TriggerConflict):
        asyncio.run(store.add(_schedule(input="different input")))

    listed = asyncio.run(store.list("acme"))
    assert [trigger.tenant for trigger in listed] == ["acme"]

    asyncio.run(store.add(_schedule(trigger_id="aaa")))
    every = asyncio.run(store.list_all())
    assert [(trigger.tenant, trigger.trigger_id) for trigger in every] == [
        ("acme", "aaa"),
        ("acme", "nightly-summary"),
        ("other", "nightly-summary"),
    ]

    disabled = asyncio.run(store.disable("acme", "nightly-summary", by="alice"))
    again = asyncio.run(store.disable("acme", "nightly-summary", by="bob"))
    assert disabled.enabled is False
    assert again.enabled is False
    assert asyncio.run(store.add(acme)).enabled is False

    with pytest.raises(TriggerNotFound):
        asyncio.run(store.disable("acme", "missing", by="alice"))
