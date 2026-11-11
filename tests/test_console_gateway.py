"""SLICE-017: the console routes model calls through the gateway."""

from __future__ import annotations

from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app
from adk_agent.models import build_model
from adk_agent.models.gateway_llm import GatewayLlm


def test_console_wraps_base_llm():
    agent = LlmAgent(
        name="probe",
        model=build_model("gemini:gemini-2.5-pro"),
        instruction="x",
    )

    build_console_app({"probe": agent}, auth_token="secret")

    assert isinstance(agent.model, GatewayLlm)


def test_console_leaves_string_model():
    agent = LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")

    build_console_app({"probe": agent}, auth_token="secret")

    assert agent.model == "gemini-2.5-pro"
