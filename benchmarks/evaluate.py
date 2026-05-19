"""Benchmark evaluator — scores generated Zephyr projects.

Runs build checks, static analysis, and runtime validation on benchmark results.

Usage:
    python -m benchmarks.evaluate [--results-dir benchmarks/results/]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("pyyaml is required: pip install pyyaml")

from benchmarks.scoring import (
    compute_weighted,
    score_api_freshness,
    score_best_practices,
    score_compilability,
    score_completeness,
    score_config_quality,
    score_correctness,
)
from benchmarks.usage import write_usage

BENCHMARKS_DIR = Path(__file__).resolve().parent
TASKS_DIR = BENCHMARKS_DIR / "tasks"
RESULTS_DIR = BENCHMARKS_DIR / "results"
DEPRECATED_APIS_FILE = BENCHMARKS_DIR / "deprecated_apis.yml"

# Common locations where a Zephyr workspace may live.
_ZEPHYR_SEARCH_PATHS = [
    Path.home() / "zephyrproject" / "zephyr",
    Path.home() / "zephyr-workspace" / "zephyr",
    Path("/opt/zephyr"),
]


def _detect_zephyr_base() -> str | None:
    """Return ZEPHYR_BASE from env or by probing common locations."""
    val = os.environ.get("ZEPHYR_BASE")
    if val and Path(val).is_dir():
        return val
    for p in _ZEPHYR_SEARCH_PATHS:
        if (p / "west.yml").exists():
            return str(p)
    return None


def load_deprecated_apis() -> list[dict]:
    if not DEPRECATED_APIS_FILE.exists():
        return []
    with open(DEPRECATED_APIS_FILE) as f:
        return yaml.safe_load(f) or []


def load_task(name: str) -> dict:
    path = TASKS_DIR / f"{name}.yml"
    with open(path) as f:
        return yaml.safe_load(f)


# ── Build check ──────────────────────────────────────────────────────────


def check_build(run_dir: Path, board: str) -> dict:
    """Try to build the project with west. Returns build evaluation dict."""
    # Check if there's at least a CMakeLists.txt
    if not (run_dir / "CMakeLists.txt").exists():
        return {
            "build_ok": False,
            "warning_count": 0,
            "error_count": 1,
            "errors": ["CMakeLists.txt not found — nothing to build"],
        }

    zephyr_base = _detect_zephyr_base()
    if not zephyr_base:
        return {
            "build_ok": False,
            "warning_count": 0,
            "error_count": 1,
            "errors": [
                "ZEPHYR_BASE not set and could not auto-detect. "
                "Run: export ZEPHYR_BASE=<path-to-zephyr> or source zephyr-env.sh"
            ],
        }

    build_dir = run_dir / "build"
    cmd = [
        "west",
        "build",
        "-b",
        board,
        "-d",
        str(build_dir.resolve()),
        str(run_dir.resolve()),
        "--",
        "-DCONF_FILE=prj.conf",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=zephyr_base,  # run from ZEPHYR_BASE so west finds the Zephyr workspace
        )
    except subprocess.TimeoutExpired:
        return {
            "build_ok": False,
            "warning_count": 0,
            "error_count": 1,
            "errors": ["Build timed out after 300s"],
        }

    combined = result.stdout + "\n" + result.stderr
    warnings = re.findall(r"warning:", combined, re.IGNORECASE)
    errors = re.findall(r"error:", combined, re.IGNORECASE)

    build_ok = result.returncode == 0

    return {
        "build_ok": build_ok,
        "warning_count": len(warnings),
        "error_count": len(errors),
        "errors": (
            [line for line in combined.splitlines() if "error:" in line.lower()][:10]
            if not build_ok
            else []
        ),
    }


# ── Static analysis ─────────────────────────────────────────────────────


def check_completeness(run_dir: Path, expected_files: list[str]) -> dict:
    """Check which expected files are present."""
    present = []
    missing = []
    for f in expected_files:
        if (run_dir / f).exists():
            present.append(f)
        else:
            missing.append(f)
    return {
        "files_present": len(present),
        "files_expected": len(expected_files),
        "present": present,
        "missing": missing,
    }


def check_deprecated_apis(run_dir: Path, task_deprecated: list[str]) -> dict:
    """Grep source files for deprecated API patterns."""
    deprecated_rules = load_deprecated_apis()

    # Also include task-specific patterns
    all_patterns = [r["pattern"] for r in deprecated_rules]
    for pattern_str in task_deprecated:
        # Task deprecated_apis are simple strings — escape for regex
        all_patterns.append(re.escape(pattern_str) + r"\s*\(")

    hits = []
    source_files = list(run_dir.rglob("*.c")) + list(run_dir.rglob("*.h"))
    # Exclude build directory
    source_files = [f for f in source_files if "build" not in f.parts]

    for src in source_files:
        content = src.read_text(errors="replace")
        for pat in all_patterns:
            if re.search(pat, content):
                hits.append(
                    {
                        "file": str(src.relative_to(run_dir)),
                        "pattern": pat,
                    }
                )

    return {
        "deprecated_hits": len(hits),
        "details": hits,
    }


def check_best_practices(run_dir: Path, checklist: list[str]) -> dict:
    """Check if best-practice patterns appear in source files.

    Each checklist item is either a plain substring or multiple alternatives
    separated by `` or `` (e.g. "FOO or BAR").  Parentheses in the pattern
    are stripped so ``find_package(Zephyr)`` matches
    ``find_package(Zephyr REQUIRED ...)``.
    """
    source_files = list(run_dir.rglob("*.c")) + list(run_dir.rglob("*.h"))
    cmake_files = list(run_dir.rglob("CMakeLists.txt"))
    all_files = source_files + cmake_files
    # Exclude build directory
    all_files = [f for f in all_files if "build" not in f.parts]

    all_content = ""
    for f in all_files:
        all_content += f.read_text(errors="replace") + "\n"

    passed = []
    failed = []
    for item in checklist:
        alternatives = [alt.strip() for alt in item.split(" or ")]
        # Strip trailing parens so "find_package(Zephyr)" matches
        # "find_package(Zephyr REQUIRED ...)"
        found = any(alt.rstrip(")") in all_content for alt in alternatives)
        if found:
            passed.append(item)
        else:
            failed.append(item)

    return {
        "passed": len(passed),
        "total": len(checklist),
        "passed_items": passed,
        "failed_items": failed,
    }


# ── Kconfig quality check ────────────────────────────────────────────────


def check_kconfig(run_dir: Path, expected_kconfig: list[str]) -> dict:
    """Check that expected Kconfig symbols appear in prj.conf."""
    prj_conf = run_dir / "prj.conf"
    if not prj_conf.exists():
        return {
            "kconfig_present": 0,
            "kconfig_expected": len(expected_kconfig),
            "present": [],
            "missing": expected_kconfig[:],
        }

    content = prj_conf.read_text(errors="replace")
    present = []
    missing = []
    for sym in expected_kconfig:
        # Match "CONFIG_FOO=y", "CONFIG_FOO=n", "CONFIG_FOO=123", etc.
        if re.search(rf"^\s*{re.escape(sym)}\s*=", content, re.MULTILINE):
            present.append(sym)
        else:
            missing.append(sym)

    return {
        "kconfig_present": len(present),
        "kconfig_expected": len(expected_kconfig),
        "present": present,
        "missing": missing,
    }


# ── Runtime check ────────────────────────────────────────────────────────


def check_runtime(
    run_dir: Path,
    board: str,
    patterns: list[str],
    stdin_commands: list[str] | None = None,
) -> dict:
    """Run native_sim binary and check serial output against patterns.

    Uses ``--uart_stdinout`` so the UART is connected to the process's
    stdin/stdout instead of a PTY, making it automatable.  If
    ``stdin_commands`` is provided those lines are fed to stdin after a
    short boot period so interactive shell commands can be exercised.
    """
    if board != "native_sim" or not patterns:
        return {
            "has_runtime_check": False,
            "matched": 0,
            "total": 0,
            "matched_patterns": [],
            "missed_patterns": [],
        }

    # Look for the built binary
    exe = run_dir / "build" / "zephyr" / "zephyr.exe"
    if not exe.exists():
        return {
            "has_runtime_check": True,
            "matched": 0,
            "total": len(patterns),
            "matched_patterns": [],
            "missed_patterns": patterns,
            "error": "zephyr.exe not found",
        }

    # --uart_stdinout routes UART0 to stdout/stdin instead of a PTY,
    # enabling capture_output and stdin injection for automated testing.
    cmd = [str(exe), "--uart_stdinout"]

    # Build stdin payload: a short delay so the shell is ready, then
    # each command followed by a newline.
    stdin_payload: bytes | None = None
    if stdin_commands:
        lines = "\n".join(stdin_commands) + "\n"
        stdin_payload = lines.encode()

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = proc.communicate(
            input=stdin_payload,
            timeout=15,
        )
        output = (
            stdout_bytes.decode(errors="replace") + "\n" + stderr_bytes.decode(errors="replace")
        )
    except subprocess.TimeoutExpired:
        # Timeout is expected for native_sim — it runs until killed.
        # communicate() already killed the process; retrieve partial output.
        proc.kill()
        stdout_bytes, stderr_bytes = proc.communicate()
        output = (
            stdout_bytes.decode(errors="replace") + "\n" + stderr_bytes.decode(errors="replace")
        )
    except OSError as e:
        return {
            "has_runtime_check": True,
            "matched": 0,
            "total": len(patterns),
            "matched_patterns": [],
            "missed_patterns": patterns,
            "error": str(e),
        }

    matched = []
    missed = []
    for pat in patterns:
        if re.search(pat, output):
            matched.append(pat)
        else:
            missed.append(pat)

    return {
        "has_runtime_check": True,
        "matched": len(matched),
        "total": len(patterns),
        "matched_patterns": matched,
        "missed_patterns": missed,
    }


# ── Orchestration ────────────────────────────────────────────────────────


def evaluate_run(run_dir: Path) -> dict | None:
    """Evaluate a single benchmark run directory. Returns evaluation dict."""
    meta_file = run_dir / "metadata.json"
    if not meta_file.exists():
        return None

    meta = json.loads(meta_file.read_text())
    task_name = meta["task"]
    board = meta["board"]
    task = load_task(task_name)

    # Ensure derived token/process metrics exist (cheap — parsed from the saved
    # transcript, so old result trees get usage.json without re-running agents).
    if not (run_dir / "usage.json").exists():
        write_usage(run_dir)

    # Run all checks
    build_result = check_build(run_dir, board)
    completeness = check_completeness(run_dir, task.get("expected_files", []))
    deprecated = check_deprecated_apis(run_dir, task.get("deprecated_apis", []))
    practices = check_best_practices(run_dir, task.get("best_practices", []))
    kconfig = check_kconfig(run_dir, task.get("expected_kconfig", []))
    runtime = check_runtime(
        run_dir,
        board,
        task.get("runtime_patterns", []),
        stdin_commands=task.get("runtime_stdin"),
    )

    # Compute scores
    scores = {
        "compilability": score_compilability(
            build_result["build_ok"], build_result["warning_count"]
        ),
        "correctness": score_correctness(
            runtime["matched"],
            runtime["total"],
            runtime["has_runtime_check"],
            build_result["build_ok"],
        ),
        "best_practices": score_best_practices(practices["passed"], practices["total"]),
        "api_freshness": score_api_freshness(deprecated["deprecated_hits"]),
        "completeness": score_completeness(
            completeness["files_present"], completeness["files_expected"]
        ),
        "config_quality": score_config_quality(
            kconfig["kconfig_present"], kconfig["kconfig_expected"]
        ),
    }
    weighted = compute_weighted(scores)

    evaluation = {
        "metadata": meta,
        "scores": scores,
        "weighted_total": weighted,
        "details": {
            "build": build_result,
            "completeness": completeness,
            "deprecated_apis": deprecated,
            "best_practices": practices,
            "kconfig": kconfig,
            "runtime": runtime,
        },
    }

    # Save evaluation result
    eval_path = run_dir / "evaluation.json"
    eval_path.write_text(json.dumps(evaluation, indent=2) + "\n")
    return evaluation


def find_run_dirs(results_dir: Path) -> list[Path]:
    """Find all run directories under the results tree."""
    dirs = []
    for meta in results_dir.rglob("metadata.json"):
        dirs.append(meta.parent)
    return sorted(dirs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate benchmark results")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=RESULTS_DIR,
        help=f"Results directory (default: {RESULTS_DIR})",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip west build step (only run static analysis)",
    )
    parser.add_argument(
        "--zephyr-base",
        type=Path,
        default=None,
        help="Path to Zephyr tree (overrides ZEPHYR_BASE env var)",
    )
    args = parser.parse_args()

    # Set ZEPHYR_BASE from flag if provided, so _detect_zephyr_base() finds it
    if args.zephyr_base:
        os.environ["ZEPHYR_BASE"] = str(args.zephyr_base.resolve())

    # Verify ZEPHYR_BASE is available before spending time on runs
    zb = _detect_zephyr_base()
    if zb:
        print(f"ZEPHYR_BASE: {zb}")
    else:
        print(
            "WARNING: ZEPHYR_BASE not set and could not auto-detect. "
            "Builds will fail. Use --zephyr-base or source zephyr-env.sh\n"
        )

    run_dirs = find_run_dirs(args.results_dir)
    if not run_dirs:
        sys.exit(f"No results found in {args.results_dir}")

    print(f"Evaluating {len(run_dirs)} runs in {args.results_dir}\n")

    for run_dir in run_dirs:
        meta = json.loads((run_dir / "metadata.json").read_text())
        label = f"{meta['task']}/{meta['condition']}/{run_dir.name}"
        print(f"  {label} ...", end=" ", flush=True)

        evaluation = evaluate_run(run_dir)
        if evaluation:
            total = evaluation["weighted_total"]
            build = "✓" if evaluation["details"]["build"]["build_ok"] else "✗"
            print(f"build={build}  score={total:.2f}")
        else:
            print("SKIP (no metadata)")

    print("\nDone. Run `python -m benchmarks.report` to generate summary.")


if __name__ == "__main__":
    main()
