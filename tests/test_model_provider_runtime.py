"""SLICE-298: provider records drive model configuration at runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime, timezone

import pytest

from adk_agent import cli
from adk_agent.core import ModelProviderRecord
from adk_agent.model_provider_runtime import FileProviderLookup
from adk_agent.models import (
    ProviderCredentials,
    clear_provider_lookup,
    resolve_model_config,
    set_provider_lookup,
)
from adk_agent.registry.model_provider_keys import FileModelProviderKeyStore
from adk_agent.registry.model_providers import FileModelProviderStore
from adk_agent.secretstore.keys import LocalKeyBackend

KEY = "sk-test-1234abcd"  # pragma: allowlist secret


class _Sink:
    def __init__(self) -> None:
        self.events: list = []

    async def emit(self, event) -> None:
        self.events.append(event)


@pytest.fixture(autouse=True)
def _reset_lookup() -> Iterator[None]:
    yield
    clear_provider_lookup()


def _record(**overrides) -> ModelProviderRecord:
    payload = {
        "provider_id": "deepseek-prod",
        "kind": "litellm",
        "model": "litellm:deepseek/deepseek-v4-pro",
        "updated_at": datetime(2026, 11, 26, tzinfo=timezone.utc),
        "updated_by": "root",
    }
    payload.update(overrides)
    return ModelProviderRecord(**payload)


def _backend(marker: bytes = b"a") -> LocalKeyBackend:
    return LocalKeyBackend({"k1": marker * 32}, "k1")


def _seed(tmp_path, record: ModelProviderRecord) -> None:
    asyncio.run(FileModelProviderStore(tmp_path).put(record))


def test_resolve_model_config_uses_record():
    calls: list[tuple[str, str]] = []

    def lookup(kind: str, name: str):
        calls.append((kind, name))
        return ProviderCredentials(api_key=KEY, api_base="https://api.example.com")

    set_provider_lookup(lookup)
    cfg = resolve_model_config("litellm:deepseek/deepseek-v4-pro")

    assert calls == [("litellm", "deepseek/deepseek-v4-pro")]
    assert cfg.api_key == KEY
    assert cfg.api_base == "https://api.example.com"


def test_provider_lookup_normalizes_prefix(tmp_path):
    _seed(tmp_path, _record())
    lookup = FileProviderLookup(str(tmp_path))

    found = lookup.lookup("litellm", "deepseek/deepseek-v4-pro")

    assert found is not None
    assert found.api_base is None


def test_provider_lookup_ignores_disabled_and_other_kind(tmp_path):
    _seed(tmp_path, _record(provider_id="off", enabled=False))
    _seed(
        tmp_path,
        _record(provider_id="claude-1", kind="claude", model="claude:claude-sonnet-5-5"),
    )
    lookup = FileProviderLookup(str(tmp_path))

    assert lookup.lookup("litellm", "deepseek/deepseek-v4-pro") is None
    assert lookup.lookup("claude", "claude-sonnet-5-5") is not None


def test_provider_lookup_uses_stored_key(tmp_path):
    _seed(tmp_path, _record(base_url="https://api.example.com"))
    backend = _backend()
    from adk_agent.secretstore.model_keys import model_key_aad

    asyncio.run(
        FileModelProviderKeyStore(tmp_path).put(
            "deepseek-prod",
            backend.wrap(KEY.encode("utf-8"), model_key_aad("deepseek-prod")),
            key_id="k1",
            hint="sk-…abcd",
        )
    )
    lookup = FileProviderLookup(str(tmp_path), backend=backend)

    found = lookup.lookup("litellm", "deepseek/deepseek-v4-pro")

    assert found is not None
    assert found.api_key == KEY
    assert found.api_base == "https://api.example.com"


def test_provider_lookup_falls_back_to_env_ref(tmp_path, monkeypatch):
    monkeypatch.setenv("ADK_SECRET_LOCAL_DEEPSEEK", KEY)
    _seed(tmp_path, _record(secret_ref="secret://local/deepseek"))  # pragma: allowlist secret
    lookup = FileProviderLookup(str(tmp_path), backend=None)

    found = lookup.lookup("litellm", "deepseek/deepseek-v4-pro")

    assert found is not None
    assert found.api_key == KEY


def test_provider_lookup_audits_decrypt_failure(tmp_path):
    _seed(tmp_path, _record())
    backend = _backend()
    from adk_agent.secretstore.model_keys import model_key_aad

    asyncio.run(
        FileModelProviderKeyStore(tmp_path).put(
            "deepseek-prod",
            backend.wrap(KEY.encode("utf-8"), model_key_aad("deepseek-prod")),
            key_id="k1",
            hint="sk-…abcd",
        )
    )
    sink = _Sink()
    lookup = FileProviderLookup(str(tmp_path), backend=_backend(b"b"), audit=sink)

    async def _run():
        found = lookup.lookup("litellm", "deepseek/deepseek-v4-pro")
        await asyncio.sleep(0)
        return found

    found = asyncio.run(_run())

    assert found is not None
    assert found.api_key is None
    assert any(event.action == "model.key_failed" for event in sink.events)
    assert all("sk-test" not in event.model_dump_json() for event in sink.events)


def test_resolve_model_config_without_records():
    cfg = resolve_model_config("litellm:deepseek/deepseek-v4-pro")

    assert cfg.api_key is None
    assert cfg.api_base is None
    assert cfg.name == "deepseek/deepseek-v4-pro"


def test_model_provider_flags_on_commands(capsys):
    for command in ("console", "serve", "serve-many", "serve-a2a", "serve-triggers"):
        with pytest.raises(SystemExit) as excinfo:
            cli.main([command, "--help"])
        assert excinfo.value.code == 0
        output = capsys.readouterr().out
        assert "--model-providers-dir" in output, command
