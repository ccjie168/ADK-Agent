"""SLICE-126: shared safe path joining for file stores."""

from __future__ import annotations

import os

import pytest

from adk_agent.registry import UnsafePath, safe_join


def test_valid_parts_join(tmp_path):
    assert safe_join(tmp_path, "acme", "agent.json") == tmp_path / "acme" / "agent.json"


@pytest.mark.parametrize(
    "part",
    [
        "..",
        "../escape",
        "/etc/passwd",
        "acme/other",
        "a\\b",
        "C:",
        ".hidden",
        "",
        "x" * 129,
    ],
)
def test_unsafe_parts_are_rejected(tmp_path, part):
    with pytest.raises(UnsafePath):
        safe_join(tmp_path, part)


def test_stricter_pattern_rejects_plus(tmp_path):
    assert safe_join(tmp_path, "a+b") == tmp_path / "a+b"

    with pytest.raises(UnsafePath):
        safe_join(tmp_path, "a+b", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def test_requires_at_least_one_part(tmp_path):
    with pytest.raises(UnsafePath):
        safe_join(tmp_path)


def test_symlink_escape_is_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, root / "sub", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this platform")

    with pytest.raises(UnsafePath):
        safe_join(root, "sub", "file.json")


def test_missing_paths_resolve_under_root(tmp_path):
    expected = tmp_path / "acme" / "nested" / "agent.json"

    assert safe_join(tmp_path, "acme", "nested", "agent.json") == expected
