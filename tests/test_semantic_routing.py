"""SLICE-221: deterministic semantic routing (ADR-0038 MVP item 5)."""

from __future__ import annotations

from adk_agent.semantics import (
    CapabilityBinding,
    Concept,
    ConceptScheme,
    RoutedCapability,
    Term,
    route_request,
)


def _scheme() -> ConceptScheme:
    return ConceptScheme(
        scheme_id="products",
        concepts=[
            Concept(
                concept_id="order",
                pref_labels=[Term(value="Order", language="en")],
                alt_labels=[Term(value="Purchase", language="en")],
            ),
            Concept(
                concept_id="customer",
                pref_labels=[Term(value="Customer", language="en")],
                hidden_labels=[Term(value="buyer", language="en")],
            ),
        ],
    )


def _bindings() -> list[CapabilityBinding]:
    return [
        CapabilityBinding(capability_id="order.lookup", concept_id="order", tool_id="lookup_order"),
        CapabilityBinding(
            capability_id="customer.profile", concept_id="customer", tool_id="get_profile"
        ),
    ]


def test_route_matches_concept_label():
    routed = route_request("show me the Order status", _scheme(), _bindings())

    assert [r.capability_id for r in routed] == ["order.lookup"]


def test_route_returns_empty_when_no_match():
    routed = route_request("what is the weather", _scheme(), _bindings())

    assert routed == []


def test_route_matches_alt_label():
    routed = route_request("track my Purchase", _scheme(), _bindings())

    assert [r.concept_id for r in routed] == ["order"]


def test_route_reports_matched_label():
    routed = route_request("show me the Order status", _scheme(), _bindings())

    assert isinstance(routed[0], RoutedCapability)
    assert routed[0].matched_label == "Order"
    assert routed[0].tool_id == "lookup_order"
