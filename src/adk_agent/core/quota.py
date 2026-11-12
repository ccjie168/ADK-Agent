"""Per-tenant quota policy and the exceeded error."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class QuotaPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_runs: int | None = Field(default=None, gt=0)
    window_seconds: float = Field(default=60.0, gt=0)
    max_concurrent: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _has_a_limit(self) -> QuotaPolicy:
        if self.max_runs is None and self.max_concurrent is None:
            raise ValueError("quota policy needs max_runs or max_concurrent")
        return self


class QuotaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenants: dict[str, QuotaPolicy] = Field(default_factory=dict)

    @field_validator("tenants")
    @classmethod
    def _non_empty_tenants(cls, value: dict[str, QuotaPolicy]) -> dict[str, QuotaPolicy]:
        if any(not tenant for tenant in value):
            raise ValueError("tenant keys must be non-empty")
        return value


class QuotaExceeded(Exception):
    """A tenant used up its run or concurrency quota."""

    def __init__(self, tenant: str, limit: str) -> None:
        super().__init__(f"tenant {tenant!r} exceeded {limit}")
        self.tenant = tenant
        self.limit = limit
