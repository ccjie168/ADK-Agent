"""SLICE-300: the demo seed signs platform build trust for in_process artifacts."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

from adk_agent.core import AgentRef
from adk_agent.registry import (
    FileAgentRegistry,
    FileArtifactStore,
    InProcessArtifactLoader,
    TrustStore,
    load_agent,
)

ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = ROOT / "scripts" / "demo_seed.py"
_KEY_ID = "demo-publisher"


def _module():
    spec = importlib.util.spec_from_file_location("demo_seed", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _seed(tmp_path: Path):
    module = _module()
    key = module._load_or_create_key(tmp_path)
    asyncio.run(module._seed(tmp_path, "acme", key))
    return module


def _trust(tmp_path: Path) -> TrustStore:
    keys = json.loads((tmp_path / "keys.json").read_text(encoding="utf-8"))
    return TrustStore({_KEY_ID: bytes.fromhex(keys[_KEY_ID])})


def test_demo_seed_signs_builder(tmp_path):
    _seed(tmp_path)
    registry = FileAgentRegistry(tmp_path / "registry")
    records = asyncio.run(registry.list("acme"))
    trust = _trust(tmp_path)

    assert records
    for record in records:
        assert record.artifact is not None
        assert record.manifest.execution_tier == "in_process"
        assert record.artifact.builder_signature is not None
        assert record.artifact.builder_key_id == _KEY_ID
        trust.verify(record.artifact)
        trust.verify_builder(record.artifact)


def test_demo_seed_artifact_loads_with_builder_trust(tmp_path):
    _seed(tmp_path)
    registry = FileAgentRegistry(tmp_path / "registry")
    store = FileArtifactStore(tmp_path / "store")
    record = asyncio.run(registry.list("acme"))[0]

    agent = asyncio.run(
        load_agent(
            registry=registry,
            ref=AgentRef(
                id=record.manifest.id,
                version=record.manifest.version,
                digest=record.digest,
            ),
            tenant="acme",
            store=store,
            loader=InProcessArtifactLoader(),
            trust=_trust(tmp_path),
            builder_keys=_trust(tmp_path),
        )
    )

    assert agent.name == record.manifest.id


def test_demo_seed_prints_builder_flags(tmp_path, capsys):
    module = _seed(tmp_path)
    module._print_next_steps(tmp_path, "acme")
    output = capsys.readouterr().out
    guide = (ROOT / "docs" / "demo" / "pilot-demo.md").read_text(encoding="utf-8")

    assert "ADK_BUILDER_KEYS" in output
    assert "--builder-keys" in output
    assert "ADK_BUILDER_KEYS" in guide
    assert "--builder-keys" in guide
