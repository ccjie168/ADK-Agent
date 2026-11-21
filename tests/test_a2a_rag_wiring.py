"""SLICE-206: A2A wraps its runner when only retrieval is configured."""

from __future__ import annotations

import importlib.util

import pytest
from google.adk.agents import LlmAgent

from adk_agent import a2a

_HAS_A2A = importlib.util.find_spec("a2a") is not None
needs_a2a = pytest.mark.skipif(not _HAS_A2A, reason="a2a-sdk is not installed")


@needs_a2a
def test_a2a_wraps_runner_when_only_rag_is_set(monkeypatch):
    seen: dict[str, object] = {}

    def fake_wrap(inner, **kwargs):
        seen.update(kwargs)
        return inner

    monkeypatch.setattr(a2a, "wrap_runner", fake_wrap)
    agent = LlmAgent(name="bot", model="gemini-2.5-pro", instruction="x")
    context = object()

    a2a.build_a2a_app(agent, rag=context, port=8000)

    assert seen.get("rag") is context


@needs_a2a
def test_a2a_without_rag_or_audit_does_not_wrap(monkeypatch):
    called: list[str] = []

    def fake_wrap(inner, **kwargs):
        called.append("wrapped")
        return inner

    monkeypatch.setattr(a2a, "wrap_runner", fake_wrap)
    agent = LlmAgent(name="bot", model="gemini-2.5-pro", instruction="x")

    a2a.build_a2a_app(agent, port=8000)

    assert called == []
