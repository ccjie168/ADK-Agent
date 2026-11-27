#!/usr/bin/env python3
"""Pretend to be WorkBuddy: call the support agent over A2A and approve the ticket."""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404
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
sys.path.insert(0, str(ROOT / "scripts"))

from adk_agent.approvals import FileApprovalInbox  # noqa: E402
from adk_agent.audit import verify_audit_file  # noqa: E402
from support_demo_flow import (  # noqa: E402
    DEFAULT_TOKEN,
    free_port,
    http,
    require,
    start_mock,
)

_AGENT = ROOT / "scripts" / "support_a2a_agent.py"
_CARD = "/.well-known/agent-card.json"
_QUESTION = "客户无法登录，验证码收不到，请帮我建单。"


def _rpc(port: int, text: str, token: str | None) -> tuple[int, Any]:
    body = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "role": "user",
                "parts": [{"kind": "text", "text": text}],
                "messageId": "m1",
            },
            "configuration": {},
        },
    }
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/", data=data, method="POST", headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def _a2a_text(payload: Any) -> str:
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("text"), str):
                found.append(node["text"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return "".join(found)


def _wait_ready(port: int, token: str) -> None:
    deadline = time.time() + 60
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{_CARD}",
        headers={"Authorization": f"Bearer {token}"},
    )
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=2) as response:  # nosec B310
                if response.status == 200:
                    return
        except (OSError, urllib.error.HTTPError):
            pass
        time.sleep(0.2)
    raise SystemExit("FAIL a2a server did not start")


def _start_agent(port: int, workdir: Path, env: dict[str, str]) -> Any:
    return subprocess.Popen(  # nosec B603
        [
            sys.executable,
            "-m",
            "adk_agent",
            "serve-a2a",
            "--agent",
            str(_AGENT),
            "--auth-token-env",
            "SUPPORT_A2A_TOKEN",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--audit-file",
            str(workdir / "a2a-audit.jsonl"),
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Mock WorkBuddy A2A client.")
    parser.add_argument("--workdir", default=None, help="keep state (default: a temp dir)")
    parser.add_argument(
        "--interactive", action="store_true", help="wait for a human decision in the console"
    )
    parser.add_argument(
        "--wait-seconds", type=float, default=300.0, help="interactive approval timeout"
    )
    parser.add_argument("--deny", action="store_true", help="deny the ticket step")
    parser.add_argument("--port", type=int, default=None, help="fixed A2A port")
    args = parser.parse_args()

    workdir = Path(args.workdir) if args.workdir else Path(mkdtemp(prefix="adk-workbuddy-"))
    workdir.mkdir(parents=True, exist_ok=True)
    port = args.port or free_port()
    mock_port = free_port()
    mock = start_mock(mock_port, DEFAULT_TOKEN)
    token = DEFAULT_TOKEN
    approvals = workdir / "approvals"
    env = dict(os.environ)
    env.update(
        {
            "SUPPORT_MOCK_URL": f"http://127.0.0.1:{mock_port}",
            "SUPPORT_MOCK_TOKEN": DEFAULT_TOKEN,
            "SUPPORT_APPROVALS_DIR": str(approvals),
            "SUPPORT_AUDIT_FILE": str(workdir / "support-audit.jsonl"),
            "SUPPORT_WAIT_SECONDS": str(args.wait_seconds + 60),
            "SUPPORT_A2A_TOKEN": token,
        }
    )
    server = _start_agent(port, workdir, env)
    try:
        _wait_ready(port, token)
        print("PASS agent card returned")

        anonymous, _ = _rpc(port, "hi", None)
        require(anonymous == 401, f"anonymous call returned {anonymous}")
        print("PASS anonymous call rejected")

        result: dict[str, Any] = {}

        def call() -> None:
            result["status"], result["body"] = _rpc(port, _QUESTION, token)

        thread = threading.Thread(target=call, daemon=True)
        thread.start()

        inbox = FileApprovalInbox(approvals, poll_seconds=0.1)
        deadline = time.time() + 60
        pending = []
        while time.time() < deadline and thread.is_alive():
            pending = inbox.pending()
            if pending:
                break
            time.sleep(0.1)
        require(bool(pending), "no approval request appeared")
        request_id = pending[0].request_id

        if args.interactive:
            print(f"WAITING approval {request_id} in {approvals}")
            deadline = time.time() + args.wait_seconds
            while time.time() < deadline and thread.is_alive():
                record = inbox.get(request_id)
                if record is not None and record.decision is not None:
                    break
                time.sleep(0.2)
            if thread.is_alive():
                print("TIMEOUT approval was not decided")
                return 3
        else:
            inbox.decide(
                request_id,
                approved=not args.deny,
                approver="workbuddy",
                reason="approved" if not args.deny else "denied",
            )

        thread.join(timeout=90)
        require(not thread.is_alive(), "a2a call did not finish")
        status = result.get("status")
        body = result.get("body")
        text = _a2a_text(body)

        if args.deny or "被拒绝" in text:
            require(status == 200, f"deny call returned {status}")
            require("被拒绝" in text, f"deny reply missing rejection: {text}")
            print("PASS reply reports the rejection")
            messages = http("GET", f"http://127.0.0.1:{mock_port}/wecom/messages")
            require(messages == [], "deny path notified wecom")
            try:
                http("GET", f"http://127.0.0.1:{mock_port}/itsm/tickets/t-1")
            except urllib.error.HTTPError as exc:
                require(exc.code == 404, "deny path created a ticket")
            else:
                raise SystemExit("FAIL deny path created a ticket")
            print("PASS deny path left no ticket or message")
            print("DENIED plan stopped before the ticket step")
            return 2

        require(status == 200, f"a2a call returned {status}: {body}")
        require("t-1" in text, f"reply missing the ticket id: {text}")
        print("PASS reply contains ticket")
        fetched = http("GET", f"http://127.0.0.1:{mock_port}/itsm/tickets/t-1")
        require(fetched["status"] == "open", "ticket is not open")
        print("PASS ticket is open")
        messages = http("GET", f"http://127.0.0.1:{mock_port}/wecom/messages")
        require(any("t-1" in item["text"] for item in messages), "wecom not notified")
        print("PASS wecom notified")

        plan_audit = workdir / "support-audit.jsonl"
        count = verify_audit_file(plan_audit)
        actions = {
            json.loads(line)["event"]["action"] for line in plan_audit.read_text().splitlines()
        }
        require("orchestration.approval" in actions, "missing approval audit")
        print(f"PASS audit verified ({count} records)")
        print("ALL PASS")
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        mock.should_exit = True
        time.sleep(0.2)


if __name__ == "__main__":
    raise SystemExit(main())
