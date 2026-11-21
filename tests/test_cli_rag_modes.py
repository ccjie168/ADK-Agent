"""SLICE-206: MCP and A2A modes accept the RAG flags and resolve manifests."""

from __future__ import annotations

import pytest
from google.adk.agents import LlmAgent

from adk_agent import cli
from adk_agent.core import AgentManifest


class RecordingFactory:
    def __init__(self) -> None:
        self.manifests = []

    def context(self, manifest):
        self.manifests.append(manifest)
        return "context"


def _manifest() -> AgentManifest:
    return AgentManifest.model_validate(
        {
            "id": "bot",
            "version": "1.0.0",
            "tenant": "acme",
            "owner": "acme",
            "model_policy": {"provider_allowlist": ["litellm"]},
            "rag": {"enabled": True},
        }
    )


def test_serve_modes_help_list_rag_flags(capsys):
    for command in ("serve", "serve-many", "serve-a2a"):
        with pytest.raises(SystemExit) as exc:
            cli.main([command, "--help"])
        assert exc.value.code == 0
        help_text = capsys.readouterr().out
        for flag in ("--rag-db", "--rag-dimensions", "--rag-model", "--rag-provider"):
            assert flag in help_text, (command, flag)


def test_agent_rag_uses_the_registry_manifest():
    factory = RecordingFactory()
    agent = LlmAgent(name="bot", model="gemini-2.5-pro", instruction="x")
    manifest = _manifest()
    object.__setattr__(agent, "_adk_manifest", manifest)

    assert cli._agent_rag(factory, agent) == "context"
    assert factory.manifests == [manifest]


def test_agent_rag_skips_file_loaded_agents_and_missing_factory():
    factory = RecordingFactory()
    agent = LlmAgent(name="bot", model="gemini-2.5-pro", instruction="x")

    assert cli._agent_rag(factory, agent) is None
    assert factory.manifests == []
    assert cli._agent_rag(None, agent) is None
