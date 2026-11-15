"""SLICE-117: console capability manifest for the current principal."""

from __future__ import annotations

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app

ALL = {
    "chat.run",
    "runs.read",
    "sessions.read",
    "approvals.read",
    "approvals.decide",
    "grants.read",
    "grants.request",
    "grants.decide",
    "audit.read",
    "registry.read",
    "registry.publish",
    "registry.load",
    "eval.read",
    "tools.read",
    "lifecycle.read",
    "connectors.read",
    "connectors.manage",
    "peers.read",
    "peers.manage",
    "policy.read",
    "policy.write",
    "ops.status",
}

BASE = {"chat.run", "runs.read", "sessions.read"}

OPERATOR = BASE | {
    "approvals.read",
    "approvals.decide",
    "grants.read",
    "grants.decide",
    "audit.read",
    "connectors.read",
    "peers.read",
    "registry.read",
    "policy.read",
}

PUBLISHER = BASE | {
    "registry.read",
    "registry.publish",
    "registry.load",
    "eval.read",
    "tools.read",
    "lifecycle.read",
    "grants.read",
    "grants.request",
}


def _agents() -> dict[str, LlmAgent]:
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def _me(roles: list[str]) -> dict:
    app = build_console_app(_agents(), auth_token="secret", roles=roles)
    with TestClient(app) as client:
        response = client.get("/api/me", headers={"Authorization": "Bearer secret"})
    assert response.status_code == 200
    return response.json()


def test_admin_gets_every_capability():
    assert set(_me(["admin"])["capabilities"]) == ALL


def test_operator_capabilities():
    capabilities = set(_me(["operator"])["capabilities"])
    assert capabilities == OPERATOR
    assert capabilities.isdisjoint(ALL - OPERATOR)


def test_publisher_capabilities():
    capabilities = set(_me(["publisher"])["capabilities"])
    assert capabilities == PUBLISHER
    assert capabilities.isdisjoint(ALL - PUBLISHER)


def test_viewer_gets_base_capabilities():
    assert set(_me(["viewer"])["capabilities"]) == BASE


def test_unknown_role_falls_back_to_base():
    assert set(_me(["wizard"])["capabilities"]) == BASE


def test_multiple_roles_union():
    assert set(_me(["viewer", "publisher"])["capabilities"]) == PUBLISHER


def test_requires_token():
    app = build_console_app(_agents(), auth_token="secret", roles=["admin"])
    with TestClient(app) as client:
        response = client.get("/api/me")
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_reports_identity():
    body = _me(["operator"])
    assert body["tenant"] == "local"
    assert body["subject"] == "console_user"
    assert body["roles"] == ["operator"]
