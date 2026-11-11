"""Load manifests and build the immutable published record."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..core import AgentManifest, PublishedAgent, manifest_digest


def load_manifest(path: str | Path) -> AgentManifest:
    """Parse and validate an ``AgentManifest`` JSON file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return AgentManifest.model_validate(data)


def published_from(manifest: AgentManifest, *, now: datetime | None = None) -> PublishedAgent:
    """Build the registry record. The signature is an integrity marker in M1."""
    digest = manifest_digest(manifest)
    return PublishedAgent(
        manifest=manifest,
        digest=digest,
        signature=f"sha256:{digest}",
        published_at=now or datetime.now(timezone.utc),
    )
