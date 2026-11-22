"""SLICE-218: terminology storage (ADR-0038 MVP item 2)."""

from __future__ import annotations

import asyncio
import importlib.util
import os

import pytest

from adk_agent.registry.terminology import FileConceptSchemeStore
from adk_agent.semantics import Concept, ConceptScheme, Term

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")


def _scheme(scheme_id: str) -> ConceptScheme:
    return ConceptScheme(
        scheme_id=scheme_id,
        concepts=[
            Concept(concept_id="customer", pref_labels=[Term(value="Customer", language="en")]),
            Concept(concept_id="client", pref_labels=[Term(value="Client", language="en")]),
        ],
    )


def test_file_store_put_get_roundtrip(tmp_path):
    store = FileConceptSchemeStore(tmp_path)
    scheme = _scheme("products")

    asyncio.run(store.put("acme", scheme))

    assert asyncio.run(store.get("acme", "products")) == scheme


def test_file_store_upsert_replaces_same_scheme(tmp_path):
    store = FileConceptSchemeStore(tmp_path)
    replacement = ConceptScheme(
        scheme_id="products",
        concepts=[Concept(concept_id="order", pref_labels=[Term(value="Order", language="en")])],
    )

    asyncio.run(store.put("acme", _scheme("products")))
    asyncio.run(store.put("acme", replacement))

    assert asyncio.run(store.get("acme", "products")) == replacement


def test_file_store_isolates_tenants(tmp_path):
    store = FileConceptSchemeStore(tmp_path)

    asyncio.run(store.put("acme", _scheme("products")))

    assert asyncio.run(store.get("globex", "products")) is None


def test_store_missing_scheme_returns_none(tmp_path):
    store = FileConceptSchemeStore(tmp_path)

    assert asyncio.run(store.get("acme", "missing")) is None


def test_file_store_lists_tenant_schemes(tmp_path):
    store = FileConceptSchemeStore(tmp_path)
    asyncio.run(store.put("acme", _scheme("products")))
    asyncio.run(store.put("acme", _scheme("customers")))
    asyncio.run(store.put("globex", _scheme("orders")))

    assert [s.scheme_id for s in asyncio.run(store.list("acme"))] == ["customers", "products"]


@_live
@_needs_driver
def test_postgres_store_roundtrip():
    from adk_agent.registry.terminology_postgres import PostgresConceptSchemeStore

    async def run():
        store = PostgresConceptSchemeStore(_LIVE_URL)
        try:
            await store.put("acme", _scheme("products"))
            return await store.get("acme", "products")
        finally:
            await store.aclose()

    assert asyncio.run(run()) == _scheme("products")
