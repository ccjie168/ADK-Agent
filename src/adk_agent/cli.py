"""Command line entry point: ``adk-agent serve|new``."""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path
from typing import Literal, cast

Transport = Literal["stdio", "streamable-http"]

_AGENT_TEMPLATE = '''"""ADK agent: {name}."""

from google.adk.agents import LlmAgent

from adk_agent import build_model, serve_agent


def ping(text: str) -> str:
    """Echo the given text back."""
    return text


agent = LlmAgent(
    name="{name}",
    model=build_model(),
    description="{name} agent.",
    instruction="You are a helpful assistant.",
    tools=[ping],
)


if __name__ == "__main__":
    serve_agent(agent, transport="stdio")
'''


def _load_module(path: str):
    file = Path(path).resolve()
    if not file.is_file():
        raise SystemExit(f"agent file not found: {file}")

    spec = importlib.util.spec_from_file_location("adk_agent_user_module", file)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_agent(path: str):
    """Load ``agent`` (or ``root_agent``) from a Python file path."""
    module = _load_module(path)
    for attr in ("agent", "root_agent"):
        if hasattr(module, attr):
            return getattr(module, attr)
    raise SystemExit(f"no `agent` or `root_agent` found in {path}")


def _load_agents(path: str) -> dict:
    """Load an ``agents`` name -> agent mapping from a Python file path."""
    module = _load_module(path)
    agents = getattr(module, "agents", None)
    if not isinstance(agents, dict) or not agents:
        raise SystemExit(f"no non-empty `agents` dict found in {path}")
    return agents


def _scaffold(name: str) -> None:
    target = Path(name)
    target.mkdir(parents=True, exist_ok=True)
    agent_file = target / "agent.py"
    if agent_file.exists():
        raise SystemExit(f"{agent_file} already exists")
    agent_file.write_text(_AGENT_TEMPLATE.format(name=target.name), encoding="utf-8")
    print(f"created {agent_file}")


def _add_http_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="HTTP bind port (defaults to $PORT, then 8000)",
    )
    parser.add_argument(
        "--auth-token-env",
        default="ADK_MCP_AUTH_TOKEN",
        help="env var holding the bearer token (never pass tokens on the command line)",
    )
    parser.add_argument(
        "--allow-unauthenticated",
        action="store_true",
        help="allow no auth on a loopback host (dev only)",
    )


def _auth_token(args: argparse.Namespace) -> str | None:
    env_name = getattr(args, "auth_token_env", None)
    return os.environ.get(env_name) if env_name else None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="adk-agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="serve an ADK agent over MCP")
    p_serve.add_argument("--agent", default=None, help="path to a Python file defining `agent`")
    p_serve.add_argument("--config", default=None, help="path to a JSON FrameworkConfig file")
    p_serve.add_argument("--name", default=None, help="MCP tool name (defaults to the agent name)")
    p_serve.add_argument(
        "--transport",
        default=None,
        choices=["stdio", "streamable-http"],
        help="MCP transport to run on (defaults to the config value, else stdio)",
    )
    _add_http_args(p_serve)

    p_many = sub.add_parser("serve-many", help="serve several agents as separate MCP tools")
    p_many.add_argument(
        "--agents",
        required=True,
        help="path to a Python file defining an `agents` dict (name -> agent)",
    )
    p_many.add_argument("--name", default="adk_agents", help="MCP server name")
    p_many.add_argument(
        "--transport",
        default=None,
        choices=["stdio", "streamable-http"],
        help="MCP transport to run on (defaults to stdio)",
    )
    _add_http_args(p_many)

    p_new = sub.add_parser("new", help="scaffold a new agent project")
    p_new.add_argument("name", help="directory / agent name")

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        from .mcp.server import serve_agent

        if args.config:
            from .config import load_config
            from .factory import build_agent

            cfg = load_config(args.config)
            if not cfg.expose:
                raise SystemExit("config has no `expose` agent")
            agent = build_agent(cfg.agents[cfg.expose])
            name = args.name or cfg.expose
            transport = args.transport or cfg.transport
        elif args.agent:
            agent = _load_agent(args.agent)
            name = args.name
            transport = args.transport or "stdio"
        else:
            raise SystemExit("provide --agent <file> or --config <file>")

        serve_agent(
            agent,
            name=name,
            transport=cast(Transport, transport),
            host=args.host,
            port=args.port,
            auth_token=_auth_token(args),
            allow_unauthenticated=args.allow_unauthenticated,
        )
    elif args.cmd == "serve-many":
        from .mcp.server import serve_many

        agents = _load_agents(args.agents)
        serve_many(
            agents,
            name=args.name,
            transport=cast(Transport, args.transport or "stdio"),
            host=args.host,
            port=args.port,
            auth_token=_auth_token(args),
            allow_unauthenticated=args.allow_unauthenticated,
        )
    elif args.cmd == "new":
        _scaffold(args.name)


if __name__ == "__main__":  # pragma: no cover
    main()
