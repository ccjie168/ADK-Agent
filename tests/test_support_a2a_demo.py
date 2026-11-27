"""SLICE-306: the support plan is reachable over A2A."""

from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
_AGENT_FILE = SCRIPTS / "support_a2a_agent.py"
_CLIENT = SCRIPTS / "prove_workbuddy_a2a.py"
_DOC = ROOT / "docs" / "demo" / "support-agent.md"

_HAS_A2A = importlib.util.find_spec("a2a") is not None
needs_a2a = pytest.mark.skipif(not _HAS_A2A, reason="a2a-sdk is not installed")
AUTH = {"Authorization": "Bearer secret"}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class MockServices:
    def __init__(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        import uvicorn

        from mock_services import build_mock_app

        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self._server = uvicorn.Server(
            uvicorn.Config(
                build_mock_app(token="demo-token"),
                host="127.0.0.1",
                port=self.port,
                log_level="error",
            )
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def __enter__(self) -> MockServices:
        self._thread.start()
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{self.url}/healthz", timeout=1):  # nosec B310
                    return self
            except OSError:
                time.sleep(0.1)
        raise AssertionError("mock services did not start")

    def __exit__(self, *exc: object) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)

    def get(self, path: str) -> object:
        request = urllib.request.Request(
            f"{self.url}{path}",
            headers={"Authorization": "Bearer demo-token"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310
            return json.loads(response.read().decode("utf-8"))


@pytest.fixture
def mock():
    with MockServices() as services:
        yield services


def _payload(text: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "role": "user",
                "parts": [{"kind": "text", "text": text}],
                "messageId": "m1",
            }
        },
    }


def _a2a_text(payload: object) -> str:
    found: list[str] = []

    def walk(node: object) -> None:
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


def _load_agent(monkeypatch, tmp_path: Path, mock_url: str):
    monkeypatch.setenv("SUPPORT_MOCK_URL", mock_url)
    monkeypatch.setenv("SUPPORT_APPROVALS_DIR", str(tmp_path / "approvals"))
    monkeypatch.setenv("SUPPORT_AUDIT_FILE", str(tmp_path / "support-audit.jsonl"))
    monkeypatch.setenv("SUPPORT_WAIT_SECONDS", "60")
    spec = importlib.util.spec_from_file_location("support_a2a_agent_under_test", _AGENT_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.agent


def _decide(root: Path, *, approved: bool) -> threading.Thread:
    def run() -> None:
        from adk_agent.approvals import FileApprovalInbox

        inbox = FileApprovalInbox(root, poll_seconds=0.05)
        deadline = time.time() + 30
        while time.time() < deadline:
            pending = inbox.pending()
            if pending:
                inbox.decide(
                    pending[0].request_id,
                    approved=approved,
                    approver="tester",
                    reason="approved" if approved else "denied",
                )
                return
            time.sleep(0.05)
        raise AssertionError("no approval request appeared")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


@needs_a2a
def test_support_a2a_agent_approves_and_creates_ticket(monkeypatch, tmp_path, mock):
    from starlette.testclient import TestClient

    from adk_agent.a2a import build_a2a_app

    agent = _load_agent(monkeypatch, tmp_path, mock.url)
    decider = _decide(tmp_path / "approvals", approved=True)
    with TestClient(build_a2a_app(agent, auth_token="secret")) as client:
        response = client.post("/", json=_payload("客户无法登录"), headers=AUTH)
    decider.join(timeout=10)

    assert response.status_code == 200, response.text
    text = _a2a_text(response.json())
    assert "t-1" in text, text
    assert mock.get("/itsm/tickets/t-1")["status"] == "open"
    assert any("t-1" in item["text"] for item in mock.get("/wecom/messages"))


@needs_a2a
def test_support_a2a_agent_denies_without_ticket(monkeypatch, tmp_path, mock):
    from starlette.testclient import TestClient

    from adk_agent.a2a import build_a2a_app

    agent = _load_agent(monkeypatch, tmp_path, mock.url)
    decider = _decide(tmp_path / "approvals", approved=False)
    with TestClient(
        build_a2a_app(agent, auth_token="secret"), raise_server_exceptions=False
    ) as client:
        response = client.post("/", json=_payload("客户无法登录"), headers=AUTH)
    decider.join(timeout=10)

    with pytest.raises(urllib.error.HTTPError) as excinfo:
        mock.get("/itsm/tickets/t-1")
    assert excinfo.value.code == 404
    assert mock.get("/wecom/messages") == []
    assert response.status_code == 200, response.text
    assert "被拒绝" in _a2a_text(response.json())


@needs_a2a
def test_support_a2a_requires_bearer_token(monkeypatch, tmp_path, mock):
    from starlette.testclient import TestClient

    from adk_agent.a2a import build_a2a_app

    agent = _load_agent(monkeypatch, tmp_path, mock.url)
    with TestClient(build_a2a_app(agent, auth_token="secret")) as client:
        response = client.post("/", json=_payload("hi"))

    assert response.status_code == 401


@needs_a2a
def test_workbuddy_a2a_end_to_end(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            str(_CLIENT),
            "--workdir",
            str(tmp_path),
            "--wait-seconds",
            "60",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=240,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS anonymous call rejected" in proc.stdout
    assert "ALL PASS" in proc.stdout


def test_support_a2a_doc_matches_cli():
    agent_source = _AGENT_FILE.read_text(encoding="utf-8")
    client_source = _CLIENT.read_text(encoding="utf-8")
    doc = _DOC.read_text(encoding="utf-8")

    for variable in (
        "SUPPORT_MOCK_URL",
        "SUPPORT_MOCK_TOKEN",
        "SUPPORT_APPROVALS_DIR",
        "SUPPORT_AUDIT_FILE",
        "SUPPORT_WAIT_SECONDS",
    ):
        assert variable in agent_source
        assert variable in doc
    for flag in ("--workdir", "--interactive", "--wait-seconds", "--deny", "--port"):
        assert flag in client_source
        assert flag in doc
    assert "support_flow" in doc
