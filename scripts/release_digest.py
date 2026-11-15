#!/usr/bin/env python3
"""Pins the deployed image digest in the Kubernetes manifests."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILES = (ROOT / "deploy/k8s/deployment.yaml", ROOT / "deploy/k8s/multi-replica.yaml")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
IMAGE_RE = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:[0-9]+)?(/[a-z0-9]+([._-][a-z0-9]+)*)+\Z")
IMAGE_LINE_RE = re.compile(
    r"(?m)^([ \t]*(?:-[ \t]+)?image:[ \t]*)\S+@sha256:[0-9a-f]{64}([ \t]*)(\r?)$"
)


def validate_image(image: str) -> None:
    if "@" in image:
        raise ValueError("image must not contain a digest")
    head = image.split("/", 1)[0]
    if "." not in head and ":" not in head and head != "localhost":
        raise ValueError("image must start with a registry host")
    if not IMAGE_RE.fullmatch(image):
        raise ValueError("image must be a lowercase repository reference without a tag")


def validate_digest(digest: str) -> None:
    if not DIGEST_RE.fullmatch(digest):
        raise ValueError("digest must be sha256 followed by 64 lowercase hex characters")


def rewrite(text: str, image: str, digest: str) -> str:
    out, count = IMAGE_LINE_RE.subn(
        lambda m: f"{m.group(1)}{image}@{digest}{m.group(2)}{m.group(3)}", text
    )
    if count == 0:
        raise ValueError("no digest-pinned image line found")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pin the deployed image digest.")
    parser.add_argument("--image", required=True, help="registry image without a tag")
    parser.add_argument("--digest", help="sha256 digest from the pushed image")
    parser.add_argument("--validate", action="store_true", help="only check the image")
    parser.add_argument("--file", dest="files", action="append", help="manifest to rewrite")
    args = parser.parse_args(argv)

    try:
        validate_image(args.image)
        if args.validate:
            print(f"image ok: {args.image}")
            return 0
        if not args.digest:
            raise ValueError("--digest is required unless --validate is set")
        validate_digest(args.digest)
        targets = [Path(path) for path in args.files] if args.files else list(DEFAULT_FILES)
        for path in targets:
            if not path.is_absolute():
                path = ROOT / path
            text = path.read_text(encoding="utf-8")
            updated = rewrite(text, args.image, args.digest)
            if updated != text:
                path.write_text(updated, encoding="utf-8")
            print(f"pinned {path}")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
