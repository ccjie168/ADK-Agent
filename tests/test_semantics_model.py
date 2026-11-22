"""SLICE-217: semantic layer core data model (ADR-0038)."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from adk_agent.semantics import CapabilityId, Concept, ConceptMapping, ConceptScheme, Term


def _term(value: str, language: str = "en") -> Term:
    return Term(value=value, language=language)


def _concept(concept_id: str, **overrides) -> Concept:
    data = {"concept_id": concept_id, "pref_labels": [_term(f"label {concept_id}")]}
    data.update(overrides)
    return Concept(**data)


def test_concept_rejects_duplicate_pref_label_in_language():
    with pytest.raises(ValidationError):
        Concept(
            concept_id="order",
            pref_labels=[_term("Order"), _term("Purchase Order")],
        )


def test_scheme_rejects_cycle_in_broader():
    with pytest.raises(ValidationError):
        ConceptScheme(
            scheme_id="s1",
            concepts=[
                _concept("a", broader=["b"]),
                _concept("b", broader=["a"]),
            ],
        )


def test_scheme_rejects_dangling_mapping():
    with pytest.raises(ValidationError):
        ConceptScheme(
            scheme_id="s1",
            concepts=[_concept("a")],
            mappings=[ConceptMapping(source_id="a", target_id="missing", kind="exact")],
        )


def test_scheme_rejects_conflicting_exact_match():
    with pytest.raises(ValidationError):
        ConceptScheme(
            scheme_id="s1",
            concepts=[_concept("a"), _concept("b")],
            mappings=[
                ConceptMapping(source_id="a", target_id="b", kind="exact"),
                ConceptMapping(source_id="a", target_id="b", kind="broad"),
            ],
        )
    with pytest.raises(ValidationError):
        ConceptScheme(
            scheme_id="s1",
            concepts=[_concept("a")],
            mappings=[ConceptMapping(source_id="a", target_id="a", kind="exact")],
        )


def test_capability_id_accepts_dot_namespaced():
    adapter = TypeAdapter(CapabilityId)

    assert adapter.validate_python("order.lookup") == "order.lookup"
    assert adapter.validate_python("inventory.query_stock") == "inventory.query_stock"


def test_capability_id_rejects_bad_shape():
    adapter = TypeAdapter(CapabilityId)
    for bad in ["Order.Lookup", "order.", ".lookup", "order..lookup", "1order"]:
        with pytest.raises(ValidationError):
            adapter.validate_python(bad)


def test_valid_scheme_builds():
    scheme = ConceptScheme(
        scheme_id="s1",
        concepts=[
            _concept("inventory"),
            _concept("stock", broader=["inventory"]),
            _concept("customer"),
            _concept("client"),
        ],
        mappings=[
            ConceptMapping(source_id="customer", target_id="client", kind="close"),
        ],
    )

    assert [c.concept_id for c in scheme.concepts] == ["inventory", "stock", "customer", "client"]
