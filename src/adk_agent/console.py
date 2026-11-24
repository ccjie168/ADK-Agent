"""A minimal private web console for ADK agents (bearer-auth protected).

`GET /` serves a static shell with no data; every `/api/*` endpoint requires
`Authorization: Bearer <token>` (CP-S6). The page asks for the token and keeps
it in ``sessionStorage`` for the current tab only.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import uuid
from collections.abc import AsyncGenerator, Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from google.adk.models import BaseLlm
from pydantic import ValidationError

from .approvals import HISTORY_STATUSES, ApprovalConflict, ApprovalExpired, ApprovalNotFound
from .approvals_postgres import ApprovalInboxUnavailable
from .audit import AuditQuery, AuditQueryUnavailable, ListAuditSink, query_events
from .audit.hashing import hash_text
from .auth import BearerAuthMiddleware, OidcAuthMiddleware, resolve_http_auth
from .core import (
    CAPABILITIES_ALL,
    CAPABILITIES_BASE,
    CAPABILITIES_OPERATOR,
    CAPABILITIES_PUBLISHER,
    AccessPolicy,
    AgentLifecycle,
    AgentLifecycleStore,
    AgentManifest,
    AgentRef,
    AgentRegistry,
    ArtifactLoader,
    ArtifactStore,
    AuditEvent,
    AuditSink,
    ConnectorConflict,
    ConnectorRequest,
    ConnectorRequestConflict,
    ConnectorRequestError,
    ConnectorRequestNotFound,
    ConnectorRequestStatus,
    ConnectorRequestStore,
    ConnectorSpec,
    ConnectorStore,
    ConnectorStoreError,
    ConnectorStoreUnavailable,
    CredentialBinding,
    CredentialConflict,
    CredentialNotFound,
    CredentialStore,
    CredentialStoreError,
    CredentialStoreUnavailable,
    EvalReportStore,
    GrantRequestConflict,
    GrantRequestExpired,
    GrantRequestNotFound,
    GrantStatus,
    GrantStoreError,
    IdentityProvider,
    Invocation,
    ModelPolicy,
    PeerGrant,
    PeerGrantStore,
    PeerIdentity,
    PeerStore,
    PeerStoreError,
    Principal,
    ProgressEvent,
    QuotaConfig,
    QuotaExceeded,
    QuotaManager,
    RemoteAgent,
    RemoteAgentError,
    RemoteAgentFetchError,
    RemoteAgentRegistration,
    RemoteAgentStore,
    RoleConflict,
    RoleDefinition,
    RoleStore,
    RoleStoreError,
    SecretProvider,
    ToolGrantRequest,
    ToolGrantStore,
    UserBinding,
    UserBindingConflict,
    UserBindingStore,
    UserBindingStoreError,
)
from .identity import OidcLogin, OidcLoginError
from .logsafe import install_log_sanitizer
from .mcp.http import resolve_port
from .metrics import MetricsRegistry
from .models import effective_default_model, is_valid_model_spec, set_default_model
from .models.config_store import ModelConfigStore, ModelConfigStoreUnavailable
from .models.gateway_llm import GatewayLlm, provider_for_model
from .ratelimit import RateLimit, RateLimitMiddleware, build_rate_limiter
from .rbac import FilePolicyStore, RolePolicyEngine
from .registry import (
    ArtifactLoadError,
    ArtifactTrustError,
    InProcessArtifactLoader,
    PublishUnavailable,
    RegistryIntegrityError,
    TrustStore,
    check_connector,
    credential_is_bound,
    fetch_agent_card,
    load_sandbox_agent,
    published_from,
    verify_published_artifact,
)
from .runtime import AgentRuntime, dev_agent_ref
from .runtime.quota_postgres import QuotaStoreUnavailable
from .runtime.sessions import scoped_user_id, session_tenant
from .sandbox import SandboxPolicy, ToolSandbox, install_tool_sandbox
from .sandbox.agent import (
    AgentSandboxUnavailable,
    SandboxToolsUnavailable,
    require_execution_supported,
)
from .sandbox.proxy import SandboxAgent
from .secretstore import (
    PrefixedEnvSecretProvider,
    RoutingSecretProvider,
    SecretNotFound,
    TenantScopedSecretProvider,
    TenantSecretProvider,
    load_key_backend,
)
from .semantics import (
    CapabilityBinding,
    ConceptScheme,
    ConceptSchemeStore,
    ConceptSchemeStoreUnavailable,
    route_request,
)
from .tools import ToolCatalog, ToolEntry, connector_tool_entries, install_declared_guards
from .tracing import resolve_trace_id

if TYPE_CHECKING:  # pragma: no cover
    from google.adk.agents import BaseAgent

    from .approvals import FileApprovalInbox
    from .approvals_postgres import PostgresApprovalInbox

logger = logging.getLogger(__name__)

_USER_ID = "console_user"
_OPEN_PATHS = frozenset({"/", "/healthz", "/auth/config", "/auth/token", "/auth/callback"})
_TRACE_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
_SAFE_TENANT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}")
_GRANT_STATUSES = frozenset({"pending", "approved", "denied", "expired", "cancelled"})
_CONNECTOR_REQUEST_STATUSES = frozenset({"pending", "approved", "denied"})


def _capabilities_for(roles: Iterable[str]) -> list[str]:
    """Hardcoded role table, used when no role definition store is configured."""
    granted: set[str] = set()
    for role in roles:
        if role == "admin":
            granted |= CAPABILITIES_ALL
        elif role in {"operator", "ops", "approver"}:
            granted |= CAPABILITIES_OPERATOR
        elif role in {"publisher", "developer"}:
            granted |= CAPABILITIES_PUBLISHER
    return sorted(granted or CAPABILITIES_BASE)


_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


_INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ADK Console</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%230f766e'/%3E%3Ctext x='16' y='22' font-family='system-ui' font-size='15' font-weight='700' fill='white' text-anchor='middle'%3EA%3C/text%3E%3C/svg%3E">
<style>
  :root {
    --bg: #f4f6fb; --panel: #ffffff; --ink: #1e293b; --muted: #64748b;
    --line: #e2e8f0; --accent: #0f766e; --accent-soft: #ecfdf5;
    --bad: #b91c1c; --radius: 10px;
    --radius-sm: 6px; --radius-lg: 14px;
    --shadow-card: 0 1px 3px rgba(15, 23, 42, .08);
    --shadow-card-hover: 0 6px 16px rgba(15, 23, 42, .12);
    --space-1: .25rem; --space-2: .5rem; --space-3: .75rem; --space-4: 1rem;
  }
  html[data-theme="dark"] {
    --bg: #0b1220; --panel: #111a2b; --ink: #e2e8f0; --muted: #94a3b8;
    --line: #24324a; --accent: #2dd4bf; --accent-soft: #0f2e2b;
    --bad: #f87171;
  }
  * { box-sizing: border-box; }
  [hidden] { display: none !important; }
  body { margin: 0; background: var(--bg); color: var(--ink); font-family: system-ui, sans-serif; }
  #login { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 1.5rem; }
  .login-card { width: min(420px, 94vw); background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 2rem; box-shadow: 0 24px 60px rgba(15, 23, 42, .12); }
  .login-card h1 { margin: .7rem 0 .3rem; font-size: 1.6rem; }
  .brand-mark { width: 44px; height: 44px; border-radius: 12px; background: var(--accent); color: #fff; display: flex; align-items: center; justify-content: center; font-weight: 700; }
  .primary { background: var(--accent); color: #fff; border: none; border-radius: var(--radius); padding: .7rem .9rem; font-weight: 600; cursor: pointer; }
  .primary:hover { filter: brightness(1.06); color: #fff; }
  #app { display: grid; grid-template-columns: 220px minmax(0, 1fr); grid-template-rows: 56px minmax(0, 1fr); min-height: 100vh; }
  .topbar { grid-column: 1 / -1; display: flex; align-items: center; gap: .6rem; padding: 0 1rem; background: var(--panel); border-bottom: 1px solid var(--line); }
  .brand { font-weight: 700; margin-right: .3rem; }
  .spacer { flex: 1; }
  #tabs { padding: 1rem .7rem; border-right: 1px solid var(--line); background: var(--panel); overflow: auto; }
  .nav-group { margin-bottom: 1.1rem; }
  .nav-title { font-size: .68rem; text-transform: uppercase; letter-spacing: .12em; color: var(--muted); padding: .3rem .6rem; }
  .tab { display: block; width: 100%; text-align: left; background: transparent; border: none; color: var(--ink); padding: .55rem .7rem; border-radius: 8px; cursor: pointer; font: inherit; }
  .tab:hover { background: var(--accent-soft); }
  .tab.active { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
  #main { padding: 1.25rem 1.4rem 2rem; overflow: auto; }
  .panel { display: none; }
  .panel.active { display: block; }
  .row { display: flex; gap: .5rem; margin-top: .75rem; flex-wrap: wrap; align-items: center; }
  input, select, button { font: inherit; }
  input, select { padding: .45rem .6rem; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); color: var(--ink); }
  button { cursor: pointer; background: var(--panel); color: var(--ink); border: 1px solid var(--line); border-radius: 8px; padding: .4rem .65rem; }
  button:hover { border-color: var(--accent); color: var(--accent); }
  button:active { transform: translateY(1px); }
  .ghost { background: transparent; border: 1px solid var(--line); border-radius: 8px; color: var(--ink); padding: .4rem .65rem; }
  #msg { flex: 1; }
  #log { border: 1px solid var(--line); border-radius: var(--radius); padding: .75rem; height: 320px; overflow-y: auto; background: var(--panel); }
  #log div { white-space: pre-wrap; margin: .2rem 0; }
  .you { color: var(--accent); }
  .agent { color: #2563eb; }
  .system { color: var(--bad); }
  table { border-collapse: collapse; width: 100%; font-size: .85rem; }
  th, td { text-align: left; border-bottom: 1px solid var(--line); padding: .3rem .4rem; }
  tbody tr { cursor: pointer; }
  tbody tr:hover, tbody tr.selected { background: var(--accent-soft); }
  .badge { background: #e6f5ea; color: #047857; border-radius: 4px; padding: 0 .35rem; font-size: .75rem; }
  .badge.bad { background: #fde8e8; color: var(--bad); }
  .badge.warn { background: #fef3c7; color: #b45309; }
  .badge.muted { background: var(--bg); color: var(--muted); }
  html[data-theme="dark"] .badge { background: #10352c; color: #6ee7b7; }
  html[data-theme="dark"] .badge.bad { background: #3b1416; color: #fca5a5; }
  html[data-theme="dark"] .badge.warn { background: #3a2c0b; color: #fcd34d; }
  html[data-theme="dark"] .badge.muted { background: var(--bg); color: var(--muted); }
  #registry-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: .8rem; }
  .card { display: flex; flex-direction: column; align-items: flex-start; gap: .3rem; text-align: left; padding: .55rem .7rem; background: var(--panel); color: var(--ink); }
  .card:hover { border-color: var(--accent); color: var(--ink); }
  .card[aria-pressed="true"] { border-color: var(--accent); background: var(--accent-soft); }
  .card-head { font-weight: 600; }
  .card-desc { color: var(--muted); font-size: .8rem; white-space: pre-wrap; }
  .card-badges { display: flex; flex-wrap: wrap; gap: .25rem; }
  .card-meta { color: var(--muted); font-size: .72rem; font-family: ui-monospace, monospace; overflow-wrap: anywhere; }
  .metric-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: var(--space-3); }
  .stat-card { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius-lg); padding: var(--space-3) var(--space-4); box-shadow: var(--shadow-card); }
  .stat-card:hover { border-color: var(--accent); box-shadow: var(--shadow-card-hover); }
  .stat-label { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); }
  .stat-value { font-size: 1.4rem; font-weight: 700; margin: .15rem 0 .05rem; }
  .stat-delta { font-size: .78rem; color: var(--muted); }
  .stat-delta.up { color: #047857; }
  .stat-delta.down { color: var(--bad); }
  #registry-empty { font-size: .85rem; }
  pre { background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: .6rem; overflow: auto; max-height: 260px; font-size: .78rem; color: var(--ink); }
  .panel-msg { color: var(--bad); font-size: .85rem; min-height: 1.2rem; }
  .panel-msg.ok { color: #047857; }
  #approval-filter, #approval-reason { flex: 1; min-width: 240px; }
  .approval-summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: .45rem; margin: .5rem 0; }
  .approval-summary div { border: 1px solid var(--line); border-radius: 8px; padding: .45rem .6rem; background: var(--panel); }
  .approval-summary span { display: block; color: var(--muted); font-size: .68rem; letter-spacing: .08em; text-transform: uppercase; }
  .approval-summary b { font-size: .85rem; font-weight: 600; word-break: break-word; }
  #approval-detail { min-height: 2rem; }
  .expiry { color: var(--muted); font-size: .8rem; }
  .expiry.soon { color: var(--bad); font-weight: 600; }
  #audit { border: 1px solid var(--line); border-radius: var(--radius); padding: .5rem .75rem; max-height: 220px; overflow-y: auto; font-family: ui-monospace, monospace; font-size: .78rem; background: var(--panel); }
  #audit div { white-space: pre-wrap; margin: .15rem 0; }
  #policy { width: 100%; font-family: ui-monospace, monospace; font-size: .8rem; }
  #policy-msg { color: var(--muted); font-size: .85rem; margin-top: .35rem; }
  #status { font-family: ui-monospace, monospace; font-size: .82rem; color: var(--muted); min-height: 1.2rem; }
  #timeline { border-left: 3px solid var(--line); margin: .4rem 0 .2rem 0; padding-left: .6rem; max-height: 180px; overflow-y: auto; font-family: ui-monospace, monospace; font-size: .78rem; }
  #timeline div { margin: .15rem 0; color: var(--muted); }
  #timeline .tool { color: #2563eb; }
  #timeline .fail { color: var(--bad); }
  #trace, #plan-trace { font-size: .78rem; }
  .trace-summary { font-family: ui-monospace, monospace; color: var(--muted); font-size: .8rem; margin: .2rem 0 .55rem; }
  .trace-axis { display: grid; grid-template-columns: 220px minmax(0, 1fr) 300px; gap: .6rem; color: var(--muted); font-size: .72rem; margin-bottom: .2rem; }
  .trace-axis .track { display: flex; justify-content: space-between; border-bottom: 1px dashed var(--line); }
  .trace-row { display: grid; grid-template-columns: 220px minmax(0, 1fr) 300px; gap: .6rem; align-items: center; padding: .18rem 0; }
  .trace-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .trace-label .kind { color: var(--muted); margin-right: .35rem; font-family: ui-monospace, monospace; }
  .trace-track { position: relative; height: 16px; background: var(--bg); border-radius: 4px; overflow: hidden; }
  .trace-bar { position: absolute; top: 3px; bottom: 3px; min-width: 2px; border-radius: 3px; background: var(--accent); opacity: .9; }
  .trace-bar.model { background: #2563eb; }
  .trace-bar.tool { background: #7c3aed; }
  .trace-bar.plan, .trace-bar.step { background: #0891b2; }
  .trace-bar.approval { background: #b45309; }
  .trace-bar.policy, .trace-bar.supervisor { background: #475569; }
  .trace-bar.error, .trace-bar.denied { background: var(--bad); }
  .trace-meta { color: var(--muted); font-family: ui-monospace, monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .trace-meta .bad { color: var(--bad); }
  .trace-row { cursor: pointer; }
  .trace-row.selected { background: var(--accent-soft); }
  .trace-row:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .trace-detail { display: grid; grid-template-columns: 180px minmax(0, 1fr); gap: .2rem .75rem; margin-top: .75rem; padding: .6rem .75rem; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); font-family: ui-monospace, monospace; }
  .trace-detail-label { color: var(--muted); }
  .trace-detail-value { word-break: break-word; }
  small, .muted { color: var(--muted); }
  @media (max-width: 760px) {
    #app { grid-template-columns: 1fr; grid-template-rows: auto auto 1fr; }
    .topbar { flex-wrap: wrap; padding: .5rem .75rem; }
    #tabs { display: flex; flex-wrap: wrap; gap: .2rem; border-right: none; border-bottom: 1px solid var(--line); padding: .5rem; }
    .nav-group { display: flex; align-items: center; flex-wrap: wrap; gap: .15rem; margin: 0; }
    .nav-title { padding: .2rem .4rem; }
    .tab { width: auto; }
    .trace-axis { display: none; }
    .trace-row { grid-template-columns: 1fr; gap: .1rem; padding: .35rem 0; }
  }
</style>
</head>
<body>
<div id="login">
  <div class="login-card">
    <div class="brand-mark">ADK</div>
    <h1>ADK Console</h1>
    <p class="muted">使用组织账号登录，或输入开发用 Bearer token。</p>
    <button id="oidc-login" class="primary" hidden>使用 OIDC 登录</button>
    <div id="token-row" class="row">
      <input id="token" type="password" placeholder="Bearer token" autocomplete="off">
      <button id="connect">Connect</button>
    </div>
    <div id="login-msg" class="panel-msg"></div>
    <p class="muted"><small>token 只保存在当前标签页的 sessionStorage。</small></p>
  </div>
</div>

<div id="app" hidden>
  <header class="topbar">
    <div class="brand">ADK Console</div>
    <select id="agent" aria-label="agent"></select>
    <select id="tenant" aria-label="tenant"></select>
    <span class="spacer"></span>
    <span id="who" class="muted"></span>
    <button id="theme" class="ghost" title="切换主题" aria-label="切换主题">◐</button>
    <button id="logout" class="ghost">退出</button>
  </header>
  <nav id="tabs">
    <div class="nav-group">
      <div class="nav-title">总览</div>
      <button id="tab-overview" class="tab active" data-tab="overview" data-capability="ops.read">Overview</button>
      <button id="tab-ask-ai" class="tab" data-tab="ask-ai" data-capability="runs.read">Ask AI</button>
    </div>
    <div class="nav-group">
      <div class="nav-title">运营</div>
      <button id="tab-chat" class="tab" data-tab="chat" data-capability="chat.run">Chat</button>
      <button id="tab-runs" class="tab" data-tab="runs" data-capability="runs.read">Runs</button>
      <button id="tab-sessions" class="tab" data-tab="sessions" data-capability="sessions.read">Sessions</button>
      <button id="tab-approvals" class="tab" data-tab="approvals" data-capability="approvals.read">Approvals</button>
      <button id="tab-grants" class="tab" data-tab="grants" data-capability="grants.read">Grants</button>
      <button id="tab-plans" class="tab" data-tab="plans" data-capability="runs.read">Plans</button>
    </div>
    <div class="nav-group">
      <div class="nav-title">构建</div>
      <button id="tab-registry" class="tab" data-tab="registry" data-capability="registry.read">Registry</button>
      <button id="tab-tools" class="tab" data-tab="tools" data-capability="tools.read">Tools</button>
      <button id="tab-connectors" class="tab" data-tab="connectors" data-capability="connectors.read">Connectors</button>
      <button id="tab-credentials" class="tab" data-tab="credentials" data-capability="connectors.read">Credentials</button>
      <button id="tab-peers" class="tab" data-tab="peers" data-capability="peers.read">Peers</button>
      <button id="tab-rag" class="tab" data-tab="rag" data-capability="ops.read">RAG</button>
      <button id="tab-model" class="tab" data-tab="model" data-capability="model.read">Model</button>
    </div>
    <div class="nav-group">
      <div class="nav-title">治理</div>
      <button id="tab-audit" class="tab" data-tab="audit-panel" data-capability="audit.read">Audit</button>
      <button id="tab-quota" class="tab" data-tab="quota" data-capability="ops.read">Quota</button>
      <button id="tab-policy" class="tab" data-tab="policy" data-capability="policy.read">Policy</button>
    </div>
    <div class="nav-group">
      <div class="nav-title">数据</div>
      <button id="tab-semantics" class="tab" data-tab="semantics" data-capability="ops.read">Semantics</button>
      <button id="tab-import" class="tab" data-tab="import" data-capability="runs.read">Import</button>
    </div>
  </nav>
  <main id="main">

<section id="overview" class="panel active" data-capability="ops.read">
  <div id="overview-cards" class="metric-grid"></div>
</section>

<section id="ask-ai" class="panel" data-capability="runs.read">
  <div class="row">
    <input id="ask-ai-text" placeholder="用自然语言描述需求..." autocomplete="off">
    <button id="ask-ai-run">Ask</button>
  </div>
  <div id="ask-ai-result"></div>
</section>

<section id="audit-panel" class="panel" data-capability="audit.read">
  <div class="row">
    <button id="refresh-audit-panel">Refresh</button>
  </div>
  <div id="audit-panel-log"></div>
</section>

<section id="quota" class="panel" data-capability="ops.read">
  <div id="quota-cards" class="metric-grid"></div>
</section>

<section id="rag" class="panel" data-capability="ops.read">
  <div id="rag-cards" class="metric-grid"></div>
</section>

<section id="model" class="panel" data-capability="model.read">
  <div id="model-cards" class="metric-grid"></div>
  <div data-capability="model.read">
    <h3>全局默认模型</h3>
    <div id="model-config" class="muted"></div>
    <div class="row" data-capability="model.write">
      <input id="model-config-input" placeholder="litellm:deepseek/deepseek-v4-pro" autocomplete="off">
      <button id="model-config-save">设置默认模型</button>
    </div>
    <div id="model-config-msg" class="panel-msg"></div>
  </div>
</section>

<section id="semantics" class="panel" data-capability="ops.read">
  <div class="row">
    <input id="semantics-route-text" placeholder="输入需求，回放语义路由..." autocomplete="off">
    <button id="semantics-route-run">Route</button>
  </div>
  <div id="semantics-schemes" class="metric-grid"></div>
  <div id="semantics-route-result"></div>
</section>

<section id="import" class="panel" data-capability="runs.read">
  <div class="row">
    <select id="import-kind">
      <option value="terminology">术语表</option>
      <option value="agent">Agent 定义</option>
    </select>
    <input id="import-payload" placeholder='粘贴 JSON（ConceptScheme 或 manifest）' autocomplete="off">
    <button id="import-run">Import</button>
  </div>
  <div id="import-result"></div>
</section>

<section id="chat" class="panel" data-capability="chat.run">
  <div id="log"></div>
  <div class="row">
    <input id="msg" placeholder="Ask the agent..." autocomplete="off">
    <button id="send">Send</button>
  </div>
  <h3>Run progress</h3>
  <div id="status"></div>
  <div id="timeline"></div>
  <div data-capability="audit.read">
    <h3>Recent audit</h3>
    <div id="audit"></div>
    <div class="row">
      <button id="refresh">Refresh audit</button>
    </div>
  </div>
</section>

<section id="registry" class="panel" data-capability="registry.read">
  <div class="row">
    <button id="refresh-registry">Refresh</button>
    <button id="refresh-remote" disabled>Refresh selected</button>
  </div>
  <div id="registry-msg" class="panel-msg"></div>
  <div id="registry-cards"></div>
  <div id="registry-empty" class="empty muted" hidden>no registry entries</div>
  <h3>Manifest</h3>
  <pre id="manifest"></pre>
  <h3>Eval report</h3>
  <pre id="eval-report"></pre>
  <h3>Artifact</h3>
  <pre id="artifact-info"></pre>
  <h3>Lifecycle</h3>
  <pre id="lifecycle-info"></pre>
  <div class="row">
    <button id="open-chat" data-capability="registry.load">Open chat</button>
    <button id="unload-agent" data-capability="registry.load">Unload</button>
    <span id="artifact-msg" class="panel-msg"></span>
  </div>
</section>

<section id="tools" class="panel" data-capability="tools.read">
  <div class="row">
    <button id="refresh-tools">Refresh</button>
  </div>
  <div id="tools-msg" class="panel-msg"></div>
  <table>
    <thead><tr><th>tool</th><th>source</th><th>data classes</th><th>approval</th><th>granted agents</th></tr></thead>
    <tbody id="tools-body"></tbody>
  </table>
</section>

<section id="connectors" class="panel" data-capability="connectors.read">
  <div class="row">
    <button id="refresh-connectors">Refresh</button>
  </div>
  <div id="connectors-msg" class="panel-msg"></div>
  <table>
    <thead><tr><th>id</th><th>tenant</th><th>kind</th><th>base url</th><th>methods</th><th>enabled</th></tr></thead>
    <tbody id="connectors-body"></tbody>
  </table>
  <h3>Register</h3>
  <div class="row">
    <input id="connector-id" placeholder="connector id" autocomplete="off">
    <input id="connector-tenant" placeholder="tenant (blank = global)" autocomplete="off">
    <select id="connector-kind">
      <option value="http">http</option>
      <option value="openapi">openapi</option>
      <option value="mcp">mcp</option>
    </select>
    <input id="connector-base-url" placeholder="https://api.example.com" autocomplete="off">
  </div>
  <div class="row">
    <input id="connector-auth-ref" placeholder="secret://name/token (optional)" autocomplete="off">
    <input id="connector-methods" placeholder="methods: GET,POST" autocomplete="off">
    <input id="connector-prefixes" placeholder="path prefixes: /v1/" autocomplete="off">
    <input id="connector-data-classes" placeholder="data classes: internal" autocomplete="off">
  </div>
  <div class="row">
    <button id="connector-register" data-capability="connectors.manage">Register</button>
    <button id="connector-disable" data-capability="connectors.manage">Disable selected</button>
    <button id="connector-check" data-capability="connectors.manage">Check selected</button>
  </div>
  <div id="connector-health" class="panel-msg"></div>
  <h3>Requests</h3>
  <div class="row">
    <button id="refresh-connector-requests">Refresh</button>
    <select id="connector-request-status">
      <option value="">all statuses</option>
      <option value="pending">pending</option>
      <option value="approved">approved</option>
      <option value="denied">denied</option>
    </select>
  </div>
  <div id="connector-requests-msg" class="panel-msg"></div>
  <table>
    <thead><tr><th>id</th><th>tenant</th><th>connector</th><th>status</th><th>requested by</th><th>reason</th></tr></thead>
    <tbody id="connector-requests-body"></tbody>
  </table>
  <h3>Request a connector</h3>
  <div class="row">
    <input id="connector-request-id" placeholder="connector id" autocomplete="off">
    <select id="connector-request-kind">
      <option value="http">http</option>
      <option value="openapi">openapi</option>
      <option value="mcp">mcp</option>
    </select>
    <input id="connector-request-base-url" placeholder="https://api.example.com" autocomplete="off">
  </div>
  <div class="row">
    <input id="connector-request-auth-ref" placeholder="secret://name/token (optional)" autocomplete="off">
    <input id="connector-request-methods" placeholder="methods: GET,POST" autocomplete="off">
    <input id="connector-request-prefixes" placeholder="path prefixes: /v1/" autocomplete="off">
    <input id="connector-request-data-classes" placeholder="data classes: internal" autocomplete="off">
  </div>
  <div class="row">
    <input id="connector-request-reason" placeholder="reason" autocomplete="off">
    <button id="connector-request-submit">Request</button>
    <button id="connector-request-approve" data-capability="connectors.manage">Approve selected</button>
    <button id="connector-request-deny" data-capability="connectors.manage">Deny selected</button>
  </div>
</section>

<section id="credentials" class="panel" data-capability="connectors.read">
  <div class="row">
    <button id="refresh-credentials">Refresh</button>
    <input id="credential-tenant" placeholder="tenant filter (blank = current)" autocomplete="off">
  </div>
  <div id="credentials-msg" class="panel-msg"></div>
  <table>
    <thead><tr><th>id</th><th>tenant</th><th>secret ref</th><th>description</th><th>status</th></tr></thead>
    <tbody id="credentials-body"></tbody>
  </table>
  <h3>Register</h3>
  <div class="row">
    <input id="credential-id" placeholder="credential id" autocomplete="off">
    <input id="credential-ref" placeholder="secret://tenant/name" autocomplete="off">
    <input id="credential-description" placeholder="description (optional)" autocomplete="off">
  </div>
  <div class="row">
    <button id="credential-register" data-capability="connectors.manage">Register</button>
    <button id="credential-disable" data-capability="connectors.manage">Disable selected</button>
  </div>
</section>

<section id="peers" class="panel" data-capability="peers.read">
  <div class="row">
    <button id="refresh-peers">Refresh</button>
  </div>
  <div id="peers-msg" class="panel-msg"></div>
  <table>
    <thead><tr><th>peer</th><th>tenant</th><th>subject</th><th>kind</th><th>enabled</th><th>grants</th></tr></thead>
    <tbody id="peers-body"></tbody>
  </table>
  <h3>Register</h3>
  <div class="row">
    <input id="peer-id" placeholder="peer id" autocomplete="off">
    <input id="peer-tenant" placeholder="tenant" autocomplete="off">
    <input id="peer-subject" placeholder="subject (blank = id)" autocomplete="off">
    <select id="peer-kind">
      <option value="service">service</option>
      <option value="human">human</option>
      <option value="agent">agent</option>
    </select>
    <button id="peer-register" data-capability="peers.manage">Register</button>
    <button id="peer-disable" data-capability="peers.manage">Disable selected</button>
  </div>
  <h3>Grant</h3>
  <div class="row">
    <input id="peer-agent" placeholder="agent id" autocomplete="off">
    <label><input type="checkbox" id="peer-action-read" checked> read</label>
    <label><input type="checkbox" id="peer-action-invoke" checked> invoke</label>
    <button id="peer-grant" data-capability="peers.manage">Grant</button>
    <button id="peer-revoke" data-capability="peers.manage">Revoke</button>
  </div>
</section>

<section id="runs" class="panel" data-capability="runs.read">
  <div class="row">
    <button id="refresh-runs">Refresh</button>
  </div>
  <div id="runs-msg" class="panel-msg"></div>
  <table>
    <thead><tr><th>run</th><th>agent</th><th>status</th><th>started</th><th>latency</th><th>cost</th><th>events</th></tr></thead>
    <tbody id="runs-body"></tbody>
  </table>
  <h3>Trace</h3>
  <div id="trace"></div>
</section>

<section id="sessions" class="panel" data-capability="sessions.read">
  <div class="row">
    <select id="session-agent"></select>
    <button id="refresh-sessions">Refresh</button>
  </div>
  <div id="sessions-msg" class="panel-msg"></div>
  <table>
    <thead><tr><th>session</th><th>last update</th></tr></thead>
    <tbody id="sessions-body"></tbody>
  </table>
  <div id="selected-session"><small></small></div>
</section>

<section id="approvals" class="panel" data-capability="approvals.read">
  <div class="row">
    <button id="refresh-approvals">Refresh</button>
    <input id="approval-filter" placeholder="filter by id, step, agent or reason" autocomplete="off">
  </div>
  <div id="approvals-msg" class="panel-msg"></div>
  <table>
    <thead><tr><th>request</th><th>step</th><th>agent</th><th>reason</th><th>requested</th><th>expires</th></tr></thead>
    <tbody id="approvals-body"></tbody>
  </table>
  <div id="approval-empty" class="muted" hidden>没有待决审批。</div>
  <h3>Request</h3>
  <div id="approval-summary" class="approval-summary"></div>
  <pre id="approval-detail"></pre>
  <div class="row">
    <input id="approval-reason" placeholder="decision reason (optional)" autocomplete="off">
    <button id="approve" data-capability="approvals.decide">Approve</button>
    <button id="deny" data-capability="approvals.decide">Deny</button>
  </div>
  <h3>History</h3>
  <div class="row">
    <button id="refresh-approval-history">Refresh</button>
    <select id="approval-history-status">
      <option value="">all</option>
      <option value="approved">approved</option>
      <option value="denied">denied</option>
      <option value="expired">expired</option>
      <option value="cancelled">cancelled</option>
    </select>
  </div>
  <div id="approval-history-msg" class="panel-msg"></div>
  <table>
    <thead><tr><th>request</th><th>status</th><th>agent</th><th>approver</th><th>terminal</th><th>reason</th><th>archived</th></tr></thead>
    <tbody id="approval-history-body"></tbody>
  </table>
</section>

<section id="grants" class="panel" data-capability="grants.read">
  <div class="row">
    <button id="refresh-grants">Refresh</button>
  </div>
  <div id="grants-msg" class="panel-msg"></div>
  <table>
    <thead><tr><th>tool</th><th>agent</th><th>version</th><th>status</th><th>expires</th></tr></thead>
    <tbody id="grants-body"></tbody>
  </table>
  <div class="row">
    <input id="grant-tool" placeholder="tool id (e.g. crm.read)" autocomplete="off">
    <input id="grant-reason" placeholder="reason" autocomplete="off">
    <button id="grant-request" data-capability="grants.request">Request for selected</button>
  </div>
  <div class="row">
    <button id="grant-approve" data-capability="grants.decide">Approve</button>
    <button id="grant-deny" data-capability="grants.decide">Deny</button>
  </div>
  <h3>Tool usage (recent audit)</h3>
  <table>
    <thead><tr><th>tool</th><th>allowed</th><th>denied</th><th>temporary</th></tr></thead>
    <tbody id="grant-usage-body"></tbody>
  </table>
</section>

<section id="plans" class="panel" data-capability="runs.read">
  <div class="row">
    <button id="refresh-plans">Refresh</button>
  </div>
  <div id="plans-msg" class="panel-msg"></div>
  <table>
    <thead><tr><th>plan</th><th>tenant</th><th>status</th><th>steps</th><th>approvals</th><th>started</th></tr></thead>
    <tbody id="plans-body"></tbody>
  </table>
  <h3>Plan trace</h3>
  <div id="plan-trace"></div>
</section>

<section id="policy" class="panel" data-capability="policy.read">
  <h3>Policies</h3>
  <textarea id="policy" rows="12" spellcheck="false"></textarea>
  <div class="row">
    <button id="load-policy">Load policy</button>
    <button id="save-policy" data-capability="policy.write">Save policy</button>
  </div>
  <div id="policy-msg"></div>
</section>
  </main>
</div>

<script>
const $ = (id) => document.getElementById(id);
const TABS = ["overview", "ask-ai", "chat", "registry", "tools", "connectors", "credentials", "peers", "runs", "sessions", "approvals", "grants", "plans", "audit-panel", "quota", "rag", "model", "semantics", "import", "policy"];
let sessionId = null;
let capabilities = null;
let approvalsData = [];
let selectedApproval = null;
let selectedRegistry = null;
let selectedGrant = null;
let selectedConnector = null;
let selectedConnectorRequest = null;
let selectedCredential = null;
let selectedPeer = null;
const token = () => $("token").value.trim();
$("token").value = sessionStorage.getItem("adk_token") || "";
$("token").addEventListener("change", () => sessionStorage.setItem("adk_token", token()));

function can(cap) {
  return capabilities === null || capabilities.has(cap);
}

async function loadMe() {
  try {
    const result = await getJson("/api/me");
    if (!result.ok || !result.data || !Array.isArray(result.data.capabilities)) return;
    capabilities = new Set(result.data.capabilities);
  } catch (e) {
    capabilities = null;
  }
}

function applyCapabilities() {
  if (capabilities === null) return;
  for (const el of document.querySelectorAll("[data-capability]")) {
    el.hidden = !capabilities.has(el.dataset.capability);
  }
  for (const group of document.querySelectorAll("#tabs .nav-group")) {
    const tabs = Array.from(group.querySelectorAll("[data-capability]"));
    const visible = tabs.some((tab) => !tab.hidden);
    group.hidden = !visible;
    const title = group.querySelector(".nav-title");
    if (title) title.hidden = !visible;
  }
}

function showTab(name) {
  let target = name;
  const requested = $("tab-" + name);
  if (!requested || requested.hidden) {
    const first = document.querySelector("#tabs .tab:not([hidden])");
    if (first) target = first.dataset.tab;
  }
  for (const tab of TABS) {
    const panel = $(tab);
    const button = $("tab-" + tab);
    if (panel) panel.classList.toggle("active", tab === target);
    if (button) button.classList.toggle("active", tab === target);
  }
  if (location.hash !== "#" + target) history.replaceState(null, "", "#" + target);
}

async function getJson(path) {
  const response = await fetch(path, { headers: { Authorization: "Bearer " + token() } });
  if (response.status === 401) {
    sessionStorage.removeItem("adk_token");
    showLogin();
  }
  let data = null;
  try { data = await response.json(); } catch (e) { data = null; }
  return { ok: response.ok, status: response.status, data: data };
}

async function loadOverview() {
  const result = await getJson("/api/overview");
  const container = $("overview-cards");
  if (!container) return;
  container.innerHTML = "";
  if (!result.ok || !result.data || !result.data.cards) return;
  for (const card of result.data.cards) {
    const el = document.createElement("div");
    el.className = "stat-card";
    el.setAttribute("role", "button");
    el.setAttribute("tabindex", "0");
    el.addEventListener("click", () => showTab(card.panel));
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); showTab(card.panel); }
    });
    const label = document.createElement("div");
    label.className = "stat-label";
    label.textContent = card.label;
    const value = document.createElement("div");
    value.className = "stat-value";
    value.textContent = card.value === null ? "未配置" : String(card.value);
    el.appendChild(label);
    el.appendChild(value);
    container.appendChild(el);
  }
}

async function postJson(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      Authorization: "Bearer " + token(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  let data = null;
  try { data = await response.json(); } catch (e) { data = null; }
  return { ok: response.ok, status: response.status, data: data };
}

async function putJson(path, body) {
  const response = await fetch(path, {
    method: "PUT",
    headers: {
      Authorization: "Bearer " + token(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  let data = null;
  try { data = await response.json(); } catch (e) { data = null; }
  return { ok: response.ok, status: response.status, data: data };
}

async function deleteJson(path) {
  const response = await fetch(path, {
    method: "DELETE",
    headers: { Authorization: "Bearer " + token() },
  });
  let data = null;
  try { data = await response.json(); } catch (e) { data = null; }
  return { ok: response.ok, status: response.status, data: data };
}

function cell(text) {
  const td = document.createElement("td");
  td.textContent = text == null ? "-" : String(text);
  return td;
}

const BADGE_TONES = {
  verified: "good", pinned: "good", eval: "good", published: "good",
  approved: "good",
  untrusted: "bad", changed: "bad", retired: "bad", denied: "bad",
  unsigned: "warn", unreachable: "warn", deprecated: "warn", expired: "warn",
  cancelled: "muted",
};

function badgeLabel(label) {
  const tone = BADGE_TONES[label] || "muted";
  return tone === "good" ? "badge"
    : tone === "bad" ? "badge bad"
      : tone === "warn" ? "badge warn" : "badge muted";
}

function badgeSpan(label) {
  const span = document.createElement("span");
  span.className = badgeLabel(label);
  span.textContent = label;
  return span;
}

function span(text, className) {
  const el = document.createElement("span");
  if (className) el.className = className;
  el.textContent = text == null ? "" : String(text);
  return el;
}

function registryCard(entry) {
  const local = entry.source !== "remote";
  const card = document.createElement("button");
  card.type = "button";
  card.className = "card";
  card.setAttribute("aria-pressed", "false");

  const head = span(entry.id, "card-head");
  if (local) {
    if (entry.version) {
      head.appendChild(document.createTextNode(" "));
      head.appendChild(span(entry.version, "muted"));
    }
  } else if (entry.label) {
    head.appendChild(document.createTextNode(" "));
    head.appendChild(span(entry.label, "muted"));
  }
  card.appendChild(head);
  if (local && entry.description) card.appendChild(span(entry.description, "card-desc"));

  const badges = span(null, "card-badges");
  badges.appendChild(badgeSpan(local ? "local" : "remote"));
  if (local) {
    if (entry.artifact) badges.appendChild(badgeSpan(entry.artifact.status || "unknown"));
    badges.appendChild(badgeSpan(entry.has_eval_report ? "eval" : "no eval"));
    badges.appendChild(badgeSpan((entry.lifecycle && entry.lifecycle.status) || "published"));
  } else {
    const trust = entry.trust || {};
    badges.appendChild(badgeSpan(trust.status || "unknown"));
    if (!entry.enabled) badges.appendChild(badgeSpan("disabled"));
  }
  card.appendChild(badges);

  if (local) {
    const published = String(entry.published_at || "").replace("T", " ").slice(0, 19);
    const digest = String(entry.digest || "").replace(/^sha256:/, "").slice(0, 12);
    card.appendChild(span(published + " " + digest, "card-meta"));
  } else {
    card.appendChild(span("peer " + (entry.peer_id || ""), "card-meta"));
  }
  return card;
}

function pressCard(card) {
  for (const other of $("registry-cards").children) {
    other.setAttribute("aria-pressed", other === card ? "true" : "false");
  }
}

function updateRefreshRemote() {
  $("refresh-remote").disabled = !selectedRegistry || selectedRegistry.source !== "remote";
}

function append(who, text) {
  const line = document.createElement("div");
  line.className = who;
  line.textContent = (who === "you" ? "you: " : who + ": ") + text;
  $("log").appendChild(line);
  $("log").scrollTop = $("log").scrollHeight;
}

function info(text) {
  const line = document.createElement("div");
  line.className = "muted";
  line.textContent = text;
  $("log").appendChild(line);
  $("log").scrollTop = $("log").scrollHeight;
}

async function refreshAgents() {
  const result = await getJson("/api/agents");
  if (!result.ok) return result;
  const agents = result.data || [];
  for (const selectId of ["agent", "session-agent"]) {
    const select = $(selectId);
    select.innerHTML = "";
    for (const a of agents) {
      const o = document.createElement("option");
      o.value = a.name;
      o.textContent = a.name + (a.description ? " - " + a.description : "");
      select.appendChild(o);
    }
  }
  return { ok: true, status: result.status, agents: agents };
}

async function loadAgents() {
  const result = await refreshAgents();
  if (!result.ok) { append("system", "connect failed (" + result.status + ")"); return; }
  info("connected: " + result.agents.map((a) => a.name).join(", "));
}

async function loadTenants() {
  const result = await getJson("/api/tenants");
  if (!result.ok) {
    $("registry-msg").textContent = "tenants unavailable (" + result.status + ")";
    return;
  }
  const select = $("tenant");
  select.innerHTML = "";
  for (const tenant of result.data || []) {
    const option = document.createElement("option");
    option.value = tenant;
    option.textContent = tenant;
    select.appendChild(option);
  }
  if (can("registry.read")) await loadRegistry();
}

async function loadRegistry() {
  const tenant = $("tenant").value;
  $("registry-msg").textContent = "";
  const cards = $("registry-cards");
  const empty = $("registry-empty");
  cards.innerHTML = "";
  empty.hidden = true;
  if (!tenant) return;
  const result = await getJson("/api/registry?tenant=" + encodeURIComponent(tenant));
  if (!result.ok) {
    $("registry-msg").textContent = "registry unavailable (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  const entries = result.data || [];
  for (const entry of entries) {
    const card = registryCard(entry);
    card.addEventListener("click", () => {
      pressCard(card);
      selectRegistryEntry(tenant, entry);
    });
    cards.appendChild(card);
  }
  empty.hidden = entries.length !== 0;
  updateRefreshRemote();
}

async function selectRegistryEntry(tenant, entry) {
  selectedRegistry = entry;
  updateRefreshRemote();
  $("artifact-msg").textContent = "";
  if (entry.source === "remote") {
    $("manifest").textContent = "remote catalog entry " + entry.peer_id + ": " + entry.id;
    $("eval-report").textContent = "no eval report";
    $("artifact-info").textContent = "no artifact";
    $("lifecycle-info").textContent = "not applicable";
    return;
  }
  $("artifact-info").textContent = entry.artifact
    ? JSON.stringify(entry.artifact, null, 2)
    : "no artifact";
  $("lifecycle-info").textContent = JSON.stringify(
    entry.lifecycle || { status: "published" }, null, 2);
  $("manifest").textContent = JSON.stringify(entry.manifest, null, 2);
  $("eval-report").textContent = "";
  if (!entry.has_eval_report) { $("eval-report").textContent = "no eval report"; return; }
  const path = "/api/registry/" + encodeURIComponent(tenant) + "/" +
    encodeURIComponent(entry.id) + "/" + encodeURIComponent(entry.version) + "/eval";
  const result = await getJson(path);
  $("eval-report").textContent = result.ok
    ? JSON.stringify(result.data, null, 2)
    : "eval report unavailable (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
}

async function openChat() {
  if (!selectedRegistry) {
    $("artifact-msg").textContent = "select a registry entry first";
    return;
  }
  if (selectedRegistry.source === "remote") {
    $("artifact-msg").textContent = "remote agents cannot be opened here";
    return;
  }
  const select = $("agent");
  const name = selectedRegistry.id;
  const state = selectedRegistry.lifecycle || { status: "published" };
  if (state.status === "retired") {
    $("artifact-msg").textContent =
      "version is retired" + (state.reason ? ": " + state.reason : "");
    return;
  }
  let loaded = Array.from(select.options).some((option) => option.value === name);
  if (!loaded) {
    $("artifact-msg").textContent =
      "loading " + name + " " + selectedRegistry.version + "...";
    const result = await postJson("/api/registry/load", {
      tenant: selectedRegistry.tenant,
      id: name,
      version: selectedRegistry.version,
    });
    if (!result.ok) {
      const conflict = result.status === 409 && result.data &&
        result.data.error === "name_conflict";
      if (!conflict) {
        $("artifact-msg").textContent = "load failed (" + result.status + "): " +
          ((result.data && result.data.error) || "error");
        return;
      }
      const removed = await postJson("/api/registry/unload", { name: name });
      if (!removed.ok) {
        $("artifact-msg").textContent = "swap failed (" + removed.status + "): " +
          ((removed.data && removed.data.error) || "error");
        return;
      }
      const retry = await postJson("/api/registry/load", {
        tenant: selectedRegistry.tenant,
        id: name,
        version: selectedRegistry.version,
      });
      if (!retry.ok) {
        $("artifact-msg").textContent = "swap failed (" + retry.status + "): " +
          ((retry.data && retry.data.error) || "error");
        return;
      }
    }
    await refreshAgents();
    loaded = Array.from($("agent").options).some((option) => option.value === name);
    if (!loaded) {
      $("artifact-msg").textContent = "agent " + name + " is not available";
      return;
    }
  }
  $("artifact-msg").textContent = "";
  select.value = name;
  sessionId = null;
  showTab("chat");
}

async function refreshSelectedRemote() {
  if (!selectedRegistry || selectedRegistry.source !== "remote") return;
  const result = await postJson(
    "/api/remote-agents/" + encodeURIComponent(selectedRegistry.id) + "/refresh", {});
  $("artifact-msg").textContent = result.ok
    ? "refresh: " + ((result.data && result.data.status) || "ok")
    : "refresh failed (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
  await loadRegistry();
}

async function loadTools() {
  const tenant = $("tenant").value;
  $("tools-msg").textContent = "";
  const body = $("tools-body");
  body.innerHTML = "";
  if (!tenant) return;
  const result = await getJson("/api/tools?tenant=" + encodeURIComponent(tenant));
  if (!result.ok) {
    $("tools-msg").textContent = "tools unavailable (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  for (const tool of result.data || []) {
    const row = document.createElement("tr");
    row.appendChild(cell(tool.tool_id));
    row.appendChild(cell(tool.source));
    row.appendChild(cell((tool.data_classes || []).join(", ") || "-"));
    row.appendChild(cell(tool.requires_approval ? "yes" : "no"));
    const agents = (tool.granted_agents || []).map((a) => a.id + "@" + a.version).join(", ");
    row.appendChild(cell(agents || "-"));
    body.appendChild(row);
  }
}

async function loadConnectors() {
  const tenant = $("tenant").value;
  $("connectors-msg").textContent = "";
  const body = $("connectors-body");
  body.innerHTML = "";
  if (!tenant) return;
  const result = await getJson("/api/connectors?tenant=" + encodeURIComponent(tenant));
  if (!result.ok) {
    $("connectors-msg").textContent = "connectors unavailable (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  for (const connector of result.data || []) {
    const row = document.createElement("tr");
    row.appendChild(cell(connector.connector_id));
    row.appendChild(cell(connector.tenant || "global"));
    row.appendChild(cell(connector.kind));
    row.appendChild(cell(connector.base_url));
    row.appendChild(cell((connector.methods || []).join(", ")));
    row.appendChild(cell(connector.enabled ? "yes" : "no"));
    row.addEventListener("click", () => { selectedConnector = connector; });
    body.appendChild(row);
  }
}

function listValue(id) {
  return $(id).value.split(",").map((item) => item.trim()).filter(Boolean);
}

async function registerConnector() {
  $("connectors-msg").textContent = "";
  const tenant = $("connector-tenant").value.trim();
  const body = {
    connector_id: $("connector-id").value.trim(),
    kind: $("connector-kind").value,
    base_url: $("connector-base-url").value.trim(),
    methods: listValue("connector-methods"),
    path_prefixes: listValue("connector-prefixes"),
    data_classes: listValue("connector-data-classes"),
  };
  if (tenant) body.tenant = tenant;
  const authRef = $("connector-auth-ref").value.trim();
  if (authRef) body.auth_ref = authRef;
  const result = await postJson("/api/connectors", body);
  if (!result.ok) {
    $("connectors-msg").textContent = "register failed (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  $("connectors-msg").textContent = "registered " + result.data.connector_id;
  await loadConnectors();
}

async function disableConnector() {
  if (!selectedConnector) {
    $("connectors-msg").textContent = "select a connector first";
    return;
  }
  const result = await postJson(
    "/api/connectors/" + encodeURIComponent(selectedConnector.connector_id) + "/disable", {});
  if (!result.ok) {
    $("connectors-msg").textContent = "disable failed (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  $("connectors-msg").textContent = "disabled " + result.data.connector_id;
  selectedConnector = result.data;
  await loadConnectors();
}

async function checkConnector() {
  $("connector-health").textContent = "";
  if (!selectedConnector) {
    $("connector-health").textContent = "select a connector first";
    return;
  }
  const result = await postJson(
    "/api/connectors/" + encodeURIComponent(selectedConnector.connector_id) + "/check", {});
  if (!result.ok) {
    $("connector-health").textContent = "check failed (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  const health = result.data;
  $("connector-health").textContent =
    health.status + " status=" + health.status_code + " latency=" + health.latency_ms + "ms";
}

async function loadConnectorRequests() {
  const tenant = $("tenant").value;
  $("connector-requests-msg").textContent = "";
  const body = $("connector-requests-body");
  body.innerHTML = "";
  selectedConnectorRequest = null;
  if (!tenant) return;
  let url = "/api/connector-requests?tenant=" + encodeURIComponent(tenant);
  const status = $("connector-request-status").value;
  if (status) url += "&status=" + encodeURIComponent(status);
  const result = await getJson(url);
  if (!result.ok) {
    $("connector-requests-msg").textContent =
      "requests unavailable (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  for (const item of result.data || []) {
    const row = document.createElement("tr");
    row.appendChild(cell(item.request_id));
    row.appendChild(cell(item.tenant));
    row.appendChild(cell(item.spec && item.spec.connector_id));
    row.appendChild(cell(item.status));
    row.appendChild(cell(item.requested_by));
    row.appendChild(cell(item.reason));
    row.addEventListener("click", () => {
      selectedConnectorRequest = item;
      $("connector-requests-msg").textContent = "selected " + item.request_id;
    });
    body.appendChild(row);
  }
}

async function requestConnector() {
  $("connector-requests-msg").textContent = "";
  const methods = listValue("connector-request-methods");
  const prefixes = listValue("connector-request-prefixes");
  const spec = {
    connector_id: $("connector-request-id").value.trim(),
    tenant: $("tenant").value,
    kind: $("connector-request-kind").value,
    base_url: $("connector-request-base-url").value.trim(),
    methods: methods.length ? methods : ["GET"],
    path_prefixes: prefixes.length ? prefixes : ["/"],
    data_classes: listValue("connector-request-data-classes"),
  };
  const authRef = $("connector-request-auth-ref").value.trim();
  if (authRef) spec.auth_ref = authRef;
  const result = await postJson("/api/connector-requests", {
    spec: spec,
    reason: $("connector-request-reason").value.trim(),
  });
  if (!result.ok) {
    $("connector-requests-msg").textContent = "request failed (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  await loadConnectorRequests();
  $("connector-requests-msg").textContent = "requested " + result.data.request_id;
}

async function decideConnectorRequest(approved) {
  if (!selectedConnectorRequest) {
    $("connector-requests-msg").textContent = "select a request first";
    return;
  }
  const result = await postJson(
    "/api/connector-requests/" + encodeURIComponent(selectedConnectorRequest.request_id) +
      "/decide", { approved: approved });
  if (!result.ok) {
    $("connector-requests-msg").textContent = "decision failed (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  selectedConnectorRequest = null;
  await loadConnectorRequests();
  await loadConnectors();
  $("connector-requests-msg").textContent = "decided " + result.data.request_id;
}

async function loadCredentials() {
  const tenant = $("tenant").value;
  $("credentials-msg").textContent = "";
  const body = $("credentials-body");
  body.innerHTML = "";
  if (!tenant) return;
  const filter = $("credential-tenant").value.trim() || tenant;
  const result = await getJson("/api/credentials?tenant=" + encodeURIComponent(filter));
  if (!result.ok) {
    $("credentials-msg").textContent = "credentials unavailable (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  for (const binding of result.data || []) {
    const row = document.createElement("tr");
    row.appendChild(cell(binding.credential_id));
    row.appendChild(cell(binding.tenant));
    row.appendChild(cell(binding.secret_ref));
    row.appendChild(cell(binding.description));
    row.appendChild(cell(binding.enabled ? "enabled" : "disabled"));
    row.addEventListener("click", () => { selectedCredential = binding; });
    body.appendChild(row);
  }
}

async function registerCredential() {
  $("credentials-msg").textContent = "";
  const tenant = $("credential-tenant").value.trim() || $("tenant").value;
  const body = {
    credential_id: $("credential-id").value.trim(),
    tenant: tenant,
    secret_ref: $("credential-ref").value.trim(),
    description: $("credential-description").value.trim(),
  };
  const result = await postJson("/api/credentials", body);
  if (!result.ok) {
    $("credentials-msg").textContent = "register failed (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  $("credentials-msg").textContent = "registered " + result.data.credential_id;
  await loadCredentials();
}

async function disableCredential() {
  if (!selectedCredential) {
    $("credentials-msg").textContent = "select a credential first";
    return;
  }
  const result = await postJson(
    "/api/credentials/" + encodeURIComponent(selectedCredential.credential_id) +
      "/disable?tenant=" + encodeURIComponent(selectedCredential.tenant), {});
  if (!result.ok) {
    $("credentials-msg").textContent = "disable failed (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  $("credentials-msg").textContent = "disabled " + result.data.credential_id;
  selectedCredential = result.data;
  await loadCredentials();
}

function peerGrantsText(grants) {
  const text = (grants || []).map(
    (grant) => grant.agent_id + ":" + (grant.actions || []).join("+")
  ).join(", ");
  return text || "-";
}

async function loadPeers() {
  const tenant = $("tenant").value;
  $("peers-msg").textContent = "";
  const body = $("peers-body");
  body.innerHTML = "";
  const path = tenant ? "/api/peers?tenant=" + encodeURIComponent(tenant) : "/api/peers";
  const result = await getJson(path);
  if (!result.ok) {
    $("peers-msg").textContent = "peers unavailable (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  for (const entry of result.data || []) {
    const peer = entry.peer;
    const row = document.createElement("tr");
    row.appendChild(cell(peer.peer_id));
    row.appendChild(cell(peer.tenant));
    row.appendChild(cell(peer.subject));
    row.appendChild(cell(peer.kind));
    row.appendChild(cell(peer.enabled ? "yes" : "no"));
    row.appendChild(cell(peerGrantsText(entry.grants)));
    row.addEventListener("click", () => { selectedPeer = peer; });
    body.appendChild(row);
  }
}

async function registerPeer() {
  $("peers-msg").textContent = "";
  const id = $("peer-id").value.trim();
  const body = {
    peer_id: id,
    tenant: $("peer-tenant").value.trim(),
    subject: $("peer-subject").value.trim() || id,
    kind: $("peer-kind").value,
  };
  const result = await postJson("/api/peers", body);
  if (!result.ok) {
    $("peers-msg").textContent = "register failed (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  $("peers-msg").textContent = "registered " + result.data.peer_id;
  selectedPeer = result.data;
  await loadPeers();
}

async function disablePeer() {
  if (!selectedPeer) {
    $("peers-msg").textContent = "select a peer first";
    return;
  }
  const result = await postJson(
    "/api/peers/" + encodeURIComponent(selectedPeer.peer_id) + "/disable", {});
  if (!result.ok) {
    $("peers-msg").textContent = "disable failed (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  $("peers-msg").textContent = "disabled " + result.data.peer_id;
  selectedPeer = result.data;
  await loadPeers();
}

function peerActions() {
  const actions = [];
  if ($("peer-action-read").checked) actions.push("read");
  if ($("peer-action-invoke").checked) actions.push("invoke");
  return actions;
}

async function grantPeer() {
  if (!selectedPeer) {
    $("peers-msg").textContent = "select a peer first";
    return;
  }
  const agent = $("peer-agent").value.trim();
  const result = await postJson(
    "/api/peers/" + encodeURIComponent(selectedPeer.peer_id) + "/grants",
    { agent_id: agent, actions: peerActions() });
  if (!result.ok) {
    $("peers-msg").textContent = "grant failed (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  $("peers-msg").textContent =
    "granted " + result.data.agent_id + " " + (result.data.actions || []).join("+");
  await loadPeers();
}

async function revokePeer() {
  if (!selectedPeer) {
    $("peers-msg").textContent = "select a peer first";
    return;
  }
  const agent = $("peer-agent").value.trim();
  const result = await deleteJson(
    "/api/peers/" + encodeURIComponent(selectedPeer.peer_id) + "/grants/" +
    encodeURIComponent(agent));
  if (!result.ok) {
    $("peers-msg").textContent = "revoke failed (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  $("peers-msg").textContent = result.data.revoked ? "revoked " + agent : "no grant for " + agent;
  await loadPeers();
}

async function unloadAgent() {
  if (!selectedRegistry) {
    $("artifact-msg").textContent = "select a registry entry first";
    return;
  }
  const result = await postJson("/api/registry/unload", { name: selectedRegistry.id });
  if (!result.ok) {
    $("artifact-msg").textContent = "unload failed (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  $("artifact-msg").textContent = "unloaded " + selectedRegistry.id;
  await refreshAgents();
  await loadRegistry();
}

async function loadRuns() {
  const result = await getJson("/api/runs?limit=50");
  if (!result.ok) {
    $("runs-msg").textContent = "runs unavailable (" + result.status + ")";
    return;
  }
  $("runs-msg").textContent = "";
  const body = $("runs-body");
  body.innerHTML = "";
  for (const run of result.data || []) {
    const row = document.createElement("tr");
    row.appendChild(cell(String(run.run_id).slice(0, 12)));
    row.appendChild(cell(run.agent_id));
    row.appendChild(cell(run.status));
    const started = document.createElement("td");
    started.textContent = String(run.started_at || "").replace("T", " ").slice(0, 19);
    row.appendChild(started);
    row.appendChild(cell(run.latency_ms == null ? "-" : run.latency_ms + "ms"));
    row.appendChild(cell(run.cost_usd == null ? "-" : run.cost_usd));
    row.appendChild(cell(run.events));
    row.addEventListener("click", () => {
      body.querySelectorAll("tr.selected").forEach((other) => other.classList.remove("selected"));
      row.classList.add("selected");
      showTab("runs");
      loadTrace(run.trace_id);
    });
    body.appendChild(row);
  }
}

async function loadSessions() {
  const agent = $("session-agent").value;
  $("sessions-msg").textContent = "";
  const body = $("sessions-body");
  body.innerHTML = "";
  if (!agent) return;
  const result = await getJson("/api/sessions?agent=" + encodeURIComponent(agent));
  if (!result.ok) {
    $("sessions-msg").textContent = "sessions unavailable (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  for (const session of result.data || []) {
    const row = document.createElement("tr");
    row.appendChild(cell(session.session_id));
    const updated = document.createElement("td");
    updated.textContent = String(session.last_update_time || "").replace("T", " ").slice(0, 19);
    row.appendChild(updated);
    row.addEventListener("click", () => {
      sessionId = session.session_id;
      showTab("chat");
      append("system", "session " + session.session_id);
      $("selected-session").textContent = "session: " + session.session_id;
    });
    body.appendChild(row);
  }
}

function expiryLabel(value) {
  if (!value) return { text: "no deadline", soon: false };
  const left = Date.parse(value) - Date.now();
  if (Number.isNaN(left)) return { text: value, soon: false };
  if (left <= 0) return { text: "expired", soon: true };
  const minutes = Math.ceil(left / 60000);
  if (minutes < 60) return { text: minutes + "m left", soon: minutes <= 10 };
  const hours = Math.floor(minutes / 60);
  return { text: hours + "h " + (minutes % 60) + "m left", soon: false };
}

function approvalMatches(request, needle) {
  if (!needle) return true;
  const agent = request.agent_ref ? request.agent_ref.id : "";
  return [request.request_id, request.step_id, agent, request.reason].some(
    (value) => String(value || "").toLowerCase().includes(needle),
  );
}

function prettyInput(value) {
  if (typeof value !== "string") return JSON.stringify(value, null, 2);
  try { return JSON.stringify(JSON.parse(value), null, 2); } catch (e) { return value; }
}

function renderApprovals() {
  const needle = $("approval-filter").value.trim().toLowerCase();
  const body = $("approvals-body");
  body.innerHTML = "";
  const visible = approvalsData.filter((request) => approvalMatches(request, needle));
  for (const request of visible) {
    const row = document.createElement("tr");
    if (selectedApproval && selectedApproval.request_id === request.request_id) {
      row.classList.add("selected");
    }
    row.appendChild(cell(String(request.request_id).slice(0, 16)));
    row.appendChild(cell(request.step_id));
    row.appendChild(cell(request.agent_ref && request.agent_ref.id));
    row.appendChild(cell(request.reason));
    const requested = document.createElement("td");
    requested.textContent = String(request.requested_at || "").replace("T", " ").slice(0, 19);
    row.appendChild(requested);
    const expires = document.createElement("td");
    const label = expiryLabel(request.expires_at);
    const badge = document.createElement("span");
    badge.className = "expiry" + (label.soon ? " soon" : "");
    badge.textContent = label.text;
    if (request.expires_at) badge.title = request.expires_at;
    expires.appendChild(badge);
    row.appendChild(expires);
    row.addEventListener("click", () => {
      selectedApproval = request;
      renderApprovals();
      renderApprovalDetail();
    });
    body.appendChild(row);
  }
  const empty = $("approval-empty");
  empty.hidden = visible.length > 0;
  empty.textContent = approvalsData.length === 0 ? "没有待决审批。" : "没有匹配的审批。";
}

function renderApprovalDetail() {
  const summary = $("approval-summary");
  summary.innerHTML = "";
  if (!selectedApproval) { $("approval-detail").textContent = ""; return; }
  const request = selectedApproval;
  const expires = request.expires_at
    ? String(request.expires_at).replace("T", " ").slice(0, 19) +
      " (" + expiryLabel(request.expires_at).text + ")"
    : "no deadline";
  const fields = [
    ["request", request.request_id],
    ["run", request.run_id],
    ["trace", request.trace_id],
    ["step", request.step_id],
    ["agent", request.agent_ref
      ? request.agent_ref.id + "@" + request.agent_ref.version
      : "-"],
    ["tenant", request.principal ? request.principal.tenant : "-"],
    ["requested", String(request.requested_at || "").replace("T", " ").slice(0, 19)],
    ["expires", expires],
  ];
  for (const [caption, value] of fields) {
    const box = document.createElement("div");
    const label = document.createElement("span");
    label.textContent = caption;
    const content = document.createElement("b");
    content.textContent = value == null || value === "" ? "-" : value;
    box.append(label, content);
    summary.appendChild(box);
  }
  $("approval-detail").textContent = prettyInput(request.input);
}

async function loadApprovals() {
  $("approvals-msg").className = "panel-msg";
  $("approvals-msg").textContent = "";
  const result = await getJson("/api/approvals");
  if (!result.ok) {
    approvalsData = [];
    selectedApproval = null;
    renderApprovals();
    renderApprovalDetail();
    $("approval-empty").hidden = true;
    $("approvals-msg").textContent = result.status === 404
      ? "approvals not configured"
      : "approvals unavailable (" + result.status + ")";
    return;
  }
  approvalsData = result.data || [];
  if (selectedApproval) {
    selectedApproval = approvalsData.find(
      (request) => request.request_id === selectedApproval.request_id,
    ) || null;
  }
  renderApprovals();
  renderApprovalDetail();
}

async function loadApprovalHistory() {
  $("approval-history-msg").className = "panel-msg";
  $("approval-history-msg").textContent = "";
  const body = $("approval-history-body");
  body.innerHTML = "";
  const status = $("approval-history-status").value;
  let path = "/api/approvals/history?limit=50";
  if (status) path += "&status=" + encodeURIComponent(status);
  const result = await getJson(path);
  if (!result.ok) {
    $("approval-history-msg").textContent = result.status === 404
      ? "approvals not configured"
      : "history unavailable (" + result.status + ")";
    return;
  }
  const entries = result.data || [];
  if (entries.length === 0) {
    $("approval-history-msg").className = "muted";
    $("approval-history-msg").textContent = "no approval history";
    return;
  }
  for (const entry of entries) {
    const request = entry.request || {};
    const decision = entry.decision || {};
    const agentRef = request.agent_ref || {};
    const row = document.createElement("tr");
    row.appendChild(cell(request.request_id));
    const statusCell = document.createElement("td");
    statusCell.appendChild(badgeSpan(entry.status));
    row.appendChild(statusCell);
    row.appendChild(cell(agentRef.id ? agentRef.id + "@" + (agentRef.version || "") : null));
    row.appendChild(cell(decision.approver));
    const terminal = document.createElement("td");
    terminal.textContent = String(entry.terminal_at || "").replace("T", " ").slice(0, 19);
    row.appendChild(terminal);
    row.appendChild(cell(decision.reason));
    row.appendChild(cell(entry.archived ? "yes" : "no"));
    body.appendChild(row);
  }
}

async function decideApproval(approved) {
  if (!selectedApproval) {
    $("approvals-msg").textContent = "select a request first";
    return;
  }
  const requestId = selectedApproval.request_id;
  const reason = $("approval-reason").value.trim();
  const r = await fetch("/api/approvals/" + encodeURIComponent(requestId), {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + token() },
    body: JSON.stringify({ approved: approved, reason: reason }),
  });
  let data = null;
  try { data = await r.json(); } catch (e) { data = null; }
  if (!r.ok) {
    $("approvals-msg").textContent = (data && data.error) ||
      ("decision failed (" + r.status + ")");
    return;
  }
  selectedApproval = null;
  $("approval-reason").value = "";
  $("approval-summary").innerHTML = "";
  $("approval-detail").textContent = "";
  await loadApprovals();
  $("approvals-msg").className = "panel-msg ok";
  $("approvals-msg").textContent = (approved ? "approved " : "denied ") + data.request_id;
  loadAudit();
}

async function loadGrants() {
  const tenant = $("tenant").value;
  $("grants-msg").textContent = "";
  const body = $("grants-body");
  body.innerHTML = "";
  if (!tenant) return;
  const result = await getJson("/api/tool-grants?tenant=" + encodeURIComponent(tenant));
  if (!result.ok) {
    $("grants-msg").textContent = result.status === 404
      ? "tool grants not configured"
      : "tool grants unavailable (" + result.status + "): " +
        ((result.data && result.data.error) || "error");
    return;
  }
  for (const grant of result.data || []) {
    const row = document.createElement("tr");
    row.appendChild(cell(grant.tool_id));
    row.appendChild(cell(grant.agent_id));
    row.appendChild(cell(grant.version));
    const status = document.createElement("td");
    status.textContent = grant.status;
    const left = Date.parse(grant.expires_at) - Date.now();
    if (grant.status === "approved" && left > 0 && left <= 24 * 3600 * 1000) {
      const badge = document.createElement("span");
      badge.className = "badge muted";
      badge.textContent = "expiring";
      status.appendChild(document.createTextNode(" "));
      status.appendChild(badge);
    }
    row.appendChild(status);
    const expires = document.createElement("td");
    expires.textContent = String(grant.expires_at || "").replace("T", " ").slice(0, 19);
    row.appendChild(expires);
    row.addEventListener("click", () => {
      selectedGrant = grant.request_id;
      $("grants-msg").textContent = "selected " + grant.request_id;
    });
    body.appendChild(row);
  }
  const usage = await getJson("/api/tool-grants/usage?tenant=" + encodeURIComponent(tenant));
  const usageBody = $("grant-usage-body");
  usageBody.innerHTML = "";
  if (usage.ok) {
    for (const row of usage.data || []) {
      const tr = document.createElement("tr");
      tr.appendChild(cell(row.tool_id));
      tr.appendChild(cell(row.allowed));
      tr.appendChild(cell(row.denied));
      tr.appendChild(cell(row.temporary));
      usageBody.appendChild(tr);
    }
  }
}

async function requestGrant() {
  if (!selectedRegistry) {
    $("grants-msg").textContent = "select a registry entry first";
    return;
  }
  const toolId = $("grant-tool").value.trim();
  const reason = $("grant-reason").value.trim();
  if (!toolId || !reason) {
    $("grants-msg").textContent = "tool id and reason are required";
    return;
  }
  const result = await postJson("/api/tool-grants", {
    tenant: selectedRegistry.tenant,
    agent_id: selectedRegistry.id,
    version: selectedRegistry.version,
    digest: selectedRegistry.digest,
    tool_id: toolId,
    reason: reason,
  });
  if (!result.ok) {
    $("grants-msg").textContent = "request failed (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  await loadGrants();
  $("grants-msg").textContent = "requested " + result.data.request_id;
}

async function decideGrant(approved) {
  if (!selectedGrant) {
    $("grants-msg").textContent = "select a request first";
    return;
  }
  const result = await postJson(
    "/api/tool-grants/" + encodeURIComponent(selectedGrant) + "/decide",
    { approved: approved },
  );
  if (!result.ok) {
    $("grants-msg").textContent = (result.data && result.data.error) ||
      ("decision failed (" + result.status + ")");
    return;
  }
  selectedGrant = null;
  await loadGrants();
  $("grants-msg").textContent = "decided " + result.data.request_id;
  loadAudit();
}

async function loadPlans() {
  $("plans-msg").textContent = "";
  const body = $("plans-body");
  body.innerHTML = "";
  const result = await getJson("/api/plans?limit=50");
  if (!result.ok) {
    $("plans-msg").textContent = "plans unavailable (" + result.status + ")";
    return;
  }
  for (const plan of result.data || []) {
    const row = document.createElement("tr");
    row.appendChild(cell(plan.plan_id));
    row.appendChild(cell(plan.tenant));
    row.appendChild(cell(plan.status));
    row.appendChild(cell(plan.steps));
    row.appendChild(cell(plan.approvals));
    const started = document.createElement("td");
    started.textContent = String(plan.started_at || "").replace("T", " ").slice(0, 19);
    row.appendChild(started);
    row.addEventListener("click", () => { showTab("plans"); loadTrace(plan.trace_id, "plan-trace"); });
    body.appendChild(row);
  }
}

async function connect() {
  const result = await refreshAgents();
  if (!result.ok) {
    loginError("连接失败 (" + result.status + ")");
    return;
  }
  sessionStorage.setItem(TOKEN_KEY, token());
  showApp();
  await loadMe();
  applyCapabilities();
  $("who").textContent = "已连接";
  info("connected: " + result.agents.map((a) => a.name).join(", "));
  await loadTenants();
  if (can("ops.read")) {
    await loadOverview();
    await loadQuota();
    await loadRag();
    await loadSemantics();
  }
  if (can("audit.read")) await loadAuditPanel();
  if (can("model.read")) {
    await loadModel();
    await loadModelConfig();
  }
  startLive();
  if (can("runs.read")) await loadRuns();
  if (can("sessions.read")) await loadSessions();
  if (can("approvals.read")) await loadApprovals();
  if (can("approvals.read")) await loadApprovalHistory();
  if (can("runs.read")) await loadPlans();
  if (can("tools.read")) await loadTools();
  if (can("connectors.read")) await loadConnectors();
  if (can("connectors.read")) await loadConnectorRequests();
  if (can("connectors.read")) await loadCredentials();
  if (can("grants.read")) await loadGrants();
  if (can("chat.run")) loadAudit();
  applyHashTab();
}

function resetProgress() {
  $("timeline").innerHTML = "";
  $("trace").innerHTML = "";
  $("status").textContent = "starting...";
}

function addStep(text, cls) {
  const line = document.createElement("div");
  if (cls) line.className = cls;
  line.textContent = text;
  $("timeline").appendChild(line);
  $("timeline").scrollTop = $("timeline").scrollHeight;
}

function describe(p) {
  const ms = p.elapsed_ms == null ? "" : " (" + p.elapsed_ms + "ms)";
  if (p.kind === "run.started") return "run started";
  if (p.kind === "tool.call") return "tool call: " + p.tool;
  if (p.kind === "tool.result") return "tool result: " + p.tool;
  if (p.kind === "model.text") return "model: " + String(p.text || "").slice(0, 120);
  if (p.kind === "run.finished") return "run finished" + ms;
  if (p.kind === "run.failed") return "run failed: " + (p.detail || "error") + ms;
  return p.kind;
}

function parseEvent(block) {
  const out = { name: "", data: {} };
  for (const line of block.split(String.fromCharCode(10))) {
    if (line.startsWith("event: ")) out.name = line.slice(7);
    else if (line.startsWith("data: ")) out.data = JSON.parse(line.slice(6));
  }
  return out;
}

async function send() {
  const message = $("msg").value.trim();
  if (!message) return;
  if (window.__adkTimer) clearInterval(window.__adkTimer);
  $("msg").value = "";
  append("you", message);
  resetProgress();
  const startedAt = performance.now();
  window.__adkTimer = setInterval(() => {
    $("status").textContent = "running " + ((performance.now() - startedAt) / 1000).toFixed(1) + "s";
  }, 200);

  const body = { agent: $("agent").value, message };
  if (sessionId) body.session_id = sessionId;
  const r = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + token() },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const data = await r.json();
    clearInterval(window.__adkTimer);
    $("status").textContent = "error";
    append("system", data.error || ("error " + r.status));
    return;
  }

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let traceId = null;
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      let index;
      while ((index = buffer.indexOf(String.fromCharCode(10) + String.fromCharCode(10))) >= 0) {
        const block = buffer.slice(0, index);
        buffer = buffer.slice(index + 2);
        const ev = parseEvent(block);
        if (ev.name === "progress") {
          const p = ev.data;
          const cls = p.kind === "run.failed" ? "fail" : (p.kind.startsWith("tool") ? "tool" : "");
          addStep(describe(p), cls);
          $("status").textContent = describe(p);
        } else if (ev.name === "done") {
          clearInterval(window.__adkTimer);
          sessionId = ev.data.session_id;
          traceId = ev.data.trace_id;
          append("agent", ev.data.reply || "(empty)");
          append("system", "trace " + ev.data.trace_id);
          $("status").textContent = "idle";
          loadAudit();
          loadTrace(ev.data.trace_id);
        } else if (ev.name === "error") {
          clearInterval(window.__adkTimer);
          $("status").textContent = "error";
          append("system", ev.data.error || "agent run failed");
        }
      }
    }
  } finally {
    clearInterval(window.__adkTimer);
    if (!traceId) $("status").textContent = "stream ended";
  }
}

const TRACE_KINDS = {
  agent: "agent", plan: "plan", model: "model", tool: "tool", step: "step",
  supervisor: "supervisor", approval: "approval", policy: "policy",
};

const ms = (value) => (value == null ? null : value + "ms");
const TRACE_DETAIL_FIELDS = [
  ["kind", (n) => n.kind],
  ["action", (n) => n.action],
  ["target", (n) => n.target],
  ["status", (n) => n.status],
  ["error", (n) => n.error_code],
  ["start offset", (n) => ms(n.start_offset_ms)],
  ["duration", (n) => ms(n.duration_ms)],
  ["latency", (n) => ms(n.latency_ms)],
  ["cost", (n) => (n.cost_usd == null ? null : "$" + n.cost_usd)],
  ["tokens", (n) => n.tokens],
  ["tenant", (n) => n.tenant],
  ["principal", (n) => (n.principal ? n.principal.subject + " (" + n.principal.kind + ")" : null)],
  ["approver", (n) => n.approver],
  ["agent", (n) => (n.agent ? n.agent.id + "@" + n.agent.version : null)],
  ["args hash", (n) => n.args_hash],
  ["result hash", (n) => n.result_hash],
  ["policy decision", (n) => n.policy_decision_id],
  ["policy version", (n) => n.policy_version],
  ["data classes", (n) => (n.data_classes && n.data_classes.length ? n.data_classes.join(", ") : null)],
  ["egress", (n) => n.egress],
  ["event id", (n) => n.event_id],
  ["run id", (n) => n.run_id],
  ["timestamp", (n) => n.timestamp],
];

function renderTraceDetail(detail, node) {
  detail.textContent = "";
  for (const [label, getter] of TRACE_DETAIL_FIELDS) {
    const labelCell = document.createElement("span");
    labelCell.className = "trace-detail-label";
    labelCell.textContent = label;
    const valueCell = document.createElement("span");
    valueCell.className = "trace-detail-value";
    const value = getter(node);
    valueCell.textContent = value == null ? "-" : String(value);
    detail.append(labelCell, valueCell);
  }
}

function selectTraceRow(row, node) {
  const box = row.parentElement;
  for (const other of box.querySelectorAll(".trace-row")) {
    const chosen = other === row;
    other.classList.toggle("selected", chosen);
    other.setAttribute("aria-pressed", chosen ? "true" : "false");
  }
  const detail = box.querySelector(".trace-detail");
  if (detail) renderTraceDetail(detail, node);
}

function traceSpan(node, total) {
  const row = document.createElement("div");
  row.className = "trace-row";
  row.tabIndex = 0;
  row.setAttribute("role", "button");
  row.setAttribute("aria-pressed", "false");
  row.addEventListener("click", () => selectTraceRow(row, node));
  row.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectTraceRow(row, node);
    }
  });
  const label = document.createElement("div");
  label.className = "trace-label";
  const kind = document.createElement("span");
  kind.className = "kind";
  kind.textContent = node.kind;
  label.appendChild(kind);
  label.appendChild(document.createTextNode(node.id || "-"));
  const track = document.createElement("div");
  track.className = "trace-track";
  const bar = document.createElement("div");
  const kindClass = TRACE_KINDS[node.kind] || "other";
  bar.className = "trace-bar " + kindClass + " " + (node.status || "");
  bar.style.left = ((node.start_offset_ms || 0) / total * 100) + "%";
  bar.style.width = Math.max((node.duration_ms || 0) / total * 100, 0.4) + "%";
  bar.title = node.kind + " " + node.id + " · +" + (node.start_offset_ms || 0) +
    "ms · " + (node.duration_ms || 0) + "ms · " + node.status +
    (node.error_code ? " [" + node.error_code + "]" : "");
  track.appendChild(bar);
  const meta = document.createElement("div");
  meta.className = "trace-meta";
  const status = document.createElement("span");
  status.className = node.status === "error" || node.status === "denied" ? "bad" : "";
  status.textContent = node.status + " · +" + (node.start_offset_ms || 0) +
    "ms · " + (node.duration_ms || 0) + "ms";
  meta.appendChild(status);
  if (node.error_code) meta.appendChild(document.createTextNode(" [" + node.error_code + "]"));
  if (node.cost_usd != null) meta.appendChild(document.createTextNode(" $" + node.cost_usd));
  row.append(label, track, meta);
  return row;
}

function renderTrace(box, data) {
  box.innerHTML = "";
  const root = data.root;
  const spans = [root].concat(root.children || []);
  const total = Math.max(data.total_ms || 0, 1);
  const cost = spans.reduce((sum, node) => sum + (node.cost_usd || 0), 0);
  const summary = document.createElement("div");
  summary.className = "trace-summary";
  summary.textContent = "trace " + data.trace_id + " · " + spans.length + " spans · " +
    (data.total_ms || 0) + "ms total" + (cost > 0 ? " · $" + cost.toFixed(4) : "");
  box.appendChild(summary);
  const axis = document.createElement("div");
  axis.className = "trace-axis";
  axis.appendChild(document.createElement("div"));
  const scale = document.createElement("div");
  scale.className = "track";
  const start = document.createElement("span");
  start.textContent = "0ms";
  const end = document.createElement("span");
  end.textContent = (data.total_ms || 0) + "ms";
  scale.append(start, end);
  axis.appendChild(scale);
  axis.appendChild(document.createElement("div"));
  box.appendChild(axis);
  for (const node of spans) box.appendChild(traceSpan(node, total));
  const detail = document.createElement("div");
  detail.className = "trace-detail";
  detail.textContent = "select a span to see details";
  box.appendChild(detail);
}

async function loadTrace(traceId, targetId) {
  const boxId = targetId || "trace";
  const box = $(boxId);
  const r = await fetch("/api/traces/" + encodeURIComponent(traceId), {
    headers: { Authorization: "Bearer " + token() },
  });
  if (!r.ok) { box.textContent = "trace unavailable (" + r.status + ")"; return; }
  const data = await r.json();
  if (!data.root) { box.textContent = "trace not found"; return; }
  renderTrace(box, data);
}

async function loadAudit() {
  if (capabilities !== null && !capabilities.has("audit.read")) return;
  const r = await fetch("/api/audit?limit=20", { headers: { Authorization: "Bearer " + token() } });
  if (!r.ok) { append("system", "audit failed (" + r.status + ")"); return; }
  const rows = await r.json();
  const box = $("audit");
  box.innerHTML = "";
  for (const e of rows.slice().reverse()) {
    const line = document.createElement("div");
    line.textContent = e.action + " " + e.target + " " + e.status + " " +
      (e.latency_ms ?? "-") + "ms run=" + e.run_id.slice(0, 8) +
      " trace=" + e.trace_id.slice(0, 8);
    box.appendChild(line);
  }
}

async function loadAuditPanel() {
  const r = await fetch("/api/audit?limit=100", { headers: { Authorization: "Bearer " + token() } });
  const box = $("audit-panel-log");
  if (!box) return;
  if (!r.ok) { box.textContent = "audit unavailable (" + r.status + ")"; return; }
  const rows = await r.json();
  box.innerHTML = "";
  for (const e of rows.slice().reverse()) {
    const line = document.createElement("div");
    line.textContent = e.action + " " + e.target + " " + e.status + " " +
      (e.latency_ms ?? "-") + "ms run=" + (e.run_id || "").slice(0, 8) +
      " trace=" + (e.trace_id || "").slice(0, 8);
    box.appendChild(line);
  }
}

async function loadQuota() {
  const result = await getJson("/api/quota");
  const container = $("quota-cards");
  if (!container) return;
  container.innerHTML = "";
  if (!result.ok || !result.data) return;
  const q = result.data;
  const cards = [
    { label: "窗口运行数", value: q.window_runs },
    { label: "活跃并发", value: q.active_leases },
    { label: "运行上限", value: q.max_runs === null ? "无限" : q.max_runs },
    { label: "并发上限", value: q.max_concurrent === null ? "无限" : q.max_concurrent },
    { label: "窗口秒数", value: q.window_seconds },
  ];
  for (const card of cards) {
    const el = document.createElement("div");
    el.className = "stat-card";
    const label = document.createElement("div");
    label.className = "stat-label";
    label.textContent = card.label;
    const value = document.createElement("div");
    value.className = "stat-value";
    value.textContent = String(card.value);
    el.appendChild(label);
    el.appendChild(value);
    container.appendChild(el);
  }
}

async function loadRag() {
  const result = await getJson("/api/rag");
  const container = $("rag-cards");
  if (!container) return;
  container.innerHTML = "";
  if (!result.ok || !result.data) return;
  const q = result.data;
  const cards = [
    { label: "最近检索", value: q.recent_retrievals },
    { label: "最近 top_k", value: q.last_top_k === null ? "—" : q.last_top_k },
    { label: "最近返回", value: q.last_returned === null ? "—" : q.last_returned },
  ];
  for (const card of cards) {
    const el = document.createElement("div");
    el.className = "stat-card";
    const label = document.createElement("div");
    label.className = "stat-label";
    label.textContent = card.label;
    const value = document.createElement("div");
    value.className = "stat-value";
    value.textContent = String(card.value);
    el.appendChild(label);
    el.appendChild(value);
    container.appendChild(el);
  }
}

async function loadModel() {
  const result = await getJson("/api/model");
  const container = $("model-cards");
  if (!container) return;
  container.innerHTML = "";
  if (!result.ok || !result.data) return;
  const q = result.data;
  const cards = [
    { label: "最近调用", value: q.recent_calls },
    { label: "使用别名", value: q.aliases.length ? q.aliases.join(", ") : "—" },
    { label: "降级次数", value: q.fallbacks },
  ];
  for (const card of cards) {
    const el = document.createElement("div");
    el.className = "stat-card";
    const label = document.createElement("div");
    label.className = "stat-label";
    label.textContent = card.label;
    const value = document.createElement("div");
    value.className = "stat-value";
    value.textContent = String(card.value);
    el.appendChild(label);
    el.appendChild(value);
    container.appendChild(el);
  }
}

async function loadModelConfig() {
  const result = await getJson("/api/model-config");
  const box = $("model-config");
  if (!box) return;
  if (!result.ok) {
    box.textContent = "model-config unavailable (" + result.status + ")";
    return;
  }
  const model = result.data && result.data.model;
  box.textContent = "当前默认模型: " + (model || "未配置");
}

async function saveModelConfig() {
  const box = $("model-config-msg");
  const input = $("model-config-input");
  box.className = "panel-msg";
  box.textContent = "";
  const model = input.value.trim();
  if (!model) {
    box.textContent = "模型字符串不能为空";
    return;
  }
  const result = await putJson("/api/model-config", { model: model });
  if (!result.ok) {
    box.textContent = "保存失败 (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  box.className = "panel-msg ok";
  box.textContent = "已设置 " + result.data.model;
  await loadModelConfig();
}

async function loadSemantics() {
  const result = await getJson("/api/semantics");
  const container = $("semantics-schemes");
  if (!container) return;
  container.innerHTML = "";
  if (!result.ok) return;
  for (const scheme of result.data || []) {
    const el = document.createElement("div");
    el.className = "stat-card";
    const label = document.createElement("div");
    label.className = "stat-label";
    label.textContent = "术语表";
    const value = document.createElement("div");
    value.className = "stat-value";
    value.textContent = scheme.scheme_id + " (" + ((scheme.concepts || []).length) + " 概念)";
    el.appendChild(label);
    el.appendChild(value);
    container.appendChild(el);
  }
}

async function runSemanticsRoute() {
  const text = $("semantics-route-text").value;
  if (!text) return;
  const schemes = await getJson("/api/semantics");
  const schemeId = schemes.data && schemes.data.length ? schemes.data[0].scheme_id : null;
  if (!schemeId) { $("semantics-route-result").textContent = "no scheme"; return; }
  const result = await postJson("/api/semantics/route", {
    scheme_id: schemeId,
    text: text,
    bindings: [],
  });
  const box = $("semantics-route-result");
  box.textContent = result.ok ? JSON.stringify(result.data) : "route failed (" + result.status + ")";
}

async function runImport() {
  const kind = $("import-kind").value;
  const raw = $("import-payload").value;
  if (!raw) return;
  let payload;
  try { payload = JSON.parse(raw); } catch (e) { $("import-result").textContent = "invalid json"; return; }
  const result = await postJson("/api/import/" + kind, payload);
  const box = $("import-result");
  box.textContent = result.ok
    ? JSON.stringify(result.data)
    : "import failed (" + result.status + "): " + ((result.data && result.data.error) || "error");
}

async function runAskAi() {
  const text = $("ask-ai-text").value;
  if (!text) return;
  const result = await postJson("/api/ask-ai", { text: text, bindings: [] });
  const box = $("ask-ai-result");
  box.textContent = result.ok
    ? JSON.stringify(result.data)
    : "ask failed (" + result.status + "): " + ((result.data && result.data.error) || "error");
}

async function startLive() {
  const r = await fetch("/api/live", { headers: { Authorization: "Bearer " + token() } });
  if (!r.ok) return;
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      let index;
      while ((index = buffer.indexOf(String.fromCharCode(10) + String.fromCharCode(10))) >= 0) {
        const block = buffer.slice(0, index);
        buffer = buffer.slice(index + 2);
        const ev = parseEvent(block);
        if (ev.name === "tick") {
          if (can("ops.read")) {
            loadOverview();
            loadQuota();
            loadRag();
            loadSemantics();
          }
          if (can("model.read")) {
            loadModel();
            loadModelConfig();
          }
        }
      }
    }
  } finally {
    setTimeout(startLive, 3000);
  }
}

async function loadPolicy() {
  const r = await fetch("/api/policy", { headers: { Authorization: "Bearer " + token() } });
  if (!r.ok) { $("policy-msg").textContent = "policy unavailable (" + r.status + ")"; return; }
  $("policy").value = JSON.stringify(await r.json(), null, 2);
  $("policy-msg").textContent = "loaded";
}

async function savePolicy() {
  let body;
  try { body = JSON.parse($("policy").value); }
  catch (e) { $("policy-msg").textContent = "invalid json"; return; }
  const r = await fetch("/api/policy", {
    method: "PUT",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + token() },
    body: JSON.stringify(body),
  });
  const data = await r.json();
  $("policy-msg").textContent = r.ok ? "saved version " + data.version : (data.error || "save failed");
}

$("agent").addEventListener("change", () => { sessionId = null; append("system", "agent switched"); });
const TOKEN_KEY = "adk_token";
const PKCE_VERIFIER_KEY = "adk_pkce_verifier";
const PKCE_STATE_KEY = "adk_pkce_state";
let oidcConfig = { enabled: false };

function showApp() { $("login").hidden = true; $("app").hidden = false; }
function showLogin() { $("app").hidden = true; $("login").hidden = false; }
function loginError(message) { $("login-msg").textContent = message || ""; }

async function loadAuthConfig() {
  try {
    const response = await fetch("/auth/config");
    oidcConfig = await response.json();
  } catch (e) {
    oidcConfig = { enabled: false };
  }
  if (oidcConfig.enabled) {
    $("oidc-login").hidden = false;
    $("token-row").hidden = true;
  }
}

function base64url(bytes) {
  let text = "";
  for (const byte of bytes) text += String.fromCharCode(byte);
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(size) {
  const bytes = new Uint8Array(size);
  crypto.getRandomValues(bytes);
  return base64url(bytes);
}

async function pkceChallenge(verifier) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64url(new Uint8Array(digest));
}

async function startOidcLogin() {
  const verifier = randomString(48);
  const state = randomString(16);
  sessionStorage.setItem(PKCE_VERIFIER_KEY, verifier);
  sessionStorage.setItem(PKCE_STATE_KEY, state);
  const params = new URLSearchParams({
    response_type: "code",
    client_id: oidcConfig.client_id,
    redirect_uri: oidcConfig.redirect_uri,
    scope: (oidcConfig.scopes || []).join(" "),
    state: state,
    code_challenge: await pkceChallenge(verifier),
    code_challenge_method: "S256",
  });
  const separator = oidcConfig.authorization_endpoint.includes("?") ? "&" : "?";
  location.assign(oidcConfig.authorization_endpoint + separator + params.toString());
}

async function finishOidcLogin() {
  const params = new URLSearchParams(location.search);
  const code = params.get("code");
  const state = params.get("state");
  const expected = sessionStorage.getItem(PKCE_STATE_KEY);
  if (!code || !state || !expected || state !== expected) {
    loginError("登录状态不匹配，请重试");
    return false;
  }
  const verifier = sessionStorage.getItem(PKCE_VERIFIER_KEY);
  sessionStorage.removeItem(PKCE_STATE_KEY);
  sessionStorage.removeItem(PKCE_VERIFIER_KEY);
  if (!verifier) { loginError("缺少 PKCE verifier，请重试"); return false; }
  let response;
  try {
    response = await fetch("/auth/token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code: code,
        code_verifier: verifier,
        redirect_uri: oidcConfig.redirect_uri,
      }),
    });
  } catch (e) {
    loginError("登录服务不可达");
    return false;
  }
  if (!response.ok) { loginError("登录失败 (" + response.status + ")"); return false; }
  const data = await response.json();
  if (!data.access_token) { loginError("登录响应缺少 access token"); return false; }
  sessionStorage.setItem(TOKEN_KEY, data.access_token);
  history.replaceState({}, "", "/");
  return true;
}

function logout() {
  sessionStorage.removeItem(TOKEN_KEY);
  location.assign("/");
}

function initTheme() {
  const saved = localStorage.getItem("adk_theme");
  if (saved) document.documentElement.dataset.theme = saved;
}

function toggleTheme() {
  const dark = document.documentElement.dataset.theme === "dark";
  if (dark) delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = "dark";
  localStorage.setItem("adk_theme", dark ? "" : "dark");
}

function applyHashTab() {
  const name = location.hash.replace("#", "");
  if (TABS.includes(name)) showTab(name);
}

async function bootstrap() {
  initTheme();
  await loadAuthConfig();
  const onCallback = location.pathname === "/auth/callback";
  if (oidcConfig.enabled) {
    if (onCallback) {
      const ok = await finishOidcLogin();
      if (!ok) { showLogin(); return; }
    }
    const saved = sessionStorage.getItem(TOKEN_KEY);
    if (!saved) { showLogin(); return; }
    $("token").value = saved;
    await connect();
    return;
  }
  const saved = sessionStorage.getItem(TOKEN_KEY);
  if (saved) { $("token").value = saved; await connect(); }
  else showLogin();
}

$("tenant").addEventListener("change", () => {
  loadOverview();
  if (can("registry.read")) loadRegistry();
  if (can("tools.read")) loadTools();
  if (can("connectors.read")) loadConnectors();
  if (can("connectors.read")) loadConnectorRequests();
  if (can("connectors.read")) loadCredentials();
  if (can("grants.read")) loadGrants();
});
$("session-agent").addEventListener("change", loadSessions);
$("refresh").addEventListener("click", loadAudit);
$("refresh-audit-panel").addEventListener("click", loadAuditPanel);
$("semantics-route-run").addEventListener("click", runSemanticsRoute);
$("import-run").addEventListener("click", runImport);
$("ask-ai-run").addEventListener("click", runAskAi);
$("refresh-registry").addEventListener("click", loadRegistry);
$("refresh-remote").addEventListener("click", refreshSelectedRemote);
$("open-chat").addEventListener("click", openChat);
$("unload-agent").addEventListener("click", unloadAgent);
$("refresh-runs").addEventListener("click", loadRuns);
$("refresh-tools").addEventListener("click", loadTools);
$("refresh-connectors").addEventListener("click", loadConnectors);
$("connector-register").addEventListener("click", registerConnector);
$("connector-disable").addEventListener("click", disableConnector);
$("connector-check").addEventListener("click", checkConnector);
$("refresh-connector-requests").addEventListener("click", loadConnectorRequests);
$("connector-request-status").addEventListener("change", loadConnectorRequests);
$("connector-request-submit").addEventListener("click", requestConnector);
$("connector-request-approve").addEventListener("click", () => decideConnectorRequest(true));
$("connector-request-deny").addEventListener("click", () => decideConnectorRequest(false));
$("refresh-credentials").addEventListener("click", loadCredentials);
$("credential-tenant").addEventListener("input", loadCredentials);
$("credential-register").addEventListener("click", registerCredential);
$("credential-disable").addEventListener("click", disableCredential);
$("refresh-peers").addEventListener("click", loadPeers);
$("peer-register").addEventListener("click", registerPeer);
$("peer-disable").addEventListener("click", disablePeer);
$("peer-grant").addEventListener("click", grantPeer);
$("peer-revoke").addEventListener("click", revokePeer);
$("refresh-sessions").addEventListener("click", loadSessions);
$("refresh-approvals").addEventListener("click", loadApprovals);
$("approval-filter").addEventListener("input", renderApprovals);
$("refresh-approval-history").addEventListener("click", loadApprovalHistory);
$("approval-history-status").addEventListener("change", loadApprovalHistory);
$("refresh-grants").addEventListener("click", loadGrants);
$("grant-request").addEventListener("click", requestGrant);
$("grant-approve").addEventListener("click", () => decideGrant(true));
$("grant-deny").addEventListener("click", () => decideGrant(false));
$("refresh-plans").addEventListener("click", loadPlans);
$("approve").addEventListener("click", () => decideApproval(true));
$("deny").addEventListener("click", () => decideApproval(false));
$("load-policy").addEventListener("click", () => { if (can("policy.read")) loadPolicy(); });
$("save-policy").addEventListener("click", savePolicy);
$("model-config-save").addEventListener("click", saveModelConfig);
$("connect").addEventListener("click", connect);
$("send").addEventListener("click", send);
$("msg").addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
for (const tab of TABS) {
  $("tab-" + tab).addEventListener("click", () => showTab(tab));
}
$("oidc-login").addEventListener("click", startOidcLogin);
$("logout").addEventListener("click", logout);
$("theme").addEventListener("click", toggleTheme);
bootstrap();
</script>
</body>
</html>
"""


