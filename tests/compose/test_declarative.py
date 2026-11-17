"""SLICE-123: declarative composition from controlled templates."""

from __future__ import annotations

import io
import zipfile

import pytest

from adk_agent.compose import (
    InvalidComposition,
    UnknownTemplate,
    build_composed,
    list_templates,
)
from adk_agent.core import ToolGrant
from adk_agent.registry.artifacts import artifact_digest

_TEMPLATE = "single-llm"


def _build(**overrides):
    params = {
        "template_id": _TEMPLATE,
        "name": "assistant",
        "version": "1.0.0",
        "tenant": "acme",
        "instruction": "Be helpful.",
    }
    params.update(overrides)
    return build_composed(**params)


def test_unknown_template_and_parameters_are_rejected():
    with pytest.raises(UnknownTemplate):
        _build(template_id="nope")
    with pytest.raises(InvalidComposition):
        _build(surprise="value")


@pytest.mark.parametrize("name", ["my-agent", "1agent", "", "with space"])
def test_agent_name_must_be_adk_safe(name):
    with pytest.raises(InvalidComposition):
        _build(name=name)


def test_unknown_tool_is_rejected():
    with pytest.raises(InvalidComposition):
        _build(tools=("shell",))
    with pytest.raises(InvalidComposition):
        _build(tools=("ping", "ping"))


def test_composition_is_deterministic():
    first_manifest, first = _build()
    second_manifest, second = _build()

    assert first == second
    assert first_manifest == second_manifest
    assert artifact_digest(first) == artifact_digest(second)

    _, changed = _build(instruction="Be very helpful.")
    assert artifact_digest(changed) != artifact_digest(first)


def test_instruction_cannot_escape_the_template(monkeypatch):
    monkeypatch.setenv("ADK_AGENT_MODEL", "gemini:gemini-2.5-pro")
    instruction = "'''triple''' \"\"\"double\"\"\"\nback\\slash\r\ntail"

    _, data = _build(instruction=instruction)

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        source = archive.read("agent.py").decode("utf-8")

    namespace: dict[str, object] = {}
    exec(compile(source, "<composed-agent>", "exec"), namespace)

    agent = namespace["agent"]
    assert agent.instruction == instruction
    assert agent.name == "assistant"


def test_manifest_carries_tools_and_data_classes():
    manifest, _ = _build(
        tools=("ping",),
        data_classes=("internal", "public", "internal"),
    )

    assert manifest.exposure == "none"
    assert manifest.execution_tier == "in_process"
    assert manifest.model_policy.provider_allowlist == ["litellm"]
    assert manifest.tool_grants == [
        ToolGrant(tool_id="ping", data_classes=["internal", "public", "internal"])
    ]
    assert manifest.data_scopes == ["internal", "public"]

    plain, _ = _build()
    assert plain.tool_grants == []
    assert plain.data_scopes == []


def test_templates_are_discoverable():
    templates = list_templates()

    assert [template.template_id for template in templates] == [_TEMPLATE]
    single = templates[0]
    assert single.tools == ["ping"]
    required = {param.name: param.required for param in single.parameters}
    assert required == {
        "name": True,
        "version": True,
        "tenant": True,
        "owner": False,
        "description": False,
        "instruction": True,
        "tools": False,
        "data_classes": False,
    }
