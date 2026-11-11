"""A minimal private web console for ADK agents (bearer-auth protected).

`GET /` serves a static shell with no data; every `/api/*` endpoint requires
`Authorization: Bearer <token>` (CP-S6). The page asks for the token and keeps
it in ``sessionStorage`` for the current tab only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .mcp.http import BearerAuthMiddleware, resolve_http_auth, resolve_port

if TYPE_CHECKING:  # pragma: no cover
    from google.adk.agents import BaseAgent

_USER_ID = "console_user"
_OPEN_PATHS = frozenset({"/", "/healthz"})

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
}

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


def build_console_app(
    agents: dict[str, BaseAgent],
    *,
    auth_token: str | None,
    session_db: str | None = None,
    host: str = "127.0.0.1",
    allow_unauthenticated: bool = False,
) -> FastAPI:
    """Build the console FastAPI app with one Runner per agent."""
    token = resolve_http_auth(host, auth_token, allow_unauthenticated)

    from google.adk.runners import Runner

    session_service = _session_service(session_db)
    runners = {
        name: Runner(app_name=name, agent=agent, session_service=session_service)
        for name, agent in agents.items()
    }

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

    @app.post("/api/chat")
    async def chat(request: Request) -> JSONResponse:
        from google.genai import types

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
        runner = runners.get(name)
        if runner is None:
            return JSONResponse({"error": "unknown agent"}, status_code=400)

        session_id = body.get("session_id")
        if not session_id:
            session = await session_service.create_session(app_name=name, user_id=_USER_ID)
            session_id = session.id

        new_message = types.Content(role="user", parts=[types.Part(text=message)])
        reply_parts: list[str] = []
        try:
            async for event in runner.run_async(
                user_id=_USER_ID,
                session_id=session_id,
                new_message=new_message,
            ):
                if event.is_final_response() and event.content and event.content.parts:
                    for part in event.content.parts:
                        if not part.thought and part.text:
                            reply_parts.append(part.text)
        except Exception:  # noqa: BLE001
            return JSONResponse({"error": "agent run failed"}, status_code=500)

        return JSONResponse({"session_id": session_id, "reply": "".join(reply_parts).strip()})

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
) -> None:
    """Serve the console (blocking)."""
    app = build_console_app(
        agents,
        auth_token=auth_token,
        session_db=session_db,
        host=host,
        allow_unauthenticated=allow_unauthenticated,
    )

    import uvicorn

    uvicorn.run(app, host=host, port=resolve_port(port), log_level="info")
