"""SLICE-030: weighted canary routing between two agent versions."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from adk_agent.canary import CanaryRouter
from adk_agent.core import CanaryPolicy


def _policy(*, weight: float = 0.5, tenant: str = "t1") -> CanaryPolicy:
    return CanaryPolicy(
        tenant=tenant,
        agent_id="support-bot",
        stable_version="1.0.0",
        canary_version="1.1.0",
        weight=weight,
    )


def test_zero_weight_is_stable():
    router = CanaryRouter(rand=lambda: 0.0)
    assert router.route(_policy(weight=0), "t1") == "1.0.0"


def test_full_weight_is_canary():
    router = CanaryRouter(rand=lambda: 1.0)
    assert router.route(_policy(weight=1), "t1") == "1.1.0"


def test_weight_boundary_uses_random_source():
    low = CanaryRouter(rand=lambda: 0.49)
    high = CanaryRouter(rand=lambda: 0.5)

    assert low.route(_policy(weight=0.5), "t1") == "1.1.0"
    assert high.route(_policy(weight=0.5), "t1") == "1.0.0"


def test_same_version_with_weight_rejected():
    with pytest.raises(ValidationError):
        CanaryPolicy(
            tenant="t1",
            agent_id="support-bot",
            stable_version="1.0.0",
            canary_version="1.0.0",
            weight=0.1,
        )


def test_weight_and_names_are_validated():
    with pytest.raises(ValidationError):
        _policy(weight=1.5)
    with pytest.raises(ValidationError):
        _policy(weight=-0.1)
    with pytest.raises(ValidationError):
        CanaryPolicy(
            tenant="../evil",
            agent_id="support-bot",
            stable_version="1",
            canary_version="2",
            weight=0.1,
        )


def test_tenant_mismatch_rejected():
    router = CanaryRouter(rand=lambda: 0.0)
    with pytest.raises(ValueError):
        router.route(_policy(tenant="t1"), "t2")
