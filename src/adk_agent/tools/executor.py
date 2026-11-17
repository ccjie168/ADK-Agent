"""Tool executor backed by the tool gateway (ADR-0024)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..sandbox.agent import SandboxToolError
from .client import ToolDenied, ToolGatewayClient, ToolGatewayError


def gateway_executor(client: ToolGatewayClient) -> Any:
    """Build the sandbox tool executor that calls the gateway for one run."""

    async def execute(manifest: Any, tool_id: str, args: dict[str, Any], invocation: Any) -> Any:
        if invocation is None:
            raise SandboxToolError("tool_principal_unavailable", "no invocation for the tool call")
        try:
            output = await client.invoke(
                invocation, tool_id, args, grants=list(manifest.tool_grants)
            )
        except ToolDenied as exc:
            raise SandboxToolError("tool_denied", str(exc)) from exc
        except ToolGatewayError as exc:
            raise SandboxToolError("tool_gateway_unavailable", str(exc)) from exc
        return output if isinstance(output, Mapping) else {"output": output}

    return execute


__all__ = ["gateway_executor"]
