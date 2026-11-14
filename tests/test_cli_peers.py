"""SLICE-091: the peers CLI reads and writes the same stores as the console."""

from __future__ import annotations

import json

import pytest

from adk_agent import cli


def _register(root: str) -> None:
    cli.main(
        [
            "peers",
            "register",
            "--peer-dir",
            root,
            "--id",
            "peer-a",
            "--tenant",
            "acme",
            "--subject",
            "sub-a",
        ]
    )


def _stdout(capsys) -> str:
    return capsys.readouterr().out


def test_cli_file_flow(tmp_path, capsys):
    root = str(tmp_path / "peer-state")

    cli.main(
        [
            "peers",
            "register",
            "--peer-dir",
            root,
            "--id",
            "peer-a",
            "--tenant",
            "acme",
            "--roles",
            "ops,reader",
        ]
    )
    peer = json.loads(_stdout(capsys))
    assert peer["peer_id"] == "peer-a"
    assert peer["tenant"] == "acme"
    assert peer["subject"] == "peer-a"
    assert peer["roles"] == ["ops", "reader"]
    assert peer["enabled"] is True

    cli.main(["peers", "list", "--peer-dir", root, "--tenant", "acme"])
    assert json.loads(_stdout(capsys)) == [{"peer": peer, "grants": []}]

    cli.main(
        [
            "peers",
            "grant",
            "--peer-dir",
            root,
            "--id",
            "peer-a",
            "--agent",
            "bot",
            "--actions",
            "read,invoke",
        ]
    )
    grant = json.loads(_stdout(capsys))
    assert grant == {
        "peer_id": "peer-a",
        "tenant": "acme",
        "agent_id": "bot",
        "actions": ["read", "invoke"],
    }

    cli.main(["peers", "list", "--peer-dir", root])
    [listed] = json.loads(_stdout(capsys))
    assert listed["grants"] == [grant]

    cli.main(["peers", "disable", "--peer-dir", root, "--id", "peer-a"])
    disabled = json.loads(_stdout(capsys))
    assert disabled["enabled"] is False

    cli.main(["peers", "revoke", "--peer-dir", root, "--id", "peer-a", "--agent", "bot"])
    assert json.loads(_stdout(capsys)) == {"revoked": True}

    cli.main(["peers", "list", "--peer-dir", root])
    [listed] = json.loads(_stdout(capsys))
    assert listed["grants"] == []


def test_cli_revoke_missing(tmp_path, capsys):
    root = str(tmp_path / "peer-state")
    _register(root)
    capsys.readouterr()

    cli.main(["peers", "revoke", "--peer-dir", root, "--id", "peer-a", "--agent", "bot"])

    assert json.loads(_stdout(capsys)) == {"revoked": False}


def test_cli_bad_action_exits(tmp_path, capsys):
    root = str(tmp_path / "peer-state")
    _register(root)

    with pytest.raises(SystemExit) as unknown:
        cli.main(
            [
                "peers",
                "grant",
                "--peer-dir",
                root,
                "--id",
                "peer-a",
                "--agent",
                "bot",
                "--actions",
                "read,write",
            ]
        )
    assert unknown.value.code == 1
    assert "action" in capsys.readouterr().err

    with pytest.raises(SystemExit) as empty:
        cli.main(
            [
                "peers",
                "grant",
                "--peer-dir",
                root,
                "--id",
                "peer-a",
                "--agent",
                "bot",
                "--actions",
                "",
            ]
        )
    assert empty.value.code == 1


def test_cli_unknown_peer_exits(tmp_path, capsys):
    root = str(tmp_path / "peer-state")

    with pytest.raises(SystemExit) as exc:
        cli.main(["peers", "disable", "--peer-dir", root, "--id", "missing"])

    assert exc.value.code == 1
    assert "unknown peer" in capsys.readouterr().err


def test_cli_tenant_change_exits(tmp_path, capsys):
    root = str(tmp_path / "peer-state")
    _register(root)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "peers",
                "register",
                "--peer-dir",
                root,
                "--id",
                "peer-a",
                "--tenant",
                "other",
            ]
        )

    assert exc.value.code == 1
    assert "tenant" in capsys.readouterr().err


def test_cli_store_selector(tmp_path, capsys):
    with pytest.raises(SystemExit) as missing:
        cli.main(["peers", "list"])
    assert missing.value.code == 1
    assert "set exactly one of --peer-dir or --peer-db" in capsys.readouterr().err

    with pytest.raises(SystemExit) as both:
        cli.main(["peers", "list", "--peer-dir", str(tmp_path), "--peer-db", "postgresql://x"])
    assert both.value.code == 1


def test_cli_store_error_exits(tmp_path, capsys):
    root = tmp_path / "peer-state"
    (root / "peers").mkdir(parents=True)
    (root / "peers" / "broken.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        cli.main(["peers", "list", "--peer-dir", str(root)])

    assert exc.value.code == 1
    assert "peers failed" in capsys.readouterr().err
