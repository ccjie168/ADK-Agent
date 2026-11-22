"""Capability identifiers (ADR-0038, layer 2)."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

CapabilityId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")]
