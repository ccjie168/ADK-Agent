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
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from google.adk.models import BaseLlm
from google.adk.tools import BaseTool
from google.adk.tools.base_toolset import BaseToolset
from pydantic import ValidationError

from .audit import ListAuditSink
from .audit.hashing import hash_text
from .auth import BearerAuthMiddleware, OidcAuthMiddleware, resolve_http_auth
from .core import (
    AccessPolicy,
    AgentRegistry,
    AuditEvent,
    EvalReportStore,
    IdentityProvider,
    Invocation,
    ModelPolicy,
    Principal,
    ProgressEvent,
    ToolGrant,
)
from .mcp.http import resolve_port
from .models.gateway_llm import GatewayLlm, provider_for_model
from .rbac import FilePolicyStore, RolePolicyEngine
from .registry import RegistryIntegrityError
from .runtime import AgentRuntime, dev_agent_ref
from .sandbox import SandboxPolicy, ToolSandbox, install_tool_sandbox
from .tools import GrantPolicyEngine, ToolGuard, install_tool_guard, toolset_tool_ids

if TYPE_CHECKING:  # pragma: no cover
    from google.adk.agents import BaseAgent

logger = logging.getLogger(__name__)

_USER_ID = "console_user"
_OPEN_PATHS = frozenset({"/", "/healthz"})
_TRACE_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")

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
  <button id="tab-runs" class="tab" data-tab="runs">Runs</button>
  <button id="tab-sessions" class="tab" data-tab="sessions">Sessions</button>
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
  </div>
  <div id="registry-msg" class="panel-msg"></div>
  <table>
    <thead><tr><th>id</th><th>version</th><th>published</th><th>eval</th></tr></thead>
    <tbody id="registry-body"></tbody>
  </table>
  <h3>Manifest</h3>
  <pre id="manifest"></pre>
  <h3>Eval report</h3>
  <pre id="eval-report"></pre>
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
const TABS = ["chat", "registry", "runs", "sessions", "policy"];
let sessionId = null;
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

function cell(text) {
  const td = document.createElement("td");
  td.textContent = text == null ? "-" : String(text);
  return td;
}

function append(who, text) {
  const line = document.createElement("div");
  line.className = who;
  line.textContent = (who === "you" ? "you: " : who + ": ") + text;
  $("log").appendChild(line);
  $("log").scrollTop = $("log").scrollHeight;
}

async function loadAgents() {
  const result = await getJson("/api/agents");
  if (!result.ok) { append("system", "connect failed (" + result.status + ")"); return; }
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
  append("system", "connected: " + agents.map((a) => a.name).join(", "));
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
    const row = document.createElement("tr");
    row.appendChild(cell(entry.id));
    row.appendChild(cell(entry.version));
    const published = document.createElement("td");
    published.textContent = String(entry.published_at || "").replace("T", " ").slice(0, 19);
    row.appendChild(published);
    const evalCell = document.createElement("td");
    if (entry.has_eval_report) {
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = "eval";
      evalCell.appendChild(badge);
    } else {
      evalCell.textContent = "-";
    }
    row.appendChild(evalCell);
    row.addEventListener("click", () => selectRegistryEntry(tenant, entry));
    body.appendChild(row);
  }
}

