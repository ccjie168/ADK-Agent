"""Shared pieces of the support demo: mock calls, the agents and the plan."""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from adk_agent.audit import AuditPipeline  # noqa: E402
from adk_agent.core import (  # noqa: E402
    AgentRef,
    ConnectorSpec,
    Invocation,
    InvocationResult,
    OrchestrationPlan,
    PlanStep,
    Principal,
    ToolGrant,
)

DEFAULT_TOKEN = "demo-token"  # nosec B105  # loopback-only demo token
SECRET_REF = "secret://mock/token"  # nosec B105  # reference, not a secret  # pragma: allowlist secret
_DIGEST = "d" * 64


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL {message}")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_mock(port: int, token: str = DEFAULT_TOKEN) -> Any:
    """Run ``scripts/mock_services.py`` in a background thread."""
    import uvicorn

    from mock_services import build_mock_app

    server = uvicorn.Server(
        uvicorn.Config(build_mock_app(token=token), host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(  # nosec B310  # fixed loopback http URL
                f"http://127.0.0.1:{port}/healthz", timeout=1
            ):
                return server
        except OSError:
            time.sleep(0.1)
    raise SystemExit("mock services did not start")


def http(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    token: str = DEFAULT_TOKEN,
) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # nosec B310
        return json.loads(response.read().decode("utf-8"))


def agent_ref(name: str) -> AgentRef:
    return AgentRef(id=name, version="1.0.0", digest=_DIGEST)


def result(invocation: Invocation, text: str) -> InvocationResult:
    return InvocationResult(
        run_id=invocation.run_id,
        trace_id=invocation.trace_id,
        agent_ref=invocation.agent_ref,
        text=text,
    )


def connector_specs(base_url: str, tenant: str = "local") -> list[ConnectorSpec]:
    """The two write connectors the tool gateway serves in the demo.

    The ticket connector is L2 here because the L3 approval already happened at
    the plan step; the gateway has no per-tool approval token to present.
    """
    return [
        ConnectorSpec(
            connector_id="mock-itsm",
            tenant=tenant,
            kind="http",
            base_url=base_url,
            auth_ref=SECRET_REF,
            methods=["GET", "POST"],
            path_prefixes=["/itsm/"],
            risk_level="L2",
        ),
        ConnectorSpec(
            connector_id="mock-wecom",
            tenant=tenant,
            kind="http",
            base_url=base_url,
            auth_ref=SECRET_REF,
            methods=["POST"],
            path_prefixes=["/wecom/"],
            risk_level="L2",
        ),
    ]


def _grants() -> list[ToolGrant]:
    return [
        ToolGrant(tool_id="mock-itsm", risk_level="L2"),
        ToolGrant(tool_id="mock-wecom", risk_level="L2"),
    ]


def start_gateway(port: int, base_url: str, token: str, audit_path: Path) -> Any:
    """Serve the two connectors through the tool gateway on loopback."""
    import os

    import uvicorn

    from adk_agent.audit import JsonlAuditSink
    from adk_agent.secretstore import PrefixedEnvSecretProvider
    from adk_agent.tools import FunctionRegistry, FunctionToolGateway
    from adk_agent.tools.connectors import HttpxAdapter, build_connector_tools
    from adk_agent.tools.service import build_tool_gateway_app

    os.environ["ADK_SECRET_MOCK_TOKEN"] = token
    tools = build_connector_tools(
        connector_specs(base_url),
        secrets=PrefixedEnvSecretProvider(),
        adapter=HttpxAdapter(trust_env=False),
    )
    gateway = FunctionToolGateway(FunctionRegistry(tools), audit=JsonlAuditSink(audit_path))
    app = build_tool_gateway_app(gateway, auth_token=token, trust_caller_policy=True)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(  # nosec B310  # fixed loopback http URL
                f"http://127.0.0.1:{port}/healthz", timeout=1
            ):
                return server
        except OSError:
            time.sleep(0.1)
    raise SystemExit("tool gateway did not start")


async def _ticket_via_gateway(invocation: Invocation, url: str, token: str) -> str:
    from adk_agent.tools.client import ToolGatewayClient

    client = ToolGatewayClient(url, token=token)
    ticket = await client.invoke(
        invocation,
        "mock-itsm",
        {
            "path": "/itsm/tickets",
            "method": "POST",
            "json_body": {
                "title": "客户无法登录",
                "description": invocation.input,
                "priority": "high",
            },
        },
        grants=_grants(),
        idempotency_key=f"{invocation.run_id}-itsm",
    )
    ticket_id = ticket["body"]["id"]
    await client.invoke(
        invocation,
        "mock-wecom",
        {
            "path": "/wecom/webhook",
            "method": "POST",
            "json_body": {"text": f"工单 {ticket_id} 已创建，请跟进。"},
        },
        grants=_grants(),
        idempotency_key=f"{invocation.run_id}-wecom",
    )
    return ticket_id


def build_agents(
    base: str,
    token: str = DEFAULT_TOKEN,
    gateway: tuple[str, str] | None = None,
) -> dict[str, Any]:
    async def support(invocation: Invocation) -> InvocationResult:
        return result(invocation, "建议先重置密码；如仍失败请创建工单。")

    async def ticket_writer(invocation: Invocation) -> InvocationResult:
        if gateway is not None:
            ticket_id = await _ticket_via_gateway(invocation, gateway[0], gateway[1])
            return result(invocation, f"已创建工单 {ticket_id}")
        ticket = await asyncio.to_thread(
            http,
            "POST",
            f"{base}/itsm/tickets",
            {
                "title": "客户无法登录",
                "description": invocation.input,
                "priority": "high",
            },
            token,
        )
        await asyncio.to_thread(
            http,
            "POST",
            f"{base}/wecom/webhook",
            {"text": f"工单 {ticket['id']} 已创建，请跟进。"},
            token,
        )
        return result(invocation, f"已创建工单 {ticket['id']}")

    return {"support": support, "ticket_writer": ticket_writer}


class PipelineSink:
    def __init__(self, pipeline: AuditPipeline) -> None:
        self._pipeline = pipeline

    async def emit(self, event: Any) -> None:
        await self._pipeline.append(event)


def build_plan(approval_timeout: float | None = None) -> OrchestrationPlan:
    return OrchestrationPlan(
        plan_id="support-flow",
        version="1.0.0",
        strategy="sequential",
        steps=[
            PlanStep(id="answer", agent_ref=agent_ref("support")),
            PlanStep(
                id="ticket",
                agent_ref=agent_ref("ticket_writer"),
                input="客户反馈验证码收不到，请创建工单。",
                risk_level="L3",
                approval_reason="创建工单会通知客户",
                timeout_seconds=approval_timeout,
            ),
        ],
    )


def parent_invocation(input_text: str, deadline: datetime | None = None) -> Invocation:
    return Invocation(
        run_id="support-run-1",
        trace_id="support-trace-1",
        principal=Principal(tenant="local", subject="demo", kind="human"),
        agent_ref=agent_ref("support-flow"),
        input=input_text,
        deadline=deadline,
    )
