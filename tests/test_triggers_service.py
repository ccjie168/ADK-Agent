"""SLICE-125: the webhook trigger execution service."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent
from google.adk.sessions import InMemorySessionService

from adk_agent.audit import ListAuditSink
from adk_agent.audit.hashing import hash_text
from adk_agent.core import (
    AgentArtifact,
    AgentLifecycle,
    AgentManifest,
    AgentTrigger,
    QuotaConfig,
    QuotaPolicy,
    ToolGrant,
    TriggerFire,
    hash_webhook_token,
)
from adk_agent.registry import FileTriggerFireStore
from adk_agent.registry.manifest import published_from
from adk_agent.runtime.quota import InMemoryQuotaManager
from adk_agent.triggers_service import build_triggers_app

_TOKEN = "webhook-token-0123456789"
_OTHER_DIGEST = "sha256:" + "b" * 64
AUTH = {"Authorization": f"Bearer {_TOKEN}"}


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


class FakeTriggerStore:
    def __init__(self, triggers: list[AgentTrigger]) -> None:
        self._triggers = {(item.tenant, item.trigger_id): item for item in triggers}

    async def get(self, tenant: str, trigger_id: str) -> AgentTrigger | None:
        return self._triggers.get((tenant, trigger_id))


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


class FakeLifecycle:
    def __init__(self, status: str) -> None:
        self.status = status

    async def get(self, tenant: str, agent_id: str, version: str) -> AgentLifecycle:
        return AgentLifecycle(status=self.status)


def _published(*, grants: list[ToolGrant] | None = None):
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


def _webhook(
    *,
    trigger_id: str = "nightly",
    digest: str = _DIGEST,
    input_text: str = "Summarize yesterday.",
    enabled: bool = True,
) -> AgentTrigger:
    return AgentTrigger(
        trigger_id=trigger_id,
        tenant="acme",
        agent_id="assistant",
        version="1.0.0",
        digest=digest,
        kind="webhook",
        webhook_token_hash=hash_webhook_token(_TOKEN),
        input=input_text,
        enabled=enabled,
        created_by="admin",
        created_at=datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc),
    )


def _schedule(trigger_id: str = "scheduled") -> AgentTrigger:
    return AgentTrigger(
        trigger_id=trigger_id,
        tenant="acme",
        agent_id="assistant",
        version="1.0.0",
        digest=_DIGEST,
        kind="schedule",
        every_seconds=3600,
        created_by="admin",
        created_at=datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc),
    )


def _agent() -> LlmAgent:
    return LlmAgent(name="assistant", model="gemini-2.5-pro", instruction="x")


def _client(
    triggers: list[AgentTrigger],
    *,
    published=None,
    registry=None,
    lifecycle=None,
    tool_grants=None,
    audit=None,
    quota=None,
    quota_config=None,
    fire_store=None,
):
    runner = FakeRunner()
    trust = FakeTrust()
    loader = FakeLoader(_agent())
    app = build_triggers_app(
        triggers=FakeTriggerStore(triggers),
        registry=registry or FakeRegistry(published or _PUBLISHED),
        artifact_store=object(),
        trust=trust,
        loader=loader,
        lifecycle=lifecycle,
        tool_grants=tool_grants,
        audit=audit,
        quota=quota,
        quota_config=quota_config,
        session_service=InMemorySessionService(),
        runner_factory=lambda agent: runner,
        fire_store=fire_store,
    )
    return TestClient(app), runner, trust, loader


def _fire(client: TestClient, *, headers=None, json=None):
    return client.post(
        "/v1/tenants/acme/triggers/nightly/fire",
        headers={**AUTH, **(headers or {})},
        json=json,
    )


def test_fire_runs_the_pinned_agent():
    audit = ListAuditSink()
    client, runner, trust, loader = _client([_webhook()], audit=audit)

    with client:
        response = _fire(
            client,
            headers={"X-Trace-Id": "trace-1"},
            json={"input": "hello"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["text"] == "hi there"
    assert body["duplicate"] is False
    assert body["trace_id"] == "trace-1"
    assert body["run_id"]

    assert runner.calls == 1
    assert len(trust.verified) == 1
    assert len(loader.loaded) == 1

    events = audit.recent(20)
    actions = [event.action for event in events]
    assert "agent.run" in actions
    assert "trigger.fire" in actions
    fired = next(event for event in events if event.action == "trigger.fire")
    assert fired.status == "ok"
    assert fired.args_hash == hash_text("hello")
    assert fired.result_hash == hash_text("hi there")
    assert fired.principal.subject == "trigger:nightly"
    assert fired.target == "acme/nightly"
    assert fired.run_id == body["run_id"]
    assert fired.trace_id == "trace-1"


def test_wrong_token_is_unauthorized():
    audit = ListAuditSink()
    client, runner, _, _ = _client([_webhook()], audit=audit)

    with client:
        response = client.post(
            "/v1/tenants/acme/triggers/nightly/fire",
            headers={"Authorization": "Bearer wrong-token"},
            json={"input": "hello"},
        )

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}
    assert runner.calls == 0
    assert audit.recent(10) == []


def test_disabled_and_schedule_triggers_are_rejected():
    client, runner, _, _ = _client(
        [_webhook(trigger_id="nightly"), _webhook(trigger_id="paused", enabled=False), _schedule()]
    )

    with client:
        disabled = client.post(
            "/v1/tenants/acme/triggers/paused/fire", headers=AUTH, json={"input": "hi"}
        )
        scheduled = client.post(
            "/v1/tenants/acme/triggers/scheduled/fire", headers=AUTH, json={"input": "hi"}
        )

    assert disabled.status_code == 409
    assert disabled.json() == {"error": "trigger_disabled"}
    assert scheduled.status_code == 409
    assert scheduled.json() == {"error": "trigger_kind_mismatch"}
    assert runner.calls == 0


def test_digest_and_lifecycle_are_enforced():
    mismatch, runner, _, _ = _client([_webhook(digest=_OTHER_DIGEST)])
    with mismatch:
        response = _fire(mismatch, json={"input": "hello"})

    assert response.status_code == 409
    assert response.json() == {"error": "digest_mismatch"}
    assert runner.calls == 0

    retired, runner, _, _ = _client([_webhook()], lifecycle=FakeLifecycle("retired"))
    with retired:
        response = _fire(retired, json={"input": "hello"})

    assert response.status_code == 409
    assert response.json() == {"error": "version_retired"}
    assert runner.calls == 0


def test_fire_uses_the_real_registry_digest(tmp_path):
    from adk_agent.registry import FileAgentRegistry

    registry = FileAgentRegistry(tmp_path / "registry")
    asyncio.run(registry.publish(_PUBLISHED))
    trigger = _webhook(digest=f"sha256:{_PUBLISHED.digest}")
    client, runner, _, _ = _client([trigger], registry=registry)

    with client:
        response = _fire(client, json={"input": "hello"})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert runner.calls == 1


def test_approval_required_is_refused():
    audit = ListAuditSink()
    grants = [ToolGrant(tool_id="payments", requires_approval=True)]
    published = _published(grants=grants)
    client, runner, _, loader = _client(
        [_webhook(digest=f"sha256:{published.digest}")],
        published=published,
        audit=audit,
    )

    with client:
        response = _fire(client, json={"input": "hello"})

    assert response.status_code == 409
    assert response.json() == {"error": "approval_required"}
    assert runner.calls == 0
    assert loader.loaded == []

    [fired] = [event for event in audit.recent(10) if event.action == "trigger.fire"]
    assert fired.status == "denied"
    assert fired.error_code == "approval_required"


def test_idempotency_key_runs_once(tmp_path):
    audit = ListAuditSink()
    fire_store = FileTriggerFireStore(tmp_path)
    client, runner, _, _ = _client([_webhook()], audit=audit, fire_store=fire_store)

    with client:
        first = _fire(client, headers={"Idempotency-Key": "key-1"}, json={"input": "hello"})
        second = _fire(client, headers={"Idempotency-Key": "key-1"}, json={"input": "hello"})

    assert first.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["text"] == ""
    assert second.json()["run_id"] == first.json()["run_id"]
    assert second.json()["trace_id"] == first.json()["trace_id"]
    assert second.json()["status"] == "ok"
    assert runner.calls == 1

    stored = asyncio.run(fire_store.get("acme", "nightly", "key-1"))
    assert stored is not None
    assert stored.status == "ok"


def test_in_progress_idempotency_key_is_rejected(tmp_path):
    fire_store = FileTriggerFireStore(tmp_path)
    asyncio.run(
        fire_store.claim(
            TriggerFire(
                tenant="acme",
                trigger_id="nightly",
                idempotency_key="key-running",
                run_id="run-running",
                trace_id="trace-running",
                status="running",
                created_at=datetime.now(timezone.utc),
            )
        )
    )
    client, runner, _, _ = _client([_webhook()], fire_store=fire_store)

    with client:
        response = _fire(client, headers={"Idempotency-Key": "key-running"})

    assert response.status_code == 409
    assert response.json() == {"error": "fire_in_progress"}
    assert runner.calls == 0


def test_quota_exceeded():
    audit = ListAuditSink()
    quota = InMemoryQuotaManager()
    config = QuotaConfig(tenants={"acme": QuotaPolicy(max_runs=1, window_seconds=60)})
    client, runner, _, _ = _client([_webhook()], audit=audit, quota=quota, quota_config=config)

    with client:
        first = _fire(client, json={"input": "hello"})
        second = _fire(client, json={"input": "hello"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json() == {"error": "quota_exceeded"}
    assert runner.calls == 1

    fired = [event for event in audit.recent(20) if event.action == "trigger.fire"]
    assert any(event.status == "denied" and event.error_code == "quota_exceeded" for event in fired)
