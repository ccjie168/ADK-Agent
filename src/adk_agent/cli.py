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
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.parse import urlsplit

if TYPE_CHECKING:  # pragma: no cover
    from .audit import AuditQuery, SigningKeyring
    from .core import AuditSink, IdentityProvider, QuotaConfig, QuotaManager
    from .ratelimit import RateLimit
    from .registry import TrustStore

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


def _artifact_trust(args: argparse.Namespace) -> TrustStore | None:
    """Build a trust store from ``--artifact-keys`` or ``$ADK_ARTIFACT_KEYS``."""
    from .registry import ArtifactTrustError, TrustStore

    keys_file = getattr(args, "artifact_keys", None)
    try:
        keys_text = (
            Path(keys_file).read_text(encoding="utf-8")
            if keys_file
            else os.environ.get("ADK_ARTIFACT_KEYS")
        )
    except OSError as exc:
        print(f"cannot read artifact keys: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    if not keys_text:
        return None
    try:
        return TrustStore.from_json(keys_text)
    except ArtifactTrustError as exc:
        print(f"invalid artifact keys: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


def _artifact_store(args: argparse.Namespace) -> Any:
    """Build the artifact store from ``--artifact-dir`` or ``$ARTIFACT_URL``."""
    from .registry import FileArtifactStore
    from .registry.artifacts_postgres import PostgresArtifactStore

    artifact_dir = getattr(args, "artifact_dir", None)
    url = os.environ.get("ARTIFACT_URL")
    if url and artifact_dir:
        print("set exactly one of --artifact-dir or ARTIFACT_URL", file=sys.stderr)
        raise SystemExit(1)
    if url:
        return PostgresArtifactStore(url)
    if artifact_dir:
        return FileArtifactStore(artifact_dir)
    return None


def _registry_agents(args: argparse.Namespace) -> dict[str, Any] | None:
    """Load agents named by ``--agent-ref`` from the registry."""
    refs = getattr(args, "agent_ref", None)
    if not refs:
        return None

    from .registry import (
        ArtifactLoadError,
        ArtifactStoreError,
        ArtifactTrustError,
        HttpAgentRegistry,
        PublishUnavailable,
        RefError,
        load_registry_agents,
    )

    trust = _artifact_trust(args)
    if trust is None:
        print(
            "artifact trust keys are required: provide --artifact-keys FILE "
            "or set ADK_ARTIFACT_KEYS",
            file=sys.stderr,
        )
        raise SystemExit(1)

    store = _artifact_store(args)
    if store is None:
        print("set exactly one of --artifact-dir or ARTIFACT_URL", file=sys.stderr)
        raise SystemExit(1)

    try:
        registry = _agent_registry(args)
        lifecycle = _lifecycle_source(args, registry)

        async def load():
            try:
                return await load_registry_agents(
                    refs,
                    registry=registry,
                    store=store,
                    trust=trust,
                    lifecycle=lifecycle,
                )
            finally:
                if isinstance(registry, HttpAgentRegistry):
                    await registry.aclose()

        return asyncio.run(load())
    except (
        RefError,
        ArtifactLoadError,
        ArtifactTrustError,
        ArtifactStoreError,
        PublishUnavailable,
    ) as exc:
        print(f"registry load failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


def _load_tools(path: str) -> Any:
    """Load a ``tools`` mapping of tool_id to callable or ``ToolSpec``."""
    from .tools import FunctionRegistry, ToolSpec

    module = _load_module(path)
    tools = getattr(module, "tools", None)
    if not isinstance(tools, dict) or not tools:
        raise SystemExit(f"no `tools` mapping found in {path}")
    specs = []
    for tool_id, value in tools.items():
        if isinstance(value, ToolSpec):
            specs.append(value)
        elif callable(value):
            specs.append(ToolSpec(tool_id=tool_id, handler=value))
        else:
            raise SystemExit(f"tool {tool_id!r} is not callable or a ToolSpec")
    return FunctionRegistry(specs)


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
        help=(
            "SQLite session DB path for single-node demos (defaults to $SESSION_DB); "
            "$SESSION_URL selects a shared Postgres store instead"
        ),
    )


def _add_rate_limit_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--rate-limit",
        type=int,
        default=None,
        help="max requests per caller per window (default: no limit)",
    )
    parser.add_argument(
        "--rate-limit-window",
        type=float,
        default=None,
        help="rate limit window in seconds (default: 60)",
    )


def _add_audit_args(parser: argparse.ArgumentParser) -> None:
    audit = parser.add_mutually_exclusive_group()
    audit.add_argument("--audit-file", default=None, help="append JSONL audit events here")
    audit.add_argument(
        "--audit-url", default=None, help="send audit events to this audit service URL"
    )
    parser.add_argument(
        "--audit-token-env",
        default="ADK_AUDIT_AUTH_TOKEN",
        help=(
            "env var holding the audit bearer token (only used with --audit-url; "
            "never pass tokens on the command line)"
        ),
    )


def _add_audit_quota_args(parser: argparse.ArgumentParser) -> None:
    _add_audit_args(parser)
    parser.add_argument("--quota-config", default=None, help="JSON QuotaConfig file")


def _auth_token(args: argparse.Namespace) -> str | None:
    env_name = getattr(args, "auth_token_env", None)
    return os.environ.get(env_name) if env_name else None


def _add_registry_client_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--registry-url",
        default=None,
        help="registry control-plane URL; when set, read metadata over HTTP",
    )
    parser.add_argument(
        "--registry-token-env",
        default="ADK_REGISTRY_AUTH_TOKEN",
        help="env var holding the registry bearer token (never pass tokens on the command line)",
    )


