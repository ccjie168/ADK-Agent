"""SLICE-085: connector specs and their egress-facing validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from adk_agent.core import ConnectorSpec

BASE = {
    "connector_id": "crm",
    "kind": "http",
    "base_url": "https://crm.example.com",
    "auth_ref": "secret://crm/token",
    "methods": ["GET"],
    "path_prefixes": ["/v1/"],
    "data_classes": ["internal"],
}


def test_valid_spec():
    spec = ConnectorSpec(**BASE)
    assert spec.enabled is True
    assert spec.timeout_seconds == 10
    assert spec.max_response_bytes == 1024 * 1024


def test_http_only_loopback():
    assert ConnectorSpec(**{**BASE, "base_url": "http://127.0.0.1:8080"}).base_url
    with pytest.raises(ValidationError):
        ConnectorSpec(**{**BASE, "base_url": "http://crm.example.com"})


def test_secret_reference():
    assert ConnectorSpec(**{**BASE, "auth_ref": None}).auth_ref is None
    for value in ("token", "env://TOKEN", "secret://", "secret://a b"):
        with pytest.raises(ValidationError):
            ConnectorSpec(**{**BASE, "auth_ref": value})


def test_limits():
    with pytest.raises(ValidationError):
        ConnectorSpec(**{**BASE, "timeout_seconds": 0})
    with pytest.raises(ValidationError):
        ConnectorSpec(**{**BASE, "timeout_seconds": 61})
    with pytest.raises(ValidationError):
        ConnectorSpec(**{**BASE, "max_response_bytes": 0})
    with pytest.raises(ValidationError):
        ConnectorSpec(**{**BASE, "methods": []})


def test_path_prefixes():
    for value in ("v1/", "/v1/../etc", "/v1/../../"):
        with pytest.raises(ValidationError):
            ConnectorSpec(**{**BASE, "path_prefixes": [value]})


def test_unsupported_kind():
    with pytest.raises(ValidationError):
        ConnectorSpec(**{**BASE, "kind": "grpc"})
