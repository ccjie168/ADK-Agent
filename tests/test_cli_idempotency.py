"""SLICE-177: serve-tool-gateway wires the idempotency store via CLI flags."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from adk_agent import cli
from adk_agent.tools import FileToolIdempotencyStore, PostgresToolIdempotencyStore


def test_idempotency_store_none_without_flags():
    assert (
        cli._idempotency_store(SimpleNamespace(idempotency_dir=None, idempotency_db=None)) is None
    )


def test_idempotency_store_file():
    store = cli._idempotency_store(
        SimpleNamespace(idempotency_dir="/tmp/idem", idempotency_db=None)
    )
    assert isinstance(store, FileToolIdempotencyStore)


def test_idempotency_store_postgres():
    store = cli._idempotency_store(
        SimpleNamespace(idempotency_dir=None, idempotency_db="postgresql://user@127.0.0.1:5432/adk")
    )
    assert isinstance(store, PostgresToolIdempotencyStore)


def test_idempotency_store_rejects_both():
    with pytest.raises(SystemExit):
        cli._idempotency_store(
            SimpleNamespace(idempotency_dir="/tmp/idem", idempotency_db="postgresql://user@h/db")
        )


def test_serve_tool_gateway_help_lists_idempotency_flags(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["serve-tool-gateway", "--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--idempotency-dir" in help_text
    assert "--idempotency-db" in help_text
