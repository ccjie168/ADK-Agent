"""SLICE-047: W3C traceparent parsing and trace id resolution."""

from __future__ import annotations

import re

from adk_agent.tracing import resolve_trace_id, trace_id_from_traceparent

TRACE = "4bf9" * 8
PARENT = "00f0" * 4


def test_valid_traceparent():
    assert trace_id_from_traceparent(f"00-{TRACE}-{PARENT}-01") == TRACE


def test_rejects_version_ff():
    assert trace_id_from_traceparent(f"ff-{TRACE}-{PARENT}-01") is None


def test_rejects_zero_trace_id():
    assert trace_id_from_traceparent(f"00-{'0' * 32}-{PARENT}-01") is None


def test_rejects_zero_parent_id():
    assert trace_id_from_traceparent(f"00-{TRACE}-{'0' * 16}-01") is None


def test_rejects_malformed():
    for value in (
        None,
        "",
        "abc",
        f"00-{TRACE}-{PARENT}",
        f"00-{TRACE.upper()}-{PARENT}-01",
        f"00-{TRACE}-{PARENT}-0",
        f"00-{TRACE}-{PARENT}-zz",
    ):
        assert trace_id_from_traceparent(value) is None


def test_x_trace_id_wins():
    assert resolve_trace_id("console-trace", f"00-{TRACE}-{PARENT}-01") == "console-trace"


def test_invalid_x_trace_id_falls_back_to_traceparent():
    assert resolve_trace_id("bad trace", f"00-{TRACE}-{PARENT}-01") == TRACE


def test_generates_when_missing():
    generated = resolve_trace_id(None, None)

    assert re.fullmatch(r"[0-9a-f]{32}", generated)