def _registry_token(args: argparse.Namespace) -> str | None:
    env_name = getattr(args, "registry_token_env", None) or "ADK_REGISTRY_AUTH_TOKEN"
    return os.environ.get(env_name)


def _lifecycle_source(args: argparse.Namespace, registry: Any = None) -> Any:
    from .registry import FileAgentLifecycleStore, HttpAgentLifecycleStore, HttpAgentRegistry

    if not getattr(args, "registry_url", None):
        return FileAgentLifecycleStore(args.registry)
    client = registry if isinstance(registry, HttpAgentRegistry) else _agent_registry(args)
    return HttpAgentLifecycleStore(client)


def _tool_catalog(args: argparse.Namespace) -> Any:
    path = getattr(args, "tool_catalog", None)
    if not path:
        return None
    from .tools import ToolCatalogError, load_tool_catalog

    try:
        return load_tool_catalog(path)
    except ToolCatalogError as exc:
        print(f"invalid tool catalog: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


def _agent_registry(args: argparse.Namespace) -> Any:
    """Return the HTTP registry client when a URL is set, else the file registry."""
    from .registry import FileAgentRegistry, HttpAgentRegistry

    url = getattr(args, "registry_url", None)
    if not url:
        return FileAgentRegistry(args.registry)
    if not url.startswith(("http://", "https://")):
        print(
            f"invalid --registry-url {url!r}: expected http:// or https://",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return HttpAgentRegistry(url, auth_token=_registry_token(args))


def _rate_limit(args: argparse.Namespace) -> RateLimit | None:
    limit = getattr(args, "rate_limit", None)
    window = getattr(args, "rate_limit_window", None)
    if limit is None:
        if window is not None:
            print("--rate-limit-window requires --rate-limit", file=sys.stderr)
            raise SystemExit(1)
        return None
    if limit <= 0:
        print("--rate-limit must be greater than 0", file=sys.stderr)
        raise SystemExit(1)
    window_seconds = 60.0 if window is None else window
    if window_seconds <= 0:
        print("--rate-limit-window must be greater than 0", file=sys.stderr)
        raise SystemExit(1)

    from .ratelimit import RateLimit

    return RateLimit(limit=limit, window_seconds=window_seconds)


def _identity_provider(args: argparse.Namespace) -> IdentityProvider | None:
    if not getattr(args, "oidc_config", None):
        return None
    if getattr(args, "allow_unauthenticated", False):
        print("oidc config cannot combine with allow_unauthenticated", file=sys.stderr)
        raise SystemExit(1)
    try:
        from .identity import OidcConfig, OidcIdentityProvider

        config = OidcConfig.model_validate_json(Path(args.oidc_config).read_text(encoding="utf-8"))
        return OidcIdentityProvider(config)
    except Exception as exc:  # noqa: BLE001
        print(f"invalid oidc config: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


def _audit_signing() -> tuple[str | None, SigningKeyring | None]:
    from .audit import KeyringError, SigningKeyring

    signing_key = os.environ.get("ADK_AUDIT_SIGNING_KEY")
    keyring_value = os.environ.get("ADK_AUDIT_KEYRING")
    if signing_key is not None and keyring_value is not None:
        print(
            "ADK_AUDIT_KEYRING and ADK_AUDIT_SIGNING_KEY cannot be set together",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if keyring_value is None:
        return signing_key, None
    try:
        keyring = SigningKeyring.from_env(keyring_value)
    except KeyringError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    return None, keyring


def _audit_sink(args: argparse.Namespace) -> AuditSink | None:
    from .audit import HttpAuditSink, JsonlAuditSink
    from .auth import LOOPBACK_HOSTS

    if args.audit_url:
        host = urlsplit(args.audit_url).hostname
        token = os.environ.get(args.audit_token_env) if args.audit_token_env else None
        if host not in LOOPBACK_HOSTS and token is None:
            raise SystemExit(
                f"refusing a non-loopback audit URL without a token: set "
                f"{args.audit_token_env} or use a loopback --audit-url"
            )
        return HttpAuditSink(args.audit_url, auth_token=token)
    if args.audit_file:
        return JsonlAuditSink(args.audit_file)
    return None


def _audit_query(args: argparse.Namespace) -> AuditQuery | None:
    from .audit import FileAuditQuery, HttpAuditQuery
    from .auth import LOOPBACK_HOSTS

    if args.audit_url:
        host = urlsplit(args.audit_url).hostname
        token = os.environ.get(args.audit_token_env) if args.audit_token_env else None
        if host not in LOOPBACK_HOSTS and token is None:
            print(
                f"refusing a non-loopback audit URL without a token: set "
                f"{args.audit_token_env} or use a loopback --audit-url",
                file=sys.stderr,
            )
            raise SystemExit(1)
        return HttpAuditQuery(args.audit_url, auth_token=token)
    if args.audit_file:
        return FileAuditQuery(args.audit_file)
    return None


def _publish_artifact(args: argparse.Namespace, manifest: Any) -> tuple[Any, bytes | None]:
    from .core import AgentArtifact
    from .registry import (
        FileArtifactStore,
        load_manifest,
        load_private_key,
        pack_agent,
        read_artifact_zip,
        sign_digest,
    )
    from .registry.artifacts import artifact_digest
    from .registry.artifacts_postgres import PostgresArtifactStore

    if args.artifact is None:
        if args.key is not None or args.key_id is not None or args.artifact_dir is not None:
            raise ValueError("--key, --key-id and --artifact-dir require --artifact")
        return None, None
    if not args.key or not args.key_id:
        raise ValueError("--artifact requires --key and --key-id")
    source = Path(args.artifact)
    if source.is_dir():
        data = pack_agent(source)
        inner = load_manifest(source / "manifest.json")
    else:
        data, inner = read_artifact_zip(source)
    if inner != manifest:
        raise ValueError("artifact manifest does not match the published manifest")
    url = os.environ.get("ARTIFACT_URL")
    if args.registry_url:
        if args.artifact_dir or url:
            raise ValueError("--artifact-dir and ARTIFACT_URL cannot be used with --registry-url")
    elif bool(args.artifact_dir) == bool(url):
        raise ValueError("set exactly one of --artifact-dir or ARTIFACT_URL")
    key = load_private_key(args.key)
    digest = artifact_digest(data)
    artifact = AgentArtifact(
        digest=digest,
        size=len(data),
        signature=sign_digest(digest, key),
        key_id=args.key_id,
    )
    if args.registry_url:
        return artifact, data
    store = PostgresArtifactStore(url) if url else FileArtifactStore(args.artifact_dir)
    asyncio.run(store.put(artifact, data))
    return artifact, None


def _quota_settings(
    args: argparse.Namespace,
) -> tuple[QuotaManager | None, QuotaConfig | None]:
    path = getattr(args, "quota_config", None)
    if not path:
        return None, None

    from .core import QuotaConfig

    try:
        config = QuotaConfig.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"invalid quota config: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

    from .runtime.quota_postgres import QuotaStoreUnavailable, build_quota_manager

    try:
        manager = build_quota_manager(os.environ.get("QUOTA_URL"))
    except QuotaStoreUnavailable as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    return manager, config


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="adk-agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="serve an ADK agent over MCP")
    p_serve.add_argument("--agent", default=None, help="path to a Python file defining `agent`")
    p_serve.add_argument("--config", default=None, help="path to a JSON FrameworkConfig file")
    p_serve.add_argument(
        "--agent-ref",
        action="append",
        dest="agent_ref",
        default=None,
        help="registry reference TENANT/ID@VERSION (repeatable; one for serve)",
    )
    p_serve.add_argument(
        "--registry",
        default=os.environ.get("ADK_REGISTRY_DIR", "registry"),
        help="registry directory (defaults to $ADK_REGISTRY_DIR, then ./registry)",
    )
    _add_registry_client_args(p_serve)
    p_serve.add_argument(
        "--artifact-dir", default=None, help="content-addressed directory for artifact bytes"
    )
    p_serve.add_argument(
        "--artifact-keys",
        default=None,
        help="JSON file mapping key id to a 64 hex Ed25519 public key",
    )
    p_serve.add_argument("--name", default=None, help="MCP tool name (defaults to the agent name)")
    p_serve.add_argument(
        "--transport",
        default=None,
        choices=["stdio", "streamable-http"],
        help="MCP transport to run on (defaults to the config value, else stdio)",
    )
    _add_http_args(p_serve)
    p_serve.add_argument(
        "--oidc-config",
        default=None,
        help=(
            "JSON OidcConfig file; when set, use OIDC auth and ignore --auth-token-env and --role"
        ),
    )
    _add_runtime_args(p_serve)
    _add_audit_quota_args(p_serve)
    _add_rate_limit_args(p_serve)
    p_serve.add_argument(
        "--metrics",
        action="store_true",
        help="count runs and expose /metrics on streamable-http",
    )
    p_serve.add_argument(
        "--session-tenant-scope",
        action="store_true",
        help="scope OIDC session keys to <tenant>:<subject> (default: off)",
    )

    p_many = sub.add_parser("serve-many", help="serve several agents as separate MCP tools")
    p_many.add_argument(
        "--agents",
        default=None,
        help="path to a Python file defining an `agents` dict (name -> agent)",
    )
    p_many.add_argument(
        "--agent-ref",
        action="append",
        dest="agent_ref",
        default=None,
        help="registry reference TENANT/ID@VERSION (repeatable)",
    )
    p_many.add_argument(
        "--registry",
        default=os.environ.get("ADK_REGISTRY_DIR", "registry"),
        help="registry directory (defaults to $ADK_REGISTRY_DIR, then ./registry)",
    )
    _add_registry_client_args(p_many)
    p_many.add_argument(
        "--artifact-dir", default=None, help="content-addressed directory for artifact bytes"
    )
    p_many.add_argument(
        "--artifact-keys",
        default=None,
        help="JSON file mapping key id to a 64 hex Ed25519 public key",
    )
    p_many.add_argument("--name", default="adk_agents", help="MCP server name")
    p_many.add_argument(
        "--transport",
        default=None,
        choices=["stdio", "streamable-http"],
        help="MCP transport to run on (defaults to stdio)",
    )
    _add_http_args(p_many)
    p_many.add_argument(
        "--oidc-config",
        default=None,
        help=(
            "JSON OidcConfig file; when set, use OIDC auth and ignore --auth-token-env and --role"
        ),
    )
    _add_runtime_args(p_many)
    _add_audit_quota_args(p_many)
    _add_rate_limit_args(p_many)
    p_many.add_argument(
        "--metrics",
        action="store_true",
        help="count runs and expose /metrics on streamable-http",
    )
    p_many.add_argument(
        "--session-tenant-scope",
        action="store_true",
        help="scope OIDC session keys to <tenant>:<subject> (default: off)",
    )

    p_a2a = sub.add_parser("serve-a2a", help="serve an ADK agent over A2A (needs a2a-sdk)")
    p_a2a.add_argument("--agent", required=True, help="path to a Python file defining `agent`")
    p_a2a.add_argument(
        "--rpc-path",
        default="",
        help="mount the RPC and agent-card routes under this path prefix",
    )
    _add_http_args(p_a2a)
    _add_audit_quota_args(p_a2a)
    _add_rate_limit_args(p_a2a)

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
    p_gateway.add_argument(
        "--breaker-failures",
        type=int,
        default=5,
        help="consecutive provider failures that open the circuit (default: 5)",
    )
    p_gateway.add_argument(
        "--breaker-reset",
        type=float,
        default=30.0,
        help="seconds an open circuit waits before probing (default: 30)",
    )
    gateway_audit = p_gateway.add_mutually_exclusive_group()
    gateway_audit.add_argument("--audit-file", default=None, help="append JSONL audit events here")
    gateway_audit.add_argument(
        "--audit-url", default=None, help="send audit events to this audit service URL"
    )
    p_gateway.add_argument(
        "--audit-token-env",
        default="ADK_AUDIT_AUTH_TOKEN",
        help=(
            "env var holding the audit bearer token (only used with --audit-url; "
            "never pass tokens on the command line)"
        ),
    )
    _add_http_args(p_gateway)
    _add_rate_limit_args(p_gateway)
    p_gateway.add_argument(
        "--oidc-config",
        default=None,
        help=(
            "JSON OidcConfig file; when set, use OIDC auth and ignore --auth-token-env and --role"
        ),
    )

    p_tools = sub.add_parser(
        "serve-tool-gateway", help="serve the tool gateway as a standalone service"
    )
    p_tools.add_argument(
        "--tools",
        required=True,
        help="path to a Python file defining a `tools` mapping (tool_id -> callable or ToolSpec)",
    )
    tools_audit = p_tools.add_mutually_exclusive_group()
    tools_audit.add_argument("--audit-file", default=None, help="append JSONL audit events here")
    tools_audit.add_argument(
        "--audit-url", default=None, help="send audit events to this audit service URL"
    )
    p_tools.add_argument(
        "--audit-token-env",
        default="ADK_AUDIT_AUTH_TOKEN",
        help=(
            "env var holding the audit bearer token (only used with --audit-url; "
            "never pass tokens on the command line)"
        ),
    )
    _add_http_args(p_tools)
    _add_rate_limit_args(p_tools)
    p_tools.add_argument(
        "--oidc-config",
        default=None,
        help=(
            "JSON OidcConfig file; when set, use OIDC auth and ignore --auth-token-env and --role"
        ),
    )

    p_audit = sub.add_parser("serve-audit", help="serve the audit pipeline as a standalone service")
    p_audit.add_argument("--out", required=True, help="append chained audit records here (JSONL)")
    p_audit.add_argument(
        "--audit-max-records",
        type=int,
        default=None,
        help="rotate the audit file into FILE.000001 segments after this many records",
    )
    _add_http_args(p_audit)
    _add_rate_limit_args(p_audit)
    p_audit.add_argument(
        "--oidc-config",
        default=None,
        help=(
            "JSON OidcConfig file; when set, use OIDC auth and ignore --auth-token-env and --role"
        ),
    )

    p_registry = sub.add_parser("serve-registry", help="serve the agent registry control plane")
    p_registry.add_argument(
        "--database-url",
        default=os.environ.get("REGISTRY_DATABASE_URL"),
        help="Postgres DSN for published versions (defaults to $REGISTRY_DATABASE_URL)",
    )
    p_registry.add_argument(
        "--artifact-dir", default=None, help="content-addressed directory for artifact bytes"
    )
    p_registry.add_argument(
        "--artifact-keys",
        default=None,
        help="JSON file mapping key id to a 64 hex Ed25519 public key",
    )
    _add_http_args(p_registry)
    _add_rate_limit_args(p_registry)
    p_registry.add_argument(
        "--oidc-config",
        default=None,
        help=(
            "JSON OidcConfig file; when set, use OIDC auth and ignore --auth-token-env and --role"
        ),
    )
    _add_audit_args(p_registry)

    p_verify = sub.add_parser("verify-audit", help="verify an audit chain file")
    p_verify.add_argument("path", help="path to a chained audit JSONL file")

    p_console = sub.add_parser("console", help="serve a private web console for agents")
    p_console.add_argument(
        "--agents",
        default=None,
        help="path to a Python file defining an `agents` dict (name -> agent)",
    )
    p_console.add_argument(
        "--agent-ref",
        action="append",
        dest="agent_ref",
        default=None,
        help="registry reference TENANT/ID@VERSION (repeatable)",
    )
    p_console.add_argument(
        "--artifact-dir", default=None, help="content-addressed directory for artifact bytes"
    )
    p_console.add_argument(
        "--artifact-keys",
        default=None,
        help="JSON file mapping key id to a 64 hex Ed25519 public key",
    )
    p_console.add_argument(
        "--tool-catalog",
        default=None,
        help="read-only tool catalog JSON for the Tools panel",
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
    p_console.add_argument(
        "--registry",
        default=os.environ.get("ADK_REGISTRY_DIR", "registry"),
        help="registry directory (defaults to $ADK_REGISTRY_DIR, then ./registry)",
    )
    _add_registry_client_args(p_console)
    p_console.add_argument(
        "--oidc-config",
        default=None,
        help=(
            "JSON OidcConfig file; when set, use OIDC auth and ignore --auth-token-env and --role"
        ),
    )
    p_console.add_argument(
        "--quota-config",
        default=None,
        help="JSON QuotaConfig file",
    )
    p_console.add_argument(
        "--approval-dir",
        default=os.environ.get("ADK_APPROVAL_DIR"),
        help="approval inbox directory (defaults to $ADK_APPROVAL_DIR)",
    )
    p_console.add_argument(
        "--approval-ttl",
        type=float,
        default=None,
        help="fallback approval expiry in seconds for requests without expires_at",
    )
    p_console.add_argument(
        "--sse-queue-size",
        type=int,
        default=512,
        help="max buffered progress events per SSE stream (default: 512)",
    )
    p_console.add_argument(
        "--max-loaded-agents",
        type=int,
        default=20,
        help="max agents the console may hold, startup plus on-demand (default: 20)",
    )
    p_console.add_argument(
        "--session-tenant-scope",
        action="store_true",
        help="scope session keys to <tenant>:<subject> (default: off)",
    )
    _add_audit_args(p_console)
    _add_http_args(p_console)
    _add_rate_limit_args(p_console)
    _add_runtime_args(p_console)

    p_approvals = sub.add_parser("approvals", help="manage approval records")
    approvals_sub = p_approvals.add_subparsers(dest="approvals_cmd", required=True)
    p_prune = approvals_sub.add_parser("prune", help="archive or delete terminal approval records")
    p_prune.add_argument(
        "--dir",
        default=os.environ.get("ADK_APPROVAL_DIR"),
        help="approval inbox directory (defaults to $ADK_APPROVAL_DIR)",
    )
    p_prune.add_argument(
        "--older-than",
        type=float,
        required=True,
        help="retention period in seconds; terminal records older than this are pruned",
    )
    p_prune.add_argument(
        "--delete",
        action="store_true",
        help="delete records instead of moving them to <dir>/archive",
    )

    p_lifecycle = sub.add_parser("lifecycle", help="change a published version's lifecycle state")
    lifecycle_sub = p_lifecycle.add_subparsers(dest="lifecycle_cmd", required=True)
    p_lifecycle_set = lifecycle_sub.add_parser("set", help="set the lifecycle status")
    p_lifecycle_set.add_argument("--tenant", required=True)
    p_lifecycle_set.add_argument("--id", required=True)
    p_lifecycle_set.add_argument("--version", required=True)
    p_lifecycle_set.add_argument("--status", required=True, help="published, deprecated or retired")
    p_lifecycle_set.add_argument("--reason", default="")
    p_lifecycle_set.add_argument(
        "--registry",
        default=os.environ.get("ADK_REGISTRY_DIR", "registry"),
        help="registry directory (defaults to $ADK_REGISTRY_DIR, then ./registry)",
    )
    _add_registry_client_args(p_lifecycle_set)

    p_backup = sub.add_parser("backup", help="archive file-based state into a gzip tar")
    p_backup.add_argument("--out", required=True, help="archive path to write")
    p_backup.add_argument("--registry", default=None, help="registry directory to include")
    p_backup.add_argument("--approvals", default=None, help="approval inbox directory to include")
    p_backup.add_argument(
        "--audit", default=None, help="audit JSONL file to include with its rotation segments"
    )

    p_restore = sub.add_parser("restore", help="restore a file-based state backup")
    p_restore.add_argument("--archive", required=True, help="backup archive to read")
    p_restore.add_argument("--dest", required=True, help="directory to restore into")
    p_restore.add_argument(
        "--force", action="store_true", help="replace a non-empty destination after a full extract"
    )

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
    _add_registry_client_args(p_publish)
    p_publish.add_argument(
        "--eval-report",
        default=None,
        help="path to an EvalReport JSON file (required when the manifest declares eval_suite)",
    )
    p_publish.add_argument(
        "--artifact",
        default=None,
        help="agent project directory or artifact zip to attach",
    )
    p_publish.add_argument(
        "--key",
        default=None,
        help="PEM Ed25519 private key used to sign the artifact digest",
    )
    p_publish.add_argument(
        "--key-id",
        default=None,
        help="key id recorded with the artifact signature",
    )
    p_publish.add_argument(
        "--artifact-dir",
        default=None,
        help="content-addressed directory for artifact bytes",
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
        rate_limit = _rate_limit(args)
        from .mcp.server import serve_agent

        if sum(bool(value) for value in (args.config, args.agent, args.agent_ref)) > 1:
            print("--config, --agent and --agent-ref are mutually exclusive", file=sys.stderr)
            raise SystemExit(1)

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
        elif args.agent_ref:
            if len(args.agent_ref) > 1:
                print("serve accepts exactly one --agent-ref", file=sys.stderr)
                raise SystemExit(1)
            agents = _registry_agents(args) or {}
            agent = next(iter(agents.values()))
            name = args.name or agent.name
            transport = args.transport or "stdio"
        else:
            print("provide --agent <file>, --config <file> or --agent-ref", file=sys.stderr)
            raise SystemExit(1)

        if rate_limit is not None and transport != "streamable-http":
            print("--rate-limit requires streamable-http", file=sys.stderr)
            raise SystemExit(1)

        oidc = _identity_provider(args)
        if oidc is not None and transport != "streamable-http":
            print("oidc config requires streamable-http", file=sys.stderr)
            raise SystemExit(1)

        from .factory import build_runner

        audit = _audit_sink(args)
        quota, quota_config = _quota_settings(args)
        metrics = None
        if args.metrics:
            from .metrics import MetricsRegistry

            metrics = MetricsRegistry()
        serve_agent(
            agent=agent,
            name=name,
            transport=cast(Transport, transport),
            host=args.host,
            port=args.port,
            auth_token=_auth_token(args),
            allow_unauthenticated=args.allow_unauthenticated,
            oidc=oidc,
            runner=build_runner(agent, args.session_db),
            audit=audit,
            quota=quota,
            quota_config=quota_config,
            metrics=metrics,
            rate_limit=rate_limit,
            session_tenant_scope=args.session_tenant_scope,
        )
    elif args.cmd == "serve-many":
        rate_limit = _rate_limit(args)
        from .factory import build_runner
        from .mcp.server import serve_many

        if bool(args.agents) == bool(args.agent_ref):
            print("provide exactly one of --agents or --agent-ref", file=sys.stderr)
            raise SystemExit(1)
        agents = _load_agents(args.agents) if args.agents else (_registry_agents(args) or {})
        transport = args.transport or "stdio"
        if rate_limit is not None and transport != "streamable-http":
            print("--rate-limit requires streamable-http", file=sys.stderr)
            raise SystemExit(1)
        oidc = _identity_provider(args)
        if oidc is not None and transport != "streamable-http":
            print("oidc config requires streamable-http", file=sys.stderr)
            raise SystemExit(1)
        runner_factory = (
            partial(build_runner, session_db=args.session_db) if args.session_db else None
        )
        audit = _audit_sink(args)
        quota, quota_config = _quota_settings(args)
        metrics = None
        if args.metrics:
            from .metrics import MetricsRegistry

            metrics = MetricsRegistry()
        serve_many(
            agents,
            name=args.name,
            transport=cast(Transport, transport),
            host=args.host,
            port=args.port,
            auth_token=_auth_token(args),
            allow_unauthenticated=args.allow_unauthenticated,
            oidc=oidc,
            runner_factory=runner_factory,
            audit=audit,
            quota=quota,
            quota_config=quota_config,
            metrics=metrics,
            rate_limit=rate_limit,
            session_tenant_scope=args.session_tenant_scope,
        )
    elif args.cmd == "serve-a2a":
        rate_limit = _rate_limit(args)
        from .a2a import A2aUnavailable, serve_a2a

        agent = _load_agent(args.agent)
        audit = _audit_sink(args)
        quota, quota_config = _quota_settings(args)
        try:
            serve_a2a(
                agent,
                host=args.host,
                port=args.port,
                rpc_path=args.rpc_path,
                auth_token=_auth_token(args),
                allow_unauthenticated=args.allow_unauthenticated,
                audit=audit,
                quota=quota,
                quota_config=quota_config,
                rate_limit=rate_limit,
            )
        except A2aUnavailable as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None
    elif args.cmd == "serve-model-gateway":
        rate_limit = _rate_limit(args)
        from .core import ModelProvider
        from .mcp.http import resolve_port
        from .metrics import MetricsRegistry
        from .models.breaker import BreakerProvider
        from .models.gateway import PolicyModelGateway
        from .models.service import build_model_gateway_app, build_providers
        from .resilience import CircuitBreaker

        if args.breaker_failures <= 0 or args.breaker_reset <= 0:
            print("breaker thresholds must be positive", file=sys.stderr)
            raise SystemExit(1)

        oidc = _identity_provider(args)
        try:
            providers = build_providers(args.providers or ["litellm"], vllm_url=args.vllm_url)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None

        metrics = MetricsRegistry()
        providers = {
            name: cast(
                ModelProvider,
                BreakerProvider(
                    provider,
                    CircuitBreaker(
                        failure_threshold=args.breaker_failures,
                        reset_seconds=args.breaker_reset,
                    ),
                    metrics=metrics,
                ),
            )
            for name, provider in providers.items()
        }
        sink = _audit_sink(args)
        app = build_model_gateway_app(
            PolicyModelGateway(providers, audit=sink),
            host=args.host,
            auth_token=_auth_token(args),
            allow_unauthenticated=args.allow_unauthenticated,
            oidc=oidc,
            metrics=metrics,
            rate_limit=rate_limit,
        )

        import uvicorn

        uvicorn.run(app, host=args.host, port=resolve_port(args.port), log_level="info")
    elif args.cmd == "serve-tool-gateway":
        rate_limit = _rate_limit(args)
        from .mcp.http import resolve_port
        from .tools import FunctionToolGateway
        from .tools.service import build_tool_gateway_app

        registry = _load_tools(args.tools)
        sink = _audit_sink(args)
        oidc = _identity_provider(args)
        app = build_tool_gateway_app(
            FunctionToolGateway(registry, audit=sink),
            host=args.host,
            auth_token=_auth_token(args),
            allow_unauthenticated=args.allow_unauthenticated,
            oidc=oidc,
            rate_limit=rate_limit,
        )

        import uvicorn

        uvicorn.run(app, host=args.host, port=resolve_port(args.port), log_level="info")
    elif args.cmd == "serve-audit":
        rate_limit = _rate_limit(args)
        from .audit import AuditPipeline
        from .audit.service import build_audit_pipeline_app
        from .mcp.http import resolve_port

        if args.audit_max_records is not None and args.audit_max_records <= 0:
            print("--audit-max-records must be greater than 0", file=sys.stderr)
            raise SystemExit(1)
        signing_key, keyring = _audit_signing()
        oidc = _identity_provider(args)
        app = build_audit_pipeline_app(
            AuditPipeline(
                args.out,
                max_records=args.audit_max_records,
                signing_key=signing_key,
                keyring=keyring,
            ),
            host=args.host,
            auth_token=_auth_token(args),
            allow_unauthenticated=args.allow_unauthenticated,
            oidc=oidc,
            rate_limit=rate_limit,
        )

        import uvicorn

        uvicorn.run(app, host=args.host, port=resolve_port(args.port), log_level="info")
    elif args.cmd == "serve-registry":
        rate_limit = _rate_limit(args)
        from .mcp.http import resolve_port
        from .registry import (
            ArtifactStoreError,
            FileArtifactStore,
            PostgresAgentLifecycleStore,
            PostgresAgentRegistry,
            PostgresEvalReportStore,
            RegistryStoreUnavailable,
        )
        from .registry.artifacts_postgres import PostgresArtifactStore
        from .registry.service import build_registry_service_app

        if not args.database_url:
            print(
                "database URL is required: provide --database-url or set REGISTRY_DATABASE_URL",
                file=sys.stderr,
            )
            raise SystemExit(1)
        try:
            registry = PostgresAgentRegistry(args.database_url)
            eval_reports = PostgresEvalReportStore(args.database_url)
            lifecycle = PostgresAgentLifecycleStore(args.database_url)
        except RegistryStoreUnavailable as exc:
            print(f"registry store unavailable: {exc}", file=sys.stderr)
            raise SystemExit(1) from None

        url = os.environ.get("ARTIFACT_URL")
        if url and args.artifact_dir:
            print("set exactly one of --artifact-dir or ARTIFACT_URL", file=sys.stderr)
            raise SystemExit(1)
        store: Any = None
        try:
            if url:
                store = PostgresArtifactStore(url)
            elif args.artifact_dir:
                store = FileArtifactStore(args.artifact_dir)
        except ArtifactStoreError as exc:
            print(f"invalid artifact store: {exc}", file=sys.stderr)
            raise SystemExit(1) from None

        oidc = _identity_provider(args)
        app = build_registry_service_app(
            registry,
            artifact_store=store,
            eval_reports=eval_reports,
            lifecycle=lifecycle,
            audit=_audit_sink(args),
            trust=_artifact_trust(args),
            host=args.host,
            auth_token=_auth_token(args),
            allow_unauthenticated=args.allow_unauthenticated,
            oidc=oidc,
            rate_limit=rate_limit,
        )

        import uvicorn

        uvicorn.run(app, host=args.host, port=resolve_port(args.port), log_level="info")
    elif args.cmd == "verify-audit":
        from .audit import AuditChainBroken, AuditSignatureInvalid, verify_audit_file

        signing_key, keyring = _audit_signing()
        try:
            count = verify_audit_file(args.path, signing_key=signing_key, keyring=keyring)
        except AuditSignatureInvalid as exc:
            print(f"audit signature invalid at record {exc.index}", file=sys.stderr)
            raise SystemExit(1) from None
        except AuditChainBroken as exc:
            print(
                f"audit chain broken at record {exc.index} for tenant {exc.tenant!r}",
                file=sys.stderr,
            )
            raise SystemExit(1) from None
        except Exception as exc:  # noqa: BLE001
            print(f"invalid audit file: {exc}", file=sys.stderr)
            raise SystemExit(1) from None
        print(f"ok {count} records")
    elif args.cmd == "console":
        rate_limit = _rate_limit(args)
        from .console import run_console
        from .registry import (
            FileAgentLifecycleStore,
            FileEvalReportStore,
            HttpEvalReportStore,
            InProcessArtifactLoader,
        )

        if args.sse_queue_size < 1:
            print("--sse-queue-size must be at least 1", file=sys.stderr)
            raise SystemExit(1)
        if args.max_loaded_agents < 1:
            print("--max-loaded-agents must be at least 1", file=sys.stderr)
            raise SystemExit(1)

        oidc = _identity_provider(args)
        quota, quota_config = _quota_settings(args)
        approvals = None
        if args.approval_dir:
            from .approvals import FileApprovalInbox

            approvals = FileApprovalInbox(Path(args.approval_dir), ttl_seconds=args.approval_ttl)

        if args.agents and args.agent_ref:
            print("--agents and --agent-ref are mutually exclusive", file=sys.stderr)
            raise SystemExit(1)
        if args.agents:
            agents = _load_agents(args.agents)
        elif args.agent_ref:
            agents = _registry_agents(args) or {}
        else:
            print("provide --agents or --agent-ref", file=sys.stderr)
            raise SystemExit(1)

        audit_query = _audit_query(args)
        audit_sink = _audit_sink(args)
        artifact_trust = _artifact_trust(args)
        artifact_store = _artifact_store(args)
        registry_client = _agent_registry(args)
        console_lifecycle = _lifecycle_source(args, registry_client)
        run_console(
            agents=agents,
            host=args.host,
            port=args.port,
            auth_token=_auth_token(args),
            allow_unauthenticated=args.allow_unauthenticated,
            session_db=args.session_db,
            policy_file=args.policy,
            roles=args.roles,
            registry=registry_client,
            tool_catalog=_tool_catalog(args),
            lifecycle=console_lifecycle,
            eval_reports=(
                HttpEvalReportStore(args.registry_url, auth_token=_registry_token(args))
                if args.registry_url
                else FileEvalReportStore(args.registry)
            ),
            artifact_store=artifact_store,
            artifact_loader=InProcessArtifactLoader() if artifact_store else None,
            artifact_trust=artifact_trust,
            max_loaded_agents=args.max_loaded_agents,
            audit_sink=audit_sink,
            audit_query=audit_query,
            oidc=oidc,
            quota=quota,
            quota_config=quota_config,
            approvals=approvals,
            sse_queue_size=args.sse_queue_size,
            rate_limit=rate_limit,
            session_tenant_scope=args.session_tenant_scope,
        )
    elif args.cmd == "approvals":
        from .approvals import FileApprovalInbox

        if not args.dir:
            print(
                "approval dir is required: provide --dir or set ADK_APPROVAL_DIR",
                file=sys.stderr,
            )
            raise SystemExit(1)
        if args.older_than <= 0:
            print("--older-than must be greater than 0", file=sys.stderr)
            raise SystemExit(1)
        try:
            result = FileApprovalInbox(args.dir).prune(args.older_than, archive=not args.delete)
        except OSError as exc:
            print(f"prune failed: {type(exc).__name__}", file=sys.stderr)
            raise SystemExit(1) from None
        if args.delete:
            print(f"deleted {result.deleted} requests")
        else:
            print(f"archived {result.archived} requests")
    elif args.cmd == "backup":
        from .backup import BackupError, create_backup

        sources = [
            (kind, path)
            for kind, path in (
                ("registry", args.registry),
                ("approvals", args.approvals),
                ("audit", args.audit),
            )
            if path
        ]
        if not sources:
            print("backup needs at least one source", file=sys.stderr)
            raise SystemExit(1)
        try:
            _, digest = create_backup(args.out, sources)
        except (BackupError, OSError) as exc:
            print(f"backup failed: {type(exc).__name__}", file=sys.stderr)
            raise SystemExit(1) from None
        print(f"wrote {args.out} sha256:{digest}")
    elif args.cmd == "restore":
        from .backup import BackupError, restore_backup

        try:
            restore_backup(args.archive, args.dest, force=args.force)
        except BackupError as exc:
            print(f"restore failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from None
        dest = Path(args.dest)
        files = sum(1 for path in dest.rglob("*") if path.is_file())
        print(f"restored {files} files to {args.dest}")
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
    elif args.cmd == "lifecycle":
        from .core import LifecycleTransitionError
        from .registry import (
            FileAgentLifecycleStore,
            FileAgentRegistry,
            HttpAgentLifecycleStore,
            RegistryError,
        )

        if args.status not in {"published", "deprecated", "retired"}:
            print(f"invalid status: {args.status!r}", file=sys.stderr)
            raise SystemExit(1)
        try:
            if args.registry_url:
                client = _agent_registry(args)
                remote = HttpAgentLifecycleStore(client)

                async def set_remote():
                    try:
                        return await remote.set(
                            args.tenant,
                            args.id,
                            args.version,
                            status=args.status,
                            changed_by="cli",
                            reason=args.reason,
                        )
                    finally:
                        await client.aclose()

                state = asyncio.run(set_remote())
            else:
                registry = FileAgentRegistry(args.registry)

                async def check_version():
                    records = await registry.list(args.tenant)
                    if not any(
                        record.manifest.id == args.id and record.manifest.version == args.version
                        for record in records
                    ):
                        raise LookupError(f"version not found: {args.id}@{args.version}")

                asyncio.run(check_version())
                state = asyncio.run(
                    FileAgentLifecycleStore(args.registry).set(
                        args.tenant,
                        args.id,
                        args.version,
                        status=args.status,
                        changed_by="cli",
                        reason=args.reason,
                    )
                )
        except (LifecycleTransitionError, RegistryError, LookupError, ValueError) as exc:
            print(f"lifecycle failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from None
        print(f"{args.tenant}/{args.id}@{args.version} status={state.status}")
    elif args.cmd == "publish":
        from .core import EvalReport
        from .eval import enforce_eval_gate
        from .registry import (
            FileEvalReportStore,
            HttpEvalReportStore,
            load_manifest,
            published_from,
        )

        try:
            manifest = load_manifest(args.path)
            report = (
                EvalReport.model_validate_json(Path(args.eval_report).read_text(encoding="utf-8"))
                if args.eval_report
                else None
            )
            enforce_eval_gate(manifest, report)
            artifact, artifact_bytes = _publish_artifact(args, manifest)
            registry = _agent_registry(args)

            async def publish_record():
                eval_store = (
                    HttpEvalReportStore(args.registry_url, auth_token=_registry_token(args))
                    if args.registry_url and report is not None
                    else None
                )
                try:
                    stored = await registry.publish(published_from(manifest, artifact=artifact))
                    if eval_store is not None and report is not None:
                        await eval_store.put(manifest.tenant, manifest.id, manifest.version, report)
                    if artifact_bytes is not None:
                        await registry.upload_artifact(stored.artifact, artifact_bytes)
                finally:
                    if eval_store is not None and hasattr(eval_store, "aclose"):
                        await eval_store.aclose()
                    if hasattr(registry, "aclose"):
                        await registry.aclose()
                return stored

            stored = asyncio.run(publish_record())
            if report is not None and not args.registry_url:
                asyncio.run(
                    FileEvalReportStore(args.registry).put(
                        manifest.tenant, manifest.id, manifest.version, report
                    )
                )
        except Exception as exc:  # noqa: BLE001
            print(f"publish failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from None
        print(
            f"published {stored.manifest.tenant}/{stored.manifest.id}@{stored.manifest.version} "
            f"sha256:{stored.digest}"
        )
        if stored.artifact is not None:
            print(f"artifact {stored.artifact.digest}")
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
