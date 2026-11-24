"""SLICE-272: the security aggregate endpoint (ADR-0042)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.audit.query import FileAuditQuery
from adk_agent.console import build_console_app

AUTH = {"Authorization": "Bearer secret"}


def _agents() -> dict[str, LlmAgent]:
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def _client(tmp_path, *, roles=("admin",), **kwargs):
    audit_path = tmp_path / "audit.jsonl"
    audit_path.write_text("", encoding="utf-8")
    app = build_console_app(
        _agents(),
        auth_token="secret",
        roles=list(roles),
        audit_query=FileAuditQuery(audit_path),
        **kwargs,
    )
    return TestClient(app)


def test_security_requires_capability(tmp_path):
    with _client(tmp_path, roles=["base"]) as client:
        response = client.get("/api/security", headers=AUTH)

    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}


def test_security_summarises_audit_and_policy(tmp_path):
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(json.dumps({"version": "v7", "bindings": []}), encoding="utf-8")
    with _client(tmp_path, policy_file=str(policy_file)) as client:
        response = client.get("/api/security", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["audit"]["backend"] == "file"
    assert body["audit"]["records"] == 0
    assert body["policy"] == {"version": "v7", "bindings": 0}
    assert body["scans"] is None
    assert set(body["keys"]) == {"audit_signing", "credentials"}


def test_security_verifies_the_file_chain(tmp_path):
    with _client(tmp_path) as client:
        response = client.get("/api/security?verify=1", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["audit"]["verified"] is True


def test_security_never_leaks_key_material(tmp_path, monkeypatch):
    marker = "-".join(["leak", "marker", "value"])
    monkeypatch.setenv(
        "ADK_AUDIT_KEYRING",
        json.dumps({"active": "k2", "keys": {"k1": marker, "k2": marker + "-2"}}),
    )
    monkeypatch.delenv("ADK_SECRET_KEKS", raising=False)
    monkeypatch.delenv("ADK_SECRET_KEKS_FILE", raising=False)
    with _client(tmp_path) as client:
        response = client.get("/api/security", headers=AUTH)

    body = response.text
    assert response.status_code == 200
    assert marker not in body
    assert json.loads(body)["keys"]["audit_signing"]["active"] == "k2"
    assert sorted(json.loads(body)["keys"]["audit_signing"]["kids"]) == ["k1", "k2"]


def test_security_reads_the_scan_report(tmp_path):
    report = tmp_path / "security.json"
    report.write_text(
        json.dumps(
            {
                "generated_at": "2026-11-24T00:00:00Z",
                "codeql": {"open": 0},
                "dependencies": {"vulnerabilities": 0},
            }
        ),
        encoding="utf-8",
    )
    with _client(tmp_path, security_report=str(report)) as client:
        response = client.get("/api/security", headers=AUTH)

    assert response.json()["scans"]["codeql"]["open"] == 0


def test_security_counts_credentials_by_key(tmp_path, monkeypatch):
    import base64
    from datetime import datetime, timezone

    from adk_agent.core import CredentialBinding
    from adk_agent.registry import FileCredentialStore

    kek_one = base64.b64encode(b"0" * 32).decode("ascii")
    kek_two = base64.b64encode(b"1" * 32).decode("ascii")
    monkeypatch.setenv(
        "ADK_SECRET_KEKS",
        json.dumps({"active": "kek-2", "keys": {"kek-1": kek_one, "kek-2": kek_two}}),
    )
    store = FileCredentialStore(tmp_path / "creds")
    now = datetime(2026, 11, 24, tzinfo=timezone.utc)
    for cid, kid in (("old", "kek-1"), ("new", "kek-2"), ("bare", None)):
        binding = CredentialBinding(
            credential_id=cid,
            tenant="local",
            secret_ref=f"secret://local/{cid}",
            created_by="admin",
            created_at=now,
            wrapped_secret={"v": 1, "key_id": kid} if kid else None,
            secret_key_id=kid,
        )
        __import__("asyncio").run(store.add(binding))

    with _client(tmp_path, credentials=store) as client:
        body = client.get("/api/security", headers=AUTH).json()

    keys = body["keys"]["credentials"]
    assert keys["active_key_id"] == "kek-2"
    assert keys["by_key_id"] == {"kek-1": 1, "kek-2": 1, "unwrapped": 1}
    assert keys["needs_rewrap"] == 1
