"""SLICE-178: ConnectorSpec.delegation field (ADR-0031 slice 1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from adk_agent.core import ConnectorSpec


def _spec(**overrides) -> ConnectorSpec:
    data = {
        "connector_id": "crm",
        "kind": "http",
        "base_url": "https://crm.example.com",
        "methods": ["GET"],
    }
    data.update(overrides)
    return ConnectorSpec(**data)


def test_connector_accepts_delegation():
    assert _spec(delegation="controlled-service").delegation == "controlled-service"


def test_connector_rejects_unknown_delegation():
    with pytest.raises(ValidationError):
        _spec(delegation="bogus")


def test_connector_delegation_defaults_service():
    assert _spec().delegation == "service"
