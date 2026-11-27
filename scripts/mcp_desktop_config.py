#!/usr/bin/env python3
"""Print a Claude Desktop ``mcpServers`` entry for the support agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
_AGENT = ROOT / "scripts" / "support_a2a_agent.py"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _loopback_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme != "http" or parts.hostname not in _LOOPBACK_HOSTS:
        raise SystemExit("--mock-url must be a loopback http URL")
    return value.rstrip("/")


def build_config(python: str, workdir: Path, mock_url: str, wait_seconds: int) -> dict:
    return {
        "mcpServers": {
            "adk-support": {
                "command": python,
                "args": [
                    "-m",
                    "adk_agent",
                    "serve",
                    "--agent",
                    str(_AGENT),
                ],
                "env": {
                    "SUPPORT_MOCK_URL": mock_url,
                    "SUPPORT_MOCK_TOKEN": "demo-token",  # nosec B105  # loopback demo token
                    "SUPPORT_APPROVALS_DIR": str(workdir / "approvals"),
                    "SUPPORT_AUDIT_FILE": str(workdir / "support-audit.jsonl"),
                    "SUPPORT_WAIT_SECONDS": str(wait_seconds),
                },
            }
        }
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Print a Claude Desktop MCP config entry.")
    parser.add_argument(
        "--workdir",
        default=str(Path.home() / ".adk" / "state"),
        help="where approvals and the plan audit go (default: ~/.adk/state)",
    )
    parser.add_argument("--mock-url", default="http://127.0.0.1:8055")
    parser.add_argument("--wait-seconds", type=int, default=120)
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()

    config = build_config(
        args.python,
        Path(args.workdir).expanduser(),
        _loopback_url(args.mock_url),
        args.wait_seconds,
    )
    print(json.dumps(config, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