def _session_service(session_db: str | None, *, rls: bool = False) -> Any:
    from .runtime.sessions import configured_session_service

    service = configured_session_service(session_db, rls=rls)
    if service is not None:
        return service

    from google.adk.sessions import InMemorySessionService

    return InMemorySessionService()


async def _session_id_for(session_service: Any, app_name: str, raw: object, user_id: str) -> str:
    """Return an existing session for this agent, or create a new one."""
    if isinstance(raw, str) and raw:
        session = await session_service.get_session(
            app_name=app_name, user_id=user_id, session_id=raw
        )
        if session is not None:
            return str(session.id)
    session = await session_service.create_session(app_name=app_name, user_id=user_id)
    return str(session.id)


def _trace_id(request: Request) -> str:
    return resolve_trace_id(
        request.headers.get("x-trace-id"),
        request.headers.get("traceparent"),
    )


_ACTION_KINDS = {
    "agent.run": "agent",
    "orchestration.run": "plan",
    "model.call": "model",
    "tool.call": "tool",
    "orchestration.step": "step",
    "orchestration.supervisor": "supervisor",
    "orchestration.approval": "approval",
    "policy.update": "policy",
}


def _trace_node(event: AuditEvent) -> dict:
    return {
        "id": event.target,
        "kind": _ACTION_KINDS.get(event.action, event.action),
        "status": event.status,
        "error_code": event.error_code,
        "latency_ms": event.latency_ms,
        "cost_usd": event.cost_usd,
        "timestamp": event.timestamp.isoformat(),
        "event_id": event.event_id,
        "run_id": event.run_id,
        "action": event.action,
        "target": event.target,
        "tenant": event.tenant,
        "principal": {"subject": event.principal.subject, "kind": event.principal.kind},
        "agent": {"id": event.agent_ref.id, "version": event.agent_ref.version},
        "approver": event.approver,
        "args_hash": event.args_hash,
        "result_hash": event.result_hash,
        "policy_decision_id": event.policy_decision_id,
        "policy_version": event.policy_version,
        "data_classes": list(event.data_classes),
        "tokens": event.tokens,
        "egress": event.egress,
    }


