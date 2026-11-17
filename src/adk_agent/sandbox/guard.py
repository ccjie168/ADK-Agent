"""Deny or allowlist network access inside the sandbox child process."""

from __future__ import annotations

import os
import socket
import subprocess  # nosec B404  # imported to patch Popen, not to run it
from typing import Any, NoReturn

from .errors import SandboxViolation
from .policy import SandboxPolicy

_last_violation: SandboxViolation | None = None

_PROCESS_CALLS = (
    "fork",
    "forkpty",
    "posix_spawn",
    "posix_spawnp",
    "execl",
    "execle",
    "execlp",
    "execlpe",
    "execv",
    "execve",
    "execvp",
    "execvpe",
    "spawnl",
    "spawnle",
    "spawnlp",
    "spawnlpe",
    "spawnv",
    "spawnve",
    "spawnvp",
    "spawnvpe",
)


def last_violation() -> SandboxViolation | None:
    """The violation instance the guard raised most recently."""
    return _last_violation


def _deny(reason: str) -> NoReturn:
    global _last_violation
    violation = SandboxViolation(reason)
    _last_violation = violation
    raise violation


def install_network_guard(policy: SandboxPolicy, *, strict: bool = False) -> None:
    """Patch socket calls in this process. Call it in the child before the handler.

    ``strict`` also blocks socket creation for INET, INET6 and UNIX families and
    process creation, which would otherwise reach the network outside Python.
    """
    allowed = set(policy.allowed_hosts or [])
    resolved: set[str] = set()

    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def host_allowed(host: Any) -> bool:
        if policy.allow_network:
            return True
        return isinstance(host, str) and host.lower() in allowed

    def guarded_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        if not host_allowed(host):
            _deny(f"network access to {host!r} is denied")
        infos = real_getaddrinfo(host, port, *args, **kwargs)
        for info in infos:
            address = info[4]
            if address and isinstance(address[0], str):
                resolved.add(address[0])
        return infos

    def address_allowed(self: socket.socket, address: Any) -> bool:
        if self.family not in (socket.AF_INET, socket.AF_INET6):
            return True
        if policy.allow_network:
            return True
        host = address[0] if isinstance(address, tuple) else address
        if not isinstance(host, str):
            return False
        return host in resolved or host.lower() in allowed

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        if not address_allowed(self, address):
            _deny(f"network access to {address!r} is denied")
        return real_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> Any:
        if not address_allowed(self, address):
            _deny(f"network access to {address!r} is denied")
        return real_connect_ex(self, address)

    socket.getaddrinfo = guarded_getaddrinfo  # type: ignore
    socket.socket.connect = guarded_connect  # type: ignore
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore

    if not (strict and not policy.allow_network):
        return

    import _socket

    real_init = socket.socket.__init__
    real_c_socket = _socket.socket
    blocked_families = {socket.AF_INET, socket.AF_INET6}
    if hasattr(socket, "AF_UNIX"):
        blocked_families.add(socket.AF_UNIX)

    class _GuardedSocket(real_c_socket):  # type: ignore[misc, valid-type]
        def __init__(self, family=-1, type=-1, proto=-1, fileno=None):  # type: ignore[no-untyped-def]
            actual = socket.AF_INET if family == -1 else family
            if fileno is None and actual in blocked_families:
                _deny(f"socket family {actual} is denied")
            real_c_socket.__init__(self, family, type, proto, fileno)

    _socket.socket = _GuardedSocket  # type: ignore[misc]

    def guarded_init(
        self: Any,
        family: int = -1,
        type: int = -1,
        proto: int = -1,
        fileno: int | None = None,
    ) -> None:
        if fileno is not None:
            real_init(self, family, type, proto, fileno)
            return
        actual = socket.AF_INET if family == -1 else family
        if actual in blocked_families:
            _deny(f"socket family {actual} is denied")
        real_init(self, family, type, proto)

    socket.socket.__init__ = guarded_init  # type: ignore

    def deny_process(*args: Any, **kwargs: Any) -> NoReturn:
        _deny("process creation is denied")

    os.system = deny_process  # type: ignore
    os.popen = deny_process  # type: ignore
    for name in _PROCESS_CALLS:
        if hasattr(os, name):
            setattr(os, name, deny_process)
    subprocess.Popen.__init__ = deny_process  # type: ignore
