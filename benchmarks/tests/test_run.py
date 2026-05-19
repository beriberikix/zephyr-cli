"""Unit tests for benchmarks.run helpers that don't require an agent.

Run from the repository root:  python -m pytest benchmarks/tests/
"""

from __future__ import annotations

import json
from datetime import datetime

from benchmarks.run import collect_artifacts, save_metadata


def test_save_metadata_writes_valid_json(tmp_path) -> None:
    task = {"name": "demo", "difficulty": "simple", "board": "native_sim"}
    save_metadata(
        tmp_path,
        task,
        "treatment",
        "provider/model",
        "1.0",
        returncode=0,
        elapsed=1.5,
        stdout="agent output",
        stderr="",
        docs_info={"provisioned": True, "version": "3.7.0"},
    )
    meta = json.loads((tmp_path / "metadata.json").read_text())
    assert meta["task"] == "demo"
    assert meta["condition"] == "treatment"
    assert meta["docs_provisioned"] is True
    assert meta["docs_version"] == "3.7.0"
    # Timestamp must be ISO-parseable — guards against the datetime.UTC regression.
    datetime.fromisoformat(meta["timestamp"])
    assert (tmp_path / "stdout.txt").read_text() == "agent output"


def test_save_metadata_baseline_never_marks_docs_provisioned(tmp_path) -> None:
    task = {"name": "demo", "difficulty": "simple", "board": "native_sim"}
    save_metadata(
        tmp_path,
        task,
        "baseline",
        "provider/model",
        "1.0",
        returncode=0,
        elapsed=1.0,
        stdout="",
        stderr="",
        docs_info={"provisioned": True, "version": "3.7.0"},
    )
    meta = json.loads((tmp_path / "metadata.json").read_text())
    # The baseline arm never has docs, regardless of what was provisioned.
    assert meta["docs_provisioned"] is False


def test_collect_artifacts_copies_output_and_skips_scaffolding(tmp_path) -> None:
    workdir = tmp_path / "work"
    (workdir / "src").mkdir(parents=True)
    (workdir / "CMakeLists.txt").write_text("cmake")
    (workdir / "src" / "main.c").write_text("int main(void) { return 0; }")
    (workdir / "opencode.json").write_text("{}")
    (workdir / ".agents" / "skills").mkdir(parents=True)
    (workdir / ".git").mkdir()
    (workdir / ".git" / "HEAD").write_text("ref: refs/heads/main")
    (workdir / "zephyr-docs").mkdir()  # the docs corpus symlink in real runs

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    collect_artifacts(workdir, run_dir)

    # Agent output is copied.
    assert (run_dir / "CMakeLists.txt").read_text() == "cmake"
    assert (run_dir / "src" / "main.c").exists()
    assert (run_dir / "opencode.json").exists()  # kept for provenance
    # Benchmark scaffolding is skipped.
    assert not (run_dir / ".agents").exists()
    assert not (run_dir / ".git").exists()
    assert not (run_dir / "zephyr-docs").exists()


def test_collect_artifacts_flattens_a_nested_project(tmp_path) -> None:
    # The agent placed the project one level down in app/ instead of at root.
    workdir = tmp_path / "work"
    (workdir / "app" / "src").mkdir(parents=True)
    (workdir / "app" / "CMakeLists.txt").write_text("cmake")
    (workdir / "app" / "prj.conf").write_text("CONFIG_FOO=y")
    (workdir / "app" / "src" / "main.c").write_text("int main(void) { return 0; }")
    (workdir / ".agents" / "skills").mkdir(parents=True)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    collect_artifacts(workdir, run_dir)

    # The nested project is flattened to the run-dir top level for the evaluator.
    assert (run_dir / "CMakeLists.txt").read_text() == "cmake"
    assert (run_dir / "prj.conf").exists()
    assert (run_dir / "src" / "main.c").exists()
    assert not (run_dir / "app").exists()
