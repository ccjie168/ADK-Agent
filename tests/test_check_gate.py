"""SLICE-005: `check.py --full` must run the fast gate too."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_CHECK = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_SPEC = importlib.util.spec_from_file_location("check_gate", _CHECK)
assert _SPEC is not None and _SPEC.loader is not None
check: Any = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check)


def _names(steps: list) -> list[str]:
    return [name for name, _module, _args in steps]


def test_fast_selection():
    assert check.select_steps(["--fast"]) == check.FAST_STEPS


def test_full_selection_contains_fast_and_full_only_steps():
    full = check.select_steps(["--full"])
    fast_names = _names(check.FAST_STEPS)
    full_only = [step for step in check.FULL_STEPS if step not in check.FAST_STEPS]
    assert full_only
    assert set(fast_names) <= set(_names(full))
    assert set(_names(full_only)) <= set(_names(full))
