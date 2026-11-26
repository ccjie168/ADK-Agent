#!/usr/bin/env python3
"""Register the support-demo mock services as console-visible connectors."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adk_agent.core import ConnectorSpec, CredentialBinding  # noqa: E402
from adk_agent.registry import FileConnectorStore, FileCredentialStore  # noqa: E402

_SECRET_REF = "secret://local/mock_token"  # nosec B105  # reference, not a secret  # pragma: allowlist secret


def _specs(base_url: str, tenant: str) -> list[ConnectorSpec]:
    return [
        ConnectorSpec(
            connector_id="mock-itsm",
            tenant=tenant,
            kind="http",
            base_url=base_url,
            auth_ref=_SECRET_REF,
            methods=["GET", "POST"],
            path_prefixes=["/itsm/"],
            risk_level="L3",
        ),
        ConnectorSpec(
            connector_id="mock-quark",
            tenant=tenant,
            kind="http",
            base_url=base_url,
            auth_ref=_SECRET_REF,
            methods=["GET", "POST"],
            path_prefixes=["/quark/"],
            risk_level="L2",
        ),
    ]


async def _write(connectors_dir: Path, credentials_dir: Path, base_url: str, tenant: str) -> None:
    binding = CredentialBinding(
        credential_id="mock-token-ref",
        tenant=tenant,
        secret_ref=_SECRET_REF,
        description="mock services bearer token",
        created_by="support-demo",
        created_at=datetime.now(timezone.utc),
    )
    credentials = FileCredentialStore(credentials_dir)
    if await credentials.get(tenant, binding.credential_id) is None:
        await credentials.add(binding)
    store = FileConnectorStore(connectors_dir)
    for spec in _specs(base_url, tenant):
        await store.add(spec)


def main() -> None:
    parser = argparse.ArgumentParser(description="Register the support demo connectors.")
    parser.add_argument("--connectors-dir", required=True)
    parser.add_argument("--credentials-dir", required=True)
    parser.add_argument("--tenant", default="local")
    parser.add_argument("--base-url", default="http://127.0.0.1:8055")
    args = parser.parse_args()

    asyncio.run(
        _write(
            Path(args.connectors_dir),
            Path(args.credentials_dir),
            args.base_url,
            args.tenant,
        )
    )
    print("registered mock-itsm and mock-quark")
    print(f"  connectors: {args.connectors_dir}")
    print(f"  credentials: {args.credentials_dir}")
    print("  set ADK_SECRET_LOCAL_MOCK_TOKEN to the mock token before the console starts")


if __name__ == "__main__":
    main()
