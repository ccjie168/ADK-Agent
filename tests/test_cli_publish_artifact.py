"""SLICE-066: publish attaches a signed deterministic artifact."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from adk_agent import cli
from adk_agent.core import PublishedAgent
from adk_agent.registry import pack_agent, verify_digest
from adk_agent.registry.artifacts import artifact_digest

_HAS_CRYPTO = importlib.util.find_spec("cryptography") is not None
needs_crypto = pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography is not installed")


def _manifest(version: str = "1.0.0") -> dict:
    return {
        "id": "bot",
        "version": version,
        "tenant": "acme",
        "owner": "acme",
        "model_policy": {"provider_allowlist": ["litellm"]},
    }


def _project(tmp_path, version: str = "1.0.0") -> Path:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    (project / "manifest.json").write_text(json.dumps(_manifest(version)), encoding="utf-8")
    (project / "agent.py").write_text("agent = object()\n", encoding="utf-8")
    return project


def _key(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    path = tmp_path / "publisher.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return key, path


def _record(tmp_path) -> PublishedAgent:
    path = tmp_path / "registry" / "acme" / "bot" / "1.0.0.json"
    return PublishedAgent.model_validate_json(path.read_text(encoding="utf-8"))


@needs_crypto
def test_publish_with_artifact(tmp_path, capsys):
    project = _project(tmp_path)
    key, key_path = _key(tmp_path)
    store = tmp_path / "store"

    cli.main(
        [
            "publish",
            str(project / "manifest.json"),
            "--registry",
            str(tmp_path / "registry"),
            "--artifact",
            str(project),
            "--key",
            str(key_path),
            "--key-id",
            "publisher-1",
            "--artifact-dir",
            str(store),
        ]
    )

    record = _record(tmp_path)
    data = pack_agent(project)
    assert record.artifact is not None
    assert record.artifact.digest == artifact_digest(data)
    assert record.artifact.size == len(data)
    assert record.artifact.key_id == "publisher-1"
    assert verify_digest(record.artifact.digest, record.artifact.signature, key.public_key())
    hexdigest = record.artifact.digest.split(":", 1)[1]
    assert (store / "sha256" / hexdigest).read_bytes() == data
    assert "artifact sha256:" in capsys.readouterr().out


@needs_crypto
def test_publish_with_zip(tmp_path):
    project = _project(tmp_path)
    key, key_path = _key(tmp_path)
    archive = tmp_path / "bot.zip"
    archive.write_bytes(pack_agent(project))

    cli.main(
        [
            "publish",
            str(project / "manifest.json"),
            "--registry",
            str(tmp_path / "registry"),
            "--artifact",
            str(archive),
            "--key",
            str(key_path),
            "--key-id",
            "publisher-1",
            "--artifact-dir",
            str(tmp_path / "store"),
        ]
    )

    record = _record(tmp_path)
    assert record.artifact is not None
    assert record.artifact.digest == artifact_digest(archive.read_bytes())


@needs_crypto
@pytest.mark.parametrize(
    "extra",
    [
        ["--artifact", "{project}", "--key-id", "k1", "--artifact-dir", "{store}"],
        ["--artifact", "{project}", "--key", "{key}", "--artifact-dir", "{store}"],
        ["--key", "{key}", "--key-id", "k1"],
        ["--artifact", "{project}", "--key", "{key}", "--key-id", "k1"],
    ],
)
def test_publish_requires_key(tmp_path, capsys, extra):
    project = _project(tmp_path)
    _, key_path = _key(tmp_path)
    store = tmp_path / "store"
    argv = [
        "publish",
        str(project / "manifest.json"),
        "--registry",
        str(tmp_path / "registry"),
    ]
    argv += [
        str(project)
        if item == "{project}"
        else str(key_path)
        if item == "{key}"
        else str(store)
        if item == "{store}"
        else item
        for item in extra
    ]

    with pytest.raises(SystemExit) as exc:
        cli.main(argv)

    err = capsys.readouterr().err
    assert exc.value.code == 1
    assert "artifact" in err or "key" in err


@needs_crypto
def test_publish_rejects_mismatched_zip(tmp_path, capsys):
    project = _project(tmp_path)
    archive = tmp_path / "bot.zip"
    archive.write_bytes(pack_agent(project))
    other = _project(tmp_path / "other", version="2.0.0")
    _, key_path = _key(tmp_path)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "publish",
                str(other / "manifest.json"),
                "--registry",
                str(tmp_path / "registry"),
                "--artifact",
                str(archive),
                "--key",
                str(key_path),
                "--key-id",
                "publisher-1",
                "--artifact-dir",
                str(tmp_path / "store"),
            ]
        )

    assert exc.value.code == 1
    assert "manifest" in capsys.readouterr().err


def test_publish_without_artifact_is_unchanged(tmp_path):
    project = _project(tmp_path)

    cli.main(["publish", str(project / "manifest.json"), "--registry", str(tmp_path / "registry")])

    assert _record(tmp_path).artifact is None