async function selectRegistryEntry(tenant, entry) {
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

async function connect() {
  await loadAgents();
  await loadTenants();
  await loadRuns();
  await loadSessions();
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

async function loadTrace(traceId) {
  const r = await fetch("/api/traces/" + encodeURIComponent(traceId), {
    headers: { Authorization: "Bearer " + token() },
  });
  if (!r.ok) { $("trace").textContent = "trace unavailable (" + r.status + ")"; return; }
  const data = await r.json();
  const box = $("trace");
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
$("tenant").addEventListener("change", loadRegistry);
$("session-agent").addEventListener("change", loadSessions);
$("refresh").addEventListener("click", loadAudit);
$("refresh-registry").addEventListener("click", loadRegistry);
$("refresh-runs").addEventListener("click", loadRuns);
$("refresh-sessions").addEventListener("click", loadSessions);
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
    candidate = request.headers.get("x-trace-id", "")
    return candidate if _TRACE_ID.fullmatch(candidate) else uuid.uuid4().hex


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


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def _wrap_model(agent: Any, audit: ListAuditSink) -> None:
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


def _declared_tool_ids(agent: Any) -> set[str]:
    """Collect the tool names an agent tree declares."""
    tool_ids: set[str] = set()
    for tool in getattr(agent, "tools", None) or ():
        if isinstance(tool, BaseTool):
            tool_ids.add(tool.name)
            continue
        if isinstance(tool, BaseToolset):
            tool_ids |= toolset_tool_ids(tool)
            continue
        name = getattr(tool, "__name__", None)
        if isinstance(name, str):
            tool_ids.add(name)
    for sub in getattr(agent, "sub_agents", None) or ():
        tool_ids |= _declared_tool_ids(sub)
    return tool_ids


def _install_tool_guard(agent: Any, audit: ListAuditSink) -> None:
    """Allow the agent's declared tools and deny everything else."""
    grants = [ToolGrant(tool_id=tool_id) for tool_id in sorted(_declared_tool_ids(agent))]
    install_tool_guard(agent, ToolGuard(GrantPolicyEngine(grants), audit=audit))


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
    session_service: Any | None = None,
    audit_sink: ListAuditSink | None = None,
    oidc: IdentityProvider | None = None,
) -> FastAPI:
    """Build the console FastAPI app with one Runner per agent."""
    token = resolve_http_auth(host, auth_token, allow_unauthenticated) if oidc is None else None
    principal = Principal(
        tenant="local", subject=_USER_ID, kind="human", roles=list(roles or ["admin"])
    )

    def _principal_for(request: Request) -> Principal:
        found = getattr(request.state, "principal", None)
        return found if found is not None else principal

    policy_store = FilePolicyStore(policy_file) if policy_file else None
    policy_engine = RolePolicyEngine(policy_store.load()) if policy_store else None

    from google.adk.runners import Runner

    service = session_service if session_service is not None else _session_service(session_db)
    audit = audit_sink if audit_sink is not None else ListAuditSink()
    sandbox_policy = sandbox or SandboxPolicy()
    for agent in agents.values():
        _wrap_model(agent, audit)
        install_tool_sandbox(agent, ToolSandbox(sandbox_policy))
        _install_tool_guard(agent, audit)
    runners = {
        name: Runner(app_name=name, agent=agent, session_service=service)
        for name, agent in agents.items()
    }
    runtimes = {name: AgentRuntime(runner, audit=audit) for name, runner in runners.items()}

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

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

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
        events = _visible_events(audit.recent(1000), _principal_for(request))
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
        if registry is None:
            return JSONResponse({"error": "registry_not_configured"}, status_code=404)
        caller = _principal_for(request)
        target = tenant or caller.tenant
        if tenant and tenant != caller.tenant and "admin" not in caller.roles:
            return JSONResponse({"error": "tenant_forbidden"}, status_code=403)
        try:
            records = await registry.list(target)
        except RegistryIntegrityError:
            return JSONResponse({"error": "registry_corrupt"}, status_code=500)
        except ValueError:
            return JSONResponse({"error": "unsafe_tenant"}, status_code=400)

        entries = []
        for record in records:
            has_report = (
                await eval_reports.has(target, record.manifest.id, record.manifest.version)
                if eval_reports is not None
                else False
            )
            entries.append(
                {
                    "tenant": target,
                    "id": record.manifest.id,
                    "version": record.manifest.version,
                    "digest": record.digest,
                    "description": record.manifest.description,
                    "published_at": record.published_at.isoformat(),
                    "has_eval_report": has_report,
                    "manifest": record.manifest.model_dump(mode="json"),
                }
            )
        return entries

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

    @app.get("/api/runs")
    async def list_runs(request: Request, limit: int = 50) -> list[dict]:
        events = _visible_events(audit.recent(1000), _principal_for(request))
        return _summarize_runs(events, limit)

    @app.get("/api/sessions")
    async def list_sessions(request: Request, agent: str | None = None) -> Any:
        if agent not in agents:
            return JSONResponse({"error": "unknown_agent"}, status_code=400)
        listed = await service.list_sessions(
            app_name=agent, user_id=_principal_for(request).subject
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
        session_id = await _session_id_for(service, name, body.get("session_id"), caller.subject)

        invocation = Invocation(
            run_id=uuid.uuid4().hex,
            trace_id=_trace_id(request),
            principal=caller,
            agent_ref=dev_agent_ref(name),
            input=message,
        )
        if not await allowed(invocation, name):
            return JSONResponse({"error": "policy_denied"}, status_code=403)
        try:
            result = await runtime.run(invocation, user_id=caller.subject, session_id=session_id)
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
        session_id = await _session_id_for(service, name, body.get("session_id"), caller.subject)
        invocation = Invocation(
            run_id=uuid.uuid4().hex,
            trace_id=_trace_id(request),
            principal=caller,
            agent_ref=dev_agent_ref(name),
            input=message,
        )
        if not await allowed(invocation, name):
            return JSONResponse({"error": "policy_denied"}, status_code=403)

        async def events():
            queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()

            async def on_progress(event: ProgressEvent) -> None:
                await queue.put(("progress", event.model_dump(mode="json")))

            async def work() -> None:
                try:
                    result = await runtime.run(
                        invocation,
                        user_id=caller.subject,
                        session_id=session_id,
                        on_progress=on_progress,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "agent run failed: agent=%s session=%s run=%s",
                        name,
                        session_id,
                        invocation.run_id,
                    )
                    await queue.put(("error", {"error": "agent run failed"}))
                else:
                    await queue.put(
                        (
                            "done",
                            {
                                "session_id": session_id,
                                "reply": result.text,
                                "run_id": result.run_id,
                                "trace_id": result.trace_id,
                            },
                        )
                    )
                finally:
                    await queue.put(("__end__", {}))

            task = asyncio.create_task(work())
            try:
                while True:
                    kind, payload = await queue.get()
                    if kind == "__end__":
                        break
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
        events = _visible_events(audit.recent(1000), _principal_for(request))
        return _trace_payload(events, trace_id)

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
    oidc: IdentityProvider | None = None,
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
        oidc=oidc,
    )

    import uvicorn

    uvicorn.run(app, host=host, port=resolve_port(port), log_level="info")
