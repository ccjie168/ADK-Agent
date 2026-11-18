"""SLICE-146: specs must cite tests that exist."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_CHECK = Path(__file__).resolve().parents[1] / "scripts" / "check_specs.py"
_SPEC = importlib.util.spec_from_file_location("check_specs", _CHECK)
assert _SPEC is not None and _SPEC.loader is not None
check_specs: Any = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_specs)

BODY = """# SLICE-900 test spec

状态: gated

## 意图

x

## 完成判据

- [x] 用例 -> `{name}`

## 反例

x

## 5 问威胁建模

x

## 证据

x
"""


def _spec(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "SLICE-900-test.md"
    path.write_text(BODY.format(name=name), encoding="utf-8")
    return path


def test_known_test_reference_passes(tmp_path):
    path = _spec(tmp_path, "test_exists")

    assert check_specs.check_file(path, {"test_exists"}) == []


def test_unknown_test_reference_is_rejected(tmp_path):
    path = _spec(tmp_path, "test_missing")

    problems = check_specs.check_file(path, {"test_exists"})

    assert problems == ["unknown-test:test_missing"]


def test_merged_specs_skip_the_reference_check(tmp_path):
    path = _spec(tmp_path, "test_missing")
    path.write_text(
        path.read_text(encoding="utf-8").replace("状态: gated", "状态: merged"),
        encoding="utf-8",
    )

    assert check_specs.check_file(path, {"test_exists"}) == []


def test_missing_sections_are_reported(tmp_path):
    path = tmp_path / "SLICE-901-test.md"
    path.write_text("状态: gated\n", encoding="utf-8")

    problems = check_specs.check_file(path, set())

    assert "threat-model" in problems


def test_reference_variants_resolve(tmp_path):
    path = tmp_path / "SLICE-902-test.md"
    body = BODY.format(name="tests/test_x.py::test_exists()")
    path.write_text(body, encoding="utf-8")

    assert check_specs.check_file(path, {"test_exists"}) == []
    assert check_specs.check_file(path, {"test_other"}) == ["unknown-test:test_exists"]


def test_defined_tests_uses_the_ast_not_strings(tmp_path):
    module = tmp_path / "test_sample.py"
    module.write_text(
        'DOC = """\ndef test_in_a_string():\n    pass\n"""\n\n'
        "def test_real():\n    pass\n\n"
        "class TestGroup:\n    def test_member(self):\n        pass\n",
        encoding="utf-8",
    )

    names = check_specs.defined_tests(tmp_path)

    assert "test_real" in names
    assert "test_member" in names
    assert "test_in_a_string" not in names


def test_main_flags_unknown_references(tmp_path, monkeypatch, capsys):
    path = tmp_path / "SLICE-903-test.md"
    path.write_text(BODY.format(name="test_missing"), encoding="utf-8")
    monkeypatch.setattr(check_specs, "SPECS", tmp_path)
    monkeypatch.setattr(check_specs, "defined_tests", lambda: {"test_real"})

    assert check_specs.main() == 1
    assert "unknown-test:test_missing" in capsys.readouterr().out


def test_reference_floor_exempts_historical_specs(tmp_path):
    path = tmp_path / "SLICE-020-tool-guard.md"
    path.write_text(BODY.format(name="test_missing"), encoding="utf-8")

    assert check_specs.check_file(path, {"test_real"}) == []
