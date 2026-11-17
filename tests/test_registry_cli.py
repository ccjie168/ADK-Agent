"""SLICE-012: validate and publish CLI commands."""

from __future__ import annotations

import importlib.util
import json

import pytest

from adk_agent import cli

_HAS_CRYPTO = importlib.util.find_spec("cryptography") is not None
needs_crypto = pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography is not installed")


def _manifest_data() -> dict:
    return {
        "id": "support-bot",
        "version": "1.0.0",
        "tenant": "team-a",
        "owner": "team-a",
        "description": "support",
        "execution_tier": "in_process",
        "model_policy": {"provider_allowlist": ["litellm"]},
        "tool_grants": [{"tool_id": "crm.read", "data_classes": ["internal"]}],
        "data_scopes": ["internal"],
        "exposure": "mcp",
    }


def _keys(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    path = tmp_path / "key.pem"
    path.write_bytes(private)
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex()
    )
    trust = tmp_path / "trust.json"
    trust.write_text(json.dumps({"builder": public}), encoding="utf-8")
    return str(path), str(trust)


def _artifact_args(tmp_path, data: dict):
    key, trust = _keys(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    (project / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    (project / "agent.py").write_text("agent = None\n", encoding="utf-8")
    return [
        "--artifact",
        str(project),
        "--key",
        key,
        "--key-id",
        "k1",
        "--builder-key",
        key,
        "--builder-key-id",
        "builder",
        "--builder-keys",
        trust,
        "--artifact-dir",
        str(tmp_path / "store"),
    ]


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


@needs_crypto
def test_publish_writes_registry(tmp_path, capsys):
    data = _manifest_data()
    path = _write(tmp_path, data)
    registry_dir = tmp_path / "registry"
    cli.main(
        [
            "publish",
            str(path),
            "--registry",
            str(registry_dir),
            *_artifact_args(tmp_path, data),
        ]
    )
    out = capsys.readouterr().out
    assert "published team-a/support-bot@1.0.0" in out
    assert (registry_dir / "team-a" / "support-bot" / "1.0.0.json").is_file()


@needs_crypto
def test_publish_conflict_exits_one(tmp_path, capsys):
    registry_dir = tmp_path / "registry"
    data = _manifest_data()
    first = _write(tmp_path, data, "first.json")
    cli.main(
        ["publish", str(first), "--registry", str(registry_dir), *_artifact_args(tmp_path, data)]
    )

    changed = dict(data)
    changed["description"] = "changed"
    second = _write(tmp_path, changed, "second.json")
    with pytest.raises(SystemExit) as exc:
        cli.main(["publish", str(second), "--registry", str(registry_dir)])
    assert exc.value.code == 1
    assert "publish failed" in capsys.readouterr().err
