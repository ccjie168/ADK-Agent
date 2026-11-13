"""Resolve ``TENANT/ID@VERSION`` references into verified agents."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from ..core import AgentRef, AgentRegistry, ArtifactStore
from .loader import ArtifactLoadError, InProcessArtifactLoader, load_agent
from .trust import TrustStore

_SAFE_NAME = r"[A-Za-z0-9][A-Za-z0-9._+-]*"
_REF = re.compile(rf"^(?P<tenant>{_SAFE_NAME})/(?P<id>{_SAFE_NAME})@(?P<version>{_SAFE_NAME})$")


class RefError(ValueError):
    """An agent reference is malformed or resolves to a duplicate name."""


def parse_agent_ref(text: str) -> tuple[str, str, str]:
    """Split ``TENANT/ID@VERSION`` into its three safe name parts."""
    match = _REF.fullmatch(text)
    if match is None:
        raise RefError(f"invalid agent ref: {text!r}")
    return match.group("tenant"), match.group("id"), match.group("version")


async def load_registry_agents(
    refs: Iterable[str],
    *,
    registry: AgentRegistry,
    store: ArtifactStore,
    trust: TrustStore,
    loader: InProcessArtifactLoader | None = None,
) -> dict[str, Any]:
    """Load each published reference, verifying trust, keyed by agent name."""
    artifact_loader = loader or InProcessArtifactLoader()
    agents: dict[str, Any] = {}
    for text in refs:
        tenant, agent_id, version = parse_agent_ref(text)
        records = await registry.list(tenant)
        record = next(
            (
                item
                for item in records
                if item.manifest.id == agent_id and item.manifest.version == version
            ),
            None,
        )
        if record is None:
            raise ArtifactLoadError(f"agent version not found: {text}")
        ref = AgentRef(
            id=record.manifest.id,
            version=record.manifest.version,
            digest=record.digest,
            artifact_digest=record.artifact.digest if record.artifact else None,
        )
        agent = await load_agent(
            registry=registry,
            ref=ref,
            tenant=tenant,
            store=store,
            loader=artifact_loader,
            trust=trust,
        )
        if agent.name in agents:
            raise RefError(f"duplicate agent name: {agent.name}")
        agents[agent.name] = agent
    return agents


__all__ = ["RefError", "load_registry_agents", "parse_agent_ref"]
