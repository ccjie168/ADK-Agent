"""Seed a local pilot demo: signed agents, an eval report and a pending approval.

Usage:
    python scripts/demo_seed.py [--root demo] [--tenant acme]

The script writes a demo state directory with a publisher key pair, two
artifact-backed published agents, one eval report and one approval request.
It prints the environment export and the console command to run next.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_INSTALL_HINT = "install publishing support with: pip install 'adk-agent[publish]'"
_KEY_ID = "demo-publisher"


def _load_or_create_key(root: Path):
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        print(_INSTALL_HINT, file=sys.stderr)
        raise SystemExit(1) from None

    pem_path = root / "key.pem"
    keys_path = root / "keys.json"
    if pem_path.is_file() and keys_path.is_file():
        try:
            key = serialization.load_pem_private_key(pem_path.read_bytes(), password=None)
            stored = json.loads(keys_path.read_text(encoding="utf-8"))[_KEY_ID]
            derived = (
                key.public_key()
                .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
                .hex()
            )
            if isinstance(key, Ed25519PrivateKey) and derived == stored:
                return key
        except Exception:  # noqa: BLE001
            key = None

    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_hex = (
        key.public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex()
    )
    pem_path.write_bytes(pem)
    keys_path.write_text(json.dumps({_KEY_ID: public_hex}, indent=2) + "\n", encoding="utf-8")
    return key


def _write_project(root: Path, tenant: str, agent_id: str) -> Path:
    from adk_agent.core import AgentManifest

    source = root / "projects" / agent_id
    source.mkdir(parents=True, exist_ok=True)
    manifest = AgentManifest(
        id=agent_id,
        version="1.0.0",
        tenant=tenant,
        owner=tenant,
        description=f"Demo agent {agent_id}",
        model_policy={"provider_allowlist": ["litellm"]},
        execution_tier="in_process",
    )
    (source / "manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (source / "agent.py").write_text(
        "from google.adk.agents import LlmAgent\n"
        "\n"
        f"agent = LlmAgent(name={agent_id!r}, model='gemini-2.5-pro', instruction='x')\n",
        encoding="utf-8",
    )
    return source


async def _seed(root: Path, tenant: str, key) -> None:
    from adk_agent.approvals import FileApprovalInbox
    from adk_agent.core import (
        AgentArtifact,
        AgentRef,
        ApprovalRequest,
        EvalCaseResult,
        EvalReport,
        Principal,
    )
    from adk_agent.registry import (
        FileAgentRegistry,
        FileArtifactStore,
        FileEvalReportStore,
        artifact_digest,
        load_manifest,
        pack_agent,
        published_from,
        sign_digest,
    )

    registry = FileAgentRegistry(root / "registry")
    store = FileArtifactStore(root / "store")
    records = {}
    for agent_id in ("bot_a", "bot_b"):
        source = _write_project(root, tenant, agent_id)
        manifest = load_manifest(source / "manifest.json")
        data = pack_agent(source)
        digest = artifact_digest(data)
        artifact = AgentArtifact(
            digest=digest,
            size=len(data),
            signature=sign_digest(digest, key),
            key_id=_KEY_ID,
        )
        await store.put(artifact, data)
        records[agent_id] = await registry.publish(published_from(manifest, artifact=artifact))

    await FileEvalReportStore(root / "registry").put(
        tenant,
        "bot_a",
        "1.0.0",
        EvalReport(
            suite_id="demo-smoke",
            version="1.0.0",
            passed=2,
            total=2,
            results=[
                EvalCaseResult(case_id="greeting", passed=True, actual="hello"),
                EvalCaseResult(case_id="refund", passed=True, actual="refund queued"),
            ],
        ),
    )

    record = records["bot_a"]
    request = ApprovalRequest(
        request_id="demo-approval-1",
        run_id="demo-run-1",
        trace_id="demo-trace-1",
        step_id="step-1",
        agent_ref=AgentRef(
            id=record.manifest.id,
            version=record.manifest.version,
            digest=record.digest,
            artifact_digest=record.artifact.digest if record.artifact else None,
        ),
        principal=Principal(tenant=tenant, subject="demo-reviewer", kind="human"),
        input="Send the customer a refund confirmation email.",
        reason="External side effect requires a human decision.",
        requested_at=datetime.now(timezone.utc),
    )
    inbox = FileApprovalInbox(root / "approvals")
    if inbox.get(request.request_id) is None:
        inbox.submit(request)


def _print_next_steps(root: Path, tenant: str) -> None:
    keys = (root / "keys.json").as_posix()
    registry = (root / "registry").as_posix()
    store = (root / "store").as_posix()
    approvals = (root / "approvals").as_posix()
    print("demo seed complete")
    print(f"  private key: {(root / 'key.pem').as_posix()} (keep it local)")
    print(f"  public keys: {keys}")
    print("")
    print("export the trusted publisher keys before starting the console:")
    print(f'  export ADK_ARTIFACT_KEYS="$(cat {keys})"')
    print("")
    print("start the console with:")
    print(
        "  ./.venv/Scripts/python.exe -m adk_agent console"
        f" --registry {registry}"
        f" --artifact-dir {store}"
        f" --approval-dir {approvals}"
        f" --agent-ref {tenant}/bot_a@1.0.0"
        f" --agent-ref {tenant}/bot_b@1.0.0"
    )
    print("")
    print(f"sample --agent-ref: {tenant}/bot_b@1.0.0")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the pilot demo state.")
    parser.add_argument("--root", default="demo", help="demo state directory (default: demo)")
    parser.add_argument(
        "--tenant", default="acme", help="tenant for the published agents (default: acme)"
    )
    args = parser.parse_args()

    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    key = _load_or_create_key(root)
    asyncio.run(_seed(root, args.tenant, key))
    _print_next_steps(root, args.tenant)


if __name__ == "__main__":
    main()
