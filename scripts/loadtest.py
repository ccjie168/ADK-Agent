#!/usr/bin/env python3
"""Reproducible load baseline for quota reservation and audit append."""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import math
import os
import secrets
import sys
import time
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from adk_agent.audit import AuditPipeline, verify_audit_file
from adk_agent.core import AgentRef, AuditEvent, Principal, QuotaExceeded, QuotaPolicy
from adk_agent.runtime.quota_postgres import PostgresQuotaManager, build_quota_manager

MAX_RECORDS = 200_000
MAX_REQUESTS = 200_000

_AUDIT_TENANT = "loadtest"


class LoadtestError(Exception):
    """A load-test input is outside the supported range."""


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile: rank ``ceil(q/100*n)``, index ``rank - 1``."""
    if not values:
        return 0.0
    rank = math.ceil(q / 100.0 * len(values))
    index = min(max(rank - 1, 0), len(values) - 1)
    return float(sorted(values)[index])


def _require_count(name: str, value: int, maximum: int | None = None) -> None:
    if value < 1:
        raise LoadtestError(f"{name} must be at least 1")
    if maximum is not None and value > maximum:
        raise LoadtestError(f"{name} must not exceed {maximum}")


def _latency_stats(seconds: Sequence[float]) -> dict[str, float]:
    milliseconds = [value * 1000.0 for value in seconds]
    return {
        "p50": round(percentile(milliseconds, 50), 3),
        "p95": round(percentile(milliseconds, 95), 3),
        "p99": round(percentile(milliseconds, 99), 3),
        "max": round(percentile(milliseconds, 100), 3),
    }


def _throughput(count: int, elapsed: float) -> float:
    return round(count / elapsed, 3) if elapsed > 0 else 0.0


def _loadtest_event() -> AuditEvent:
    return AuditEvent(
        event_id=uuid.uuid4().hex,
        run_id=uuid.uuid4().hex,
        trace_id=uuid.uuid4().hex,
        tenant=_AUDIT_TENANT,
        principal=Principal(tenant=_AUDIT_TENANT, subject=_AUDIT_TENANT, kind="service"),
        agent_ref=AgentRef(id=_AUDIT_TENANT, version="1", digest="0" * 64),
        action="loadtest.append",
        target=_AUDIT_TENANT,
        status="ok",
        timestamp=datetime.now(timezone.utc),
    )


async def run_quota(
    requests: int,
    concurrency: int,
    *,
    max_runs: int | None = None,
    max_concurrent: int | None = None,
    window_seconds: float = 60.0,
    lease_seconds: float = 300.0,
    hold_seconds: float = 0.0,
    url: str | None = None,
    tenant: str | None = None,
) -> dict[str, object]:
    """Reserve ``requests`` times through ``concurrency`` worker loops."""
    _require_count("requests", requests, MAX_REQUESTS)
    _require_count("concurrency", concurrency)
    if max_runs is None and max_concurrent is None:
        raise LoadtestError("quota needs max_runs or max_concurrent")
    if max_runs is not None:
        _require_count("max_runs", max_runs)
    if max_concurrent is not None:
        _require_count("max_concurrent", max_concurrent)
    if window_seconds <= 0:
        raise LoadtestError("window_seconds must be positive")
    if lease_seconds < 0:
        raise LoadtestError("lease_seconds must be non-negative")
    if hold_seconds < 0:
        raise LoadtestError("hold_seconds must be non-negative")

    tenant = tenant or f"loadtest-{secrets.token_hex(4)}"
    policy = QuotaPolicy(
        max_runs=max_runs,
        window_seconds=window_seconds,
        max_concurrent=max_concurrent,
    )
    manager = (
        PostgresQuotaManager(url, lease_seconds=lease_seconds) if url else build_quota_manager(url)
    )

    started_at = datetime.now(timezone.utc).isoformat()
    pending = itertools.count()
    ok = denied = errors = 0
    active = peak_active = 0
    latencies: list[float] = []

    async def worker() -> None:
        nonlocal ok, denied, errors, active, peak_active
        while True:
            request_index = next(pending)
            if request_index >= requests:
                return
            entered = time.perf_counter()
            try:
                async with manager.reserve(tenant, policy):
                    enter_seconds = time.perf_counter() - entered
                    active += 1
                    peak_active = max(peak_active, active)
                    try:
                        if hold_seconds > 0:
                            await asyncio.sleep(hold_seconds)
                    finally:
                        active -= 1
            except QuotaExceeded:
                latencies.append(time.perf_counter() - entered)
                denied += 1
            except Exception:
                latencies.append(time.perf_counter() - entered)
                errors += 1
            else:
                latencies.append(enter_seconds)
                ok += 1

    started = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(concurrency)))
    elapsed = time.perf_counter() - started

    invariants = [{"name": "counts_balance", "holds": ok + denied + errors == requests}]
    if max_runs is not None:
        cap = min(requests, max_runs)
        invariants.append({"name": "no_oversell", "holds": ok <= cap})
        if max_concurrent is None:
            invariants.append({"name": "run_cap_saturated", "holds": ok == cap})
    if max_concurrent is not None:
        invariants.append({"name": "peak_within_limit", "holds": peak_active <= max_concurrent})
    invariants.append({"name": "no_errors", "holds": errors == 0})

    return {
        "scenario": "quota",
        "started_at": started_at,
        "tenant": tenant,
        "requests": requests,
        "concurrency": concurrency,
        "ok": ok,
        "denied": denied,
        "errors": errors,
        "latency_ms": _latency_stats(latencies),
        "throughput_per_s": _throughput(requests, elapsed),
        "peak_active": peak_active,
        "invariants": invariants,
    }


async def run_audit(
    records: int,
    path: str | Path,
    *,
    append: bool = False,
    max_records: int | None = None,
    signing_key: str | None = None,
) -> dict[str, object]:
    """Append ``records`` events and verify the resulting audit chain."""
    if records < 1 or records > MAX_RECORDS:
        raise LoadtestError(f"records must be between 1 and {MAX_RECORDS}")
    if max_records is not None and max_records < 1:
        raise LoadtestError("max_records must be at least 1")
    target = Path(path)
    if target.exists() and not append:
        raise LoadtestError(f"refusing to overwrite existing audit file {target}")

    started_at = datetime.now(timezone.utc).isoformat()
    base = 0
    verified = True
    errors = 0
    if append and target.exists():
        try:
            base = verify_audit_file(target, signing_key=signing_key)
        except Exception as exc:
            raise LoadtestError(
                f"existing audit chain does not verify ({type(exc).__name__})"
            ) from exc

    pipeline = AuditPipeline(target, max_records=max_records, signing_key=signing_key)
    latencies: list[float] = []
    ok = 0
    started = time.perf_counter()
    for _ in range(records):
        attempt = time.perf_counter()
        try:
            await pipeline.append(_loadtest_event())
        except Exception:
            errors += 1
        else:
            ok += 1
        latencies.append(time.perf_counter() - attempt)
    elapsed = time.perf_counter() - started

    verify_records = 0
    try:
        verify_records = verify_audit_file(target, signing_key=signing_key)
    except Exception:
        verified = False
        errors += 1

    invariants = [
        {"name": "no_errors", "holds": errors == 0},
        {
            "name": "chain_verifies",
            "holds": verified and verify_records == base + records,
        },
    ]

    return {
        "scenario": "audit",
        "started_at": started_at,
        "requests": records,
        "ok": ok,
        "denied": 0,
        "errors": errors,
        "latency_ms": _latency_stats(latencies),
        "throughput_per_s": _throughput(records, elapsed),
        "verify_records": verify_records,
        "invariants": invariants,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reproducible quota and audit load baseline.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    quota = subcommands.add_parser("quota", help="reserve quota under concurrency")
    quota.add_argument("--requests", type=int, required=True)
    quota.add_argument("--concurrency", type=int, default=1)
    quota.add_argument("--url", default=os.environ.get("LOADTEST_URL"))
    quota.add_argument("--max-runs", type=int)
    quota.add_argument("--max-concurrent", type=int)
    quota.add_argument("--window-seconds", type=float, default=60.0)
    quota.add_argument("--lease-seconds", type=float, default=300.0)
    quota.add_argument("--hold-seconds", type=float, default=0.0)
    quota.add_argument("--tenant")
    quota.add_argument("--out")

    audit = subcommands.add_parser("audit", help="append and verify audit records")
    audit.add_argument("--records", type=int, required=True)
    audit.add_argument("--path", required=True)
    audit.add_argument("--append", action="store_true")
    audit.add_argument("--max-records", type=int)
    audit.add_argument("--signing-key-env", default="ADK_AUDIT_SIGNING_KEY")
    audit.add_argument("--out")

    return parser


def _emit(report: dict[str, object], out: str | None) -> None:
    text = json.dumps(report, ensure_ascii=True) + "\n"
    if out:
        Path(out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "quota":
            report = asyncio.run(
                run_quota(
                    args.requests,
                    args.concurrency,
                    max_runs=args.max_runs,
                    max_concurrent=args.max_concurrent,
                    window_seconds=args.window_seconds,
                    lease_seconds=args.lease_seconds,
                    hold_seconds=args.hold_seconds,
                    url=args.url,
                    tenant=args.tenant,
                )
            )
        else:
            report = asyncio.run(
                run_audit(
                    args.records,
                    args.path,
                    append=args.append,
                    max_records=args.max_records,
                    signing_key=os.environ.get(args.signing_key_env),
                )
            )
    except LoadtestError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    _emit(report, args.out)
    return 0 if all(item["holds"] for item in report["invariants"]) else 1


if __name__ == "__main__":
    sys.exit(main())
