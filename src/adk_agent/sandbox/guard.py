"""Deny or allowlist network access inside the sandbox child process."""

from __future__ import annotations

import socket
from typing import Any

from .errors import SandboxViolation
from .policy import SandboxPolicy


def install_network_guard(policy: SandboxPolicy) -> None:
    """Patch socket calls in this process. Call it in the child before the handler."""
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
            raise SandboxViolation(f"network access to {host!r} is denied")
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
            raise SandboxViolation(f"network access to {address!r} is denied")
        return real_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> Any:
        if not address_allowed(self, address):
            raise SandboxViolation(f"network access to {address!r} is denied")
        return real_connect_ex(self, address)

    socket.getaddrinfo = guarded_getaddrinfo  # type: ignore
    socket.socket.connect = guarded_connect  # type: ignore
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore
