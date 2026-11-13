"""Failure isolation for outbound dependency calls."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Literal

__all__ = ["CircuitBreaker"]

State = Literal["closed", "open", "half_open"]


class CircuitBreaker:
    """Three-state breaker: closed, open, half_open.

    Closed calls pass through. Consecutive failures up to ``failure_threshold``
    open the circuit, which rejects calls until ``reset_seconds`` have passed.
    The next allowed call is a single probe; its outcome closes or reopens the
    circuit.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        reset_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if reset_seconds <= 0:
            raise ValueError("reset_seconds must be positive")
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._state: State = "closed"
        self._failures = 0
        self._opened_at = 0.0
        self._probe_in_flight = False

    @property
    def state(self) -> State:
        with self._lock:
            return self._state

    def allow(self) -> bool:
        with self._lock:
            if self._state == "closed":
                return True
            if self._state == "open":
                if self._clock() - self._opened_at < self.reset_seconds:
                    return False
                self._state = "half_open"
                self._probe_in_flight = True
                return True
            if self._probe_in_flight:
                return False
            self._probe_in_flight = True
            return True

    def record_success(self) -> None:
        with self._lock:
            self._state = "closed"
            self._failures = 0
            self._probe_in_flight = False

    def record_failure(self) -> None:
        with self._lock:
            now = self._clock()
            if self._state == "half_open":
                self._state = "open"
                self._opened_at = now
                self._probe_in_flight = False
            elif self._state == "open":
                self._opened_at = now
            else:
                self._failures += 1
                if self._failures >= self.failure_threshold:
                    self._state = "open"
                    self._opened_at = now
