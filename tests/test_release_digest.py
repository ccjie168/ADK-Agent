"""SLICE-109: the release pipeline pins images by digest."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ZERO = "sha256:" + "0" * 64
DIGEST = "sha256:" + "a" * 64
IMAGE = "registry.local:5000/adk/adk-agent"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "release_digest.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_validate_image():
    module = _load("release_digest_image")
    module.validate_image(IMAGE)
    for bad in ("registry.local:5000/adk-agent:latest", f"{IMAGE}@{DIGEST}", "adk-agent"):
        with pytest.raises(ValueError):
            module.validate_image(bad)


def test_validate_digest():
    module = _load("release_digest_digest")
    module.validate_digest(DIGEST)
    for bad in ("sha256:abc", "md5:" + "a" * 32, DIGEST.upper()):
        with pytest.raises(ValueError):
            module.validate_digest(bad)


def test_rewrite_pins_every_digest_line():
    module = _load("release_digest_rewrite")
    text = (
        "spec:\r\n"
        "  template:\r\n"
        "    spec:\r\n"
        "      containers:\r\n"
        f"      - image: adk-agent@{ZERO}\r\n"
        f"        name: x\r\n"
        f"      - image: other/thing@{ZERO}\r\n"
    )
    out = module.rewrite(text, IMAGE, DIGEST)
    assert out.count(f"image: {IMAGE}@{DIGEST}\r\n") == 2
    assert "adk-agent@sha256:000" not in out
    assert out.endswith("\r\n")


def test_rewrite_is_idempotent():
    module = _load("release_digest_idempotent")
    text = f"      - image: adk-agent@{ZERO}\n"
    once = module.rewrite(text, IMAGE, DIGEST)
    assert module.rewrite(once, IMAGE, DIGEST) == once


def test_cli_pins_files(tmp_path):
    module = _load("release_digest_cli")
    path = tmp_path / "manifest.yaml"
    path.write_text(f"      - image: adk-agent@{ZERO}\n", encoding="utf-8")
    assert module.main(["--image", IMAGE, "--digest", DIGEST, "--file", str(path)]) == 0
    assert f"image: {IMAGE}@{DIGEST}" in path.read_text(encoding="utf-8")
    assert (
        module.main(["--image", "adk-agent:latest", "--digest", DIGEST, "--file", str(path)]) == 2
    )


def test_release_workflow_order():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "if: github.ref == 'refs/heads/master'" in text
    assert "scripts/check.py --full" in text
    assert "trivy image" in text
    assert "docker push" in text
    assert "digest: sha256:" in text
    assert text.index("scripts/check.py --full") < text.index("docker push")
    assert text.index("trivy image") < text.index("docker push")
