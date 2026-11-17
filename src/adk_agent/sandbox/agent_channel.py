"""Bidirectional model frames for the sandbox worker (ADR-0024)."""

from __future__ import annotations

import asyncio
from typing import Any, BinaryIO

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from .frames import FrameError, read_frame, write_frame

_channel: SandboxChannel | None = None


class SandboxModelError(RuntimeError):
    """The parent could not serve a model call."""


def set_channel(channel: SandboxChannel | None) -> None:
    """Install the channel the sandbox model uses; ``None`` disables it."""
    global _channel
    _channel = channel


def channel() -> SandboxChannel | None:
    return _channel


class SandboxChannel:
    """Serve model calls over the worker's frame pipes."""

    def __init__(self, reader: BinaryIO, writer: BinaryIO) -> None:
        self._reader = reader
        self._writer = writer
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._next_id = 0
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._read_loop())

    async def call_model(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        if self._task is None:
            raise SandboxModelError("model channel is not started")
        self._next_id += 1
        call_id = self._next_id
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[call_id] = future
        write_frame(self._writer, {"type": "model", "id": call_id, "request": request})
        frame = await future
        if frame.get("type") == "model_error":
            raise SandboxModelError(str(frame.get("message", "model call failed")))
        responses = frame.get("responses")
        if not isinstance(responses, list):
            raise SandboxModelError("model result is malformed")
        return responses

    async def _read_loop(self) -> None:
        try:
            while True:
                try:
                    frame = await asyncio.to_thread(read_frame, self._reader)
                except (FrameError, OSError, ValueError):
                    break
                if not isinstance(frame, dict):
                    continue
                call_id = frame.get("id")
                if not isinstance(call_id, int):
                    continue
                future = self._pending.pop(call_id, None)
                if future is not None and not future.done():
                    future.set_result(frame)
        finally:
            self._fail_pending("model channel closed")

    def _fail_pending(self, message: str) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(SandboxModelError(message))
        self._pending.clear()

    def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self._fail_pending("model channel closed")


class SandboxModel(BaseLlm):
    """ADK model that forwards requests to the parent process."""

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> Any:
        active = _channel
        if active is None:
            raise SandboxModelError("model channel is not configured")
        responses = await active.call_model(llm_request.model_dump(mode="json"))
        for item in responses:
            yield LlmResponse.model_validate(item)
