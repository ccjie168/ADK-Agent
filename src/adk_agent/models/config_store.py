"""Global default model config store (ADR-0040)."""

from __future__ import annotations

from typing import Protocol


class ModelConfigStoreUnavailable(Exception):
    """The model config store cannot be read or written."""


class ModelConfigStore(Protocol):
    async def get(self) -> str | None: ...

    async def put(self, model: str) -> str: ...


__all__ = ["ModelConfigStore", "ModelConfigStoreUnavailable"]
