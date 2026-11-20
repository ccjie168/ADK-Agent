"""Per-tenant model spend tracking for budget enforcement (ADR-0033)."""

from __future__ import annotations


class BudgetTracker:
    """In-process USD spend per tenant; shared by every gateway in the process."""

    def __init__(self) -> None:
        self._spent: dict[str, float] = {}

    def spent(self, tenant: str) -> float:
        return self._spent.get(tenant, 0.0)

    def add(self, tenant: str, usd: float) -> None:
        if usd < 0:
            raise ValueError("spend must be non-negative")
        self._spent[tenant] = self.spent(tenant) + usd


__all__ = ["BudgetTracker"]
