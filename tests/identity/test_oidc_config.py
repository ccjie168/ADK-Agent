from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from adk_agent.identity import OidcConfig

JWKS_URL = "https://issuer.example.test/jwks"


def _config(**overrides: Any) -> OidcConfig:
    data: dict[str, Any] = {
        "issuer": "https://issuer.example.test",
        "audience": "adk-agent",
        "jwks_url": JWKS_URL,
    }
    data.update(overrides)
    return OidcConfig(**data)


def test_config_rejects_symmetric_and_none() -> None:
    with pytest.raises(ValidationError):
        _config(algorithms=("HS256",))
    with pytest.raises(ValidationError):
        _config(algorithms=("none",))


def test_config_rejects_empty_algorithms() -> None:
    with pytest.raises(ValidationError):
        _config(algorithms=())


def test_config_requires_tls_outside_loopback() -> None:
    with pytest.raises(ValidationError):
        _config(jwks_url="http://issuer.example.test/jwks")


def test_config_allows_loopback_http() -> None:
    for host in ("127.0.0.1", "localhost", "[::1]"):
        config = _config(jwks_url=f"http://{host}:8080/jwks")
        assert config.jwks_url == f"http://{host}:8080/jwks"
