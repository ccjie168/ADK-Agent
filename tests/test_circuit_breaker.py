"""SLICE-054: the circuit breaker state machine."""

from __future__ import annotations

from adk_agent.resilience import CircuitBreaker


class Clock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _breaker(clock: Clock, threshold: int = 2, reset: float = 30.0) -> CircuitBreaker:
    return CircuitBreaker(
        failure_threshold=threshold,
        reset_seconds=reset,
        clock=clock,
    )


def test_closed_until_threshold():
    breaker = _breaker(Clock())

    assert breaker.allow() is True
    breaker.record_failure()
    assert breaker.state == "closed"
    assert breaker.allow() is True


def test_opens_at_threshold():
    breaker = _breaker(Clock())
    breaker.record_failure()
    breaker.record_failure()

    assert breaker.state == "open"
    assert breaker.allow() is False


def test_rejects_before_reset():
    clock = Clock()
    breaker = _breaker(clock)
    breaker.record_failure()
    breaker.record_failure()
    clock.now += 29

    assert breaker.allow() is False


def test_half_open_single_probe():
    clock = Clock()
    breaker = _breaker(clock)
    breaker.record_failure()
    breaker.record_failure()
    clock.now += 30

    assert breaker.allow() is True
    assert breaker.state == "half_open"
    assert breaker.allow() is False


def test_probe_success_closes():
    clock = Clock()
    breaker = _breaker(clock)
    breaker.record_failure()
    breaker.record_failure()
    clock.now += 30
    assert breaker.allow() is True

    breaker.record_success()

    assert breaker.state == "closed"
    assert breaker.allow() is True


def test_probe_failure_reopens():
    clock = Clock()
    breaker = _breaker(clock)
    breaker.record_failure()
    breaker.record_failure()
    clock.now += 30
    assert breaker.allow() is True

    breaker.record_failure()

    assert breaker.state == "open"
    assert breaker.allow() is False
    clock.now += 30
    assert breaker.allow() is True


def test_success_resets_failures():
    breaker = _breaker(Clock(), threshold=2)
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()

    assert breaker.state == "closed"
