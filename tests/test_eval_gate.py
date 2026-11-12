"""SLICE-030: the publish command enforces the eval gate."""

from __future__ import annotations

import json

import pytest

from adk_agent import cli


def _manifest_data(*, eval_suite: dict | None = None) -> dict:
    data = {
        "id": "support-bot",
        "version": "1.0.0",
        "tenant": "team-a",
        "owner": "team-a",
        "model_policy": {"provider_allowlist": ["litellm"]},
    }
    if eval_suite is not None:
        data["eval_suite"] = eval_suite
    return data


def _report_data(*, passed: int = 2, total: int = 2, suite_id: str = "smoke") -> dict:
    return {"suite_id": suite_id, "version": "1", "passed": passed, "total": total}


def _write(tmp_path, data: dict, name: str):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _suite() -> dict:
    return {"suite_id": "smoke", "version": "1", "pass_threshold": 0.8}


def test_publish_requires_report(tmp_path, capsys):
    manifest = _write(tmp_path, _manifest_data(eval_suite=_suite()), "manifest.json")
    registry = tmp_path / "registry"

    with pytest.raises(SystemExit) as exc:
        cli.main(["publish", str(manifest), "--registry", str(registry)])

    assert exc.value.code == 1
    assert "eval" in capsys.readouterr().err
    assert not registry.exists()


def test_publish_rejects_failing_report(tmp_path, capsys):
    manifest = _write(tmp_path, _manifest_data(eval_suite=_suite()), "manifest.json")
    report = _write(tmp_path, _report_data(passed=1, total=2), "report.json")
    registry = tmp_path / "registry"

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "publish",
                str(manifest),
                "--registry",
                str(registry),
                "--eval-report",
                str(report),
            ]
        )

    assert exc.value.code == 1
    assert "below" in capsys.readouterr().err
    assert not registry.exists()


def test_publish_rejects_suite_mismatch(tmp_path, capsys):
    manifest = _write(tmp_path, _manifest_data(eval_suite=_suite()), "manifest.json")
    report = _write(tmp_path, _report_data(suite_id="other"), "report.json")
    registry = tmp_path / "registry"

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "publish",
                str(manifest),
                "--registry",
                str(registry),
                "--eval-report",
                str(report),
            ]
        )

    assert exc.value.code == 1
    assert "match" in capsys.readouterr().err


def test_publish_accepts_passing_report(tmp_path, capsys):
    manifest = _write(tmp_path, _manifest_data(eval_suite=_suite()), "manifest.json")
    report = _write(tmp_path, _report_data(), "report.json")
    registry = tmp_path / "registry"

    cli.main(["publish", str(manifest), "--registry", str(registry), "--eval-report", str(report)])

    assert "published team-a/support-bot@1.0.0" in capsys.readouterr().out
    assert (registry / "team-a" / "support-bot" / "1.0.0.json").is_file()


def test_publish_without_suite_is_ungated(tmp_path, capsys):
    manifest = _write(tmp_path, _manifest_data(), "manifest.json")
    registry = tmp_path / "registry"

    cli.main(["publish", str(manifest), "--registry", str(registry)])

    assert "published" in capsys.readouterr().out


def test_publish_persists_eval_report(tmp_path, capsys):
    manifest = _write(tmp_path, _manifest_data(eval_suite=_suite()), "manifest.json")
    report = _write(tmp_path, _report_data(), "report.json")
    registry = tmp_path / "registry"

    cli.main(["publish", str(manifest), "--registry", str(registry), "--eval-report", str(report)])

    capsys.readouterr()
    stored = registry / "team-a" / "support-bot" / "1.0.0.eval.json"
    assert stored.is_file()
    payload = json.loads(stored.read_text())
    assert payload["suite_id"] == "smoke"
    assert payload["passed"] == 2
    assert payload["total"] == 2


def test_republish_finishes_missing_report(tmp_path):
    manifest = _write(tmp_path, _manifest_data(eval_suite=_suite()), "manifest.json")
    report = _write(tmp_path, _report_data(), "report.json")
    registry = tmp_path / "registry"
    args = [
        "publish",
        str(manifest),
        "--registry",
        str(registry),
        "--eval-report",
        str(report),
    ]
    cli.main(args)

    stored = registry / "team-a" / "support-bot" / "1.0.0.eval.json"
    stored.unlink()

    cli.main(args)

    assert stored.is_file()