def _trace_payload(events: Iterable[AuditEvent], trace_id: str) -> dict:
    relevant = sorted(
        (event for event in events if event.trace_id == trace_id),
        key=lambda event: event.timestamp,
    )
    root = next(
        (
            event
            for event in reversed(relevant)
            if event.action in ("agent.run", "orchestration.run")
        ),
        None,
    )
    if root is None:
        return {"trace_id": trace_id, "root": None, "error": "trace_not_found"}

    root_node = _trace_node(root)
    children: list[dict] = []
    total_ms = 0
    for event in relevant:
        node = root_node if event is root else _trace_node(event)
        offset = max(0, int((event.timestamp - root.timestamp).total_seconds() * 1000))
        duration = max(0, event.latency_ms or 0)
        node["start_offset_ms"] = offset
        node["duration_ms"] = duration
        total_ms = max(total_ms, offset + duration)
        if event is not root:
            children.append(node)
    root_node["children"] = children
    return {"trace_id": trace_id, "root": root_node, "total_ms": total_ms, "error": None}


def _peer_ref(identity: PeerIdentity) -> AgentRef:
    return AgentRef(
        id=identity.peer_id,
        version="peer",
        digest=f"sha256:{hash_text(identity.model_dump_json())}",
    )


def _remote_ref(record: RemoteAgent) -> AgentRef:
    return AgentRef(id=record.remote_id, version="remote", digest=record.card_digest)


