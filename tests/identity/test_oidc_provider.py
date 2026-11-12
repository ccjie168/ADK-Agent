from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from adk_agent.identity import (
    IdentityUnavailable,
    InvalidIdentity,
    OidcConfig,
    OidcIdentityProvider,
)

ISSUER = "https://issuer.example.test"
AUDIENCE = "adk-agent"


@pytest.fixture(scope="module")
def rsa_key() -> Any:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _config(**overrides: Any) -> OidcConfig:
    data: dict[str, Any] = {
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "jwks_url": "https://issuer.example.test/jwks",
    }
    data.update(overrides)
    return OidcConfig(**data)


def _claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    data: dict[str, Any] = {
        "sub": "user-1",
        "tenant": "acme",
        "roles": ["admin", "viewer"],
        "kind": "human",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": now + 300,
        "iat": now,
    }
    data.update(overrides)
    return data


def _token(
    key: Any, claims: dict[str, Any], *, algorithm: str = "RS256", headers: dict | None = None
) -> str:
    if headers is None:
        headers = {"kid": "k1"}
    return jwt.encode(claims, key, algorithm=algorithm, headers=headers)


def _provider(
    key: Any,
    *,
    config: OidcConfig | None = None,
    resolver: Callable[[str], Any] | None = None,
) -> OidcIdentityProvider:
    if resolver is None:
        resolver = lambda _kid: key.public_key()  # noqa: E731
    return OidcIdentityProvider(config or _config(), key_resolver=resolver)


def _resolve(provider: OidcIdentityProvider, token: str) -> Any:
    return asyncio.run(provider.resolve(token))


def test_valid_token_maps_to_principal(rsa_key: Any) -> None:
    token = _token(rsa_key, _claims())
    principal = _resolve(_provider(rsa_key), token)
    assert principal.subject == "user-1"
    assert principal.tenant == "acme"
    assert principal.roles == ["admin", "viewer"]
    assert principal.kind == "human"
    assert principal.attributes == {}


def test_missing_tenant_is_rejected(rsa_key: Any) -> None:
    claims = _claims()
    del claims["tenant"]
    with pytest.raises(InvalidIdentity):
        _resolve(_provider(rsa_key), _token(rsa_key, claims))


def test_missing_roles_defaults_to_empty(rsa_key: Any) -> None:
    claims = _claims()
    del claims["roles"]
    principal = _resolve(_provider(rsa_key), _token(rsa_key, claims))
    assert principal.roles == []


def test_kind_mapping(rsa_key: Any) -> None:
    claims = _claims()
    del claims["kind"]
    assert _resolve(_provider(rsa_key), _token(rsa_key, claims)).kind == "human"

    assert _resolve(_provider(rsa_key), _token(rsa_key, _claims(kind="service"))).kind == "service"

    with pytest.raises(InvalidIdentity):
        _resolve(_provider(rsa_key), _token(rsa_key, _claims(kind="robot")))

    with pytest.raises(InvalidIdentity):
        _resolve(_provider(rsa_key), _token(rsa_key, _claims(kind=[])))


def test_wrong_issuer_is_rejected(rsa_key: Any) -> None:
    token = _token(rsa_key, _claims(iss="https://evil.example.test"))
    with pytest.raises(InvalidIdentity):
        _resolve(_provider(rsa_key), token)


def test_wrong_audience_is_rejected(rsa_key: Any) -> None:
    token = _token(rsa_key, _claims(aud="some-other-service"))
    with pytest.raises(InvalidIdentity):
        _resolve(_provider(rsa_key), token)


def test_expired_token_is_rejected(rsa_key: Any) -> None:
    token = _token(rsa_key, _claims(exp=int(time.time()) - 600))
    with pytest.raises(InvalidIdentity):
        _resolve(_provider(rsa_key), token)


def test_missing_exp_is_rejected(rsa_key: Any) -> None:
    claims = _claims()
    del claims["exp"]
    with pytest.raises(InvalidIdentity):
        _resolve(_provider(rsa_key), _token(rsa_key, claims))


def test_missing_iat_is_rejected(rsa_key: Any) -> None:
    claims = _claims()
    del claims["iat"]
    with pytest.raises(InvalidIdentity):
        _resolve(_provider(rsa_key), _token(rsa_key, claims))


def test_default_resolver_uses_jwk_client(rsa_key: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}

    class FakeJWK:
        def __init__(self, key: Any) -> None:
            self.key = key

    class FakeClient:
        def __init__(self, url: str, **kwargs: Any) -> None:
            calls["url"] = url
            calls["kwargs"] = kwargs

        def get_signing_key(self, kid: str) -> FakeJWK:
            calls["kid"] = kid
            return FakeJWK(rsa_key.public_key())

    monkeypatch.setattr(jwt, "PyJWKClient", FakeClient)
    principal = _resolve(OidcIdentityProvider(_config()), _token(rsa_key, _claims()))

    assert principal.subject == "user-1"
    assert calls["url"] == "https://issuer.example.test/jwks"
    assert calls["kid"] == "k1"
    assert calls["kwargs"] == {"cache_keys": True, "lifespan": 300}


def test_tampered_signature_is_rejected(rsa_key: Any) -> None:
    header, payload, _signature = _token(rsa_key, _claims()).split(".")
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = _token(other_key, _claims())
    _h, _p, forged_signature = forged.split(".")
    token = f"{header}.{payload}.{forged_signature}"
    with pytest.raises(InvalidIdentity):
        _resolve(_provider(rsa_key), token)


def test_disallowed_algorithm_is_rejected(rsa_key: Any) -> None:
    def never_called(_kid: str) -> Any:
        raise AssertionError("key resolver must not run before algorithm check")

    provider = _provider(rsa_key, resolver=never_called)
    hmac_token = _token("x" * 32, _claims(), algorithm="HS256")
    unmatched_token = _token(None, _claims(), algorithm="none")

    with pytest.raises(InvalidIdentity):
        _resolve(provider, hmac_token)
    with pytest.raises(InvalidIdentity):
        _resolve(provider, unmatched_token)


def test_missing_kid_is_rejected(rsa_key: Any) -> None:
    def never_called(_kid: str) -> Any:
        raise AssertionError("key resolver must not run without a kid")

    provider = _provider(rsa_key, resolver=never_called)
    token = _token(rsa_key, _claims(), headers={})
    with pytest.raises(InvalidIdentity):
        _resolve(provider, token)


def test_key_resolution_failure_is_unavailable(rsa_key: Any) -> None:
    def broken(_kid: str) -> Any:
        raise RuntimeError("jwks endpoint unreachable")

    token = _token(rsa_key, _claims())
    with pytest.raises(IdentityUnavailable):
        _resolve(_provider(rsa_key, resolver=broken), token)
