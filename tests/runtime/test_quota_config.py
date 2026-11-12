"""SLICE-044: QuotaConfig selects which tenants are limited."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from adk_agent.core import QuotaConfig, QuotaPolicy


def test_empty_tenant_rejected():
    with pytest.raises(ValidationError):
        QuotaConfig(tenants={"": QuotaPolicy(max_runs=1)})


def test_unlisted_tenant_is_unlimited():
    config = QuotaConfig(tenants={"acme": QuotaPolicy(max_runs=5)})

    assert config.tenants.get("acme") == QuotaPolicy(max_runs=5)
    assert config.tenants.get("other") is None


def test_config_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        QuotaConfig.model_validate({"tenants": {"acme": {"max_runs": 1}}, "extra": True})


def test_policy_needs_a_limit():
    with pytest.raises(ValidationError):
        QuotaConfig.model_validate({"tenants": {"acme": {}}})
