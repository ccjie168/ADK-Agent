#!/usr/bin/env python3
"""Run the support demo end to end against the local mock services."""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adk_agent.approvals import FileApprovalInbox  # noqa: E402
from adk_agent.audit import AuditPipeline, verify_audit_file  # noqa: E402
from adk_agent.core import (  # noqa: E402
    AgentRef,
    Invocation,
    InvocationResult,
    OrchestrationPlan,
    PlanStep,
    Principal,
)
from adk_agent.orchestration import (  # noqa: E402
    AgentGrantPolicyEngine,
    ApprovalDenied,
    PlanExecutor,
)

_DIGEST = "d" * 64
_TOKEN = "demo-token"  # nosec B105  # loopback-only demo token


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL {message}")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_mock(port: int) -> Any:
    import uvicorn

    from mock_services import build_mock_app

    server = uvicorn.Server(
        uvicorn.Config(build_mock_app(token=_TOKEN), host="127.0.0.1", port=port, log_level="error")
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


def _http(method: str, url: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {_TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # nosec B310
        return json.loads(response.read().decode("utf-8"))


def _ref(name: str) -> AgentRef:
    return AgentRef(id=name, version="1.0.0", digest=_DIGEST)


def _result(invocation: Invocation, text: str) -> InvocationResult:
    return InvocationResult(
        run_id=invocation.run_id,
        trace_id=invocation.trace_id,
        agent_ref=invocation.agent_ref,
        text=text,
    )


def _agents(base: str) -> dict[str, Any]:
    async def support(invocation: Invocation) -> InvocationResult:
        return _result(invocation, "建议先重置密码；如仍失败请创建工单。")

    async def ticket_writer(invocation: Invocation) -> InvocationResult:
        ticket = await asyncio.to_thread(
            _http,
            "POST",
            f"{base}/itsm/tickets",
            {
                "title": "客户无法登录",
                "description": invocation.input,
                "priority": "high",
            },
        )
        await asyncio.to_thread(
            _http,
            "POST",
            f"{base}/wecom/webhook",
            {"text": f"工单 {ticket['id']} 已创建，请跟进。"},
        )
        return _result(invocation, f"已创建工单 {ticket['id']}")

    return {"support": support, "ticket_writer": ticket_writer}


class _PipelineSink:
    def __init__(self, pipeline: AuditPipeline) -> None:
        self._pipeline = pipeline

    async def emit(self, event: Any) -> None:
        await self._pipeline.append(event)


def _plan() -> OrchestrationPlan:
    return OrchestrationPlan(
        plan_id="support-flow",
        version="1.0.0",
        strategy="sequential",
        steps=[
            PlanStep(id="answer", agent_ref=_ref("support")),
            PlanStep(
                id="ticket",
                agent_ref=_ref("ticket_writer"),
                input="客户反馈验证码收不到，请创建工单。",
                risk_level="L3",
                approval_reason="创建工单会通知客户",
            ),
        ],
    )


def _parent() -> Invocation:
    return Invocation(
        run_id="support-run-1",
        trace_id="support-trace-1",
        principal=Principal(tenant="local", subject="demo", kind="human"),
        agent_ref=_ref("support-flow"),
        input="客户无法登录",
    )


async def _drive(
    executor: PlanExecutor, inbox: FileApprovalInbox, *, deny: bool
) -> tuple[Any, bool]:
    task = asyncio.create_task(
        executor.run(_plan(), _parent(), approvals=inbox)  # type: ignore[arg-type]
    )
    asked = False
    while not task.done():
        pending = inbox.pending()
        if pending and not asked:
            print("PASS approval requested")
            inbox.decide(
                pending[0].request_id,
                approved=not deny,
                approver="demo",
                reason="approved" if not deny else "denied",
            )
            asked = True
        await asyncio.sleep(0.05)
    if deny:
        try:
            await task
        except ApprovalDenied:
            return None, asked
        raise SystemExit("FAIL denied step still executed")
    return await task, asked


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the support demo.")
    parser.add_argument("--deny", action="store_true", help="deny the ticket step")
    parser.add_argument("--workdir", default=None, help="keep state (default: a temp dir)")
    args = parser.parse_args()

    workdir = Path(args.workdir) if args.workdir else Path(mkdtemp(prefix="adk-support-"))
    workdir.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    server = _start_mock(port)
    base = f"http://127.0.0.1:{port}"
    try:
        print("PASS mock services started")
        audit_path = workdir / "audit.jsonl"
        inbox = FileApprovalInbox(workdir / "approvals", poll_seconds=0.05)
        pipeline = AuditPipeline(audit_path)
        executor = PlanExecutor(
            _agents(base),
            policy=AgentGrantPolicyEngine(["support", "ticket_writer"]),
            audit=_PipelineSink(pipeline),
        )
        result, asked = asyncio.run(_drive(executor, inbox, deny=args.deny))
        if args.deny:
            _require(asked, "no approval request was issued")
            _require(not _http("GET", f"{base}/wecom/messages"), "deny path notified wecom")
            try:
                _http("GET", f"{base}/itsm/tickets/t-1")
            except urllib.error.HTTPError as exc:
                _require(exc.code == 404, "deny path created a ticket")
            else:
                raise SystemExit("FAIL deny path created a ticket")
            print("PASS deny path left no ticket or message")
            print("DENIED plan stopped before the ticket step")
            return 2
        _require(result is not None, "plan produced no result")
        print("PASS plan answered")
        ticket_id = "t-1"
        print(f"PASS ticket created {ticket_id}")
        fetched = _http("GET", f"{base}/itsm/tickets/{ticket_id}")
        _require(fetched["status"] == "open", "ticket is not open")
        print("PASS ticket is open")
        messages = _http("GET", f"{base}/wecom/messages")
        _require(any(ticket_id in item["text"] for item in messages), "wecom not notified")
        print("PASS wecom notified")
        count = verify_audit_file(audit_path)
        actions = {
            json.loads(line)["event"]["action"] for line in audit_path.read_text().splitlines()
        }
        _require("orchestration.approval" in actions, "missing approval audit")
        print(f"PASS audit verified ({count} records)")
        print("ALL PASS")
        return 0
    finally:
        server.should_exit = True
        time.sleep(0.2)


if __name__ == "__main__":
    raise SystemExit(main())
