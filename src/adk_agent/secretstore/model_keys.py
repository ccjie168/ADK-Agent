"""Decrypt model provider keys and audit failures without leaking values.

Wrapping happens in the console write path; this module is the one place a
model key is unwrapped, so every failure is audited with an error code only.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..audit.hashing import hash_text
from ..core import AgentRef, AuditEvent, AuditSink, Principal
from ..core.context import current_invocation

logger = logging.getLogger(__name__)


class ModelKeyUnavailable(Exception):
    """The stored model key cannot be read or decrypted."""


def model_key_aad(provider_id: str) -> bytes:
    return f"adk-model-provider:{provider_id}".encode()


class ModelKeyResolver:
    """Unwrap one provider key, auditing failures without the value."""

    def __init__(self, *, store: Any, backend: Any, audit: AuditSink | None = None) -> None:
        self._store = store
        self._backend = backend
        self._audit = audit

    async def _audit_failure(self, provider_id: str, error_code: str) -> None:
        if self._audit is None:
            return
        try:
            invocation = current_invocation()
            principal = (
                invocation.principal
                if invocation is not None
                else Principal(tenant="local", subject="model_key_resolver", kind="service")
            )
            await self._audit.emit(
                AuditEvent(
                    event_id=uuid.uuid4().hex,
                    run_id=invocation.run_id if invocation is not None else uuid.uuid4().hex,
                    trace_id=invocation.trace_id if invocation is not None else uuid.uuid4().hex,
                    tenant=principal.tenant,
                    principal=principal,
                    agent_ref=AgentRef(
                        id=provider_id,
                        version="model-key",
                        digest="sha256:" + hash_text(error_code),
                    ),
                    action="model.key_failed",
                    target=provider_id,
                    status="error",
                    error_code=error_code,
                    timestamp=datetime.now(timezone.utc),
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("model key audit failed: %s", type(exc).__name__)

    async def resolve(self, provider_id: str) -> str:
        try:
            record = await self._store.get(provider_id)
        except (OSError, ValueError) as exc:
            await self._audit_failure(provider_id, "key_unreadable")
            raise ModelKeyUnavailable(f"model key for {provider_id!r} is unreadable") from exc
        if record is None:
            await self._audit_failure(provider_id, "key_missing")
            raise ModelKeyUnavailable(f"no model key for {provider_id!r}")
        if self._backend is None:
            await self._audit_failure(provider_id, "key_backend_unavailable")
            raise ModelKeyUnavailable(f"no key backend for {provider_id!r}")
        try:
            raw = self._backend.unwrap(record["wrapped_secret"], model_key_aad(provider_id))
            value = raw.decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            await self._audit_failure(provider_id, "decrypt_failed")
            raise ModelKeyUnavailable(f"model key for {provider_id!r} is unreadable") from exc
        if not value or "\r" in value or "\n" in value:
            await self._audit_failure(provider_id, "invalid_secret")
            raise ModelKeyUnavailable(f"model key for {provider_id!r} is invalid")
        return value


__all__ = ["ModelKeyResolver", "ModelKeyUnavailable", "model_key_aad"]
