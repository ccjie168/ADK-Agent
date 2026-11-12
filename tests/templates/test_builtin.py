"""SLICE-015: built-in templates render valid projects."""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

from adk_agent.core import AgentManifest
from adk_agent.templates import BuiltinTemplateSource, TemplateNotFound


def _render(template: str = "minimal", name: str = "support-bot", tenant: str = "local"):
    params = {"name": name, "tenant": tenant}
    return asyncio.run(BuiltinTemplateSource().render(template, params))


def test_render_minimal_project():
    files = _render()
    assert set(files) == {"agent.py", "manifest.json", "README.md", "tests/test_agent.py"}
    assert "LlmAgent" in files["agent.py"]
    assert "support-bot" in files["agent.py"]


def test_rendered_manifest_is_valid():
    files = _render()
    manifest = AgentManifest.model_validate(json.loads(files["manifest.json"]))
    assert manifest.id == "support-bot"
    assert manifest.version == "0.1.0"
    assert manifest.tenant == "local"
    assert manifest.model_policy.provider_allowlist == ["litellm"]


def test_rendered_manifest_uses_requested_tenant():
    files = _render(tenant="acme")
    manifest = AgentManifest.model_validate(json.loads(files["manifest.json"]))
    assert manifest.tenant == "acme"


def test_unknown_template_is_rejected():
    with pytest.raises(TemplateNotFound):
        _render("nope")


def test_unsafe_name_is_rejected():
    with pytest.raises(ValidationError):
        _render(name="../evil")
