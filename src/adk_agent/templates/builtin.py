"""Built-in project templates."""

from __future__ import annotations

import json
from collections.abc import Mapping
from string import Template

from ..core import AgentManifest, ModelPolicy, ToolGrant


class TemplateNotFound(Exception):
    """The requested template does not exist."""


_AGENT_PY = Template(
    '''"""ADK agent: $name."""

from google.adk.agents import LlmAgent

from adk_agent import build_model, serve_agent


def ping(text: str) -> str:
    """Echo the given text back."""
    return text


agent = LlmAgent(
    name="$name",
    model=build_model(),
    description="$name agent.",
    instruction="You are a helpful assistant.",
    tools=[ping],
)

root_agent = agent


if __name__ == "__main__":
    serve_agent(agent, transport="stdio")
'''
)

_README = Template(
    """# $name

Generated from the `minimal` template.

## Validate and publish

```bash
adk-agent validate manifest.json
adk-agent publish manifest.json
```

## Run

```bash
python -m adk_agent serve --agent agent.py
```

Set `ADK_AGENT_MODEL` or `GOOGLE_API_KEY` before running. See the main project
README for the supported model channels.
"""
)

_TEST = Template(
    '''"""Smoke test for $name."""

from agent import agent


def test_agent_name():
    assert agent.name == "$name"
'''
)


class BuiltinTemplateSource:
    """Render the bundled templates."""

    async def render(self, template_id: str, params: Mapping[str, str]) -> Mapping[str, str]:
        if template_id != "minimal":
            raise TemplateNotFound(f"unknown template {template_id!r}")
        name = params["name"]
        tenant = params.get("tenant", "local")
        manifest = AgentManifest(
            id=name,
            version="0.1.0",
            tenant=tenant,
            owner="change-me",
            description=f"{name} agent.",
            model_policy=ModelPolicy(provider_allowlist=["litellm"]),
            tool_grants=[ToolGrant(tool_id="ping", data_classes=["internal"])],
            data_scopes=["internal"],
            exposure="none",
        )
        return {
            "agent.py": _AGENT_PY.substitute(name=name),
            "manifest.json": json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n",
            "README.md": _README.substitute(name=name),
            "tests/test_agent.py": _TEST.substitute(name=name),
        }
