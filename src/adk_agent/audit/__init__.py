"""Audit sinks."""

from __future__ import annotations

from .http_sink import AuditSinkUnavailable, HttpAuditSink
from .jsonl import JsonlAuditSink
from .keyring import KeyringError, SigningKeyring
from .memory import ListAuditSink
from .pipeline import (
    AuditChainBroken,
    AuditPipeline,
    AuditSignatureInvalid,
    load_records,
    record_signature,
    verify_audit_file,
)

__all__ = [
    "AuditChainBroken",
    "AuditPipeline",
    "AuditSignatureInvalid",
    "AuditSinkUnavailable",
    "HttpAuditSink",
    "JsonlAuditSink",
    "KeyringError",
    "ListAuditSink",
    "SigningKeyring",
    "load_records",
    "record_signature",
    "verify_audit_file",
]
