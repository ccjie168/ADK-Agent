"""SLICE-022: sandbox policy defaults, validation, and egress checks."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from adk_agent.sandbox import SandboxPolicy, SandboxViolation, check_url


def test_policy_defaults():
    policy = SandboxPolicy()
    assert policy.timeout_seconds == 10.0
    assert policy.allow_network is False
    assert policy.allowed_hosts is None
    assert policy.env_allowlist == []
    assert policy.max_cpu_seconds is None
    assert policy.max_memory_mb is None


def test_policy_rejects_bad_timeout():
    with pytest.raises(ValidationError):
        SandboxPolicy(timeout_seconds=0)
    with pytest.raises(ValidationError):
        SandboxPolicy(timeout_seconds=-1)


def test_policy_normalizes_hosts():
    policy = SandboxPolicy(allowed_hosts=["API.Example.com"])
    assert policy.allowed_hosts == ["api.example.com"]


def test_policy_rejects_bad_host():
    with pytest.raises(ValidationError):
        SandboxPolicy(allowed_hosts=["https://api.example.com"])
    with pytest.raises(ValidationError):
        SandboxPolicy(allowed_hosts=["api.example.com/path"])


def test_policy_rejects_bad_env_name():
    with pytest.raises(ValidationError):
        SandboxPolicy(env_allowlist=["BAD NAME"])


def test_check_url_none_allows_any():
    check_url("https://anything.example.com/x", SandboxPolicy())


def test_check_url_empty_denies_all():
    with pytest.raises(SandboxViolation):
        check_url("https://api.example.com/x", SandboxPolicy(allowed_hosts=[]))


def test_check_url_list_allows_only_listed():
    policy = SandboxPolicy(allowed_hosts=["api.example.com"])
    check_url("https://api.example.com/x", policy)
    with pytest.raises(SandboxViolation):
        check_url("https://evil.example.com/x", policy)


def test_check_url_rejects_hostless_url():
    with pytest.raises(SandboxViolation):
        check_url("file:///etc/passwd", SandboxPolicy(allowed_hosts=["api.example.com"]))