def _visible_events(events: Iterable[AuditEvent], principal: Principal) -> list[AuditEvent]:
    visible = list(events)
    if "admin" in principal.roles:
        return visible
    return [event for event in visible if event.tenant == principal.tenant]


def _summarize_runs(events: Iterable[AuditEvent], limit: int) -> list[dict]:
    limit = min(max(limit, 1), 200)
    groups: dict[str, list[AuditEvent]] = {}
    for event in events:
        groups.setdefault(event.run_id, []).append(event)

    summaries: list[tuple[datetime, dict]] = []
    for run_id, group in groups.items():
        ordered = sorted(group, key=lambda event: event.timestamp)
        last = ordered[-1]
        latency_ms = next(
            (event.latency_ms for event in reversed(ordered) if event.latency_ms is not None),
            None,
        )
        cost_usd = next(
            (event.cost_usd for event in reversed(ordered) if event.cost_usd is not None),
            None,
        )
        summaries.append(
            (
                last.timestamp,
                {
                    "run_id": run_id,
                    "trace_id": last.trace_id,
                    "agent_id": last.agent_ref.id,
                    "tenant": last.tenant,
                    "status": last.status,
                    "started_at": ordered[0].timestamp.isoformat(),
                    "last_at": last.timestamp.isoformat(),
                    "latency_ms": latency_ms,
                    "cost_usd": cost_usd,
                    "events": len(ordered),
                },
            )
        )

    summaries.sort(key=lambda item: item[0], reverse=True)
    return [summary for _, summary in summaries[:limit]]


