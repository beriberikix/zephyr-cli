"""Benchmark runner — drives OpenCode to generate Zephyr projects.

Usage:
    python -m benchmarks.run --model anthropic/claude-opus-4 \\
        [--tasks blinky,wifi-http] [--runs 3] [--condition both]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("pyyaml is required: pip install pyyaml")

from benchmarks.usage import write_usage

BENCHMARKS_DIR = Path(__file__).resolve().parent
TASKS_DIR = BENCHMARKS_DIR / "tasks"
CONFIGS_DIR = BENCHMARKS_DIR / "configs"
RESULTS_DIR = BENCHMARKS_DIR / "results"

# Assumes zephyr-agent-skills is a sibling of zephyr-cli
SKILLS_REPO = BENCHMARKS_DIR.parent.parent / "zephyr-agent-skills" / "skills"

DEFAULT_BOARD = "esp32s3_devkitc/esp32s3/procpu"

# Map Zephyr board identifiers to human-readable names for prompts.
BOARD_DISPLAY_NAMES: dict[str, str] = {
    "esp32s3_devkitc/esp32s3/procpu": "ESP32-S3-DevKitC",
    "esp32_devkitc_wroom/esp32/procpu": "ESP32-DevKitC",
}


def board_display_name(board: str) -> str:
    """Return a human-readable name for a board identifier."""
    return BOARD_DISPLAY_NAMES.get(board, board)


def load_task(name: str, board: str | None = None) -> dict:
    path = TASKS_DIR / f"{name}.yml"
    if not path.exists():
        sys.exit(f"Task not found: {path}")
    with open(path) as f:
        task = yaml.safe_load(f)

    # Resolve board: "hardware" sentinel → user-supplied or default board
    if task.get("board") == "hardware":
        task["board"] = board or DEFAULT_BOARD
    elif board and task.get("board") != "native_sim":
        task["board"] = board

    # Substitute {board_name} in the prompt
    task["prompt"] = task["prompt"].replace("{board_name}", board_display_name(task["board"]))
    return task


def available_tasks() -> list[str]:
    return sorted(p.stem for p in TASKS_DIR.glob("*.yml"))


def opencode_version() -> str:
    try:
        result = subprocess.run(
            ["opencode", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() or "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"


def _slug(model: str) -> str:
    """Turn 'anthropic/claude-opus-4' into 'anthropic_claude-opus-4'."""
    return model.replace("/", "_").replace(" ", "_")


def isolate_workdir(run_dir: Path) -> None:
    """Make *run_dir* its own git repo so the agent is confined to it.

    Run directories live inside the zephyr-cli git repo. OpenCode is
    git-aware and would otherwise walk up to the enclosing repo and treat the
    whole project as the workspace — letting the agent explore and write
    files outside the run directory. A local ``git init`` stops that walk.
    """
    subprocess.run(
        ["git", "init", "-q"],
        cwd=run_dir,
        capture_output=True,
        check=False,
    )


def provision_docs() -> dict:
    """Refresh the zephyr-cli docs cache once so the treatment arm can use it.

    Returns ``{"provisioned": bool, "version": str|None, "path": str|None}``.
    A network or tooling failure is non-fatal — the benchmark still runs, but
    the report records that docs were not genuinely available to the treatment.
    """
    miss = {"provisioned": False, "version": None, "path": None}
    try:
        result = subprocess.run(
            ["zephyr-cli", "docs", "refresh", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except FileNotFoundError:
        print("WARNING: 'zephyr-cli' not found — docs will not be provisioned.")
        return miss
    except subprocess.TimeoutExpired:
        print("WARNING: docs refresh timed out — docs will not be provisioned.")
        return miss

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        print(f"WARNING: docs refresh failed — docs will not be provisioned. {detail}")
        return miss

    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        print("WARNING: could not parse docs refresh output.")
        return miss

    path, version = data.get("path"), data.get("version")
    if path and Path(path).is_dir():
        print(f"Docs provisioned: {version} ({path})")
        return {"provisioned": True, "version": version, "path": path}
    print("WARNING: docs refresh reported success but the cache path is missing.")
    return {"provisioned": False, "version": version, "path": path}


def prepare_workdir(
    task: dict,
    condition: str,
    run_dir: Path,
    docs_info: dict | None = None,
) -> dict[str, str]:
    """Set up a working directory for one benchmark run.

    Returns environment variables dict for the subprocess.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    isolate_workdir(run_dir)

    # Copy the appropriate opencode config
    config_src = CONFIGS_DIR / f"{condition}.opencode.json"
    config_dst = run_dir / "opencode.json"
    shutil.copy2(config_src, config_dst)

    env = os.environ.copy()

    # VS Code snap overrides XDG_DATA_HOME which breaks OpenCode auth
    # discovery.  Reset it so OpenCode finds ~/.local/share/opencode/auth.json.
    xdg = env.get("XDG_DATA_HOME", "")
    if "snap" in xdg:
        env["XDG_DATA_HOME"] = str(Path.home() / ".local" / "share")

    if condition == "treatment":
        # Symlink skills into .agents/skills/ for OpenCode discovery
        agents_skills = run_dir / ".agents" / "skills"
        agents_skills.mkdir(parents=True, exist_ok=True)
        if SKILLS_REPO.is_dir():
            for skill_dir in SKILLS_REPO.iterdir():
                if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                    target = agents_skills / skill_dir.name
                    if not target.exists():
                        target.symlink_to(skill_dir)
        # Symlink the LLM-optimized docs corpus as a visible top-level
        # `zephyr-docs/` so the agent can discover it by `ls` and reach it with
        # its read/grep tools — this makes "docs" genuinely part of treatment.
        if docs_info and docs_info.get("path"):
            docs_path = Path(docs_info["path"])
            if docs_path.is_dir():
                docs_link = run_dir / "zephyr-docs"
                if not docs_link.exists():
                    docs_link.symlink_to(docs_path)
        # zephyr-cli itself is reached via PATH (active venv).

    elif condition == "baseline":
        # Strip zephyr-cli from PATH to make it unavailable
        path_dirs = env.get("PATH", "").split(os.pathsep)
        filtered = [d for d in path_dirs if "zephyr-cli" not in d and "zephyr_cli" not in d]
        env["PATH"] = os.pathsep.join(filtered)

    return env


