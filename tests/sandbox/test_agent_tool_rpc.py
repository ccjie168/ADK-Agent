"""SLICE-136: sandboxed tool calls are mediated by the parent."""

from __future__ import annotations

import asyncio
import io
import json

import pytest

from adk_agent.core import AgentManifest
from adk_agent.registry import artifact_digest
from adk_agent.registry.packaging import pack_files
from adk_agent.sandbox.agent import SandboxToolError
from adk_agent.sandbox.agent_channel import SandboxChannel
from adk_agent.sandbox.agent_process import AgentSandboxLimits, ProcessAgentSandbox
from adk_agent.sandbox.errors import SandboxCrashed, SandboxViolation

_SOURCE = """
from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

_calls = 0


class Fake(BaseLlm):
    async def generate_content_async(self, llm_request, stream=False):
        global _calls
        if _calls < __CALLS__:
            _calls += 1
            part = types.Part(
                function_call=types.FunctionCall(name="ping", args={"x": _calls})
            )
        else:
            part = types.Part(text="done")
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


def ping(x: int) -> dict:
    return {"pong": x}


agent = LlmAgent(name="bot", model=Fake(model="fake"), instruction="x", tools=[ping])
"""


_TREE_SOURCE = _SOURCE.replace(
    'agent = LlmAgent(name="bot", model=Fake(model="fake"), instruction="x", tools=[ping])',
    "from google.adk.agents import SequentialAgent\n"
    'worker = LlmAgent(name="worker", model=Fake(model="fake"), instruction="x", tools=[ping])\n'
    'agent = SequentialAgent(name="bot", sub_agents=[worker])',
)


def _artifact(calls: int = 1, source: str | None = None):
    manifest = {
        "id": "bot",
        "version": "1.0.0",
        "tenant": "acme",
        "owner": "acme",
        "model_policy": {"provider_allowlist": ["fake"]},
        "execution_tier": "sandboxed",
    }
    source = (source or _SOURCE).replace("__CALLS__", str(calls))
    data = pack_files(
        {
            "manifest.json": json.dumps(manifest).encode("utf-8"),
            "agent.py": source.encode("utf-8"),
        }
    )
    from adk_agent.core import AgentArtifact

    return AgentArtifact(digest=artifact_digest(data), size=len(data)), data


def _manifest(*tool_ids: str) -> AgentManifest:
    return AgentManifest.model_validate(
        {
            "id": "bot",
            "version": "1.0.0",
            "tenant": "acme",
            "owner": "acme",
            "model_policy": {"provider_allowlist": ["fake"]},
            "execution_tier": "sandboxed",
            "tool_grants": [
                {"tool_id": tool_id, "data_classes": ["internal"]} for tool_id in tool_ids
            ],
        }
    )


def test_tool_call_round_trips():
    artifact, data = _artifact()
    seen: list = []

    async def tools(manifest, tool_id, args):
        seen.append((tool_id, args))
        return {"pong": args["x"]}

    sandbox = ProcessAgentSandbox(AgentSandboxLimits(wall_seconds=30), tools=tools)
    result = asyncio.run(sandbox.run(artifact, data, "hi", manifest=_manifest("ping")))

    assert result.text == "done"
    assert seen == [("ping", {"x": 1})]


def test_unauthorized_tool_is_refused():
    artifact, data = _artifact()
    seen: list = []

    async def tools(manifest, tool_id, args):
        seen.append(tool_id)
        return {}

    sandbox = ProcessAgentSandbox(AgentSandboxLimits(wall_seconds=30), tools=tools)
    with pytest.raises(SandboxCrashed) as exc:
        asyncio.run(sandbox.run(artifact, data, "hi", manifest=_manifest("other")))

    assert "tool_not_granted" in str(exc.value)
    assert seen == []


def test_tool_mediation_requires_executor():
    artifact, data = _artifact()
    sandbox = ProcessAgentSandbox(AgentSandboxLimits(wall_seconds=30))

    with pytest.raises(SandboxCrashed) as exc:
        asyncio.run(sandbox.run(artifact, data, "hi", manifest=_manifest("ping")))

    assert "tool_mediation_unavailable" in str(exc.value)


def test_unserializable_args_are_refused():
    channel = SandboxChannel(io.BytesIO(), io.BytesIO())

    with pytest.raises(SandboxToolError) as exc:
        asyncio.run(channel.call_tool("ping", {"x": object()}))

    assert exc.value.code == "tool_args_invalid"


def test_tool_call_limit():
    artifact, data = _artifact(calls=5)
    seen: list = []

    async def tools(manifest, tool_id, args):
        seen.append(tool_id)
        return {}

    sandbox = ProcessAgentSandbox(
        AgentSandboxLimits(wall_seconds=30, max_tool_calls=2), tools=tools
    )
    with pytest.raises(SandboxViolation):
        asyncio.run(sandbox.run(artifact, data, "hi", manifest=_manifest("ping")))

    assert len(seen) == 2


def test_executor_none_is_refused():
    artifact, data = _artifact()

    async def tools(manifest, tool_id, args):
        return None

    sandbox = ProcessAgentSandbox(AgentSandboxLimits(wall_seconds=30), tools=tools)
    with pytest.raises(SandboxCrashed) as exc:
        asyncio.run(sandbox.run(artifact, data, "hi", manifest=_manifest("ping")))

    assert "tool_result_invalid" in str(exc.value)


def test_executor_result_must_be_json():
    artifact, data = _artifact()

    async def tools(manifest, tool_id, args):
        return {"bad": object()}

    sandbox = ProcessAgentSandbox(AgentSandboxLimits(wall_seconds=30), tools=tools)
    with pytest.raises(SandboxCrashed) as exc:
        asyncio.run(sandbox.run(artifact, data, "hi", manifest=_manifest("ping")))

    assert "tool_result_invalid" in str(exc.value)


def test_synthetic_agent_tree_installs_on_llm_agents():
    artifact, data = _artifact(source=_TREE_SOURCE)
    seen: list = []

    async def tools(manifest, tool_id, args):
        seen.append(tool_id)
        return {"pong": args["x"]}

    sandbox = ProcessAgentSandbox(AgentSandboxLimits(wall_seconds=30), tools=tools)
    result = asyncio.run(sandbox.run(artifact, data, "hi", manifest=_manifest("ping")))

    assert result.text == "done"
    assert seen == ["ping"]
