"""Verified in-process artifact loading (ADR-0008)."""

from __future__ import annotations

import hashlib
import io
import stat
import uuid
import zipfile
from pathlib import PurePosixPath
from typing import Any

from ..core import MAX_ARTIFACT_BYTES, AgentArtifact, AgentManifest, ArtifactStore
from ..sandbox.agent import require_execution_supported
from .trust import TrustStore

_ALLOWED = frozenset({"manifest.json", "README.md", "requirements.txt"})
_MAX_ENTRIES = 64


class ArtifactLoadError(RuntimeError):
    """The artifact cannot be turned into a runnable agent."""


def _check_entries(archive: zipfile.ZipFile, entrypoint: str) -> None:
    infos = archive.infolist()
    if len(infos) > _MAX_ENTRIES:
        raise ArtifactLoadError("artifact has too many files")
    names: set[str] = set()
    total = 0
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        if not name or "\\" in name or path.is_absolute() or ".." in path.parts:
            raise ArtifactLoadError("artifact contains an unsafe path")
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ArtifactLoadError("artifact contains a symbolic link")
        if name not in _ALLOWED and name != entrypoint:
            raise ArtifactLoadError("artifact contains an unexpected file")
        if name in names:
            raise ArtifactLoadError("artifact contains duplicate entries")
        names.add(name)
        total += info.file_size
        if total > MAX_ARTIFACT_BYTES:
            raise ArtifactLoadError("artifact expands past the 8 MiB limit")
    if "manifest.json" not in names:
        raise ArtifactLoadError("artifact has no manifest.json")
    if entrypoint not in names:
        raise ArtifactLoadError("artifact has no entrypoint")


class InProcessArtifactLoader:
    """Verify bytes, read the entrypoint, and execute it in this process."""

    async def load(self, artifact: AgentArtifact, store: ArtifactStore) -> Any:
        data = await store.get(artifact.digest)
        if data is None:
            raise ArtifactLoadError("artifact bytes not found")
        _, hexdigest = artifact.digest.split(":", 1)
        if len(data) != artifact.size or hashlib.sha256(data).hexdigest() != hexdigest:
            raise ArtifactLoadError("artifact bytes do not match the declared digest")
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise ArtifactLoadError("artifact is not a zip") from exc
        with archive:
            _check_entries(archive, artifact.entrypoint)
            try:
                manifest = AgentManifest.model_validate_json(archive.read("manifest.json"))
            except Exception as exc:  # noqa: BLE001
                raise ArtifactLoadError("artifact manifest is invalid") from exc
            source = archive.read(artifact.entrypoint)
        namespace: dict[str, Any] = {"__name__": f"_adk_artifact_{uuid.uuid4().hex}"}
        try:
            exec(  # nosec B102  # executing signed artifact code is the loader's purpose
                compile(source, f"<artifact:{artifact.digest}>/{artifact.entrypoint}", "exec"),
                namespace,
            )
        except Exception as exc:  # noqa: BLE001
            raise ArtifactLoadError(
                f"artifact module failed to load ({type(exc).__name__})"
            ) from exc
        agent = namespace.get("agent")
        if agent is None:
            agent = namespace.get("root_agent")
        if agent is None:
            raise ArtifactLoadError("artifact module exposes no agent")
        from google.adk.agents import BaseAgent

        if not isinstance(agent, BaseAgent):
            raise ArtifactLoadError("artifact agent is not an ADK agent")
        if agent.name != manifest.id:
            raise ArtifactLoadError("artifact agent name does not match the manifest")
        return agent


async def load_agent(
    *,
    registry: Any,
    ref: Any,
    tenant: str,
    store: ArtifactStore,
    loader: InProcessArtifactLoader,
    trust: TrustStore,
) -> Any:
    """Load a published version by reference, verifying trust first."""
    published = await registry.get(ref, tenant)
    if published is None:
        raise ArtifactLoadError("agent version not found")
    require_execution_supported(published.manifest)
    if published.artifact is None:
        raise ArtifactLoadError("agent version has no artifact")
    trust.verify(published.artifact)
    return await loader.load(published.artifact, store)


__all__ = ["ArtifactLoadError", "InProcessArtifactLoader", "load_agent"]
