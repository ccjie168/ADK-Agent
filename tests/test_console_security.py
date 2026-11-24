"""SLICE-272: the security aggregate endpoint (ADR-0042)."""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timezone

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
    ciphertext_marker = "-".join(["cipher", "text", "marker"])
    for cid, kid in (("old", "kek-1"), ("new", "kek-2"), ("bare", None)):
        binding = CredentialBinding(
            credential_id=cid,
            tenant="local",
            secret_ref=f"secret://local/{cid}",
            created_by="admin",
            created_at=now,
            wrapped_secret={"v": 1, "key_id": kid, "c": ciphertext_marker} if kid else None,
            secret_key_id=kid,
        )
        asyncio.run(store.add(binding))

    with _client(tmp_path, credentials=store) as client:
        response = client.get("/api/security", headers=AUTH)
        body = response.json()

    assert ciphertext_marker not in response.text
    keys = body["keys"]["credentials"]
    assert keys["active_key_id"] == "kek-2"
    assert keys["by_key_id"] == {"kek-1": 1, "kek-2": 1, "unwrapped": 1}
    assert keys["needs_rewrap"] == 1


def test_security_rejects_ill_shaped_keyring(tmp_path, monkeypatch):
    marker = "-".join(["echo", "me"])
    monkeypatch.setenv("ADK_AUDIT_KEYRING", json.dumps({"active": "k", "keys": [marker]}))
    monkeypatch.delenv("ADK_SECRET_KEKS", raising=False)
    with _client(tmp_path) as client:
        response = client.get("/api/security", headers=AUTH)
        verified = client.get("/api/security?verify=1", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["keys"]["audit_signing"]["error"] == "invalid_keyring"
    assert marker not in response.text
    assert verified.status_code == 200
    assert verified.json()["audit"]["error"] == "invalid_keyring"


def test_security_lists_the_newest_memory_event(tmp_path):
    from adk_agent.audit import ListAuditSink
    from adk_agent.core import AgentRef, AuditEvent, Principal

    sink = ListAuditSink()
    principal = Principal(tenant="local", subject="u", kind="human")
    for stamp in (
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 6, 1, tzinfo=timezone.utc),
    ):
        asyncio.run(
            sink.emit(
                AuditEvent(
                    event_id=f"e-{stamp.month}",
                    run_id="r",
                    trace_id="t",
                    tenant="local",
                    principal=principal,
                    agent_ref=AgentRef(id="a", version="1", digest="sha256:x"),
                    action="test.event",
                    target="t",
                    status="ok",
                    timestamp=stamp,
                )
            )
        )
    app = build_console_app(_agents(), auth_token="secret", roles=["admin"], audit_sink=sink)
    with TestClient(app) as client:
        body = client.get("/api/security", headers=AUTH).json()

    assert body["audit"]["backend"] == "memory"
    assert body["audit"]["last_event_at"].startswith("2026-06-01")


class _FailingAuditQuery:
    async def events(self, **_kwargs):
        raise RuntimeError("audit backend down")


class _UnsafeCredentials:
    async def list(self, _tenant):
        raise ValueError("unsafe tenant path")


def test_security_reports_audit_unavailable(tmp_path):
    app = build_console_app(
        _agents(),
        auth_token="secret",
        roles=["admin"],
        audit_query=_FailingAuditQuery(),
    )
    with TestClient(app) as client:
        response = client.get("/api/security", headers=AUTH)

    assert response.status_code == 200
    audit = response.json()["audit"]
    assert audit["records"] is None
    assert audit["last_event_at"] is None
    assert audit["error"] == "audit_unavailable"


def test_security_ignores_an_off_schema_report(tmp_path):
    report = tmp_path / "scan.json"
    report.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
    with _client(tmp_path, security_report=str(report)) as client:
        body = client.get("/api/security", headers=AUTH).json()

    assert body["scans"] is None


def test_security_survives_an_unsafe_credential_tenant(tmp_path, monkeypatch):
    monkeypatch.delenv("ADK_SECRET_KEKS", raising=False)
    with _client(tmp_path, credentials=_UnsafeCredentials()) as client:
        response = client.get("/api/security", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["keys"]["credentials"]["error"] == "credential_store_unavailable"


def test_security_treats_a_deeply_nested_report_as_missing(tmp_path):
    report = tmp_path / "scan.json"
    report.write_text("[" * 200000 + "]" * 200000, encoding="utf-8")
    with _client(tmp_path, security_report=str(report)) as client:
        response = client.get("/api/security", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["scans"] is None


def test_security_ignores_a_report_with_wrong_notes_type(tmp_path):
    report = tmp_path / "scan.json"
    report.write_text(
        json.dumps(
            {
                "generated_at": "2026-11-24T10:00:00Z",
                "codeql": {},
                "dependencies": {},
                "notes": 123,
            }
        ),
        encoding="utf-8",
    )
    with _client(tmp_path, security_report=str(report)) as client:
        body = client.get("/api/security", headers=AUTH).json()

    assert body["scans"] is None


def test_security_keeps_audit_unavailable_after_verify(tmp_path):
    app = build_console_app(
        _agents(),
        auth_token="secret",
        roles=["admin"],
        audit_query=_FailingAuditQuery(),
    )
    with TestClient(app) as client:
        response = client.get("/api/security?verify=1", headers=AUTH)

    assert response.status_code == 200
    audit = response.json()["audit"]
    assert audit["error"] == "audit_unavailable"
    assert audit["records"] is None


def test_security_drops_unknown_scan_counters(tmp_path):
    nested = '{"a":' * 200 + "{}" + "}" * 200
    report = tmp_path / "scan.json"
    report.write_text(
        '{"generated_at": "2026-11-24T10:00:00Z", "codeql": '
        + nested
        + ', "dependencies": {"vulnerabilities": 1, "nested": '
        + nested
        + "}}",
        encoding="utf-8",
    )
    with _client(tmp_path, security_report=str(report)) as client:
        response = client.get("/api/security", headers=AUTH)

    assert response.status_code == 200
    scans = response.json()["scans"]
    assert scans["codeql"] == {}
    assert scans["dependencies"] == {"vulnerabilities": 1}
