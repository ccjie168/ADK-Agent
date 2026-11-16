"""File-backed trigger definitions for single-host development."""

from __future__ import annotations

import builtins
import json
import os
import re
import tempfile
import threading
from pathlib import Path

from ..core import (
    AgentTrigger,
    TriggerConflict,
    TriggerNotFound,
)
from .paths import safe_join

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def _definition(trigger: AgentTrigger) -> dict:
    payload = trigger.model_dump(mode="json")
    for field in ("enabled", "created_at", "created_by"):
        payload.pop(field, None)
    return payload


class FileTriggerStore:
    """One trigger per ``(tenant, trigger_id)`` under ``<root>/<tenant>/<id>.json``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()

    def _path(self, tenant: str, trigger_id: str) -> Path:
        return safe_join(self.root, tenant, f"{trigger_id}.json", pattern=_NAME.pattern)

    async def add(self, trigger: AgentTrigger) -> AgentTrigger:
        path = self._path(trigger.tenant, trigger.trigger_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if path.exists():
                return self._resolve_existing(path, trigger)
            payload = json.dumps(trigger.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
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
                return self._resolve_existing(path, trigger)
            finally:
                tmp_path.unlink(missing_ok=True)
        return trigger

    async def get(self, tenant: str, trigger_id: str) -> AgentTrigger | None:
        path = self._path(tenant, trigger_id)
        if not path.is_file():
            return None
        return AgentTrigger.model_validate_json(path.read_text(encoding="utf-8"))

    async def list(self, tenant: str) -> list[AgentTrigger]:
        directory = safe_join(self.root, tenant, pattern=_NAME.pattern)
        if not directory.is_dir():
            return []
        triggers = [
            AgentTrigger.model_validate_json(path.read_text(encoding="utf-8"))
            for path in directory.glob("*.json")
        ]
        return sorted(
            (trigger for trigger in triggers if trigger.tenant == tenant),
            key=lambda trigger: trigger.trigger_id,
        )

    async def list_all(self) -> builtins.list[AgentTrigger]:
        if not self.root.is_dir():
            return []
        triggers: builtins.list[AgentTrigger] = []
        for directory in self.root.iterdir():
            if directory.is_dir() and _NAME.fullmatch(directory.name):
                triggers.extend(await self.list(directory.name))
        return sorted(triggers, key=lambda trigger: (trigger.tenant, trigger.trigger_id))

    async def disable(self, tenant: str, trigger_id: str, *, by: str) -> AgentTrigger:
        path = self._path(tenant, trigger_id)
        with self._lock:
            if not path.is_file():
                raise TriggerNotFound(f"trigger not found: {tenant}/{trigger_id}")
            trigger = AgentTrigger.model_validate_json(path.read_text(encoding="utf-8"))
            if not trigger.enabled:
                return trigger
            disabled = trigger.model_copy(update={"enabled": False})
            payload = json.dumps(disabled.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, delete=False
            ) as tmp:
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = Path(tmp.name)
            os.replace(tmp_path, path)
            return disabled

    def _resolve_existing(self, path: Path, trigger: AgentTrigger) -> AgentTrigger:
        existing = AgentTrigger.model_validate_json(path.read_text(encoding="utf-8"))
        if _definition(existing) != _definition(trigger):
            raise TriggerConflict(
                f"trigger {trigger.tenant}/{trigger.trigger_id} already has a different definition"
            )
        return existing


__all__ = ["FileTriggerStore"]
