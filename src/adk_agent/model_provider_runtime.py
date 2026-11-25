"""Glue between provider records, encrypted keys and model construction.

``models`` must stay free of registry imports (the registry already imports
``models``), so this adapter builds the synchronous lookup and hands it to
``models.set_provider_lookup``.
"""

from __future__ import annotations

import logging
from typing import Any

from .models import ProviderCredentials
from .registry.model_provider_keys import FileModelProviderKeyStore
from .registry.model_providers import FileModelProviderStore
from .secretstore import KeyBackendError, PrefixedEnvSecretProvider, load_key_backend
from .secretstore.model_keys import ModelKeyResolver, ModelKeyUnavailable

logger = logging.getLogger(__name__)

_UNSET = object()


def model_name(model: str, kind: str) -> str:
    """Drop a leading ``kind:`` prefix so records match a bare model name."""
    prefix = f"{kind}:"
    return model[len(prefix) :] if model.startswith(prefix) else model


class FileProviderLookup:
    """Resolve ``(kind, model name)`` to credentials from the provider store."""

    def __init__(self, directory: str, *, backend: Any = _UNSET, audit: Any = None) -> None:
        self.records = FileModelProviderStore(directory)
        self.keys = FileModelProviderKeyStore(directory)
        if backend is _UNSET:
            try:
                backend = load_key_backend()
            except KeyBackendError as exc:
                logger.warning("model key backend unavailable: %s", type(exc).__name__)
                backend = None
        self.backend = backend
        self.resolver = ModelKeyResolver(store=self.keys, backend=backend, audit=audit)
        self.env = PrefixedEnvSecretProvider()

    def _key(self, record: Any) -> str | None:
        if self.backend is not None:
            try:
                if self.keys.get_sync(record.provider_id) is not None:
                    return self.resolver.resolve_sync(record.provider_id)
            except (OSError, ValueError):
                logger.warning("model key record unreadable: provider=%s", record.provider_id)
            except ModelKeyUnavailable:
                return None
        if record.secret_ref:
            try:
                return self.env.resolve_sync(record.secret_ref)
            except Exception:  # noqa: BLE001 - missing or invalid env ref falls back
                return None
        return None

    def lookup(self, kind: str, name: str) -> ProviderCredentials | None:
        try:
            records = self.records.list_sync()
        except (OSError, ValueError):
            logger.warning("model provider records unreadable; using environment defaults")
            return None
        for record in records:
            if not record.enabled or record.kind != kind:
                continue
            if model_name(record.model, kind) != name:
                continue
            return ProviderCredentials(api_key=self._key(record), api_base=record.base_url)
        return None


__all__ = ["FileProviderLookup", "model_name"]
