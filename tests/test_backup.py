"""SLICE-055: create and restore a file-state backup."""

from __future__ import annotations

import io
import tarfile

import pytest

from adk_agent.backup import BACKUP_VERSION, BackupError, create_backup, restore_backup


def _state(tmp_path):
    registry = tmp_path / "registry"
    (registry / "t1" / "bot").mkdir(parents=True)
    (registry / "t1" / "bot" / "1.0.0.json").write_text('{"id":"bot"}', encoding="utf-8")
    approvals = tmp_path / "approvals"
    approvals.mkdir()
    (approvals / "req-1.request.json").write_text('{"request_id":"req-1"}', encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    audit.write_text('{"event":1}\n', encoding="utf-8")
    (tmp_path / "audit.jsonl.000001").write_text('{"event":0}\n', encoding="utf-8")
    return registry, approvals, audit


def _backup(tmp_path):
    registry, approvals, audit = _state(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    manifest, digest = create_backup(
        archive,
        [("registry", registry), ("approvals", approvals), ("audit", audit)],
    )
    return archive, manifest, digest


def test_roundtrip(tmp_path):
    archive, manifest, digest = _backup(tmp_path)

    dest = tmp_path / "restored"
    loaded = restore_backup(archive, dest)

    assert manifest["version"] == BACKUP_VERSION
    assert len(digest) == 64
    assert loaded["version"] == BACKUP_VERSION
    assert (dest / "registry" / "t1" / "bot" / "1.0.0.json").read_text(encoding="utf-8") == (
        '{"id":"bot"}'
    )
    assert (dest / "approvals" / "req-1.request.json").exists()
    assert (dest / "audit" / "audit.jsonl").exists()
    assert (dest / "audit" / "audit.jsonl.000001").exists()
    assert (dest / "manifest.json").exists()


def test_manifest_counts(tmp_path):
    _, manifest, _ = _backup(tmp_path)

    counts = {source["kind"]: source["files"] for source in manifest["sources"]}
    assert counts == {"registry": 1, "approvals": 1, "audit": 2}


def test_audit_segments_included(tmp_path):
    archive, _, _ = _backup(tmp_path)

    with tarfile.open(archive, "r:gz") as tar:
        names = set(tar.getnames())

    assert "audit/audit.jsonl" in names
    assert "audit/audit.jsonl.000001" in names


def test_restore_refuses_nonempty(tmp_path):
    archive, _, _ = _backup(tmp_path)
    dest = tmp_path / "restored"
    dest.mkdir()
    (dest / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(BackupError):
        restore_backup(archive, dest)

    assert (dest / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_restore_force_replaces(tmp_path):
    archive, _, _ = _backup(tmp_path)
    dest = tmp_path / "restored"
    dest.mkdir()
    (dest / "old.txt").write_text("old", encoding="utf-8")

    restore_backup(archive, dest, force=True)

    assert not (dest / "old.txt").exists()
    assert (dest / "registry").is_dir()


def test_restore_rejects_traversal(tmp_path):
    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as tar:
        info = tarfile.TarInfo("../evil.txt")
        payload = b"x"
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))

    with pytest.raises(BackupError):
        restore_backup(evil, tmp_path / "dest")

    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path / "dest").exists()


def test_missing_manifest_rejected(tmp_path):
    archive = tmp_path / "plain.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("registry/x.json")
        payload = b"{}"
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))

    with pytest.raises(BackupError):
        restore_backup(archive, tmp_path / "dest")

    assert not (tmp_path / "dest").exists()


def test_unknown_kind_rejected(tmp_path):
    registry, _, _ = _state(tmp_path)

    with pytest.raises(BackupError):
        create_backup(tmp_path / "bad.tar.gz", [("other", registry)])
