"""SLICE-047: the in-process Prometheus registry."""

from __future__ import annotations

import pytest

from adk_agent.metrics import MetricsRegistry


def test_counter_render():
    registry = MetricsRegistry()
    registry.inc("adk_agent_runs_total", {"tenant": "acme", "status": "ok"})

    text = registry.render()

    assert "# TYPE adk_agent_runs_total counter" in text
    assert 'adk_agent_runs_total{status="ok",tenant="acme"} 1' in text


def test_summary_render():
    registry = MetricsRegistry()
    registry.observe("adk_agent_run_duration_seconds", 0.25, {"tenant": "acme"})
    registry.observe("adk_agent_run_duration_seconds", 0.75, {"tenant": "acme"})

    text = registry.render()

    assert "# TYPE adk_agent_run_duration_seconds summary" in text
    assert 'adk_agent_run_duration_seconds_count{tenant="acme"} 2' in text
    assert 'adk_agent_run_duration_seconds_sum{tenant="acme"} 1' in text


def test_labels_are_sorted_and_escaped():
    registry = MetricsRegistry()
    registry.inc("custom_requests_total", {"z": 'a"b', "a": "x\\y"})

    text = registry.render()

    assert 'custom_requests_total{a="x\\\\y",z="a\\"b"} 1' in text


def test_invalid_metric_name_rejected():
    registry = MetricsRegistry()

    with pytest.raises(ValueError):
        registry.inc("bad-name")
    with pytest.raises(ValueError):
        registry.observe("also-bad", 1.0)


def test_invalid_label_name_rejected():
    registry = MetricsRegistry()

    with pytest.raises(ValueError):
        registry.inc("custom_total", {"bad-name": "x"})


def test_empty_registry_renders_nothing():
    assert MetricsRegistry().render() == ""


def test_values_accumulate_per_label_set():
    registry = MetricsRegistry()
    registry.inc("custom_total", {"k": "a"})
    registry.inc("custom_total", {"k": "a"}, value=2)
    registry.inc("custom_total", {"k": "b"})

    text = registry.render()

    assert 'custom_total{k="a"} 3' in text
    assert 'custom_total{k="b"} 1' in text
