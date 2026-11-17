"""Sandbox failures. ``error_code`` is stable for audit records."""

from __future__ import annotations


class SandboxError(Exception):
    error_code = "SandboxError"


class SandboxTimeout(SandboxError):
    error_code = "SandboxTimeout"


class SandboxCrashed(SandboxError):
    error_code = "SandboxCrashed"


class SandboxViolation(SandboxError):
    error_code = "SandboxViolation"


class SandboxToolError(SandboxError):
    """A handler error raised inside the sandbox, re-raised with its class name."""

    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        super().__init__(message)
