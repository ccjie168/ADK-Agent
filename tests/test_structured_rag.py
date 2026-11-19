"""SLICE-183: structured retrieval with ACL and data_classes filtering."""

from __future__ import annotations

import asyncio

from adk_agent.core import Principal
from adk_agent.rag import InMemoryRagService, RagSource


def _principal(tenant: str = "acme", subject: str = "alice") -> Principal:
    return Principal(tenant=tenant, subject=subject, kind="human")


def _source(**overrides) -> RagSource:
    data = {
        "source_id": "po-123",
        "snippet": "SAP purchase order 123 for 500 units",
        "data_classes": ["internal"],
    }
    data.update(overrides)
    return RagSource(**data)


def _retrieve(service: InMemoryRagService, query="order", **kwargs) -> list:
    return asyncio.run(
        service.retrieve(
            query, _principal(), kwargs.get("data_classes", ["internal", "confidential"])
        )
    )


def test_retrieve_returns_acl_visible_source():
    service = InMemoryRagService([_source()])
    results = _retrieve(service)
    assert [c.source_id for c in results] == ["po-123"]


def test_retrieve_hides_unauthorized_tenant():
    service = InMemoryRagService([_source(allowed_tenants=("other",))])
    assert _retrieve(service) == []


def test_retrieve_hides_unauthorized_subject():
    service = InMemoryRagService([_source(allowed_subjects=("bob",))])
    assert _retrieve(service) == []


def test_retrieve_filters_by_data_classes():
    service = InMemoryRagService([_source(data_classes=["confidential"])])
    assert _retrieve(service, data_classes=["internal"]) == []


def test_retrieve_matches_query():
    service = InMemoryRagService([_source()])
    assert _retrieve(service, query="nomatch") == []
    assert len(_retrieve(service, query="purchase")) == 1


def test_retrieved_citations_are_acl_checked():
    service = InMemoryRagService([_source()])
    results = _retrieve(service)
    assert results and all(c.acl_checked is True for c in results)
