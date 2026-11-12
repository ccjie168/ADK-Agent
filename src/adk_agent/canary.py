"""Weighted routing between a stable and a candidate agent version."""

from __future__ import annotations

import random
from collections.abc import Callable

from .core import CanaryPolicy


class CanaryRouter:
    """Pick a version for one run. The random source is injectable for tests."""

    def __init__(self, rand: Callable[[], float] = random.random) -> None:
        self._rand = rand

    def route(self, policy: CanaryPolicy, tenant: str) -> str:
        if policy.tenant != tenant:
            raise ValueError(f"canary policy belongs to tenant {policy.tenant!r}")
        if policy.weight <= 0:
            return policy.stable_version
        if policy.weight >= 1:
            return policy.canary_version
        return policy.canary_version if self._rand() < policy.weight else policy.stable_version


__all__ = ["CanaryRouter"]
