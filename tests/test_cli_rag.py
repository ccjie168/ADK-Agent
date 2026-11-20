"""SLICE-194: rag ingest and rag search wire the pgvector pipeline into the CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adk_agent import cli
from adk_agent.core import EmbeddingResponse
from adk_agent.rag.vector_store import RagChunkRow, RagStoreUnavailable

ROOT = Path(__file__).resolve().parents[1]


class _FakeProvider:
    name = "litellm"
    egress = "third_party"

    def __init__(self, *, api_key=None, api_base=None) -> None:
        self.api_key = api_key
        self.api_base = api_base
        self.requests: list[object] = []

    async def embed(self, request):
        self.requests.append(request)
        return EmbeddingResponse(
            vectors=[[0.1, 0.2, 0.3] for _ in request.texts],
            model=request.model,
            input_tokens=len(request.texts),
            cost_usd=0.0,
            egress="third_party",
        )


class _FakeStore:
    rows: list[RagChunkRow] = []
    instances: list[_FakeStore] = []

    def __init__(self, url: str, *, dimensions: int) -> None:
        self.url = url
        self.dimensions = dimensions
        self.chunks: list[object] = []
        self.search_calls: list[dict[str, object]] = []
        _FakeStore.instances.append(self)

    async def upsert(self, chunks) -> None:
        self.chunks.extend(chunks)

    async def search(self, tenant, embedding, *, data_classes, subject=None, limit=10):
        self.search_calls.append(
            {
                "tenant": tenant,
                "embedding": list(embedding),
                "data_classes": list(data_classes),
                "subject": subject,
                "limit": limit,
            }
        )
        return _FakeStore.rows[:limit]

    async def aclose(self) -> None:
        return None


class _BoomStore:
    def __init__(self, url: str, *, dimensions: int) -> None:
        if dimensions <= 0:
            raise RagStoreUnavailable("dimensions must be positive")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("AUDIT_DATABASE_URL", raising=False)
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    monkeypatch.setattr("adk_agent.rag.vector_store.PgVectorRagStore", _FakeStore)
    monkeypatch.setattr("adk_agent.models.providers.LiteLlmProvider", _FakeProvider)
    _FakeStore.instances.clear()
    _FakeStore.rows = []


def _ingest_args(tmp_path: Path, *extra: str) -> list[str]:
    doc = tmp_path / "doc.txt"
    doc.write_text("alpha beta gamma", encoding="utf-8")
    return [
        "rag",
        "ingest",
        "--database-url",
        "postgresql://adk@127.0.0.1:5432/adk",
        "--dimensions",
        "3",
        "--model",
        "text-embedding-3-small",
        "--tenant",
        "t1",
        "--source-id",
        "s1",
        "--text",
        str(doc),
        *extra,
    ]


def test_rag_ingest_writes_chunks(tmp_path, capsys):
    cli.main(_ingest_args(tmp_path, "--data-class", "public"))
    store = _FakeStore.instances[-1]
    assert [chunk.text for chunk in store.chunks] == ["alpha beta gamma"]
    assert store.chunks[0].tenant == "t1"
    assert store.chunks[0].source_id == "s1"
    assert store.chunks[0].data_classes == ["public"]
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"tenant": "t1", "source_id": "s1", "chunks": 1}


def test_rag_ingest_rejects_empty_text(tmp_path, monkeypatch, capsys):
    doc = tmp_path / "empty.txt"
    doc.write_text("   \n\n", encoding="utf-8")
    args = _ingest_args(tmp_path)
    args[args.index("--text") + 1] = str(doc)
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 1
    assert "empty text" in capsys.readouterr().err
    assert all(not store.chunks for store in _FakeStore.instances)


def test_rag_ingest_reports_store_unavailable(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("adk_agent.rag.vector_store.PgVectorRagStore", _BoomStore)
    args = _ingest_args(tmp_path)
    args[args.index("--dimensions") + 1] = "0"
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "dimensions must be positive" in captured.err
    assert captured.out == ""


def test_rag_ingest_reports_missing_text_file(tmp_path, capsys):
    args = _ingest_args(tmp_path)
    args[args.index("--text") + 1] = str(tmp_path / "missing.txt")
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 1
    assert "could not read text" in capsys.readouterr().err


def test_rag_ingest_defaults_to_tenant_wide_visibility(tmp_path):
    cli.main(_ingest_args(tmp_path))
    chunks = _FakeStore.instances[-1].chunks
    assert chunks[0].allowed_subjects is None


def test_rag_ingest_rejects_zero_budget(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(_ingest_args(tmp_path, "--budget-usd", "0"))
    assert exc.value.code == 1
    assert "budget" in capsys.readouterr().err
    assert all(not store.chunks for store in _FakeStore.instances)


def test_rag_ingest_rejects_invalid_data_class(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(_ingest_args(tmp_path, "--data-class", "secret-sauce"))
    assert exc.value.code == 2
    assert "secret-sauce" in capsys.readouterr().err


def test_rag_ingest_reports_missing_litellm_extra(tmp_path, monkeypatch, capsys):
    class _NoLitellm(_FakeProvider):
        async def embed(self, request):
            raise ModuleNotFoundError("No module named 'litellm'")

    monkeypatch.setattr("adk_agent.models.providers.LiteLlmProvider", _NoLitellm)
    with pytest.raises(SystemExit) as exc:
        cli.main(_ingest_args(tmp_path))
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "adk-agent[litellm]" in err
    assert "Traceback" not in err


def _dir_args(root: Path, *extra: str) -> list[str]:
    return [
        "rag",
        "ingest",
        "--database-url",
        "postgresql://adk@127.0.0.1:5432/adk",
        "--dimensions",
        "3",
        "--model",
        "text-embedding-3-small",
        "--tenant",
        "t1",
        "--dir",
        str(root),
        *extra,
    ]


def test_rag_ingest_directory_ingests_relative_source_ids(tmp_path, capsys):
    root = tmp_path / "corpus"
    (root / "nested").mkdir(parents=True)
    (root / "a.txt").write_text("alpha", encoding="utf-8")
    (root / "nested" / "b.txt").write_text("beta", encoding="utf-8")
    cli.main(_dir_args(root, "--data-class", "internal"))
    chunks = _FakeStore.instances[-1].chunks
    assert [(chunk.source_id, chunk.text) for chunk in chunks] == [
        ("a.txt", "alpha"),
        ("nested/b.txt", "beta"),
    ]
    assert json.loads(capsys.readouterr().out) == {"tenant": "t1", "sources": 2, "chunks": 2}


def test_rag_ingest_directory_skips_empty_files(tmp_path, capsys):
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "good.txt").write_text("alpha", encoding="utf-8")
    (root / "empty.txt").write_text("  \n\n", encoding="utf-8")
    cli.main(_dir_args(root))
    chunks = _FakeStore.instances[-1].chunks
    assert [chunk.source_id for chunk in chunks] == ["good.txt"]
    assert json.loads(capsys.readouterr().out) == {"tenant": "t1", "sources": 1, "chunks": 1}


def test_rag_ingest_requires_source_id_without_dir(tmp_path, capsys):
    args = _ingest_args(tmp_path)
    index = args.index("--source-id")
    del args[index : index + 2]
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 1
    assert "--source-id" in capsys.readouterr().err


def test_rag_ingest_rejects_source_id_with_dir(tmp_path, capsys):
    root = tmp_path / "corpus"
    root.mkdir()
    with pytest.raises(SystemExit) as exc:
        cli.main(_dir_args(root, "--source-id", "doc"))
    assert exc.value.code == 2
    assert "--source-id" in capsys.readouterr().err


def test_rag_ingest_audits_embedding(tmp_path):
    audit = tmp_path / "audit.jsonl"
    cli.main(_ingest_args(tmp_path, "--audit-file", str(audit)))
    events = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    embeds = [event for event in events if event["action"] == "model.embed"]
    assert len(embeds) == 1
    assert embeds[0]["status"] == "ok"
    assert embeds[0]["tenant"] == "t1"


def _search_args(*extra: str) -> list[str]:
    return [
        "rag",
        "search",
        "--database-url",
        "postgresql://adk@127.0.0.1:5432/adk",
        "--dimensions",
        "3",
        "--model",
        "text-embedding-3-small",
        "--tenant",
        "t1",
        "--query",
        "hello",
        *extra,
    ]


def test_rag_search_returns_citations(capsys):
    _FakeStore.rows = [
        RagChunkRow(
            source_id="s1",
            chunk_id="c0",
            text="hello world",
            data_classes=["public"],
            distance=0.4,
        )
    ]
    cli.main(_search_args("--data-class", "public", "--subject", "alice", "--limit", "3"))
    call = _FakeStore.instances[-1].search_calls[0]
    assert call["tenant"] == "t1"
    assert call["subject"] == "alice"
    assert call["data_classes"] == ["public"]
    assert call["limit"] == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload == [
        {
            "source_id": "s1",
            "snippet": "hello world",
            "acl_checked": True,
            "confidence": pytest.approx(0.8),
        }
    ]


def test_rag_search_drops_low_confidence(capsys):
    _FakeStore.rows = [
        RagChunkRow(
            source_id="s1",
            chunk_id="c0",
            text="hello world",
            data_classes=["public"],
            distance=2.0,
        )
    ]
    cli.main(_search_args("--data-class", "public"))
    assert json.loads(capsys.readouterr().out) == []


def test_rag_search_rejects_non_positive_limit(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(_search_args("--limit", "0"))
    assert exc.value.code == 1
    assert "--limit must be greater than 0" in capsys.readouterr().err
    assert not _FakeStore.instances


def test_rag_help_lists_rag_flags(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["rag", "--help"])
    assert exc.value.code == 0
    assert "ingest" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        cli.main(["rag", "ingest", "--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    for flag in ("--database-url", "--dimensions", "--model", "--source-id", "--chunk-chars"):
        assert flag in help_text
    with pytest.raises(SystemExit) as exc:
        cli.main(["rag", "search", "--help"])
    assert exc.value.code == 0
    search_help = capsys.readouterr().out
    for flag in ("--query", "--limit", "--min-confidence", "--subject", "--budget-usd"):
        assert flag in search_help


def test_cli_contract_documents_rag_commands():
    text = (ROOT / "docs" / "contracts" / "cli.md").read_text(encoding="utf-8")
    assert "adk-agent rag ingest" in text
    assert "adk-agent rag search" in text
