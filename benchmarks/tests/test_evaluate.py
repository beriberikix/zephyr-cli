"""Unit tests for benchmarks.evaluate that need no Zephyr build.

Run from the repository root:  python -m pytest benchmarks/tests/
"""

from __future__ import annotations

import json

import pytest

import benchmarks.evaluate as ev
from benchmarks.evaluate import evaluate_run


def _make_run(run_dir, task: str = "hello-shell") -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    run_dir.joinpath("metadata.json").write_text(
        json.dumps(
            {
                "task": task,
                "difficulty": "simple",
                "board": "native_sim",
                "condition": "baseline",
                "model": "m",
            }
        )
    )
    run_dir.joinpath("CMakeLists.txt").write_text("find_package(Zephyr)")
    run_dir.joinpath("prj.conf").write_text("CONFIG_SHELL=y\n")
    (run_dir / "src").mkdir(exist_ok=True)
    run_dir.joinpath("src", "main.c").write_text("int main(void) { return 0; }")


def test_skip_build_bypasses_west(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "run_1"
    _make_run(run_dir)
    # check_build is the only path to `west build` / ZEPHYR_BASE — it must not
    # run under --skip-build.
    monkeypatch.setattr(
        ev, "check_build", lambda *a, **k: pytest.fail("check_build invoked under skip_build")
    )

    result = evaluate_run(run_dir, skip_build=True)

    assert result is not None
    build = result["details"]["build"]
    assert build["skipped"] is True
    assert build["build_ok"] is False
    # Static-analysis dimensions are still scored from the generated files.
    assert result["scores"]["best_practices"] > 0


def test_default_path_still_calls_check_build(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "run_1"
    _make_run(run_dir)
    sentinel = {"build_ok": True, "warning_count": 0, "error_count": 0, "errors": []}
    monkeypatch.setattr(ev, "check_build", lambda *a, **k: sentinel)

    result = evaluate_run(run_dir)

    assert result is not None
    assert result["details"]["build"] is sentinel
