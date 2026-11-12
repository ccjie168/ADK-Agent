"""SLICE-012: validate and publish CLI commands."""

from __future__ import annotations

import json

import pytest

from adk_agent import cli


def _manifest_data() -> dict:
    return {
        "id": "support-bot",
        "version": "1.0.0",
        "tenant": "team-a",
        "owner": "team-a",
        "description": "support",
        "model_policy": {"provider_allowlist": ["litellm"]},
        "tool_grants": [{"tool_id": "crm.read", "data_classes": ["internal"]}],
        "data_scopes": ["internal"],
        "exposure": "mcp",
    }


def _write(tmp_path, data: dict, name: str = "manifest.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_validate_ok(tmp_path, capsys):
    path = _write(tmp_path, _manifest_data())
    cli.main(["validate", str(path)])
    out = capsys.readouterr().out
    assert "team-a/support-bot@1.0.0" in out
    assert "sha256:" in out


def test_validate_rejects_unknown_field(tmp_path, capsys):
    data = _manifest_data()
    data["unknown"] = 1
    path = _write(tmp_path, data)
    with pytest.raises(SystemExit) as exc:
        cli.main(["validate", str(path)])
    assert exc.value.code == 1
    assert "invalid manifest" in capsys.readouterr().err


def test_publish_writes_registry(tmp_path, capsys):
    path = _write(tmp_path, _manifest_data())
    registry_dir = tmp_path / "registry"
    cli.main(["publish", str(path), "--registry", str(registry_dir)])
    out = capsys.readouterr().out
    assert "published team-a/support-bot@1.0.0" in out
    assert (registry_dir / "team-a" / "support-bot" / "1.0.0.json").is_file()


def test_publish_conflict_exits_one(tmp_path, capsys):
    registry_dir = tmp_path / "registry"
    first = _write(tmp_path, _manifest_data(), "first.json")
    cli.main(["publish", str(first), "--registry", str(registry_dir)])

    changed = _manifest_data()
    changed["description"] = "changed"
    second = _write(tmp_path, changed, "second.json")
    with pytest.raises(SystemExit) as exc:
        cli.main(["publish", str(second), "--registry", str(registry_dir)])
    assert exc.value.code == 1
    assert "publish failed" in capsys.readouterr().err
