"""Docs grounding eval — does the LLM-optimized docs corpus improve answers?

zephyr-cli has no docs *search* surface (docs are a cached markdown corpus), so
this is a **grounding** eval, not a *retrieval* eval: it measures whether the
corpus simply being present — reachable by the agent's read/grep tools — lifts
answer accuracy on version-specific Zephyr questions, the case where a model's
training knowledge is most likely stale.

For each question the agent is asked twice with an identical prompt:

* **without-docs** — a bare workspace.
* **with-docs**    — the same workspace with the docs corpus symlinked in as
  ``./docs``.

Answers are graded by deterministic substring matching (see ``grade``).

Caveats — this eval is deliberately lightweight and **directional**:
  * the question corpus is small and hand-curated, so results are not
    statistically significant;
  * substring grading is crude (mitigated by ``forbid_substrings`` catching the
    stale answer);
  * correctness drifts with Zephyr releases — each question carries a
    ``zephyr_version`` tag so staleness is visible.

Usage:
    python -m benchmarks.docs_eval --models anthropic/claude-opus-4-6,anthropic/claude-sonnet-4-6
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from benchmarks.run import (
    CONFIGS_DIR,
    _slug,
    isolate_workdir,
    opencode_version,
    provision_docs,
    run_opencode,
)

BENCHMARKS_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BENCHMARKS_DIR / "results"
QUESTIONS_FILE = BENCHMARKS_DIR / "data" / "docs_eval" / "questions.jsonl"

# A uniform line appended to every prompt so both arms get an identical prompt;
# it is a harmless no-op in the without-docs arm (no ./docs directory exists).
DOCS_HINT = (
    "\n\nIf a ./docs directory exists in this workspace it contains current "
    "Zephyr documentation — consult it before answering. Answer concisely."
)


def load_questions(path: Path = QUESTIONS_FILE) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def grade(answer: str, question: dict) -> bool:
    """A question passes if every expected substring (or any-of group) is
    present and no forbidden substring appears. Case-insensitive."""
    text = answer.lower()
    for entry in question.get("expect_substrings", []):
        if isinstance(entry, list):
            if not any(alt.lower() in text for alt in entry):
                return False
        elif entry.lower() not in text:
            return False
    return all(forbidden.lower() not in text for forbidden in question.get("forbid_substrings", []))


def extract_answer(stdout: str) -> str:
    """Join the assistant `text` events from an OpenCode JSONL transcript."""
    parts: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict) and obj.get("type") == "text":
            part = obj.get("part") or {}
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts) if parts else stdout


def _prepare_env() -> dict[str, str]:
    env = os.environ.copy()
    # VS Code snap overrides XDG_DATA_HOME, which breaks OpenCode auth discovery.
    xdg = env.get("XDG_DATA_HOME", "")
    if "snap" in xdg:
        env["XDG_DATA_HOME"] = str(Path.home() / ".local" / "share")
    return env


def run_question(
    question: dict,
    model: str,
    with_docs: bool,
    docs_info: dict,
    run_root: Path,
) -> dict:
    """Run one question under one arm. Returns a result dict."""
    arm = "with_docs" if with_docs else "without_docs"
    run_dir = run_root / question["id"] / arm
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    # Run the agent in a temp directory outside the repo so OpenCode cannot
    # root the project at the enclosing zephyr-cli repo (see run.run_single).
    with tempfile.TemporaryDirectory(prefix="zdocs-") as tmp:
        workdir = Path(tmp)
        isolate_workdir(workdir)
        # Skills are disabled in both arms (baseline config) so we isolate docs.
        shutil.copy2(CONFIGS_DIR / "baseline.opencode.json", workdir / "opencode.json")
        if with_docs and docs_info.get("path"):
            docs_path = Path(docs_info["path"])
            if docs_path.is_dir():
                (workdir / "docs").symlink_to(docs_path)
        prompt = question["question"] + DOCS_HINT
        returncode, stdout, stderr, elapsed = run_opencode(
            prompt, model, workdir, _prepare_env()
        )

    (run_dir / "stdout.txt").write_text(stdout)
    (run_dir / "stderr.txt").write_text(stderr)

    answer = extract_answer(stdout)
    (run_dir / "answer.txt").write_text(answer)
    passed = grade(answer, question)
    return {
        "id": question["id"],
        "arm": arm,
        "passed": passed,
        "returncode": returncode,
        "elapsed": round(elapsed, 2),
    }


def evaluate_model(model: str, questions: list[dict], docs_info: dict) -> dict:
    """Run every question under both arms for one model."""
    run_root = RESULTS_DIR / "docs_eval" / _slug(model)
    per_question: list[dict] = []
    with_passed = without_passed = 0

    for q in questions:
        print(f"  {q['id']}")
        without = run_question(q, model, with_docs=False, docs_info=docs_info, run_root=run_root)
        with_ = run_question(q, model, with_docs=True, docs_info=docs_info, run_root=run_root)
        with_passed += int(with_["passed"])
        without_passed += int(without["passed"])
        per_question.append(
            {
                "id": q["id"],
                "zephyr_version": q.get("zephyr_version"),
                "with_docs": with_["passed"],
                "without_docs": without["passed"],
            }
        )
        flag = {
            (True, True): "= both",
            (True, False): "+ docs helped",
            (False, True): "- docs hurt",
            (False, False): "= both failed",
        }[(with_["passed"], without["passed"])]
        print(f"    with={with_['passed']}  without={without['passed']}  {flag}")

    total = len(questions)
    return {
        "model": model,
        "with_docs": {"passed": with_passed, "total": total},
        "without_docs": {"passed": without_passed, "total": total},
        "questions": per_question,
    }


def format_markdown(report: dict) -> str:
    lines = [
        "# Docs Grounding Eval\n",
        "_Grounding eval (not retrieval): does the docs corpus being present "
        "improve answers? Directional — small hand-curated corpus._\n",
        "| Model | With docs | Without docs | Δ |",
        "|-------|----------:|-------------:|--:|",
    ]
    for row in report["models"]:
        w, wo = row["with_docs"], row["without_docs"]
        wr = w["passed"] / w["total"] if w["total"] else 0.0
        wor = wo["passed"] / wo["total"] if wo["total"] else 0.0
        lines.append(
            f"| {row['model']} | {w['passed']}/{w['total']} ({wr * 100:.0f}%) "
            f"| {wo['passed']}/{wo['total']} ({wor * 100:.0f}%) "
            f"| {(wr - wor) * 100:+.0f}pp |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Docs grounding eval")
    parser.add_argument(
        "--models",
        help="Comma-separated provider/model list",
    )
    parser.add_argument("--model", help="A single provider/model (alias for --models)")
    args = parser.parse_args()

    models: list[str] = []
    if args.models:
        models += [m.strip() for m in args.models.split(",") if m.strip()]
    if args.model:
        models.append(args.model.strip())
    models = list(dict.fromkeys(models))
    if not models:
        parser.error("provide --models or --model")

    if opencode_version() == "unknown":
        print("WARNING: 'opencode' not found in PATH. Install from https://opencode.ai")

    questions = load_questions()
    print(f"Docs grounding eval: {len(questions)} questions x {len(models)} model(s)")

    docs_info = provision_docs()
    if not docs_info.get("provisioned"):
        sys.exit("Docs could not be provisioned — cannot run the with-docs arm.")

    report = {"docs_version": docs_info.get("version"), "models": []}
    for model in models:
        print(f"=== Model: {model} ===")
        report["models"].append(evaluate_model(model, questions, docs_info))

    json_path = RESULTS_DIR / "docs-eval.json"
    md_path = RESULTS_DIR / "docs-eval.md"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    md_path.write_text(format_markdown(report))
    print(f"\nWrote {json_path}\nWrote {md_path}")
    print(format_markdown(report))


if __name__ == "__main__":
    main()
