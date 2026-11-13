"""SLICE-066: deterministic agent packaging."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from adk_agent.core import AgentManifest
from adk_agent.registry import PackagingError, pack_agent, read_artifact_zip
from adk_agent.registry.artifacts import artifact_digest


def _manifest(**overrides) -> dict:
    data = {
        "id": "bot",
        "version": "1.0.0",
        "tenant": "acme",
        "owner": "acme",
        "model_policy": {"provider_allowlist": ["litellm"]},
    }
    data.update(overrides)
    return data


def _project(tmp_path, manifest=None):
    (tmp_path / "manifest.json").write_text(
        json.dumps(_manifest() if manifest is None else manifest), encoding="utf-8"
    )
    (tmp_path / "agent.py").write_text("agent = object()\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")
    (tmp_path / "README.md").write_text("readme\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_smoke.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


def test_pack_is_deterministic(tmp_path):
    project = _project(tmp_path)

    first = pack_agent(project)
    second = pack_agent(project)

    assert first == second
    assert artifact_digest(first).startswith("sha256:")


def test_pack_includes_allowed_files(tmp_path):
    data = pack_agent(_project(tmp_path))

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())

    assert names == {"manifest.json", "agent.py", "requirements.txt", "README.md"}


def test_zip_entries_are_normalized(tmp_path):
    data = pack_agent(_project(tmp_path))

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()

    assert [info.filename for info in infos] == sorted(info.filename for info in infos)
    for info in infos:
        assert info.date_time == (1980, 1, 1, 0, 0, 0)
        assert info.external_attr >> 16 == 0o644
        assert info.compress_type == zipfile.ZIP_STORED


def test_pack_requires_manifest_and_entrypoint(tmp_path):
    with pytest.raises(PackagingError):
        pack_agent(tmp_path)

    (tmp_path / "manifest.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    with pytest.raises(PackagingError):
        pack_agent(tmp_path)


def test_read_zip_checks_manifest(tmp_path):
    project = _project(tmp_path)
    archive = tmp_path / "agent.zip"
    archive.write_bytes(pack_agent(project))

    data, manifest = read_artifact_zip(archive)

    assert data == archive.read_bytes()
    assert manifest == AgentManifest.model_validate(_manifest())


def test_read_zip_rejects_bad_manifest(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("manifest.json", "{}")
        handle.writestr("agent.py", "x = 1\n")

    with pytest.raises(PackagingError):
        read_artifact_zip(archive)
