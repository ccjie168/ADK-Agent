#!/usr/bin/env python3
"""Serve the support-demo plan as one ADK agent over A2A or MCP.

Load with ``serve-a2a --agent scripts/support_a2a_agent.py`` or
``serve --agent scripts/support_a2a_agent.py``. The plan is the same one
``prove_support_demo.py`` runs: an answer step and a ticket step that needs a
human decision in ``SUPPORT_APPROVALS_DIR``.

With ``SUPPORT_DEFER=1`` a pending approval returns an immediate
acknowledgement instead of blocking; a resumer in this process continues the
plan once the decision lands.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
for _path in (str(ROOT / "src"), str(SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from adk_agent.approval_resumer import ApprovalResumer  # noqa: E402
from adk_agent.approvals import ApprovalHistoryEntry, FileApprovalInbox  # noqa: E402
from adk_agent.audit import AuditPipeline  # noqa: E402
from adk_agent.core import Invocation, PlanPending, Principal  # noqa: E402
from adk_agent.core.context import current_invocation  # noqa: E402
from adk_agent.notify import WebhookNotifier  # noqa: E402
from adk_agent.orchestration import (  # noqa: E402
    AgentGrantPolicyEngine,
    ApprovalDenied,
    ApprovalTimeout,
    PlanExecutionError,
    PlanExecutor,
)
from support_demo_flow import (  # noqa: E402
    DEFAULT_TOKEN,
    PipelineSink,
    agent_ref,
    build_agents,
    build_plan,
)

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
logger = logging.getLogger(__name__)
_PENDING: dict[str, Invocation] = {}
_RESUMER_TASK: Any = None


def _loopback_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme != "http" or parts.hostname not in _LOOPBACK_HOSTS:
        raise ValueError("SUPPORT_MOCK_URL must be a loopback http URL")
    return value.rstrip("/")


def _user_text(ctx: InvocationContext) -> str:
    content = getattr(ctx, "user_content", None)
    for part in getattr(content, "parts", None) or ():
        text = getattr(part, "text", None)
        if isinstance(text, str) and text:
            return text
    return ""


def _build_notifier() -> WebhookNotifier | None:
    url = os.environ.get("SUPPORT_NOTIFY_WEBHOOK_URL")
    if not url:
        return None
    env_name = os.environ.get("SUPPORT_NOTIFY_SECRET_ENV", "")
    secret = os.environ.get(env_name, "") if env_name else ""
    if not secret:
        raise ValueError("SUPPORT_NOTIFY_WEBHOOK_URL needs SUPPORT_NOTIFY_SECRET_ENV")
    return WebhookNotifier(url, secret=secret)


class SupportFlowAgent(BaseAgent):
    """Run the support plan and return its final text or a deferral ack."""

    mock_url: str
    mock_token: str = DEFAULT_TOKEN
    approvals_dir: str = "support-approvals"
    audit_file: str = "support-audit.jsonl"
    wait_seconds: float = 120.0
    defer: bool = False
    notify_webhook_url: str | None = None
    notify_secret_env: str | None = None

    def _inbox(self) -> FileApprovalInbox:
        return FileApprovalInbox(
            self.approvals_dir,
            poll_seconds=0.2,
            ttl_seconds=self.wait_seconds + 60,
        )

    def _executor(self, notifier: Any) -> PlanExecutor:
        return PlanExecutor(
            build_agents(self.mock_url, self.mock_token),
            policy=AgentGrantPolicyEngine(["support", "ticket_writer"]),
            audit=PipelineSink(AuditPipeline(self.audit_file)),
            defer_approvals=self.defer,
            notifier=notifier,
        )

    def _notifier(self) -> WebhookNotifier | None:
        if not self.notify_webhook_url:
            return None
        secret = os.environ.get(self.notify_secret_env or "", "")
        if not secret:
            raise ValueError("notify webhook needs its secret environment variable")
        return WebhookNotifier(self.notify_webhook_url, secret=secret)

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        caller = current_invocation()
        deadline = datetime.now(timezone.utc) + timedelta(seconds=self.wait_seconds + 60)
        parent = Invocation(
            run_id=caller.run_id if caller else ctx.invocation_id,
            trace_id=caller.trace_id if caller else ctx.invocation_id,
            principal=(
                caller.principal
                if caller
                else Principal(tenant="local", subject="workbuddy", kind="service")
            ),
            agent_ref=caller.agent_ref if caller else agent_ref("support_flow"),
            input=_user_text(ctx),
            deadline=deadline,
        )
        inbox = self._inbox()
        executor = self._executor(self._notifier())
        try:
            result = await executor.run(
                build_plan(self.wait_seconds + 60),
                parent,
                approvals=inbox,  # type: ignore[arg-type]
            )
        except ApprovalDenied:
            text = "工单创建被拒绝，未执行。"
        except ApprovalTimeout:
            text = "工单创建等待审批超时，请稍后在控制台处理。"
        except PlanExecutionError:
            text = "工单创建失败，请查看审计记录。"
        else:
            if isinstance(result, PlanPending):
                _PENDING[result.request_id] = parent
                self._ensure_resumer(inbox)
                text = f"已提交，等待审批，request_id={result.request_id}"
            else:
                text = result.final_text
        yield Event(
            author=self.name,
            invocation_id=ctx.invocation_id,
            content=types.Content(role="model", parts=[types.Part(text=text)]),
        )

    def _ensure_resumer(self, inbox: FileApprovalInbox) -> None:
        global _RESUMER_TASK
        if _RESUMER_TASK is None or _RESUMER_TASK.done():
            resumer = ApprovalResumer(inbox, self._resume, poll_seconds=0.5)
            _RESUMER_TASK = asyncio.create_task(resumer.run_forever())

    async def _resume(self, entry: ApprovalHistoryEntry) -> None:
        parent = _PENDING.pop(entry.request.request_id, None)
        if parent is None:
            return
        fresh = parent.model_copy(
            update={
                "deadline": datetime.now(timezone.utc) + timedelta(seconds=self.wait_seconds + 60)
            }
        )
        try:
            await self._executor(self._notifier()).run(
                build_plan(self.wait_seconds + 60),
                fresh,
                approvals=self._inbox(),  # type: ignore[arg-type]
            )
        except (ApprovalDenied, ApprovalTimeout, PlanExecutionError):
            logger.warning("deferred support run did not finish", exc_info=True)


agent = SupportFlowAgent(
    name="support_flow",
    mock_url=_loopback_url(os.environ.get("SUPPORT_MOCK_URL", "http://127.0.0.1:8055")),
    mock_token=os.environ.get("SUPPORT_MOCK_TOKEN", DEFAULT_TOKEN),
    approvals_dir=os.environ.get("SUPPORT_APPROVALS_DIR", "support-approvals"),
    audit_file=os.environ.get("SUPPORT_AUDIT_FILE", "support-audit.jsonl"),
    wait_seconds=float(os.environ.get("SUPPORT_WAIT_SECONDS", "120")),
    defer=os.environ.get("SUPPORT_DEFER", "0") == "1",
    notify_webhook_url=os.environ.get("SUPPORT_NOTIFY_WEBHOOK_URL"),
    notify_secret_env=os.environ.get("SUPPORT_NOTIFY_SECRET_ENV"),
)
