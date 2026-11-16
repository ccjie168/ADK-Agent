"""Central log sanitizer: escape CR and LF before records reach any handler."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

_installed = False


def _clean(value: object) -> object:
    if isinstance(value, str):
        return value.replace("\r", "\\r").replace("\n", "\\n")
    return value


class _SanitizingFactory:
    """Wrap the active log record factory and escape strings in each record."""

    def __init__(self, factory: Callable[..., logging.LogRecord]) -> None:
        self._factory = factory

    def __call__(self, *args: Any, **kwargs: Any) -> logging.LogRecord:
        record = self._factory(*args, **kwargs)
        record.msg = _clean(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_clean(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: _clean(value) for key, value in record.args.items()}
        return record


def install_log_sanitizer() -> None:
    """Install the sanitizing factory once; later calls are no-ops."""
    global _installed
    if _installed:
        return
    logging.setLogRecordFactory(_SanitizingFactory(logging.getLogRecordFactory()))
    _installed = True
