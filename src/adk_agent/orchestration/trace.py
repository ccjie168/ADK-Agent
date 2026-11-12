"""Build a trace tree from audit events for one trace_id."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal

from ..core import AuditEvent, TraceNode

NodeKind = Literal["plan", "step", "supervisor", "approval"]

_ACTIONS: dict[str, NodeKind] = {
    "orchestration.step": "step",
    "orchestration.supervisor": "supervisor",
    "orchestration.approval": "approval",
}


def _node(event: AuditEvent, kind: NodeKind, children: list[TraceNode] | None = None) -> TraceNode:
    return TraceNode(
        id=event.target,
        kind=kind,
        status=event.status,
        error_code=event.error_code,
        latency_ms=event.latency_ms,
        cost_usd=event.cost_usd,
        children=children or [],
    )


def build_trace(events: Iterable[AuditEvent], trace_id: str) -> TraceNode:
    relevant: Sequence[AuditEvent] = sorted(
        (event for event in events if event.trace_id == trace_id),
        key=lambda event: event.timestamp,
    )
    root = next(
        (event for event in reversed(relevant) if event.action == "orchestration.run"),
        None,
    )
    supervisors = [event for event in relevant if event.action == "orchestration.supervisor"]
    others = [
        event
        for event in relevant
        if event.action in {"orchestration.step", "orchestration.approval"}
    ]

    children: list[TraceNode] = []
    if supervisors:
        first = supervisors[0].timestamp
        children.extend(
            _node(event, _ACTIONS[event.action]) for event in others if event.timestamp < first
        )
        for index, supervisor in enumerate(supervisors):
            start = supervisor.timestamp
            end = supervisors[index + 1].timestamp if index + 1 < len(supervisors) else None
            nested = [
                _node(event, _ACTIONS[event.action])
                for event in others
                if event.timestamp >= start and (end is None or event.timestamp < end)
            ]
            children.append(_node(supervisor, "supervisor", nested))
    else:
        children = [_node(event, _ACTIONS[event.action]) for event in others]

    if root is None:
        return TraceNode(
            id=trace_id,
            kind="plan",
            status="error",
            error_code="trace_not_found",
            children=children,
        )
    return _node(root, "plan", children)
