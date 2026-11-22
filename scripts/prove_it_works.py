"""End-to-end proof harness: run the real services and assert observable behaviour.

Unlike the unit suite, every check here starts a real process (or a real
container), talks HTTP, and inspects the real Postgres audit chain. The model
and embedding provider is a local OpenAI-compatible stub, so no external API
key or network call is involved.

Usage:

    python scripts/prove_it_works.py            # run every check
    python scripts/prove_it_works.py --only P2,P3
    python scripts/prove_it_works.py --smoke    # release subset: P1-P4
    python scripts/prove_it_works.py --keep     # keep the work dir for debugging

The harness exits 1 when any check fails. Evidence is written to
``<work>/report.json`` and printed as a table.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess  # nosec B404 - fixed argv lists only
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
ADMIN_TOKEN = "proof-" + secrets.token_hex(8)
MCP_TOKEN = "mcp-" + secrets.token_hex(8)
HOOK_TOKEN = "hook-" + secrets.token_hex(8)
PEER_TOKEN = "peer-" + secrets.token_hex(8)
EMBED_DIMENSIONS = 32
STUB_MODEL = "openai/proof-stub"


# --------------------------------------------------------------------------- stub


def build_stub_app() -> FastAPI:
    """Local OpenAI-compatible server: deterministic chat reply and embedding."""
    app = FastAPI()

    def _reply(body: dict[str, Any]) -> str:
        parts: list[str] = []
        for message in body.get("messages") or []:
            content = message.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                parts.extend(
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                )
        text = "\n".join(part for part in parts if part)
        return "PROOF-OK: " + text[-1500:]

    def _embedding(text: str) -> list[float]:
        # One shared unit vector keeps the proof about plumbing, not ranking.
        return [1.0 / (EMBED_DIMENSIONS**0.5)] * EMBED_DIMENSIONS

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/chat/completions")
    async def completions(request: Request) -> Any:
        body = await request.json()
        text = _reply(body)
        if body.get("stream"):

            def events() -> Iterable[str]:
                chunk = {
                    "id": "proof",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": body.get("model", "proof"),
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": text},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                done = {
                    "id": "proof",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": body.get("model", "proof"),
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(done)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(events(), media_type="text/event-stream")
        return {
            "id": "proof",
            "object": "chat.completion",
            "created": 0,
            "model": body.get("model", "proof"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16},
        }

    @app.post("/v1/embeddings")
    async def embeddings(request: Request) -> JSONResponse:
        body = await request.json()
        inputs = body.get("input")
        texts = [inputs] if isinstance(inputs, str) else list(inputs or [])
        data = [
            {"object": "embedding", "index": index, "embedding": _embedding(text)}
            for index, text in enumerate(texts)
        ]
        return JSONResponse(
            {
                "object": "list",
                "model": body.get("model", "proof-embed"),
                "data": data,
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            }
        )

    return app


@dataclass
class Service:
    name: str
    process: subprocess.Popen[bytes]
    port: int
    log_path: Path
    log_handle: Any

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
        # Windows refuses to delete files with an open handle, so release it
        # before the work dir is cleaned up.
        self.log_handle.close()


@dataclass
class Result:
    check: str
    ok: bool
    detail: str
    evidence: list[str] = field(default_factory=list)


def require(condition: bool, message: str = "proof check failed") -> None:
    """Like assert, but kept under ``python -O`` and accepted by bandit."""
    if not condition:
        raise AssertionError(message)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_http(url: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=2.0)
            if response.status_code < 500:
                return
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(0.3)
    raise RuntimeError(f"service did not become healthy at {url}: {last}")


class Proof:
    def __init__(self, work: Path) -> None:
        self.work = work
        self.services: list[Service] = []
        self.stub_port = free_port()
        self.pg_port = free_port()
        self.container = f"adk-prove-{uuid.uuid4().hex[:8]}"
        self.pg_user = "adk"
        self.pg_password = secrets.token_hex(12)
        self.results: list[Result] = []
        self._stub: uvicorn.Server | None = None

    # ------------------------------------------------------------- infrastructure

    @property
    def stub_url(self) -> str:
        return f"http://127.0.0.1:{self.stub_port}"

    @property
    def pg_url(self) -> str:
        scheme = "post" + "gresql"
        return f"{scheme}://{self.pg_user}:{self.pg_password}@127.0.0.1:{self.pg_port}/adk"

    def start_stub(self) -> None:
        server = uvicorn.Server(
            uvicorn.Config(
                build_stub_app(), host="127.0.0.1", port=self.stub_port, log_level="error"
            )
        )
        self._stub = server
        threading.Thread(target=server.run, daemon=True).start()
        wait_http(f"{self.stub_url}/healthz", 30)

    def start_postgres(self) -> None:
        subprocess.run(  # nosec B603 B607
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                self.container,
                "-e",
                f"POSTGRES_USER={self.pg_user}",
                "-e",
                f"POSTGRES_PASSWORD={self.pg_password}",
                "-e",
                "POSTGRES_DB=adk",
                "-p",
                f"127.0.0.1:{self.pg_port}:5432",
                "docker.m.daocloud.io/pgvector/pgvector:pg15",
            ],
            check=True,
            capture_output=True,
        )
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            probe = subprocess.run(  # nosec B603 B607
                [
                    "docker",
                    "exec",
                    self.container,
                    "psql",
                    "-U",
                    self.pg_user,
                    "-d",
                    "adk",
                    "-tAc",
                    "select 1",
                ],
                capture_output=True,
                text=True,
            )
            # pg_isready can answer during initdb's temporary server, then the
            # real cluster restarts; only a completed query proves readiness.
            if probe.returncode == 0 and probe.stdout.strip() == "1":
                return
            time.sleep(0.5)
        raise RuntimeError("postgres container did not become ready")

    def psql(self, sql: str) -> str:
        done = subprocess.run(  # nosec B603 B607
            [
                "docker",
                "exec",
                self.container,
                "psql",
                "-U",
                self.pg_user,
                "-d",
                "adk",
                "-tAc",
                sql,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            raise RuntimeError(f"psql failed: {done.stderr.strip()}")
        return done.stdout.strip()

    def service_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["OPENAI_API_KEY"] = secrets.token_hex(8)
        env["OPENAI_BASE_URL"] = f"{self.stub_url}/v1"
        env["ADK_AGENT_MODEL"] = f"litellm:{STUB_MODEL}"
        return env

    def start_service(
        self,
        name: str,
        args: list[str],
        *,
        health: str | None = None,
        env: dict[str, str] | None = None,
    ) -> Service:
        port = free_port()
        logs = self.work / "logs"
        logs.mkdir(exist_ok=True)
        log_path = logs / f"{name}.log"
        handle = log_path.open("wb")
        process = subprocess.Popen(  # nosec B603 B607
            [PY, "-m", "adk_agent", *[part.replace("{port}", str(port)) for part in args]],
            cwd=str(self.work),
            env=env or self.service_env(),
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
        service = Service(
            name=name, process=process, port=port, log_path=log_path, log_handle=handle
        )
        self.services.append(service)
        if health:
            try:
                wait_http(health.replace("{port}", str(port)))
            except RuntimeError:
                print(f"--- {name} log ---")
                print(log_path.read_text(encoding="utf-8", errors="replace")[-4000:])
                raise
        return service

    def stop_all(self) -> None:
        if self._stub is not None:
            self._stub.should_exit = True
        for service in reversed(self.services):
            service.stop()
        subprocess.run(  # nosec B603 B607
            ["docker", "rm", "-f", self.container], capture_output=True, check=False
        )


# ----------------------------------------------------------------------------- checks


def check_env(proof: Proof) -> Result:
    """P1: the stub, Postgres and the real model channel are alive."""
    one = proof.psql("select 1")
    stub = httpx.get(f"{proof.stub_url}/healthz", timeout=5).status_code
    require(one == "1" and stub == 200, f"Postgres select 1 -> {one!r}, stub -> {stub}")
    return Result(
        "P1 environment",
        True,
        f"Postgres and stub are up (stub port {proof.stub_port})",
        [f"select 1 -> {one}", f"stub health -> {stub}"],
    )


def _audit_event(tenant: str, index: int, **overrides: Any) -> Any:
    from adk_agent.core import AgentRef, AuditEvent, Principal

    fields: dict[str, Any] = {
        "event_id": f"proof-{index}",
        "run_id": f"run-{index}",
        "trace_id": f"trace-{index}",
        "tenant": tenant,
        "principal": Principal(tenant=tenant, subject="alice", kind="human"),
        "agent_ref": AgentRef(id="proof_agent", version="1.0.0", digest="a" * 64),
        "action": "agent.run",
        "target": "proof_agent@1.0.0",
        "status": "ok",
        "timestamp": "2026-11-21T00:00:00+00:00",
    }
    fields.update(overrides)
    return AuditEvent(**fields)


def _approval_request(request_id: str) -> Any:
    from datetime import datetime, timezone

    from adk_agent.core import AgentRef, ApprovalRequest, Principal

    return ApprovalRequest(
        request_id=request_id,
        run_id=f"run-{request_id}",
        trace_id=f"trace-{request_id}",
        step_id="step-1",
        agent_ref=AgentRef(id="proof_agent", version="1.0.0", digest="c" * 64),
        principal=Principal(tenant="local", subject="alice", kind="human"),
        input="escalate",
        requested_at=datetime.now(timezone.utc),
    )


def check_audit(proof: Proof) -> Result:
    """P2: file and Postgres chains verify, and a single changed field breaks them."""
    import asyncio

    from adk_agent.audit import (
        AuditChainBroken,
        AuditPipeline,
        verify_audit_database,
        verify_audit_file,
    )
    from adk_agent.audit.postgres import PostgresAuditSink

    evidence: list[str] = []
    path = proof.work / "audit" / "file-chain.jsonl"
    pipeline = AuditPipeline(path)
    for index in range(3):
        asyncio.run(pipeline.append(_audit_event("acme", index)))
    require(verify_audit_file(path) == 3, "file chain did not verify")
    evidence.append("file chain: 3 events appended, verify_audit_file -> 3")

    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[1])
    tampered["event"]["target"] = "proof_agent@9.9.9"
    lines[1] = json.dumps(tampered, separators=(",", ":"), ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        verify_audit_file(path)
    except AuditChainBroken:
        evidence.append("file chain: one tampered target -> AuditChainBroken")
    else:
        raise AssertionError("tampered file chain still verified")

    sink = PostgresAuditSink(proof.pg_url)
    for index in range(3):
        asyncio.run(sink.append(_audit_event("acme", index)))
    rows = int(proof.psql("select count(*) from adk_audit_records"))
    stored = asyncio.run(verify_audit_database(proof.pg_url))
    require(stored == rows and rows >= 3, f"verified {stored} of {rows} rows")
    evidence.append(f"postgres chain: verify_audit_database -> {stored}")

    proof.psql(
        "update adk_audit_records set event = jsonb_set(event, '{target}', "
        "'\"proof_agent@9.9.9\"') where tenant = 'acme' and sequence = 2"
    )
    try:
        asyncio.run(verify_audit_database(proof.pg_url))
    except AuditChainBroken:
        evidence.append("postgres chain: one tampered row -> AuditChainBroken")
    else:
        raise AssertionError("tampered postgres chain still verified")
    proof.psql("delete from adk_audit_records where tenant = 'acme'")
    remaining = int(proof.psql("select count(*) from adk_audit_records where tenant = 'acme'"))
    require(remaining == 0, f"{remaining} acme rows survived cleanup")
    require(
        asyncio.run(verify_audit_database(proof.pg_url))
        == int(proof.psql("select count(*) from adk_audit_records")),
        "chain verification count diverged after cleanup",
    )
    return Result(
        "P2 audit chain", True, "file + postgres chains verify and detect tampering", evidence
    )


def _write_keys(work: Path) -> dict[str, Path]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    def make(name: str) -> tuple[Path, str]:
        key = Ed25519PrivateKey.generate()
        pem = work / f"{name}.pem"
        pem.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        raw = key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return pem, raw.hex()

    artifact_pem, artifact_hex = make("artifact-key")
    builder_pem, builder_hex = make("builder-key")
    keys = work / "artifact-keys.json"
    keys.write_text(json.dumps({"artifact-1": artifact_hex}), encoding="utf-8")
    builders = work / "builder-keys.json"
    builders.write_text(json.dumps({"builder-1": builder_hex}), encoding="utf-8")
    return {
        "artifact_pem": artifact_pem,
        "builder_pem": builder_pem,
        "artifact_keys": keys,
        "builder_keys": builders,
    }


def _write_agent_project(work: Path, agent_id: str, version: str = "1.0.0") -> Path:
    project = work / f"agent-src-{agent_id}"
    project.mkdir(exist_ok=True)
    manifest = {
        "id": agent_id,
        "version": version,
        "tenant": "acme",
        "owner": "proof",
        "description": "deterministic end-to-end proof agent",
        "model_policy": {"provider_allowlist": ["litellm"], "model_allowlist": [STUB_MODEL]},
        "tool_grants": [{"tool_id": "echo", "data_classes": []}],
        "execution_tier": "in_process",
    }
    (project / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (project / "agent.py").write_text(
        "from google.adk.agents import LlmAgent\n"
        "from adk_agent import build_model\n"
        "\n"
        "\n"
        "def echo(text: str) -> str:\n"
        '    """Echo the given text back."""\n'
        "    return text\n"
        "\n"
        "\n"
        "agent = LlmAgent(\n"
        f'    name="{agent_id}",\n'
        "    model=build_model(),\n"
        '    instruction="Answer the user. Use the echo tool when asked to echo.",\n'
        "    tools=[echo],\n"
        ")\n",
        encoding="utf-8",
    )
    return project


def _publish(
    proof: Proof,
    project: Path,
    keys: dict[str, Path],
    registry_url: str,
    env: dict[str, str],
) -> None:
    publish = subprocess.run(  # nosec B603 B607
        [
            PY,
            "-m",
            "adk_agent",
            "publish",
            str(project / "manifest.json"),
            "--registry-url",
            registry_url,
            "--registry-token-env",
            "PROOF_TOKEN",
            "--artifact",
            str(project),
            "--key",
            str(keys["artifact_pem"]),
            "--key-id",
            "artifact-1",
            "--builder-key",
            str(keys["builder_pem"]),
            "--builder-key-id",
            "builder-1",
            "--builder-keys",
            str(keys["builder_keys"]),
        ],
        cwd=str(proof.work),
        env=env,
        capture_output=True,
        text=True,
    )
    require(publish.returncode == 0, f"publish failed: {publish.stderr[-800:]}")


def check_registry_chat(proof: Proof) -> Result:
    """P3: sign, publish over HTTP, load on demand, chat through the real model channel."""
    keys = _write_keys(proof.work)
    startup_project = _write_agent_project(proof.work, "proof_agent")
    ondemand_project = _write_agent_project(proof.work, "proof_ondemand")
    artifacts = proof.work / "artifacts"
    artifacts.mkdir(exist_ok=True)
    env = proof.service_env()
    env["PROOF_TOKEN"] = ADMIN_TOKEN

    registry = proof.start_service(
        "registry",
        [
            "serve-registry",
            "--database-url",
            proof.pg_url,
            "--artifact-dir",
            str(artifacts),
            "--artifact-keys",
            str(keys["artifact_keys"]),
            "--builder-keys",
            str(keys["builder_keys"]),
            "--auth-token-env",
            "PROOF_TOKEN",
            "--host",
            "127.0.0.1",
            "--port",
            "{port}",
        ],
        health="http://127.0.0.1:{port}/healthz",
        env=env,
    )
    registry_url = f"http://127.0.0.1:{registry.port}"

    _publish(proof, startup_project, keys, registry_url, env)
    _publish(proof, ondemand_project, keys, registry_url, env)

    listed = httpx.get(
        f"{registry_url}/v1/agents",
        params={"tenant": "acme"},
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        timeout=10,
    )
    require(listed.status_code == 200, listed.text)
    payload = listed.json()
    entries = payload.get("agents", payload) if isinstance(payload, dict) else payload
    ids = {entry["manifest"]["id"] for entry in entries}
    require({"proof_agent", "proof_ondemand"} <= ids, listed.text)

    console = proof.start_service(
        "console",
        [
            "console",
            "--registry-url",
            registry_url,
            "--registry-token-env",
            "PROOF_TOKEN",
            "--agent-ref",
            "acme/proof_agent@1.0.0",
            "--artifact-dir",
            str(artifacts),
            "--artifact-keys",
            str(keys["artifact_keys"]),
            "--audit-db",
            proof.pg_url,
            "--allow-unauthenticated",
            "--role",
            "admin",
            "--host",
            "127.0.0.1",
            "--port",
            "{port}",
        ],
        health="http://127.0.0.1:{port}/healthz",
        env=env,
    )
    console_url = f"http://127.0.0.1:{console.port}"

    replies: dict[str, str] = {}
    for name in ("proof_agent", "proof_ondemand"):
        if name == "proof_ondemand":
            loaded = httpx.post(
                f"{console_url}/api/registry/load",
                json={"tenant": "acme", "id": name, "version": "1.0.0"},
                timeout=60,
            )
            require(loaded.status_code == 200, loaded.text)
        chat = httpx.post(
            f"{console_url}/api/chat",
            json={"agent": name, "message": f"hello {name}"},
            timeout=60,
        )
        require(chat.status_code == 200, chat.text)
        reply = chat.json()["reply"]
        require(reply.startswith("PROOF-OK"), reply)
        require(f"hello {name}" in reply, reply)
        replies[name] = reply

    runs = proof.psql(
        "select count(*) from adk_audit_records where action = 'agent.run' "
        "and event->>'status' = 'ok' "
        "and event->'agent_ref'->>'id' in ('proof_agent', 'proof_ondemand')"
    )
    require(int(runs) == 2, f"expected two agent.run rows for the P3 agents, got {runs}")
    tenants = proof.psql(
        "select distinct tenant from adk_audit_records where action = 'agent.run' "
        "and event->'agent_ref'->>'id' in ('proof_agent', 'proof_ondemand')"
    )

    return Result(
        "P3 publish/load/chat",
        True,
        "signed artifacts published over HTTP; startup and on-demand load both chat and audit",
        [
            f"registry listed {sorted(ids)}",
            f"startup chat reply: {replies['proof_agent'][:40]!r}",
            f"on-demand load + chat reply: {replies['proof_ondemand'][:40]!r}",
            f"agent.run audit rows: {runs} (tenants: {tenants})",
        ],
    )


def _start_registry(
    proof: Proof, keys: dict[str, Path], artifacts: Path, env: dict[str, str]
) -> tuple[Service, str]:
    registry = proof.start_service(
        "registry",
        [
            "serve-registry",
            "--database-url",
            proof.pg_url,
            "--artifact-dir",
            str(artifacts),
            "--artifact-keys",
            str(keys["artifact_keys"]),
            "--builder-keys",
            str(keys["builder_keys"]),
            "--auth-token-env",
            "PROOF_TOKEN",
            "--host",
            "127.0.0.1",
            "--port",
            "{port}",
        ],
        health="http://127.0.0.1:{port}/healthz",
        env=env,
    )
    return registry, f"http://127.0.0.1:{registry.port}"


def _ingest_marker(
    proof: Proof, env: dict[str, str], tenant: str, source: str, marker: str
) -> None:
    doc = proof.work / f"{source}.txt"
    doc.write_text(f"{marker} proof document.\n", encoding="utf-8")
    done = subprocess.run(  # nosec B603 B607
        [
            PY,
            "-m",
            "adk_agent",
            "rag",
            "ingest",
            "--database-url",
            proof.pg_url,
            "--dimensions",
            str(EMBED_DIMENSIONS),
            "--model",
            "openai/proof-embed",
            "--provider",
            "litellm",
            "--tenant",
            tenant,
            "--source-id",
            source,
            "--text",
            str(doc),
            "--data-class",
            "public",
        ],
        cwd=str(proof.work),
        env=env,
        capture_output=True,
        text=True,
    )
    require(done.returncode == 0, done.stderr[-800:])


def _record_digest(registry_url: str, tenant: str, agent_id: str) -> str:
    response = httpx.get(
        f"{registry_url}/v1/agents/{tenant}/{agent_id}/1.0.0",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        timeout=10,
    )
    require(response.status_code == 200, response.text)
    return response.json()["digest"]


def _invocation(tenant: str, agent_id: str, digest: str, run: str) -> dict[str, Any]:
    return {
        "run_id": f"run-{run}",
        "trace_id": f"trace-{run}",
        "principal": {"tenant": tenant, "subject": "alice", "kind": "human"},
        "agent_ref": {"id": agent_id, "version": "1.0.0", "digest": digest},
        "input": "proof",
    }


def check_tools(proof: Proof) -> Result:
    """P4: tool grants, HITL refusal, idempotent replay and write-key enforcement."""
    keys = _write_keys(proof.work)
    artifacts = proof.work / "artifacts-tools"
    artifacts.mkdir(exist_ok=True)
    env = proof.service_env()
    env["PROOF_TOKEN"] = ADMIN_TOKEN
    counter = proof.work / "tool-calls.log"
    env["PROOF_TOOL_LOG"] = str(counter)

    project = proof.work / "agent-src-proof_tools"
    project.mkdir(exist_ok=True)
    manifest = {
        "id": "proof_tools",
        "version": "1.0.0",
        "tenant": "acme",
        "owner": "proof",
        "description": "tool governance proof agent",
        "model_policy": {"provider_allowlist": ["litellm"], "model_allowlist": [STUB_MODEL]},
        "tool_grants": [
            {"tool_id": "echo", "data_classes": []},
            {"tool_id": "danger", "data_classes": [], "requires_approval": True},
            {"tool_id": "wipe", "data_classes": []},
        ],
        "execution_tier": "in_process",
    }
    (project / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (project / "agent.py").write_text(
        "from google.adk.agents import LlmAgent\n"
        "from adk_agent import build_model\n"
        "\n"
        "agent = LlmAgent(name='proof_tools', model=build_model(), instruction='proof')\n",
        encoding="utf-8",
    )
    tools_file = proof.work / "proof-tools.py"
    tools_file.write_text(
        "import os\n"
        "\n"
        "from adk_agent.tools import ToolSpec\n"
        "\n"
        "\n"
        "def _log(name):\n"
        "    with open(os.environ['PROOF_TOOL_LOG'], 'a', encoding='utf-8') as handle:\n"
        "        handle.write(name + '\\n')\n"
        "\n"
        "\n"
        "def echo(text):\n"
        "    _log('echo')\n"
        "    return {'echo': text}\n"
        "\n"
        "\n"
        "def danger():\n"
        "    _log('danger')\n"
        "    return {'ok': True}\n"
        "\n"
        "\n"
        "def wipe():\n"
        "    _log('wipe')\n"
        "    return {'ok': True}\n"
        "\n"
        "\n"
        "def free():\n"
        "    _log('free')\n"
        "    return {'ok': True}\n"
        "\n"
        "\n"
        "tools = {\n"
        "    'echo': ToolSpec(tool_id='echo', handler=echo),\n"
        "    'danger': ToolSpec(tool_id='danger', handler=danger, requires_approval=True),\n"
        "    'wipe': ToolSpec(tool_id='wipe', handler=wipe, write=True),\n"
        "    'free': ToolSpec(tool_id='free', handler=free),\n"
        "}\n",
        encoding="utf-8",
    )

    registry, registry_url = _start_registry(proof, keys, artifacts, env)
    _publish(proof, project, keys, registry_url, env)
    digest = _record_digest(registry_url, "acme", "proof_tools")

    gateway = proof.start_service(
        "tool-gateway",
        [
            "serve-tool-gateway",
            "--tools",
            str(tools_file),
            "--registry-url",
            registry_url,
            "--registry-token-env",
            "PROOF_TOKEN",
            "--idempotency-db",
            proof.pg_url,
            "--audit-db",
            proof.pg_url,
            "--allow-unauthenticated",
            "--host",
            "127.0.0.1",
            "--port",
            "{port}",
        ],
        health="http://127.0.0.1:{port}/healthz",
        env=env,
    )
    gateway_url = f"http://127.0.0.1:{gateway.port}/v1/invoke"

    def invoke(tool_id: str, *, key: str | None = None, run: str = "1") -> httpx.Response:
        request: dict[str, Any] = {"tool_id": tool_id, "args": {}}
        if key is not None:
            request["idempotency_key"] = key
        if tool_id == "echo":
            request["args"] = {"text": "hi"}
        return httpx.post(
            gateway_url,
            json={
                "invocation": _invocation("acme", "proof_tools", digest, run),
                "request": request,
            },
            timeout=30,
        )

    first = invoke("echo")
    require(first.status_code == 200, first.text)
    require(first.json()["output"] == {"echo": "hi"})

    denied = invoke("free")
    require(denied.status_code == 403 and denied.json()["error"] == "tool_denied", denied.text)

    approval = invoke("danger", key="danger-1")
    require(
        approval.status_code == 403 and approval.json()["error"] == "tool_denied", approval.text
    )
    approval_audit = proof.psql(
        "select count(*) from adk_audit_records where action = 'tool.call' "
        "and event->>'error_code' = 'approval_required'"
    )
    require(int(approval_audit) == 1, f"approval_required audit rows: {approval_audit}")

    missing = invoke("wipe")
    require(missing.status_code == 400 and missing.json()["error"] == "idempotency_missing")
    governed = invoke("wipe", key="wipe-1")
    require(governed.status_code == 200, governed.text)
    replay = invoke("wipe", key="wipe-1", run="2")
    require(replay.status_code == 200, replay.text)
    require(replay.json()["output"] == governed.json()["output"])
    calls = counter.read_text(encoding="utf-8").split()
    require(calls.count("wipe") == 1, f"idempotent replay executed {calls.count('wipe')} times")

    total = proof.psql("select count(*) from adk_audit_records where action = 'tool.call'")
    require(int(total) == 6, f"expected six tool.call audit rows, got {total}")
    return Result(
        "P4 tool gateway",
        True,
        "grants, HITL refusal, idempotent replay and write-key enforcement all observed",
        [
            f"granted call: {first.status_code} {first.json()['output']}",
            f"same idempotency key on a write tool: replay ok, handler executed "
            f"{calls.count('wipe')} time",
            f"ungranted tool: {denied.status_code} {denied.json()['error']}",
            f"approval-required tool: {approval.status_code}, audit error_code rows {approval_audit}",
            f"write tool without key: {missing.status_code} {missing.json()['error']}; "
            f"with key: {governed.status_code}",
            f"tool.call audit rows: {total}",
        ],
    )


def check_mcp(proof: Proof) -> Result:
    """P5: MCP over HTTP rejects anonymous callers and runs the registry agent."""
    import asyncio

    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    keys = _write_keys(proof.work)
    artifacts = proof.work / "artifacts-mcp"
    artifacts.mkdir(exist_ok=True)
    env = proof.service_env()
    env["PROOF_TOKEN"] = ADMIN_TOKEN
    env["PROOF_MCP_TOKEN"] = MCP_TOKEN

    project = _write_agent_project(proof.work, "proof_mcp")
    manifest_path = project / "manifest.json"
    mcp_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mcp_manifest["rag"] = {
        "enabled": True,
        "top_k": 3,
        "min_confidence": 0.0,
        "data_classes": ["public"],
    }
    manifest_path.write_text(json.dumps(mcp_manifest, indent=2), encoding="utf-8")
    registry, registry_url = _start_registry(proof, keys, artifacts, env)
    _publish(proof, project, keys, registry_url, env)
    _ingest_marker(proof, env, "local", "mcp-rag", "MCP-RAG-MARKER")

    server = proof.start_service(
        "mcp",
        [
            "serve",
            "--agent-ref",
            "acme/proof_mcp@1.0.0",
            "--registry-url",
            registry_url,
            "--registry-token-env",
            "PROOF_TOKEN",
            "--artifact-dir",
            str(artifacts),
            "--artifact-keys",
            str(keys["artifact_keys"]),
            "--transport",
            "streamable-http",
            "--auth-token-env",
            "PROOF_MCP_TOKEN",
            "--audit-db",
            proof.pg_url,
            "--rag-db",
            proof.pg_url,
            "--rag-dimensions",
            str(EMBED_DIMENSIONS),
            "--rag-model",
            "openai/proof-embed",
            "--rag-provider",
            "litellm",
            "--host",
            "127.0.0.1",
            "--port",
            "{port}",
        ],
        health="http://127.0.0.1:{port}/healthz",
        env=env,
    )
    url = f"http://127.0.0.1:{server.port}/mcp"

    anonymous = httpx.post(
        url,
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        timeout=10,
    )
    require(anonymous.status_code == 401, f"anonymous initialize -> {anonymous.status_code}")

    async def call() -> tuple[int, str]:
        http = create_mcp_http_client(headers={"Authorization": "Bearer " + MCP_TOKEN})
        async with http, streamable_http_client(url, http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                result = await session.call_tool(tools.tools[0].name, {"request": "hello mcp"})
            texts = [getattr(item, "text", "") for item in result.content]
            return len(tools.tools), "".join(texts)

    rag_before = int(
        proof.psql("select count(*) from adk_audit_records where action = 'rag.retrieve'")
    )
    try:
        count, reply = asyncio.run(call())
    except Exception as exc:  # noqa: BLE001 - surface the nested cause
        import traceback

        inners = getattr(exc, "exceptions", ()) or (exc,)
        details = ["".join(traceback.format_exception(inner))[-1200:] for inner in inners]
        raise RuntimeError("MCP call failed:\n" + "\n---\n".join(details)) from None
    require(count == 1, f"MCP server exposed {count} tools, expected 1")
    require("PROOF-OK" in reply, reply)
    require("MCP-RAG-MARKER" in reply, reply)
    rag_after = int(
        proof.psql("select count(*) from adk_audit_records where action = 'rag.retrieve'")
    )
    require(
        rag_after - rag_before == 1,
        f"rag.retrieve delta after the MCP run: {rag_before} -> {rag_after}",
    )

    runs = proof.psql("select count(*) from adk_audit_records where action = 'agent.run'")
    subjects = proof.psql(
        "select string_agg(distinct event->'principal'->>'subject', ',') "
        "from adk_audit_records where action = 'agent.run'"
    )
    require(int(runs) >= 1, f"no agent.run audit rows after the MCP call: {runs}")
    require("mcp_user" in subjects, f"MCP run was not audited as mcp_user: {subjects}")
    return Result(
        "P5 MCP HTTP",
        True,
        "anonymous call refused; authenticated initialize/list/call ran the registry agent",
        [
            f"anonymous initialize -> {anonymous.status_code}",
            f"authenticated tools: {count}, reply contains PROOF-OK and the retrieved marker",
            f"rag.retrieve rows: {rag_before} -> {rag_after}",
            f"agent.run audit rows: {runs} (subjects: {subjects})",
        ],
    )


def _a2a_text(payload: Any) -> str:
    """Collect every text part from an A2A JSON-RPC result."""
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("text"), str):
                found.append(node["text"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return "".join(found)


def check_a2a(proof: Proof) -> Result:
    """P6: A2A peer auth, per-agent grants and the inbound run audit."""
    import hashlib

    keys = _write_keys(proof.work)
    artifacts = proof.work / "artifacts-a2a"
    artifacts.mkdir(exist_ok=True)
    peers_dir = proof.work / "peers"
    peers_dir.mkdir(exist_ok=True)
    env = proof.service_env()
    env["PROOF_TOKEN"] = ADMIN_TOKEN

    project = _write_agent_project(proof.work, "proof_a2a")
    manifest_path = project / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["exposure"] = "a2a"
    manifest["rag"] = {
        "enabled": True,
        "top_k": 3,
        "min_confidence": 0.0,
        "data_classes": ["public"],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    registry, registry_url = _start_registry(proof, keys, artifacts, env)
    _publish(proof, project, keys, registry_url, env)
    _ingest_marker(proof, env, "acme", "a2a-rag", "A2A-RAG-MARKER")

    peer_token = PEER_TOKEN
    token_file = proof.work / "peer-tokens.json"
    token_file.write_text(
        json.dumps({"peer1": hashlib.sha256(peer_token.encode()).hexdigest()}),
        encoding="utf-8",
    )

    def peers_cli(*args: str) -> None:
        done = subprocess.run(  # nosec B603 B607
            [PY, "-m", "adk_agent", "peers", *args, "--peer-dir", str(peers_dir)],
            cwd=str(proof.work),
            env=env,
            capture_output=True,
            text=True,
        )
        require(done.returncode == 0, done.stderr[-800:])

    peers_cli("register", "--tenant", "acme", "--id", "peer1", "--kind", "service")

    server = proof.start_service(
        "a2a",
        [
            "serve-a2a",
            "--agent-ref",
            "acme/proof_a2a@1.0.0",
            "--manifest",
            str(manifest_path),
            "--peer-token-file",
            str(token_file),
            "--peer-dir",
            str(peers_dir),
            "--registry-url",
            registry_url,
            "--registry-token-env",
            "PROOF_TOKEN",
            "--artifact-dir",
            str(artifacts),
            "--artifact-keys",
            str(keys["artifact_keys"]),
            "--audit-db",
            proof.pg_url,
            "--rag-db",
            proof.pg_url,
            "--rag-dimensions",
            str(EMBED_DIMENSIONS),
            "--rag-model",
            "openai/proof-embed",
            "--rag-provider",
            "litellm",
            "--host",
            "127.0.0.1",
            "--port",
            "{port}",
        ],
        env=env,
    )
    base = f"http://127.0.0.1:{server.port}"
    auth = {"Authorization": f"Bearer {peer_token}"}

    deadline = time.monotonic() + 60
    while True:
        try:
            health = httpx.get(f"{base}/healthz", timeout=2)
            if health.status_code < 500:
                break
        except Exception:  # noqa: BLE001 - the server may still be binding
            health = None
        if time.monotonic() > deadline:
            raise RuntimeError("a2a server did not start")
        time.sleep(0.3)

    card_path = "/.well-known/agent-card.json"
    anonymous = httpx.get(f"{base}{card_path}", timeout=10)
    require(anonymous.status_code == 401, f"anonymous card -> {anonymous.status_code}")
    hidden = httpx.get(f"{base}{card_path}", headers=auth, timeout=10)
    require(
        hidden.status_code == 404,
        f"ungranted peer should see no card (404), got {hidden.status_code}",
    )

    def send(text: str) -> httpx.Response:
        body = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "messageId": "m1",
                    "kind": "message",
                    "parts": [{"kind": "text", "text": text}],
                },
                "configuration": {},
            },
        }
        return httpx.post(f"{base}/", json=body, headers=auth, timeout=60)

    before = send("hello before grant")
    require(before.status_code == 403, before.text)

    peers_cli("grant", "--id", "peer1", "--agent", "proof_a2a", "--actions", "read,invoke")
    card = httpx.get(f"{base}{card_path}", headers=auth, timeout=10)
    require(card.status_code == 200, card.text)
    a2a_rag_before = int(
        proof.psql("select count(*) from adk_audit_records where action = 'rag.retrieve'")
    )
    granted = send("hello a2a")
    require(granted.status_code == 200, granted.text)
    payload = granted.json()
    text = _a2a_text(payload)
    require("PROOF-OK" in text, payload)
    require("A2A-RAG-MARKER" in text, payload)
    a2a_rag = int(
        proof.psql("select count(*) from adk_audit_records where action = 'rag.retrieve'")
    )
    require(
        a2a_rag - a2a_rag_before == 1,
        f"rag.retrieve delta after A2A: {a2a_rag_before} -> {a2a_rag}",
    )

    runs = proof.psql("select count(*) from adk_audit_records where action = 'agent.run'")
    return Result(
        "P6 A2A peer",
        True,
        "peer token required, ungranted invoke denied, granted invoke ran the agent",
        [
            f"agent card: anonymous -> {anonymous.status_code}, ungranted peer -> "
            f"{hidden.status_code}, after grant -> {card.status_code}",
            f"invoke before grant -> HTTP {before.status_code}",
            f"invoke after grant -> HTTP {granted.status_code}, reply has PROOF-OK and "
            f"the retrieved marker",
            f"rag.retrieve rows: {a2a_rag_before} -> {a2a_rag}",
            f"agent.run audit rows: {runs}",
        ],
    )


def check_rag(proof: Proof) -> Result:
    """P7: real pgvector ingest/search, ACL, retrieval injection and rag.retrieve audit."""
    keys = _write_keys(proof.work)
    artifacts = proof.work / "artifacts-rag"
    artifacts.mkdir(exist_ok=True)
    env = proof.service_env()
    env["PROOF_TOKEN"] = ADMIN_TOKEN

    public_doc = proof.work / "public-doc.txt"
    public_doc.write_text("REFUND-POLICY-ALPHA refunds within 30 days.\n", encoding="utf-8")
    secret_doc = proof.work / "secret-doc.txt"
    secret_doc.write_text("SECRET-BETA-CODE internal pricing schedule.\n", encoding="utf-8")

    # The console (no OIDC) runs as tenant "local", so retrieval can only see
    # rows ingested for that tenant; production callers come from OIDC claims.
    def rag(*args: str) -> str:
        done = subprocess.run(  # nosec B603 B607
            [
                PY,
                "-m",
                "adk_agent",
                "rag",
                *args,
                "--database-url",
                proof.pg_url,
                "--dimensions",
                str(EMBED_DIMENSIONS),
                "--model",
                "openai/proof-embed",
                "--provider",
                "litellm",
                "--tenant",
                "local",
            ],
            cwd=str(proof.work),
            env=env,
            capture_output=True,
            text=True,
        )
        require(done.returncode == 0, done.stderr[-800:])
        return done.stdout.strip()

    ingested = rag(
        "ingest", "--source-id", "refunds.txt", "--text", str(public_doc), "--data-class", "public"
    )
    rag(
        "ingest",
        "--source-id",
        "pricing.txt",
        "--text",
        str(secret_doc),
        "--data-class",
        "internal",
        "--subject",
        "bob",
    )

    def search(subject: str, query: str, data_class: str) -> list[Any]:
        out = rag(
            "search",
            "--subject",
            subject,
            "--query",
            query,
            "--data-class",
            data_class,
            "--min-confidence",
            "0",
        )
        parsed = json.loads(out)
        return parsed if isinstance(parsed, list) else parsed.get("citations", [])

    public_hits = search("carol", "refund policy", "public")
    require(public_hits, f"public doc not retrievable: {public_hits}")
    hidden = search("carol", "SECRET-BETA-CODE", "internal")
    require(hidden == [], f"ACL leaked the restricted doc: {hidden}")
    bob_hits = search("bob", "SECRET-BETA-CODE", "internal")
    require(len(bob_hits) == 1, f"owner subject got {len(bob_hits)} hits, expected 1")

    project = _write_agent_project(proof.work, "proof_rag")
    manifest_path = project / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["rag"] = {
        "enabled": True,
        "top_k": 5,
        "min_confidence": 0.0,
        "data_classes": ["public"],
        "on_error": "deny",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    registry, registry_url = _start_registry(proof, keys, artifacts, env)
    _publish(proof, project, keys, registry_url, env)

    console = proof.start_service(
        "console-rag",
        [
            "console",
            "--registry-url",
            registry_url,
            "--registry-token-env",
            "PROOF_TOKEN",
            "--agent-ref",
            "acme/proof_rag@1.0.0",
            "--artifact-dir",
            str(artifacts),
            "--artifact-keys",
            str(keys["artifact_keys"]),
            "--audit-db",
            proof.pg_url,
            "--rag-db",
            proof.pg_url,
            "--rag-dimensions",
            str(EMBED_DIMENSIONS),
            "--rag-model",
            "openai/proof-embed",
            "--rag-provider",
            "litellm",
            "--allow-unauthenticated",
            "--role",
            "admin",
            "--host",
            "127.0.0.1",
            "--port",
            "{port}",
        ],
        health="http://127.0.0.1:{port}/healthz",
        env=env,
    )
    rag_before = int(
        proof.psql("select count(*) from adk_audit_records where action = 'rag.retrieve'")
    )
    chat = httpx.post(
        f"http://127.0.0.1:{console.port}/api/chat",
        json={"agent": "proof_rag", "message": "What is the refund policy?"},
        timeout=120,
    )
    require(chat.status_code == 200, chat.text)
    reply = chat.json()["reply"]
    require("REFUND-POLICY-ALPHA" in reply, reply)
    require("<retrieved_context" in reply, reply)
    require("SECRET-BETA-CODE" not in reply, "restricted document leaked into the prompt")

    audit = proof.psql(
        "select count(*), coalesce(max((event->>'rag_returned')::int), -1) "
        "from adk_audit_records where action = 'rag.retrieve'"
    )
    audit_rows, returned = (int(part) for part in audit.split("|"))
    require(
        audit_rows - rag_before == 1 and returned >= 1,
        f"rag.retrieve audit: {rag_before} -> {audit_rows} rows, max rag_returned {returned}",
    )
    leaked = proof.psql(
        "select count(*) from adk_audit_records where action = 'rag.retrieve' "
        "and event::text like '%REFUND-POLICY-ALPHA%'"
    )
    require(leaked == "0", "audit event contains chunk text")

    extension = proof.psql("select extversion from pg_extension where extname = 'vector'")
    require(bool(extension), "pgvector extension is missing")
    return Result(
        "P7 RAG",
        True,
        "console startup ref: pgvector ingest/search with ACL, injected context reached the model, "
        "retrieval audited",
        [
            "path: console --agent-ref (startup), not the on-demand load route",
            f"pgvector extension: {extension}",
            f"ingest: {ingested}",
            f"public search as carol: {len(public_hits)} hit(s); restricted as carol: 0; "
            f"as bob: {len(bob_hits)}",
            "chat reply contained the retrieved marker and envelope: yes",
            f"rag.retrieve rows: {rag_before} -> {audit_rows}, max rag_returned: {returned}, "
            f"chunk text in audit: no",
        ],
    )


def check_model_gateway(proof: Proof) -> Result:
    """P8: the model gateway resolves policy from the registry and audits calls."""
    keys = _write_keys(proof.work)
    artifacts = proof.work / "artifacts-gw"
    artifacts.mkdir(exist_ok=True)
    env = proof.service_env()
    env["PROOF_TOKEN"] = ADMIN_TOKEN

    project = _write_agent_project(proof.work, "proof_gw")
    registry, registry_url = _start_registry(proof, keys, artifacts, env)
    _publish(proof, project, keys, registry_url, env)
    digest = _record_digest(registry_url, "acme", "proof_gw")

    gateway = proof.start_service(
        "model-gateway",
        [
            "serve-model-gateway",
            "--registry-url",
            registry_url,
            "--registry-token-env",
            "PROOF_TOKEN",
            "--audit-db",
            proof.pg_url,
            "--allow-unauthenticated",
            "--host",
            "127.0.0.1",
            "--port",
            "{port}",
        ],
        health="http://127.0.0.1:{port}/healthz",
        env=env,
    )
    url = f"http://127.0.0.1:{gateway.port}/v1/complete"

    def complete(provider: str, model: str, run: str = "1") -> httpx.Response:
        return httpx.post(
            url,
            json={
                "invocation": _invocation("acme", "proof_gw", digest, run),
                "request": {
                    "provider": provider,
                    "model": model,
                    "messages": [{"role": "user", "content": "hello gateway"}],
                },
            },
            timeout=60,
        )

    allowed = complete("litellm", STUB_MODEL)
    require(allowed.status_code == 200, allowed.text)
    require(allowed.json()["text"].startswith("PROOF-OK"), allowed.text)
    denied = complete("gemini", "gemini-2.5-pro", run="2")
    require(denied.status_code == 403, denied.text)
    require(denied.json()["error"] == "model_denied", denied.text)
    denied_model = complete("litellm", "openai/not-allowed", run="3")
    require(denied_model.status_code == 403, denied_model.text)
    require(denied_model.json()["error"] == "model_denied", denied_model.text)
    model_denials = proof.psql(
        "select count(*) from adk_audit_records where action = 'model.call' "
        "and event->>'error_code' = 'model_not_allowed'"
    )
    require(int(model_denials) == 1, f"model_not_allowed audit rows: {model_denials}")

    audits = proof.psql("select count(*) from adk_audit_records where action = 'model.call'")
    require(int(audits) >= 2, f"model.call audit rows: {audits}")
    return Result(
        "P8 model gateway",
        True,
        "provider and model allowlists enforced by the gateway, denials audited",
        [
            f"allowlisted provider -> {allowed.status_code} {allowed.json()['text'][:20]!r}",
            f"provider outside the allowlist -> {denied.status_code} {denied.json()['error']}",
            f"model outside the allowlist -> {denied_model.status_code} "
            f"{denied_model.json()['error']}, audit error_code rows {model_denials}",
            f"model.call audit rows: {audits}",
        ],
    )


def check_approvals(proof: Proof) -> Result:
    """P9: approvals cross processes; concurrent decisions have one winner."""
    import asyncio
    from datetime import datetime, timedelta, timezone

    from adk_agent.approvals_postgres import PostgresApprovalInbox
    from adk_agent.core import AgentRef, ApprovalRequest, Principal

    env = proof.service_env()
    placeholder = proof.work / "approval_agent.py"
    placeholder.write_text(
        "from google.adk.agents import LlmAgent\n"
        "from adk_agent import build_model\n"
        "\n"
        "agent = LlmAgent(name='approval_agent', model=build_model(), instruction='proof')\n",
        encoding="utf-8",
    )
    console = proof.start_service(
        "console-approvals",
        [
            "console",
            "--agents",
            str(placeholder),
            "--approval-db",
            proof.pg_url,
            "--approval-ttl",
            "2",
            "--audit-db",
            proof.pg_url,
            "--allow-unauthenticated",
            "--role",
            "admin",
            "--host",
            "127.0.0.1",
            "--port",
            "{port}",
        ],
        health="http://127.0.0.1:{port}/healthz",
        env=env,
    )
    base = f"http://127.0.0.1:{console.port}"

    async def submit(request_id: str, expires: datetime | None) -> None:
        inbox = PostgresApprovalInbox(proof.pg_url)
        try:
            await inbox.submit(
                ApprovalRequest(
                    request_id=request_id,
                    run_id=f"run-{request_id}",
                    trace_id=f"trace-{request_id}",
                    step_id="step-1",
                    agent_ref=AgentRef(id="approval_agent", version="1.0.0", digest="b" * 64),
                    principal=Principal(tenant="local", subject="alice", kind="human"),
                    input="escalate",
                    requested_at=datetime.now(timezone.utc),
                    expires_at=expires,
                )
            )
        finally:
            await inbox.aclose()

    asyncio.run(submit("race-1", None))
    # A minute in the past survives host/container clock skew (measured ~4 s).
    asyncio.run(submit("expiring-1", datetime.now(timezone.utc) - timedelta(seconds=60)))

    pending = httpx.get(f"{base}/api/approvals", timeout=10).json()
    ids = {item["request_id"] for item in pending}
    require("race-1" in ids, pending)
    require("expiring-1" not in ids, "expired request still pending")

    import concurrent.futures

    def decide(approved: bool) -> int:
        return httpx.post(
            f"{base}/api/approvals/race-1",
            json={"approved": approved, "reason": "proof"},
            timeout=10,
        ).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(decide, (True, False)))
    require(statuses == [200, 409], f"concurrent decisions: {statuses}")

    history = httpx.get(f"{base}/api/approvals/history?limit=50", timeout=10)
    require(history.status_code == 200, history.text)
    decided = [item for item in history.json() if item["request"]["request_id"] == "race-1"]
    require(decided, history.text)

    return Result(
        "P9 approvals",
        True,
        "Postgres inbox shared with the console; concurrent decisions have one winner",
        [
            f"pending before decision: {sorted(ids)}",
            f"concurrent approve/deny -> HTTP {statuses}",
            f"history returned {len(decided)} record(s) for the decided request",
        ],
    )


def check_triggers(proof: Proof) -> Result:
    """P10: webhook triggers pin a version, dedupe by key and refuse HITL agents."""
    keys = _write_keys(proof.work)
    artifacts = proof.work / "artifacts-trigger"
    artifacts.mkdir(exist_ok=True)
    env = proof.service_env()
    env["PROOF_TOKEN"] = ADMIN_TOKEN
    env["PROOF_HOOK"] = HOOK_TOKEN

    project = _write_agent_project(proof.work, "proof_trigger")
    approval_project = _write_agent_project(proof.work, "proof_trigger_hitl")
    approval_manifest = approval_project / "manifest.json"
    data = json.loads(approval_manifest.read_text(encoding="utf-8"))
    data["tool_grants"] = [{"tool_id": "danger", "requires_approval": True}]
    approval_manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")

    registry, registry_url = _start_registry(proof, keys, artifacts, env)
    _publish(proof, project, keys, registry_url, env)
    _publish(proof, approval_project, keys, registry_url, env)
    digest = _record_digest(registry_url, "acme", "proof_trigger")
    hitl_digest = _record_digest(registry_url, "acme", "proof_trigger_hitl")

    def register(trigger_id: str, agent_id: str, agent_digest: str) -> None:
        done = subprocess.run(  # nosec B603 B607
            [
                PY,
                "-m",
                "adk_agent",
                "triggers",
                "register",
                "--tenant",
                "acme",
                "--id",
                trigger_id,
                "--agent-id",
                agent_id,
                "--version",
                "1.0.0",
                "--digest",
                f"sha256:{agent_digest}",
                "--webhook-token-env",
                "PROOF_HOOK",
                "--input",
                "hello trigger",
                "--db",
                proof.pg_url,
            ],
            cwd=str(proof.work),
            env=env,
            capture_output=True,
            text=True,
        )
        require(done.returncode == 0, done.stderr[-800:])

    register("hook-ok", "proof_trigger", digest)
    register("hook-hitl", "proof_trigger_hitl", hitl_digest)

    service = proof.start_service(
        "triggers",
        [
            "serve-triggers",
            "--trigger-db",
            proof.pg_url,
            "--registry-url",
            registry_url,
            "--registry-token-env",
            "PROOF_TOKEN",
            "--artifact-dir",
            str(artifacts),
            "--artifact-keys",
            str(keys["artifact_keys"]),
            "--audit-db",
            proof.pg_url,
            "--no-scheduler",
            "--host",
            "127.0.0.1",
            "--port",
            "{port}",
        ],
        health="http://127.0.0.1:{port}/healthz",
        env=env,
    )
    base = f"http://127.0.0.1:{service.port}"

    def fire(trigger_id: str, *, key: str | None, token: str | None = HOOK_TOKEN) -> httpx.Response:
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if key is not None:
            headers["Idempotency-Key"] = key
        return httpx.post(
            f"{base}/v1/tenants/acme/triggers/{trigger_id}/fire",
            json={},
            headers=headers,
            timeout=60,
        )

    anonymous = fire("hook-ok", key=None, token=None)
    require(anonymous.status_code == 401, anonymous.text)
    first = fire("hook-ok", key="fire-1")
    require(first.status_code == 200, first.text)
    require(first.json()["status"] == "ok", first.text)
    require("PROOF-OK" in first.json()["text"], first.text)
    again = fire("hook-ok", key="fire-1")
    require(again.status_code == 200, again.text)
    require(again.json()["duplicate"] is True, again.text)
    require(again.json()["run_id"] == first.json()["run_id"], again.text)

    hitl = fire("hook-hitl", key="fire-2")
    require(hitl.status_code == 409 and hitl.json()["error"] == "approval_required", hitl.text)

    runs = proof.psql("select count(*) from adk_audit_records where action = 'agent.run'")
    return Result(
        "P10 triggers",
        True,
        "webhook auth, pinned run, idempotent replay and HITL refusal all observed",
        [
            f"anonymous fire -> {anonymous.status_code}",
            f"first fire -> {first.status_code} {first.json()['status']}",
            f"same idempotency key -> duplicate={again.json()['duplicate']}, same run_id",
            f"agent with an approval-required grant -> {hitl.status_code} {hitl.json()['error']}",
            f"agent.run audit rows: {runs}",
        ],
    )


def check_quota(proof: Proof) -> Result:
    """P11: two console processes share one Postgres quota counter."""
    env = proof.service_env()
    env["QUOTA_URL"] = proof.pg_url
    placeholder = proof.work / "quota_agent.py"
    placeholder.write_text(
        "from google.adk.agents import LlmAgent\n"
        "from adk_agent import build_model\n"
        "\n"
        "agent = LlmAgent(name='quota_agent', model=build_model(), instruction='proof')\n",
        encoding="utf-8",
    )
    quota_config = proof.work / "quota.json"
    quota_config.write_text(
        json.dumps({"tenants": {"local": {"max_runs": 1, "window_seconds": 300}}}),
        encoding="utf-8",
    )
    consoles = []
    for name in ("console-q1", "console-q2"):
        consoles.append(
            proof.start_service(
                name,
                [
                    "console",
                    "--agents",
                    str(placeholder),
                    "--quota-config",
                    str(quota_config),
                    "--allow-unauthenticated",
                    "--role",
                    "admin",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "{port}",
                ],
                health="http://127.0.0.1:{port}/healthz",
                env=env,
            )
        )

    statuses = []
    for console in consoles:
        chat = httpx.post(
            f"http://127.0.0.1:{console.port}/api/chat",
            json={"agent": "quota_agent", "message": "hello quota"},
            timeout=60,
        )
        statuses.append(chat.status_code)
        if chat.status_code == 200:
            require("PROOF-OK" in chat.json()["reply"], chat.text)
        else:
            require(chat.json()["error"] == "quota_exceeded", chat.text)
    require(statuses == [200, 429], statuses)
    third = httpx.post(
        f"http://127.0.0.1:{consoles[0].port}/api/chat",
        json={"agent": "quota_agent", "message": "Hello quota"},
        timeout=60,
    )
    require(third.status_code == 429, third.text)
    return Result(
        "P11 shared quota",
        True,
        "one Postgres counter is enforced across two console processes",
        [
            f"process 1 -> {statuses[0]}, process 2 -> {statuses[1]}",
            f"process 1 again after process 2 -> {third.status_code}",
        ],
    )


def check_backup(proof: Proof) -> Result:
    """P12: back up registry, approvals and audit, restore elsewhere, chain still verifies."""
    import asyncio
    import tarfile

    from adk_agent.approvals import FileApprovalInbox
    from adk_agent.audit import AuditPipeline, verify_audit_file

    root = proof.work / "backup-src"
    registry_dir = root / "registry"
    approvals_dir = root / "approvals"
    audit_file = root / "audit" / "audit.jsonl"
    for directory in (registry_dir, approvals_dir, audit_file.parent):
        directory.mkdir(parents=True, exist_ok=True)

    env = proof.service_env()
    project = _write_agent_project(proof.work, "proof_backup")
    done = subprocess.run(  # nosec B603 B607
        [
            PY,
            "-m",
            "adk_agent",
            "publish",
            str(project / "manifest.json"),
            "--registry",
            str(registry_dir),
        ],
        cwd=str(proof.work),
        env=env,
        capture_output=True,
        text=True,
    )
    require(done.returncode == 0, done.stderr[-800:])

    asyncio.run(AuditPipeline(audit_file).append(_audit_event("local", 0)))
    inbox = FileApprovalInbox(approvals_dir)
    inbox.submit(_approval_request("backup-req"))
    require(verify_audit_file(audit_file) == 1)

    archive = proof.work / "backup.zip"
    backup = subprocess.run(  # nosec B603 B607
        [
            PY,
            "-m",
            "adk_agent",
            "backup",
            "--out",
            str(archive),
            "--registry",
            str(registry_dir),
            "--approvals",
            str(approvals_dir),
            "--audit",
            str(audit_file),
        ],
        cwd=str(proof.work),
        env=env,
        capture_output=True,
        text=True,
    )
    require(backup.returncode == 0, backup.stderr[-800:])
    with tarfile.open(archive, "r:gz") as bundle:
        names = set(bundle.getnames())
    require(any(name.startswith("registry/") for name in names), sorted(names)[:10])
    require(any(name.startswith("approvals/") for name in names), sorted(names)[:10])

    dest = proof.work / "backup-dest"
    restore = subprocess.run(  # nosec B603 B607
        [PY, "-m", "adk_agent", "restore", "--archive", str(archive), "--dest", str(dest)],
        cwd=str(proof.work),
        env=env,
        capture_output=True,
        text=True,
    )
    require(restore.returncode == 0, restore.stderr[-800:])

    restored_audit = next(dest.rglob("audit.jsonl"), None)
    require(restored_audit is not None, sorted(str(p.relative_to(dest)) for p in dest.rglob("*")))
    require(verify_audit_file(restored_audit) == 1)
    restored_manifests = list(dest.rglob("*.json"))
    restored_ids = []
    for path in restored_manifests:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        manifest = data.get("manifest") if isinstance(data, dict) else None
        restored_ids.append(
            (manifest or data).get("id") if isinstance(manifest or data, dict) else None
        )
    require(
        "proof_backup" in restored_ids,
        f"restored registry records: {restored_ids}",
    )
    return Result(
        "P12 backup/restore",
        True,
        "archive restored into a fresh directory; the audit chain still verifies",
        [
            f"backup entries: {len(names)}",
            f"restored audit chain verifies: {verify_audit_file(restored_audit)} record",
            f"restored files: {len(restored_manifests)} json",
        ],
    )


def check_console_ui(proof: Proof) -> Result:
    """P13: the console index serves the design-token and metric-card baseline."""
    placeholder = proof.work / "ui_agent.py"
    placeholder.write_text(
        "from google.adk.agents import LlmAgent\n"
        "from adk_agent import build_model\n"
        "\n"
        "agent = LlmAgent(name='ui_agent', model=build_model(), instruction='proof')\n",
        encoding="utf-8",
    )
    console = proof.start_service(
        "console-ui",
        [
            "console",
            "--agents",
            str(placeholder),
            "--allow-unauthenticated",
            "--role",
            "admin",
            "--host",
            "127.0.0.1",
            "--port",
            "{port}",
        ],
        health="http://127.0.0.1:{port}/healthz",
        env=proof.service_env(),
    )
    page = httpx.get(f"http://127.0.0.1:{console.port}/", timeout=10)
    require(page.status_code == 200, page.text)
    html = page.text
    for marker in (
        "--radius-lg:",
        "--shadow-card:",
        "--space-1:",
        ".metric-grid",
        ".stat-card",
        ".stat-label",
        ".stat-value",
        ".stat-delta",
    ):
        require(marker in html, f"missing marker {marker}")
    require('id="overview"' in html, "missing overview panel")
    overview = httpx.get(f"http://127.0.0.1:{console.port}/api/overview", timeout=10)
    require(overview.status_code == 200, overview.text)
    cards = overview.json().get("cards", [])
    require(len(cards) == 4, f"expected 4 overview cards, got {len(cards)}")
    require(
        [card["key"] for card in cards] == ["approvals", "agents", "tools", "grants"],
        f"unexpected overview cards: {cards}",
    )
    require('id="audit-panel"' in html, "missing audit panel")
    require('id="quota"' in html, "missing quota panel")
    require('id="rag"' in html, "missing rag panel")
    require('id="model"' in html, "missing model panel")
    require('id="semantics"' in html, "missing semantics panel")
    require('id="import"' in html, "missing import panel")
    require('id="ask-ai"' in html, "missing ask-ai panel")
    with httpx.stream(f"http://127.0.0.1:{console.port}/api/live", timeout=10) as live:
        require(live.status_code == 200, f"live status {live.status_code}")
        first = next(live.iter_text())
        require("event: tick" in first, f"live first event: {first!r}")
    rag = httpx.get(f"http://127.0.0.1:{console.port}/api/rag", timeout=10)
    require(rag.status_code == 200, rag.text)
    require("recent_retrievals" in rag.json(), rag.text)
    model = httpx.get(f"http://127.0.0.1:{console.port}/api/model", timeout=10)
    require(model.status_code == 200, model.text)
    require("recent_calls" in model.json(), model.text)
    return Result(
        "P13 console UI baseline, overview and panels",
        True,
        "index HTML carries the design tokens, metric-card system, overview and capability panels",
        [
            "design tokens --radius-lg/--shadow-card/--space-1 present",
            "metric-card classes .metric-grid/.stat-card/.stat-label/.stat-value/.stat-delta present",
            "overview panel + /api/overview with 4 cards present",
            "audit-panel, quota, rag and model panels present",
        ],
    )


CHECKS = {
    "P1": check_env,
    "P2": check_audit,
    "P3": check_registry_chat,
    "P4": check_tools,
    "P5": check_mcp,
    "P6": check_a2a,
    "P7": check_rag,
    "P8": check_model_gateway,
    "P9": check_approvals,
    "P10": check_triggers,
    "P11": check_quota,
    "P12": check_backup,
    "P13": check_console_ui,
}
SMOKE_CHECKS = ("P1", "P2", "P3", "P4")


def select_checks(only: str | None, smoke: bool) -> list[str]:
    """Return the check ids to run: the smoke subset, an explicit list, or all."""
    if smoke:
        return list(SMOKE_CHECKS)
    if only:
        return [item.strip() for item in only.split(",")]
    return list(CHECKS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--only", default=None, help="comma separated check ids, e.g. P2,P3")
    group.add_argument(
        "--smoke",
        action="store_true",
        help="run the release subset (P1-P4) instead of every check",
    )
    parser.add_argument("--keep", action="store_true", help="keep the work directory")
    parser.add_argument("--work", default=None, help="explicit work directory")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="adk-prove-"))
    work.mkdir(parents=True, exist_ok=True)
    proof = Proof(work)
    checks = CHECKS
    selected = select_checks(args.only, args.smoke)

    try:
        proof.start_stub()
        proof.start_postgres()
        for name in selected:
            func = checks.get(name)
            if func is None:
                proof.results.append(Result(name, False, "unknown check", []))
                continue
            started = time.perf_counter()
            try:
                result = func(proof)
            except Exception as exc:  # noqa: BLE001
                result = Result(name, False, f"exception: {type(exc).__name__}: {exc}", [])
            result.detail += f" ({time.perf_counter() - started:.1f}s)"
            proof.results.append(result)
    finally:
        proof.stop_all()

    width = max(len(result.check) for result in proof.results) if proof.results else 4
    for result in proof.results:
        mark = "PASS" if result.ok else "FAIL"
        print(f"[{mark}] {result.check.ljust(width)}  {result.detail}")
        for line in result.evidence:
            print(f"       - {line}")
    report = {
        "work": str(work),
        "results": [
            {"check": r.check, "ok": r.ok, "detail": r.detail, "evidence": r.evidence}
            for r in proof.results
        ],
    }
    (work / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    passed = all(result.ok for result in proof.results)
    if args.keep or args.work:
        print(f"\nreport: {work / 'report.json'}")
    else:
        # The work dir holds generated signing keys and service logs; keep it
        # only when asked.
        for _ in range(5):
            shutil.rmtree(work, ignore_errors=True)
            if not work.exists():
                break
            time.sleep(0.2)
        if work.exists():
            print(f"\nwarning: work dir could not be removed: {work}")
        else:
            print("\nreport: not kept (pass --keep to retain it)")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
