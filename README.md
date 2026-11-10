# adk-agent

A reusable multi-agent application framework built on
[Google ADK](https://adk.dev), with **bidirectional MCP integration**:

- **Incoming** — ADK agents consume tools from any MCP server
  (`McpToolset`): filesystem, git, databases, web, internal services.
- **Outgoing** — an ADK agent is exposed as an MCP server
  (`to_mcp_server`), so **Claude Code** (or any MCP host) can drive it as a
  single tool.

The point: use **Claude Code as the development entry point**, and let it
delegate work to your ADK multi-agent applications over MCP.

```
Claude Code ── MCP (stdio/http) ──► adk-agent framework ── MCP ──► external MCP ecosystem
```

## Quickstart

```bash
# 1. isolated environment
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev,litellm]"

# 2. pick an LLM backend
#    (a) DeepSeek via its Anthropic-compatible endpoint - lightweight, no litellm:
export ADK_AGENT_MODEL=claude:deepseek-v4-pro
export ANTHROPIC_AUTH_TOKEN=sk-...
export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic

#    (b) DeepSeek via LiteLLM's OpenAI-compatible provider:
# export ADK_AGENT_MODEL=litellm:deepseek/deepseek-v4-pro
# export DEEPSEEK_API_KEY=sk-...

#    (c) Gemini (auto-selected when GOOGLE_API_KEY is present):
# export GOOGLE_API_KEY=...

# DeepSeek's /anthropic endpoint rejects `redacted_thinking` in history; keep
# thinking disabled for multi-turn: generate_content_config=disable_thinking().

# 3. run the minimal agent as an MCP server
.venv/Scripts/python.exe -m adk_agent serve --agent examples/minimal/agent.py
```

## Connect it to Claude Code

Project-scope MCP config lives in the project-root [`.mcp.json`](.mcp.json).
It pins `ADK_AGENT_MODEL=claude:deepseek-v4-pro` and expands
`ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` from the Claude Code environment,
so no secret is stored in the file.

After the dependencies are installed, **reload the VSCode window** (or restart
the session) so Claude Code picks up the new `.mcp.json`, then approve the
`adk-minimal` server (check with `/mcp`). You should then see a tool named
`minimal_agent` (referenced as `mcp__adk-minimal__minimal_agent`) and can ask
Claude Code to call it.

To use Gemini instead, change the `env` block in `.mcp.json` to
`"ADK_AGENT_MODEL": "gemini:gemini-2.5-pro"` and add `"GOOGLE_API_KEY": "${GOOGLE_API_KEY}"`.

Equivalent CLI form:

```bash
claude mcp add adk-minimal --scope project \
  -- C:/AI_System/ADK-Agent/.venv/Scripts/python.exe -m adk_agent serve \
  --agent C:/AI_System/ADK-Agent/examples/minimal/agent.py
```

## Library usage

```python
from google.adk.agents import LlmAgent
from adk_agent import build_model, serve_agent

agent = LlmAgent(
    name="my_agent",
    model=build_model("gemini:gemini-2.5-pro"),  # or "litellm:deepseek/deepseek-v4-pro"
    instruction="You are helpful.",
    tools=[],
)

serve_agent(agent, transport="stdio")  # or "streamable-http"
```

Consume an external MCP server from inside an ADK agent:

```python
from adk_agent.config import AgentConfig, McpServerConfig
from adk_agent.factory import build_agent

agent = build_agent(
    AgentConfig(
        name="fs_agent",
        instruction="Read files on request.",
        mcp_servers=[
            McpServerConfig(
                transport="stdio",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                tool_filter=["read_file", "list_directory"],
            )
        ],
    )
)
```

## Multi-agent

Two ways to expose a multi-agent app ([examples/multi_agent](examples/multi_agent)):

1. **Orchestrator as one tool** — an `LlmAgent` with `sub_agents`; Claude Code
   sees a single tool and delegation happens inside ADK.

   ```bash
   adk-agent serve --agent examples/multi_agent/agent.py
   ```

   Verified: `"What is 17 times 23?"` → orchestrator delegates to `math_agent`
   → `391`.

2. **Each agent as its own tool** — `serve_many` registers one MCP tool per agent.

   ```bash
   adk-agent serve-many --agents examples/multi_agent/agent.py
   ```

   Claude Code then sees `math_agent` and `time_agent` separately. Verified:
   `"What is 12 plus 30?"` on `math_agent` → `42`.

## Layout

```
src/adk_agent/
├─ config.py      pydantic schema (agent / model / mcp server)
├─ models.py      build_model(): Gemini | LiteLlm | Claude (lazy imports)
├─ factory.py     build_agent(): wire model + MCP toolsets + sub-agents
├─ mcp/client.py  toolset_from_config() -> McpToolset        (incoming)
├─ mcp/server.py  serve_agent() -> to_mcp_server + run      (outgoing)
└─ cli.py         adk-agent serve | new
examples/minimal/ minimal agent + project .mcp.json
```

## Development web UI

ADK ships a local web UI; no frontend code needed:

```bash
adk web examples/          # FastAPI + browser UI on http://127.0.0.1:8000
```

It auto-discovers the agent folders (`minimal`, `multi_agent`) — verified via
`/list-apps` → `["minimal","multi_agent"]`. Use it for chat and inspection
during development. A custom frontend is best deferred until the backend
surface (multi-agent orchestration, MCP in/out, transport) is stable.

## Engineering gate

This repo follows the Starter Kit baseline in
[docs/decisions/ADR-0001-project-baseline.md](docs/decisions/ADR-0001-project-baseline.md).

```bash
python scripts/check.py --fast          # format, lint, types, tests, secrets
python scripts/check.py --full          # + SAST (bandit), dependency audit (pip-audit)
python scripts/check.py --fast --strict # missing tools become failures
python scripts/negative_check.py        # S4: inject defects, prove the gate goes red
```

Tools are pinned in [requirements-dev.txt](requirements-dev.txt). Hard rules for
agents live in [CLAUDE.md](CLAUDE.md); slice and ADR templates are in
[docs/specs/](docs/specs/) and [docs/decisions/](docs/decisions/).

## Status

Phase 0 + Phase 1 are implemented and verified end-to-end:

- `pytest` — 6 passing (model factory, agent tree, config loading).
- `scripts/probe_mcp.py` — MCP handshake + tool listing over stdio; Claude Code
  will see one tool named after the agent (`minimal_agent`).
- `scripts/call_tool.py` — a real agent invocation through MCP. Verified against
  DeepSeek's Anthropic-compatible endpoint (`AnthropicLlm`): the model called the
  `get_time` tool and returned the answer.
- Multi-agent: orchestrator delegation (`17×23` → `391`) and `serve_many`
  (`12+30` → `42`), both through MCP.
- `adk web examples/` auto-discovers both example apps.

> Note: `google.adk.models.Claude` is the **Vertex AI** adapter; the plain
> Anthropic-API adapter (for `ANTHROPIC_BASE_URL` endpoints) is
> `google.adk.models.anthropic_llm.AnthropicLlm`. The `claude:` provider maps to
> the latter.

Next phases from the plan: config-driven multi-agent orchestration,
streamable-HTTP / Cloud Run, A2A interop, evaluation and tracing.

## Dev tools

```bash
# list the tools an MCP server publishes (no LLM call)
python scripts/probe_mcp.py -- .venv/Scripts/python.exe -m adk_agent serve \
  --agent examples/minimal/agent.py

# actually invoke the agent through MCP
python scripts/call_tool.py "What time is it?" -- .venv/Scripts/python.exe \
  -m adk_agent serve --agent examples/minimal/agent.py
```
