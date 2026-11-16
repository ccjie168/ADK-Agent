"""SLICE-120: central log sanitizer escaping CR and LF."""

from __future__ import annotations

import logging

from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app
from adk_agent.logsafe import install_log_sanitizer


def _messages(caplog, name: str) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == name]


def test_console_installs_sanitizer(caplog):
    agent = LlmAgent(name="probe", model="gemini-2.5-pro", description="probe", instruction="x")
    build_console_app({"probe": agent}, auth_token="secret")
    logger = logging.getLogger("slice120.console")
    with caplog.at_level(logging.INFO, logger="slice120.console"):
        logger.info("built\nconsole")
    assert _messages(caplog, "slice120.console") == ["built\\nconsole"]


def test_message_newlines_are_escaped(caplog):
    install_log_sanitizer()
    logger = logging.getLogger("slice120.message")
    with caplog.at_level(logging.INFO, logger="slice120.message"):
        logger.info("line one\nline two")
    assert _messages(caplog, "slice120.message") == ["line one\\nline two"]


def test_argument_newlines_are_escaped(caplog):
    install_log_sanitizer()
    logger = logging.getLogger("slice120.args")
    with caplog.at_level(logging.INFO, logger="slice120.args"):
        logger.info("target=%s", "a\r\nb")
    assert _messages(caplog, "slice120.args") == ["target=a\\r\\nb"]


def test_mapping_arguments_are_escaped(caplog):
    install_log_sanitizer()
    logger = logging.getLogger("slice120.mapping")
    with caplog.at_level(logging.INFO, logger="slice120.mapping"):
        logger.info("%(target)s", {"target": "x\ny"})
    assert _messages(caplog, "slice120.mapping") == ["x\\ny"]


def test_normal_messages_are_unchanged(caplog):
    install_log_sanitizer()
    logger = logging.getLogger("slice120.normal")
    with caplog.at_level(logging.INFO, logger="slice120.normal"):
        logger.info("plain message")
        logger.info("count=%d", 7)
    assert _messages(caplog, "slice120.normal") == ["plain message", "count=7"]


def test_install_is_idempotent(caplog):
    install_log_sanitizer()
    install_log_sanitizer()
    logger = logging.getLogger("slice120.idempotent")
    with caplog.at_level(logging.INFO, logger="slice120.idempotent"):
        logger.info("a\nb")
    assert _messages(caplog, "slice120.idempotent") == ["a\\nb"]
