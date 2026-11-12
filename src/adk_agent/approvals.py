"""A directory-backed approval inbox that implements the ``ApprovalGate`` port.

Each approval is two files under one root, so an executor process and a console
process can share a request without sharing memory:

``<root>/<request_id>.request.json``   written once, idempotent for the same id
``<root>/<request_id>.decision.json``  created exclusively, never rewritten
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .core import ApprovalDecision, ApprovalRequest

_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
_REQUEST_SUFFIX = ".request.json"
_DECISION_SUFFIX = ".decision.json"


class ApprovalInboxError(Exception):
    """Base class for approval inbox failures."""


class InvalidApprovalRequest(ApprovalInboxError):
    """The request id is unsafe to turn into a filename."""


class ApprovalNotFound(ApprovalInboxError):
    """No request file exists for this id."""


class ApprovalConflict(ApprovalInboxError):
    """A request or decision already exists with different content."""


@dataclass(frozen=True)
class ApprovalRecord:
    request: ApprovalRequest
    decision: ApprovalDecision | None


def _checked_id(request_id: str) -> str:
    if not _REQUEST_ID.fullmatch(request_id):
        raise InvalidApprovalRequest(f"unsafe request id: {request_id!r}")
    return request_id


def _atomic_write(path: Path, payload: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(payload)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    try:
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


class FileApprovalInbox:
    """Store approval requests and decisions as two files per request."""

    def __init__(
        self,
        root: str | Path,
        *,
        poll_seconds: float = 0.5,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(root)
        self.poll_seconds = poll_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _request_path(self, request_id: str) -> Path:
        return self.root / f"{request_id}{_REQUEST_SUFFIX}"

    def _decision_path(self, request_id: str) -> Path:
        return self.root / f"{request_id}{_DECISION_SUFFIX}"

    def submit(self, request: ApprovalRequest) -> None:
        request_id = _checked_id(request.request_id)
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._request_path(request_id)
        if path.exists():
            existing = ApprovalRequest.model_validate_json(path.read_text(encoding="utf-8"))
            if existing != request:
                raise ApprovalConflict(
                    f"request {request_id!r} already exists with different content"
                )
            return
        _atomic_write(path, request.model_dump_json())

    def decide(
        self,
        request_id: str,
        *,
        approved: bool,
        approver: str,
        reason: str = "",
    ) -> ApprovalDecision:
        request_id = _checked_id(request_id)
        request_path = self._request_path(request_id)
        if not request_path.exists():
            raise ApprovalNotFound(f"no request {request_id!r}")
        self.root.mkdir(parents=True, exist_ok=True)
        decision = ApprovalDecision(
            request_id=request_id,
            approved=approved,
            approver=approver,
            reason=reason,
            decided_at=self._clock(),
        )
        target = self._decision_path(request_id)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.root, delete=False) as tmp:
            tmp.write(decision.model_dump_json())
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        try:
            try:
                os.link(tmp_path, target)
            except FileExistsError:
                raise ApprovalConflict(f"request {request_id!r} already has a decision") from None
        finally:
            tmp_path.unlink(missing_ok=True)
        return decision

    def get(self, request_id: str) -> ApprovalRecord | None:
        if not _REQUEST_ID.fullmatch(request_id):
            return None
        request_path = self._request_path(request_id)
        if not request_path.exists():
            return None
        request = ApprovalRequest.model_validate_json(request_path.read_text(encoding="utf-8"))
        decision_path = self._decision_path(request_id)
        decision = (
            ApprovalDecision.model_validate_json(decision_path.read_text(encoding="utf-8"))
            if decision_path.exists()
            else None
        )
        return ApprovalRecord(request=request, decision=decision)

    def pending(self) -> list[ApprovalRequest]:
        if not self.root.is_dir():
            return []
        found: list[ApprovalRequest] = []
        for path in self.root.glob(f"*{_REQUEST_SUFFIX}"):
            request_id = path.name[: -len(_REQUEST_SUFFIX)]
            if not _REQUEST_ID.fullmatch(request_id):
                continue
            if self._decision_path(request_id).exists():
                continue
            try:
                found.append(ApprovalRequest.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        found.sort(key=lambda request: (request.requested_at, request.request_id))
        return found

    async def request(self, request: ApprovalRequest) -> ApprovalDecision:
        """Submit and wait for a decision file to appear."""
        self.submit(request)
        request_id = request.request_id
        while True:
            record = self.get(request_id)
            if record is not None and record.decision is not None:
                return record.decision
            await asyncio.sleep(self.poll_seconds)


__all__ = [
    "ApprovalConflict",
    "ApprovalNotFound",
    "ApprovalRecord",
    "FileApprovalInbox",
    "InvalidApprovalRequest",
]