def run_opencode(
    prompt: str,
    model: str,
    workdir: Path,
    env: dict[str, str],
) -> tuple[int, str, str, float]:
    """Run opencode in non-interactive mode. Returns (returncode, stdout, stderr, elapsed)."""
    cmd = [
        "opencode",
        "run",
        prompt,
        "--model",
        model,
        "--format",
        "json",
        "--dangerously-skip-permissions",
        # Pin the project directory explicitly — otherwise OpenCode roots at
        # the nearest enclosing git repo instead of this workdir.
        "--dir",
        str(workdir),
    ]

    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=workdir,
            env=env,
            timeout=600,  # 10 min max per task
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        return 1, "", "Timed out after 600s", elapsed

    elapsed = time.monotonic() - start
    return result.returncode, result.stdout, result.stderr, elapsed


def save_metadata(
    run_dir: Path,
    task: dict,
    condition: str,
    model: str,
    agent_version: str,
    returncode: int,
    elapsed: float,
    stdout: str,
    stderr: str,
    docs_info: dict | None = None,
) -> None:
    docs_info = docs_info or {}
    meta = {
        "task": task["name"],
        "difficulty": task["difficulty"],
        "board": task["board"],
        "condition": condition,
        "model": model,
        "agent": "opencode",
        "agent_version": agent_version,
        "timestamp": datetime.now(UTC).isoformat(),
        "wall_clock_seconds": round(elapsed, 2),
        "opencode_returncode": returncode,
        # Whether the treatment arm genuinely had the docs corpus available.
        "docs_provisioned": bool(docs_info.get("provisioned"))
        if condition == "treatment"
        else False,
        "docs_version": docs_info.get("version"),
    }
    (run_dir / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n")
    (run_dir / "stdout.txt").write_text(stdout)
    (run_dir / "stderr.txt").write_text(stderr)


_ARTIFACT_SKIP = {".agents", ".git", "zephyr-docs"}


def _project_root(workdir: Path) -> Path:
    """Find the directory holding the agent's generated ``CMakeLists.txt``.

    The agent may place the project at the workdir top level or nest it one
    level down in a subdirectory (e.g. ``app/``); the evaluator expects the
    project files at the top of the run directory, so the directory holding
    ``CMakeLists.txt`` is the root to flatten from.
    """
    if (workdir / "CMakeLists.txt").exists():
        return workdir
    nested = [
        d
        for d in sorted(workdir.iterdir())
        if d.is_dir() and d.name not in _ARTIFACT_SKIP and (d / "CMakeLists.txt").exists()
    ]
    return nested[0] if nested else workdir


def collect_artifacts(workdir: Path, run_dir: Path) -> None:
    """Copy the agent's generated project files from *workdir* into *run_dir*.

    The agent may nest the project in a subdirectory; the directory holding its
    ``CMakeLists.txt`` is treated as the project root and flattened into
    *run_dir*. Benchmark scaffolding (the ``.agents/`` skills dir, the
    ``zephyr-docs`` corpus symlink, and the local ``.git``) is skipped.
    """
    src = _project_root(workdir)
    for item in sorted(src.iterdir()):
        if item.name in _ARTIFACT_SKIP:
            continue
        dest = run_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)


