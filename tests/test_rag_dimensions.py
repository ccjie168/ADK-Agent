"""SLICE-208: embedding dimensions must be positive at every entry point."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from adk_agent import cli
from adk_agent.rag.vector_store import PgVectorRagStore, RagStoreUnavailable


def _args(dimensions: int) -> SimpleNamespace:
    return SimpleNamespace(
        rag_db="postgresql://u@127.0.0.1:1/x",
        rag_dimensions=dimensions,
        rag_model="text-embedding-3-small",
        rag_provider="litellm",
    )


@pytest.mark.parametrize("dimensions", [0, -1])
def test_rag_factory_rejects_non_positive_dimensions(dimensions, capsys):
    with pytest.raises(SystemExit) as exc:
        cli._rag_factory(_args(dimensions))
    assert exc.value.code == 1
    assert "--rag-dimensions must be positive" in capsys.readouterr().err


def test_vector_store_rejects_non_positive_dimensions():
    with pytest.raises(RagStoreUnavailable):
        PgVectorRagStore("postgresql://u@127.0.0.1:1/x", dimensions=0)


@pytest.mark.parametrize("command", ["ingest", "search"])
def test_rag_cli_rejects_zero_dimensions(command, capsys, tmp_path):
    document = tmp_path / "doc.txt"
    document.write_text("hello\n", encoding="utf-8")
    argv = [
        "rag",
        command,
        "--database-url",
        "postgresql://u@127.0.0.1:1/x",
        "--dimensions",
        "0",
        "--model",
        "m",
        "--tenant",
        "t",
    ]
    if command == "ingest":
        argv += ["--source-id", "doc", "--text", str(document)]
    else:
        argv += ["--query", "hello"]

    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 1
    assert "dimensions must be positive" in capsys.readouterr().err
