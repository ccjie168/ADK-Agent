"""SLICE-072: commands read the registry over HTTP when given a URL."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pytest
from google.adk.agents import LlmAgent

from adk_agent import cli
from adk_agent.registry import FileAgentRegistry

_HAS_CRYPTO = importlib.util.find_spec("cryptography") is not None
needs_crypto = pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography is not installed")


class FakeRegistry:
    instances: list[FakeRegistry] = []

    def __init__(self, url: str, *, auth_token: str | None = None, **_kwargs) -> None:
        self.url = url
        self.auth_token = auth_token
        self.published = []
        self.uploaded = []
        FakeRegistry.instances.append(self)

    async def publish(self, agent):
        self.published.append(agent)
        return agent

    async def get(self, ref, tenant):
        return None

    async def list(self, tenant):
        return []

    async def tenants(self):
        return []

    async def upload_artifact(self, artifact, data):
        self.uploaded.append((artifact, data))

    async def aclose(self) -> None:
        pass


@pytest.fixture
def fake_registry(monkeypatch):
    FakeRegistry.instances = []
    monkeypatch.setattr("adk_agent.registry.HttpAgentRegistry", FakeRegistry)
    return FakeRegistry.instances


def _manifest(_version: str = "1.0.0") -> dict:
    return {
        "id": "bot",
        "version": "1.0.0",
        "tenant": "acme",
        "owner": "acme",
        "model_policy": {"provider_allowlist": ["litellm"]},
    }


def _manifest_file(tmp_path) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest()), encoding="utf-8")
    return path


def _agents_file(tmp_path) -> str:
    path = tmp_path / "agents.py"
    path.write_text(
        "from google.adk.agents import LlmAgent\n"
        "agents = {'probe': LlmAgent(name='probe', model='gemini-2.5-pro', instruction='x')}\n",
        encoding="utf-8",
    )
    return str(path)


def _keys_file(tmp_path) -> Path:
    path = tmp_path / "keys.json"
    path.write_text(json.dumps({"k1": "00" * 32}), encoding="utf-8")
    return path


def _namespace(**values) -> argparse.Namespace:
    base = {
        "registry_url": None,
        "registry_token_env": "ADK_REGISTRY_AUTH_TOKEN",
        "registry": "reg",
    }
    base.update(values)
    return argparse.Namespace(**base)


def test_agent_registry_prefers_url(fake_registry, monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "tok")

    registry = cli._agent_registry(
        _namespace(registry_url="http://reg.example", registry_token_env="MY_TOKEN")
    )

    assert registry is fake_registry[0]
    assert registry.url == "http://reg.example"
    assert registry.auth_token == "tok"


def test_agent_registry_falls_back_to_files(tmp_path):
    registry = cli._agent_registry(_namespace(registry=str(tmp_path)))

    assert isinstance(registry, FileAgentRegistry)


def test_bad_url_rejected(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("adk_agent.console.run_console", lambda *a, **k: None)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            ["console", "--agents", _agents_file(tmp_path), "--registry-url", "ftp://reg.example"]
        )

    assert exc.value.code == 1
    assert "registry" in capsys.readouterr().err.lower()


def test_console_wires_http_registry(tmp_path, monkeypatch, fake_registry):
    captured: dict = {}
    monkeypatch.setattr("adk_agent.console.run_console", lambda *a, **k: captured.update(k))

    cli.main(
        ["console", "--agents", _agents_file(tmp_path), "--registry-url", "http://reg.example"]
    )

    assert captured["registry"].url == "http://reg.example"


def test_serve_uses_http_registry(tmp_path, monkeypatch, fake_registry):
    captured: dict = {}

    async def load(refs, *, registry, **_kwargs):
        captured["registry"] = registry
        return {
            "probe": LlmAgent(
                name="probe", model="gemini-2.5-pro", description="probe", instruction="x"
            )
        }

    monkeypatch.setattr("adk_agent.registry.load_registry_agents", load)
    monkeypatch.setattr("adk_agent.mcp.server.serve_agent", lambda *a, **k: captured.update(k))

    cli.main(
        [
            "serve",
            "--agent-ref",
            "acme/bot@1.0.0",
            "--artifact-dir",
            str(tmp_path / "store"),
            "--artifact-keys",
            str(_keys_file(tmp_path)),
            "--registry-url",
            "http://reg.example",
        ]
    )

    assert captured["registry"].url == "http://reg.example"


def test_publish_uses_http_registry(tmp_path, fake_registry, capsys):
    cli.main(["publish", str(_manifest_file(tmp_path)), "--registry-url", "http://reg.example"])

    [record] = fake_registry[0].published
    assert record.manifest.id == "bot"
    assert "published acme/bot@1.0.0" in capsys.readouterr().out


@needs_crypto
def test_publish_uploads_artifact(tmp_path, fake_registry, capsys):
    project = tmp_path / "project"
    project.mkdir()
    (project / "manifest.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    (project / "agent.py").write_text("agent = object()\n", encoding="utf-8")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key_path = tmp_path / "publisher.pem"
    key_path.write_bytes(
        Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    cli.main(
        [
            "publish",
            str(project / "manifest.json"),
            "--registry-url",
            "http://reg.example",
            "--artifact",
            str(project),
            "--key",
            str(key_path),
            "--key-id",
            "publisher-1",
        ]
    )

    [record] = fake_registry[0].published
    [(artifact, data)] = fake_registry[0].uploaded
    assert artifact.digest == record.artifact.digest
    assert artifact.size == len(data)
    assert "artifact sha256:" in capsys.readouterr().out


@needs_crypto
def test_publish_artifact_source_exclusive(tmp_path, fake_registry, capsys):
    project = tmp_path / "project"
    project.mkdir()
    (project / "manifest.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    (project / "agent.py").write_text("agent = object()\n", encoding="utf-8")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key_path = tmp_path / "publisher.pem"
    key_path.write_bytes(
        Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "publish",
                str(project / "manifest.json"),
                "--registry-url",
                "http://reg.example",
                "--artifact",
                str(project),
                "--key",
                str(key_path),
                "--key-id",
                "publisher-1",
                "--artifact-dir",
                str(tmp_path / "store"),
            ]
        )

    assert exc.value.code == 1
    assert "artifact" in capsys.readouterr().err.lower()


def test_publish_eval_report_exclusive(tmp_path, fake_registry, capsys):
    report = tmp_path / "report.json"
    report.write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "publish",
                str(_manifest_file(tmp_path)),
                "--registry-url",
                "http://reg.example",
                "--eval-report",
                str(report),
            ]
        )

    assert exc.value.code == 1
    assert "eval" in capsys.readouterr().err.lower()
