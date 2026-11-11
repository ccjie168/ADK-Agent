"""Module-level handlers for sandbox tests. They stay picklable under spawn."""

from __future__ import annotations

import os
import socket
import threading
import time


def add(a: int, b: int) -> int:
    return a + b


async def async_add(a: int, b: int) -> int:
    return a + b


def sleep_long(seconds: float) -> str:
    time.sleep(seconds)
    return "done"


def pids() -> int:
    return os.getpid()


def env_keys() -> list[str]:
    return sorted(os.environ)


def fetch(host: str, port: int) -> str:
    with socket.create_connection((host, port), timeout=2) as connection:
        connection.sendall(b"ping")
    return "connected"


def boom() -> str:
    raise ValueError("boom")


def eat_memory() -> str:
    block = bytearray(200 * 1024 * 1024)
    return str(len(block))


def unsendable() -> object:
    return threading.Lock()
