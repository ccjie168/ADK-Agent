"""A minimal private web console for ADK agents (bearer-auth protected).

`GET /` serves a static shell with no data; every `/api/*` endpoint requires
`Authorization: Bearer <token>` (CP-S6). The page asks for the token and keeps
it in ``sessionStorage`` for the current tab only.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from google.adk.models import BaseLlm
from google.adk.tools import BaseTool
from google.adk.tools.base_toolset import BaseToolset
from pydantic import ValidationError

from .audit import ListAuditSink
from .audit.hashing import hash_text
from .auth import BearerAuthMiddleware, resolve_http_auth
from .core import AccessPolicy, AuditEvent, Invocation, ModelPolicy, Principal, ToolGrant
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

async function send() {
  const message = $("msg").value.trim();
  if (!message) return;
  $("msg").value = "";
  append("you", message);
  const body = { agent: $("agent").value, message };
  if (sessionId) body.session_id = sessionId;
  const r = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + token() },
    body: JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok) { append("system", data.error || ("error " + r.status)); return; }
  sessionId = data.session_id;
  append("agent", data.reply || "(empty)");
  append("system", "trace " + data.trace_id);
  loadAudit();
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
    if session_db:
        from pathlib import Path

        from google.adk.sessions.sqlite_session_service import SqliteSessionService

        Path(session_db).parent.mkdir(parents=True, exist_ok=True)
        return SqliteSessionService(session_db)

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
        if policy_engine is not None:
            decision = await policy_engine.decide(invocation, "agent.run", name)
            if decision.decision != "allow":
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
                        args_hash=hash_text(message),
                        status="denied",
                        error_code="policy_denied",
                        timestamp=datetime.now(timezone.utc),
                    )
                )
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
