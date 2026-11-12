#!/usr/bin/env python3
"""Write docs/contracts/*.schema.json from the core models."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adk_agent.config import FrameworkConfig  # noqa: E402
from adk_agent.core import (  # noqa: E402
    AccessPolicy,
    AgentManifest,
    AgentRef,
    ApprovalDecision,
    ApprovalRequest,
    AuditEvent,
    AuditRecord,
    CanaryPolicy,
    EvalReport,
    EvalSuiteSpec,
    Invocation,
    ModelGatewayRequest,
    OrchestrationPlan,
    Principal,
    ProgressEvent,
    QuotaConfig,
    SupervisorDecision,
    ToolGatewayRequest,
)
from adk_agent.identity.oidc import OidcConfig  # noqa: E402

CONTRACTS = ROOT / "docs" / "contracts"

SCHEMAS: dict[str, type[BaseModel]] = {
    "manifest.schema.json": AgentManifest,
    "agent_ref.schema.json": AgentRef,
    "principal.schema.json": Principal,
    "invocation.schema.json": Invocation,
    "audit_event.schema.json": AuditEvent,
    "audit_record.schema.json": AuditRecord,
    "approval_request.schema.json": ApprovalRequest,
    "approval_decision.schema.json": ApprovalDecision,
    "framework_config.schema.json": FrameworkConfig,
    "orchestration_plan.schema.json": OrchestrationPlan,
    "supervisor_decision.schema.json": SupervisorDecision,
    "access_policy.schema.json": AccessPolicy,
    "eval_suite_spec.schema.json": EvalSuiteSpec,
    "eval_report.schema.json": EvalReport,
    "canary_policy.schema.json": CanaryPolicy,
    "model_gateway_request.schema.json": ModelGatewayRequest,
    "tool_gateway_request.schema.json": ToolGatewayRequest,
    "progress_event.schema.json": ProgressEvent,
    "quota_config.schema.json": QuotaConfig,
    "oidc_config.schema.json": OidcConfig,
}


def render() -> dict[str, str]:
    return {
        name: json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
        for name, model in SCHEMAS.items()
    }


def write() -> None:
    CONTRACTS.mkdir(parents=True, exist_ok=True)
    for name, text in render().items():
        (CONTRACTS / name).write_text(text, encoding="utf-8")
        print(f"wrote {CONTRACTS / name}")


if __name__ == "__main__":
    write()
