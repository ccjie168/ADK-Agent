"""Model call shapes shared by the gateway and providers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str


class ModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    messages: list[Message] = Field(min_length=1)
    max_output_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0, le=2)


class EmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    texts: list[str] = Field(min_length=1)


class EmbeddingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    vectors: list[list[float]] = Field(min_length=1)
    model: str = Field(min_length=1)
    input_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    egress: Literal["none", "third_party"] = "third_party"


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    egress: Literal["none", "third_party"]
