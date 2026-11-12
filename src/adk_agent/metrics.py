"""In-process Prometheus metrics with counters and summaries."""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping

__all__ = ["MetricsRegistry"]

_METRIC_NAME = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]*")
_LABEL_NAME = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")

_Labels = tuple[tuple[str, str], ...]


class MetricsRegistry:
    """Thread-safe counters and summaries rendered as Prometheus text."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[_Labels, float]] = {}
        self._summaries: dict[str, dict[_Labels, tuple[float, int]]] = {}

    def inc(
        self,
        name: str,
        labels: Mapping[str, str] | None = None,
        value: float = 1.0,
    ) -> None:
        key = _label_key(name, labels)
        with self._lock:
            series = self._counters.setdefault(name, {})
            series[key] = series.get(key, 0.0) + value

    def observe(
        self,
        name: str,
        value: float,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        key = _label_key(name, labels)
        with self._lock:
            series = self._summaries.setdefault(name, {})
            total, count = series.get(key, (0.0, 0))
            series[key] = (total + value, count + 1)

    def render(self) -> str:
        with self._lock:
            counters = {name: dict(series) for name, series in self._counters.items()}
            summaries = {name: dict(series) for name, series in self._summaries.items()}

        lines: list[str] = []
        for name in sorted(counters):
            lines.append(f"# TYPE {name} counter")
            for key in sorted(counters[name]):
                lines.append(f"{name}{_labels_text(key)} {_format(counters[name][key])}")
        for name in sorted(summaries):
            lines.append(f"# TYPE {name} summary")
            for key in sorted(summaries[name]):
                total, count = summaries[name][key]
                lines.append(f"{name}_count{_labels_text(key)} {_format(count)}")
                lines.append(f"{name}_sum{_labels_text(key)} {_format(total)}")

        if not lines:
            return ""
        return "\n".join(lines) + "\n"


def _label_key(name: str, labels: Mapping[str, str] | None) -> _Labels:
    if not _METRIC_NAME.fullmatch(name):
        raise ValueError(f"invalid metric name: {name!r}")
    if not labels:
        return ()
    pairs: list[tuple[str, str]] = []
    for label_name, label_value in labels.items():
        if not _LABEL_NAME.fullmatch(label_name):
            raise ValueError(f"invalid label name: {label_name!r}")
        pairs.append((label_name, str(label_value)))
    return tuple(sorted(pairs))


def _labels_text(key: _Labels) -> str:
    if not key:
        return ""
    body = ",".join(f'{name}="{_escape(value)}"' for name, value in key)
    return "{" + body + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format(value: float) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return repr(number)
