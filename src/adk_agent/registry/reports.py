"""File-backed eval reports. One immutable report per published version."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from ..core import EvalReport
from .file import _SAFE_NAME
from .paths import safe_join


class EvalReportConflict(Exception):
    """The same agent version already has a different eval report."""


class FileEvalReportStore:
    """Store reports under ``<root>/<tenant>/<id>/<version>.eval.json``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, tenant: str, agent_id: str, version: str) -> Path:
        return safe_join(
            self.root,
            tenant,
            agent_id,
            f"{version}.eval.json",
            pattern=_SAFE_NAME.pattern,
        )

    async def put(self, tenant: str, agent_id: str, version: str, report: EvalReport) -> EvalReport:
        path = self._path(tenant, agent_id, version)
        if path.exists():
            return self._resolve_existing(path, tenant, agent_id, version, report)

        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as tmp:
            tmp.write(payload)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        try:
            os.link(tmp_path, path)
        except FileExistsError:
            return self._resolve_existing(path, tenant, agent_id, version, report)
        finally:
            tmp_path.unlink(missing_ok=True)
        return report

    async def get(self, tenant: str, agent_id: str, version: str) -> EvalReport | None:
        path = self._path(tenant, agent_id, version)
        if not path.is_file():
            return None
        return EvalReport.model_validate_json(path.read_text(encoding="utf-8"))

    async def has(self, tenant: str, agent_id: str, version: str) -> bool:
        return self._path(tenant, agent_id, version).is_file()

    def _resolve_existing(
        self,
        path: Path,
        tenant: str,
        agent_id: str,
        version: str,
        report: EvalReport,
    ) -> EvalReport:
        existing = EvalReport.model_validate_json(path.read_text(encoding="utf-8"))
        if existing.model_dump(mode="json") != report.model_dump(mode="json"):
            raise EvalReportConflict(
                f"{tenant}/{agent_id}@{version} already has a different eval report"
            )
        return existing
