"""SLICE-295: every proof service that reads artifacts trusts the builder keys."""

from __future__ import annotations

from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prove_it_works.py"


def _lines() -> list[str]:
    return _SCRIPT.read_text(encoding="utf-8").splitlines()


def test_every_service_with_artifact_keys_passes_builder_keys():
    lines = _lines()
    for index, line in enumerate(lines):
        if line.strip() != '"--artifact-keys",':
            continue
        value = lines[index + 1].strip()
        assert not value.startswith('"--'), (index + 1, "artifact keys lost their value")
        window = lines[index + 2 : index + 10]
        assert not any('"--artifact-keys"' in item for item in window), index + 1
        positions = [i for i, item in enumerate(window) if '"--builder-keys"' in item]
        assert positions, (index + 1, window)
        following = window[positions[0] + 1]
        assert 'keys["builder_keys"]' in following, (index + 1, following)


def test_the_harness_uses_the_builder_key_file():
    text = _SCRIPT.read_text(encoding="utf-8")
    assert '"--builder-key"' in text
    assert 'keys["builder_keys"]' in text
