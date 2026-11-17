"""SLICE-130: model frames between the sandbox worker and its parent."""

from __future__ import annotations

import asyncio
import io
import os

import pytest

from adk_agent.sandbox.agent_channel import SandboxChannel, SandboxModelError
from adk_agent.sandbox.frames import read_frame, write_frame


def _frame(payload: dict) -> bytes:
    buffer = io.BytesIO()
    write_frame(buffer, payload)
    return buffer.getvalue()


def _written(writer: io.BytesIO) -> dict:
    return read_frame(io.BytesIO(writer.getvalue()))


def _pair():
    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, "rb")
    writer = io.BytesIO()
    channel = SandboxChannel(reader, writer)
    channel.start()
    return channel, write_fd, writer


def test_call_model_round_trip():
    async def scenario():
        channel, write_fd, writer = _pair()
        task = asyncio.create_task(channel.call_model({"contents": []}))
        await asyncio.sleep(0.05)
        request = _written(writer)
        assert request["type"] == "model"
        os.write(
            write_fd,
            _frame({"type": "model_result", "id": request["id"], "responses": [{"seq": 1}]}),
        )
        result = await task
        os.close(write_fd)
        channel.close()
        return result

    assert asyncio.run(scenario()) == [{"seq": 1}]


def test_calls_are_dispatched_by_id():
    async def scenario():
        channel, write_fd, writer = _pair()
        first = asyncio.create_task(channel.call_model({"which": "first"}))
        await asyncio.sleep(0.02)
        second = asyncio.create_task(channel.call_model({"which": "second"}))
        await asyncio.sleep(0.05)
        buffer = io.BytesIO(writer.getvalue())
        one = read_frame(buffer)
        two = read_frame(buffer)
        assert {one["request"]["which"], two["request"]["which"]} == {"first", "second"}
        os.write(
            write_fd,
            _frame({"type": "model_result", "id": two["id"], "responses": [{"seq": 2}]}),
        )
        os.write(
            write_fd,
            _frame({"type": "model_result", "id": one["id"], "responses": [{"seq": 1}]}),
        )
        assert await first == [{"seq": 1}]
        assert await second == [{"seq": 2}]
        os.close(write_fd)
        channel.close()

    asyncio.run(scenario())


def test_model_errors_are_raised():
    async def scenario():
        channel, write_fd, writer = _pair()
        task = asyncio.create_task(channel.call_model({"contents": []}))
        await asyncio.sleep(0.05)
        request = _written(writer)
        os.write(
            write_fd,
            _frame({"type": "model_error", "id": request["id"], "message": "KernelBoom"}),
        )
        with pytest.raises(SandboxModelError):
            await task
        os.close(write_fd)
        channel.close()

    asyncio.run(scenario())


def test_eof_fails_pending_calls():
    async def scenario():
        channel, write_fd, writer = _pair()
        task = asyncio.create_task(channel.call_model({"contents": []}))
        await asyncio.sleep(0.05)
        os.close(write_fd)
        with pytest.raises(SandboxModelError):
            await task
        channel.close()

    asyncio.run(scenario())
