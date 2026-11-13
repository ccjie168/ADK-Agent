"""SLICE-058: fixed-window ingress rate limiting."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from adk_agent import cli
from adk_agent.audit.service import build_audit_pipeline_app
from adk_agent.console import build_console_app
from adk_agent.core import Principal
from adk_agent.metrics import MetricsRegistry
from adk_agent.models.service import build_model_gateway_app
from adk_agent.ratelimit import FixedWindowLimiter, RateLimit, RateLimitMiddleware
from adk_agent.tools.service import build_tool_gateway_app

AUTH = {"Authorization": "Bearer secret"}


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


async def _ok(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def _app(limit: int, window: float = 60.0, clock: Clock | None = None, metrics=None) -> Starlette:
    app = Starlette(routes=[Route("/x", _ok), Route("/healthz", _ok)])
    kwargs: dict = {
        "limiter": FixedWindowLimiter(limit, window, clock=clock or Clock()),
        "surface": "test",
    }
    if metrics is not None:
        kwargs["metrics"] = metrics
    app.add_middleware(RateLimitMiddleware, **kwargs)
    return app


class _SetPrincipal(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        subject = request.headers.get("x-subject", "alice")
        request.state.principal = Principal(tenant="acme", subject=subject, kind="human")
        return await call_next(request)


def test_allows_up_to_limit():
    limiter = FixedWindowLimiter(3, 60, clock=Clock())

    assert [limiter.check("a") for _ in range(3)] == [None, None, None]
    assert limiter.check("a") is not None


def test_retry_after_counts_down():
    clock = Clock()
    limiter = FixedWindowLimiter(2, 10, clock=clock)
    limiter.check("a")
    limiter.check("a")

    assert limiter.check("a") == 10.0
    clock.now = 1005
    assert limiter.check("a") == 5.0


def test_window_resets():
    clock = Clock()
    limiter = FixedWindowLimiter(2, 10, clock=clock)
    limiter.check("a")
    limiter.check("a")
    assert limiter.check("a") is not None

    clock.now = 1010
    assert limiter.check("a") is None


def test_keys_are_isolated():
    limiter = FixedWindowLimiter(1, 30, clock=Clock())

    assert limiter.check("acme:alice") is None
    assert limiter.check("acme:alice") is not None
    assert limiter.check("acme:bob") is None


def test_middleware_denies():
    with TestClient(_app(2)) as client:
        assert client.get("/x").status_code == 200
        assert client.get("/x").status_code == 200
        third = client.get("/x")

    assert third.status_code == 429
    assert third.json() == {"error": "rate_limited"}
    assert int(third.headers["Retry-After"]) >= 1


def test_middleware_keys_by_principal():
    app = Starlette(routes=[Route("/x", _ok)])
    app.add_middleware(
        RateLimitMiddleware,
        limiter=FixedWindowLimiter(2, 60, clock=Clock()),
        surface="test",
    )
    app.add_middleware(_SetPrincipal)

    with TestClient(app) as client:
        assert client.get("/x", headers={"x-subject": "alice"}).status_code == 200
        assert client.get("/x", headers={"x-subject": "alice"}).status_code == 200
        assert client.get("/x", headers={"x-subject": "alice"}).status_code == 429
        assert client.get("/x", headers={"x-subject": "bob"}).status_code == 200


def test_healthz_is_exempt():
    with TestClient(_app(1)) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/healthz").status_code == 200
        assert client.get("/healthz").status_code == 200


def test_rate_limited_metric():
    metrics = MetricsRegistry()

    with TestClient(_app(1, metrics=metrics)) as client:
        client.get("/x")
        client.get("/x")

    rendered = metrics.render()
    assert "adk_http_rate_limited_total" in rendered
    assert 'surface="test"' in rendered


def test_auth_runs_before_limit():
    app = build_model_gateway_app(
        object(), auth_token="secret", rate_limit=RateLimit(limit=1, window_seconds=60)
    )

    with TestClient(app) as client:
        assert client.post("/v1/complete", json={}).status_code == 401
        assert client.post("/v1/complete", json={}).status_code == 401


def test_metrics_endpoint_is_exempt():
    app = build_model_gateway_app(
        object(), auth_token="secret", rate_limit=RateLimit(limit=1, window_seconds=60)
    )

    with TestClient(app) as client:
        assert client.post("/v1/complete", json={}, headers=AUTH).status_code == 400
        assert client.get("/metrics", headers=AUTH).status_code == 200
        assert client.get("/metrics", headers=AUTH).status_code == 200


def test_model_gateway_wired():
    app = build_model_gateway_app(
        object(), auth_token="secret", rate_limit=RateLimit(limit=2, window_seconds=60)
    )

    with TestClient(app) as client:
        assert client.post("/v1/complete", json={}, headers=AUTH).status_code == 400
        assert client.post("/v1/complete", json={}, headers=AUTH).status_code == 400
        assert client.post("/v1/complete", json={}, headers=AUTH).status_code == 429
        assert client.get("/healthz").status_code == 200


def test_tool_gateway_wired():
    app = build_tool_gateway_app(
        object(), auth_token="secret", rate_limit=RateLimit(limit=1, window_seconds=60)
    )

    with TestClient(app) as client:
        assert client.post("/v1/invoke", json={}, headers=AUTH).status_code == 400
        assert client.post("/v1/invoke", json={}, headers=AUTH).status_code == 429


def test_console_wired():
    agents = {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }
    app = build_console_app(
        agents, auth_token="secret", rate_limit=RateLimit(limit=1, window_seconds=60)
    )

    with TestClient(app) as client:
        assert client.post("/api/chat", json={}, headers=AUTH).status_code == 400
        assert client.post("/api/chat", json={}, headers=AUTH).status_code == 429


def test_audit_wired():
    app = build_audit_pipeline_app(
        object(), auth_token="secret", rate_limit=RateLimit(limit=1, window_seconds=60)
    )

    with TestClient(app) as client:
        assert client.post("/v1/events", json={}, headers=AUTH).status_code == 400
        assert client.post("/v1/events", json={}, headers=AUTH).status_code == 429


def _agents_file(tmp_path):
    path = tmp_path / "agents.py"
    path.write_text(
        "from google.adk.agents import LlmAgent\n"
        "agents = {'probe': LlmAgent(name='probe', model='gemini-2.5-pro', instruction='x')}\n",
        encoding="utf-8",
    )
    return str(path)


def _bad_commands(tmp_path):
    agents = _agents_file(tmp_path)
    tools = tmp_path / "tools.py"
    tools.write_text("tools = {}\n", encoding="utf-8")
    return [
        ["console", "--agents", agents, "--rate-limit", "0"],
        ["console", "--agents", agents, "--rate-limit", "5", "--rate-limit-window", "0"],
        ["console", "--agents", agents, "--rate-limit-window", "5"],
        ["serve-model-gateway", "--rate-limit", "0"],
        ["serve-tool-gateway", "--tools", str(tools), "--rate-limit", "0"],
        ["serve-audit", "--out", str(tmp_path / "audit.jsonl"), "--rate-limit", "0"],
    ]


@pytest.mark.parametrize("command", range(6))
def test_cli_rejects_bad_flags(tmp_path, capsys, command):
    argv = _bad_commands(tmp_path)[command]

    with pytest.raises(SystemExit) as exc:
        cli.main(argv)

    assert exc.value.code == 1
    assert "rate-limit" in capsys.readouterr().err


def test_console_cli_wires_rate_limit(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("adk_agent.console.run_console", lambda *a, **k: captured.update(k))

    cli.main(["console", "--agents", _agents_file(tmp_path), "--rate-limit", "5"])

    assert captured["rate_limit"].limit == 5
    assert captured["rate_limit"].window_seconds == 60.0
