"""Command line entry point: ``adk-agent serve|new``."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import re
import sys
import uuid
from functools import partial
from pathlib import Path
from typing import Literal, cast

Transport = Literal["stdio", "streamable-http"]

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")


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
    """Load an ``agents`` mapping, or wrap a single ``agent``/``root_agent``."""
    module = _load_module(path)
    agents = getattr(module, "agents", None)
    if isinstance(agents, dict) and agents:
        return agents
    for attr in ("agent", "root_agent"):
        candidate = getattr(module, attr, None)
        if candidate is not None:
            return {candidate.name: candidate}
    raise SystemExit(f"no `agents` dict or `agent`/`root_agent` found in {path}")


def _scaffold(name: str, template: str = "minimal", tenant: str = "local") -> None:
    if not _NAME.fullmatch(name):
        print(f"invalid agent name: {name!r}", file=sys.stderr)
        raise SystemExit(1)
    if not _NAME.fullmatch(tenant):
        print(f"invalid tenant name: {tenant!r}", file=sys.stderr)
        raise SystemExit(1)

    from .templates import BuiltinTemplateSource, TemplateNotFound

    source = BuiltinTemplateSource()
    try:
        files = asyncio.run(source.render(template, {"name": name, "tenant": tenant}))
    except TemplateNotFound as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None

    target = Path(name)
    if (target / "agent.py").exists():
        print(f"{target / 'agent.py'} already exists", file=sys.stderr)
        raise SystemExit(1)

    target.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"created {path}")


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


def _add_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--session-db",
        default=os.environ.get("SESSION_DB"),
        help="SQLite session DB path (defaults to $SESSION_DB; omit for in-memory)",
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
    _add_runtime_args(p_serve)

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
    _add_runtime_args(p_many)

    p_a2a = sub.add_parser("serve-a2a", help="serve an ADK agent over A2A (needs a2a-sdk)")
    p_a2a.add_argument("--agent", required=True, help="path to a Python file defining `agent`")
    p_a2a.add_argument(
        "--rpc-path",
        default="",
        help="mount the RPC and agent-card routes under this path prefix",
    )
    _add_http_args(p_a2a)

    p_gateway = sub.add_parser(
        "serve-model-gateway", help="serve the model gateway as a standalone service"
    )
    p_gateway.add_argument(
        "--provider",
        action="append",
        dest="providers",
        default=None,
        help="provider to serve, repeatable (default: litellm)",
    )
    p_gateway.add_argument(
        "--vllm-url", default=None, help="vLLM base URL (defaults to $VLLM_BASE_URL)"
    )
    p_gateway.add_argument("--audit-file", default=None, help="append JSONL audit events here")
    _add_http_args(p_gateway)

    p_console = sub.add_parser("console", help="serve a private web console for agents")
    p_console.add_argument(
        "--agents",
        required=True,
        help="path to a Python file defining an `agents` dict (name -> agent)",
    )
    p_console.add_argument(
        "--policy",
        default=None,
        help="path to an AccessPolicy JSON file (enables RBAC and /api/policy)",
    )
    p_console.add_argument(
        "--role",
        action="append",
        dest="roles",
        default=None,
        help="role for the console principal (repeatable; default: admin)",
    )
    _add_http_args(p_console)
    _add_runtime_args(p_console)

    p_new = sub.add_parser("new", help="scaffold a new agent project")
    p_new.add_argument("name", help="agent name, created as a directory")
    p_new.add_argument(
        "--template",
        default="minimal",
        help="template id (default: minimal)",
    )
    p_new.add_argument(
        "--tenant",
        default="local",
        help="tenant the agent belongs to (default: local)",
    )

    p_validate = sub.add_parser("validate", help="validate an agent manifest")
    p_validate.add_argument("path", help="path to an AgentManifest JSON file")

    p_publish = sub.add_parser("publish", help="publish an agent manifest")
    p_publish.add_argument("path", help="path to an AgentManifest JSON file")
    p_publish.add_argument(
        "--registry",
        default=os.environ.get("ADK_REGISTRY_DIR", "registry"),
        help="registry directory (defaults to $ADK_REGISTRY_DIR, then ./registry)",
    )
    p_publish.add_argument(
        "--eval-report",
        default=None,
        help="path to an EvalReport JSON file (required when the manifest declares eval_suite)",
    )

    p_eval = sub.add_parser("eval", help="run an eval suite against agents")
    p_eval.add_argument("suite", help="path to an EvalSuiteSpec JSON file")
    p_eval.add_argument(
        "--agents",
        required=True,
        help="path to a Python file defining an `agents` dict (name -> agent)",
    )
    p_eval.add_argument(
        "--out",
        default=None,
        help="write the report JSON here (defaults to stdout)",
    )

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

        from .factory import build_runner

        serve_agent(
            agent,
            name=name,
            transport=cast(Transport, transport),
            host=args.host,
            port=args.port,
            auth_token=_auth_token(args),
            allow_unauthenticated=args.allow_unauthenticated,
            runner=build_runner(agent, args.session_db),
        )
    elif args.cmd == "serve-many":
        from .factory import build_runner
        from .mcp.server import serve_many

        agents = _load_agents(args.agents)
        runner_factory = (
            partial(build_runner, session_db=args.session_db) if args.session_db else None
        )
        serve_many(
            agents,
            name=args.name,
            transport=cast(Transport, args.transport or "stdio"),
            host=args.host,
            port=args.port,
            auth_token=_auth_token(args),
            allow_unauthenticated=args.allow_unauthenticated,
            runner_factory=runner_factory,
        )
    elif args.cmd == "serve-a2a":
        from .a2a import A2aUnavailable, serve_a2a

        agent = _load_agent(args.agent)
        try:
            serve_a2a(
                agent,
                host=args.host,
                port=args.port,
                rpc_path=args.rpc_path,
                auth_token=_auth_token(args),
                allow_unauthenticated=args.allow_unauthenticated,
            )
        except A2aUnavailable as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None
    elif args.cmd == "serve-model-gateway":
        from .audit import JsonlAuditSink
        from .mcp.http import resolve_port
        from .models.gateway import PolicyModelGateway
        from .models.service import build_model_gateway_app, build_providers

        try:
            providers = build_providers(args.providers or ["litellm"], vllm_url=args.vllm_url)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None

        sink = JsonlAuditSink(args.audit_file) if args.audit_file else None
        app = build_model_gateway_app(
            PolicyModelGateway(providers, audit=sink),
            host=args.host,
            auth_token=_auth_token(args),
            allow_unauthenticated=args.allow_unauthenticated,
        )

        import uvicorn

        uvicorn.run(app, host=args.host, port=resolve_port(args.port), log_level="info")
    elif args.cmd == "console":
        from .console import run_console

        agents = _load_agents(args.agents)
        run_console(
            agents,
            host=args.host,
            port=args.port,
            auth_token=_auth_token(args),
            allow_unauthenticated=args.allow_unauthenticated,
            session_db=args.session_db,
            policy_file=args.policy,
            roles=args.roles,
        )
    elif args.cmd == "validate":
        from .core import manifest_digest
        from .registry import load_manifest

        try:
            manifest = load_manifest(args.path)
        except Exception as exc:  # noqa: BLE001
            print(f"invalid manifest: {exc}", file=sys.stderr)
            raise SystemExit(1) from None
        print(
            f"{manifest.tenant}/{manifest.id}@{manifest.version} sha256:{manifest_digest(manifest)}"
        )
    elif args.cmd == "publish":
        from .core import EvalReport
        from .eval import enforce_eval_gate
        from .registry import FileAgentRegistry, load_manifest, published_from

        try:
            manifest = load_manifest(args.path)
            report = (
                EvalReport.model_validate_json(Path(args.eval_report).read_text(encoding="utf-8"))
                if args.eval_report
                else None
            )
            enforce_eval_gate(manifest, report)
            registry = FileAgentRegistry(args.registry)
            stored = asyncio.run(registry.publish(published_from(manifest)))
        except Exception as exc:  # noqa: BLE001
            print(f"publish failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from None
        print(
            f"published {stored.manifest.tenant}/{stored.manifest.id}@{stored.manifest.version} "
            f"sha256:{stored.digest}"
        )
    elif args.cmd == "eval":
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService

        from .core import EvalSuiteSpec, Invocation, InvocationResult, Principal
        from .eval import EvalRunner
        from .runtime import AgentRuntime, dev_agent_ref

        suite = EvalSuiteSpec.model_validate_json(Path(args.suite).read_text(encoding="utf-8"))
        agents = _load_agents(args.agents)
        target = agents.get(suite.agent)
        if target is None:
            print(f"unknown agent: {suite.agent!r}", file=sys.stderr)
            raise SystemExit(1)

        service = InMemorySessionService()
        runtime = AgentRuntime(Runner(app_name=suite.agent, agent=target, session_service=service))

        async def call(invocation: Invocation) -> InvocationResult:
            session = await service.create_session(app_name=suite.agent, user_id="eval")
            return await runtime.run(invocation, user_id="eval", session_id=str(session.id))

        invocation = Invocation(
            run_id=uuid.uuid4().hex,
            trace_id=uuid.uuid4().hex,
            principal=Principal(tenant="local", subject="eval", kind="service"),
            agent_ref=dev_agent_ref(suite.agent),
            input="",
        )
        report = asyncio.run(EvalRunner(call).run(suite, invocation))
        payload = report.model_dump_json(indent=2) + "\n"
        if args.out:
            Path(args.out).write_text(payload, encoding="utf-8")
            print(f"wrote {args.out}")
        else:
            print(payload, end="")
    elif args.cmd == "new":
        _scaffold(args.name, args.template, args.tenant)


if __name__ == "__main__":  # pragma: no cover
    main()
