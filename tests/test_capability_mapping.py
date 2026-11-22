"""SLICE-220: capability mapping (ADR-0038 MVP item 4)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from adk_agent.semantics import CapabilityBinding, validate_capability_bindings


def test_capability_binding_validates():
    binding = CapabilityBinding(
        capability_id="order.lookup", concept_id="order", tool_id="lookup_order"
    )

    validate_capability_bindings([binding], concept_ids={"order"}, tool_ids={"lookup_order"})


def test_capability_binding_rejects_bad_capability_id():
    with pytest.raises(ValidationError):
        CapabilityBinding(capability_id="Order.Lookup", concept_id="order", tool_id="lookup_order")


def test_duplicate_capability_id_rejected():
    binding = CapabilityBinding(
        capability_id="order.lookup", concept_id="order", tool_id="lookup_order"
    )

    with pytest.raises(ValueError):
        validate_capability_bindings(
            [binding, binding], concept_ids={"order"}, tool_ids={"lookup_order"}
        )


def test_missing_concept_rejected():
    binding = CapabilityBinding(
        capability_id="order.lookup", concept_id="missing", tool_id="lookup_order"
    )

    with pytest.raises(ValueError):
        validate_capability_bindings([binding], concept_ids={"order"}, tool_ids={"lookup_order"})


def test_missing_tool_rejected():
    binding = CapabilityBinding(capability_id="order.lookup", concept_id="order", tool_id="missing")

    with pytest.raises(ValueError):
        validate_capability_bindings([binding], concept_ids={"order"}, tool_ids={"lookup_order"})
