"""SLICE-280: console compose signing flags are all-or-none and validated early."""

from __future__ import annotations

import pytest

from adk_agent import cli


def _agents_file(tmp_path):
    path = tmp_path / "agents.py"
    path.write_text(
        "from google.adk.agents import LlmAgent\n"
        "agents = {'probe': LlmAgent(name='probe', model='gemini-2.5-pro', instruction='x')}\n",
        encoding="utf-8",
    )
    return path


def test_console_rejects_partial_compose_keys(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "console",
                "--agents",
                str(_agents_file(tmp_path)),
                "--allow-unauthenticated",
                "--compose-key",
                str(tmp_path / "compose.pem"),
                "--compose-key-id",
                "compose-1",
            ]
        )
    assert exc.value.code == 2
    assert "compose" in capsys.readouterr().err


def test_console_rejects_an_invalid_compose_key(tmp_path, capsys):
    bad = tmp_path / "bad.pem"
    bad.write_text("not a private key", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "console",
                "--agents",
                str(_agents_file(tmp_path)),
                "--allow-unauthenticated",
                "--compose-key",
                str(bad),
                "--compose-key-id",
                "compose-1",
                "--compose-builder-key",
                str(bad),
                "--compose-builder-key-id",
                "builder-1",
            ]
        )
    assert exc.value.code == 1
    assert "compose" in capsys.readouterr().err
