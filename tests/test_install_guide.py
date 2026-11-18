"""SLICE-144: the install and usage manual references real commands and flags."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from adk_agent import cli

GUIDE = Path(__file__).resolve().parent.parent / "docs" / "guides" / "install-and-use.md"


def _guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


def _invocations() -> list[tuple[list[str], list[str]]]:
    text = _guide().replace("\\\n", " ")
    found: list[tuple[list[str], list[str]]] = []
    for line in text.splitlines():
        match = re.search(r"-m adk_agent ([a-z0-9-]+)(.*)", line)
        if match is None:
            continue
        command = [match.group(1)]
        rest = match.group(2)
        tokens = rest.split()
        if tokens and re.fullmatch(r"[a-z][a-z0-9-]*", tokens[0]):
            command.append(tokens.pop(0))
        flags = re.findall(r"--[a-z][a-z0-9-]*", " ".join(tokens))
        found.append((command, flags))
    return found


def test_guide_covers_the_required_sections():
    text = _guide()

    for heading in (
        "# 安装与使用手册",
        "## 从源码安装",
        "## 配置模型",
        "## 控制台",
        "## 发布与加载",
        "## 凭据",
        "## Docker",
        "## 升级与回滚",
        "## 排障",
    ):
        assert heading in text


def test_every_guide_command_is_a_real_subcommand():
    invocations = _invocations()
    first_tokens = {command[0] for command, _ in invocations}

    assert {"console", "credentials", "publish", "serve"} <= first_tokens
    for command, _ in invocations:
        with pytest.raises(SystemExit) as exc:
            cli.main([*command, "--help"])
        assert exc.value.code == 0, command


def test_every_guide_flag_is_accepted_by_its_command(capsys):
    invocations = _invocations()

    assert any("compose" in command for command, _ in invocations)
    for command, flags in invocations:
        if not flags:
            continue
        capsys.readouterr()
        with pytest.raises(SystemExit) as exc:
            cli.main([*command, "--help"])
        assert exc.value.code == 0, command
        help_text = capsys.readouterr().out
        for flag in flags:
            pattern = rf"(?<![\w-]){re.escape(flag)}(?![\w-])"
            assert re.search(pattern, help_text), f"{flag} is not accepted by {' '.join(command)}"


def test_guide_commands_carry_the_required_flags():
    invocations = {tuple(command): flags for command, flags in _invocations()}

    compose = set(invocations[("compose",)])
    assert {
        "--template",
        "--tenant",
        "--id",
        "--version",
        "--instruction",
        "--key",
        "--key-id",
        "--builder-key",
        "--builder-key-id",
        "--artifact-dir",
        "--registry",
    } <= compose

    publish = set(invocations[("publish",)])
    assert {
        "--key",
        "--key-id",
        "--builder-key",
        "--builder-key-id",
        "--builder-keys",
        "--artifact-dir",
        "--registry",
    } <= publish


def test_guide_documents_required_auth_and_credential_environment():
    text = _guide()

    assert "ADK_SECRET_KEKS" in text
    assert "ADK_MCP_AUTH_TOKEN" in text
    assert "ADK_CONSOLE_TOKEN" in text
    assert "credentials rewrap" in text
    assert "TLS" in text
    assert "--builder-keys" in text
