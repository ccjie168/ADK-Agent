"""SLICE-137: the sandbox tool executor backed by the gateway."""

from __future__ import annotations

import asyncio

import pytest

from adk_agent.core import AgentManifest
from adk_agent.sandbox.agent import SandboxToolError
from adk_agent.tools.client import ToolDenied
from adk_agent.tools.executor import gateway_executor


def _manifest() -> AgentManifest:
    return AgentManifest.model_validate(
        {
            "id": "bot",
            "version": "1.0.0",
            "tenant": "acme",
            "owner": "acme",
            "model_policy": {"provider_allowlist": ["litellm"]},
            "execution_tier": "sandboxed",
            "tool_grants": [{"tool_id": "crm.read", "data_classes": ["internal"]}],
        }
    )


class _Client:
    def __init__(self, output=None, error=None) -> None:
        self.output = output
        self.error = error
        self.calls: list = []

    async def invoke(self, invocation, tool_id, args, *, grants=None):
        self.calls.append((invocation, tool_id, args, grants))
        if self.error is not None:
            raise self.error
        return self.output


def test_executor_requires_an_invocation():
    execute = gateway_executor(_Client(output={"ok": 1}))

    with pytest.raises(SandboxToolError) as exc:
        asyncio.run(execute(_manifest(), "crm.read", {}, None))

    assert exc.value.code == "tool_principal_unavailable"


def test_executor_wraps_non_mapping_outputs():
    client = _Client(output=[1, 2])

    async def run():
        execute = gateway_executor(client)
        return await execute(_manifest(), "crm.read", {"x": 1}, object())

    assert asyncio.run(run()) == {"output": [1, 2]}
    assert client.calls[0][3][0].tool_id == "crm.read"


def test_executor_maps_denials():
    execute = gateway_executor(_Client(error=ToolDenied("no")))

    with pytest.raises(SandboxToolError) as exc:
        asyncio.run(execute(_manifest(), "crm.read", {}, object()))

    assert exc.value.code == "tool_denied"


def test_executor_maps_gateway_failures():
    from adk_agent.tools.client import ToolGatewayError

    execute = gateway_executor(_Client(error=ToolGatewayError("down")))

    with pytest.raises(SandboxToolError) as exc:
        asyncio.run(execute(_manifest(), "crm.read", {}, object()))

    assert exc.value.code == "tool_gateway_unavailable"