def _summarize_plans(events: Iterable[AuditEvent], limit: int) -> list[dict]:
    limit = min(max(limit, 1), 200)
    groups: dict[str, list[AuditEvent]] = {}
    for event in events:
        groups.setdefault(event.trace_id, []).append(event)

    summaries: list[tuple[datetime, dict]] = []
    for trace_id, group in groups.items():
        runs = [event for event in group if event.action == "orchestration.run"]
        if not runs:
            continue
        ordered = sorted(group, key=lambda event: event.timestamp)
        latest = max(runs, key=lambda event: event.timestamp)
        summaries.append(
            (
                ordered[-1].timestamp,
                {
                    "trace_id": trace_id,
                    "plan_id": latest.target,
                    "agent_id": latest.agent_ref.id,
                    "tenant": latest.tenant,
                    "status": latest.status,
                    "error_code": latest.error_code,
                    "started_at": ordered[0].timestamp.isoformat(),
                    "last_at": ordered[-1].timestamp.isoformat(),
                    "steps": sum(1 for event in group if event.action == "orchestration.step"),
                    "approvals": sum(
                        1 for event in group if event.action == "orchestration.approval"
                    ),
                    "latency_ms": latest.latency_ms,
                    "cost_usd": latest.cost_usd,
                },
            )
        )

    summaries.sort(key=lambda item: item[0], reverse=True)
    return [summary for _, summary in summaries[:limit]]


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


class ProgressBuffer:
    """Bounded queue for progress events that never drops terminal events."""

    def __init__(self, max_progress: int) -> None:
        if max_progress < 1:
            raise ValueError("max_progress must be at least 1")
        self._max_progress = max_progress
        self._queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()
        self._progress = 0
        self.dropped = 0
        self.peak_depth = 0

    @property
    def depth(self) -> int:
        return self._queue.qsize()

    def _observe(self) -> None:
        self.peak_depth = max(self.peak_depth, self._queue.qsize())

    def put_progress(self, payload: dict) -> None:
        if self._progress >= self._max_progress:
            self._queue.get_nowait()
            self.dropped += 1
            self._progress -= 1
        self._queue.put_nowait(("progress", payload))
        self._progress += 1
        self._observe()

    async def put_terminal(self, kind: str, payload: dict) -> None:
        await self._queue.put((kind, {**payload, "dropped": self.dropped}))
        self._observe()

    async def get(self) -> tuple[str, dict]:
        item = await self._queue.get()
        if item[0] == "progress":
            self._progress -= 1
        return item


def _wrap_model(agent: Any, audit: AuditSink) -> None:
    """Route an agent's ADK model through the policy gateway."""
    model = getattr(agent, "model", None)
    if isinstance(model, BaseLlm):
        provider = provider_for_model(model)
        agent.model = GatewayLlm(
            model=model.model,
            delegate=model,
            provider=provider,
            policy=ModelPolicy(provider_allowlist=[provider]),
            audit=audit,
        )
    for sub in getattr(agent, "sub_agents", None) or ():
        _wrap_model(sub, audit)


