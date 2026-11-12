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
from .auth import BearerAuthMiddleware, resolve_http_auth
from .core import (
    AccessPolicy,
    AuditEvent,
    Invocation,
    ModelPolicy,
    Principal,
    ProgressEvent,
    ToolGrant,
)
from .mcp.http import resolve_port
from .models.gateway_llm import GatewayLlm, provider_for_model
from .rbac import FilePolicyStore, RolePolicyEngine
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
  body { font-family: system-ui, sans-serif; max-width: 860px; margin: 2rem auto; padding: 0 1rem; }
  #log { border: 1px solid #ccc; border-radius: 6px; padding: .75rem; height: 360px; overflow-y: auto; }
  #log div { white-space: pre-wrap; margin: .2rem 0; }
  .row { display: flex; gap: .5rem; margin-top: .75rem; }
  input, select, button { font: inherit; padding: .45rem .6rem; }
  #msg { flex: 1; }
  .you { color: #0b5; }
  .agent { color: #246; }
  .system { color: #a00; }
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
<div id="log"></div>
<div class="row">
  <input id="msg" placeholder="Ask the agent..." autocomplete="off">
  <button id="send">Send</button>
</div>
<h3>Run progress</h3>
<div id="status"></div>
<div id="timeline"></div>
<h3>Trace</h3>
<div id="trace"></div>
<h3>Recent audit</h3>
<div id="audit"></div>
<div class="row">
  <button id="refresh">Refresh audit</button>
</div>
<h3>Policies</h3>
<textarea id="policy" rows="10" spellcheck="false"></textarea>
<div class="row">
  <button id="load-policy">Load policy</button>
  <button id="save-policy">Save policy</button>
</div>
<div id="policy-msg"></div>
<script>
const $ = (id) => document.getElementById(id);
let sessionId = null;
const token = () => $("token").value.trim();
$("token").value = sessionStorage.getItem("adk_token") || "";
$("token").addEventListener("change", () => sessionStorage.setItem("adk_token", token()));

function append(who, text) {
  const line = document.createElement("div");
  line.className = who;
  line.textContent = (who === "you" ? "you: " : who + ": ") + text;
  $("log").appendChild(line);
  $("log").scrollTop = $("log").scrollHeight;
}

async function loadAgents() {
  const r = await fetch("/api/agents", { headers: { Authorization: "Bearer " + token() } });
  if (!r.ok) { append("system", "connect failed (" + r.status + ")"); return; }
  const agents = await r.json();
  $("agent").innerHTML = "";
  for (const a of agents) {
    const o = document.createElement("option");
    o.value = a.name;
    o.textContent = a.name + (a.description ? " - " + a.description : "");
    $("agent").appendChild(o);
  }
  append("system", "connected: " + agents.map((a) => a.name).join(", "));
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
  for (const line of block.split("\n")) {
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
      while ((index = buffer.indexOf("\n\n")) >= 0) {
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
$("refresh").addEventListener("click", loadAudit);
$("load-policy").addEventListener("click", loadPolicy);
$("save-policy").addEventListener("click", savePolicy);
$("connect").addEventListener("click", loadAgents);
$("send").addEventListener("click", send);
$("msg").addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
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


async def _session_id_for(session_service: Any, app_name: str, raw: object) -> str:
    """Return an existing session for this agent, or create a new one."""
    if isinstance(raw, str) and raw:
        session = await session_service.get_session(
            app_name=app_name, user_id=_USER_ID, session_id=raw
        )
        if session is not None:
            return str(session.id)
    session = await session_service.create_session(app_name=app_name, user_id=_USER_ID)
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
) -> FastAPI:
    """Build the console FastAPI app with one Runner per agent."""
    token = resolve_http_auth(host, auth_token, allow_unauthenticated)
    principal = Principal(
        tenant="local", subject=_USER_ID, kind="human", roles=list(roles or ["admin"])
    )
    policy_store = FilePolicyStore(policy_file) if policy_file else None
    policy_engine = RolePolicyEngine(policy_store.load()) if policy_store else None

    from google.adk.runners import Runner

    session_service = _session_service(session_db)
    audit = ListAuditSink()
    sandbox_policy = sandbox or SandboxPolicy()
    for agent in agents.values():
        _wrap_model(agent, audit)
        install_tool_sandbox(agent, ToolSandbox(sandbox_policy))
        _install_tool_guard(agent, audit)
    runners = {
        name: Runner(app_name=name, agent=agent, session_service=session_service)
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
                tenant=principal.tenant,
                principal=principal,
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
    async def list_audit(limit: int = 50) -> list[dict]:
        limit = min(max(limit, 1), 200)
        return [event.model_dump(mode="json") for event in audit.recent(limit)]

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

            invocation = Invocation(
                run_id=uuid.uuid4().hex,
                trace_id=_trace_id(request),
                principal=principal,
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
                        tenant=principal.tenant,
                        principal=principal,
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
                    tenant=principal.tenant,
                    principal=principal,
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

        session_id = await _session_id_for(session_service, name, body.get("session_id"))

        invocation = Invocation(
            run_id=uuid.uuid4().hex,
            trace_id=_trace_id(request),
            principal=principal,
            agent_ref=dev_agent_ref(name),
            input=message,
        )
        if not await allowed(invocation, name):
            return JSONResponse({"error": "policy_denied"}, status_code=403)
        try:
            result = await runtime.run(invocation, user_id=_USER_ID, session_id=session_id)
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

        session_id = await _session_id_for(session_service, name, body.get("session_id"))
        invocation = Invocation(
            run_id=uuid.uuid4().hex,
            trace_id=_trace_id(request),
            principal=principal,
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
                        user_id=_USER_ID,
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
    async def get_trace(trace_id: str) -> dict:
        if not _TRACE_ID.fullmatch(trace_id):
            return {"trace_id": trace_id, "root": None, "error": "trace_not_found"}
        return _trace_payload(audit.recent(1000), trace_id)

    if token:
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
    )

    import uvicorn

    uvicorn.run(app, host=host, port=resolve_port(port), log_level="info")
