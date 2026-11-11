#!/usr/bin/env python3
"""SLICE-002 container smoke test.

Builds the image, then verifies:
  - /healthz is 200 without auth
  - /mcp is 401 without a token
  - /mcp works with the bearer token (initialize + list_tools)
  - the container runs as non-root
  - the container refuses to start without ADK_MCP_AUTH_TOKEN

Usage: python scripts/smoke_container.py
Requires Docker. Exits 0 on success.
"""

from __future__ import annotations

import asyncio
import os
import subprocess  # nosec B404  # docker CLI smoke test
import sys
import time

import httpx
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

IMAGE = "adk-agent-mcp:smoke"
NAME = "adk-agent-mcp-smoke"
HOST_PORT = 18080
TOKEN = "smoke-secret"  # nosec B105  # ephemeral test token, not a credential
MODEL = "claude:deepseek-v4-pro"


_SENSITIVE = ("TOKEN", "KEY", "SECRET", "PASSWORD")


def _redact(cmd: list[str]) -> list[str]:
    """Mask KEY=value pairs for credentials before printing the command."""
    safe: list[str] = []
    for part in cmd:
        if "=" in part:
            key = part.split("=", 1)[0]
            if any(marker in key.upper() for marker in _SENSITIVE):
                part = f"{key}=***"
        safe.append(part)
    return safe


def sh(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("+", " ".join(_redact(cmd)))
    return subprocess.run(cmd, text=True, **kwargs)  # nosec B603  # fixed argv, no shell


def wait_health(url: str, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with httpx.Client(trust_env=False, timeout=2.0) as client:
                if client.get(url).status_code == 200:
                    return True
        except Exception:  # nosec B110  # polling loop retries until timeout
            pass
        time.sleep(0.5)
    return False


async def mcp_roundtrip(url: str) -> list[str]:
    async with (
        httpx2.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"}, trust_env=False) as http,
        streamable_http_client(url, http_client=http) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        return [t.name for t in tools.tools]


def main() -> int:
    failures: list[str] = []
    try:
        build = sh(["docker", "build", "-t", IMAGE, "."], cwd=os.getcwd(), timeout=1200)
        if build.returncode != 0:
            print("BUILD FAILED")
            return 1

        sh(["docker", "rm", "-f", NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        env = [
            "-e",
            "PORT=8080",
            "-e",
            f"ADK_MCP_AUTH_TOKEN={TOKEN}",
            "-e",
            f"ADK_AGENT_MODEL={MODEL}",
            "-e",
            "SESSION_DB=/data/sessions.db",
        ]
        for key in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
            if os.environ.get(key):
                env += ["-e", f"{key}={os.environ[key]}"]

        run = sh(["docker", "run", "-d", "--name", NAME, "-p", f"{HOST_PORT}:8080", *env, IMAGE])
        if run.returncode != 0:
            print("RUN FAILED")
            return 1

        base = f"http://127.0.0.1:{HOST_PORT}"
        if wait_health(f"{base}/healthz"):
            print("[PASS] healthz 200")
        else:
            failures.append("healthz not 200")
            sh(["docker", "logs", NAME])

        with httpx.Client(trust_env=False, timeout=10.0) as client:
            code = client.post(f"{base}/mcp", json={}).status_code
        if code == 401:
            print("[PASS] no-token /mcp 401")
        else:
            failures.append(f"no-token /mcp got {code}")

        try:
            tools = asyncio.run(mcp_roundtrip(f"{base}/mcp"))
            if tools:
                print(f"[PASS] authenticated list_tools: {tools}")
            else:
                failures.append("authenticated list_tools empty")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"authenticated MCP failed: {exc}")

        uid = sh(["docker", "exec", NAME, "id", "-u"], capture_output=True).stdout.strip()
        if uid and uid != "0":
            print(f"[PASS] non-root uid={uid}")
        else:
            failures.append(f"container runs as root (uid={uid!r})")

        db = sh(["docker", "exec", NAME, "printenv", "SESSION_DB"], capture_output=True)
        if db.stdout.strip() == "/data/sessions.db":
            print("[PASS] SESSION_DB=/data/sessions.db")
        else:
            failures.append(f"SESSION_DB={db.stdout.strip()!r}")

        writable = sh(
            ["docker", "exec", NAME, "sh", "-c", "touch /data/probe && rm /data/probe"],
            capture_output=True,
        )
        if writable.returncode == 0:
            print("[PASS] /data writable")
        else:
            failures.append("/data not writable")

        try:
            refused = sh(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-e",
                    "PORT=8080",
                    "-e",
                    f"ADK_AGENT_MODEL={MODEL}",
                    IMAGE,
                ],
                capture_output=True,
                timeout=180,
            )
            if refused.returncode != 0:
                print(f"[PASS] no-token startup refused (exit {refused.returncode})")
            else:
                failures.append("container started without ADK_MCP_AUTH_TOKEN")
        except subprocess.TimeoutExpired:
            failures.append("container hung without ADK_MCP_AUTH_TOKEN")
    finally:
        sh(["docker", "rm", "-f", NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if failures:
        print("FAILED:")
        for item in failures:
            print(" -", item)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
