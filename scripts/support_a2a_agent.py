#!/usr/bin/env python3
"""Serve the support-demo plan as one ADK agent over A2A.

Load with ``serve-a2a --agent scripts/support_a2a_agent.py``. The plan is the
same one ``prove_support_demo.py`` runs: an unapproved answer step and a ticket
step that waits for a human decision in ``SUPPORT_APPROVALS_DIR``.
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from pathlib import Path
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

from adk_agent.approvals import FileApprovalInbox  # noqa: E402
from adk_agent.audit import AuditPipeline  # noqa: E402
from adk_agent.core import Invocation, Principal  # noqa: E402
from adk_agent.core.context import current_invocation  # noqa: E402
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


class SupportFlowAgent(BaseAgent):
    """Run the support plan and return its final text."""

    mock_url: str
    mock_token: str = DEFAULT_TOKEN
    approvals_dir: str = "support-approvals"
    audit_file: str = "support-audit.jsonl"
    wait_seconds: float = 120.0

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
        inbox = FileApprovalInbox(
            self.approvals_dir,
            poll_seconds=0.2,
            ttl_seconds=self.wait_seconds + 60,
        )
        executor = PlanExecutor(
            build_agents(self.mock_url, self.mock_token),
            policy=AgentGrantPolicyEngine(["support", "ticket_writer"]),
            audit=PipelineSink(AuditPipeline(self.audit_file)),
        )
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
            text = result.final_text
        yield Event(
            author=self.name,
            invocation_id=ctx.invocation_id,
            content=types.Content(role="model", parts=[types.Part(text=text)]),
        )


agent = SupportFlowAgent(
    name="support_flow",
    mock_url=_loopback_url(os.environ.get("SUPPORT_MOCK_URL", "http://127.0.0.1:8055")),
    mock_token=os.environ.get("SUPPORT_MOCK_TOKEN", DEFAULT_TOKEN),
    approvals_dir=os.environ.get("SUPPORT_APPROVALS_DIR", "support-approvals"),
    audit_file=os.environ.get("SUPPORT_AUDIT_FILE", "support-audit.jsonl"),
    wait_seconds=float(os.environ.get("SUPPORT_WAIT_SECONDS", "120")),
)
