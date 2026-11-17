"""Declarative agent composition from controlled templates (ADR-0022)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any, cast

from pydantic import BaseModel, ConfigDict

from ..core import (
    AgentArtifact,
    AgentManifest,
    DataClass,
    ModelPolicy,
    PublishedAgent,
    ToolGrant,
)
from ..eval import enforce_eval_gate
from ..registry import RegistryConflict, pack_files, published_from, sign_digest
from ..registry.artifacts import artifact_digest

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_TOOL_IDS = frozenset({"ping"})
_MAX_INSTRUCTION = 4000


class ComposeError(Exception):
    """A composition cannot be built or published."""


class UnknownTemplate(ComposeError):
    """The requested template id is not defined by the platform."""


class InvalidComposition(ComposeError):
    """The supplied parameters cannot produce a loadable agent."""


class TemplateParameter(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    description: str
    required: bool
    default: Any = None


class TemplateInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    template_id: str
    description: str
    parameters: list[TemplateParameter]
    tools: list[str]


def _parameter(
    name: str, description: str, *, required: bool, default: Any = None
) -> TemplateParameter:
    return TemplateParameter(name=name, description=description, required=required, default=default)


def list_templates() -> list[TemplateInfo]:
    """Return the platform templates and their accepted parameters."""
    return [
        TemplateInfo(
            template_id="single-llm",
            description="Single LlmAgent with optional built-in ping tool",
            parameters=[
                _parameter("name", "agent id, ADK-safe", required=True),
                _parameter("version", "version string", required=True),
                _parameter("tenant", "tenant", required=True),
                _parameter("owner", "owner label", required=False),
                _parameter("description", "agent description", required=False),
                _parameter("instruction", "system instruction", required=True),
                _parameter("tools", "subset of [ping]", required=False, default=[]),
                _parameter(
                    "data_classes", "data classes for tool grants", required=False, default=[]
                ),
            ],
            tools=["ping"],
        )
    ]


def _selected_tools(tools: Iterable[str]) -> list[str]:
    selected = list(tools)
    if len(selected) != len(set(selected)):
        raise InvalidComposition("tools must not contain duplicates")
    unknown = sorted(set(selected) - _TOOL_IDS)
    if unknown:
        raise InvalidComposition(f"unknown tools: {', '.join(unknown)}")
    return selected


def _render_agent(name: str, description: str, instruction: str, tools: Iterable[str]) -> str:
    ping = (
        'def ping(text: str) -> str:\n    """Echo the given text back."""\n    return text\n\n\n'
        if "ping" in tools
        else ""
    )
    tool_list = "tools=[ping]," if "ping" in tools else "tools=[],"
    return (
        '"""ADK agent generated from the single-llm template."""\n\n'
        "from google.adk.agents import LlmAgent\n\n"
        "from adk_agent import build_model\n\n\n"
        f"{ping}"
        "agent = LlmAgent(\n"
        f"    name={name!r},\n"
        "    model=build_model(),\n"
        f"    description={description!r},\n"
        f"    instruction={instruction!r},\n"
        f"    {tool_list}\n"
        ")\n\n"
        "root_agent = agent\n"
    )


def build_composed(
    *,
    template_id: str,
    name: str,
    version: str,
    tenant: str,
    owner: str | None = None,
    description: str | None = None,
    instruction: str,
    tools: Iterable[str] = (),
    data_classes: Iterable[str] = (),
    **unexpected: object,
) -> tuple[AgentManifest, bytes]:
    """Render a manifest and deterministic artifact from template parameters."""
    if unexpected:
        raise InvalidComposition(f"unknown parameters: {', '.join(sorted(unexpected))}")
    if template_id != "single-llm":
        raise UnknownTemplate(f"unknown template {template_id!r}")
    if not _NAME.fullmatch(name):
        raise InvalidComposition(f"agent name {name!r} is not ADK-safe")
    if not instruction:
        raise InvalidComposition("instruction must not be empty")
    if len(instruction) > _MAX_INSTRUCTION:
        raise InvalidComposition(f"instruction exceeds {_MAX_INSTRUCTION} characters")

    selected = _selected_tools(tools)
    classes = list(data_classes)
    resolved_owner = tenant if owner is None else owner
    resolved_description = f"{name} agent." if description is None else description

    manifest = AgentManifest(
        id=name,
        version=version,
        tenant=tenant,
        owner=resolved_owner,
        description=resolved_description,
        model_policy=ModelPolicy(provider_allowlist=["litellm"]),
        tool_grants=(
            [ToolGrant(tool_id="ping", data_classes=cast("list[DataClass]", classes))]
            if "ping" in selected
            else []
        ),
        data_scopes=(cast("list[DataClass]", sorted(set(classes))) if selected else []),
        exposure="none",
        execution_tier="in_process",
    )
    agent_py = _render_agent(name, resolved_description, instruction, selected)
    manifest_json = json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    data = pack_files(
        {
            "manifest.json": manifest_json.encode("utf-8"),
            "agent.py": agent_py.encode("utf-8"),
        }
    )
    return manifest, data


async def compose_and_publish(
    *,
    template_id: str,
    name: str,
    version: str,
    tenant: str,
    owner: str | None = None,
    description: str | None = None,
    instruction: str,
    tools: Iterable[str] = (),
    data_classes: Iterable[str] = (),
    registry: Any,
    artifact_store: Any | None = None,
    private_key: Any,
    key_id: str,
    builder_key: Any | None = None,
    builder_key_id: str | None = None,
    now: datetime | None = None,
) -> PublishedAgent:
    """Build, sign, publish, and store a composed agent version."""
    manifest, data = build_composed(
        template_id=template_id,
        name=name,
        version=version,
        tenant=tenant,
        owner=owner,
        description=description,
        instruction=instruction,
        tools=tools,
        data_classes=data_classes,
    )
    enforce_eval_gate(manifest, None)
    if builder_key is None or builder_key_id is None:
        raise ComposeError("composed artifacts are in_process and require a builder key")

    digest = artifact_digest(data)
    artifact = AgentArtifact(
        digest=digest,
        size=len(data),
        signature=sign_digest(digest, private_key),
        key_id=key_id,
        builder_signature=(sign_digest(digest, builder_key) if builder_key is not None else None),
        builder_key_id=builder_key_id if builder_key is not None else None,
    )
    published = published_from(manifest, artifact=artifact, now=now)
    stored = await registry.publish(published)
    if stored.artifact is None or stored.artifact.digest != artifact.digest:
        raise RegistryConflict(
            f"{tenant}/{name}@{version} is already published with a different artifact"
        )

    if artifact_store is not None:
        await artifact_store.put(artifact, data)
    elif hasattr(registry, "upload_artifact"):
        await registry.upload_artifact(artifact, data)
    else:
        raise ComposeError("no artifact destination")
    return stored


__all__ = [
    "ComposeError",
    "InvalidComposition",
    "TemplateInfo",
    "TemplateParameter",
    "UnknownTemplate",
    "build_composed",
    "compose_and_publish",
    "list_templates",
]
