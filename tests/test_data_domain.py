"""SLICE-219: data domain dimension (ADR-0038 MVP item 3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from adk_agent.semantics import DataDomain


def test_data_domain_defaults_to_internal():
    domain = DataDomain(concept_id="order")

    assert domain.sensitivity == "internal"


def test_data_domain_rejects_unknown_sensitivity():
    with pytest.raises(ValidationError):
        DataDomain(concept_id="order", sensitivity="top-secret")


def test_data_domain_accepts_tenant_concept():
    domain = DataDomain(concept_id="warehouse_region_east")

    assert domain.concept_id == "warehouse_region_east"


def test_data_domain_orthogonal_axes():
    same_domain = [
        DataDomain(concept_id="order", sensitivity=s) for s in ("public", "confidential")
    ]
    same_sensitivity = [
        DataDomain(concept_id=c, sensitivity="internal") for c in ("order", "customer")
    ]

    assert [d.sensitivity for d in same_domain] == ["public", "confidential"]
    assert [d.concept_id for d in same_sensitivity] == ["order", "customer"]
