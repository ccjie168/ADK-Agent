"""SLICE-308: the support demo's writes can run through the tool gateway."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from adk_agent.audit import JsonlAuditSink
from adk_agent.core import Invocation, Principal, ToolGrant
from adk_agent.secretstore import PrefixedEnvSecretProvider
from adk_agent.tools import FunctionRegistry, FunctionToolGateway
from adk_agent.tools.connectors import build_connector_tools
from adk_agent.tools.service import build_tool_gateway_app

ROOT = Path(__file__).resolve().parents[1]
_DEMO = ROOT / "scripts" / "prove_support_demo.py"
_FLOW = ROOT / "scripts" / "support_demo_flow.py"
_DOC = ROOT / "docs" / "demo" / "support-agent.md"


def _run(*extra: str, workdir: Path, timeout: float = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_DEMO), "--workdir", str(workdir), *extra],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _audit_actions(path: Path) -> list[tuple[str, str]]:
    actions = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        event = record.get("event", record)
        actions.append((event["action"], event["target"]))
    return actions


def test_support_demo_tool_gateway_path(tmp_path):
    proc = _run("--tool-gateway", workdir=tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS tools went through the gateway" in proc.stdout
    assert "ALL PASS" in proc.stdout
    calls = _audit_actions(tmp_path / "gateway-audit.jsonl")
    assert ("tool.call", "mock-itsm") in calls
    assert ("tool.call", "mock-wecom") in calls


def test_tool_gateway_denies_ungranted_tool(tmp_path):
    import os

    os.environ["ADK_SECRET_MOCK_TOKEN"] = "demo-token"  # pragma: allowlist secret
    sys.path.insert(0, str(ROOT / "scripts"))
    from support_demo_flow import connector_specs

    specs = [
        spec for spec in connector_specs("http://127.0.0.1:9") if spec.connector_id == "mock-itsm"
    ]
    tools = build_connector_tools(specs, secrets=PrefixedEnvSecretProvider())
    gateway = FunctionToolGateway(
        FunctionRegistry(tools), audit=JsonlAuditSink(tmp_path / "gateway.jsonl")
    )
    app = build_tool_gateway_app(gateway, auth_token="secret", trust_caller_policy=True)
    body = {
        "invocation": Invocation(
            run_id="r1",
            trace_id="t1",
            principal=Principal(tenant="local", subject="demo", kind="service"),
            agent_ref={"id": "ticket_writer", "version": "1.0.0", "digest": "d" * 64},
            input="x",
        ).model_dump(mode="json"),
        "request": {
            "tool_id": "mock-wecom",
            "args": {"path": "/wecom/webhook", "method": "POST", "json_body": {"text": "x"}},
        },
        "grants": [
            ToolGrant(tool_id="mock-itsm", risk_level="L3").model_dump(mode="json"),
            ToolGrant(tool_id="mock-wecom", risk_level="L2").model_dump(mode="json"),
        ],
    }
    with TestClient(app) as client:
        response = client.post("/v1/invoke", json=body, headers={"Authorization": "Bearer secret"})

    assert response.status_code == 403
    assert response.json()["error"] == "tool_denied"


def test_support_demo_default_path_unchanged(tmp_path):
    proc = _run(workdir=tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert "PASS ticket created t-1" in proc.stdout
    assert "tools went through the gateway" not in proc.stdout
    assert not (tmp_path / "gateway-audit.jsonl").exists()


def test_support_doc_mentions_tool_gateway():
    doc = _DOC.read_text(encoding="utf-8")
    demo = _DEMO.read_text(encoding="utf-8")
    flow = _FLOW.read_text(encoding="utf-8")

    assert "--tool-gateway" in demo
    assert "--tool-gateway" in doc
    assert "工具网关" in doc
    assert "mock-wecom" in doc
    assert "connector_specs" in flow
