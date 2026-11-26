"""SLICE-305: the support demo can be approved and viewed from the console."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.approvals import FileApprovalInbox
from adk_agent.console import build_console_app
from adk_agent.registry import FileConnectorStore, FileCredentialStore

ROOT = Path(__file__).resolve().parents[1]
_DEMO = ROOT / "scripts" / "prove_support_demo.py"
_REGISTER = ROOT / "scripts" / "support_demo_register.py"


def _wait_for_request(root: Path, timeout: float = 10.0):
    inbox = FileApprovalInbox(root, poll_seconds=0.05)
    deadline = time.time() + timeout
    while time.time() < deadline:
        pending = inbox.pending()
        if pending:
            return inbox, pending[0]
        time.sleep(0.05)
    raise AssertionError("no approval request appeared")


def test_support_demo_interactive_waits_for_decision(tmp_path):
    approvals = tmp_path / "approvals"
    proc = subprocess.Popen(
        [
            sys.executable,
            str(_DEMO),
            "--interactive",
            "--wait-seconds",
            "30",
            "--approvals-dir",
            str(approvals),
            "--audit-file",
            str(tmp_path / "audit.jsonl"),
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    inbox, request = _wait_for_request(approvals)
    inbox.decide(request.request_id, approved=True, approver="tester")
    stdout, stderr = proc.communicate(timeout=60)

    assert proc.returncode == 0, stdout + stderr
    assert "WAITING" in stdout
    assert "ALL PASS" in stdout


def test_support_demo_interactive_timeout(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            str(_DEMO),
            "--interactive",
            "--wait-seconds",
            "1",
            "--approvals-dir",
            str(tmp_path / "approvals"),
            "--audit-file",
            str(tmp_path / "audit.jsonl"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "TIMEOUT" in proc.stdout
    requests = list((tmp_path / "approvals").glob("*.request.json"))
    assert requests
    payload = json.loads(requests[0].read_text(encoding="utf-8"))
    assert payload["expires_at"] is not None


def test_register_mock_connectors(tmp_path):
    connectors = tmp_path / "connectors"
    credentials = tmp_path / "credentials"
    proc = subprocess.run(
        [
            sys.executable,
            str(_REGISTER),
            "--connectors-dir",
            str(connectors),
            "--credentials-dir",
            str(credentials),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 0, proc.stderr
    again = subprocess.run(
        [
            sys.executable,
            str(_REGISTER),
            "--connectors-dir",
            str(connectors),
            "--credentials-dir",
            str(credentials),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert again.returncode == 0, again.stderr
    specs = asyncio.run(FileConnectorStore(connectors).list("local"))
    bindings = asyncio.run(FileCredentialStore(credentials).list("local"))

    assert [spec.connector_id for spec in specs] == ["mock-itsm", "mock-quark"]
    assert all(spec.auth_ref == "secret://local/mock_token" for spec in specs)
    assert [binding.credential_id for binding in bindings] == ["mock-token-ref"]
    assert bindings[0].enabled is True


def test_console_lists_mock_connectors(tmp_path):
    subprocess.run(
        [
            sys.executable,
            str(_REGISTER),
            "--connectors-dir",
            str(tmp_path / "connectors"),
            "--credentials-dir",
            str(tmp_path / "credentials"),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    app = build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token="secret",
        roles=["admin"],
        connectors=FileConnectorStore(tmp_path / "connectors"),
    )
    with TestClient(app) as client:
        response = client.get("/api/connectors", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 200
    assert [item["connector_id"] for item in response.json()] == ["mock-itsm", "mock-quark"]


def test_support_console_doc_matches_cli():
    demo = _DEMO.read_text(encoding="utf-8")
    register = _REGISTER.read_text(encoding="utf-8")
    doc = (ROOT / "docs" / "demo" / "support-agent.md").read_text(encoding="utf-8")

    for flag in ("--interactive", "--approvals-dir", "--audit-file", "--wait-seconds"):
        assert flag in demo
        assert flag in doc
    assert "--connectors-dir" in register
    assert "--credentials-dir" in register
    assert "mock-itsm" in doc and "mock-quark" in doc
