"""A minimal private web console for ADK agents (bearer-auth protected).

`GET /` serves a static shell with no data; every `/api/*` endpoint requires
`Authorization: Bearer <token>` (CP-S6). The page asks for the token and keeps
it in ``sessionStorage`` for the current tab only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, cast

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from google.adk.models import BaseLlm
from pydantic import ValidationError

from .approvals import ApprovalConflict, ApprovalExpired, ApprovalNotFound, FileApprovalInbox
from .audit import AuditQuery, AuditQueryUnavailable, ListAuditSink, query_events
from .audit.hashing import hash_text
from .auth import BearerAuthMiddleware, OidcAuthMiddleware, resolve_http_auth
from .core import (
    AccessPolicy,
    AgentLifecycle,
    AgentLifecycleStore,
    AgentRef,
    AgentRegistry,
    ArtifactLoader,
    ArtifactStore,
    AuditEvent,
    AuditSink,
    ConnectorConflict,
    ConnectorSpec,
    ConnectorStore,
    ConnectorStoreError,
    ConnectorStoreUnavailable,
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
    SecretProvider,
    ToolGrantRequest,
    ToolGrantStore,
)
from .mcp.http import resolve_port
from .metrics import MetricsRegistry
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
    fetch_agent_card,
)
from .runtime import AgentRuntime, dev_agent_ref
from .runtime.quota_postgres import QuotaStoreUnavailable
from .runtime.sessions import scoped_user_id
from .sandbox import SandboxPolicy, ToolSandbox, install_tool_sandbox
from .secretstore import PrefixedEnvSecretProvider, SecretNotFound
from .tools import ToolCatalog, ToolEntry, connector_tool_entries, install_declared_guards
from .tracing import resolve_trace_id

if TYPE_CHECKING:  # pragma: no cover
    from google.adk.agents import BaseAgent

logger = logging.getLogger(__name__)

_USER_ID = "console_user"
_OPEN_PATHS = frozenset({"/", "/healthz"})
_TRACE_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
_GRANT_STATUSES = frozenset({"pending", "approved", "denied", "expired", "cancelled"})

_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ADK Console</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; }
  #log { border: 1px solid #ccc; border-radius: 6px; padding: .75rem; height: 320px; overflow-y: auto; }
  #log div { white-space: pre-wrap; margin: .2rem 0; }
  .row { display: flex; gap: .5rem; margin-top: .75rem; }
  input, select, button { font: inherit; padding: .45rem .6rem; }
  #msg { flex: 1; }
  .you { color: #0b5; }
  .agent { color: #246; }
  .system { color: #a00; }
  #tabs { display: flex; gap: .25rem; margin: 1rem 0 .5rem; flex-wrap: wrap; }
  .tab { background: #eee; border: 1px solid #ccc; border-radius: 6px 6px 0 0; cursor: pointer; }
  .tab.active { background: #fff; border-bottom-color: #fff; font-weight: 600; }
  .panel { display: none; }
  .panel.active { display: block; }
  table { border-collapse: collapse; width: 100%; font-size: .85rem; }
  th, td { text-align: left; border-bottom: 1px solid #ddd; padding: .3rem .4rem; }
  tbody tr { cursor: pointer; }
  tbody tr:hover { background: #f5f8ff; }
  .badge { background: #e6f5ea; color: #0b5; border-radius: 4px; padding: 0 .35rem; font-size: .75rem; }
  .badge.bad { background: #fde8e8; color: #a00; }
  .badge.muted { background: #eee; color: #666; }
  pre { background: #f7f7f7; border: 1px solid #ddd; border-radius: 6px; padding: .6rem; overflow: auto; max-height: 260px; font-size: .78rem; }
  .panel-msg { color: #a00; font-size: .85rem; min-height: 1.2rem; }
  #audit { border: 1px solid #ccc; border-radius: 6px; padding: .5rem .75rem; max-height: 220px; overflow-y: auto; font-family: ui-monospace, monospace; font-size: .78rem; }
  #audit div { white-space: pre-wrap; margin: .15rem 0; }
  #policy { width: 100%; box-sizing: border-box; font-family: ui-monospace, monospace; font-size: .8rem; }
  #policy-msg { color: #666; font-size: .85rem; margin-top: .35rem; }
  #status { font-family: ui-monospace, monospace; font-size: .82rem; color: #444; min-height: 1.2rem; }
  #timeline { border-left: 3px solid #ddd; margin: .4rem 0 .2rem 0; padding-left: .6rem; max-height: 180px; overflow-y: auto; font-family: ui-monospace, monospace; font-size: .78rem; }
  #timeline div { margin: .15rem 0; color: #444; }
  #timeline .tool { color: #246; }
  #timeline .fail { color: #a00; }
  #trace { font-family: ui-monospace, monospace; font-size: .78rem; }
  #trace div { margin: .12rem 0; }
  #trace .child { padding-left: 1.1rem; color: #444; }
  #trace .ok { color: #0b5; }
  #trace .error, #trace .denied { color: #a00; }
  small { color: #666; }
</style>
</head>
<body>
<h2>ADK Console</h2>
<p><small>All data endpoints require the bearer token. It is kept in this tab only.</small></p>
<div class="row">
  <select id="agent"></select>
  <input id="token" type="password" placeholder="Bearer token" autocomplete="off">
  <button id="connect">Connect</button>
</div>

<div id="tabs">
  <button id="tab-chat" class="tab active" data-tab="chat">Chat</button>
  <button id="tab-registry" class="tab" data-tab="registry">Registry</button>
  <button id="tab-tools" class="tab" data-tab="tools">Tools</button>
  <button id="tab-connectors" class="tab" data-tab="connectors">Connectors</button>
  <button id="tab-peers" class="tab" data-tab="peers">Peers</button>
  <button id="tab-runs" class="tab" data-tab="runs">Runs</button>
  <button id="tab-sessions" class="tab" data-tab="sessions">Sessions</button>
  <button id="tab-approvals" class="tab" data-tab="approvals">Approvals</button>
  <button id="tab-grants" class="tab" data-tab="grants">Grants</button>
  <button id="tab-plans" class="tab" data-tab="plans">Plans</button>
  <button id="tab-policy" class="tab" data-tab="policy">Policy</button>
</div>

<section id="chat" class="panel active">
  <div id="log"></div>
  <div class="row">
    <input id="msg" placeholder="Ask the agent..." autocomplete="off">
    <button id="send">Send</button>
  </div>
  <h3>Run progress</h3>
  <div id="status"></div>
  <div id="timeline"></div>
  <h3>Recent audit</h3>
  <div id="audit"></div>
  <div class="row">
    <button id="refresh">Refresh audit</button>
  </div>
</section>

<section id="registry" class="panel">
  <div class="row">
    <select id="tenant"></select>
    <button id="refresh-registry">Refresh</button>
    <button id="refresh-remote" disabled>Refresh selected</button>
  </div>
  <div id="registry-msg" class="panel-msg"></div>
  <table>
    <thead><tr><th>id</th><th>source</th><th>version</th><th>published</th><th>eval</th><th>artifact</th><th>lifecycle</th><th>trust</th></tr></thead>
    <tbody id="registry-body"></tbody>
  </table>
  <h3>Manifest</h3>
  <pre id="manifest"></pre>
  <h3>Eval report</h3>
  <pre id="eval-report"></pre>
  <h3>Artifact</h3>
  <pre id="artifact-info"></pre>
  <h3>Lifecycle</h3>
  <pre id="lifecycle-info"></pre>
  <div class="row">
    <button id="open-chat">Open chat</button>
    <button id="unload-agent">Unload</button>
    <span id="artifact-msg" class="panel-msg"></span>
  </div>
</section>

<section id="tools" class="panel">
  <div class="row">
    <button id="refresh-tools">Refresh</button>
  </div>
  <div id="tools-msg" class="panel-msg"></div>
  <table>
    <thead><tr><th>tool</th><th>source</th><th>data classes</th><th>approval</th><th>granted agents</th></tr></thead>
    <tbody id="tools-body"></tbody>
  </table>
</section>

<section id="connectors" class="panel">
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
    <button id="connector-register">Register</button>
    <button id="connector-disable">Disable selected</button>
    <button id="connector-check">Check selected</button>
  </div>
  <div id="connector-health" class="panel-msg"></div>
</section>

<section id="peers" class="panel">
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
    <button id="peer-register">Register</button>
    <button id="peer-disable">Disable selected</button>
  </div>
  <h3>Grant</h3>
  <div class="row">
    <input id="peer-agent" placeholder="agent id" autocomplete="off">
    <label><input type="checkbox" id="peer-action-read" checked> read</label>
    <label><input type="checkbox" id="peer-action-invoke" checked> invoke</label>
    <button id="peer-grant">Grant</button>
    <button id="peer-revoke">Revoke</button>
  </div>
</section>

<section id="runs" class="panel">
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

<section id="sessions" class="panel">
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

<section id="approvals" class="panel">
  <div class="row">
    <button id="refresh-approvals">Refresh</button>
  </div>
  <div id="approvals-msg" class="panel-msg"></div>
  <table>
    <thead><tr><th>request</th><th>step</th><th>agent</th><th>reason</th><th>requested</th></tr></thead>
    <tbody id="approvals-body"></tbody>
  </table>
  <h3>Request</h3>
  <pre id="approval-detail"></pre>
  <div class="row">
    <button id="approve">Approve</button>
    <button id="deny">Deny</button>
  </div>
</section>

<section id="grants" class="panel">
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
    <button id="grant-request">Request for selected</button>
  </div>
  <div class="row">
    <button id="grant-approve">Approve</button>
    <button id="grant-deny">Deny</button>
  </div>
  <h3>Tool usage (recent audit)</h3>
  <table>
    <thead><tr><th>tool</th><th>allowed</th><th>denied</th><th>temporary</th></tr></thead>
    <tbody id="grant-usage-body"></tbody>
  </table>
</section>

<section id="plans" class="panel">
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

<section id="policy" class="panel">
  <h3>Policies</h3>
  <textarea id="policy" rows="12" spellcheck="false"></textarea>
  <div class="row">
    <button id="load-policy">Load policy</button>
    <button id="save-policy">Save policy</button>
  </div>
  <div id="policy-msg"></div>
</section>

<script>
const $ = (id) => document.getElementById(id);
const TABS = ["chat", "registry", "tools", "connectors", "peers", "runs", "sessions", "approvals", "grants", "plans", "policy"];
let sessionId = null;
let selectedApproval = null;
let selectedRegistry = null;
let selectedGrant = null;
let selectedConnector = null;
let selectedPeer = null;
const token = () => $("token").value.trim();
$("token").value = sessionStorage.getItem("adk_token") || "";
$("token").addEventListener("change", () => sessionStorage.setItem("adk_token", token()));

function showTab(name) {
  for (const tab of TABS) {
    const panel = $(tab);
    const button = $("tab-" + tab);
    if (panel) panel.classList.toggle("active", tab === name);
    if (button) button.classList.toggle("active", tab === name);
  }
}

async function getJson(path) {
  const response = await fetch(path, { headers: { Authorization: "Bearer " + token() } });
  let data = null;
  try { data = await response.json(); } catch (e) { data = null; }
  return { ok: response.ok, status: response.status, data: data };
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

function artifactCell(info) {
  const td = document.createElement("td");
  if (!info) { td.textContent = "-"; return td; }
  const badge = document.createElement("span");
  badge.className = info.status === "verified" ? "badge"
    : info.status === "untrusted" ? "badge bad" : "badge muted";
  const hex = String(info.digest || "").replace(/^sha256:/, "").slice(0, 12);
  badge.textContent = info.status + " " + hex;
  td.appendChild(badge);
  return td;
}

function lifecycleCell(info) {
  const td = document.createElement("td");
  if (!info || info.status === "published") { td.textContent = "published"; return td; }
  const badge = document.createElement("span");
  badge.className = info.status === "retired" ? "badge bad" : "badge muted";
  badge.textContent = info.status;
  td.appendChild(badge);
  return td;
}

function trustCell(entry, local) {
  const td = document.createElement("td");
  if (local) { td.textContent = "-"; return td; }
  const trust = entry.trust || {};
  const badge = document.createElement("span");
  badge.className = trust.status === "pinned" ? "badge"
    : trust.status === "changed" ? "badge bad" : "badge muted";
  badge.textContent = trust.status || "unknown";
  td.appendChild(badge);
  if (!entry.enabled) {
    td.appendChild(document.createTextNode(" "));
    const disabled = document.createElement("span");
    disabled.className = "badge muted";
    disabled.textContent = "disabled";
    td.appendChild(disabled);
  }
  return td;
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
  append("system", "connected: " + result.agents.map((a) => a.name).join(", "));
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
  await loadRegistry();
}

async function loadRegistry() {
  const tenant = $("tenant").value;
  $("registry-msg").textContent = "";
  const body = $("registry-body");
  body.innerHTML = "";
  if (!tenant) return;
  const result = await getJson("/api/registry?tenant=" + encodeURIComponent(tenant));
  if (!result.ok) {
    $("registry-msg").textContent = "registry unavailable (" + result.status + "): " +
      ((result.data && result.data.error) || "error");
    return;
  }
  for (const entry of result.data || []) {
    const local = entry.source !== "remote";
    const row = document.createElement("tr");
    row.appendChild(cell(entry.id));
    const sourceCell = document.createElement("td");
    const sourceBadge = document.createElement("span");
    sourceBadge.className = "badge muted";
    sourceBadge.textContent = local ? "local" : "remote";
    sourceCell.appendChild(sourceBadge);
    row.appendChild(sourceCell);
    row.appendChild(cell(local ? entry.version : null));
    const published = document.createElement("td");
    published.textContent = local
      ? String(entry.published_at || "").replace("T", " ").slice(0, 19)
      : "-";
    row.appendChild(published);
    const evalCell = document.createElement("td");
    if (local && entry.has_eval_report) {
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = "eval";
      evalCell.appendChild(badge);
    } else {
      evalCell.textContent = "-";
    }
    row.appendChild(evalCell);
    row.appendChild(local ? artifactCell(entry.artifact) : cell(null));
    row.appendChild(local ? lifecycleCell(entry.lifecycle) : cell(null));
    row.appendChild(trustCell(entry, local));
    row.addEventListener("click", () => selectRegistryEntry(tenant, entry));
    body.appendChild(row);
  }
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
    row.addEventListener("click", () => { showTab("runs"); loadTrace(run.trace_id); });
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

async function loadApprovals() {
  $("approvals-msg").textContent = "";
  const body = $("approvals-body");
  body.innerHTML = "";
  const result = await getJson("/api/approvals");
  if (!result.ok) {
    $("approvals-msg").textContent = result.status === 404
      ? "approvals not configured"
      : "approvals unavailable (" + result.status + ")";
    return;
  }
  for (const request of result.data || []) {
    const row = document.createElement("tr");
    row.appendChild(cell(String(request.request_id).slice(0, 16)));
    row.appendChild(cell(request.step_id));
    row.appendChild(cell(request.agent_ref && request.agent_ref.id));
    row.appendChild(cell(request.reason));
    const requested = document.createElement("td");
    requested.textContent = String(request.requested_at || "").replace("T", " ").slice(0, 19);
    row.appendChild(requested);
    row.addEventListener("click", () => {
      selectedApproval = request.request_id;
      $("approval-detail").textContent = JSON.stringify(request, null, 2);
    });
    body.appendChild(row);
  }
}

async function decideApproval(approved) {
  if (!selectedApproval) {
    $("approvals-msg").textContent = "select a request first";
    return;
  }
  const r = await fetch("/api/approvals/" + encodeURIComponent(selectedApproval), {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + token() },
    body: JSON.stringify({ approved: approved }),
  });
  let data = null;
  try { data = await r.json(); } catch (e) { data = null; }
  if (!r.ok) {
    $("approvals-msg").textContent = (data && data.error) ||
      ("decision failed (" + r.status + ")");
    return;
  }
  selectedApproval = null;
  $("approval-detail").textContent = "";
  await loadApprovals();
  $("approvals-msg").textContent = "decided " + data.request_id;
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
  await loadAgents();
  await loadTenants();
  await loadRuns();
  await loadSessions();
  await loadApprovals();
  await loadPlans();
  await loadTools();
  await loadConnectors();
  await loadGrants();
  loadAudit();
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

async function loadTrace(traceId, targetId) {
  const boxId = targetId || "trace";
  const r = await fetch("/api/traces/" + encodeURIComponent(traceId), {
    headers: { Authorization: "Bearer " + token() },
  });
  if (!r.ok) { $(boxId).textContent = "trace unavailable (" + r.status + ")"; return; }
  const data = await r.json();
  const box = $(boxId);
  box.innerHTML = "";
  if (!data.root) { box.textContent = "trace not found"; return; }
  const rootLine = document.createElement("div");
  rootLine.className = data.root.status;
  rootLine.textContent = data.root.kind + " " + data.root.id + " " + data.root.status +
    (data.root.latency_ms == null ? "" : " " + data.root.latency_ms + "ms");
  box.appendChild(rootLine);
  for (const child of data.root.children || []) {
    const line = document.createElement("div");
    line.className = "child " + child.status;
    line.textContent = child.kind + " " + child.id + " " + child.status +
      (child.latency_ms == null ? "" : " " + child.latency_ms + "ms") +
      (child.error_code ? " [" + child.error_code + "]" : "");
    box.appendChild(line);
  }
}

async function loadAudit() {
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
$("tenant").addEventListener("change", () => { loadRegistry(); loadTools(); loadConnectors(); loadGrants(); });
$("session-agent").addEventListener("change", loadSessions);
$("refresh").addEventListener("click", loadAudit);
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
$("refresh-peers").addEventListener("click", loadPeers);
$("peer-register").addEventListener("click", registerPeer);
$("peer-disable").addEventListener("click", disablePeer);
$("peer-grant").addEventListener("click", grantPeer);
$("peer-revoke").addEventListener("click", revokePeer);
$("refresh-sessions").addEventListener("click", loadSessions);
$("refresh-approvals").addEventListener("click", loadApprovals);
$("refresh-grants").addEventListener("click", loadGrants);
$("grant-request").addEventListener("click", requestGrant);
$("grant-approve").addEventListener("click", () => decideGrant(true));
$("grant-deny").addEventListener("click", () => decideGrant(false));
$("refresh-plans").addEventListener("click", loadPlans);
$("approve").addEventListener("click", () => decideApproval(true));
$("deny").addEventListener("click", () => decideApproval(false));
$("load-policy").addEventListener("click", loadPolicy);
$("save-policy").addEventListener("click", savePolicy);
$("connect").addEventListener("click", connect);
$("send").addEventListener("click", send);
$("msg").addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
for (const tab of TABS) {
  $("tab-" + tab).addEventListener("click", () => showTab(tab));
}
</script>
</body>
</html>
"""