def run_single(
    task_name: str,
    condition: str,
    model: str,
    run_index: int,
    agent_version: str,
    board: str | None = None,
    docs_info: dict | None = None,
    write_usage_json: bool = True,
) -> Path:
    """Execute a single benchmark run and return the result directory."""
    task = load_task(task_name, board=board)
    slug = _slug(model)
    run_dir = RESULTS_DIR / slug / task_name / condition / f"run_{run_index}"

    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"  [{condition}] run {run_index}: opencode run --model {model} ...")
    # The agent works in a temp directory OUTSIDE the zephyr-cli repo. OpenCode
    # roots the project at the nearest enclosing git repo, so a workdir inside
    # this repo would let the agent explore — and write into — zephyr-cli
    # itself. Generated files are copied into run_dir afterwards for scoring.
    with tempfile.TemporaryDirectory(prefix="zbench-") as tmp:
        workdir = Path(tmp)
        env = prepare_workdir(task, condition, workdir, docs_info=docs_info)
        returncode, stdout, stderr, elapsed = run_opencode(
            task["prompt"].strip(),
            model,
            workdir,
            env,
        )
        collect_artifacts(workdir, run_dir)

    save_metadata(
        run_dir,
        task,
        condition,
        model,
        agent_version,
        returncode,
        elapsed,
        stdout,
        stderr,
        docs_info=docs_info,
    )
    # Derive token/process metrics from the transcript we just saved.
    if write_usage_json:
        write_usage(run_dir, force=True)
    status = "OK" if returncode == 0 else f"FAIL(rc={returncode})"
    print(f"    {status} in {elapsed:.1f}s")
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Zephyr-CLI AI code quality benchmarks",
    )
    parser.add_argument(
        "--models",
        help="Comma-separated provider/model list, e.g. "
        "anthropic/claude-opus-4-6,anthropic/claude-sonnet-4-6",
    )
    parser.add_argument(
        "--model",
        help="A single provider/model — alias for --models with one entry",
    )
    parser.add_argument(
        "--board",
        default=DEFAULT_BOARD,
        help=f"Zephyr board identifier for hardware tasks (default: {DEFAULT_BOARD})",
    )
    parser.add_argument(
        "--tasks",
        help="Comma-separated task names (default: all)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of runs per task per condition (default: 3)",
    )
    parser.add_argument(
        "--condition",
        choices=["both", "baseline", "treatment"],
        default="both",
        help="Which condition(s) to run (default: both)",
    )
    parser.add_argument(
        "--native-sim-only",
        action="store_true",
        help="Only run tasks that target native_sim (skips hardware tasks)",
    )
    parser.add_argument(
        "--no-usage",
        action="store_true",
        help="Skip deriving usage.json (token/process metrics) after each run",
    )
    args = parser.parse_args()

    # Resolve the model list (dedupe, preserve order). Every task is run under
    # each model; accuracy and tokens are reported per model, never averaged.
    models: list[str] = []
    if args.models:
        models += [m.strip() for m in args.models.split(",") if m.strip()]
    if args.model:
        models.append(args.model.strip())
    models = list(dict.fromkeys(models))
    if not models:
        parser.error(
            "provide --models or --model, e.g. "
            "--models anthropic/claude-opus-4-6,anthropic/claude-sonnet-4-6"
        )

    # Verify opencode is installed
    agent_version = opencode_version()
    if agent_version == "unknown":
        print("WARNING: 'opencode' not found in PATH. Install from https://opencode.ai")

    # Determine tasks
    task_names = [t.strip() for t in args.tasks.split(",")] if args.tasks else available_tasks()

    # Filter to native_sim tasks only if requested
    if args.native_sim_only:
        native_tasks = []
        for name in task_names:
            t = load_task(name, board=args.board)
            if t.get("board") == "native_sim":
                native_tasks.append(name)
        skipped = set(task_names) - set(native_tasks)
        if skipped:
            print(f"--native-sim-only: skipping hardware tasks: {', '.join(sorted(skipped))}")
        task_names = native_tasks

    conditions = ["baseline", "treatment"] if args.condition == "both" else [args.condition]

    # Provision the docs cache once — only needed when a treatment arm runs.
    docs_info = {"provisioned": False, "version": None, "path": None}
    if "treatment" in conditions:
        docs_info = provision_docs()

    print(
        f"Benchmark: models={models}, board={args.board}, tasks={task_names}, "
        f"runs={args.runs}, conditions={conditions}"
    )
    print(f"OpenCode version: {agent_version}")
    print(f"Results → {RESULTS_DIR}\n")

    for model in models:
        print(f"=== Model: {model} ===")
        for task_name in task_names:
            print(f"Task: {task_name}")
            for condition in conditions:
                for run_idx in range(1, args.runs + 1):
                    run_single(
                        task_name,
                        condition,
                        model,
                        run_idx,
                        agent_version,
                        board=args.board,
                        docs_info=docs_info,
                        write_usage_json=not args.no_usage,
                    )
            print()

    print("Done. Run `python -m benchmarks.evaluate` to score results.")


if __name__ == "__main__":
    main()
