#!/usr/bin/env python3
"""Run the support demo end to end against the local mock services."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import time
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from adk_agent.approvals import FileApprovalInbox  # noqa: E402
from adk_agent.audit import AuditPipeline, verify_audit_file  # noqa: E402
from adk_agent.orchestration import (  # noqa: E402
    AgentGrantPolicyEngine,
    ApprovalDenied,
    PlanExecutor,
)
from support_demo_flow import (  # noqa: E402
    PipelineSink,
    build_agents,
    build_plan,
    free_port,
    http,
    parent_invocation,
    require,
    start_mock,
)

_TOKEN = "demo-token"  # nosec B105  # loopback-only demo token


def _start_mock(port: int) -> Any:
    return start_mock(port, _TOKEN)


def _http(method: str, url: str, body: dict[str, Any] | None = None) -> Any:
    return http(method, url, body, _TOKEN)


async def _drive(
    executor: PlanExecutor,
    inbox: FileApprovalInbox,
    *,
    deny: bool,
    interactive: bool,
    wait_seconds: float,
    seen: list[str],
) -> tuple[Any, bool, str]:
    approval_timeout = wait_seconds + 60 if interactive else None
    deadline = (
        datetime.now(timezone.utc) + timedelta(seconds=wait_seconds + 60) if interactive else None
    )
    task = asyncio.create_task(
        executor.run(
            build_plan(approval_timeout),
            parent_invocation("客户无法登录", deadline),
            approvals=inbox,  # type: ignore[arg-type]
        )
    )
    asked = False
    while not task.done():
        pending = inbox.pending()
        if not asked and (pending or (interactive and seen)):
            print("PASS approval requested")
            request_id = seen[0] if seen else pending[0].request_id
            asked = True
            if interactive:
                print(f"WAITING approval {request_id} in {inbox.root}")
                deadline = time.monotonic() + wait_seconds
                while not task.done() and time.monotonic() < deadline:
                    record = inbox.get(request_id)
                    if record is not None and record.decision is not None:
                        break
                    await asyncio.sleep(0.1)
                if not task.done() and time.monotonic() >= deadline:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                    return None, asked, "timeout"
            else:
                inbox.decide(
                    request_id,
                    approved=not deny,
                    approver="demo",
                    reason="approved" if not deny else "denied",
                )
        await asyncio.sleep(0.05)
    try:
        result = await task
    except ApprovalDenied:
        return None, asked, "denied"
    return result, asked, "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the support demo.")
    parser.add_argument("--deny", action="store_true", help="deny the ticket step")
    parser.add_argument("--workdir", default=None, help="keep state (default: a temp dir)")
    parser.add_argument(
        "--approvals-dir", default=None, help="approval inbox to write (e.g. the console one)"
    )
    parser.add_argument(
        "--audit-file", default=None, help="audit chain file to write (console-readable)"
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="leave the approval pending until a human decides",
    )
    parser.add_argument(
        "--wait-seconds", type=float, default=300.0, help="interactive approval timeout"
    )
    args = parser.parse_args()

    workdir = Path(args.workdir) if args.workdir else Path(mkdtemp(prefix="adk-support-"))
    workdir.mkdir(parents=True, exist_ok=True)
    port = free_port()
    server = _start_mock(port)
    base = f"http://127.0.0.1:{port}"
    try:
        print("PASS mock services started")
        audit_path = Path(args.audit_file) if args.audit_file else workdir / "audit.jsonl"
        approvals = Path(args.approvals_dir) if args.approvals_dir else workdir / "approvals"
        seen: list[str] = []
        on_submit = None
        if args.interactive:

            def on_submit(request: Any) -> None:
                seen.append(request.request_id)

        ttl = args.wait_seconds + 60 if args.interactive else None
        inbox = FileApprovalInbox(
            approvals, poll_seconds=0.05, ttl_seconds=ttl, on_submit=on_submit
        )
        pipeline = AuditPipeline(audit_path)
        executor = PlanExecutor(
            build_agents(base, _TOKEN),
            policy=AgentGrantPolicyEngine(["support", "ticket_writer"]),
            audit=PipelineSink(pipeline),
        )
        result, asked, status = asyncio.run(
            _drive(
                executor,
                inbox,
                deny=args.deny,
                interactive=args.interactive,
                wait_seconds=args.wait_seconds,
                seen=seen,
            )
        )
        if status == "timeout":
            print("TIMEOUT approval was not decided")
            return 3
        if args.deny or status == "denied":
            require(asked, "no approval request was issued")
            require(not _http("GET", f"{base}/wecom/messages"), "deny path notified wecom")
            try:
                _http("GET", f"{base}/itsm/tickets/t-1")
            except urllib.error.HTTPError as exc:
                require(exc.code == 404, "deny path created a ticket")
            else:
                raise SystemExit("FAIL deny path created a ticket")
            print("PASS deny path left no ticket or message")
            print("DENIED plan stopped before the ticket step")
            return 2
        require(result is not None, "plan produced no result")
        print("PASS plan answered")
        ticket_id = "t-1"
        print(f"PASS ticket created {ticket_id}")
        fetched = _http("GET", f"{base}/itsm/tickets/{ticket_id}")
        require(fetched["status"] == "open", "ticket is not open")
        print("PASS ticket is open")
        messages = _http("GET", f"{base}/wecom/messages")
        require(any(ticket_id in item["text"] for item in messages), "wecom not notified")
        print("PASS wecom notified")
        count = verify_audit_file(audit_path)
        actions = {
            json.loads(line)["event"]["action"] for line in audit_path.read_text().splitlines()
        }
        require("orchestration.approval" in actions, "missing approval audit")
        print(f"PASS audit verified ({count} records)")
        print("ALL PASS")
        return 0
    finally:
        server.should_exit = True
        time.sleep(0.2)


if __name__ == "__main__":
    raise SystemExit(main())
