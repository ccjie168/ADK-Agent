"""SLICE-303: local mock services for the support-agent demo."""

from __future__ import annotations

import base64
import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = ROOT / "scripts" / "mock_services.py"
AUTH = {"Authorization": "Bearer mock-token"}


def _app():
    spec = importlib.util.spec_from_file_location("mock_services", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.build_mock_app(token="mock-token")


def test_mock_health_is_open_and_writes_need_token():
    with TestClient(_app()) as client:
        health = client.get("/healthz")
        denied = client.post("/itsm/tickets", json={"title": "x"})

    assert health.status_code == 200
    assert denied.status_code == 401
    assert denied.json() == {"error": "unauthorized"}


def test_mock_ticket_roundtrip():
    with TestClient(_app()) as client:
        created = client.post(
            "/itsm/tickets",
            headers=AUTH,
            json={"title": "无法登录", "description": "验证码收不到", "priority": "high"},
        )
        ticket_id = created.json()["id"]
        fetched = client.get(f"/itsm/tickets/{ticket_id}", headers=AUTH)
        missing = client.get("/itsm/tickets/nope", headers=AUTH)
        invalid = client.post("/itsm/tickets", headers=AUTH, json={"title": ""})

    assert created.status_code == 201
    assert created.json()["status"] == "open"
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "无法登录"
    assert missing.status_code == 404
    assert missing.json() == {"error": "ticket_not_found"}
    assert invalid.status_code == 400
    assert invalid.json() == {"error": "invalid_ticket"}


def test_mock_quark_limit_and_metadata():
    content = base64.b64encode(b"hello").decode("ascii")
    big = base64.b64encode(b"x" * (1024 * 1024 + 1)).decode("ascii")
    with TestClient(_app()) as client:
        created = client.post(
            "/quark/files", headers=AUTH, json={"name": "note.txt", "content_base64": content}
        )
        file_id = created.json()["file_id"]
        meta = client.get(f"/quark/files/{file_id}", headers=AUTH)
        too_big = client.post(
            "/quark/files", headers=AUTH, json={"name": "big.bin", "content_base64": big}
        )
        invalid = client.post("/quark/files", headers=AUTH, json={"name": "x" * 200})

    assert created.status_code == 201
    assert created.json()["size"] == 5
    assert meta.status_code == 200
    assert meta.json() == {"file_id": file_id, "name": "note.txt", "size": 5}
    assert too_big.status_code == 413
    assert too_big.json() == {"error": "file_too_large"}
    assert invalid.status_code == 400
    assert invalid.json() == {"error": "invalid_file"}


def test_mock_wecom_records_messages():
    with TestClient(_app()) as client:
        sent = client.post("/wecom/webhook", headers=AUTH, json={"text": "工单已创建"})
        listed = client.get("/wecom/messages", headers=AUTH)

    assert sent.status_code == 201
    assert sent.json()["sent"] is True
    assert listed.status_code == 200
    assert [item["text"] for item in listed.json()] == ["工单已创建"]


def test_support_demo_doc_matches_script():
    text = _SCRIPT.read_text(encoding="utf-8")
    doc = (ROOT / "docs" / "demo" / "support-agent.md").read_text(encoding="utf-8")

    assert "--port" in text
    assert "--print-token" in text
    for token in ("MOCK_TOKEN", "mock-token", "8055", "/itsm/tickets", "/quark/files"):
        assert token in doc
