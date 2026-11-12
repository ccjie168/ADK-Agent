"""Deterministic eval suites and reports."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    input: str = Field(min_length=1)
    expected: str = Field(min_length=1)
    match: Literal["exact", "contains"] = "contains"


class EvalSuiteSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    agent: str = Field(min_length=1)
    cases: list[EvalCase] = Field(min_length=1)


class EvalCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    passed: bool
    actual: str = ""
    error: str | None = None


class EvalReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    passed: int = Field(ge=0)
    total: int = Field(gt=0)
    results: list[EvalCaseResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def _counts_consistent(self) -> EvalReport:
        if self.passed > self.total:
            raise ValueError("passed cannot exceed total")
        return self

    @property
    def score(self) -> float:
        return self.passed / self.total
