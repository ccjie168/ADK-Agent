"""Length-prefixed JSON frames for the agent sandbox protocol."""

from __future__ import annotations

import asyncio
import json
import struct
from typing import Any, BinaryIO

MAX_FRAME = 32 * 1024 * 1024
_HEADER = struct.Struct(">I")


class FrameError(ValueError):
    """A frame is too large, truncated, or not JSON."""


def _encode(payload: Any) -> bytes:
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_FRAME:
        raise FrameError("frame is too large")
    return _HEADER.pack(len(data)) + data


def write_frame(stream: BinaryIO, payload: Any) -> None:
    stream.write(_encode(payload))
    stream.flush()


def read_frame(stream: BinaryIO) -> Any:
    header = stream.read(_HEADER.size)
    if len(header) != _HEADER.size:
        raise FrameError("frame header is truncated")
    (size,) = _HEADER.unpack(header)
    if size > MAX_FRAME:
        raise FrameError("frame is too large")
    data = stream.read(size)
    if len(data) != size:
        raise FrameError("frame body is truncated")
    try:
        return json.loads(data)
    except ValueError as exc:
        raise FrameError("frame is not JSON") from exc


async def write_frame_async(writer: asyncio.StreamWriter, payload: Any) -> None:
    writer.write(_encode(payload))
    await writer.drain()


async def read_frame_async(reader: asyncio.StreamReader) -> Any:
    try:
        header = await reader.readexactly(_HEADER.size)
        (size,) = _HEADER.unpack(header)
        if size > MAX_FRAME:
            raise FrameError("frame is too large")
        data = await reader.readexactly(size)
    except asyncio.IncompleteReadError as exc:
        raise FrameError("frame is truncated") from exc
    try:
        return json.loads(data)
    except ValueError as exc:
        raise FrameError("frame is not JSON") from exc
