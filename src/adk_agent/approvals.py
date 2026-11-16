"""A directory-backed approval inbox that implements the ``ApprovalGate`` port.

Each approval is two files under one root, so an executor process and a console
process can share a request without sharing memory:

``<root>/<request_id>.request.json``   written once, idempotent for the same id
``<root>/<request_id>.decision.json``  created exclusively, never rewritten
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import re
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .core import ApprovalDecision, ApprovalRequest
from .registry.paths import safe_join

_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
_REQUEST_SUFFIX = ".request.json"
_DECISION_SUFFIX = ".decision.json"
_REQUEST_FILE = r"^[A-Za-z0-9._-]{1,128}\.request\.json$"
_DECISION_FILE = r"^[A-Za-z0-9._-]{1,128}\.decision\.json$"
HISTORY_STATUSES = ("approved", "denied", "expired", "cancelled")

_logger = logging.getLogger(__name__)


class ApprovalInboxError(Exception):
    """Base class for approval inbox failures."""


class InvalidApprovalRequest(ApprovalInboxError):
    """The request id is unsafe to turn into a filename."""


class ApprovalNotFound(ApprovalInboxError):
    """No request file exists for this id."""


class ApprovalConflict(ApprovalInboxError):
    """A request or decision already exists with different content."""


class ApprovalExpired(ApprovalInboxError):
    """The request deadline passed before a decision was recorded."""


@dataclass(frozen=True)
class ApprovalRecord:
    request: ApprovalRequest
    decision: ApprovalDecision | None


@dataclass(frozen=True)
class ApprovalHistoryEntry:
    request: ApprovalRequest
    decision: ApprovalDecision | None
    status: str
    archived: bool
    terminal_at: datetime


@dataclass(frozen=True)
class PruneResult:
    archived: int = 0
    deleted: int = 0
    kept: int = 0


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
        ttl_seconds: float | None = None,
        on_submit: Callable[[ApprovalRequest], Awaitable[None] | None] | None = None,
    ) -> None:
        self.root = Path(root)
        self.poll_seconds = poll_seconds
        self.ttl_seconds = ttl_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._on_submit = on_submit

    def _request_path(self, request_id: str) -> Path:
        return safe_join(self.root, f"{request_id}{_REQUEST_SUFFIX}", pattern=_REQUEST_FILE)

    def _decision_path(self, request_id: str) -> Path:
        return safe_join(self.root, f"{request_id}{_DECISION_SUFFIX}", pattern=_DECISION_FILE)

    def expires_at(self, request: ApprovalRequest) -> datetime | None:
        if request.expires_at is not None:
            return request.expires_at
        if self.ttl_seconds is None:
            return None
        return request.requested_at + timedelta(seconds=self.ttl_seconds)

    def is_expired(self, request: ApprovalRequest, now: datetime | None = None) -> bool:
        deadline = self.expires_at(request)
        if deadline is None:
            return False
        return (now if now is not None else self._clock()) >= deadline

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
        target = self._decision_path(request_id)
        if target.exists():
            raise ApprovalConflict(f"request {request_id!r} already has a decision")
        request = ApprovalRequest.model_validate_json(request_path.read_text(encoding="utf-8"))
        if self.is_expired(request):
            raise ApprovalExpired(f"approval request {request_id!r} has expired")
        self.root.mkdir(parents=True, exist_ok=True)
        decision = ApprovalDecision(
            request_id=request_id,
            approved=approved,
            approver=approver,
            reason=reason,
            decided_at=self._clock(),
        )
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
                request = ApprovalRequest.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if self.is_expired(request):
                continue
            found.append(request)
        found.sort(key=lambda request: (request.requested_at, request.request_id))
        return found

    def history(
        self,
        *,
        tenant: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[ApprovalHistoryEntry]:
        if status is not None and status not in HISTORY_STATUSES:
            raise ValueError(f"unknown approval history status: {status!r}")
        limit = max(1, min(200, limit))
        found: list[ApprovalHistoryEntry] = []
        for directory, archived in ((self.root, False), (safe_join(self.root, "archive"), True)):
            if not directory.is_dir():
                continue
            for path in directory.glob(f"*{_REQUEST_SUFFIX}"):
                request_id = path.name[: -len(_REQUEST_SUFFIX)]
                if not _REQUEST_ID.fullmatch(request_id):
                    continue
                try:
                    request = ApprovalRequest.model_validate_json(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if tenant is not None and request.principal.tenant != tenant:
                    continue
                decision_path = directory / f"{request_id}{_DECISION_SUFFIX}"
                try:
                    decision = (
                        ApprovalDecision.model_validate_json(
                            decision_path.read_text(encoding="utf-8")
                        )
                        if decision_path.exists()
                        else None
                    )
                except (OSError, ValueError):
                    continue
                if decision is not None:
                    entry_status = "approved" if decision.approved else "denied"
                    terminal_at = decision.decided_at
                elif self.is_expired(request):
                    deadline = self.expires_at(request)
                    if deadline is None:
                        continue
                    entry_status = "expired"
                    terminal_at = deadline
                else:
                    continue
                if status is not None and entry_status != status:
                    continue
                found.append(
                    ApprovalHistoryEntry(
                        request=request,
                        decision=decision,
                        status=entry_status,
                        archived=archived,
                        terminal_at=terminal_at,
                    )
                )
        found.sort(
            key=lambda entry: (entry.terminal_at, entry.request.request_id),
            reverse=True,
        )
        return found[:limit]

    def prune(
        self,
        max_age_seconds: float,
        *,
        archive: bool = True,
        now: datetime | None = None,
    ) -> PruneResult:
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be greater than 0")
        current = now if now is not None else self._clock()
        cutoff = current - timedelta(seconds=max_age_seconds)
        archive_dir = safe_join(self.root, "archive")
        archived = 0
        deleted = 0
        kept = 0

        if not self.root.is_dir():
            return PruneResult()

        for path in self.root.glob(f"*{_REQUEST_SUFFIX}"):
            request_id = path.name[: -len(_REQUEST_SUFFIX)]
            if not _REQUEST_ID.fullmatch(request_id):
                kept += 1
                continue
            try:
                request = ApprovalRequest.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                kept += 1
                continue
            decision_path = self._decision_path(request_id)
            try:
                decision = (
                    ApprovalDecision.model_validate_json(decision_path.read_text(encoding="utf-8"))
                    if decision_path.exists()
                    else None
                )
            except (OSError, ValueError):
                kept += 1
                continue

            if decision is not None:
                terminal = decision.decided_at
            elif self.is_expired(request, current):
                deadline = self.expires_at(request)
                if deadline is None:
                    kept += 1
                    continue
                terminal = deadline
            else:
                kept += 1
                continue

            if not terminal < cutoff:
                kept += 1
                continue

            if archive:
                target_request = archive_dir / path.name
                target_decision = archive_dir / decision_path.name
                if target_request.exists() or (decision is not None and target_decision.exists()):
                    kept += 1
                    continue
                archive_dir.mkdir(parents=True, exist_ok=True)
                os.replace(path, target_request)
                if decision is not None:
                    os.replace(decision_path, target_decision)
                archived += 1
            else:
                path.unlink()
                if decision is not None:
                    decision_path.unlink()
                deleted += 1

        return PruneResult(archived=archived, deleted=deleted, kept=kept)

    async def request(self, request: ApprovalRequest) -> ApprovalDecision:
        """Submit, notify, then wait for a decision file to appear."""
        self.submit(request)
        await self._notify(request)
        request_id = request.request_id
        while True:
            record = self.get(request_id)
            if record is not None and record.decision is not None:
                return record.decision
            if self.is_expired(request):
                raise ApprovalExpired(f"approval request {request_id!r} has expired")
            await asyncio.sleep(self.poll_seconds)

    async def _notify(self, request: ApprovalRequest) -> None:
        if self._on_submit is None:
            return
        try:
            result = self._on_submit(request)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "approval notification failed for %s: %s",
                request.request_id,
                type(exc).__name__,
            )


__all__ = [
    "HISTORY_STATUSES",
    "ApprovalConflict",
    "ApprovalExpired",
    "ApprovalHistoryEntry",
    "ApprovalNotFound",
    "ApprovalRecord",
    "FileApprovalInbox",
    "InvalidApprovalRequest",
    "PruneResult",
]
