"""SLICE-166: --trust-caller-policy is loopback-only."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from adk_agent.cli import _trust_caller_policy


def test_trust_caller_policy_requires_loopback():
    with pytest.raises(SystemExit):
        _trust_caller_policy(SimpleNamespace(host="0.0.0.0", trust_caller_policy=True))


def test_trust_caller_policy_loopback_ok():
    args = SimpleNamespace(host="127.0.0.1", trust_caller_policy=True)
    assert _trust_caller_policy(args) is True


def test_trust_caller_policy_off_by_default():
    args = SimpleNamespace(host="0.0.0.0", trust_caller_policy=False)
    assert _trust_caller_policy(args) is False


def test_trust_caller_policy_rejects_registry():
    args = SimpleNamespace(
        host="127.0.0.1", trust_caller_policy=True, registry="/tmp/reg", registry_url=None
    )
    with pytest.raises(SystemExit):
        _trust_caller_policy(args)
