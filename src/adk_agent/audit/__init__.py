"""Audit sinks."""

from __future__ import annotations

from .http_sink import AuditQueryUnavailable, AuditSinkUnavailable, HttpAuditQuery, HttpAuditSink
from .jsonl import JsonlAuditSink
from .keyring import KeyringError, SigningKeyring
from .memory import ListAuditSink
from .pipeline import (
    AuditChainBroken,
    AuditPipeline,
    AuditSignatureInvalid,
    load_records,
    query_events,
    record_signature,
    verify_audit_file,
)
from .postgres import (
    AuditStoreUnavailable,
    PostgresAuditQuery,
    PostgresAuditSink,
    query_audit_records,
    verify_audit_database,
)
from .query import AuditQuery, FileAuditQuery

__all__ = [
    "AuditChainBroken",
    "AuditPipeline",
    "AuditQuery",
    "AuditQueryUnavailable",
    "AuditSignatureInvalid",
    "AuditSinkUnavailable",
    "AuditStoreUnavailable",
    "FileAuditQuery",
    "HttpAuditQuery",
    "HttpAuditSink",
    "JsonlAuditSink",
    "KeyringError",
    "ListAuditSink",
    "PostgresAuditQuery",
    "PostgresAuditSink",
    "SigningKeyring",
    "load_records",
    "query_audit_records",
    "query_events",
    "record_signature",
    "verify_audit_database",
    "verify_audit_file",
]