def build_console_app(
    agents: dict[str, BaseAgent],
    *,
    auth_token: str | None,
    session_db: str | None = None,
    host: str = "127.0.0.1",
    allow_unauthenticated: bool = False,
    sandbox: SandboxPolicy | None = None,
    policy_file: str | None = None,
    roles: list[str] | None = None,
    registry: AgentRegistry | None = None,
    eval_reports: EvalReportStore | None = None,
    tool_catalog: ToolCatalog | None = None,
    lifecycle: AgentLifecycleStore | None = None,
    tool_grants: ToolGrantStore | None = None,
    connectors: ConnectorStore | None = None,
    connector_requests: ConnectorRequestStore | None = None,
    credentials: CredentialStore | None = None,
    peers: PeerStore | None = None,
    peer_grants: PeerGrantStore | None = None,
    remote_agents: RemoteAgentStore | None = None,
    remote_secrets: SecretProvider | None = None,
    artifact_store: ArtifactStore | None = None,
    artifact_loader: ArtifactLoader | None = None,
    artifact_trust: TrustStore | None = None,
    max_loaded_agents: int = 20,
    session_service: Any | None = None,
    audit_sink: AuditSink | None = None,
    audit_query: AuditQuery | None = None,
    oidc: IdentityProvider | None = None,
    oidc_login: OidcLogin | None = None,
    quota: QuotaManager | None = None,
    quota_config: QuotaConfig | None = None,
    approvals: FileApprovalInbox | PostgresApprovalInbox | None = None,
    metrics: MetricsRegistry | None = None,
    sse_queue_size: int = 512,
    rate_limit: RateLimit | None = None,
    session_tenant_scope: bool = False,
    session_rls: bool = False,
    rag: Any | None = None,
    terminology: ConceptSchemeStore | None = None,
    model_config_store: ModelConfigStore | None = None,
    role_store: RoleStore | None = None,
    user_binding_store: UserBindingStore | None = None,
    security_report: str | None = None,
    ui: str = "legacy",
) -> FastAPI:
    """Build the console FastAPI app with one Runner per agent."""
    install_log_sanitizer()
    token = resolve_http_auth(host, auth_token, allow_unauthenticated) if oidc is None else None
    metrics = metrics if metrics is not None else MetricsRegistry()
    principal = Principal(
        tenant="local", subject=_USER_ID, kind="human", roles=list(roles or ["requester"])
    )

    def _principal_for(request: Request) -> Principal:
        found = getattr(request.state, "principal", None)
        return found if found is not None else principal

    async def _effective_roles(caller: Principal) -> set[str]:
        """Token roles plus the tenant-scoped user binding's roles.

        A binding store failure keeps the token roles: a store hiccup must not
        strip capabilities the token already grants, nor add any.
        """
        roles = set(caller.roles)
        if user_binding_store is None:
            return roles
        try:
            binding = await user_binding_store.get(caller.tenant, caller.subject)
        except (UserBindingStoreError, ValueError):
            logger.exception("user binding read failed for tenant=%s", caller.tenant)
            return roles
        if binding is not None:
            roles |= set(binding.roles)
        return roles

    async def _caps_for(caller: Principal) -> list[str]:
        """Capabilities for a principal, from the role store when one is configured.

        A role the store does not define grants nothing, so a principal whose
        roles are all undefined gets the base floor. A store failure fails
        closed the same way rather than falling back to the hardcoded table,
        which would hand ``admin`` its management rights while the store is down.
        """
        if role_store is None:
            return _capabilities_for(await _effective_roles(caller))
        granted: set[str] = set()
        try:
            for name in await _effective_roles(caller):
                definition = await role_store.get(name)
                if definition is not None:
                    granted |= set(definition.capabilities)
        except (RoleStoreError, ValueError):
            # ValueError covers a claim role name the file store's whitelist
            # rejects; RoleDefinition.name uses the same pattern, so such a
            # name can never name a defined role.
            logger.exception("role store failed for tenant=%s", caller.tenant)
            return sorted(CAPABILITIES_BASE)
        return sorted(granted or CAPABILITIES_BASE)

    async def _forbidden_if_missing(caller: Principal, capability: str) -> JSONResponse | None:
        if capability in await _caps_for(caller):
            return None
        return JSONResponse({"error": "forbidden"}, status_code=403)

    def _session_user(caller: Principal) -> str:
        return scoped_user_id(caller) if session_tenant_scope else caller.subject

    def _artifact_info(record: Any) -> dict[str, Any] | None:
        artifact = record.artifact
        if artifact is None:
            return None
        if artifact.signature is None or artifact.key_id is None:
            status = "unsigned"
        elif artifact_trust is None:
            status = "unknown"
        else:
            try:
                artifact_trust.verify(artifact)
            except ArtifactTrustError:
                status = "untrusted"
            else:
                status = "verified"
        return {
            "digest": artifact.digest,
            "size": artifact.size,
            "key_id": artifact.key_id,
            "status": status,
        }

    async def _lifecycle(state_of: Any) -> AgentLifecycle:
        if lifecycle is None:
            return AgentLifecycle.default()
        return await lifecycle.get(
            state_of.manifest.tenant, state_of.manifest.id, state_of.manifest.version
        )

    policy_store = FilePolicyStore(policy_file) if policy_file else None
    policy_engine = RolePolicyEngine(policy_store.load()) if policy_store else None
    audit = audit_sink if audit_sink is not None else ListAuditSink()
    if remote_secrets is not None:
        secrets = remote_secrets
    elif credentials is not None:
        secrets = RoutingSecretProvider(
            TenantSecretProvider(load_key_backend(), credentials, audit=audit),
            PrefixedEnvSecretProvider(),
        )
    else:
        secrets = PrefixedEnvSecretProvider()

    from google.adk.runners import Runner

    service = (
        session_service
        if session_service is not None
        else _session_service(session_db, rls=session_rls)
    )

    async def _emit_peer(
        action: str,
        *,
        target: str,
        caller: Principal,
        identity: PeerIdentity,
        args_hash: str = "",
    ) -> None:
        await audit.emit(
            AuditEvent(
                event_id=uuid.uuid4().hex,
                run_id=uuid.uuid4().hex,
                trace_id=uuid.uuid4().hex,
                tenant=caller.tenant,
                principal=caller,
                agent_ref=_peer_ref(identity),
                action=action,
                target=target,
                args_hash=args_hash or None,
                status="ok",
                timestamp=datetime.now(timezone.utc),
            )
        )

    async def _emit_remote(
        action: str,
        *,
        target: str,
        caller: Principal,
        record: RemoteAgent,
        args_hash: str = "",
    ) -> None:
        await audit.emit(
            AuditEvent(
                event_id=uuid.uuid4().hex,
                run_id=uuid.uuid4().hex,
                trace_id=uuid.uuid4().hex,
                tenant=caller.tenant,
                principal=caller,
                agent_ref=_remote_ref(record),
                action=action,
                target=target,
                args_hash=args_hash or None,
                status="ok",
                timestamp=datetime.now(timezone.utc),
            )
        )

    async def _query_events(request: Request, limit: int = 1000) -> list[AuditEvent]:
        if audit_query is None:
            if isinstance(audit, ListAuditSink):
                return audit.recent(limit)
            path = getattr(audit, "path", None)
            return query_events(path, limit=limit, order="desc") if path is not None else []
        caller = _principal_for(request)
        tenant = None if "admin" in caller.roles else caller.tenant
        return await audit_query.events(tenant=tenant, limit=limit)

    sandbox_policy = sandbox or SandboxPolicy()
    runners: dict[str, Runner] = {}
    runtimes: dict[str, AgentRuntime] = {}

    def _register(name: str, agent: Any, manifest: AgentManifest | None = None) -> None:
        if not isinstance(agent, SandboxAgent):
            _wrap_model(agent, audit)
            install_tool_sandbox(agent, ToolSandbox(sandbox_policy))
            install_declared_guards(agent, audit, overlay=tool_grants)
        runner = Runner(app_name=name, agent=agent, session_service=service)
        agents[name] = agent
        runners[name] = runner
        # Only registry manifests can opt into retrieval; file-loaded agents cannot.
        context = rag.context(manifest) if rag is not None and manifest is not None else None
        runtimes[name] = AgentRuntime(
            runner, audit=audit, metrics=metrics, source="console", rag=context
        )

    for name, agent in list(agents.items()):
        # Registry refs carry their manifest from the loader; file-loaded
        # agents have none and therefore never opt into retrieval.
        _register(name, agent, getattr(agent, "_adk_manifest", None))

    loaded_versions: dict[str, str] = {}
    loaded_tenants: dict[str, str] = {}
    load_lock = asyncio.Lock()

    async def allowed(invocation: Invocation, name: str) -> bool:
        if policy_engine is None:
            return True
        decision = await policy_engine.decide(invocation, "agent.run", name)
        if decision.decision == "allow":
            return True
        await audit.emit(
            AuditEvent(
                event_id=uuid.uuid4().hex,
                run_id=invocation.run_id,
                trace_id=invocation.trace_id,
                tenant=invocation.principal.tenant,
                principal=invocation.principal,
                agent_ref=invocation.agent_ref,
                action="agent.run",
                target=name,
                args_hash=hash_text(invocation.input),
                status="denied",
                error_code="policy_denied",
                timestamp=datetime.now(timezone.utc),
            )
        )
        return False

    app = FastAPI(title="ADK Console", docs_url=None, redoc_url=None)

    @app.exception_handler(AuditQueryUnavailable)
    async def audit_unavailable(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse({"error": "audit_unavailable"}, status_code=502)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics_endpoint() -> PlainTextResponse:
        return PlainTextResponse(
            metrics.render(), media_type="text/plain; version=0.0.4; charset=utf-8"
        )

    if ui == "vue" and (_WEB_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=_WEB_DIST / "assets"), name="vue-assets")
        shell = (_WEB_DIST / "index.html").read_text(encoding="utf-8")
    else:
        shell = _INDEX_HTML

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return shell

    @app.get("/auth/callback", response_class=HTMLResponse)
    async def auth_callback() -> str:
        return shell

    @app.get("/auth/config")
    async def auth_config() -> Any:
        if oidc_login is None:
            return {"enabled": False}
        return oidc_login.public_config()

    @app.post("/auth/token")
    async def oidc_token(request: Request) -> Any:
        if oidc_login is None:
            return JSONResponse({"error": "oidc_not_configured"}, status_code=404)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        code = body.get("code")
        verifier = body.get("code_verifier")
        redirect_uri = body.get("redirect_uri")
        if not isinstance(code, str) or not code:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(verifier, str) or not verifier:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(redirect_uri, str) or not redirect_uri:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        try:
            tokens = await oidc_login.exchange(
                code=code, code_verifier=verifier, redirect_uri=redirect_uri
            )
        except OidcLoginError:
            logger.warning("oidc code exchange failed")
            return JSONResponse({"error": "oidc_login_failed"}, status_code=401)
        return JSONResponse(tokens)

    @app.get("/api/me")
    async def me(request: Request) -> dict[str, Any]:
        caller = _principal_for(request)
        return {
            "tenant": caller.tenant,
            "subject": caller.subject,
            "roles": list(caller.roles),
            "capabilities": await _caps_for(caller),
        }

    def _role_payload(role: RoleDefinition) -> dict[str, Any]:
        return {
            "name": role.name,
            "capabilities": list(role.capabilities),
            "builtin": role.builtin,
            "description": role.description,
        }

    async def _emit_role_event(
        action: str, *, target: str, caller: Principal, request: Request
    ) -> None:
        try:
            await audit.emit(
                AuditEvent(
                    event_id=uuid.uuid4().hex,
                    run_id=uuid.uuid4().hex,
                    trace_id=_trace_id(request),
                    tenant=caller.tenant,
                    principal=caller,
                    agent_ref=AgentRef(
                        id="roles", version="roles", digest=f"sha256:{hash_text(target)}"
                    ),
                    action=action,
                    target=target,
                    status="ok",
                    timestamp=datetime.now(timezone.utc),
                )
            )
        except Exception:  # noqa: BLE001 - a failed audit must not undo the write
            logger.exception("audit emit failed: action=%s target=%s", action, target)

    @app.get("/api/roles")
    async def list_roles(request: Request) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "roles.read")
        if denied is not None:
            return denied
        if role_store is None:
            return JSONResponse({"error": "role_store_not_configured"}, status_code=404)
        try:
            roles = await role_store.list()
        except RoleStoreError:
            logger.exception("role store list failed")
            return JSONResponse({"error": "role_store_unavailable"}, status_code=503)
        return {"roles": [_role_payload(role) for role in roles]}

    @app.put("/api/roles/{name}")
    async def put_role(request: Request, name: str) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "roles.manage")
        if denied is not None:
            return denied
        if role_store is None:
            return JSONResponse({"error": "role_store_not_configured"}, status_code=404)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        try:
            role = RoleDefinition(
                name=name,
                capabilities=tuple(body.get("capabilities") or ()),
                description=body.get("description") or "",
            )
        except (ValidationError, TypeError):
            return JSONResponse({"error": "invalid_role"}, status_code=400)
        existing = await _get_role(role_store, name)
        if existing is not None:
            # Editing must not shed the builtin flag, or a later delete of a
            # built-in role would be allowed.
            role = role.model_copy(update={"builtin": existing.builtin})
            return await _replace_role(role_store, role, caller, request)
        try:
            stored = await role_store.add(role)
        except RoleConflict:
            return JSONResponse({"error": "role_conflict"}, status_code=409)
        except RoleStoreError:
            logger.exception("role write failed: name=%s", name)
            return JSONResponse({"error": "role_store_unavailable"}, status_code=503)
        await _emit_role_event("role.define", target=stored.name, caller=caller, request=request)
        return _role_payload(stored)

    async def _get_role(store: RoleStore, name: str) -> RoleDefinition | None:
        try:
            return await store.get(name)
        except (RoleStoreError, ValueError):
            return None

    async def _replace_role(
        store: RoleStore, role: RoleDefinition, caller: Principal, request: Request
    ) -> Any:
        # The store keeps the first definition and refuses a different one, so a
        # changed definition is written by removing then re-adding the role.
        try:
            await store.delete(role.name)
            stored = await store.add(role)
        except RoleStoreError:
            logger.exception("role write failed: name=%s", role.name)
            return JSONResponse({"error": "role_store_unavailable"}, status_code=503)
        await _emit_role_event("role.define", target=stored.name, caller=caller, request=request)
        return _role_payload(stored)

    @app.delete("/api/roles/{name}")
    async def delete_role(request: Request, name: str) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "roles.manage")
        if denied is not None:
            return denied
        if role_store is None:
            return JSONResponse({"error": "role_store_not_configured"}, status_code=404)
        existing = await _get_role(role_store, name)
        if existing is None:
            return JSONResponse({"error": "role_not_found"}, status_code=404)
        if existing.builtin:
            return JSONResponse({"error": "builtin_role_immutable"}, status_code=409)
        try:
            removed = await role_store.delete(name)
        except RoleStoreError:
            logger.exception("role delete failed: name=%s", name)
            return JSONResponse({"error": "role_store_unavailable"}, status_code=503)
        if not removed:
            return JSONResponse({"error": "role_not_found"}, status_code=404)
        await _emit_role_event("role.remove", target=name, caller=caller, request=request)
        return {"removed": name}

    def _binds_tenant(request: Request, caller: Principal) -> str | JSONResponse:
        """The tenant whose bindings this caller may touch."""
        requested = request.query_params.get("tenant")
        if requested is None:
            return caller.tenant
        if "admin" not in caller.roles:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        if not _SAFE_TENANT.fullmatch(requested):
            return JSONResponse({"error": "invalid_tenant"}, status_code=400)
        return requested

    @app.get("/api/users")
    async def list_users(request: Request) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "roles.read")
        if denied is not None:
            return denied
        if user_binding_store is None:
            return JSONResponse({"error": "user_binding_store_not_configured"}, status_code=404)
        tenant = _binds_tenant(request, caller)
        if isinstance(tenant, JSONResponse):
            return tenant
        try:
            bindings = await user_binding_store.list(tenant)
        except UserBindingStoreError:
            logger.exception("user binding list failed: tenant=%s", tenant)
            return JSONResponse({"error": "user_binding_store_unavailable"}, status_code=503)
        return {
            "users": [
                {"tenant": binding.tenant, "subject": binding.subject, "roles": list(binding.roles)}
                for binding in bindings
            ]
        }

    @app.put("/api/users/{subject}")
    async def put_user(request: Request, subject: str) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "roles.manage")
        if denied is not None:
            return denied
        if user_binding_store is None:
            return JSONResponse({"error": "user_binding_store_not_configured"}, status_code=404)
        tenant = _binds_tenant(request, caller)
        if isinstance(tenant, JSONResponse):
            return tenant
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        try:
            binding = UserBinding(
                tenant=tenant, subject=subject, roles=tuple(body.get("roles") or ())
            )
        except (ValidationError, TypeError):
            return JSONResponse({"error": "invalid_user_binding"}, status_code=400)
        existing = await _get_binding(user_binding_store, tenant, subject)
        try:
            if existing is not None and existing.roles != binding.roles:
                await user_binding_store.delete(tenant, subject)
            stored = await user_binding_store.add(binding)
        except UserBindingConflict:
            return JSONResponse({"error": "user_binding_conflict"}, status_code=409)
        except UserBindingStoreError:
            logger.exception("user binding write failed: tenant=%s", tenant)
            return JSONResponse({"error": "user_binding_store_unavailable"}, status_code=503)
        await _emit_role_event(
            "user.bind", target=f"{stored.tenant}/{stored.subject}", caller=caller, request=request
        )
        return {
            "tenant": stored.tenant,
            "subject": stored.subject,
            "roles": list(stored.roles),
        }

    async def _get_binding(
        store: UserBindingStore, tenant: str, subject: str
    ) -> UserBinding | None:
        try:
            return await store.get(tenant, subject)
        except (UserBindingStoreError, ValueError):
            return None

    @app.delete("/api/users/{subject}")
    async def delete_user(request: Request, subject: str) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "roles.manage")
        if denied is not None:
            return denied
        if user_binding_store is None:
            return JSONResponse({"error": "user_binding_store_not_configured"}, status_code=404)
        tenant = _binds_tenant(request, caller)
        if isinstance(tenant, JSONResponse):
            return tenant
        try:
            removed = await user_binding_store.delete(tenant, subject)
        except UserBindingStoreError:
            logger.exception("user binding delete failed: tenant=%s", tenant)
            return JSONResponse({"error": "user_binding_store_unavailable"}, status_code=503)
        if not removed:
            return JSONResponse({"error": "user_binding_not_found"}, status_code=404)
        await _emit_role_event(
            "user.unbind", target=f"{tenant}/{subject}", caller=caller, request=request
        )
        return {"removed": subject}

    def _audit_backend_name() -> str:
        from .audit.http_sink import HttpAuditQuery
        from .audit.postgres import PostgresAuditQuery
        from .audit.query import FileAuditQuery

        if audit_query is not None:
            if isinstance(audit_query, FileAuditQuery):
                return "file"
            if isinstance(audit_query, HttpAuditQuery):
                return "http"
            if isinstance(audit_query, PostgresAuditQuery):
                return "db"
            return "unknown"
        if isinstance(audit, ListAuditSink):
            return "memory"
        return "file" if getattr(audit, "path", None) is not None else "none"

    def _audit_file_path() -> Path | None:
        from .audit.query import FileAuditQuery

        if isinstance(audit_query, FileAuditQuery):
            return audit_query.path
        path = getattr(audit, "path", None)
        return Path(path) if path is not None else None

    def _audit_signing_summary() -> dict[str, Any]:
        from .audit.keyring import KeyringError, SigningKeyring

        raw = os.environ.get("ADK_AUDIT_KEYRING")
        if raw:
            try:
                keyring = SigningKeyring.from_env(raw)
            except KeyringError:
                # Unparseable or ill-shaped keyrings report a fixed code; the
                # parsed values must never reach the response or the logs.
                return {"active": None, "kids": [], "legacy": False, "error": "invalid_keyring"}
            if keyring is None:  # pragma: no cover - raw is truthy here
                return {"active": None, "kids": [], "legacy": False}
            return {
                "active": keyring.active,
                "kids": sorted(keyring.keys),
                "legacy": keyring.legacy is not None,
            }
        if os.environ.get("ADK_AUDIT_SIGNING_KEY"):
            return {"active": "default", "kids": ["default"], "legacy": False}
        return {"active": None, "kids": [], "legacy": False}

    async def _credential_key_summary(caller: Principal) -> dict[str, Any]:
        active_key_id: str | None = None
        try:
            backend = load_key_backend()
            active_key_id = backend.current_key_id() if backend is not None else None
        except Exception:  # noqa: BLE001 - the summary must never fail the request
            logger.exception("key backend unavailable for the security summary")
        by_key_id: dict[str, int] = {}
        needs_rewrap = 0
        if credentials is not None:
            try:
                bindings = await credentials.list(caller.tenant)
            except CredentialStoreError:
                logger.exception("credential list failed for the security summary")
                bindings = []
            for binding in bindings:
                key = binding.secret_key_id or "unwrapped"
                by_key_id[key] = by_key_id.get(key, 0) + 1
                if (
                    binding.wrapped_secret is not None
                    and active_key_id is not None
                    and binding.secret_key_id != active_key_id
                ):
                    needs_rewrap += 1
        return {
            "active_key_id": active_key_id,
            "by_key_id": by_key_id,
            "needs_rewrap": needs_rewrap,
        }

    _verify_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    async def _verify_audit_chain() -> dict[str, Any]:
        import time

        path = _audit_file_path()
        if path is None:
            return {"verified": None, "error": "backend_unsupported"}
        key = str(path)
        now = time.monotonic()
        cached = _verify_cache.get(key)
        if cached is not None and now - cached[0] < 60:
            return cached[1]
        from .audit import AuditChainBroken, AuditSignatureInvalid
        from .audit.keyring import KeyringError
        from .audit.pipeline import verify_audit_file

        try:
            _signing_key, keyring = _audit_signing_for_console()
        except KeyringError:
            return {"verified": None, "error": "invalid_keyring"}
        try:
            count = await asyncio.wait_for(
                asyncio.to_thread(verify_audit_file, path, keyring=keyring), timeout=10
            )
            result: dict[str, Any] = {"verified": True, "checked_records": count}
        except asyncio.TimeoutError:
            result = {"verified": None, "error": "verify_timeout"}
        except (AuditChainBroken, AuditSignatureInvalid):
            result = {"verified": False, "error": "chain_broken"}
        except Exception:  # noqa: BLE001 - report a fixed code, never the contents
            logger.exception("audit verification failed")
            result = {"verified": False, "error": "verify_failed"}
        _verify_cache[key] = (now, result)
        return result

    def _audit_signing_for_console() -> tuple[str | None, Any]:
        raw = os.environ.get("ADK_AUDIT_KEYRING")
        if raw:
            from .audit.keyring import KeyringError, SigningKeyring

            keyring = SigningKeyring.from_env(raw)
            if keyring is None:  # pragma: no cover - raw is truthy here
                raise KeyringError("ADK_AUDIT_KEYRING is empty")
            return keyring.keys[keyring.active], keyring
        return os.environ.get("ADK_AUDIT_SIGNING_KEY"), None

    def _scan_summary() -> dict[str, Any] | None:
        if security_report is None:
            return None
        try:
            payload = json.loads(Path(security_report).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        return {
            "generated_at": payload.get("generated_at"),
            "codeql": payload.get("codeql") if isinstance(payload.get("codeql"), dict) else None,
            "dependencies": (
                payload.get("dependencies")
                if isinstance(payload.get("dependencies"), dict)
                else None
            ),
        }

    @app.get("/api/security")
    async def security_summary(request: Request) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "ops.read")
        if denied is not None:
            return denied
        try:
            events = await _query_events(request, limit=1000)
        except Exception:  # noqa: BLE001
            logger.exception("audit query failed for the security summary")
            events = []
        audit_block: dict[str, Any] = {
            "backend": _audit_backend_name(),
            "records": len(events),
            "last_event_at": (
                max(events, key=lambda event: event.timestamp).timestamp.isoformat()
                if events
                else None
            ),
            "verified": None,
        }
        if request.query_params.get("verify") == "1":
            audit_block.update(await _verify_audit_chain())
        policy_block = {
            "version": policy_engine.policy.version if policy_engine is not None else None,
            "bindings": len(policy_engine.policy.bindings) if policy_engine is not None else None,
        }
        return {
            "audit": audit_block,
            "keys": {
                "audit_signing": _audit_signing_summary(),
                "credentials": await _credential_key_summary(caller),
            },
            "policy": policy_block,
            "scans": _scan_summary(),
        }

    @app.get("/api/overview")
    async def overview(request: Request) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "ops.read")
        if denied is not None:
            return denied
        caps = set(await _caps_for(caller))
        target = caller.tenant
        cards: list[dict[str, Any]] = [
            {"key": "approvals", "label": "待审批", "panel": "approvals", "value": None},
            {"key": "agents", "label": "已注册 Agent", "panel": "registry", "value": None},
            {"key": "tools", "label": "工具", "panel": "tools", "value": None},
            {"key": "grants", "label": "待处理授权", "panel": "grants", "value": None},
        ]

        if approvals is not None and "approvals.read" in caps:
            try:
                pending = approvals.pending()
                if inspect.isawaitable(pending):
                    pending = await pending
                if "admin" not in caller.roles:
                    pending = [item for item in pending if item.principal.tenant == target]
                cards[0]["value"] = len(pending)
            except ApprovalInboxUnavailable:
                logger.exception("overview approvals failed: tenant=%s", target)

        if registry is not None and "registry.read" in caps:
            try:
                cards[1]["value"] = len(await registry.list(target))
            except (RegistryIntegrityError, ValueError):
                logger.exception("overview registry failed: tenant=%s", target)

        if tool_catalog is not None and "tools.read" in caps:
            cards[2]["value"] = len(tool_catalog.tools)

        if tool_grants is not None and "grants.read" in caps:
            try:
                records = await tool_grants.list(target, status=cast(GrantStatus, "pending"))
                cards[3]["value"] = len(records)
            except GrantStoreError:
                logger.exception("overview grants failed: tenant=%s", target)

        return {"cards": cards}

    @app.get("/api/quota")
    async def get_quota(request: Request) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "ops.read")
        if denied is not None:
            return denied
        if quota is None or quota_config is None:
            return JSONResponse({"error": "quota_not_configured"}, status_code=404)
        policy = quota_config.tenants.get(caller.tenant)
        if policy is None:
            return JSONResponse({"error": "quota_not_configured"}, status_code=404)
        try:
            usage = await quota.usage(caller.tenant, policy)
        except QuotaStoreUnavailable:
            return JSONResponse({"error": "quota_unavailable"}, status_code=503)
        return usage.model_dump(mode="json")

    @app.get("/api/rag")
    async def get_rag(request: Request) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "ops.read")
        if denied is not None:
            return denied
        events = await _query_events(request, limit=200)
        retrievals = [event for event in events if event.action == "rag.retrieve"]
        last = retrievals[-1] if retrievals else None
        return {
            "recent_retrievals": len(retrievals),
            "last_top_k": last.rag_top_k if last else None,
            "last_returned": last.rag_returned if last else None,
        }

    @app.get("/api/model")
    async def get_model(request: Request) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "model.read")
        if denied is not None:
            return denied
        events = await _query_events(request, limit=200)
        calls = [event for event in events if event.action == "model.call"]
        aliases = sorted({event.model_alias for event in calls if event.model_alias})
        fallbacks = sum(event.fallback_count for event in calls)
        return {
            "recent_calls": len(calls),
            "aliases": aliases,
            "fallbacks": fallbacks,
        }

    async def _read_default_model() -> str:
        if model_config_store is not None:
            try:
                stored = await model_config_store.get()
            except ModelConfigStoreUnavailable:
                stored = None
            if stored:
                return stored
        return effective_default_model()

    @app.get("/api/model-config")
    async def get_model_config(request: Request) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "model.read")
        if denied is not None:
            return denied
        return {"model": await _read_default_model()}

    @app.put("/api/model-config")
    async def put_model_config(request: Request) -> JSONResponse:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "model.write")
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid json"}, status_code=400)
        if not isinstance(body, dict) or not isinstance(body.get("model"), str):
            return JSONResponse({"error": "invalid_model"}, status_code=400)
        model = body["model"].strip()
        if not is_valid_model_spec(model):
            return JSONResponse({"error": "invalid_model"}, status_code=400)
        if model_config_store is not None:
            try:
                await model_config_store.put(model)
            except ModelConfigStoreUnavailable:
                return JSONResponse({"error": "model_config_unavailable"}, status_code=503)
        set_default_model(model)
        await audit.emit(
            AuditEvent(
                event_id=uuid.uuid4().hex,
                run_id=uuid.uuid4().hex,
                trace_id=_trace_id(request),
                tenant=caller.tenant,
                principal=caller,
                agent_ref=dev_agent_ref("model"),
                action="model.configure",
                target=model,
                status="ok",
                timestamp=datetime.now(timezone.utc),
            )
        )
        return JSONResponse({"model": model})

    @app.get("/api/semantics")
    async def list_semantics(request: Request) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "ops.read")
        if denied is not None:
            return denied
        if terminology is None:
            return JSONResponse({"error": "terminology_not_configured"}, status_code=404)
        try:
            schemes = await terminology.list(caller.tenant)
        except ConceptSchemeStoreUnavailable:
            return JSONResponse({"error": "terminology_unavailable"}, status_code=503)
        return [scheme.model_dump(mode="json") for scheme in schemes]

    @app.post("/api/semantics/route")
    async def route_semantics(request: Request) -> Any:
        if terminology is None:
            return JSONResponse({"error": "terminology_not_configured"}, status_code=404)
        caller = _principal_for(request)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        scheme_id = body.get("scheme_id")
        text = body.get("text")
        raw_bindings = body.get("bindings")
        if not isinstance(scheme_id, str) or not isinstance(text, str) or not text.strip():
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(raw_bindings, list):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        try:
            scheme = await terminology.get(caller.tenant, scheme_id)
            if scheme is None:
                return JSONResponse({"error": "scheme_not_found"}, status_code=404)
            bindings = [CapabilityBinding.model_validate(b) for b in raw_bindings]
        except ConceptSchemeStoreUnavailable:
            return JSONResponse({"error": "terminology_unavailable"}, status_code=503)
        except ValidationError:
            return JSONResponse({"error": "invalid_binding"}, status_code=400)
        routed = route_request(text, scheme, bindings)
        return [item.model_dump(mode="json") for item in routed]

    @app.post("/api/import/terminology")
    async def import_terminology(request: Request) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "semantics.write")
        if denied is not None:
            return denied
        if terminology is None:
            return JSONResponse({"error": "terminology_not_configured"}, status_code=404)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        try:
            scheme = ConceptScheme.model_validate(body)
        except ValidationError:
            return JSONResponse({"error": "invalid_scheme"}, status_code=400)
        try:
            await terminology.put(caller.tenant, scheme)
        except ConceptSchemeStoreUnavailable:
            return JSONResponse({"error": "terminology_unavailable"}, status_code=503)
        await audit.emit(
            AuditEvent(
                event_id=uuid.uuid4().hex,
                run_id=uuid.uuid4().hex,
                trace_id=_trace_id(request),
                tenant=caller.tenant,
                principal=caller,
                agent_ref=AgentRef(id="terminology", version="0", digest="sha256:" + "0" * 64),
                action="terminology.import",
                target=f"{caller.tenant}/{scheme.scheme_id}",
                status="ok",
                timestamp=datetime.now(timezone.utc),
            )
        )
        return scheme.model_dump(mode="json")

    @app.post("/api/import/agent")
    async def import_agent(request: Request) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "registry.publish")
        if denied is not None:
            return denied
        if registry is None:
            return JSONResponse({"error": "registry_not_configured"}, status_code=404)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        try:
            manifest = AgentManifest.model_validate(body)
        except ValidationError:
            return JSONResponse({"error": "invalid_manifest"}, status_code=400)
        if manifest.tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
        record = published_from(manifest)
        try:
            await registry.publish(record)
        except Exception:  # noqa: BLE001
            return JSONResponse({"error": "registry_unavailable"}, status_code=503)
        await audit.emit(
            AuditEvent(
                event_id=uuid.uuid4().hex,
                run_id=uuid.uuid4().hex,
                trace_id=_trace_id(request),
                tenant=caller.tenant,
                principal=caller,
                agent_ref=AgentRef(id=manifest.id, version=manifest.version, digest=record.digest),
                action="agent.import",
                target=f"{manifest.tenant}/{manifest.id}@{manifest.version}",
                status="ok",
                timestamp=datetime.now(timezone.utc),
            )
        )
        return {"id": manifest.id, "version": manifest.version}

    @app.post("/api/ask-ai")
    async def ask_ai(request: Request) -> Any:
        if terminology is None:
            return JSONResponse({"error": "terminology_not_configured"}, status_code=404)
        caller = _principal_for(request)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        text = body.get("text")
        raw_bindings = body.get("bindings", [])
        if not isinstance(text, str) or not text.strip():
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(raw_bindings, list):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        try:
            schemes = await terminology.list(caller.tenant)
            bindings = [CapabilityBinding.model_validate(b) for b in raw_bindings]
        except ConceptSchemeStoreUnavailable:
            return JSONResponse({"error": "terminology_unavailable"}, status_code=503)
        except ValidationError:
            return JSONResponse({"error": "invalid_binding"}, status_code=400)
        if not schemes:
            return {"hits": [], "scheme_id": None}
        scheme = schemes[0]
        routed = route_request(text, scheme, bindings)
        return {
            "hits": [item.model_dump(mode="json") for item in routed],
            "scheme_id": scheme.scheme_id,
        }

    @app.get("/api/agents")
    async def list_agents() -> list[dict[str, str]]:
        return [
            {"name": name, "description": agent.description or ""} for name, agent in agents.items()
        ]

    @app.get("/api/live")
    async def live(request: Request) -> Any:
        async def events() -> AsyncGenerator[str, None]:
            while True:
                if await request.is_disconnected():
                    break
                yield _sse("tick", {"ts": datetime.now(timezone.utc).isoformat()})
                await asyncio.sleep(5)

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.get("/api/audit")
    async def list_audit(request: Request, limit: int = 50) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "audit.read")
        if denied is not None:
            return denied
        limit = min(max(limit, 1), 200)
        events = _visible_events(await _query_events(request), caller)
        return [event.model_dump(mode="json") for event in events[-limit:]]

    @app.get("/api/tenants")
    async def list_tenants(request: Request) -> Any:
        if registry is None:
            return JSONResponse({"error": "registry_not_configured"}, status_code=404)
        caller = _principal_for(request)
        names = await registry.tenants()
        if "admin" not in caller.roles:
            names = [name for name in names if name == caller.tenant]
        return names

    @app.get("/api/registry")
    async def list_registry(request: Request, tenant: str | None = None) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "registry.read")
        if denied is not None:
            return denied
        if registry is None and remote_agents is None:
            return JSONResponse({"error": "registry_not_configured"}, status_code=404)
        target = tenant or caller.tenant
        if tenant and tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
        if tenant is not None and not _SAFE_NAME.fullmatch(tenant):
            return JSONResponse({"error": "unsafe_tenant"}, status_code=400)

        entries: list[dict[str, Any]] = []
        if registry is not None:
            try:
                records = await registry.list(target)
            except RegistryIntegrityError:
                return JSONResponse({"error": "registry_corrupt"}, status_code=500)
            except ValueError:
                return JSONResponse({"error": "unsafe_tenant"}, status_code=400)
            try:
                states = [await _lifecycle(record) for record in records]
            except Exception:  # noqa: BLE001
                logger.exception("lifecycle read failed")
                return JSONResponse({"error": "lifecycle_unavailable"}, status_code=503)
            for record, state in zip(records, states, strict=True):
                has_report = (
                    await eval_reports.has(target, record.manifest.id, record.manifest.version)
                    if eval_reports is not None
                    else False
                )
                entries.append(
                    {
                        "tenant": target,
                        "id": record.manifest.id,
                        "source": "local",
                        "version": record.manifest.version,
                        "digest": record.digest,
                        "description": record.manifest.description,
                        "published_at": record.published_at.isoformat(),
                        "has_eval_report": has_report,
                        "manifest": record.manifest.model_dump(mode="json"),
                        "artifact": _artifact_info(record),
                        "lifecycle": state.model_dump(mode="json"),
                    }
                )

        if remote_agents is not None:
            try:
                remote_records = await remote_agents.list()
            except RemoteAgentError:
                logger.exception("remote agent list failed: tenant=%s", target)
                return JSONResponse({"error": "remote_agent_store_unavailable"}, status_code=503)
            for remote_record in remote_records:
                if remote_record.tenant != target:
                    continue
                entries.append(
                    {
                        "tenant": remote_record.tenant,
                        "id": remote_record.remote_id,
                        "source": "remote",
                        "peer_id": remote_record.peer_id,
                        "label": remote_record.label,
                        "agent_card_url": remote_record.agent_card_url,
                        "enabled": remote_record.enabled,
                        "trust": {
                            "status": remote_record.status,
                            "card_digest": remote_record.card_digest,
                            "observed_digest": remote_record.observed_digest,
                            "checked_at": remote_record.checked_at.isoformat(),
                        },
                    }
                )

        entries.sort(
            key=lambda entry: (
                entry["id"],
                0 if entry["source"] == "local" else 1,
                entry.get("version") or "",
            )
        )
        return entries

    @app.post("/api/registry/load")
    async def load_registry_entry(request: Request) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "registry.load")
        if denied is not None:
            return denied
        if registry is None:
            return JSONResponse({"error": "registry_not_configured"}, status_code=404)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        tenant = body.get("tenant")
        agent_id = body.get("id")
        version = body.get("version")
        if not isinstance(tenant, str) or not tenant:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(agent_id, str) or not agent_id:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(version, str) or not version:
            return JSONResponse({"error": "invalid_request"}, status_code=400)

        if tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
        if artifact_trust is None:
            return JSONResponse({"error": "artifact_trust_unavailable"}, status_code=503)
        if artifact_store is None:
            return JSONResponse({"error": "artifact_store_unavailable"}, status_code=503)

        try:
            records = await registry.list(tenant)
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        except Exception:  # noqa: BLE001
            logger.exception("registry load failed: tenant=%s", tenant)
            return JSONResponse({"error": "load_failed"}, status_code=500)
        record = next(
            (
                item
                for item in records
                if item.manifest.id == agent_id and item.manifest.version == version
            ),
            None,
        )
        if record is None:
            return JSONResponse({"error": "not_found"}, status_code=404)
        try:
            state = await _lifecycle(record)
        except Exception:  # noqa: BLE001
            logger.exception("lifecycle read failed")
            return JSONResponse({"error": "lifecycle_unavailable"}, status_code=503)
        if state.status == "retired":
            return JSONResponse({"error": "version_retired"}, status_code=409)
        try:
            require_execution_supported(record.manifest)
        except AgentSandboxUnavailable:
            return JSONResponse({"error": "sandbox_unavailable"}, status_code=409)

        async with load_lock:
            if agent_id in agents:
                if agent_id in loaded_versions and loaded_versions[agent_id] != version:
                    return JSONResponse({"error": "name_conflict"}, status_code=409)
                return JSONResponse({"name": agent_id, "version": version, "loaded": False})
            if len(agents) >= max_loaded_agents:
                return JSONResponse({"error": "load_limit"}, status_code=409)
            artifact = record.artifact
            if artifact is None:
                return JSONResponse({"error": "artifact_missing"}, status_code=409)
            try:
                artifact_trust.verify(artifact)
            except ArtifactTrustError:
                return JSONResponse({"error": "artifact_untrusted"}, status_code=409)
            except PublishUnavailable:
                return JSONResponse({"error": "artifact_trust_unavailable"}, status_code=503)

            loader = artifact_loader or InProcessArtifactLoader()
            try:
                if record.manifest.execution_tier == "sandboxed":
                    agent = await load_sandbox_agent(record, store=artifact_store)
                else:
                    await verify_published_artifact(record, store=artifact_store)
                    agent = await loader.load(artifact, artifact_store)
            except SandboxToolsUnavailable:
                return JSONResponse({"error": "tool_mediation_unavailable"}, status_code=409)
            except ArtifactLoadError:
                logger.exception("artifact load failed: %s/%s@%s", tenant, agent_id, version)
                return JSONResponse({"error": "load_failed"}, status_code=500)

            _register(agent_id, agent, record.manifest)
            loaded_versions[agent_id] = version
            loaded_tenants[agent_id] = tenant
            await audit.emit(
                AuditEvent(
                    event_id=uuid.uuid4().hex,
                    run_id=uuid.uuid4().hex,
                    trace_id=_trace_id(request),
                    tenant=caller.tenant,
                    principal=caller,
                    agent_ref=AgentRef(id=agent_id, version=version, digest=record.digest),
                    action="agent.load",
                    target=agent_id,
                    status="ok",
                    timestamp=datetime.now(timezone.utc),
                )
            )
        return JSONResponse({"name": agent_id, "version": version, "loaded": True})

    @app.post("/api/registry/unload")
    async def unload_registry_entry(request: Request) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "registry.load")
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        name = body.get("name")
        if not isinstance(name, str) or not name:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        async with load_lock:
            if name not in agents:
                return JSONResponse({"error": "not_found"}, status_code=404)
            tenant = loaded_tenants.get(name)
            if tenant is None:
                return JSONResponse({"error": "not_unloadable"}, status_code=409)
            if tenant != caller.tenant and "admin" not in caller.roles:
                return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
            agents.pop(name, None)
            runners.pop(name, None)
            runtimes.pop(name, None)
            loaded_versions.pop(name, None)
            loaded_tenants.pop(name, None)
            await audit.emit(
                AuditEvent(
                    event_id=uuid.uuid4().hex,
                    run_id=uuid.uuid4().hex,
                    trace_id=_trace_id(request),
                    tenant=caller.tenant,
                    principal=caller,
                    agent_ref=dev_agent_ref(name),
                    action="agent.unload",
                    target=name,
                    status="ok",
                    timestamp=datetime.now(timezone.utc),
                )
            )
        return JSONResponse({"name": name, "unloaded": True})

    @app.get("/api/registry/{tenant}/{agent_id}/{version}/eval")
    async def get_eval_report(request: Request, tenant: str, agent_id: str, version: str) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "registry.read")
        if denied is not None:
            return denied
        if tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
        if eval_reports is None:
            return JSONResponse({"error": "registry_not_configured"}, status_code=404)
        try:
            report = await eval_reports.get(tenant, agent_id, version)
        except ValidationError:
            return JSONResponse({"error": "registry_corrupt"}, status_code=500)
        except ValueError:
            return JSONResponse({"error": "unsafe_tenant"}, status_code=400)
        if report is None:
            return JSONResponse({"error": "eval_report_not_found"}, status_code=404)
        return report.model_dump(mode="json")

    @app.get("/api/tools")
    async def list_tools(request: Request, tenant: str | None = None) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "tools.read")
        if denied is not None:
            return denied
        if tool_catalog is None and connectors is None:
            return JSONResponse({"error": "tool_catalog_not_configured"}, status_code=404)
        target = tenant or caller.tenant
        if tenant and tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
        grants: dict[str, set[tuple[str, str]]] = {}
        if registry is not None:
            try:
                records = await registry.list(target)
            except ValueError:
                return JSONResponse({"error": "unsafe_tenant"}, status_code=400)
            except Exception:  # noqa: BLE001
                logger.exception("tool catalog registry read failed")
                return JSONResponse({"error": "registry_corrupt"}, status_code=500)
            for record in records:
                for grant in record.manifest.tool_grants:
                    grants.setdefault(grant.tool_id, set()).add(
                        (record.manifest.id, record.manifest.version)
                    )

        def _view(tool: ToolEntry) -> dict[str, Any]:
            granted = sorted(grants.get(tool.tool_id, set()))
            return {
                "tool_id": tool.tool_id,
                "description": tool.description,
                "source": tool.source,
                "data_classes": list(tool.data_classes),
                "requires_approval": tool.requires_approval,
                "tenant": tool.tenant,
                "granted_agents": [
                    {"id": agent_id, "version": version} for agent_id, version in granted
                ],
            }

        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        if tool_catalog is not None:
            for tool in tool_catalog.tools:
                if tool.tenant is not None and tool.tenant != target:
                    continue
                seen.add(tool.tool_id)
                entries.append(_view(tool))
        if connectors is not None:
            try:
                specs = await connectors.list(target)
            except ConnectorStoreError:
                logger.exception("tool catalog connector read failed: tenant=%s", target)
                return JSONResponse({"error": "connector_store_unavailable"}, status_code=503)
            for tool in connector_tool_entries(specs):
                if tool.tool_id in seen:
                    continue
                seen.add(tool.tool_id)
                entries.append(_view(tool))
        entries.sort(key=lambda entry: entry["tool_id"])
        return entries

    @app.get("/api/tool-grants/usage")
    async def tool_grant_usage(request: Request, tenant: str | None = None) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "grants.read")
        if denied is not None:
            return denied
        if tenant and tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
        events = _visible_events(await _query_events(request), caller)
        counts: dict[str, dict[str, Any]] = {}
        for event in events:
            if event.action != "tool.call":
                continue
            row = counts.setdefault(
                event.target, {"tool_id": event.target, "allowed": 0, "denied": 0, "temporary": 0}
            )
            if event.status == "ok":
                row["allowed"] += 1
            elif event.status == "denied":
                row["denied"] += 1
            if event.policy_version == "grants-v2":
                row["temporary"] += 1
        return sorted(counts.values(), key=lambda row: row["tool_id"])

    @app.get("/api/connectors")
    async def list_connectors(request: Request, tenant: str | None = None) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "connectors.read")
        if denied is not None:
            return denied
        if connectors is None:
            return JSONResponse({"error": "connectors_not_configured"}, status_code=404)
        target = tenant or caller.tenant
        if tenant and tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
        try:
            records = await connectors.list(target)
        except ConnectorStoreError:
            logger.exception("connector list failed: tenant=%s", target)
            return JSONResponse({"error": "connector_store_unavailable"}, status_code=503)
        return [record.model_dump(mode="json") for record in records]

    @app.post("/api/connectors")
    async def register_connector(request: Request) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "connectors.manage")
        if denied is not None:
            return denied
        if connectors is None:
            return JSONResponse({"error": "connectors_not_configured"}, status_code=404)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        try:
            spec = ConnectorSpec.model_validate(body)
        except ValidationError:
            return JSONResponse({"error": "invalid_connector"}, status_code=400)
        if credentials is not None:
            try:
                bound = await credential_is_bound(credentials, spec)
            except CredentialStoreError:
                logger.exception("credential list failed: tenant=%s", spec.tenant)
                return JSONResponse({"error": "credential_store_unavailable"}, status_code=503)
            if not bound:
                return JSONResponse({"error": "credential_unbound"}, status_code=400)
        try:
            stored = await connectors.add(spec)
        except ConnectorConflict:
            return JSONResponse({"error": "connector_conflict"}, status_code=409)
        except ConnectorStoreUnavailable:
            logger.exception("connector register failed: id=%s", spec.connector_id)
            return JSONResponse({"error": "connector_store_unavailable"}, status_code=503)
        except ConnectorStoreError:
            logger.exception("connector register failed: id=%s", spec.connector_id)
            return JSONResponse({"error": "connector_store_unavailable"}, status_code=503)
        await audit.emit(
            AuditEvent(
                event_id=uuid.uuid4().hex,
                run_id=uuid.uuid4().hex,
                trace_id=uuid.uuid4().hex,
                tenant=caller.tenant,
                principal=caller,
                agent_ref=AgentRef(
                    id=spec.connector_id,
                    version="connector",
                    digest=f"sha256:{hash_text(spec.model_dump_json())}",
                ),
                action="connector.register",
                target=f"{spec.tenant or 'global'}/{spec.connector_id}",
                args_hash=hash_text(stored.model_dump_json()),
                status="ok",
                timestamp=datetime.now(timezone.utc),
            )
        )
        return JSONResponse(stored.model_dump(mode="json"), status_code=201)

    @app.post("/api/connectors/{connector_id}/disable")
    async def disable_connector(request: Request, connector_id: str) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "connectors.manage")
        if denied is not None:
            return denied
        if connectors is None:
            return JSONResponse({"error": "connectors_not_configured"}, status_code=404)
        try:
            existing = await connectors.get(connector_id)
        except ConnectorStoreError:
            logger.exception("connector read failed: id=%s", connector_id)
            return JSONResponse({"error": "connector_store_unavailable"}, status_code=503)
        if existing is None:
            return JSONResponse({"error": "connector_not_found"}, status_code=404)
        try:
            disabled = await connectors.disable(connector_id, by=caller.subject)
        except ConnectorStoreError:
            logger.exception("connector disable failed: id=%s", connector_id)
            return JSONResponse({"error": "connector_store_unavailable"}, status_code=503)
        if existing.enabled:
            await audit.emit(
                AuditEvent(
                    event_id=uuid.uuid4().hex,
                    run_id=uuid.uuid4().hex,
                    trace_id=uuid.uuid4().hex,
                    tenant=caller.tenant,
                    principal=caller,
                    agent_ref=AgentRef(
                        id=existing.connector_id,
                        version="connector",
                        digest=f"sha256:{hash_text(existing.model_dump_json())}",
                    ),
                    action="connector.disable",
                    target=f"{existing.tenant or 'global'}/{connector_id}",
                    args_hash=hash_text("enabled->disabled"),
                    status="ok",
                    timestamp=datetime.now(timezone.utc),
                )
            )
        return JSONResponse(disabled.model_dump(mode="json"))

    @app.post("/api/connectors/{connector_id}/check")
    async def check_connector_health(request: Request, connector_id: str) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "connectors.manage")
        if denied is not None:
            return denied
        if connectors is None:
            return JSONResponse({"error": "connectors_not_configured"}, status_code=404)
        try:
            spec = await connectors.get(connector_id)
        except ConnectorStoreError:
            logger.exception("connector read failed: id=%s", connector_id)
            return JSONResponse({"error": "connector_store_unavailable"}, status_code=503)
        if spec is None:
            return JSONResponse({"error": "connector_not_found"}, status_code=404)
        if spec.tenant is not None and spec.tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
        health = await check_connector(spec)
        return JSONResponse(health.model_dump(mode="json"))

    @app.get("/api/connector-requests")
    async def list_connector_requests(
        request: Request, tenant: str | None = None, status: str | None = None
    ) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "connectors.read")
        if denied is not None:
            return denied
        if connector_requests is None:
            return JSONResponse({"error": "connector_requests_not_configured"}, status_code=404)
        request_status: ConnectorRequestStatus | None = None
        if status is not None:
            if status not in _CONNECTOR_REQUEST_STATUSES:
                return JSONResponse({"error": "invalid_status"}, status_code=400)
            request_status = cast(ConnectorRequestStatus, status)
        target = tenant or caller.tenant
        if tenant and tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
        try:
            records = await connector_requests.list(target, status=request_status)
        except ConnectorRequestError:
            logger.exception("connector request list failed: tenant=%s", target)
            return JSONResponse({"error": "connector_request_store_unavailable"}, status_code=503)
        records.sort(key=lambda record: (record.requested_at, record.request_id), reverse=True)
        return [record.model_dump(mode="json") for record in records]

    @app.post("/api/connector-requests")
    async def create_connector_request(request: Request) -> Any:
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(body.get("spec"), dict):
            return JSONResponse({"error": "invalid_connector_request"}, status_code=400)
        reason = body.get("reason")
        if not isinstance(reason, str):
            return JSONResponse({"error": "invalid_connector_request"}, status_code=400)
        try:
            spec = ConnectorSpec.model_validate(body["spec"])
        except ValidationError:
            return JSONResponse({"error": "invalid_connector_request"}, status_code=400)

        caller = _principal_for(request)
        if spec.tenant is None or spec.tenant != caller.tenant:
            return JSONResponse({"error": "invalid_connector_request"}, status_code=400)
        if connector_requests is None:
            return JSONResponse({"error": "connector_requests_not_configured"}, status_code=404)
        try:
            record = ConnectorRequest(
                request_id=uuid.uuid4().hex,
                tenant=caller.tenant,
                spec=spec,
                reason=reason,
                requested_by=caller.subject,
                requested_at=datetime.now(timezone.utc),
            )
        except ValidationError:
            return JSONResponse({"error": "invalid_connector_request"}, status_code=400)
        try:
            created = await connector_requests.add(record)
        except ConnectorRequestError:
            logger.exception(
                "connector request add failed: tenant=%s connector=%s",
                caller.tenant,
                spec.connector_id,
            )
            return JSONResponse({"error": "connector_request_store_unavailable"}, status_code=503)

        await audit.emit(
            AuditEvent(
                event_id=uuid.uuid4().hex,
                run_id=uuid.uuid4().hex,
                trace_id=_trace_id(request),
                tenant=caller.tenant,
                principal=caller,
                agent_ref=AgentRef(
                    id=spec.connector_id,
                    version="connector",
                    digest=f"sha256:{hash_text(spec.model_dump_json())}",
                ),
                action="connector.request",
                target=f"{caller.tenant}/{spec.connector_id}",
                args_hash=hash_text(created.model_dump_json()),
                status="ok",
                timestamp=datetime.now(timezone.utc),
            )
        )
        return JSONResponse(created.model_dump(mode="json"), status_code=201)

    @app.post("/api/connector-requests/{request_id}/decide")
    async def decide_connector_request(request: Request, request_id: str) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "connectors.manage")
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(body, dict) or not isinstance(body.get("approved"), bool):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        reason = body.get("reason", "")
        if not isinstance(reason, str):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if connector_requests is None:
            return JSONResponse({"error": "connector_requests_not_configured"}, status_code=404)
        try:
            record = await connector_requests.get(request_id)
        except ConnectorRequestError:
            logger.exception("connector request read failed: %s", request_id)
            return JSONResponse({"error": "connector_request_store_unavailable"}, status_code=503)
        if record is None:
            return JSONResponse({"error": "connector_request_not_found"}, status_code=404)

        approved = body["approved"]
        registered: ConnectorSpec | None = None
        if approved:
            if record.status != "pending":
                return JSONResponse({"error": "connector_request_already_decided"}, status_code=409)
            if connectors is None:
                return JSONResponse({"error": "connectors_not_configured"}, status_code=404)
            if credentials is not None:
                try:
                    bound = await credential_is_bound(credentials, record.spec)
                except CredentialStoreError:
                    logger.exception("credential list failed: tenant=%s", record.spec.tenant)
                    return JSONResponse({"error": "credential_store_unavailable"}, status_code=503)
                if not bound:
                    return JSONResponse({"error": "credential_unbound"}, status_code=400)
            try:
                registered = await connectors.add(record.spec)
            except ConnectorConflict:
                return JSONResponse({"error": "connector_conflict"}, status_code=409)
            except ConnectorStoreError:
                logger.exception("connector register failed: id=%s", record.spec.connector_id)
                return JSONResponse({"error": "connector_store_unavailable"}, status_code=503)

        try:
            decided = await connector_requests.decide(
                request_id,
                approved=approved,
                decided_by=caller.subject,
                reason=reason,
                registered_connector=record.spec.connector_id if approved else None,
            )
        except ConnectorRequestNotFound:
            return JSONResponse({"error": "connector_request_not_found"}, status_code=404)
        except ConnectorRequestConflict:
            return JSONResponse({"error": "connector_request_already_decided"}, status_code=409)
        except ConnectorRequestError:
            logger.exception("connector request decide failed: %s", request_id)
            return JSONResponse({"error": "connector_request_store_unavailable"}, status_code=503)

        if registered is not None:
            await audit.emit(
                AuditEvent(
                    event_id=uuid.uuid4().hex,
                    run_id=uuid.uuid4().hex,
                    trace_id=_trace_id(request),
                    tenant=caller.tenant,
                    principal=caller,
                    agent_ref=AgentRef(
                        id=registered.connector_id,
                        version="connector",
                        digest=f"sha256:{hash_text(registered.model_dump_json())}",
                    ),
                    action="connector.register",
                    target=f"{registered.tenant or 'global'}/{registered.connector_id}",
                    args_hash=hash_text(registered.model_dump_json()),
                    status="ok",
                    timestamp=datetime.now(timezone.utc),
                )
            )
        await audit.emit(
            AuditEvent(
                event_id=uuid.uuid4().hex,
                run_id=uuid.uuid4().hex,
                trace_id=_trace_id(request),
                tenant=caller.tenant,
                principal=caller,
                agent_ref=AgentRef(
                    id=record.spec.connector_id,
                    version="connector",
                    digest=f"sha256:{hash_text(record.spec.model_dump_json())}",
                ),
                action="connector.request.decide",
                target=request_id,
                status="ok" if approved else "denied",
                timestamp=datetime.now(timezone.utc),
            )
        )
        return JSONResponse(decided.model_dump(mode="json"))

    @app.get("/api/credentials")
    async def list_credentials(request: Request, tenant: str | None = None) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "connectors.read")
        if denied is not None:
            return denied
        if credentials is None:
            return JSONResponse({"error": "credentials_not_configured"}, status_code=404)
        target = tenant or caller.tenant
        if tenant and tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
        if tenant is not None and not _SAFE_TENANT.fullmatch(tenant):
            return JSONResponse({"error": "unsafe_tenant"}, status_code=400)
        try:
            records = await credentials.list(target)
        except CredentialStoreError:
            logger.exception("credential list failed: tenant=%s", target)
            return JSONResponse({"error": "credential_store_unavailable"}, status_code=503)
        return [record.model_dump(mode="json", exclude={"wrapped_secret"}) for record in records]

    @app.post("/api/credentials")
    async def register_credential(request: Request) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "connectors.manage")
        if denied is not None:
            return denied
        if credentials is None:
            return JSONResponse({"error": "credentials_not_configured"}, status_code=404)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if any(key in body for key in ("wrapped_secret", "secret_key_id", "secret_version")):
            return JSONResponse({"error": "invalid_credential"}, status_code=400)
        body["created_by"] = caller.subject
        body["created_at"] = datetime.now(timezone.utc)
        try:
            binding = CredentialBinding.model_validate(body)
        except ValidationError:
            return JSONResponse({"error": "invalid_credential"}, status_code=400)
        try:
            stored = await credentials.add(binding)
        except CredentialConflict:
            return JSONResponse({"error": "credential_conflict"}, status_code=409)
        except CredentialStoreUnavailable:
            logger.exception(
                "credential register failed: id=%s/%s",
                binding.tenant,
                binding.credential_id,
            )
            return JSONResponse({"error": "credential_store_unavailable"}, status_code=503)
        except CredentialStoreError:
            logger.exception(
                "credential register failed: id=%s/%s",
                binding.tenant,
                binding.credential_id,
            )
            return JSONResponse({"error": "credential_store_unavailable"}, status_code=503)
        await audit.emit(
            AuditEvent(
                event_id=uuid.uuid4().hex,
                run_id=uuid.uuid4().hex,
                trace_id=uuid.uuid4().hex,
                tenant=caller.tenant,
                principal=caller,
                agent_ref=AgentRef(
                    id=binding.credential_id,
                    version="credential",
                    digest=f"sha256:{hash_text(binding.model_dump_json())}",
                ),
                action="credential.register",
                target=f"{binding.tenant}/{binding.credential_id}",
                args_hash=hash_text(stored.model_dump_json()),
                status="ok",
                timestamp=datetime.now(timezone.utc),
            )
        )
        return JSONResponse(
            stored.model_dump(mode="json", exclude={"wrapped_secret"}), status_code=201
        )

    @app.post("/api/credentials/{credential_id}/disable")
    async def disable_credential(
        request: Request, credential_id: str, tenant: str | None = None
    ) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "connectors.manage")
        if denied is not None:
            return denied
        if credentials is None:
            return JSONResponse({"error": "credentials_not_configured"}, status_code=404)
        target = tenant or caller.tenant
        try:
            existing = await credentials.get(target, credential_id)
        except CredentialStoreError:
            logger.exception("credential read failed: id=%s/%s", target, credential_id)
            return JSONResponse({"error": "credential_store_unavailable"}, status_code=503)
        if existing is None:
            return JSONResponse({"error": "credential_not_found"}, status_code=404)
        try:
            disabled = await credentials.disable(target, credential_id, by=caller.subject)
        except CredentialNotFound:
            return JSONResponse({"error": "credential_not_found"}, status_code=404)
        except CredentialStoreError:
            logger.exception("credential disable failed: id=%s/%s", target, credential_id)
            return JSONResponse({"error": "credential_store_unavailable"}, status_code=503)
        if existing.enabled:
            await audit.emit(
                AuditEvent(
                    event_id=uuid.uuid4().hex,
                    run_id=uuid.uuid4().hex,
                    trace_id=uuid.uuid4().hex,
                    tenant=caller.tenant,
                    principal=caller,
                    agent_ref=AgentRef(
                        id=existing.credential_id,
                        version="credential",
                        digest=f"sha256:{hash_text(existing.model_dump_json())}",
                    ),
                    action="credential.disable",
                    target=f"{existing.tenant}/{credential_id}",
                    args_hash=hash_text("enabled->disabled"),
                    status="ok",
                    timestamp=datetime.now(timezone.utc),
                )
            )
        return JSONResponse(disabled.model_dump(mode="json", exclude={"wrapped_secret"}))

    @app.get("/api/peers")
    async def list_peers(request: Request, tenant: str | None = None) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "peers.read")
        if denied is not None:
            return denied
        if peers is None or peer_grants is None:
            return JSONResponse({"error": "peers_not_configured"}, status_code=404)
        if tenant is not None and tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
        try:
            identities = await peers.list()
            grants = await peer_grants.list()
        except PeerStoreError:
            logger.exception("peer list failed: tenant=%s", caller.tenant)
            return JSONResponse({"error": "peer_store_unavailable"}, status_code=503)
        if "admin" in caller.roles:
            if tenant is not None:
                identities = [identity for identity in identities if identity.tenant == tenant]
        else:
            identities = [identity for identity in identities if identity.tenant == caller.tenant]
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

    @app.post("/api/peers")
    async def register_peer(request: Request) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "peers.manage")
        if denied is not None:
            return denied
        if peers is None or peer_grants is None:
            return JSONResponse({"error": "peers_not_configured"}, status_code=404)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        try:
            identity = PeerIdentity.model_validate(body)
        except ValidationError:
            return JSONResponse({"error": "invalid_peer"}, status_code=400)
        try:
            existing = await peers.get(identity.peer_id)
        except ValueError:
            return JSONResponse({"error": "invalid_peer"}, status_code=400)
        except PeerStoreError:
            logger.exception("peer read failed: id=%s", identity.peer_id)
            return JSONResponse({"error": "peer_store_unavailable"}, status_code=503)
        if existing is not None and existing.tenant != identity.tenant:
            return JSONResponse({"error": "peer_tenant_immutable"}, status_code=409)
        try:
            stored = await peers.put(identity)
        except PeerStoreError:
            logger.exception("peer register failed: id=%s", identity.peer_id)
            return JSONResponse({"error": "peer_store_unavailable"}, status_code=503)
        await _emit_peer(
            "peer.register",
            target=stored.peer_id,
            caller=caller,
            identity=stored,
            args_hash=hash_text(stored.model_dump_json()),
        )
        return JSONResponse(stored.model_dump(mode="json"))

    @app.post("/api/peers/{peer_id}/disable")
    async def disable_peer(request: Request, peer_id: str) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "peers.manage")
        if denied is not None:
            return denied
        if peers is None or peer_grants is None:
            return JSONResponse({"error": "peers_not_configured"}, status_code=404)
        try:
            existing = await peers.get(peer_id)
        except ValueError:
            return JSONResponse({"error": "peer_not_found"}, status_code=404)
        except PeerStoreError:
            logger.exception("peer read failed: id=%s", peer_id)
            return JSONResponse({"error": "peer_store_unavailable"}, status_code=503)
        if existing is None:
            return JSONResponse({"error": "peer_not_found"}, status_code=404)
        if existing.tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
        try:
            stored = await peers.put(existing.model_copy(update={"enabled": False}))
        except PeerStoreError:
            logger.exception("peer disable failed: id=%s", peer_id)
            return JSONResponse({"error": "peer_store_unavailable"}, status_code=503)
        if existing.enabled:
            await _emit_peer(
                "peer.disable",
                target=stored.peer_id,
                caller=caller,
                identity=existing,
                args_hash=hash_text("enabled->disabled"),
            )
        return JSONResponse(stored.model_dump(mode="json"))

    @app.post("/api/peers/{peer_id}/grants")
    async def put_peer_grant(request: Request, peer_id: str) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "peers.manage")
        if denied is not None:
            return denied
        if peers is None or peer_grants is None:
            return JSONResponse({"error": "peers_not_configured"}, status_code=404)
        try:
            peer = await peers.get(peer_id)
        except ValueError:
            return JSONResponse({"error": "peer_not_found"}, status_code=404)
        except PeerStoreError:
            logger.exception("peer read failed: id=%s", peer_id)
            return JSONResponse({"error": "peer_store_unavailable"}, status_code=503)
        if peer is None:
            return JSONResponse({"error": "peer_not_found"}, status_code=404)
        if peer.tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        agent_id = body.get("agent_id")
        actions = body.get("actions")
        if (
            not isinstance(agent_id, str)
            or not agent_id
            or not isinstance(actions, list)
            or not actions
            or not all(isinstance(action, str) for action in actions)
            or any(action not in {"read", "invoke"} for action in actions)
        ):
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        try:
            grant = PeerGrant(
                peer_id=peer.peer_id,
                tenant=peer.tenant,
                agent_id=agent_id,
                actions=actions,
            )
        except ValidationError:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        try:
            stored = await peer_grants.put(grant)
        except PeerStoreError:
            logger.exception("peer grant write failed: peer=%s agent=%s", peer_id, agent_id)
            return JSONResponse({"error": "peer_store_unavailable"}, status_code=503)
        await _emit_peer(
            "peer.grant",
            target=f"{stored.peer_id}/{stored.agent_id}",
            caller=caller,
            identity=peer,
            args_hash=hash_text(stored.model_dump_json()),
        )
        return JSONResponse(stored.model_dump(mode="json"))

    @app.delete("/api/peers/{peer_id}/grants/{agent_id}")
    async def revoke_peer_grant(request: Request, peer_id: str, agent_id: str) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "peers.manage")
        if denied is not None:
            return denied
        if peers is None or peer_grants is None:
            return JSONResponse({"error": "peers_not_configured"}, status_code=404)
        try:
            peer = await peers.get(peer_id)
        except ValueError:
            return JSONResponse({"error": "peer_not_found"}, status_code=404)
        except PeerStoreError:
            logger.exception("peer read failed: id=%s", peer_id)
            return JSONResponse({"error": "peer_store_unavailable"}, status_code=503)
        if peer is None:
            return JSONResponse({"error": "peer_not_found"}, status_code=404)
        if peer.tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
        try:
            revoked = await peer_grants.delete(peer_id, agent_id)
        except ValueError:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        except PeerStoreError:
            logger.exception("peer grant delete failed: peer=%s agent=%s", peer_id, agent_id)
            return JSONResponse({"error": "peer_store_unavailable"}, status_code=503)
        if revoked:
            await _emit_peer(
                "peer.revoke",
                target=f"{peer_id}/{agent_id}",
                caller=caller,
                identity=peer,
                args_hash=hash_text(agent_id),
            )
        return JSONResponse({"revoked": revoked})

    @app.get("/api/remote-agents")
    async def list_remote_agents(request: Request, tenant: str | None = None) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "peers.read")
        if denied is not None:
            return denied
        if remote_agents is None:
            return JSONResponse({"error": "remote_agents_not_configured"}, status_code=404)
        if tenant is not None and tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
        try:
            records = await remote_agents.list()
        except RemoteAgentError:
            logger.exception("remote agent list failed: tenant=%s", caller.tenant)
            return JSONResponse({"error": "remote_agent_store_unavailable"}, status_code=503)
        if "admin" in caller.roles:
            if tenant is not None:
                records = [record for record in records if record.tenant == tenant]
        else:
            records = [record for record in records if record.tenant == caller.tenant]
        records.sort(key=lambda record: record.remote_id)
        return [record.model_dump(mode="json") for record in records]

    @app.post("/api/remote-agents")
    async def register_remote_agent(request: Request) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "peers.manage")
        if denied is not None:
            return denied
        if remote_agents is None or peers is None:
            return JSONResponse({"error": "remote_agents_not_configured"}, status_code=404)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        try:
            registration = RemoteAgentRegistration.model_validate(body)
        except ValidationError:
            return JSONResponse({"error": "invalid_remote_agent"}, status_code=400)
        try:
            peer = await peers.get(registration.peer_id)
        except ValueError:
            return JSONResponse({"error": "peer_not_found"}, status_code=404)
        except PeerStoreError:
            logger.exception("peer read failed: id=%s", registration.peer_id)
            return JSONResponse({"error": "peer_store_unavailable"}, status_code=503)
        if peer is None or not peer.enabled:
            return JSONResponse({"error": "peer_not_found"}, status_code=404)
        if peer.tenant != registration.tenant:
            return JSONResponse({"error": "tenant_mismatch"}, status_code=400)
        try:
            existing = await remote_agents.get(registration.remote_id)
        except ValueError:
            return JSONResponse({"error": "invalid_remote_agent"}, status_code=400)
        except RemoteAgentError:
            logger.exception("remote agent read failed: id=%s", registration.remote_id)
            return JSONResponse({"error": "remote_agent_store_unavailable"}, status_code=503)
        if existing is not None and existing.tenant != registration.tenant:
            return JSONResponse({"error": "remote_agent_tenant_immutable"}, status_code=409)
        credential = None
        if registration.credential_ref is not None:
            try:
                credential = await TenantScopedSecretProvider(secrets, registration.tenant).resolve(
                    registration.credential_ref
                )
            except SecretNotFound:
                return JSONResponse({"error": "secret_unavailable"}, status_code=503)
        try:
            digest, card = await fetch_agent_card(registration.agent_card_url, credential)
        except RemoteAgentFetchError as exc:
            code = {
                "unreachable": "card_unreachable",
                "unauthorized": "card_unauthorized",
                "too_large": "card_too_large",
                "invalid_card": "card_invalid",
            }[exc.reason]
            return JSONResponse({"error": code}, status_code=502)
        if card.get("name") != registration.remote_id:
            return JSONResponse({"error": "card_name_mismatch"}, status_code=400)
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
        try:
            stored = await remote_agents.put(record)
        except RemoteAgentError:
            logger.exception("remote agent register failed: id=%s", registration.remote_id)
            return JSONResponse({"error": "remote_agent_store_unavailable"}, status_code=503)
        await _emit_remote(
            "remote_agent.register",
            target=stored.remote_id,
            caller=caller,
            record=stored,
            args_hash=hash_text(stored.model_dump_json()),
        )
        return JSONResponse(stored.model_dump(mode="json"))

    @app.post("/api/remote-agents/{remote_id}/refresh")
    async def refresh_remote_agent(request: Request, remote_id: str) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "peers.manage")
        if denied is not None:
            return denied
        if remote_agents is None:
            return JSONResponse({"error": "remote_agents_not_configured"}, status_code=404)
        try:
            existing = await remote_agents.get(remote_id)
        except ValueError:
            return JSONResponse({"error": "remote_agent_not_found"}, status_code=404)
        except RemoteAgentError:
            logger.exception("remote agent read failed: id=%s", remote_id)
            return JSONResponse({"error": "remote_agent_store_unavailable"}, status_code=503)
        if existing is None:
            return JSONResponse({"error": "remote_agent_not_found"}, status_code=404)
        if existing.tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
        digest: str | None = None
        try:
            credential = (
                await TenantScopedSecretProvider(secrets, existing.tenant).resolve(
                    existing.credential_ref
                )
                if existing.credential_ref is not None
                else None
            )
            digest, _card = await fetch_agent_card(existing.agent_card_url, credential)
        except (SecretNotFound, RemoteAgentFetchError):
            digest = None
        checked_at = datetime.now(timezone.utc)
        if digest == existing.card_digest:
            record = existing.model_copy(
                update={"checked_at": checked_at, "status": "pinned", "observed_digest": None}
            )
        elif digest is not None:
            record = existing.model_copy(
                update={"checked_at": checked_at, "status": "changed", "observed_digest": digest}
            )
        else:
            record = existing.model_copy(update={"checked_at": checked_at, "status": "unreachable"})
        try:
            stored = await remote_agents.put(record)
        except RemoteAgentError:
            logger.exception("remote agent refresh failed: id=%s", remote_id)
            return JSONResponse({"error": "remote_agent_store_unavailable"}, status_code=503)
        await _emit_remote(
            "remote_agent.refresh",
            target=stored.remote_id,
            caller=caller,
            record=stored,
            args_hash=hash_text(stored.model_dump_json()),
        )
        return JSONResponse(stored.model_dump(mode="json"))

    @app.post("/api/remote-agents/{remote_id}/disable")
    async def disable_remote_agent(request: Request, remote_id: str) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "peers.manage")
        if denied is not None:
            return denied
        if remote_agents is None:
            return JSONResponse({"error": "remote_agents_not_configured"}, status_code=404)
        try:
            existing = await remote_agents.get(remote_id)
        except ValueError:
            return JSONResponse({"error": "remote_agent_not_found"}, status_code=404)
        except RemoteAgentError:
            logger.exception("remote agent read failed: id=%s", remote_id)
            return JSONResponse({"error": "remote_agent_store_unavailable"}, status_code=503)
        if existing is None:
            return JSONResponse({"error": "remote_agent_not_found"}, status_code=404)
        if existing.tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
        if existing.enabled:
            try:
                stored = await remote_agents.put(existing.model_copy(update={"enabled": False}))
            except RemoteAgentError:
                logger.exception("remote agent disable failed: id=%s", remote_id)
                return JSONResponse({"error": "remote_agent_store_unavailable"}, status_code=503)
            await _emit_remote(
                "remote_agent.disable",
                target=stored.remote_id,
                caller=caller,
                record=existing,
                args_hash=hash_text("enabled->disabled"),
            )
        else:
            stored = existing
        return JSONResponse(stored.model_dump(mode="json"))

    @app.get("/api/tool-grants")
    async def list_tool_grants(
        request: Request, tenant: str | None = None, status: str | None = None
    ) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "grants.read")
        if denied is not None:
            return denied
        if tool_grants is None:
            return JSONResponse({"error": "tool_grants_not_configured"}, status_code=404)
        grant_status: GrantStatus | None = None
        if status is not None:
            if status not in _GRANT_STATUSES:
                return JSONResponse({"error": "invalid_status"}, status_code=400)
            grant_status = cast(GrantStatus, status)
        target = tenant or caller.tenant
        if tenant and tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
        try:
            records = await tool_grants.list(target, status=grant_status)
        except GrantStoreError:
            logger.exception("tool grant list failed: tenant=%s", target)
            return JSONResponse({"error": "grant_store_unavailable"}, status_code=503)
        records.sort(key=lambda record: (record.requested_at, record.request_id), reverse=True)
        return [record.model_dump(mode="json") for record in records]

    @app.post("/api/tool-grants")
    async def create_tool_grant(request: Request) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "grants.request")
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_request"}, status_code=400)

        agent_id = body.get("agent_id")
        version = body.get("version")
        digest = body.get("digest")
        tool_id = body.get("tool_id")
        reason = body.get("reason")
        if (
            not isinstance(agent_id, str)
            or not agent_id
            or not isinstance(version, str)
            or not version
            or not isinstance(digest, str)
            or not digest
            or not isinstance(tool_id, str)
            or not tool_id
            or not isinstance(reason, str)
            or not reason
        ):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not _SAFE_NAME.fullmatch(agent_id) or not _SAFE_NAME.fullmatch(version):
            return JSONResponse({"error": "invalid_request"}, status_code=400)

        tenant = body.get("tenant")
        if tenant is not None and (not isinstance(tenant, str) or not _SAFE_NAME.fullmatch(tenant)):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        data_classes = body.get("data_classes", [])
        if not isinstance(data_classes, list) or not all(
            isinstance(item, str) for item in data_classes
        ):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        expires_hours = body.get("expires_hours", 24)
        if (
            isinstance(expires_hours, bool)
            or not isinstance(expires_hours, int)
            or not 1 <= expires_hours <= 168
        ):
            return JSONResponse({"error": "invalid_request"}, status_code=400)

        if tool_grants is None:
            return JSONResponse({"error": "tool_grants_not_configured"}, status_code=404)
        target = tenant or caller.tenant
        if target != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)

        record = None
        if registry is not None:
            try:
                records = await registry.list(target)
            except ValueError:
                return JSONResponse({"error": "invalid_request"}, status_code=400)
            except Exception:  # noqa: BLE001
                logger.exception("tool grant registry read failed")
                return JSONResponse({"error": "registry_corrupt"}, status_code=500)
            record = next(
                (
                    item
                    for item in records
                    if item.manifest.id == agent_id and item.manifest.version == version
                ),
                None,
            )
        if record is None or record.digest != digest:
            return JSONResponse({"error": "not_found"}, status_code=404)

        try:
            state = await _lifecycle(record)
        except Exception:  # noqa: BLE001
            logger.exception("lifecycle read failed")
            return JSONResponse({"error": "lifecycle_unavailable"}, status_code=503)
        if state.status == "retired":
            return JSONResponse({"error": "version_retired"}, status_code=409)

        now = datetime.now(timezone.utc)
        try:
            grant = ToolGrantRequest(
                request_id=uuid.uuid4().hex,
                tenant=target,
                agent_id=agent_id,
                version=version,
                digest=record.digest,
                tool_id=tool_id,
                data_classes=data_classes,
                reason=reason,
                requested_by=caller.subject,
                requested_at=now,
                expires_at=now + timedelta(hours=expires_hours),
            )
        except ValidationError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        try:
            created = await tool_grants.add(grant)
        except GrantStoreError:
            logger.exception("tool grant add failed: tenant=%s", target)
            return JSONResponse({"error": "grant_store_unavailable"}, status_code=503)

        await audit.emit(
            AuditEvent(
                event_id=uuid.uuid4().hex,
                run_id=uuid.uuid4().hex,
                trace_id=_trace_id(request),
                tenant=caller.tenant,
                principal=caller,
                agent_ref=AgentRef(id=agent_id, version=version, digest=record.digest),
                action="tool_grant.request",
                target=f"{agent_id}@{version}:{tool_id}",
                status="ok",
                timestamp=datetime.now(timezone.utc),
            )
        )
        return JSONResponse(created.model_dump(mode="json"), status_code=201)

    @app.post("/api/tool-grants/{request_id}/decide")
    async def decide_tool_grant(request: Request, request_id: str) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "grants.decide")
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(body, dict) or not isinstance(body.get("approved"), bool):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        reason = body.get("reason", "")
        if not isinstance(reason, str):
            return JSONResponse({"error": "invalid_request"}, status_code=400)

        if tool_grants is None:
            return JSONResponse({"error": "tool_grants_not_configured"}, status_code=404)
        try:
            decided = await tool_grants.decide(
                request_id,
                approved=body["approved"],
                decided_by=caller.subject,
                reason=reason,
            )
        except GrantRequestNotFound:
            return JSONResponse({"error": "grant_not_found"}, status_code=404)
        except GrantRequestConflict:
            return JSONResponse({"error": "grant_already_decided"}, status_code=409)
        except GrantRequestExpired:
            return JSONResponse({"error": "grant_expired"}, status_code=410)
        except GrantStoreError:
            logger.exception("tool grant decide failed: %s", request_id)
            return JSONResponse({"error": "grant_store_unavailable"}, status_code=503)

        await audit.emit(
            AuditEvent(
                event_id=uuid.uuid4().hex,
                run_id=uuid.uuid4().hex,
                trace_id=_trace_id(request),
                tenant=caller.tenant,
                principal=caller,
                agent_ref=AgentRef(
                    id=decided.agent_id, version=decided.version, digest=decided.digest
                ),
                action="tool_grant.decide",
                target=request_id,
                status="ok" if decided.status == "approved" else "denied",
                timestamp=datetime.now(timezone.utc),
            )
        )
        return JSONResponse(decided.model_dump(mode="json"))

    @app.get("/api/runs")
    async def list_runs(request: Request, limit: int = 50) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "runs.read")
        if denied is not None:
            return denied
        events = _visible_events(await _query_events(request), caller)
        return _summarize_runs(events, limit)

    @app.get("/api/approvals")
    async def list_approvals(request: Request) -> Any:
        caller = _principal_for(request)
        if "approvals.read" not in await _caps_for(caller):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        if approvals is None:
            return JSONResponse({"error": "approvals_not_configured"}, status_code=404)
        try:
            pending = approvals.pending()
            if inspect.isawaitable(pending):
                pending = await pending
        except ApprovalInboxUnavailable:
            return JSONResponse({"error": "approval_unavailable"}, status_code=503)
        if "admin" not in caller.roles:
            pending = [item for item in pending if item.principal.tenant == caller.tenant]
        payload = []
        for item in pending:
            deadline = approvals.expires_at(item) if hasattr(approvals, "expires_at") else None
            if deadline is not None and deadline != item.expires_at:
                item = item.model_copy(update={"expires_at": deadline})
            payload.append(item.model_dump(mode="json"))
        return payload

    @app.post("/api/approvals/{request_id}")
    async def decide_approval(request: Request, request_id: str) -> Any:
        caller = _principal_for(request)
        if "approvals.decide" not in await _caps_for(caller):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        if approvals is None:
            return JSONResponse({"error": "approvals_not_configured"}, status_code=404)
        if not _TRACE_ID.fullmatch(request_id):
            return JSONResponse({"error": "unsafe_request_id"}, status_code=400)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid json"}, status_code=400)
        if not isinstance(body, dict) or not isinstance(body.get("approved"), bool):
            return JSONResponse({"error": "invalid decision"}, status_code=400)
        reason = body.get("reason", "")
        if not isinstance(reason, str):
            return JSONResponse({"error": "invalid decision"}, status_code=400)

        try:
            record = approvals.get(request_id)
            if inspect.isawaitable(record):
                record = await record
        except ApprovalInboxUnavailable:
            return JSONResponse({"error": "approval_unavailable"}, status_code=503)
        if record is None:
            return JSONResponse({"error": "approval_not_found"}, status_code=404)
        stored = record.request
        if stored.principal.tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)

        if policy_engine is not None:
            invocation = Invocation(
                run_id=stored.run_id,
                trace_id=stored.trace_id,
                principal=caller,
                agent_ref=stored.agent_ref,
                input="",
            )
            policy = await policy_engine.decide(invocation, "approval.decide", stored.agent_ref.id)
            if policy.decision != "allow":
                await audit.emit(
                    AuditEvent(
                        event_id=uuid.uuid4().hex,
                        run_id=stored.run_id,
                        trace_id=stored.trace_id,
                        tenant=caller.tenant,
                        principal=caller,
                        approver=caller.subject,
                        agent_ref=stored.agent_ref,
                        action="approval.decide",
                        target=request_id,
                        status="denied",
                        error_code="policy_denied",
                        timestamp=datetime.now(timezone.utc),
                    )
                )
                return JSONResponse({"error": "policy_denied"}, status_code=403)

        try:
            decision = approvals.decide(
                request_id,
                approved=body["approved"],
                approver=caller.subject,
                reason=reason,
            )
            if inspect.isawaitable(decision):
                decision = await decision
        except ApprovalConflict:
            return JSONResponse({"error": "approval_already_decided"}, status_code=409)
        except ApprovalExpired:
            return JSONResponse({"error": "approval_expired"}, status_code=410)
        except ApprovalNotFound:
            return JSONResponse({"error": "approval_not_found"}, status_code=404)
        except ApprovalInboxUnavailable:
            return JSONResponse({"error": "approval_unavailable"}, status_code=503)

        await audit.emit(
            AuditEvent(
                event_id=uuid.uuid4().hex,
                run_id=stored.run_id,
                trace_id=stored.trace_id,
                tenant=caller.tenant,
                principal=caller,
                approver=caller.subject,
                agent_ref=stored.agent_ref,
                action="approval.decide",
                target=request_id,
                status="ok" if decision.approved else "denied",
                timestamp=datetime.now(timezone.utc),
            )
        )
        return JSONResponse(decision.model_dump(mode="json"))

    @app.get("/api/approvals/history")
    async def approval_history(request: Request, limit: int = 50, status: str | None = None) -> Any:
        caller = _principal_for(request)
        if "approvals.read" not in await _caps_for(caller):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        if approvals is None:
            return JSONResponse({"error": "approvals_not_configured"}, status_code=404)
        if status is not None and status not in HISTORY_STATUSES:
            return JSONResponse({"error": "invalid_status"}, status_code=400)
        limit = max(1, min(200, limit))
        tenant = None if "admin" in caller.roles else caller.tenant
        try:
            entries = approvals.history(tenant=tenant, status=status, limit=limit)
            if inspect.isawaitable(entries):
                entries = await entries
        except ApprovalInboxUnavailable:
            return JSONResponse({"error": "approval_unavailable"}, status_code=503)
        return [
            {
                "request": entry.request.model_dump(mode="json"),
                "decision": (
                    entry.decision.model_dump(mode="json") if entry.decision is not None else None
                ),
                "status": entry.status,
                "archived": entry.archived,
                "terminal_at": entry.terminal_at.isoformat().replace("+00:00", "Z"),
            }
            for entry in entries
        ]

    @app.get("/api/plans")
    async def list_plans(request: Request, limit: int = 50) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "runs.read")
        if denied is not None:
            return denied
        events = _visible_events(await _query_events(request), caller)
        return _summarize_plans(events, limit)

    @app.get("/api/sessions")
    async def list_sessions(request: Request, agent: str | None = None) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "sessions.read")
        if denied is not None:
            return denied
        if agent not in agents:
            return JSONResponse({"error": "unknown_agent"}, status_code=400)
        with session_tenant(caller.tenant):
            listed = await service.list_sessions(app_name=agent, user_id=_session_user(caller))
        sessions = sorted(
            listed.sessions, key=lambda session: session.last_update_time, reverse=True
        )
        return [
            {
                "session_id": session.id,
                "last_update_time": datetime.fromtimestamp(
                    session.last_update_time, tz=timezone.utc
                ).isoformat(),
            }
            for session in sessions
        ]

    if policy_store is not None and policy_engine is not None:

        @app.get("/api/policy")
        async def get_policy(request: Request) -> Any:
            caller = _principal_for(request)
            denied = await _forbidden_if_missing(caller, "policy.read")
            if denied is not None:
                return denied
            return policy_engine.policy.model_dump(mode="json")

        @app.put("/api/policy")
        async def put_policy(request: Request) -> JSONResponse:
            try:
                body = await request.json()
            except ValueError:
                return JSONResponse({"error": "invalid json"}, status_code=400)
            try:
                policy = AccessPolicy.model_validate(body)
            except ValidationError:
                return JSONResponse({"error": "invalid policy"}, status_code=400)

            caller = _principal_for(request)
            invocation = Invocation(
                run_id=uuid.uuid4().hex,
                trace_id=_trace_id(request),
                principal=caller,
                agent_ref=dev_agent_ref("policy"),
                input=policy.version,
            )
            decision = await policy_engine.decide(invocation, "policy.update", policy.version)
            if decision.decision != "allow":
                await audit.emit(
                    AuditEvent(
                        event_id=uuid.uuid4().hex,
                        run_id=invocation.run_id,
                        trace_id=invocation.trace_id,
                        tenant=caller.tenant,
                        principal=caller,
                        agent_ref=invocation.agent_ref,
                        action="policy.update",
                        target=policy.version,
                        status="denied",
                        error_code="policy_denied",
                        timestamp=datetime.now(timezone.utc),
                    )
                )
                return JSONResponse({"error": "policy_denied"}, status_code=403)

            policy_store.save(policy)
            policy_engine.update(policy)
            await audit.emit(
                AuditEvent(
                    event_id=uuid.uuid4().hex,
                    run_id=uuid.uuid4().hex,
                    trace_id=_trace_id(request),
                    tenant=caller.tenant,
                    principal=caller,
                    agent_ref=dev_agent_ref("policy"),
                    action="policy.update",
                    target=policy.version,
                    status="ok",
                    timestamp=datetime.now(timezone.utc),
                )
            )
            return JSONResponse(policy.model_dump(mode="json"))

    @app.post("/api/chat")
    async def chat(request: Request) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "chat.run")
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid json"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "expected a json object"}, status_code=400)

        name = body.get("agent")
        if not isinstance(name, str):
            return JSONResponse({"error": "unknown agent"}, status_code=400)
        message = str(body.get("message") or "").strip()
        if not message:
            return JSONResponse({"error": "message is required"}, status_code=400)
        runtime = runtimes.get(name)
        if runtime is None:
            return JSONResponse({"error": "unknown agent"}, status_code=400)

        with session_tenant(caller.tenant):
            session_id = await _session_id_for(
                service, name, body.get("session_id"), _session_user(caller)
            )

        invocation = Invocation(
            run_id=uuid.uuid4().hex,
            trace_id=_trace_id(request),
            principal=caller,
            agent_ref=dev_agent_ref(name),
            input=message,
        )
        if not await allowed(invocation, name):
            return JSONResponse({"error": "policy_denied"}, status_code=403)
        quota_policy = quota_config.tenants.get(caller.tenant) if quota_config else None
        try:
            with session_tenant(caller.tenant):
                result = await runtime.run(
                    invocation,
                    user_id=_session_user(caller),
                    session_id=session_id,
                    quota=quota,
                    quota_policy=quota_policy,
                )
        except QuotaExceeded:
            return JSONResponse({"error": "quota_exceeded"}, status_code=429)
        except QuotaStoreUnavailable:
            logger.exception("quota store unavailable: agent=%s run=%s", name, invocation.run_id)
            return JSONResponse({"error": "quota_unavailable"}, status_code=503)
        except Exception:  # noqa: BLE001
            logger.exception(
                "agent run failed: agent=%s session=%s run=%s",
                name,
                session_id,
                invocation.run_id,
            )
            return JSONResponse({"error": "agent run failed"}, status_code=500)

        return JSONResponse(
            {
                "session_id": session_id,
                "reply": result.text,
                "run_id": result.run_id,
                "trace_id": result.trace_id,
            }
        )

    @app.post("/api/chat/stream")
    async def chat_stream(request: Request) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "chat.run")
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid json"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "expected a json object"}, status_code=400)

        name = body.get("agent")
        if not isinstance(name, str):
            return JSONResponse({"error": "unknown agent"}, status_code=400)
        message = str(body.get("message") or "").strip()
        if not message:
            return JSONResponse({"error": "message is required"}, status_code=400)
        runtime = runtimes.get(name)
        if runtime is None:
            return JSONResponse({"error": "unknown agent"}, status_code=400)

        with session_tenant(caller.tenant):
            session_id = await _session_id_for(
                service, name, body.get("session_id"), _session_user(caller)
            )
        invocation = Invocation(
            run_id=uuid.uuid4().hex,
            trace_id=_trace_id(request),
            principal=caller,
            agent_ref=dev_agent_ref(name),
            input=message,
        )
        if not await allowed(invocation, name):
            return JSONResponse({"error": "policy_denied"}, status_code=403)
        quota_policy = quota_config.tenants.get(caller.tenant) if quota_config else None

        async def events():
            buffer = ProgressBuffer(sse_queue_size)

            async def on_progress(event: ProgressEvent) -> None:
                buffer.put_progress(event.model_dump(mode="json"))
                # Let the response generator drain before the run emits again.
                await asyncio.sleep(0)

            async def work() -> None:
                try:
                    with session_tenant(caller.tenant):
                        result = await runtime.run(
                            invocation,
                            user_id=_session_user(caller),
                            session_id=session_id,
                            on_progress=on_progress,
                            quota=quota,
                            quota_policy=quota_policy,
                        )
                except QuotaExceeded:
                    await buffer.put_terminal("error", {"error": "quota_exceeded"})
                except QuotaStoreUnavailable:
                    logger.exception(
                        "quota store unavailable: agent=%s run=%s",
                        name,
                        invocation.run_id,
                    )
                    await buffer.put_terminal("error", {"error": "quota_unavailable"})
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "agent run failed: agent=%s session=%s run=%s",
                        name,
                        session_id,
                        invocation.run_id,
                    )
                    await buffer.put_terminal("error", {"error": "agent run failed"})
                else:
                    await buffer.put_terminal(
                        "done",
                        {
                            "session_id": session_id,
                            "reply": result.text,
                            "run_id": result.run_id,
                            "trace_id": result.trace_id,
                        },
                    )
                finally:
                    await buffer.put_terminal("__end__", {})

            task = asyncio.create_task(work())
            try:
                while True:
                    kind, payload = await buffer.get()
                    if kind == "__end__":
                        break
                    if kind == "error" and payload["dropped"] == 0:
                        payload = {"error": payload["error"]}
                    yield _sse(kind, payload)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/traces/{trace_id}")
    async def get_trace(request: Request, trace_id: str) -> Any:
        caller = _principal_for(request)
        denied = await _forbidden_if_missing(caller, "runs.read")
        if denied is not None:
            return denied
        if not _TRACE_ID.fullmatch(trace_id):
            return {"trace_id": trace_id, "root": None, "error": "trace_not_found"}
        events = _visible_events(await _query_events(request), caller)
        return _trace_payload(events, trace_id)

    if rate_limit is not None:
        app.add_middleware(
            RateLimitMiddleware,
            limiter=build_rate_limiter(rate_limit, surface="console", metrics=metrics),
            surface="console",
            exempt=frozenset({"/healthz", "/metrics"}),
            metrics=metrics,
        )
    open_prefixes = (
        frozenset({"/assets/"}) if ui == "vue" and (_WEB_DIST / "assets").is_dir() else frozenset()
    )
    if oidc is not None:
        app.add_middleware(
            OidcAuthMiddleware, provider=oidc, open_paths=_OPEN_PATHS, open_prefixes=open_prefixes
        )
    elif token:
        app.add_middleware(
            BearerAuthMiddleware, token=token, open_paths=_OPEN_PATHS, open_prefixes=open_prefixes
        )

    return app


