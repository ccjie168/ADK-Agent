"""SLICE-128: publish requires a declared execution tier."""

from __future__ import annotations

import json

import pytest

from adk_agent import cli


def _manifest(tier: str | None = None) -> dict:
    data = {
        "id": "bot",
        "version": "1.0.0",
        "tenant": "acme",
        "owner": "acme",
        "model_policy": {"provider_allowlist": ["litellm"]},
    }
    if tier is not None:
        data["execution_tier"] = tier
    return data


def _publish(tmp_path, tier: str | None):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest(tier)), encoding="utf-8")
    cli.main(["publish", str(path), "--registry", str(tmp_path / "registry")])


def test_publish_defaults_to_sandboxed(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        _publish(tmp_path, None)

    assert exc.value.code == 1
    assert "sandbox" in capsys.readouterr().err
    assert not (tmp_path / "registry").exists()


def test_publish_refuses_sandboxed_without_a_backend(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        _publish(tmp_path, "sandboxed")

    assert exc.value.code == 1
    assert "sandbox" in capsys.readouterr().err
    assert not (tmp_path / "registry").exists()


def test_publish_in_process_writes_the_record(tmp_path):
    _publish(tmp_path, "in_process")

    record = tmp_path / "registry" / "acme" / "bot" / "1.0.0.json"
    assert record.is_file()
    assert json.loads(record.read_text(encoding="utf-8"))["manifest"]["execution_tier"] == (
        "in_process"
    )
