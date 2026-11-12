"""Compatibility re-export of the audited runner now shared with A2A."""

from ..runtime.audit_proxy import AuditedRunner, wrap_runner

AuditedMcpRunner = AuditedRunner
__all__ = ["AuditedMcpRunner", "wrap_runner"]