def _session_service(session_db: str | None) -> Any:
    from .runtime.sessions import configured_session_service

    service = configured_session_service(session_db)
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

    node = _trace_node(root)
    node["children"] = [_trace_node(event) for event in relevant if event is not root]
    return {"trace_id": trace_id, "root": node, "error": None}


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
    quota: QuotaManager | None = None,
    quota_config: QuotaConfig | None = None,
    approvals: FileApprovalInbox | None = None,
    metrics: MetricsRegistry | None = None,
    sse_queue_size: int = 512,
    rate_limit: RateLimit | None = None,
    session_tenant_scope: bool = False,
) -> FastAPI:
    """Build the console FastAPI app with one Runner per agent."""
    token = resolve_http_auth(host, auth_token, allow_unauthenticated) if oidc is None else None
    metrics = metrics if metrics is not None else MetricsRegistry()
    principal = Principal(
        tenant="local", subject=_USER_ID, kind="human", roles=list(roles or ["admin"])
    )

    def _principal_for(request: Request) -> Principal:
        found = getattr(request.state, "principal", None)
        return found if found is not None else principal

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
    secrets = remote_secrets if remote_secrets is not None else PrefixedEnvSecretProvider()

    from google.adk.runners import Runner

    service = session_service if session_service is not None else _session_service(session_db)
    audit = audit_sink if audit_sink is not None else ListAuditSink()

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

    def _register(name: str, agent: Any) -> None:
        _wrap_model(agent, audit)
        install_tool_sandbox(agent, ToolSandbox(sandbox_policy))
        install_declared_guards(agent, audit, overlay=tool_grants)
        runner = Runner(app_name=name, agent=agent, session_service=service)
        agents[name] = agent
        runners[name] = runner
        runtimes[name] = AgentRuntime(runner, audit=audit, metrics=metrics, source="console")

    for name, agent in list(agents.items()):
        _register(name, agent)

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

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _INDEX_HTML

    @app.get("/api/agents")
    async def list_agents() -> list[dict[str, str]]:
        return [
            {"name": name, "description": agent.description or ""} for name, agent in agents.items()
        ]

    @app.get("/api/audit")
    async def list_audit(request: Request, limit: int = 50) -> list[dict]:
        limit = min(max(limit, 1), 200)
        events = _visible_events(await _query_events(request), _principal_for(request))
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
        if registry is None and remote_agents is None:
            return JSONResponse({"error": "registry_not_configured"}, status_code=404)
        caller = _principal_for(request)
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

        caller = _principal_for(request)
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
                agent = await loader.load(artifact, artifact_store)
            except ArtifactLoadError:
                logger.exception("artifact load failed: %s/%s@%s", tenant, agent_id, version)
                return JSONResponse({"error": "load_failed"}, status_code=500)

            _register(agent_id, agent)
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
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        name = body.get("name")
        if not isinstance(name, str) or not name:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        caller = _principal_for(request)
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
        if tool_catalog is None and connectors is None:
            return JSONResponse({"error": "tool_catalog_not_configured"}, status_code=404)
        caller = _principal_for(request)
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
        if connectors is None:
            return JSONResponse({"error": "connectors_not_configured"}, status_code=404)
        caller = _principal_for(request)
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
        if "admin" not in caller.roles:
            return JSONResponse({"error": "forbidden"}, status_code=403)
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
        if "admin" not in caller.roles:
            return JSONResponse({"error": "forbidden"}, status_code=403)
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
        if connectors is None:
            return JSONResponse({"error": "connectors_not_configured"}, status_code=404)
        caller = _principal_for(request)
        try:
            spec = await connectors.get(connector_id)
        except ConnectorStoreError:
            logger.exception("connector read failed: id=%s", connector_id)
            return JSONResponse({"error": "connector_store_unavailable"}, status_code=503)
        if spec is None:
            return JSONResponse({"error": "connector_not_found"}, status_code=404)
        if spec.tenant is not None and spec.tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
        if "admin" not in caller.roles:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        health = await check_connector(spec)
        return JSONResponse(health.model_dump(mode="json"))

    @app.get("/api/peers")
    async def list_peers(request: Request, tenant: str | None = None) -> Any:
        if peers is None or peer_grants is None:
            return JSONResponse({"error": "peers_not_configured"}, status_code=404)
        caller = _principal_for(request)
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
        if "admin" not in caller.roles:
            return JSONResponse({"error": "forbidden"}, status_code=403)
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
        if peers is None or peer_grants is None:
            return JSONResponse({"error": "peers_not_configured"}, status_code=404)
        caller = _principal_for(request)
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
        if "admin" not in caller.roles:
            return JSONResponse({"error": "forbidden"}, status_code=403)
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
        if peers is None or peer_grants is None:
            return JSONResponse({"error": "peers_not_configured"}, status_code=404)
        caller = _principal_for(request)
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
        if "admin" not in caller.roles:
            return JSONResponse({"error": "forbidden"}, status_code=403)
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
        if peers is None or peer_grants is None:
            return JSONResponse({"error": "peers_not_configured"}, status_code=404)
        caller = _principal_for(request)
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
        if "admin" not in caller.roles:
            return JSONResponse({"error": "forbidden"}, status_code=403)
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
        if remote_agents is None:
            return JSONResponse({"error": "remote_agents_not_configured"}, status_code=404)
        caller = _principal_for(request)
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
        if "admin" not in caller.roles:
            return JSONResponse({"error": "forbidden"}, status_code=403)
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
                credential = await secrets.resolve(registration.credential_ref)
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
        if remote_agents is None:
            return JSONResponse({"error": "remote_agents_not_configured"}, status_code=404)
        caller = _principal_for(request)
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
        if "admin" not in caller.roles:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        digest: str | None = None
        try:
            credential = (
                await secrets.resolve(existing.credential_ref)
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
        if remote_agents is None:
            return JSONResponse({"error": "remote_agents_not_configured"}, status_code=404)
        caller = _principal_for(request)
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
        if "admin" not in caller.roles:
            return JSONResponse({"error": "forbidden"}, status_code=403)
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
        if tool_grants is None:
            return JSONResponse({"error": "tool_grants_not_configured"}, status_code=404)
        grant_status: GrantStatus | None = None
        if status is not None:
            if status not in _GRANT_STATUSES:
                return JSONResponse({"error": "invalid_status"}, status_code=400)
            grant_status = cast(GrantStatus, status)
        caller = _principal_for(request)
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
        caller = _principal_for(request)
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
        caller = _principal_for(request)
        if "admin" not in caller.roles:
            return JSONResponse({"error": "forbidden"}, status_code=403)
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
    async def list_runs(request: Request, limit: int = 50) -> list[dict]:
        events = _visible_events(await _query_events(request), _principal_for(request))
        return _summarize_runs(events, limit)

    @app.get("/api/approvals")
    async def list_approvals(request: Request) -> Any:
        if approvals is None:
            return JSONResponse({"error": "approvals_not_configured"}, status_code=404)
        caller = _principal_for(request)
        pending = approvals.pending()
        if "admin" not in caller.roles:
            pending = [item for item in pending if item.principal.tenant == caller.tenant]
        return [item.model_dump(mode="json") for item in pending]

    @app.post("/api/approvals/{request_id}")
    async def decide_approval(request: Request, request_id: str) -> Any:
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

        caller = _principal_for(request)
        record = approvals.get(request_id)
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
        except ApprovalConflict:
            return JSONResponse({"error": "approval_already_decided"}, status_code=409)
        except ApprovalExpired:
            return JSONResponse({"error": "approval_expired"}, status_code=410)
        except ApprovalNotFound:
            return JSONResponse({"error": "approval_not_found"}, status_code=404)

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

    @app.get("/api/plans")
    async def list_plans(request: Request, limit: int = 50) -> list[dict]:
        events = _visible_events(await _query_events(request), _principal_for(request))
        return _summarize_plans(events, limit)

    @app.get("/api/sessions")
    async def list_sessions(request: Request, agent: str | None = None) -> Any:
        if agent not in agents:
            return JSONResponse({"error": "unknown_agent"}, status_code=400)
        listed = await service.list_sessions(
            app_name=agent, user_id=_session_user(_principal_for(request))
        )
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
        async def get_policy() -> dict:
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
    async def chat(request: Request) -> JSONResponse:
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

        caller = _principal_for(request)
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

        caller = _principal_for(request)
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
    async def get_trace(request: Request, trace_id: str) -> dict:
        if not _TRACE_ID.fullmatch(trace_id):
            return {"trace_id": trace_id, "root": None, "error": "trace_not_found"}
        events = _visible_events(await _query_events(request), _principal_for(request))
        return _trace_payload(events, trace_id)

    if rate_limit is not None:
        app.add_middleware(
            RateLimitMiddleware,
            limiter=build_rate_limiter(rate_limit, surface="console", metrics=metrics),
            surface="console",
            exempt=frozenset({"/healthz", "/metrics"}),
            metrics=metrics,
        )
    if oidc is not None:
        app.add_middleware(OidcAuthMiddleware, provider=oidc, open_paths=_OPEN_PATHS)
    elif token:
        app.add_middleware(BearerAuthMiddleware, token=token, open_paths=_OPEN_PATHS)

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
    quota: QuotaManager | None = None,
    quota_config: QuotaConfig | None = None,
    approvals: FileApprovalInbox | None = None,
    metrics: MetricsRegistry | None = None,
    sse_queue_size: int = 512,
    rate_limit: RateLimit | None = None,
    session_tenant_scope: bool = False,
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
        quota=quota,
        quota_config=quota_config,
        approvals=approvals,
        metrics=metrics,
        sse_queue_size=sse_queue_size,
        rate_limit=rate_limit,
        session_tenant_scope=session_tenant_scope,
    )

    import uvicorn

    uvicorn.run(app, host=host, port=resolve_port(port), log_level="info")
