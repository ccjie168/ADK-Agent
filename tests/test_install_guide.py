"""SLICE-144: the install and usage manual references real commands and sections."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from adk_agent import cli

GUIDE = Path(__file__).resolve().parent.parent / "docs" / "guides" / "install-and-use.md"


def _guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


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
    commands = sorted(set(re.findall(r"-m adk_agent ([a-z0-9-]+)", _guide())))

    assert "serve" in commands
    assert "console" in commands
    assert "docs" not in commands
    for command in commands:
        with pytest.raises(SystemExit) as exc:
            cli.main([command, "--help"])
        assert exc.value.code == 0, command


def test_guide_names_the_credential_environment():
    text = _guide()

    assert "ADK_SECRET_KEKS" in text
    assert "credentials rewrap" in text
    assert "TLS" in text
