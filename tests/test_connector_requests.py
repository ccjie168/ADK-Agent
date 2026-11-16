"""SLICE-122: connector request model and the file store state machine."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from adk_agent.core import (
    ConnectorRequest,
    ConnectorRequestConflict,
    ConnectorRequestNotFound,
    ConnectorSpec,
)
from adk_agent.registry import FileConnectorRequestStore

_NOW = datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc)


def _spec(tenant: str = "acme", **overrides) -> ConnectorSpec:
    data = {
        "connector_id": "crm",
        "tenant": tenant,
        "kind": "http",
        "base_url": "https://crm.example.com",
        "auth_ref": f"secret://{tenant}/token",
        "methods": ["GET"],
        "path_prefixes": ["/v1/crm/"],
        "data_classes": ["internal"],
    }
    data.update(overrides)
    return ConnectorSpec.model_validate(data)


def _request(**overrides) -> ConnectorRequest:
    data = {
        "request_id": "req-1",
        "tenant": "acme",
        "spec": _spec(),
        "reason": "Need CRM read access",
        "requested_by": "alice",
        "requested_at": _NOW,
    }
    data.update(overrides)
    return ConnectorRequest(**data)


def test_request_rejects_foreign_tenant_spec():
    with pytest.raises(ValidationError):
        _request(tenant="acme", spec=_spec(tenant="other"))


def test_pending_request_rejects_decision_fields():
    with pytest.raises(ValidationError):
        _request(decided_by="admin")
    with pytest.raises(ValidationError):
        _request(decided_at=_NOW)
    with pytest.raises(ValidationError):
        _request(registered_connector="crm")


def test_approved_requires_registered_connector():
    with pytest.raises(ValidationError):
        _request(status="approved", decided_by="admin", decided_at=_NOW)


def test_denied_rejects_registered_connector():
    with pytest.raises(ValidationError):
        _request(
            status="denied",
            decided_by="admin",
            decided_at=_NOW,
            registered_connector="crm",
        )


def test_file_store_roundtrip_and_decisions(tmp_path):
    store = FileConnectorRequestStore(tmp_path / "requests")
    first = _request(request_id="req-1")
    second = _request(request_id="req-2", reason="second")
    foreign = _request(request_id="req-3", tenant="other", spec=_spec(tenant="other"))

    async def flow() -> None:
        assert await store.add(first) == first
        assert await store.add(first) == first
        assert await store.get("req-1") == first
        assert await store.get("missing") is None

        await store.add(second)
        await store.add(foreign)
        listed = await store.list("acme")
        assert [record.request_id for record in listed] == ["req-1", "req-2"]

        approved = await store.decide(
            "req-1",
            approved=True,
            decided_by="admin",
            reason="ok",
            registered_connector="crm",
        )
        assert approved.status == "approved"
        assert approved.registered_connector == "crm"
        denied = await store.decide("req-2", approved=False, decided_by="admin", reason="no")
        assert denied.status == "denied"
        assert denied.registered_connector is None

        assert [record.request_id for record in await store.list("acme", status="approved")] == [
            "req-1"
        ]
        assert [record.request_id for record in await store.list("acme", status="denied")] == [
            "req-2"
        ]

        with pytest.raises(ConnectorRequestConflict):
            await store.decide("req-1", approved=False, decided_by="admin", reason="again")
        with pytest.raises(ConnectorRequestConflict):
            await store.add(_request(request_id="req-1", reason="different"))
        with pytest.raises(ConnectorRequestNotFound):
            await store.decide(
                "missing", approved=True, decided_by="admin", reason="x", registered_connector="crm"
            )

    asyncio.run(flow())
