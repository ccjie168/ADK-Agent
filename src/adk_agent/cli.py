"""Command line entry point: ``adk-agent serve|new``."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.util
import json
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
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
_DATA_CLASSES = ("public", "internal", "confidential", "restricted")

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
    """Load ``agent`` (or ``root_agent``) from a Python file path.

    A file that defines only a single-entry ``agents`` mapping also counts, so
    ``serve`` can reuse the same file as ``serve-many``.
    """
    module = _load_module(path)
    for attr in ("agent", "root_agent"):
        if hasattr(module, attr):
            return getattr(module, attr)
    agents = getattr(module, "agents", None)
    if isinstance(agents, dict) and len(agents) == 1:
        return next(iter(agents.values()))
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


def _builder_trust(args: argparse.Namespace) -> TrustStore | None:
    """Build a builder trust store from ``--builder-keys`` or ``$ADK_BUILDER_KEYS``."""
    from .registry import ArtifactTrustError, TrustStore

    keys_file = getattr(args, "builder_keys", None)
    try:
        keys_text = (
            Path(keys_file).read_text(encoding="utf-8")
            if keys_file
            else os.environ.get("ADK_BUILDER_KEYS")
        )
    except OSError as exc:
        print(f"cannot read builder keys: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    if not keys_text:
        return None
    try:
        return TrustStore.from_json(keys_text)
    except ArtifactTrustError as exc:
        print(f"invalid builder keys: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


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


def _tool_grant_store(args: argparse.Namespace) -> Any:
    """Build the tool grant store from ``--tool-grants-dir`` or ``$GRANT_URL``."""
    from .registry import FileToolGrantStore, PostgresToolGrantStore

    grants_dir = getattr(args, "tool_grants_dir", None)
    url = os.environ.get("GRANT_URL")
    if url and grants_dir:
        print("set exactly one of --tool-grants-dir or GRANT_URL", file=sys.stderr)
        raise SystemExit(1)
    if grants_dir:
        return FileToolGrantStore(grants_dir)
    if url:
        return PostgresToolGrantStore(url)
    return None


def _idempotency_store(args: argparse.Namespace) -> Any:
    """Build the tool idempotency store from ``--idempotency-dir`` or ``--idempotency-db``."""
    from .tools import FileToolIdempotencyStore, PostgresToolIdempotencyStore

    directory = getattr(args, "idempotency_dir", None)
    url = getattr(args, "idempotency_db", None)
    if directory and url:
        print("set exactly one of --idempotency-dir or --idempotency-db", file=sys.stderr)
        raise SystemExit(1)
    if directory:
        return FileToolIdempotencyStore(directory)
    if url:
        return PostgresToolIdempotencyStore(url)
    return None


def _connector_store(args: argparse.Namespace) -> Any:
    """Build the connector store from ``--connectors-dir`` or ``--registry-url``."""
    from .registry import FileConnectorStore, HttpConnectorStore

    directory = getattr(args, "connectors_dir", None)
    url = getattr(args, "registry_url", None)
    if directory and url:
        print("set exactly one of --connectors-dir or --registry-url", file=sys.stderr)
        raise SystemExit(1)
    if directory:
        return FileConnectorStore(directory)
    if url:
        if not url.startswith(("http://", "https://")):
            print(f"invalid --registry-url {url!r}: expected http:// or https://", file=sys.stderr)
            raise SystemExit(1)
        return HttpConnectorStore(url, auth_token=_registry_token(args))
    return None


def _key_backend_message(exc: Exception) -> str:
    if os.environ.get("ADK_SECRET_BACKEND") == "vault":
        return f"invalid Vault key backend configuration (ADK_VAULT_*): {exc}"
    return f"invalid ADK_SECRET_KEKS/ADK_SECRET_KEKS_FILE: {exc}"


def _credential_store(args: argparse.Namespace) -> Any:
    """Build the credential store from ``--credentials-dir`` or ``--credential-db``."""
    from .registry import FileCredentialStore, PostgresCredentialStore

    directory = getattr(args, "credentials_dir", None)
    url = getattr(args, "credential_db", None)
    env_url = os.environ.get("CREDENTIAL_DATABASE_URL")
    if directory and url:
        print("set exactly one of --credentials-dir or --credential-db", file=sys.stderr)
        raise SystemExit(2)
    if directory and env_url:
        print(
            "--credentials-dir conflicts with CREDENTIAL_DATABASE_URL",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if url and env_url:
        print(
            "--credential-db conflicts with CREDENTIAL_DATABASE_URL",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if directory:
        return FileCredentialStore(directory)
    if url:
        return PostgresCredentialStore(url)
    if env_url:
        return PostgresCredentialStore(env_url)
    return None


def _trigger_store(args: argparse.Namespace) -> Any:
    """Build the trigger store from ``--dir``, ``--db``, or ``$TRIGGER_DATABASE_URL``."""
    from .registry import FileTriggerStore, PostgresTriggerStore

    directory = getattr(args, "dir", None)
    url = getattr(args, "db", None)
    env_url = os.environ.get("TRIGGER_DATABASE_URL")
    if directory and url:
        print("set exactly one of --dir or --db", file=sys.stderr)
        raise SystemExit(2)
    if directory and env_url:
        print("--dir conflicts with TRIGGER_DATABASE_URL", file=sys.stderr)
        raise SystemExit(2)
    if directory:
        return FileTriggerStore(directory)
    if url:
        return PostgresTriggerStore(url)
    if env_url:
        return PostgresTriggerStore(env_url)
    return None


async def _require_credential_binding(store: Any, spec: Any) -> None:
    """Reject a connector whose tenant reference has no enabled binding."""
    from .registry import credential_is_bound

    if not await credential_is_bound(store, spec):
        raise ValueError("credential_unbound")


def _connector_request_store(args: argparse.Namespace) -> Any:
    """Build the connector request store from the file dir or Postgres URL."""
    from .registry import FileConnectorRequestStore, PostgresConnectorRequestStore

    directory = getattr(args, "connector_requests_dir", None)
    if directory is None:
        directory = getattr(args, "dir", None)
    url = getattr(args, "connector_request_db", None)
    if url is None:
        url = getattr(args, "db", None)
    env_url = os.environ.get("CONNECTOR_REQUEST_DATABASE_URL")
    if directory and url:
        print(
            "set exactly one of --connector-requests-dir or --connector-request-db",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if directory and env_url:
        print(
            "--connector-requests-dir conflicts with CONNECTOR_REQUEST_DATABASE_URL",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if directory:
        return FileConnectorRequestStore(directory)
    if url:
        return PostgresConnectorRequestStore(url)
    if env_url:
        return PostgresConnectorRequestStore(env_url)
    return None


def _peer_stores(args: argparse.Namespace) -> tuple[Any, Any]:
    from .registry import (
        FilePeerGrantStore,
        FilePeerStore,
        PostgresPeerGrantStore,
        PostgresPeerStore,
    )

    directory = getattr(args, "peer_dir", None)
    url = getattr(args, "peer_db", None)
    if bool(directory) == bool(url):
        print("set exactly one of --peer-dir or --peer-db", file=sys.stderr)
        raise SystemExit(1)
    if directory:
        return FilePeerStore(directory), FilePeerGrantStore(directory)
    database_url = cast("str", url)
    return PostgresPeerStore(database_url), PostgresPeerGrantStore(database_url)


def _remote_agent_store(args: argparse.Namespace) -> Any:
    from .registry import FileRemoteAgentStore, PostgresRemoteAgentStore

    directory = getattr(args, "peer_dir", None)
    if directory:
        return FileRemoteAgentStore(directory)
    return PostgresRemoteAgentStore(cast("str", getattr(args, "peer_db", None)))


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
    from .sandbox.agent import AgentSandboxUnavailable, SandboxToolsUnavailable

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
        AgentSandboxUnavailable,
        SandboxToolsUnavailable,
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
    audit.add_argument(
        "--audit-db", default=None, help="write audit events directly to this Postgres URL"
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


def _add_tool_grant_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--tool-grants-dir",
        default=None,
        help="directory of temporary tool grant requests (or set GRANT_URL)",
    )


def _add_idempotency_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--idempotency-dir",
        default=None,
        help="directory of tool idempotency records (file backend)",
    )
    parser.add_argument(
        "--idempotency-db",
        default=None,
        help="Postgres URL of tool idempotency records (shared backend)",
    )


def _auth_token(args: argparse.Namespace) -> str | None:
    env_name = getattr(args, "auth_token_env", None)
    return os.environ.get(env_name) if env_name else None


def _trust_caller_policy(args: argparse.Namespace) -> bool:
    """Return the loopback-only escape-hatch flag, rejecting non-loopback use."""
    flag = bool(getattr(args, "trust_caller_policy", False))
    if not flag:
        return False
    from .auth import LOOPBACK_HOSTS

    if args.host not in LOOPBACK_HOSTS:
        print("--trust-caller-policy is only allowed on a loopback host", file=sys.stderr)
        raise SystemExit(1)
    if getattr(args, "registry_url", None) or getattr(args, "registry", None):
        print(
            "--trust-caller-policy cannot be combined with --registry or --registry-url",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return True


def _add_peer_store_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--peer-dir", default=None, help="peer and grant file store root")
    parser.add_argument("--peer-db", default=None, help="Postgres URL for peers and grants")


def _add_credential_store_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--credentials-dir", default=None, help="file store root for credential bindings"
    )
    parser.add_argument(
        "--credential-db",
        default=None,
        help="Postgres URL for credential bindings (defaults to $CREDENTIAL_DATABASE_URL)",
    )


def _add_trigger_store_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dir", default=None, help="file store root for triggers")
    parser.add_argument(
        "--db",
        default=None,
        help="Postgres URL for triggers (defaults to $TRIGGER_DATABASE_URL)",
    )


def _add_connector_request_store_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dir", default=None, help="file store root for connector requests")
    parser.add_argument(
        "--db",
        default=None,
        help="Postgres URL for connector requests (defaults to $CONNECTOR_REQUEST_DATABASE_URL)",
    )


def _add_agent_sandbox_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--agent-sandbox",
        action="store_true",
        help="run sandboxed agents in the agent sandbox instead of in-process",
    )
    parser.add_argument(
        "--allow-unsandboxed",
        action="store_true",
        help="allow --agent-sandbox on a platform without process limits (development)",
    )


def _add_tool_gateway_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--tool-gateway-url",
        default=None,
        help="tool gateway URL for sandboxed tool calls (enables tool grants)",
    )
    parser.add_argument(
        "--tool-gateway-token-env",
        default="ADK_TOOL_GATEWAY_TOKEN",
        help="env var holding the tool gateway bearer token",
    )


def _install_agent_sandbox(args: argparse.Namespace) -> None:
    """Register the process sandbox backend before registry agents load."""
    if not getattr(args, "agent_sandbox", False):
        return
    from .models import build_model
    from .sandbox.agent import set_agent_sandbox_backend
    from .sandbox.agent_process import ProcessAgentSandbox, agent_sandbox_supported

    if not agent_sandbox_supported() and not args.allow_unsandboxed:
        print(
            "--agent-sandbox requires POSIX process limits; "
            "pass --allow-unsandboxed for local development",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if not agent_sandbox_supported():
        print(
            "warning: the agent sandbox runs without process limits",
            file=sys.stderr,
        )
    tools: Any = None
    url = getattr(args, "tool_gateway_url", None)
    if url:
        from .tools.client import ToolGatewayClient
        from .tools.executor import gateway_executor

        token_env = getattr(args, "tool_gateway_token_env", "ADK_TOOL_GATEWAY_TOKEN")
        token = os.environ.get(token_env) if token_env else None
        if not token:
            print(
                f"warning: {token_env or '(unset)'} is not set; "
                "tool gateway calls will be unauthenticated",
                file=sys.stderr,
            )
        tools = gateway_executor(ToolGatewayClient(str(url), token=token))
    set_agent_sandbox_backend(ProcessAgentSandbox(model=build_model(), tools=tools))


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


def _model_policy_resolver(args: argparse.Namespace) -> Any:
    """Resolve the model policy from the registry by agent_ref (ADR-0028).

    Returns ``None`` when no registry is configured, so the gateway fails closed.
    """
    from .registry import FileAgentRegistry, HttpAgentRegistry

    url = getattr(args, "registry_url", None)
    registry: Any
    if url:
        if not url.startswith(("http://", "https://")):
            print(
                f"invalid --registry-url {url!r}: expected http:// or https://",
                file=sys.stderr,
            )
            raise SystemExit(1)
        registry = HttpAgentRegistry(url, auth_token=_registry_token(args))
    else:
        registry_dir = getattr(args, "registry", None)
        if not registry_dir:
            return None
        registry = FileAgentRegistry(registry_dir)

    async def resolve(invocation: Any) -> Any:
        record = await registry.get(invocation.agent_ref, invocation.principal.tenant)
        return record.manifest.model_policy if record is not None else None

    return resolve


def _tool_grant_resolver(args: argparse.Namespace) -> Any:
    """Resolve manifest tool grants from the registry by agent_ref (ADR-0028).

    Returns ``None`` when no registry is configured, so the gateway fails closed.
    """
    from .registry import FileAgentRegistry, HttpAgentRegistry

    url = getattr(args, "registry_url", None)
    registry: Any
    if url:
        if not url.startswith(("http://", "https://")):
            print(
                f"invalid --registry-url {url!r}: expected http:// or https://",
                file=sys.stderr,
            )
            raise SystemExit(1)
        registry = HttpAgentRegistry(url, auth_token=_registry_token(args))
    else:
        registry_dir = getattr(args, "registry", None)
        if not registry_dir:
            return None
        registry = FileAgentRegistry(registry_dir)

    async def resolve(invocation: Any) -> Any:
        record = await registry.get(invocation.agent_ref, invocation.principal.tenant)
        return record.manifest.tool_grants if record is not None else None

    return resolve


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


def _session_rls(args: argparse.Namespace) -> bool:
    if not getattr(args, "session_rls", False):
        return False
    if not getattr(args, "session_tenant_scope", False):
        print("--session-rls requires --session-tenant-scope", file=sys.stderr)
        raise SystemExit(1)
    url = os.environ.get("SESSION_URL")
    if not url or not url.startswith(("postgresql://", "postgresql+asyncpg://")):
        print("--session-rls requires a Postgres SESSION_URL", file=sys.stderr)
        raise SystemExit(1)
    _verify_session_rls(url)
    return True


def _verify_session_rls(url: str) -> None:
    try:
        from sqlalchemy.exc import DBAPIError

        from .runtime.session_rls import (
            SessionRlsUnavailable,
            engine_for_url,
            verify_session_rls,
        )
    except ImportError:
        print("session rls requires sqlalchemy and asyncpg", file=sys.stderr)
        raise SystemExit(1) from None

    engine = engine_for_url(url)

    async def _check() -> None:
        try:
            await verify_session_rls(engine)
        finally:
            await engine.dispose()

    try:
        asyncio.run(_check())
    except SessionRlsUnavailable as exc:
        print(f"session rls unavailable: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except DBAPIError as exc:
        print(f"session rls check failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None


def _oidc_config(args: argparse.Namespace) -> Any:
    if not getattr(args, "oidc_config", None):
        return None
    try:
        from .identity import OidcConfig

        return OidcConfig.model_validate_json(Path(args.oidc_config).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"invalid oidc config: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


def _identity_provider(args: argparse.Namespace) -> IdentityProvider | None:
    config = _oidc_config(args)
    if config is None:
        return None
    if getattr(args, "allow_unauthenticated", False):
        print("oidc config cannot combine with allow_unauthenticated", file=sys.stderr)
        raise SystemExit(1)
    from .identity import OidcIdentityProvider

    return OidcIdentityProvider(config)


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


def _audit_backend(args: argparse.Namespace) -> tuple[str | None, str | None, str | None]:
    audit_file = getattr(args, "audit_file", None)
    audit_url = getattr(args, "audit_url", None)
    audit_db = getattr(args, "audit_db", None)
    if audit_file or audit_url:
        return audit_file, audit_url, None
    if audit_db:
        return None, None, audit_db
    env_db = os.environ.get("AUDIT_DATABASE_URL") or None
    if env_db:
        return None, None, env_db
    return None, None, None


def _audit_sink(args: argparse.Namespace) -> AuditSink | None:
    from .audit import HttpAuditSink, JsonlAuditSink, PostgresAuditSink
    from .auth import LOOPBACK_HOSTS

    audit_file, audit_url, audit_db = _audit_backend(args)
    if audit_url:
        host = urlsplit(audit_url).hostname
        token = os.environ.get(args.audit_token_env) if args.audit_token_env else None
        if host not in LOOPBACK_HOSTS and token is None:
            raise SystemExit(
                f"refusing a non-loopback audit URL without a token: set "
                f"{args.audit_token_env} or use a loopback --audit-url"
            )
        return HttpAuditSink(audit_url, auth_token=token)
    if audit_file:
        return JsonlAuditSink(audit_file)
    if audit_db:
        signing_key, keyring = _audit_signing()
        return PostgresAuditSink(audit_db, signing_key=signing_key, keyring=keyring)
    return None


def _audit_query(args: argparse.Namespace) -> AuditQuery | None:
    from .audit import FileAuditQuery, HttpAuditQuery, PostgresAuditQuery
    from .auth import LOOPBACK_HOSTS

    audit_file, audit_url, audit_db = _audit_backend(args)
    if audit_url:
        host = urlsplit(audit_url).hostname
        token = os.environ.get(args.audit_token_env) if args.audit_token_env else None
        if host not in LOOPBACK_HOSTS and token is None:
            print(
                f"refusing a non-loopback audit URL without a token: set "
                f"{args.audit_token_env} or use a loopback --audit-url",
                file=sys.stderr,
            )
            raise SystemExit(1)
        return HttpAuditQuery(audit_url, auth_token=token)
    if audit_file:
        return FileAuditQuery(audit_file)
    if audit_db:
        return PostgresAuditQuery(audit_db)
    return None


def _approval_backend(
    explicit_dir: str | None,
    explicit_db: str | None,
    *,
    dir_flag: str = "--approval-dir",
    db_flag: str = "--approval-db",
) -> tuple[str, str] | None:
    if explicit_dir and explicit_db:
        print(f"{dir_flag} and {db_flag} are mutually exclusive", file=sys.stderr)
        raise SystemExit(1)
    if explicit_db:
        return ("db", explicit_db)
    if explicit_dir:
        return ("dir", explicit_dir)
    env_db = os.environ.get("APPROVAL_DATABASE_URL")
    if env_db:
        return ("db", env_db)
    env_dir = os.environ.get("ADK_APPROVAL_DIR")
    if env_dir:
        return ("dir", env_dir)
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
        if (
            args.key is not None
            or args.key_id is not None
            or args.artifact_dir is not None
            or getattr(args, "builder_key", None) is not None
            or getattr(args, "builder_key_id", None) is not None
        ):
            raise ValueError(
                "--key, --key-id, --artifact-dir and the builder key flags require --artifact"
            )
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
    builder_key = load_private_key(args.builder_key) if args.builder_key else None
    if (builder_key is None) != (args.builder_key_id is None):
        raise ValueError("set both --builder-key and --builder-key-id or neither")
    artifact = AgentArtifact(
        digest=digest,
        size=len(data),
        signature=sign_digest(digest, key),
        key_id=args.key_id,
        builder_signature=(sign_digest(digest, builder_key) if builder_key is not None else None),
        builder_key_id=args.builder_key_id,
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


def _peer_exit(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(2)


def _peer_a2a(args: argparse.Namespace) -> dict[str, Any] | None:
    """Return serve_a2a kwargs for peer mode, or None for legacy shared-token mode."""
    peer_flags = [
        getattr(args, "manifest", None),
        getattr(args, "peer_dir", None),
        getattr(args, "peer_db", None),
        getattr(args, "peer_token_file", None),
        getattr(args, "oidc_config", None),
    ]
    if not any(peer_flags):
        return None
    if not getattr(args, "manifest", None):
        _peer_exit("peer mode requires --manifest")
    if bool(getattr(args, "peer_dir", None)) == bool(getattr(args, "peer_db", None)):
        _peer_exit("set exactly one of --peer-dir or --peer-db")
    if bool(getattr(args, "oidc_config", None)) == bool(getattr(args, "peer_token_file", None)):
        _peer_exit("set exactly one of --oidc-config or --peer-token-file")
    if _auth_token(args) or getattr(args, "allow_unauthenticated", False):
        _peer_exit("peer mode cannot combine with --auth-token-env or --allow-unauthenticated")

    from .identity.peer_tokens import load_peer_tokens
    from .registry import (
        FilePeerGrantStore,
        FilePeerStore,
        PostgresPeerGrantStore,
        PostgresPeerStore,
    )
    from .registry.manifest import load_manifest

    try:
        manifest = load_manifest(args.manifest)
    except Exception as exc:  # noqa: BLE001
        print(f"invalid manifest: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    if manifest.exposure != "a2a":
        _peer_exit('peer mode requires a manifest with exposure "a2a"')

    peers: Any
    peer_grants: Any
    if args.peer_dir:
        peers = FilePeerStore(args.peer_dir)
        peer_grants = FilePeerGrantStore(args.peer_dir)
    else:
        peers = PostgresPeerStore(args.peer_db)
        peer_grants = PostgresPeerGrantStore(args.peer_db)

    if args.oidc_config:
        oidc = _identity_provider(args)
        peer_tokens = None
    else:
        oidc = None
        try:
            peer_tokens = load_peer_tokens(args.peer_token_file)
        except (ValueError, OSError) as exc:
            print(f"invalid peer token file: {exc}", file=sys.stderr)
            raise SystemExit(1) from None

    return {
        "oidc": oidc,
        "peers": peers,
        "peer_grants": peer_grants,
        "peer_tokens": peer_tokens,
        "manifest": manifest,
    }


def _rag_invocation(tenant: str, subject: str):
    from .core import Invocation, Principal
    from .runtime import dev_agent_ref

    return Invocation(
        run_id=uuid.uuid4().hex,
        trace_id=uuid.uuid4().hex,
        principal=Principal(tenant=tenant, subject=subject, kind="service"),
        agent_ref=dev_agent_ref("rag"),
        input="",
    )


def _rag_policy(args: argparse.Namespace):
    from .core import ModelPolicy

    return ModelPolicy(provider_allowlist=[args.provider], budget_usd=args.budget_usd)


def _rag_embedder(args: argparse.Namespace, sink: AuditSink | None):
    from .models.budget import BudgetTracker
    from .models.embeddings import EmbeddingGateway
    from .models.providers import LiteLlmProvider

    if args.provider != "litellm":
        print(f"unknown provider {args.provider!r}", file=sys.stderr)
        raise SystemExit(1)
    provider = LiteLlmProvider(
        api_key=os.environ.get("LITELLM_API_KEY"),
        api_base=os.environ.get("LITELLM_API_BASE"),
    )
    # The tracker is per process: a one-shot command only enforces --budget-usd 0
    # before its single embedding call, it cannot see spend from earlier runs.
    return EmbeddingGateway({args.provider: provider}, audit=sink, budgets=BudgetTracker())


def _read_rag_input(value: str | None, *, what: str) -> str:
    try:
        text = sys.stdin.read() if value is None else Path(value).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"could not read {what}: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
    if not text.strip():
        print(f"empty {what}", file=sys.stderr)
        raise SystemExit(1)
    return text


async def _rag_ingest(args: argparse.Namespace) -> None:
    from .rag.ingest import IngestionPipeline
    from .rag.vector_store import PgVectorRagStore

    if args.chunk_chars <= 0:
        print("--chunk-chars must be greater than 0", file=sys.stderr)
        raise SystemExit(1)
    text = _read_rag_input(args.text, what="text")
    sink = _audit_sink(args)
    store = PgVectorRagStore(args.database_url, dimensions=args.dimensions)
    try:
        pipeline = IngestionPipeline(
            store,
            _rag_embedder(args, sink),
            provider=args.provider,
            model=args.model,
            chunk_chars=args.chunk_chars,
        )
        count = await pipeline.ingest(
            _rag_invocation(args.tenant, "rag-ingest"),
            tenant=args.tenant,
            source_id=args.source_id,
            text=text,
            data_classes=list(args.data_classes),
            policy=_rag_policy(args),
            allowed_subjects=list(args.subjects) or None,
        )
    finally:
        await store.aclose()
    print(json.dumps({"tenant": args.tenant, "source_id": args.source_id, "chunks": count}))


async def _rag_search(args: argparse.Namespace) -> None:
    from .rag.guard import RagGuard
    from .rag.pgvector_service import PgVectorRagService
    from .rag.vector_store import PgVectorRagStore

    if args.limit <= 0:
        print("--limit must be greater than 0", file=sys.stderr)
        raise SystemExit(1)
    query = args.query if args.query is not None else sys.stdin.read()
    if not query.strip():
        print("empty query", file=sys.stderr)
        raise SystemExit(1)
    sink = _audit_sink(args)
    store = PgVectorRagStore(args.database_url, dimensions=args.dimensions)
    try:
        service = PgVectorRagService(
            store,
            _rag_embedder(args, sink),
            provider=args.provider,
            model=args.model,
            guard=RagGuard(min_confidence=args.min_confidence),
            limit=args.limit,
        )
        invocation = _rag_invocation(args.tenant, args.subject)
        citations = await service.retrieve(
            query,
            invocation.principal,
            list(args.data_classes),
            invocation=invocation,
            policy=_rag_policy(args),
        )
    finally:
        await store.aclose()
    payload = [citation.model_dump(mode="json") for citation in citations]
    print(json.dumps(payload))


def _run_rag(args: argparse.Namespace) -> None:
    from .models.gateway import ModelDenied
    from .rag.vector_store import RagStoreUnavailable

    try:
        if args.rag_cmd == "ingest":
            asyncio.run(_rag_ingest(args))
        else:
            asyncio.run(_rag_search(args))
    except (RagStoreUnavailable, ModelDenied, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception as exc:  # noqa: BLE001 - provider errors must not print a traceback
        print(f"rag failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None


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
    _add_tool_grant_args(p_serve)
    _add_rate_limit_args(p_serve)
    _add_agent_sandbox_args(p_serve)
    _add_tool_gateway_args(p_serve)
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
    p_serve.add_argument(
        "--session-rls",
        action="store_true",
        help="enforce tenant RLS on the Postgres session tables (needs --session-tenant-scope)",
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
    _add_tool_grant_args(p_many)
    _add_rate_limit_args(p_many)
    _add_agent_sandbox_args(p_many)
    _add_tool_gateway_args(p_many)
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
    p_many.add_argument(
        "--session-rls",
        action="store_true",
        help="enforce tenant RLS on the Postgres session tables (needs --session-tenant-scope)",
    )

    p_a2a = sub.add_parser("serve-a2a", help="serve an ADK agent over A2A (needs a2a-sdk)")
    p_a2a.add_argument("--agent", default=None, help="path to a Python file defining `agent`")
    p_a2a.add_argument(
        "--agent-ref",
        action="append",
        dest="agent_ref",
        default=None,
        help="registry reference TENANT/ID@VERSION (one for serve-a2a)",
    )
    p_a2a.add_argument(
        "--registry",
        default=os.environ.get("ADK_REGISTRY_DIR", "registry"),
        help="registry directory (defaults to $ADK_REGISTRY_DIR, then ./registry)",
    )
    _add_registry_client_args(p_a2a)
    p_a2a.add_argument(
        "--artifact-dir", default=None, help="content-addressed directory for artifact bytes"
    )
    p_a2a.add_argument(
        "--artifact-keys",
        default=None,
        help="JSON file mapping key id to a 64 hex Ed25519 public key",
    )
    _add_agent_sandbox_args(p_a2a)
    _add_tool_gateway_args(p_a2a)
    p_a2a.add_argument(
        "--rpc-path",
        default="",
        help="mount the RPC and agent-card routes under this path prefix",
    )
    _add_http_args(p_a2a)
    _add_audit_quota_args(p_a2a)
    _add_rate_limit_args(p_a2a)
    p_a2a.add_argument("--manifest", default=None, help="AgentManifest JSON (peer mode)")
    p_a2a.add_argument(
        "--peer-dir", default=None, help="peer and grant file store root (peer mode)"
    )
    p_a2a.add_argument(
        "--peer-db", default=None, help="Postgres URL for peers and grants (peer mode)"
    )
    p_a2a.add_argument("--peer-token-file", default=None, help="peer token hash file (peer mode)")
    p_a2a.add_argument(
        "--oidc-config",
        default=None,
        help="JSON OidcConfig file (peer mode identity)",
    )

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
    gateway_audit.add_argument(
        "--audit-db", default=None, help="write audit events directly to this Postgres URL"
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

    _add_registry_client_args(p_gateway)
    p_gateway.add_argument(
        "--registry",
        default=None,
        help="registry directory for server-side model policy (file backend)",
    )
    p_gateway.add_argument(
        "--trust-caller-policy",
        action="store_true",
        default=False,
        help="trust the caller-supplied policy (loopback dev only)",
    )

    p_gateway.add_argument(
        "--guardrails",
        default=None,
        help="JSON guardrail config file (default: disabled)",
    )

    p_tools = sub.add_parser(
        "serve-tool-gateway", help="serve the tool gateway as a standalone service"
    )
    p_tools.add_argument(
        "--tools",
        default=None,
        help="path to a Python file defining a `tools` mapping (tool_id -> callable or ToolSpec)",
    )
    p_tools.add_argument(
        "--connectors-dir",
        default=None,
        help="directory of registered connectors to expose as tools",
    )
    p_tools.add_argument(
        "--connector-tenant",
        default="local",
        help="tenant whose connectors are loaded (default: local)",
    )
    _add_credential_store_args(p_tools)
    _add_registry_client_args(p_tools)
    p_tools.add_argument(
        "--registry",
        default=None,
        help="registry directory for server-side tool grants (file backend)",
    )
    _add_tool_grant_args(p_tools)
    _add_idempotency_args(p_tools)
    p_tools.add_argument(
        "--trust-caller-policy",
        action="store_true",
        default=False,
        help="trust the caller-supplied grants (loopback dev only)",
    )
    tools_audit = p_tools.add_mutually_exclusive_group()
    tools_audit.add_argument("--audit-file", default=None, help="append JSONL audit events here")
    tools_audit.add_argument(
        "--audit-url", default=None, help="send audit events to this audit service URL"
    )
    tools_audit.add_argument(
        "--audit-db", default=None, help="write audit events directly to this Postgres URL"
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
    p_audit.add_argument("--out", default=None, help="append chained audit records here (JSONL)")
    p_audit.add_argument(
        "--audit-db", default=None, help="write chained audit records to this Postgres URL"
    )
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

    p_serve_triggers = sub.add_parser(
        "serve-triggers", help="serve the webhook trigger execution service"
    )
    p_serve_triggers.add_argument(
        "--triggers-dir", default=None, help="file store root for trigger definitions and fires"
    )
    p_serve_triggers.add_argument(
        "--trigger-db",
        default=None,
        help="Postgres URL for triggers and fires (defaults to $TRIGGER_DATABASE_URL)",
    )
    p_serve_triggers.add_argument("--registry", default=None, help="registry directory")
    _add_registry_client_args(p_serve_triggers)
    p_serve_triggers.add_argument(
        "--artifact-dir", default=None, help="content-addressed directory for artifact bytes"
    )
    p_serve_triggers.add_argument(
        "--artifact-keys",
        default=None,
        help="JSON file mapping key id to a 64 hex Ed25519 public key",
    )
    _add_tool_grant_args(p_serve_triggers)
    _add_audit_args(p_serve_triggers)
    p_serve_triggers.add_argument("--session-db", default=None, help="SQLite session database path")
    p_serve_triggers.add_argument("--quota-config", default=None, help="JSON QuotaConfig file")
    _add_rate_limit_args(p_serve_triggers)
    p_serve_triggers.add_argument(
        "--agent-sandbox",
        action="store_true",
        help="run sandboxed agents in the agent sandbox instead of in-process",
    )
    p_serve_triggers.add_argument(
        "--allow-unsandboxed",
        action="store_true",
        help="allow --agent-sandbox on a platform without process limits (development)",
    )
    p_serve_triggers.add_argument(
        "--schedule-tick", type=float, default=15.0, help="seconds between schedule ticks (min 5)"
    )
    p_serve_triggers.add_argument(
        "--trigger-attempts",
        type=int,
        default=3,
        help="pre-run load attempts per schedule fire (min 1)",
    )
    p_serve_triggers.add_argument(
        "--no-scheduler", action="store_true", help="serve webhooks without the schedule loop"
    )
    p_serve_triggers.add_argument("--host", default="127.0.0.1", help="HTTP bind host")
    p_serve_triggers.add_argument(
        "--port",
        type=int,
        default=None,
        help="HTTP bind port (defaults to $PORT, then 8000)",
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
        "--builder-keys",
        default=None,
        help="JSON file mapping builder key id to a 64 hex Ed25519 public key",
    )
    p_registry.add_argument(
        "--artifact-keys",
        default=None,
        help="JSON file mapping key id to a 64 hex Ed25519 public key",
    )
    _add_credential_store_args(p_registry)
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
    p_verify.add_argument("path", nargs="?", help="path to a chained audit JSONL file")
    p_verify.add_argument("--audit-db", default=None, help="Postgres audit database URL")

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
        "--connectors-dir",
        default=None,
        help="connector store directory for the Connectors panel (falls back to --registry-url)",
    )
    p_console.add_argument(
        "--connector-requests-dir",
        default=None,
        help="connector request store directory (or set CONNECTOR_REQUEST_DATABASE_URL)",
    )
    p_console.add_argument(
        "--connector-request-db",
        default=None,
        help="Postgres URL for connector requests (defaults to $CONNECTOR_REQUEST_DATABASE_URL)",
    )
    _add_credential_store_args(p_console)
    _add_peer_store_args(p_console)
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
        help="role for the console principal (repeatable; default: requester)",
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
        default=None,
        help="approval inbox directory (defaults to $ADK_APPROVAL_DIR)",
    )
    p_console.add_argument(
        "--approval-db",
        default=None,
        help="Postgres URL for the approval inbox (defaults to $APPROVAL_DATABASE_URL)",
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
    p_console.add_argument(
        "--session-rls",
        action="store_true",
        help="enforce tenant RLS on the Postgres session tables (needs --session-tenant-scope)",
    )
    _add_audit_args(p_console)
    _add_http_args(p_console)
    _add_rate_limit_args(p_console)
    _add_runtime_args(p_console)
    _add_tool_grant_args(p_console)
    _add_agent_sandbox_args(p_console)
    _add_tool_gateway_args(p_console)

    p_approvals = sub.add_parser("approvals", help="manage approval records")
    approvals_sub = p_approvals.add_subparsers(dest="approvals_cmd", required=True)
    p_prune = approvals_sub.add_parser("prune", help="archive or delete terminal approval records")
    p_prune.add_argument(
        "--dir",
        default=None,
        help="approval inbox directory (defaults to $ADK_APPROVAL_DIR)",
    )
    p_prune.add_argument(
        "--db",
        default=None,
        help="Postgres URL for approvals (defaults to $APPROVAL_DATABASE_URL)",
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

    p_sessions = sub.add_parser("sessions", help="manage the shared session store")
    sessions_sub = p_sessions.add_subparsers(dest="sessions_cmd", required=True)
    p_enable_rls = sessions_sub.add_parser(
        "enable-rls", help="install row-level security on the ADK session tables"
    )
    p_enable_rls.add_argument(
        "--database-url",
        default=None,
        help="Postgres session URL (defaults to $SESSION_URL)",
    )

    p_connectors = sub.add_parser("connectors", help="register and list external API connectors")
    connectors_sub = p_connectors.add_subparsers(dest="connectors_cmd", required=True)

    p_cl_list = connectors_sub.add_parser("list", help="list visible connectors")
    p_cl_list.add_argument("--tenant", required=True)
    p_cl_list.add_argument("--connectors-dir", default=None)
    _add_registry_client_args(p_cl_list)

    p_cl_register = connectors_sub.add_parser("register", help="register a connector")
    p_cl_register.add_argument("--connectors-dir", default=None)
    _add_credential_store_args(p_cl_register)
    p_cl_register.add_argument("--tenant", default=None)
    p_cl_register.add_argument("--id", required=True)
    p_cl_register.add_argument("--kind", required=True, choices=["http", "openapi", "mcp"])
    p_cl_register.add_argument("--base-url", required=True)
    p_cl_register.add_argument("--auth-ref", default=None)
    p_cl_register.add_argument("--methods", default="GET")
    p_cl_register.add_argument("--path-prefixes", default="/")
    p_cl_register.add_argument("--data-classes", default="")
    p_cl_register.add_argument("--timeout-seconds", type=int, default=10)
    p_cl_register.add_argument("--max-response-bytes", type=int, default=1024 * 1024)
    _add_registry_client_args(p_cl_register)

    p_cl_disable = connectors_sub.add_parser("disable", help="disable a connector")
    p_cl_disable.add_argument("--connectors-dir", default=None)
    p_cl_disable.add_argument("--id", required=True)
    _add_registry_client_args(p_cl_disable)

    p_cl_check = connectors_sub.add_parser("check", help="probe a connector's health")
    p_cl_check.add_argument("--connectors-dir", default=None)
    p_cl_check.add_argument("--id", required=True)
    _add_registry_client_args(p_cl_check)

    p_credentials = sub.add_parser(
        "credentials", help="manage tenant credential reference bindings"
    )
    credentials_sub = p_credentials.add_subparsers(dest="credentials_cmd", required=True)

    p_cr_list = credentials_sub.add_parser("list", help="list credential bindings")
    p_cr_list.add_argument("--tenant", required=True)
    _add_credential_store_args(p_cr_list)

    p_cr_register = credentials_sub.add_parser("register", help="register a binding")
    p_cr_register.add_argument("--tenant", required=True)
    p_cr_register.add_argument("--id", required=True)
    p_cr_register.add_argument("--secret-ref", dest="secret_ref", required=True)
    p_cr_register.add_argument("--description", default="")
    p_cr_register.add_argument(
        "--secret-stdin",
        action="store_true",
        help=(
            "read the secret from stdin and store it encrypted "
            "(needs ADK_SECRET_KEKS/ADK_SECRET_KEKS_FILE, or ADK_SECRET_BACKEND=vault)"
        ),
    )
    _add_credential_store_args(p_cr_register)

    p_cr_disable = credentials_sub.add_parser("disable", help="disable a binding")
    p_cr_disable.add_argument("--tenant", required=True)
    p_cr_disable.add_argument("--id", required=True)
    _add_credential_store_args(p_cr_disable)

    p_cr_rewrap = credentials_sub.add_parser(
        "rewrap",
        help=(
            "re-wrap credential data keys under the active key backend "
            "(needs ADK_SECRET_KEKS/ADK_SECRET_KEKS_FILE, or ADK_SECRET_BACKEND=vault)"
        ),
    )
    p_cr_rewrap.add_argument("--tenant", required=True)
    p_cr_rewrap.add_argument(
        "--dry-run", action="store_true", help="report what would change without writing"
    )
    _add_credential_store_args(p_cr_rewrap)

    p_cr_migrate = credentials_sub.add_parser(
        "migrate",
        help=(
            "move local KEK records to the Vault backend "
            "(needs ADK_SECRET_KEKS/ADK_SECRET_KEKS_FILE and ADK_SECRET_BACKEND=vault)"
        ),
    )
    p_cr_migrate.add_argument("--to", required=True, choices=["vault"])
    p_cr_migrate.add_argument("--tenant", required=True)
    p_cr_migrate.add_argument(
        "--dry-run", action="store_true", help="report what would migrate without writing"
    )
    _add_credential_store_args(p_cr_migrate)

    p_triggers = sub.add_parser("triggers", help="manage scheduled and webhook trigger definitions")
    triggers_sub = p_triggers.add_subparsers(dest="triggers_cmd", required=True)

    p_tr_list = triggers_sub.add_parser("list", help="list trigger definitions")
    p_tr_list.add_argument("--tenant", required=True)
    _add_trigger_store_args(p_tr_list)

    p_tr_register = triggers_sub.add_parser("register", help="register a trigger definition")
    p_tr_register.add_argument("--tenant", required=True)
    p_tr_register.add_argument("--id", required=True)
    p_tr_register.add_argument("--agent-id", required=True)
    p_tr_register.add_argument("--version", required=True)
    p_tr_register.add_argument("--digest", required=True)
    trigger_kind = p_tr_register.add_mutually_exclusive_group(required=True)
    trigger_kind.add_argument("--every-seconds", type=int, default=None)
    trigger_kind.add_argument("--webhook-token-env", default=None)
    p_tr_register.add_argument("--input", default="")
    _add_trigger_store_args(p_tr_register)

    p_tr_disable = triggers_sub.add_parser("disable", help="disable a trigger")
    p_tr_disable.add_argument("--tenant", required=True)
    p_tr_disable.add_argument("--id", required=True)
    _add_trigger_store_args(p_tr_disable)

    p_connector_requests = sub.add_parser(
        "connector-requests", help="request and decide connector registrations"
    )
    connector_requests_sub = p_connector_requests.add_subparsers(
        dest="connector_requests_cmd", required=True
    )

    p_cor_list = connector_requests_sub.add_parser("list", help="list connector requests")
    p_cor_list.add_argument("--tenant", required=True)
    p_cor_list.add_argument("--status", default=None)
    _add_connector_request_store_args(p_cor_list)

    p_cor_request = connector_requests_sub.add_parser(
        "request", help="request a connector registration"
    )
    p_cor_request.add_argument("--tenant", required=True)
    p_cor_request.add_argument("--id", required=True)
    p_cor_request.add_argument("--kind", required=True, choices=["http", "openapi", "mcp"])
    p_cor_request.add_argument("--base-url", required=True)
    p_cor_request.add_argument("--auth-ref", default=None)
    p_cor_request.add_argument("--methods", default="GET")
    p_cor_request.add_argument("--path-prefixes", default="/")
    p_cor_request.add_argument("--data-classes", default="")
    p_cor_request.add_argument("--reason", required=True)
    _add_connector_request_store_args(p_cor_request)

    p_cor_decide = connector_requests_sub.add_parser(
        "decide", help="approve or deny a connector request"
    )
    p_cor_decide.add_argument("request_id")
    decision = p_cor_decide.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--deny", action="store_true")
    p_cor_decide.add_argument("--reason", default="")
    p_cor_decide.add_argument("--connectors-dir", default=None)
    _add_registry_client_args(p_cor_decide)
    _add_credential_store_args(p_cor_decide)
    _add_connector_request_store_args(p_cor_decide)

    p_peers = sub.add_parser("peers", help="manage A2A peers and their action grants")
    peers_sub = p_peers.add_subparsers(dest="peers_cmd", required=True)

    p_pe_list = peers_sub.add_parser("list", help="list peers with their grants")
    p_pe_list.add_argument("--tenant", default=None)
    _add_peer_store_args(p_pe_list)

    p_pe_register = peers_sub.add_parser("register", help="register a peer identity")
    p_pe_register.add_argument("--id", required=True)
    p_pe_register.add_argument("--tenant", required=True)
    p_pe_register.add_argument("--subject", default=None)
    p_pe_register.add_argument("--kind", default="service", choices=["service", "human", "agent"])
    p_pe_register.add_argument("--roles", default="")
    _add_peer_store_args(p_pe_register)

    p_pe_disable = peers_sub.add_parser("disable", help="disable a peer")
    p_pe_disable.add_argument("--id", required=True)
    _add_peer_store_args(p_pe_disable)

    p_pe_grant = peers_sub.add_parser("grant", help="grant agent actions to a peer")
    p_pe_grant.add_argument("--id", required=True)
    p_pe_grant.add_argument("--agent", required=True)
    p_pe_grant.add_argument("--actions", required=True)
    _add_peer_store_args(p_pe_grant)

    p_pe_revoke = peers_sub.add_parser("revoke", help="revoke an agent grant from a peer")
    p_pe_revoke.add_argument("--id", required=True)
    p_pe_revoke.add_argument("--agent", required=True)
    _add_peer_store_args(p_pe_revoke)

    p_remote = sub.add_parser("remote-agents", help="manage remote A2A agent catalog records")
    remote_sub = p_remote.add_subparsers(dest="remote_cmd", required=True)

    p_ra_list = remote_sub.add_parser("list", help="list remote agents")
    p_ra_list.add_argument("--tenant", default=None)
    _add_peer_store_args(p_ra_list)

    p_ra_register = remote_sub.add_parser("register", help="register a remote agent card")
    p_ra_register.add_argument("--id", required=True)
    p_ra_register.add_argument("--tenant", required=True)
    p_ra_register.add_argument("--peer", required=True)
    p_ra_register.add_argument("--card-url", required=True)
    p_ra_register.add_argument("--credential-ref", default=None)
    p_ra_register.add_argument("--label", default="")
    _add_peer_store_args(p_ra_register)
    _add_credential_store_args(p_ra_register)

    p_ra_refresh = remote_sub.add_parser("refresh", help="refresh a remote agent card")
    p_ra_refresh.add_argument("--id", required=True)
    _add_peer_store_args(p_ra_refresh)
    _add_credential_store_args(p_ra_refresh)

    p_ra_disable = remote_sub.add_parser("disable", help="disable a remote agent record")
    p_ra_disable.add_argument("--id", required=True)
    _add_peer_store_args(p_ra_disable)

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

    p_tool_grants = sub.add_parser("tool-grants", help="manage temporary tool grant requests")
    tool_grants_sub = p_tool_grants.add_subparsers(dest="tool_grants_cmd", required=True)

    p_tg_list = tool_grants_sub.add_parser("list", help="list grant requests")
    p_tg_list.add_argument("--tenant", required=True)
    p_tg_list.add_argument(
        "--status", default=None, help="pending, approved, denied, expired, cancelled"
    )
    _add_tool_grant_args(p_tg_list)

    p_tg_request = tool_grants_sub.add_parser("request", help="create a pending grant request")
    p_tg_request.add_argument("--tenant", required=True)
    p_tg_request.add_argument("--id", required=True)
    p_tg_request.add_argument("--version", required=True)
    p_tg_request.add_argument("--digest", required=True)
    p_tg_request.add_argument("--tool", required=True)
    p_tg_request.add_argument("--reason", required=True)
    p_tg_request.add_argument("--expires-hours", type=int, default=24)
    _add_tool_grant_args(p_tg_request)

    p_tg_decide = tool_grants_sub.add_parser("decide", help="approve or deny a grant request")
    p_tg_decide.add_argument("request_id")
    decision = p_tg_decide.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--deny", action="store_true")
    p_tg_decide.add_argument("--reason", default="")
    _add_tool_grant_args(p_tg_decide)

    p_rag = sub.add_parser("rag", help="ingest documents into and search the pgvector RAG store")
    rag_sub = p_rag.add_subparsers(dest="rag_cmd", required=True)

    p_rag_ingest = rag_sub.add_parser("ingest", help="chunk, embed, and store one source")
    p_rag_ingest.add_argument("--database-url", required=True)
    p_rag_ingest.add_argument("--dimensions", type=int, required=True)
    p_rag_ingest.add_argument("--model", required=True)
    p_rag_ingest.add_argument("--provider", default="litellm")
    p_rag_ingest.add_argument("--tenant", required=True)
    p_rag_ingest.add_argument("--source-id", required=True)
    p_rag_ingest.add_argument("--text", default=None, help="file to ingest; stdin when omitted")
    p_rag_ingest.add_argument(
        "--data-class", dest="data_classes", action="append", default=[], choices=_DATA_CLASSES
    )
    p_rag_ingest.add_argument("--subject", dest="subjects", action="append", default=[])
    p_rag_ingest.add_argument("--chunk-chars", type=int, default=800)
    p_rag_ingest.add_argument("--budget-usd", type=float, default=None)
    _add_audit_args(p_rag_ingest)

    p_rag_search = rag_sub.add_parser("search", help="retrieve ACL-checked citations")
    p_rag_search.add_argument("--database-url", required=True)
    p_rag_search.add_argument("--dimensions", type=int, required=True)
    p_rag_search.add_argument("--model", required=True)
    p_rag_search.add_argument("--provider", default="litellm")
    p_rag_search.add_argument("--tenant", required=True)
    p_rag_search.add_argument("--subject", default="rag-search")
    p_rag_search.add_argument("--query", default=None, help="query text; stdin when omitted")
    p_rag_search.add_argument(
        "--data-class", dest="data_classes", action="append", default=[], choices=_DATA_CLASSES
    )
    p_rag_search.add_argument("--limit", type=int, default=10)
    p_rag_search.add_argument("--min-confidence", type=float, default=0.5)
    p_rag_search.add_argument("--budget-usd", type=float, default=None)
    _add_audit_args(p_rag_search)

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
    p_publish.add_argument(
        "--builder-keys",
        default=None,
        help="JSON file mapping builder key id to a 64 hex Ed25519 public key",
    )
    p_publish.add_argument(
        "--builder-key",
        default=None,
        help="PEM Ed25519 private key that signs in_process artifacts",
    )
    p_publish.add_argument(
        "--builder-key-id",
        default=None,
        help="builder key id recorded with the artifact",
    )

    sub.add_parser("templates", help="list composition templates")

    p_compose = sub.add_parser("compose", help="compose and publish an agent from a template")
    p_compose.add_argument("--template", required=True, help="template id (see `templates`)")
    p_compose.add_argument(
        "--builder-key",
        default=None,
        help="PEM Ed25519 private key that signs in_process artifacts",
    )
    p_compose.add_argument(
        "--builder-key-id",
        default=None,
        help="builder key id recorded with the artifact",
    )
    p_compose.add_argument("--tenant", required=True, help="tenant the agent belongs to")
    p_compose.add_argument("--id", dest="agent_id", required=True, help="agent id")
    p_compose.add_argument("--version", required=True, help="agent version")
    p_compose.add_argument("--instruction", required=True, help="system instruction")
    p_compose.add_argument("--owner", default=None, help="owner label (defaults to the tenant)")
    p_compose.add_argument("--description", default=None, help="agent description")
    p_compose.add_argument("--tools", default="", help="comma-separated tools (subset of ping)")
    p_compose.add_argument(
        "--data-classes", dest="data_classes", default="", help="comma-separated data classes"
    )
    p_compose.add_argument("--key", default=None, help="PEM Ed25519 private key")
    p_compose.add_argument("--key-id", dest="key_id", default=None, help="key id for the signature")
    p_compose.add_argument(
        "--registry",
        default=os.environ.get("ADK_REGISTRY_DIR", "registry"),
        help="registry directory (defaults to $ADK_REGISTRY_DIR, then ./registry)",
    )
    _add_registry_client_args(p_compose)
    p_compose.add_argument(
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

    from .observability import configure_otel

    configure_otel()

    if args.cmd == "serve":
        _install_agent_sandbox(args)
        rate_limit = _rate_limit(args)
        session_rls = _session_rls(args)
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
        from .sandbox.proxy import SandboxAgent
        from .tools import install_declared_guards

        if not isinstance(agent, SandboxAgent):
            install_declared_guards(agent, audit, overlay=_tool_grant_store(args))
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
            runner=build_runner(agent, args.session_db, session_rls=session_rls),
            audit=audit,
            quota=quota,
            quota_config=quota_config,
            metrics=metrics,
            rate_limit=rate_limit,
            session_tenant_scope=args.session_tenant_scope,
            tool_guard=True,
        )
    elif args.cmd == "serve-many":
        _install_agent_sandbox(args)
        rate_limit = _rate_limit(args)
        session_rls = _session_rls(args)
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
            partial(
                build_runner,
                session_db=args.session_db,
                session_rls=session_rls,
            )
            if args.session_db or os.environ.get("SESSION_URL")
            else None
        )
        audit = _audit_sink(args)
        from .sandbox.proxy import SandboxAgent
        from .tools import install_declared_guards

        tool_grants = _tool_grant_store(args)
        for loaded_agent in agents.values():
            if not isinstance(loaded_agent, SandboxAgent):
                install_declared_guards(loaded_agent, audit, overlay=tool_grants)
        quota, quota_config = _quota_settings(args)
        metrics = None
        if args.metrics:
            from .metrics import MetricsRegistry

            metrics = MetricsRegistry()
        serve_many(
            agents=agents,
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
            tool_guard=True,
        )
    elif args.cmd == "serve-a2a":
        _install_agent_sandbox(args)
        rate_limit = _rate_limit(args)
        from .a2a import A2aUnavailable, serve_a2a
        from .sandbox.proxy import SandboxAgent
        from .tools import install_declared_guards

        if (args.agent is not None) == (args.agent_ref is not None):
            print("provide exactly one of --agent or --agent-ref", file=sys.stderr)
            raise SystemExit(1)
        if args.agent_ref:
            if len(args.agent_ref) != 1:
                print("serve-a2a accepts exactly one --agent-ref", file=sys.stderr)
                raise SystemExit(1)
            loaded = _registry_agents(args) or {}
            if not loaded:
                print("registry load produced no agent", file=sys.stderr)
                raise SystemExit(1)
            agent = next(iter(loaded.values()))
        else:
            agent = _load_agent(args.agent)
        audit = _audit_sink(args)
        if not isinstance(agent, SandboxAgent):
            install_declared_guards(agent, audit)
        quota, quota_config = _quota_settings(args)
        peer = _peer_a2a(args)
        if peer is not None and args.agent_ref is not None and agent.name != peer["manifest"].id:
            print("loaded agent name does not match --manifest id", file=sys.stderr)
            raise SystemExit(1)
        try:
            serve_a2a(
                agent=agent,
                host=args.host,
                port=args.port,
                rpc_path=args.rpc_path,
                auth_token=None if peer else _auth_token(args),
                allow_unauthenticated=False if peer else args.allow_unauthenticated,
                audit=audit,
                quota=quota,
                quota_config=quota_config,
                rate_limit=rate_limit,
                require_context=True,
                **(peer or {}),
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
        from .guardrails import GuardrailConfigError, build_guardrail_pipeline

        try:
            guardrails = build_guardrail_pipeline(args.guardrails)
        except GuardrailConfigError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None
        trust_caller_policy = _trust_caller_policy(args)
        app = build_model_gateway_app(
            PolicyModelGateway(providers, audit=sink, guardrails=guardrails),
            host=args.host,
            auth_token=_auth_token(args),
            allow_unauthenticated=args.allow_unauthenticated,
            oidc=oidc,
            metrics=metrics,
            rate_limit=rate_limit,
            policy_resolver=None if trust_caller_policy else _model_policy_resolver(args),
            trust_caller_policy=trust_caller_policy,
        )

        import uvicorn

        uvicorn.run(app, host=args.host, port=resolve_port(args.port), log_level="info")
    elif args.cmd == "serve-tool-gateway":
        rate_limit = _rate_limit(args)
        from .core import CredentialStoreError
        from .mcp.http import resolve_port
        from .registry import FileConnectorStore
        from .registry.connectors_postgres import PostgresConnectorStore
        from .secretstore import (
            KeyBackendError,
            PrefixedEnvSecretProvider,
            RoutingSecretProvider,
            TenantScopedSecretProvider,
            TenantSecretProvider,
            load_key_backend,
        )
        from .tools import FunctionRegistry, FunctionToolGateway
        from .tools.connectors import build_connector_tools
        from .tools.service import build_tool_gateway_app

        sink = _audit_sink(args)
        connector_url = os.environ.get("CONNECTOR_URL")
        connector_source = bool(args.connectors_dir) + bool(connector_url)
        if args.connectors_dir and connector_url:
            print("set exactly one of --connectors-dir or CONNECTOR_URL", file=sys.stderr)
            raise SystemExit(1)
        if not args.tools and connector_source == 0:
            print("provide --tools, --connectors-dir or CONNECTOR_URL", file=sys.stderr)
            raise SystemExit(1)

        credential_flags = bool(
            getattr(args, "credentials_dir", None)
            or getattr(args, "credential_db", None)
            or os.environ.get("CREDENTIAL_DATABASE_URL")
        )
        if credential_flags and connector_source == 0:
            print(
                "--credentials-dir and --credential-db require --connectors-dir or CONNECTOR_URL",
                file=sys.stderr,
            )
            raise SystemExit(1)
        try:
            credential_store: Any = _credential_store(args)
        except CredentialStoreError as exc:
            print(f"invalid credential store: {exc}", file=sys.stderr)
            raise SystemExit(1) from None
        if connector_source:
            specs = _load_tools(args.tools).specs() if args.tools else []
            connector_store = (
                PostgresConnectorStore(connector_url)
                if connector_url
                else FileConnectorStore(args.connectors_dir)
            )
            connector_specs = asyncio.run(connector_store.list(args.connector_tenant))
            inner: Any = PrefixedEnvSecretProvider()
            if credential_store is not None:
                try:
                    key_backend = load_key_backend()
                except KeyBackendError as exc:
                    print(
                        _key_backend_message(exc),
                        file=sys.stderr,
                    )
                    raise SystemExit(1) from None
                inner = RoutingSecretProvider(
                    TenantSecretProvider(key_backend, credential_store, audit=sink),
                    inner,
                )
            specs.extend(
                build_connector_tools(
                    connector_specs,
                    secrets=TenantScopedSecretProvider(inner, args.connector_tenant),
                )
            )
            try:
                tool_registry = FunctionRegistry(specs)
            except ValueError as exc:
                print(f"invalid tool set: {exc}", file=sys.stderr)
                raise SystemExit(1) from None
        else:
            tool_registry = _load_tools(args.tools)
        oidc = _identity_provider(args)
        trust_caller_policy = _trust_caller_policy(args)
        app = build_tool_gateway_app(
            FunctionToolGateway(tool_registry, audit=sink, idempotency=_idempotency_store(args)),
            host=args.host,
            auth_token=_auth_token(args),
            allow_unauthenticated=args.allow_unauthenticated,
            oidc=oidc,
            rate_limit=rate_limit,
            grant_resolver=None if trust_caller_policy else _tool_grant_resolver(args),
            tool_grants=None if trust_caller_policy else _tool_grant_store(args),
            trust_caller_policy=trust_caller_policy,
        )

        import uvicorn

        uvicorn.run(app, host=args.host, port=resolve_port(args.port), log_level="info")
        from .registry.credentials_postgres import PostgresCredentialStore

        if isinstance(credential_store, PostgresCredentialStore):
            # The pool may have opened in uvicorn's loop, which is now closed;
            # a cross-loop close is best-effort and must not fail shutdown.
            with contextlib.suppress(Exception):
                asyncio.run(credential_store.aclose())
    elif args.cmd == "serve-audit":
        rate_limit = _rate_limit(args)
        from .audit import AuditPipeline, PostgresAuditSink, query_audit_records
        from .audit.service import build_audit_pipeline_app
        from .mcp.http import resolve_port

        if args.out and args.audit_db:
            print("serve-audit requires exactly one of --out or --audit-db", file=sys.stderr)
            raise SystemExit(2)
        db_url = args.audit_db or (
            None if args.out else (os.environ.get("AUDIT_DATABASE_URL") or None)
        )
        if not args.out and not db_url:
            print(
                "serve-audit requires --out or --audit-db (or set AUDIT_DATABASE_URL)",
                file=sys.stderr,
            )
            raise SystemExit(2)
        if args.audit_max_records is not None and args.audit_max_records <= 0:
            print("--audit-max-records must be greater than 0", file=sys.stderr)
            raise SystemExit(1)
        if db_url and args.audit_max_records is not None:
            print("--audit-max-records only applies to --out (file mode)", file=sys.stderr)
            raise SystemExit(2)
        signing_key, keyring = _audit_signing()
        oidc = _identity_provider(args)
        if db_url:
            app = build_audit_pipeline_app(
                PostgresAuditSink(db_url, signing_key=signing_key, keyring=keyring),
                host=args.host,
                auth_token=_auth_token(args),
                allow_unauthenticated=args.allow_unauthenticated,
                oidc=oidc,
                rate_limit=rate_limit,
                query=lambda **kwargs: query_audit_records(db_url, **kwargs),
            )
        else:
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
    elif args.cmd == "serve-triggers":
        if args.agent_sandbox:
            from .sandbox.agent_process import agent_sandbox_supported

            if not agent_sandbox_supported() and not args.allow_unsandboxed:
                print(
                    "--agent-sandbox requires POSIX process limits; "
                    "pass --allow-unsandboxed for local development",
                    file=sys.stderr,
                )
                raise SystemExit(1)
            if not agent_sandbox_supported():
                print(
                    "warning: the agent sandbox runs without process limits",
                    file=sys.stderr,
                )
        if args.schedule_tick < 5:
            print("--schedule-tick must be at least 5 seconds", file=sys.stderr)
            raise SystemExit(1)
        if args.trigger_attempts < 1:
            print("--trigger-attempts must be at least 1", file=sys.stderr)
            raise SystemExit(1)
        rate_limit = _rate_limit(args)
        from google.adk.sessions import InMemorySessionService

        from .mcp.http import resolve_port
        from .registry import (
            FileTriggerFireStore,
            FileTriggerStore,
            InProcessArtifactLoader,
            PostgresTriggerFireStore,
            PostgresTriggerStore,
        )
        from .runtime.sessions import configured_session_service
        from .triggers_service import build_triggers_app

        env_db = os.environ.get("TRIGGER_DATABASE_URL")
        if args.triggers_dir and args.trigger_db:
            print("set exactly one of --triggers-dir or --trigger-db", file=sys.stderr)
            raise SystemExit(1)
        if args.triggers_dir and env_db:
            print("--triggers-dir conflicts with TRIGGER_DATABASE_URL", file=sys.stderr)
            raise SystemExit(1)
        database_url = args.trigger_db or env_db
        if not args.triggers_dir and not database_url:
            print(
                "trigger store is required: provide --triggers-dir, --trigger-db, "
                "or set TRIGGER_DATABASE_URL",
                file=sys.stderr,
            )
            raise SystemExit(1)
        triggers: Any
        if args.triggers_dir:
            triggers = FileTriggerStore(args.triggers_dir)
            fire_store: Any = FileTriggerFireStore(args.triggers_dir)
        else:
            triggers = PostgresTriggerStore(cast("str", database_url))
            fire_store = PostgresTriggerFireStore(cast("str", database_url))

        if not args.registry and not args.registry_url:
            print(
                "registry is required: provide --registry DIR or --registry-url URL",
                file=sys.stderr,
            )
            raise SystemExit(1)
        registry = _agent_registry(args)
        artifact_store = _artifact_store(args)
        if artifact_store is None:
            print(
                "artifact store is required: provide --artifact-dir or set ARTIFACT_URL",
                file=sys.stderr,
            )
            raise SystemExit(1)
        trust = _artifact_trust(args)
        if trust is None:
            print(
                "artifact trust keys are required: provide --artifact-keys "
                "or set ADK_ARTIFACT_KEYS",
                file=sys.stderr,
            )
            raise SystemExit(1)

        quota, quota_config = _quota_settings(args)
        sandbox: Any = None
        if args.agent_sandbox:
            from .models import build_model
            from .sandbox.agent_process import ProcessAgentSandbox

            sandbox = ProcessAgentSandbox(model=build_model())
        app = build_triggers_app(
            triggers=triggers,
            registry=registry,
            artifact_store=artifact_store,
            trust=trust,
            loader=InProcessArtifactLoader(),
            lifecycle=_lifecycle_source(args, registry),
            tool_grants=_tool_grant_store(args),
            audit=_audit_sink(args),
            quota=quota,
            quota_config=quota_config,
            session_service=configured_session_service(args.session_db) or InMemorySessionService(),
            rate_limit=rate_limit,
            fire_store=fire_store,
            sandbox=sandbox,
            scheduler=not args.no_scheduler,
            schedule_tick=args.schedule_tick,
            trigger_attempts=args.trigger_attempts,
        )

        import uvicorn

        uvicorn.run(app, host=args.host, port=resolve_port(args.port), log_level="info")

        for backend in (triggers, fire_store):
            close = getattr(backend, "aclose", None)
            if close is not None:
                # The pool may have opened in uvicorn's loop, which is now closed.
                with contextlib.suppress(Exception):
                    asyncio.run(close())
    elif args.cmd == "serve-registry":
        rate_limit = _rate_limit(args)
        from .mcp.http import resolve_port
        from .registry import (
            ArtifactStoreError,
            FileArtifactStore,
            PostgresAgentLifecycleStore,
            PostgresAgentRegistry,
            PostgresConnectorStore,
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
            connectors = PostgresConnectorStore(args.database_url)
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
        from .core import CredentialStoreError
        from .secretstore import KeyBackendError, load_key_backend

        try:
            credential_store = _credential_store(args)
        except CredentialStoreError as exc:
            print(f"invalid credential store: {exc}", file=sys.stderr)
            raise SystemExit(1) from None
        try:
            key_backend = load_key_backend()
        except KeyBackendError as exc:
            print(_key_backend_message(exc), file=sys.stderr)
            raise SystemExit(1) from None
        app = build_registry_service_app(
            registry,
            artifact_store=store,
            eval_reports=eval_reports,
            lifecycle=lifecycle,
            connectors=connectors,
            credentials=credential_store,
            key_backend=key_backend,
            audit=_audit_sink(args),
            trust=_artifact_trust(args),
            builder_keys=_builder_trust(args),
            host=args.host,
            auth_token=_auth_token(args),
            allow_unauthenticated=args.allow_unauthenticated,
            oidc=oidc,
            rate_limit=rate_limit,
        )

        import uvicorn

        uvicorn.run(app, host=args.host, port=resolve_port(args.port), log_level="info")
        from .registry.credentials_postgres import PostgresCredentialStore

        if isinstance(credential_store, PostgresCredentialStore):
            # Same cross-loop caveat as the console command.
            with contextlib.suppress(Exception):
                asyncio.run(credential_store.aclose())
    elif args.cmd == "verify-audit":
        from .audit import (
            AuditChainBroken,
            AuditSignatureInvalid,
            verify_audit_database,
            verify_audit_file,
        )

        if (args.path is None) == (args.audit_db is None):
            print("verify-audit requires exactly one of FILE or --audit-db", file=sys.stderr)
            raise SystemExit(2)

        signing_key, keyring = _audit_signing()
        try:
            if args.audit_db is not None:
                count = asyncio.run(
                    verify_audit_database(args.audit_db, signing_key=signing_key, keyring=keyring)
                )
            else:
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
        _install_agent_sandbox(args)
        rate_limit = _rate_limit(args)
        session_rls = _session_rls(args)
        from .audit import PostgresAuditQuery
        from .console import run_console
        from .registry import (
            FileAgentLifecycleStore,
            FileConnectorStore,
            FileEvalReportStore,
            HttpConnectorStore,
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
        oidc_config = _oidc_config(args)
        oidc_login = None
        if oidc_config is not None and oidc_config.browser is not None:
            from .identity import OidcLogin

            oidc_login = OidcLogin(oidc_config.browser)
        quota, quota_config = _quota_settings(args)
        approval_backend = _approval_backend(args.approval_dir, args.approval_db)
        approvals: Any = None
        if approval_backend is not None:
            if approval_backend[0] == "db":
                from .approvals_postgres import PostgresApprovalInbox

                approvals = PostgresApprovalInbox(
                    approval_backend[1], ttl_seconds=args.approval_ttl
                )
            else:
                from .approvals import FileApprovalInbox

                approvals = FileApprovalInbox(
                    Path(approval_backend[1]), ttl_seconds=args.approval_ttl
                )

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
        tool_grants = _tool_grant_store(args)
        console_connectors: Any = None
        if args.connectors_dir:
            console_connectors = FileConnectorStore(args.connectors_dir)
        elif args.registry_url:
            console_connectors = HttpConnectorStore(
                args.registry_url, auth_token=_registry_token(args)
            )
        else:
            console_connectors = None
        console_credentials: Any = _credential_store(args)
        if console_credentials is not None:
            from .secretstore import KeyBackendError, load_key_backend

            try:
                load_key_backend()
            except KeyBackendError as exc:
                print(_key_backend_message(exc), file=sys.stderr)
                raise SystemExit(1) from None
        console_connector_requests: Any = _connector_request_store(args)
        console_peers: Any = None
        console_peer_grants: Any = None
        console_remote_agents: Any = None
        if args.peer_dir or args.peer_db:
            console_peers, console_peer_grants = _peer_stores(args)
            console_remote_agents = _remote_agent_store(args)
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
            tool_grants=tool_grants,
            connectors=console_connectors,
            connector_requests=console_connector_requests,
            credentials=console_credentials,
            peers=console_peers,
            peer_grants=console_peer_grants,
            remote_agents=console_remote_agents,
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
            oidc_login=oidc_login,
            quota=quota,
            quota_config=quota_config,
            approvals=approvals,
            sse_queue_size=args.sse_queue_size,
            rate_limit=rate_limit,
            session_tenant_scope=args.session_tenant_scope,
            session_rls=session_rls,
        )
        if isinstance(audit_query, PostgresAuditQuery):
            # The pool may have opened in uvicorn's loop, which is now closed;
            # a cross-loop close is best-effort and must not fail shutdown.
            with contextlib.suppress(Exception):
                asyncio.run(audit_query.aclose())
        from .approvals_postgres import PostgresApprovalInbox

        if isinstance(approvals, PostgresApprovalInbox):
            # Same cross-loop caveat as the audit query above.
            with contextlib.suppress(Exception):
                asyncio.run(approvals.aclose())
        from .registry.credentials_postgres import PostgresCredentialStore

        if isinstance(console_credentials, PostgresCredentialStore):
            # Same cross-loop caveat as the audit query above.
            with contextlib.suppress(Exception):
                asyncio.run(console_credentials.aclose())
        from .registry.connector_requests_postgres import PostgresConnectorRequestStore

        if isinstance(console_connector_requests, PostgresConnectorRequestStore):
            # Same cross-loop caveat as the audit query above.
            with contextlib.suppress(Exception):
                asyncio.run(console_connector_requests.aclose())
    elif args.cmd == "approvals":
        backend = _approval_backend(args.dir, args.db, dir_flag="--dir", db_flag="--db")
        if backend is None:
            print(
                "approval dir is required: provide --dir or --db, "
                "or set ADK_APPROVAL_DIR or APPROVAL_DATABASE_URL",
                file=sys.stderr,
            )
            raise SystemExit(1)
        if args.older_than <= 0:
            print("--older-than must be greater than 0", file=sys.stderr)
            raise SystemExit(1)
        kind, value = backend
        if kind == "db":
            from .approvals import ApprovalInboxError
            from .approvals_postgres import PostgresApprovalInbox

            async def _prune_db() -> Any:
                inbox = PostgresApprovalInbox(value)
                try:
                    return await inbox.prune(args.older_than, archive=not args.delete)
                finally:
                    await inbox.aclose()

            try:
                result = asyncio.run(_prune_db())
            except (ApprovalInboxError, ValueError) as exc:
                print(f"prune failed: {type(exc).__name__}", file=sys.stderr)
                raise SystemExit(1) from None
        else:
            from .approvals import FileApprovalInbox

            try:
                result = FileApprovalInbox(value).prune(args.older_than, archive=not args.delete)
            except OSError as exc:
                print(f"prune failed: {type(exc).__name__}", file=sys.stderr)
                raise SystemExit(1) from None
        if args.delete:
            print(f"deleted {result.deleted} requests")
        else:
            print(f"archived {result.archived} requests")
    elif args.cmd == "sessions":
        url = args.database_url or os.environ.get("SESSION_URL")
        if not url:
            print("--database-url or SESSION_URL is required", file=sys.stderr)
            raise SystemExit(1)
        if not url.startswith(("postgresql://", "postgresql+asyncpg://")):
            print("sessions enable-rls requires a Postgres URL", file=sys.stderr)
            raise SystemExit(1)
        try:
            from sqlalchemy.exc import DBAPIError

            from .runtime.session_rls import (
                SessionRlsUnavailable,
                engine_for_url,
                setup_session_rls,
            )
        except ImportError:
            print("sessions enable-rls requires sqlalchemy and asyncpg", file=sys.stderr)
            raise SystemExit(1) from None

        engine = engine_for_url(url)

        async def _enable() -> None:
            try:
                await setup_session_rls(engine)
            finally:
                await engine.dispose()

        try:
            asyncio.run(_enable())
        except SessionRlsUnavailable as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None
        except DBAPIError as exc:
            print(f"session rls setup failed: {type(exc).__name__}", file=sys.stderr)
            raise SystemExit(1) from None
        print("session rls enabled")
    elif args.cmd == "rag":
        _run_rag(args)
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
    elif args.cmd == "peers":
        from pydantic import ValidationError

        from .core import PeerAction, PeerGrant, PeerIdentity, PeerStoreError

        peers_store, grants_store = _peer_stores(args)

        def _split(value: str) -> list[str]:
            return [item.strip() for item in value.split(",") if item.strip()]

        async def run_peers() -> Any:
            if args.peers_cmd == "list":
                identities = await peers_store.list()
                grants = await grants_store.list()
                if args.tenant is not None:
                    identities = [
                        identity for identity in identities if identity.tenant == args.tenant
                    ]
                by_peer: dict[str, list[PeerGrant]] = {}
                for grant in grants:
                    by_peer.setdefault(grant.peer_id, []).append(grant)
                identities.sort(key=lambda identity: identity.peer_id)
                return [
                    {
                        "peer": identity.model_dump(mode="json"),
                        "grants": [
                            grant.model_dump(mode="json")
                            for grant in sorted(
                                by_peer.get(identity.peer_id, []),
                                key=lambda grant: grant.agent_id,
                            )
                        ],
                    }
                    for identity in identities
                ]
            if args.peers_cmd == "register":
                identity = PeerIdentity(
                    peer_id=args.id,
                    tenant=args.tenant,
                    subject=args.subject or args.id,
                    kind=args.kind,
                    roles=_split(args.roles),
                )
                existing = await peers_store.get(identity.peer_id)
                if existing is not None and existing.tenant != identity.tenant:
                    raise LookupError(f"peer tenant is immutable: {identity.peer_id}")
                return await peers_store.put(identity)
            peer = await peers_store.get(args.id)
            if peer is None:
                raise LookupError(f"unknown peer: {args.id}")
            if args.peers_cmd == "disable":
                return await peers_store.put(peer.model_copy(update={"enabled": False}))
            if args.peers_cmd == "grant":
                actions = _split(args.actions)
                if not actions or any(action not in {"read", "invoke"} for action in actions):
                    raise ValueError(f"invalid actions: {args.actions!r}")
                return await grants_store.put(
                    PeerGrant(
                        peer_id=peer.peer_id,
                        tenant=peer.tenant,
                        agent_id=args.agent,
                        actions=cast("list[PeerAction]", actions),
                    )
                )
            return {"revoked": await grants_store.delete(peer.peer_id, args.agent)}

        try:
            result = asyncio.run(run_peers())
        except (PeerStoreError, ValidationError, LookupError, ValueError) as exc:
            print(f"peers failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from None
        payload = result if isinstance(result, (dict, list)) else result.model_dump(mode="json")
        print(json.dumps(payload))
    elif args.cmd == "remote-agents":
        from pydantic import ValidationError

        from .core import (
            CredentialStoreError,
            RemoteAgent,
            RemoteAgentError,
            RemoteAgentFetchError,
            RemoteAgentRegistration,
        )
        from .registry import fetch_agent_card
        from .secretstore import (
            KeyBackendError,
            PrefixedEnvSecretProvider,
            RoutingSecretProvider,
            SecretNotFound,
            TenantScopedSecretProvider,
            TenantSecretProvider,
            load_key_backend,
        )

        peer_store, _ = _peer_stores(args)
        remote_store = _remote_agent_store(args)
        credential_store = (
            _credential_store(args) if args.remote_cmd in {"register", "refresh"} else None
        )
        secrets: Any = PrefixedEnvSecretProvider()
        if credential_store is not None:
            try:
                key_backend = load_key_backend()
            except KeyBackendError as exc:
                print(_key_backend_message(exc), file=sys.stderr)
                raise SystemExit(1) from None
            secrets = RoutingSecretProvider(
                TenantSecretProvider(key_backend, credential_store),
                secrets,
            )

        async def _run_remote_agents() -> Any:
            if args.remote_cmd == "list":
                records = await remote_store.list()
                if args.tenant is not None:
                    records = [record for record in records if record.tenant == args.tenant]
                records.sort(key=lambda record: record.remote_id)
                return [record.model_dump(mode="json") for record in records]

            if args.remote_cmd == "register":
                registration = RemoteAgentRegistration(
                    remote_id=args.id,
                    tenant=args.tenant,
                    peer_id=args.peer,
                    agent_card_url=args.card_url,
                    credential_ref=args.credential_ref,
                    label=args.label,
                )
                peer = await peer_store.get(registration.peer_id)
                if peer is None or not peer.enabled:
                    raise LookupError(f"unknown or disabled peer: {registration.peer_id}")
                if peer.tenant != registration.tenant:
                    raise ValueError(
                        f"tenant mismatch: record {registration.tenant} != peer {peer.tenant}"
                    )
                existing = await remote_store.get(registration.remote_id)
                if existing is not None and existing.tenant != registration.tenant:
                    raise ValueError(f"remote agent tenant is immutable: {registration.remote_id}")
                credential = (
                    await TenantScopedSecretProvider(secrets, registration.tenant).resolve(
                        registration.credential_ref
                    )
                    if registration.credential_ref is not None
                    else None
                )
                digest, card = await fetch_agent_card(registration.agent_card_url, credential)
                if card.get("name") != registration.remote_id:
                    raise ValueError(
                        f"card name mismatch: {card.get('name')!r} != {registration.remote_id}"
                    )
                record = RemoteAgent(
                    remote_id=registration.remote_id,
                    tenant=registration.tenant,
                    peer_id=registration.peer_id,
                    agent_card_url=registration.agent_card_url,
                    credential_ref=registration.credential_ref,
                    label=registration.label,
                    card_digest=digest,
                    observed_digest=None,
                    checked_at=datetime.now(timezone.utc),
                    status="pinned",
                    enabled=existing.enabled if existing is not None else True,
                )
                return await remote_store.put(record)

            existing = await remote_store.get(args.id)
            if existing is None:
                raise LookupError(f"unknown remote agent: {args.id}")

            if args.remote_cmd == "disable":
                return await remote_store.put(existing.model_copy(update={"enabled": False}))

            refreshed: str | None = None
            try:
                credential = (
                    await TenantScopedSecretProvider(secrets, existing.tenant).resolve(
                        existing.credential_ref
                    )
                    if existing.credential_ref is not None
                    else None
                )
                refreshed, _card = await fetch_agent_card(existing.agent_card_url, credential)
            except (SecretNotFound, RemoteAgentFetchError):
                refreshed = None
            checked_at = datetime.now(timezone.utc)
            if refreshed == existing.card_digest:
                record = existing.model_copy(
                    update={"checked_at": checked_at, "status": "pinned", "observed_digest": None}
                )
            elif refreshed is not None:
                record = existing.model_copy(
                    update={
                        "checked_at": checked_at,
                        "status": "changed",
                        "observed_digest": refreshed,
                    }
                )
            else:
                record = existing.model_copy(
                    update={"checked_at": checked_at, "status": "unreachable"}
                )
            return await remote_store.put(record)

        async def run_remote_agents() -> Any:
            try:
                return await _run_remote_agents()
            finally:
                close = getattr(credential_store, "aclose", None)
                if close is not None:
                    await close()

        try:
            result = asyncio.run(run_remote_agents())
        except (
            CredentialStoreError,
            RemoteAgentError,
            RemoteAgentFetchError,
            SecretNotFound,
            ValidationError,
            LookupError,
            ValueError,
        ) as exc:
            print(f"remote agents failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from None
        payload = result if isinstance(result, (dict, list)) else result.model_dump(mode="json")
        print(json.dumps(payload))
    elif args.cmd == "connectors":
        from pydantic import ValidationError

        from .core import (
            ConnectorSpec,
            ConnectorStoreError,
            CredentialStoreError,
            DataClass,
            HttpMethod,
        )
        from .registry import ConnectorForbidden, ConnectorNotFound

        store = _connector_store(args)
        if store is None:
            print("set --connectors-dir or --registry-url", file=sys.stderr)
            raise SystemExit(1)
        credential_store = _credential_store(args) if args.connectors_cmd == "register" else None

        def _split(value: str) -> list[str]:
            return [item.strip() for item in value.split(",") if item.strip()]

        async def run_connectors() -> Any:
            try:
                if args.connectors_cmd == "list":
                    return await store.list(args.tenant)
                if args.connectors_cmd == "check":
                    from .registry import check_connector

                    spec = await store.get(args.id)
                    if spec is None:
                        raise ConnectorNotFound(f"connector not found: {args.id}")
                    return await check_connector(spec)
                if args.connectors_cmd == "disable":
                    return await store.disable(args.id, by="cli")
                spec = ConnectorSpec(
                    connector_id=args.id,
                    tenant=args.tenant or None,
                    kind=args.kind,
                    base_url=args.base_url,
                    auth_ref=args.auth_ref or None,
                    methods=cast(
                        "list[HttpMethod]", [item.upper() for item in _split(args.methods)]
                    ),
                    path_prefixes=_split(args.path_prefixes),
                    data_classes=cast("list[DataClass]", _split(args.data_classes)),
                    timeout_seconds=args.timeout_seconds,
                    max_response_bytes=args.max_response_bytes,
                )
                if credential_store is not None:
                    await _require_credential_binding(credential_store, spec)
                return await store.add(spec)
            finally:
                close = getattr(store, "aclose", None)
                if close is not None:
                    await close()
                if credential_store is not None:
                    cred_close = getattr(credential_store, "aclose", None)
                    if cred_close is not None:
                        await cred_close()

        try:
            result = asyncio.run(run_connectors())
        except (
            ConnectorStoreError,
            ConnectorForbidden,
            ConnectorNotFound,
            CredentialStoreError,
            ValidationError,
            ValueError,
        ) as exc:
            print(f"connectors failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from None

        if args.connectors_cmd == "list":
            print(json.dumps([record.model_dump(mode="json") for record in result]))
        else:
            print(json.dumps(result.model_dump(mode="json")))
    elif args.cmd == "credentials":
        from pydantic import ValidationError

        from .core import CredentialBinding, CredentialStoreError
        from .secretstore.keys import KeyBackendError

        store = _credential_store(args)
        if store is None:
            print("set --credentials-dir or --credential-db", file=sys.stderr)
            raise SystemExit(1)

        async def run_credentials() -> Any:
            try:
                if args.credentials_cmd == "list":
                    return await store.list(args.tenant)
                if args.credentials_cmd == "disable":
                    return await store.disable(args.tenant, args.id, by="cli")
                if args.credentials_cmd == "rewrap":
                    from .secretstore import credential_aad, load_key_backend

                    backend = load_key_backend()
                    if backend is None:
                        raise ValueError(
                            "set ADK_SECRET_KEKS or ADK_SECRET_KEKS_FILE to rewrap credentials"
                        )
                    active = backend.current_key_id()
                    rewrapped = 0
                    skipped = 0
                    for binding in await store.list(args.tenant):
                        wrapped = binding.wrapped_secret
                        if wrapped is None or (
                            binding.secret_key_id == active and wrapped.get("key_id") == active
                        ):
                            skipped += 1
                            continue
                        rewrapped_secret = backend.rewrap(
                            wrapped,
                            credential_aad(binding.tenant, binding.credential_id),
                        )
                        rewrapped += 1
                        if not args.dry_run:
                            await store.replace_wrapped(
                                binding.tenant, binding.credential_id, rewrapped_secret, active
                            )
                    return {
                        "tenant": args.tenant,
                        "rewrapped": rewrapped,
                        "skipped": skipped,
                        "dry_run": args.dry_run,
                    }
                if args.credentials_cmd == "migrate":
                    from .secretstore import credential_aad
                    from .secretstore.keys import (
                        VaultKeyBackend,
                        load_key_backend,
                        load_local_backend,
                    )

                    local = load_local_backend()
                    target = load_key_backend(allow_local=True)
                    if not isinstance(target, VaultKeyBackend):
                        raise ValueError("set ADK_SECRET_BACKEND=vault for credentials migrate")
                    migrated = 0
                    skipped = 0
                    try:
                        for binding in await store.list(args.tenant):
                            wrapped = binding.wrapped_secret
                            if wrapped is None:
                                skipped += 1
                                continue
                            if wrapped.get("v") == 2:
                                if wrapped.get("backend") != "vault":
                                    raise KeyBackendError("secret payload is malformed")
                                skipped += 1
                                continue
                            nonce = wrapped.get("nonce")
                            ciphertext = wrapped.get("ciphertext")
                            if not isinstance(nonce, str) or not isinstance(ciphertext, str):
                                raise KeyBackendError("secret payload is malformed")
                            aad = credential_aad(binding.tenant, binding.credential_id)
                            dek = local.unwrap_dek(wrapped, aad)
                            migrated_secret = target.wrap_dek(
                                dek, nonce=nonce, ciphertext=ciphertext
                            )
                            if target.unwrap_dek(migrated_secret, aad) != dek:
                                raise KeyBackendError("migrated credential failed verification")
                            migrated += 1
                            if not args.dry_run:
                                await store.replace_wrapped(
                                    binding.tenant,
                                    binding.credential_id,
                                    migrated_secret,
                                    migrated_secret["key_id"],
                                )
                    except KeyBackendError:
                        print(
                            json.dumps(
                                {
                                    "tenant": args.tenant,
                                    "migrated": migrated,
                                    "skipped": skipped,
                                    "dry_run": args.dry_run,
                                    "error": "migration_failed",
                                }
                            ),
                            file=sys.stderr,
                        )
                        raise
                    return {
                        "tenant": args.tenant,
                        "migrated": migrated,
                        "skipped": skipped,
                        "dry_run": args.dry_run,
                    }
                wrapped = None
                key_id = None
                version = None
                if getattr(args, "secret_stdin", False):
                    from .secretstore import credential_aad, load_key_backend

                    backend = load_key_backend()
                    if backend is None:
                        raise ValueError(
                            "set ADK_SECRET_KEKS or ADK_SECRET_KEKS_FILE to store a secret"
                        )
                    value = sys.stdin.read().rstrip("\r\n")
                    if not value:
                        raise ValueError("the secret on stdin is empty")
                    if "\r" in value or "\n" in value:
                        raise ValueError("the secret must be a single line")
                    wrapped = backend.wrap(
                        value.encode("utf-8"), credential_aad(args.tenant, args.id)
                    )
                    key_id = backend.current_key_id()
                    version = 1
                binding = CredentialBinding(
                    credential_id=args.id,
                    tenant=args.tenant,
                    secret_ref=args.secret_ref,
                    description=args.description,
                    created_by="cli",
                    created_at=datetime.now(timezone.utc),
                    wrapped_secret=wrapped,
                    secret_key_id=key_id,
                    secret_version=version,
                )
                return await store.add(binding)
            finally:
                close = getattr(store, "aclose", None)
                if close is not None:
                    await close()

        try:
            result = asyncio.run(run_credentials())
        except (CredentialStoreError, ValidationError, ValueError, KeyBackendError) as exc:
            print(f"credentials failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from None

        if args.credentials_cmd in {"rewrap", "migrate"}:
            print(json.dumps(result))
        elif args.credentials_cmd == "list":
            print(
                json.dumps(
                    [
                        record.model_dump(mode="json", exclude={"wrapped_secret"})
                        for record in result
                    ]
                )
            )
        else:
            print(json.dumps(result.model_dump(mode="json", exclude={"wrapped_secret"})))
    elif args.cmd == "triggers":
        from pydantic import ValidationError

        from .core import AgentTrigger, TriggerError, hash_webhook_token

        store = _trigger_store(args)
        if store is None:
            print("set --dir, --db, or TRIGGER_DATABASE_URL", file=sys.stderr)
            raise SystemExit(1)

        async def run_triggers() -> Any:
            try:
                if args.triggers_cmd == "list":
                    return await store.list(args.tenant)
                if args.triggers_cmd == "disable":
                    return await store.disable(args.tenant, args.id, by="cli")
                token_hash = None
                if args.webhook_token_env is not None:
                    token = os.environ.get(args.webhook_token_env)
                    if token is None:
                        raise ValueError(
                            f"webhook token env var {args.webhook_token_env} is not set"
                        )
                    token_hash = hash_webhook_token(token)
                trigger = AgentTrigger(
                    trigger_id=args.id,
                    tenant=args.tenant,
                    agent_id=args.agent_id,
                    version=args.version,
                    digest=args.digest,
                    kind="webhook" if token_hash is not None else "schedule",
                    every_seconds=None if token_hash is not None else args.every_seconds,
                    webhook_token_hash=token_hash,
                    input=args.input,
                    created_by="cli",
                    created_at=datetime.now(timezone.utc),
                )
                return await store.add(trigger)
            finally:
                close = getattr(store, "aclose", None)
                if close is not None:
                    await close()

        try:
            result = asyncio.run(run_triggers())
        except (TriggerError, ValidationError, ValueError) as exc:
            print(f"triggers failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from None

        if args.triggers_cmd == "list":
            print(json.dumps([record.model_dump(mode="json") for record in result]))
        else:
            print(json.dumps(result.model_dump(mode="json")))
    elif args.cmd == "connector-requests":
        from pydantic import ValidationError

        from .core import (
            ConnectorRequest,
            ConnectorRequestConflict,
            ConnectorRequestError,
            ConnectorRequestNotFound,
            ConnectorRequestStatus,
            ConnectorSpec,
            ConnectorStoreError,
            CredentialStoreError,
            DataClass,
            HttpMethod,
            parse_credential_ref,
        )
        from .registry import (
            ConnectorForbidden,
            ConnectorNotFound,
            credential_is_bound,
        )

        def _split(value: str) -> list[str]:
            return [item.strip() for item in value.split(",") if item.strip()]

        if args.connector_requests_cmd == "list" and args.status not in {
            None,
            "pending",
            "approved",
            "denied",
        }:
            print(f"invalid status: {args.status!r}", file=sys.stderr)
            raise SystemExit(1)

        store = _connector_request_store(args)
        if store is None:
            print(
                "set --dir or --db (or CONNECTOR_REQUEST_DATABASE_URL)",
                file=sys.stderr,
            )
            raise SystemExit(1)
        approve_connector_store: Any = None
        approve_credential_store: Any = None
        if args.connector_requests_cmd == "decide" and args.approve:
            approve_connector_store = _connector_store(args)
            if approve_connector_store is None:
                print(
                    "set --connectors-dir or --registry-url to approve",
                    file=sys.stderr,
                )
                raise SystemExit(1)
            approve_credential_store = _credential_store(args)

        async def run_connector_requests() -> Any:
            try:
                if args.connector_requests_cmd == "list":
                    return await store.list(
                        args.tenant, status=cast("ConnectorRequestStatus", args.status)
                    )
                if args.connector_requests_cmd == "request":
                    spec = ConnectorSpec(
                        connector_id=args.id,
                        tenant=args.tenant,
                        kind=args.kind,
                        base_url=args.base_url,
                        auth_ref=args.auth_ref or None,
                        methods=cast(
                            "list[HttpMethod]",
                            [item.upper() for item in _split(args.methods)],
                        ),
                        path_prefixes=_split(args.path_prefixes),
                        data_classes=cast("list[DataClass]", _split(args.data_classes)),
                    )
                    if spec.auth_ref is not None:
                        try:
                            ref_tenant, _ = parse_credential_ref(spec.auth_ref)
                        except ValueError:
                            ref_tenant = None
                        if ref_tenant is not None and ref_tenant != args.tenant:
                            raise ConnectorRequestError(
                                "credential_unbound: auth_ref tenant must match --tenant"
                            )
                    record = ConnectorRequest(
                        request_id=uuid.uuid4().hex,
                        tenant=args.tenant,
                        spec=spec,
                        reason=args.reason,
                        requested_by="cli",
                        requested_at=datetime.now(timezone.utc),
                    )
                    return await store.add(record)
                record = await store.get(args.request_id)
                if record is None:
                    raise ConnectorRequestNotFound(
                        f"connector request {args.request_id!r} not found"
                    )
                if record.status != "pending":
                    raise ConnectorRequestConflict(
                        f"connector request {args.request_id!r} is {record.status}"
                    )
                if args.deny:
                    return await store.decide(
                        args.request_id,
                        approved=False,
                        decided_by="cli",
                        reason=args.reason,
                    )
                if approve_credential_store is not None and not await credential_is_bound(
                    approve_credential_store, record.spec
                ):
                    raise ValueError("credential_unbound")
                await approve_connector_store.add(record.spec)
                return await store.decide(
                    args.request_id,
                    approved=True,
                    decided_by="cli",
                    reason=args.reason,
                    registered_connector=record.spec.connector_id,
                )
            finally:
                for candidate in (
                    store,
                    approve_connector_store,
                    approve_credential_store,
                ):
                    close = getattr(candidate, "aclose", None)
                    if close is not None:
                        await close()

        try:
            result = asyncio.run(run_connector_requests())
        except (
            ConnectorRequestError,
            ConnectorStoreError,
            ConnectorForbidden,
            ConnectorNotFound,
            CredentialStoreError,
            ValidationError,
            ValueError,
        ) as exc:
            print(f"connector request failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from None

        if args.connector_requests_cmd == "list":
            print(json.dumps([record.model_dump(mode="json") for record in result]))
        else:
            print(json.dumps(result.model_dump(mode="json")))
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
                file_registry = FileAgentRegistry(args.registry)

                async def check_version():
                    records = await file_registry.list(args.tenant)
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
    elif args.cmd == "tool-grants":
        from pydantic import ValidationError

        from .core import GrantStoreError, ToolGrantRequest

        if args.tool_grants_cmd == "request" and not 1 <= args.expires_hours <= 168:
            print("--expires-hours must be between 1 and 168", file=sys.stderr)
            raise SystemExit(1)
        if (
            args.tool_grants_cmd == "list"
            and args.status is not None
            and args.status not in {"pending", "approved", "denied", "expired", "cancelled"}
        ):
            print(f"invalid status: {args.status!r}", file=sys.stderr)
            raise SystemExit(1)
        store = _tool_grant_store(args)
        if store is None:
            print("set --tool-grants-dir or GRANT_URL", file=sys.stderr)
            raise SystemExit(1)

        async def run_tool_grants() -> Any:
            if args.tool_grants_cmd == "list":
                return await store.list(args.tenant, status=args.status)
            if args.tool_grants_cmd == "request":
                now = datetime.now(timezone.utc)
                request = ToolGrantRequest(
                    request_id=uuid.uuid4().hex,
                    tenant=args.tenant,
                    agent_id=args.id,
                    version=args.version,
                    digest=args.digest,
                    tool_id=args.tool,
                    reason=args.reason,
                    requested_by="cli",
                    requested_at=now,
                    expires_at=now + timedelta(hours=args.expires_hours),
                )
                return await store.add(request)
            return await store.decide(
                args.request_id,
                approved=args.approve,
                decided_by="cli",
                reason=args.reason,
            )

        try:
            result = asyncio.run(run_tool_grants())
        except (GrantStoreError, ValidationError, ValueError) as exc:
            print(f"tool-grants failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from None

        if args.tool_grants_cmd == "list":
            print(json.dumps([record.model_dump(mode="json") for record in result]))
        else:
            print(json.dumps(result.model_dump(mode="json")))
    elif args.cmd == "templates":
        from .compose import list_templates

        print(json.dumps([template.model_dump(mode="json") for template in list_templates()]))
    elif args.cmd == "compose":
        from .compose import ComposeError, compose_and_publish
        from .eval import EvalGateFailed
        from .registry import (
            FileArtifactStore,
            PackagingError,
            PublishUnavailable,
            RegistryError,
            load_private_key,
        )

        if not args.key or not args.key_id:
            print("compose failed: --key and --key-id are required", file=sys.stderr)
            raise SystemExit(1)
        if not args.builder_key or not args.builder_key_id:
            print(
                "compose failed: --builder-key and --builder-key-id are required",
                file=sys.stderr,
            )
            raise SystemExit(1)

        registry = _agent_registry(args)
        compose_store: Any = None
        if args.registry_url:
            if args.artifact_dir or os.environ.get("ARTIFACT_URL"):
                print(
                    "compose failed: --artifact-dir and ARTIFACT_URL cannot be used with "
                    "--registry-url",
                    file=sys.stderr,
                )
                raise SystemExit(1)
        else:
            url = os.environ.get("ARTIFACT_URL")
            if bool(args.artifact_dir) == bool(url):
                print(
                    "compose failed: set exactly one of --artifact-dir or ARTIFACT_URL",
                    file=sys.stderr,
                )
                raise SystemExit(1)
            if url:
                from .registry.artifacts_postgres import PostgresArtifactStore

                compose_store = PostgresArtifactStore(url)
            else:
                compose_store = FileArtifactStore(args.artifact_dir)

        def _split(value: str) -> list[str]:
            return [item.strip() for item in value.split(",") if item.strip()]

        async def run_compose() -> Any:
            try:
                return await compose_and_publish(
                    template_id=args.template,
                    name=args.agent_id,
                    version=args.version,
                    tenant=args.tenant,
                    owner=args.owner,
                    description=args.description,
                    instruction=args.instruction,
                    tools=_split(args.tools),
                    data_classes=_split(args.data_classes),
                    registry=registry,
                    artifact_store=compose_store,
                    private_key=load_private_key(args.key),
                    key_id=args.key_id,
                    builder_key=load_private_key(args.builder_key),
                    builder_key_id=args.builder_key_id,
                )
            finally:
                if compose_store is not None:
                    close = getattr(compose_store, "aclose", None)
                    if close is not None:
                        await close()
                close = getattr(registry, "aclose", None)
                if close is not None:
                    await close()

        try:
            stored = asyncio.run(run_compose())
        except (
            ComposeError,
            PublishUnavailable,
            PackagingError,
            EvalGateFailed,
            RegistryError,
            ValueError,
            OSError,
        ) as exc:
            print(f"compose failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from None

        print(
            f"composed {stored.manifest.tenant}/{stored.manifest.id}"
            f"@{stored.manifest.version} sha256:{stored.digest}"
        )
        if stored.artifact is not None:
            print(f"artifact {stored.artifact.digest}")
    elif args.cmd == "publish":
        from .core import AgentManifest, EvalReport, declared_execution_tier
        from .eval import enforce_eval_gate
        from .registry import (
            FileEvalReportStore,
            HttpEvalReportStore,
            published_from,
        )
        from .sandbox.agent import agent_sandbox_available

        try:
            data = json.loads(Path(args.path).read_text(encoding="utf-8"))
            data.setdefault("execution_tier", "sandboxed")
            manifest = AgentManifest.model_validate(data)
            if declared_execution_tier(data) == "sandboxed" and not agent_sandbox_available():
                raise ValueError("manifest requires the agent sandbox, which is not available")
            report = (
                EvalReport.model_validate_json(Path(args.eval_report).read_text(encoding="utf-8"))
                if args.eval_report
                else None
            )
            enforce_eval_gate(manifest, report)
            artifact, artifact_bytes = _publish_artifact(args, manifest)
            if manifest.execution_tier == "in_process" and artifact is not None:
                builder_trust = _builder_trust(args)
                if builder_trust is None:
                    raise ValueError(
                        "in_process publish requires --builder-keys or ADK_BUILDER_KEYS"
                    )
                builder_trust.verify_builder(artifact)
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
