"""The ADK A2A modules, resolved lazily through a caller-supplied importer.

The ``a2a-sdk`` extra is optional: both factories translate a missing
dependency into :class:`A2aUnavailable` with the install hint.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

__all__ = ["A2aUnavailable", "remote_a2a_agent", "to_a2a"]

_INSTALL_HINT = (
    "A2A support needs the optional dependency; install it with "
    "`pip install 'a2a-sdk[http-server]>=0.3.4,<2'` "
    "(the range ADK 2.x declares for its a2a extra)."
)

Importer = Callable[[str], Any]


class A2aUnavailable(RuntimeError):
    """The optional A2A dependency is not installed."""


def to_a2a(importer: Importer) -> Any:
    try:
        return importer("google.adk.a2a.utils.agent_to_a2a").to_a2a
    except ImportError as exc:
        raise A2aUnavailable(_INSTALL_HINT) from exc


def remote_a2a_agent(importer: Importer) -> Any:
    try:
        return importer("google.adk.a2a.agent._remote_a2a_agent").RemoteA2aAgent
    except ImportError as exc:
        raise A2aUnavailable(_INSTALL_HINT) from exc
