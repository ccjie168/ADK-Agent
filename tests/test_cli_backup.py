"""SLICE-055: backup and restore CLI commands."""

from __future__ import annotations

import pytest

from adk_agent import cli


def _state(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "bot.json").write_text("{}", encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    audit.write_text('{"event":1}\n', encoding="utf-8")
    return registry, audit


def test_cli_backup(tmp_path, capsys):
    registry, audit = _state(tmp_path)
    archive = tmp_path / "backup.tar.gz"

    cli.main(
        [
            "backup",
            "--out",
            str(archive),
            "--registry",
            str(registry),
            "--audit",
            str(audit),
        ]
    )

    out = capsys.readouterr().out
    assert "wrote" in out
    assert "sha256:" in out
    assert archive.exists()


def test_cli_restore(tmp_path, capsys):
    registry, audit = _state(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    cli.main(
        [
            "backup",
            "--out",
            str(archive),
            "--registry",
            str(registry),
            "--audit",
            str(audit),
        ]
    )
    dest = tmp_path / "restored"

    cli.main(["restore", "--archive", str(archive), "--dest", str(dest)])

    assert "restored" in capsys.readouterr().out
    assert (dest / "registry" / "bot.json").exists()
    assert (dest / "audit" / "audit.jsonl").exists()


def test_cli_backup_requires_source(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["backup", "--out", str(tmp_path / "backup.tar.gz")])

    assert exc.value.code == 1
    assert "source" in capsys.readouterr().err


def test_cli_restore_refuses_nonempty(tmp_path, capsys):
    registry, audit = _state(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    cli.main(
        [
            "backup",
            "--out",
            str(archive),
            "--registry",
            str(registry),
            "--audit",
            str(audit),
        ]
    )
    dest = tmp_path / "restored"
    dest.mkdir()
    (dest / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        cli.main(["restore", "--archive", str(archive), "--dest", str(dest)])

    assert exc.value.code == 1
    assert "not empty" in capsys.readouterr().err
