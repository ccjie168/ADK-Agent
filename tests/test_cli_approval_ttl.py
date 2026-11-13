"""SLICE-049: console --approval-ttl wiring."""

from __future__ import annotations

import adk_agent.console as console_module
from adk_agent import cli
from adk_agent.approvals import FileApprovalInbox


def test_console_forwards_approval_ttl(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("adk_agent.cli._load_agents", lambda path: {"probe": object()})
    monkeypatch.setattr(console_module, "run_console", lambda *a, **k: captured.update(k))

    cli.main(
        [
            "console",
            "--agents",
            "x.py",
            "--approval-dir",
            str(tmp_path / "inbox"),
            "--approval-ttl",
            "30",
        ]
    )

    approvals = captured["approvals"]
    assert isinstance(approvals, FileApprovalInbox)
    assert approvals.ttl_seconds == 30.0


def test_approval_ttl_defaults_to_none(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("adk_agent.cli._load_agents", lambda path: {"probe": object()})
    monkeypatch.setattr(console_module, "run_console", lambda *a, **k: captured.update(k))

    cli.main(["console", "--agents", "x.py", "--approval-dir", str(tmp_path / "inbox")])

    assert captured["approvals"].ttl_seconds is None
