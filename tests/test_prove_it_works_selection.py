"""SLICE-216: the proof harness can run a release smoke subset."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prove_it_works.py"
_SPEC = importlib.util.spec_from_file_location("prove_it_works", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
module = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = module
_SPEC.loader.exec_module(module)


def test_smoke_selects_the_release_subset():
    assert module.select_checks(None, True) == ["P1", "P2", "P3", "P4"]


def test_only_is_split_and_trimmed():
    assert module.select_checks(" P2, P3 ", False) == ["P2", "P3"]


def test_default_runs_every_check():
    selected = module.select_checks(None, False)

    assert selected == list(module.CHECKS)
    assert len(selected) == len(module.CHECKS)


def test_smoke_and_only_are_mutually_exclusive(capsys):
    parser = module.build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--smoke", "--only", "P1"])

    assert exc.value.code == 2
    assert "not allowed with" in capsys.readouterr().err


def test_parser_exposes_smoke():
    parser = module.build_parser()

    args = parser.parse_args(["--smoke"])

    assert args.smoke is True
    assert args.only is None
