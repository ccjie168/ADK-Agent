"""SLICE-127: the schedule tick, retries, and scheduler lifecycle."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent
from google.adk.sessions import InMemorySessionService

from adk_agent.core import (
    AgentArtifact,
    AgentManifest,
    AgentTrigger,
    hash_webhook_token,
)
from adk_agent.registry import FileTriggerFireStore
from adk_agent.registry.manifest import published_from
from adk_agent.triggers_service import (
    TriggerExecution,
    build_triggers_app,
    run_schedule_tick,
)

_TOKEN = "webhook-token-0123456789"
AUTH = {"Authorization": f"Bearer {_TOKEN}"}
_NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


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
        self.author = "assistant"
        self.content = FakeContent([FakePart(text)])

    def is_final_response(self) -> bool:
        return True


class FakeRunner:
    def __init__(self, text: str = "hi there") -> None:
        self.text = text
        self.calls = 0

    async def run_async(self, **kwargs):
        self.calls += 1
        yield FakeEvent(self.text)


class RaisingRunner:
    def __init__(self) -> None:
        self.calls = 0

    async def run_async(self, **kwargs):
        self.calls += 1
        raise RuntimeError("boom")
        yield  # pragma: no cover


class FakeTriggerStore:
    def __init__(self, triggers: list[AgentTrigger]) -> None:
        self._triggers = {(item.tenant, item.trigger_id): item for item in triggers}

    async def get(self, tenant: str, trigger_id: str) -> AgentTrigger | None:
        return self._triggers.get((tenant, trigger_id))

    async def list(self, tenant: str) -> list[AgentTrigger]:
        return [item for item in self._triggers.values() if item.tenant == tenant]

    async def list_all(self) -> list[AgentTrigger]:
        return list(self._triggers.values())


class FakeRegistry:
    def __init__(self, published) -> None:
        self.published = published

    async def get(self, ref, tenant: str):
        return self.published if self.published.digest == ref.digest else None

    async def list(self, tenant: str):
        return [self.published]


class FakeTrust:
    def __init__(self) -> None:
        self.verified: list[AgentArtifact] = []

    def verify(self, artifact: AgentArtifact) -> None:
        self.verified.append(artifact)


class FakeLoader:
    def __init__(self, agent: LlmAgent) -> None:
        self.agent = agent
        self.loaded: list[AgentArtifact] = []

    async def load(self, artifact: AgentArtifact, store) -> LlmAgent:
        self.loaded.append(artifact)
        return self.agent


class FlakyLoader(FakeLoader):
    def __init__(self, agent: LlmAgent, failures: int) -> None:
        super().__init__(agent)
        self.failures = failures
        self.calls = 0

    async def load(self, artifact: AgentArtifact, store) -> LlmAgent:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("artifact load failed")
        return await super().load(artifact, store)


def _published(*, grants=None):
    manifest = AgentManifest(
        id="assistant",
        version="1.0.0",
        tenant="acme",
        owner="acme",
        model_policy={"provider_allowlist": ["litellm"]},
        tool_grants=grants or [],
    )
    artifact = AgentArtifact(digest="sha256:" + "d" * 64, size=1)
    return published_from(manifest, artifact=artifact)


_PUBLISHED = _published()
_DIGEST = f"sha256:{_PUBLISHED.digest}"


def _schedule(
    trigger_id: str = "scheduled",
    *,
    every_seconds: int = 3600,
    enabled: bool = True,
) -> AgentTrigger:
    return AgentTrigger(
        trigger_id=trigger_id,
        tenant="acme",
        agent_id="assistant",
        version="1.0.0",
        digest=_DIGEST,
        kind="schedule",
        every_seconds=every_seconds,
        input="Summarize yesterday.",
        enabled=enabled,
        created_by="admin",
        created_at=datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc),
    )


def _webhook(trigger_id: str = "nightly") -> AgentTrigger:
    return AgentTrigger(
        trigger_id=trigger_id,
        tenant="acme",
        agent_id="assistant",
        version="1.0.0",
        digest=_DIGEST,
        kind="webhook",
        webhook_token_hash=hash_webhook_token(_TOKEN),
        input="Summarize yesterday.",
        created_by="admin",
        created_at=datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc),
    )


def _agent() -> LlmAgent:
    return LlmAgent(name="assistant", model="gemini-2.5-pro", instruction="x")


def _app(
    *,
    triggers: list[AgentTrigger],
    loader,
    runner=None,
    fire_store=None,
    trigger_attempts: int = 3,
    scheduler: bool = False,
    schedule_tick: float = 15.0,
):
    runner = runner or FakeRunner()
    trust = FakeTrust()
    app = build_triggers_app(
        triggers=FakeTriggerStore(triggers),
        registry=FakeRegistry(_PUBLISHED),
        artifact_store=object(),
        trust=trust,
        loader=loader,
        session_service=InMemorySessionService(),
        runner_factory=lambda agent: runner,
        fire_store=fire_store,
        trigger_attempts=trigger_attempts,
        scheduler=scheduler,
        schedule_tick=schedule_tick,
    )
    return app, runner, trust, loader


def _fire(client: TestClient, *, headers=None):
    return client.post(
        "/v1/tenants/acme/triggers/nightly/fire",
        headers={**AUTH, **(headers or {})},
        json={"input": "hello"},
    )


def test_slot_runs_once(tmp_path):
    calls: list[str] = []

    async def execute(trigger, input_text, *, fire, run_id, trace_id, attempts):
        calls.append(trigger.trigger_id)
        return TriggerExecution("ok", None, run_id, trace_id, "done")

    store = FakeTriggerStore([_schedule()])
    fire_store = FileTriggerFireStore(tmp_path)

    first = asyncio.run(
        run_schedule_tick(
            triggers=store,
            fire_store=fire_store,
            execute=execute,
            now=_NOW,
            attempts=3,
        )
    )
    repeated = asyncio.run(
        run_schedule_tick(
            triggers=store,
            fire_store=fire_store,
            execute=execute,
            now=_NOW,
            attempts=3,
        )
    )
    later = asyncio.run(
        run_schedule_tick(
            triggers=store,
            fire_store=fire_store,
            execute=execute,
            now=_NOW + timedelta(hours=1),
            attempts=3,
        )
    )

    assert len(first) == 1
    assert repeated == []
    assert len(later) == 1
    assert calls == ["scheduled", "scheduled"]


def test_disabled_and_webhook_triggers_are_skipped(tmp_path):
    calls: list[str] = []

    async def execute(trigger, input_text, *, fire, run_id, trace_id, attempts):
        calls.append(trigger.trigger_id)
        return TriggerExecution("ok", None, run_id, trace_id, "done")

    store = FakeTriggerStore([_schedule("due"), _schedule("off", enabled=False), _webhook("hook")])

    asyncio.run(
        run_schedule_tick(
            triggers=store,
            fire_store=FileTriggerFireStore(tmp_path),
            execute=execute,
            now=_NOW,
            attempts=3,
        )
    )

    assert calls == ["due"]


def test_slot_has_one_winner(tmp_path):
    calls = 0

    async def execute(trigger, input_text, *, fire, run_id, trace_id, attempts):
        nonlocal calls
        calls += 1
        return TriggerExecution("ok", None, run_id, trace_id, "done")

    store = FakeTriggerStore([_schedule()])
    fire_store = FileTriggerFireStore(tmp_path)

    async def run_both():
        return await asyncio.gather(
            run_schedule_tick(
                triggers=store,
                fire_store=fire_store,
                execute=execute,
                now=_NOW,
                attempts=3,
            ),
            run_schedule_tick(
                triggers=store,
                fire_store=fire_store,
                execute=execute,
                now=_NOW,
                attempts=3,
            ),
        )

    asyncio.run(run_both())

    assert calls == 1


def test_pre_run_failures_are_retried(tmp_path):
    loader = FlakyLoader(_agent(), failures=2)
    app, runner, _, _ = _app(
        triggers=[_webhook()],
        loader=loader,
        trigger_attempts=3,
    )

    with TestClient(app) as client:
        response = _fire(client)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert loader.calls == 3
    assert runner.calls == 1

    fire_store = FileTriggerFireStore(tmp_path)
    loader = FlakyLoader(_agent(), failures=99)
    app, runner, _, _ = _app(
        triggers=[_webhook()],
        loader=loader,
        fire_store=fire_store,
        trigger_attempts=3,
    )

    with TestClient(app) as client:
        response = _fire(client, headers={"Idempotency-Key": "key-load"})

    assert response.status_code == 502
    assert response.json() == {"error": "agent_load_failed"}
    assert loader.calls == 3
    assert runner.calls == 0

    stored = asyncio.run(fire_store.get("acme", "nightly", "key-load"))
    assert stored is not None
    assert stored.status == "error"
    assert stored.error_code == "agent_load_failed"


def test_agent_failures_are_not_retried():
    loader = FakeLoader(_agent())
    runner = RaisingRunner()
    app, _, _, _ = _app(triggers=[_webhook()], loader=loader, runner=runner)

    with TestClient(app) as client:
        response = _fire(client)

    assert response.status_code == 500
    assert response.json() == {"error": "run_failed"}
    assert runner.calls == 1


def test_scheduler_stops_on_shutdown(tmp_path):
    app, _, _, _ = _app(
        triggers=[],
        loader=FakeLoader(_agent()),
        fire_store=FileTriggerFireStore(tmp_path),
        scheduler=True,
        schedule_tick=5.0,
    )

    with TestClient(app):
        task = app.state.scheduler_task
        assert not task.done()

    assert task.done()
    assert task.cancelled()
