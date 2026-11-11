"""SLICE-021: secret providers resolve references and reject unsafe values."""

from __future__ import annotations

import asyncio

import pytest

from adk_agent.secretstore import (
    EnvSecretProvider,
    MappingSecretProvider,
    SecretNotFound,
    secret_header_provider,
)


def test_env_provider_resolves(monkeypatch):
    monkeypatch.setenv("DEMO_TOKEN", "s3cret")
    assert asyncio.run(EnvSecretProvider().resolve("DEMO_TOKEN")) == "s3cret"


def test_env_provider_missing(monkeypatch):
    monkeypatch.delenv("DEMO_TOKEN", raising=False)
    with pytest.raises(SecretNotFound) as raised:
        asyncio.run(EnvSecretProvider().resolve("DEMO_TOKEN"))
    assert "DEMO_TOKEN" in str(raised.value)
    assert "s3cret" not in str(raised.value)


def test_env_provider_rejects_invalid_reference():
    with pytest.raises(SecretNotFound):
        asyncio.run(EnvSecretProvider().resolve("../etc/passwd"))


def test_env_provider_rejects_newline(monkeypatch):
    monkeypatch.setenv("DEMO_TOKEN", "abc\r\nX-Evil: 1")
    with pytest.raises(SecretNotFound):
        asyncio.run(EnvSecretProvider().resolve("DEMO_TOKEN"))


def test_mapping_provider():
    provider = MappingSecretProvider({"DEMO_TOKEN": "value"})
    assert asyncio.run(provider.resolve("DEMO_TOKEN")) == "value"
    with pytest.raises(SecretNotFound):
        asyncio.run(provider.resolve("MISSING"))


def test_mapping_provider_rejects_empty():
    provider = MappingSecretProvider({"DEMO_TOKEN": ""})
    with pytest.raises(SecretNotFound):
        asyncio.run(provider.resolve("DEMO_TOKEN"))


def test_secret_header_provider():
    provider = secret_header_provider(
        MappingSecretProvider({"DEMO_TOKEN": "value"}),
        {"Authorization": "DEMO_TOKEN"},
    )
    assert asyncio.run(provider(None)) == {"Authorization": "value"}


def test_secret_header_provider_rejects_bad_name():
    with pytest.raises(ValueError):
        secret_header_provider(MappingSecretProvider({}), {"Bad Header": "DEMO_TOKEN"})
