"""SLICE-129: length-prefixed frames for the agent sandbox protocol."""

from __future__ import annotations

import io
import struct

import pytest

from adk_agent.sandbox.frames import MAX_FRAME, FrameError, read_frame, write_frame


def test_round_trip():
    buffer = io.BytesIO()
    write_frame(buffer, {"type": "run", "input": "hello"})
    write_frame(buffer, {"type": "final", "text": "ok"})
    buffer.seek(0)

    assert read_frame(buffer) == {"type": "run", "input": "hello"}
    assert read_frame(buffer) == {"type": "final", "text": "ok"}


def test_oversized_frame_is_rejected():
    buffer = io.BytesIO()
    with pytest.raises(FrameError):
        write_frame(buffer, {"blob": "x" * (MAX_FRAME + 1)})
    assert buffer.getvalue() == b""


def test_truncated_frame_is_rejected():
    buffer = io.BytesIO(struct.pack(">I", 100) + b"short")
    with pytest.raises(FrameError):
        read_frame(buffer)
