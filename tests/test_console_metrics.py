"""SLICE-047: the console exposes in-process metrics."""

from __future__ import annotations

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app
from adk_agent.core import QuotaConfig, QuotaPolicy
from adk_agent.metrics import MetricsRegistry
from adk_agent.runtime.quota import InMemoryQuotaManager

AUTH = {"Authorization": "Bearer secret"}


class FakePart:
    def __init__(self, text: str) -> None:
        self.text = text
        self.thought = False
        self.function_call = None
        self.function_response = None


class FakeContent:
    def __init__(self, parts: list[FakePart]) -> None:
        self.parts = parts


class FakeEvent:
    def __init__(self, text: str) -> None:
        self.author = "probe"
        self.content = FakeContent([FakePart(text)])

    def is_final_response(self) -> bool:
        return True


def _agents() -> dict[str, LlmAgent]:
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def _patch_runner(monkeypatch) -> None:
    async def run_async(self, **kwargs):
        yield FakeEvent("hi there")

    monkeypatch.setattr("google.adk.runners.Runner.run_async", run_async)


def _app(metrics: MetricsRegistry, **kwargs) -> TestClient:
    return TestClient(build_console_app(_agents(), auth_token="secret", metrics=metrics, **kwargs))


def _chat(client: TestClient):
    return client.post("/api/chat", json={"agent": "probe", "message": "hi"}, headers=AUTH)


def test_metrics_require_token():
    with TestClient(build_console_app(_agents(), auth_token="secret")) as client:
        assert client.get("/metrics").status_code == 401


def test_metrics_count_runs(monkeypatch):
    _patch_runner(monkeypatch)
    metrics = MetricsRegistry()
    with _app(metrics) as client:
        assert _chat(client).status_code == 200
        response = client.get("/metrics", headers=AUTH)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    text = response.text
    assert (
        'adk_agent_runs_total{agent="probe",source="console",status="ok",tenant="local"} 1' in text
    )
    assert 'adk_agent_run_duration_seconds_count{agent="probe",tenant="local"} 1' in text


def test_metrics_count_quota_denials(monkeypatch):
    _patch_runner(monkeypatch)
    metrics = MetricsRegistry()
    quota = InMemoryQuotaManager()
    config = QuotaConfig(tenants={"local": QuotaPolicy(max_runs=1, window_seconds=60)})
    with _app(metrics, quota=quota, quota_config=config) as client:
        assert _chat(client).status_code == 200
        assert _chat(client).status_code == 429
        response = client.get("/metrics", headers=AUTH)

    text = response.text
    assert (
        'adk_agent_runs_total{agent="probe",source="console",status="denied",tenant="local"} 1'
        in text
    )
    assert 'adk_agent_quota_denials_total{limit="max_runs",tenant="local"} 1' in text
