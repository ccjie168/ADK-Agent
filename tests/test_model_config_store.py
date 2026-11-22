"""SLICE-230: the file-backed global default model store round-trips."""

from __future__ import annotations

import asyncio

from adk_agent.registry.model_config import FileModelConfigStore


def test_file_model_config_store_roundtrip(tmp_path):
    store = FileModelConfigStore(tmp_path / "model")

    assert asyncio.run(store.get()) is None

    asyncio.run(store.put("litellm:openai/gpt-4o"))
    assert asyncio.run(store.get()) == "litellm:openai/gpt-4o"

    asyncio.run(store.put("claude:claude-sonnet-5-5"))
    assert asyncio.run(store.get()) == "claude:claude-sonnet-5-5"