def run_console(
    agents: dict[str, BaseAgent],
    *,
    host: str = "127.0.0.1",
    port: int | None = None,
    auth_token: str | None = None,
    allow_unauthenticated: bool = False,
    session_db: str | None = None,
    sandbox: SandboxPolicy | None = None,
    policy_file: str | None = None,
    roles: list[str] | None = None,
    registry: AgentRegistry | None = None,
    eval_reports: EvalReportStore | None = None,
    tool_catalog: ToolCatalog | None = None,
    lifecycle: AgentLifecycleStore | None = None,
    tool_grants: ToolGrantStore | None = None,
    connectors: ConnectorStore | None = None,
    connector_requests: ConnectorRequestStore | None = None,
    credentials: CredentialStore | None = None,
    peers: PeerStore | None = None,
    peer_grants: PeerGrantStore | None = None,
    remote_agents: RemoteAgentStore | None = None,
    remote_secrets: SecretProvider | None = None,
    artifact_store: ArtifactStore | None = None,
    artifact_loader: ArtifactLoader | None = None,
    artifact_trust: TrustStore | None = None,
    max_loaded_agents: int = 20,
    audit_sink: AuditSink | None = None,
    audit_query: AuditQuery | None = None,
    oidc: IdentityProvider | None = None,
    oidc_login: OidcLogin | None = None,
    quota: QuotaManager | None = None,
    quota_config: QuotaConfig | None = None,
    approvals: FileApprovalInbox | PostgresApprovalInbox | None = None,
    metrics: MetricsRegistry | None = None,
    sse_queue_size: int = 512,
    rate_limit: RateLimit | None = None,
    session_tenant_scope: bool = False,
    session_rls: bool = False,
    rag: Any | None = None,
    terminology: ConceptSchemeStore | None = None,
    model_config_store: ModelConfigStore | None = None,
    role_store: RoleStore | None = None,
    user_binding_store: UserBindingStore | None = None,
    security_report: str | None = None,
    ui: str = "legacy",
) -> None:
    """Serve the console (blocking)."""
    app = build_console_app(
        agents,
        auth_token=auth_token,
        session_db=session_db,
        host=host,
        allow_unauthenticated=allow_unauthenticated,
        sandbox=sandbox,
        policy_file=policy_file,
        roles=roles,
        registry=registry,
        eval_reports=eval_reports,
        tool_catalog=tool_catalog,
        lifecycle=lifecycle,
        tool_grants=tool_grants,
        connectors=connectors,
        connector_requests=connector_requests,
        credentials=credentials,
        peers=peers,
        peer_grants=peer_grants,
        remote_agents=remote_agents,
        remote_secrets=remote_secrets,
        artifact_store=artifact_store,
        artifact_loader=artifact_loader,
        artifact_trust=artifact_trust,
        max_loaded_agents=max_loaded_agents,
        audit_sink=audit_sink,
        audit_query=audit_query,
        oidc=oidc,
        oidc_login=oidc_login,
        quota=quota,
        quota_config=quota_config,
        approvals=approvals,
        metrics=metrics,
        sse_queue_size=sse_queue_size,
        rate_limit=rate_limit,
        session_tenant_scope=session_tenant_scope,
        session_rls=session_rls,
        rag=rag,
        terminology=terminology,
        model_config_store=model_config_store,
        role_store=role_store,
        user_binding_store=user_binding_store,
        security_report=security_report,
        ui=ui,
    )

    import uvicorn

    uvicorn.run(app, host=host, port=resolve_port(port), log_level="info")
