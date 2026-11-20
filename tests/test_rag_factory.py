"""SLICE-199: entry points build RagContext from manifest.rag (ADR-0036)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from adk_agent import cli
from adk_agent.core import AgentManifest
from adk_agent.rag.context import RagContext
from adk_agent.rag.factory import RagFactory


class FakeStore:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class FakeGateway:
    pass


def _manifest(**overrides) -> AgentManifest:
    base = {
        "id": "assistant",
        "version": "1.0.0",
        "tenant": "acme",
        "owner": "acme",
        "model_policy": {"provider_allowlist": ["litellm"]},
    }
    base.update(overrides)
    return AgentManifest(**base)


def _factory(**overrides) -> RagFactory:
    return RagFactory(
        FakeStore(),
        FakeGateway(),
        provider="litellm",
        model="text-embedding-3-small",
        **overrides,
    )


def test_factory_skips_manifests_without_rag():
    assert _factory().context(_manifest()) is None


def test_factory_skips_disabled_rag():
    assert _factory().context(_manifest(rag={"enabled": False})) is None


def test_factory_builds_context_from_manifest():
    factory = _factory()
    manifest = _manifest(
        rag={
            "enabled": True,
            "top_k": 3,
            "min_confidence": 0.7,
            "data_classes": ["internal"],
            "on_error": "degrade",
        }
    )
    context = factory.context(manifest)
    assert isinstance(context, RagContext)
    assert context.top_k == 3
    assert context.guard.min_confidence == 0.7
    assert context.on_error == "degrade"
    assert context.data_classes == ["internal"]
    assert context.policy == manifest.model_policy
    assert context.service.store is factory.store
    assert context.service.embedder is factory.gateway


def test_factory_shares_one_store_across_contexts():
    factory = _factory()
    first = factory.context(_manifest(rag={"enabled": True}))
    second = factory.context(_manifest(rag={"enabled": True, "top_k": 1}))
    assert first.service.store is second.service.store
    assert first.guard is not second.guard


def test_factory_close_closes_store():
    store = FakeStore()
    factory = RagFactory(store, FakeGateway(), provider="litellm", model="m")
    import asyncio

    asyncio.run(factory.aclose())
    assert store.closed is True


def test_build_rag_factory_rejects_unknown_provider():
    from adk_agent.rag.factory import build_rag_factory

    with pytest.raises(ValueError, match="unknown rag provider"):
        build_rag_factory(
            database_url="postgresql://adk@127.0.0.1:5432/adk",
            dimensions=3,
            model="m",
            provider="vllm",
        )


def test_cli_rag_factory_is_none_without_flags():
    args = SimpleNamespace(rag_db=None, rag_dimensions=None, rag_model=None, rag_provider="litellm")
    assert cli._rag_factory(args) is None


def test_cli_rag_factory_requires_dimensions_and_model(capsys):
    args = SimpleNamespace(
        rag_db="postgresql://adk@127.0.0.1:5432/adk",
        rag_dimensions=None,
        rag_model=None,
        rag_provider="litellm",
    )
    with pytest.raises(SystemExit) as exc:
        cli._rag_factory(args)
    assert exc.value.code == 1
    assert "--rag-dimensions" in capsys.readouterr().err


def test_console_and_triggers_help_list_rag_flags(capsys):
    for command in ("console", "serve-triggers"):
        with pytest.raises(SystemExit) as exc:
            cli.main([command, "--help"])
        assert exc.value.code == 0
        help_text = capsys.readouterr().out
        for flag in ("--rag-db", "--rag-dimensions", "--rag-model", "--rag-provider"):
            assert flag in help_text
