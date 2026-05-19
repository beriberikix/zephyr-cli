"""Derive token + process usage metrics for benchmark runs.

Each run directory holds a verbatim ``stdout.txt`` JSONL transcript.  This
module parses it (via :mod:`benchmarks.transcript`) and writes a sibling
``usage.json`` — a *derived-analytics* file kept separate from the *provenance*
``metadata.json``.  Because it works from the saved transcript, it can backfill
runs the agent already produced without any re-runs.

Usage:
    python -m benchmarks.usage [--results-dir benchmarks/results/] [--force]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from benchmarks.transcript import parse_transcript_file

BENCHMARKS_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BENCHMARKS_DIR / "results"

USAGE_SCHEMA = 1


def build_usage(run_dir: Path) -> dict | None:
    """Parse ``stdout.txt`` in *run_dir* into a usage dict, or None if absent."""
    stdout = run_dir / "stdout.txt"
    if not stdout.exists():
        return None

    header: dict = {"schema": USAGE_SCHEMA}
    meta_file = run_dir / "metadata.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
            header.update(
                task=meta.get("task"),
                condition=meta.get("condition"),
                model=meta.get("model"),
            )
        except (json.JSONDecodeError, ValueError):
            pass

    metrics = parse_transcript_file(stdout)
    return {**header, **metrics.to_dict()}


def write_usage(run_dir: Path, force: bool = False) -> bool:
    """Write ``usage.json`` for *run_dir*. Returns True if written."""
    usage_path = run_dir / "usage.json"
    if usage_path.exists() and not force:
        return False
    usage = build_usage(run_dir)
    if usage is None:
        return False
    usage_path.write_text(json.dumps(usage, indent=2) + "\n")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill usage.json for benchmark runs from their transcripts",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=RESULTS_DIR,
        help=f"Results directory (default: {RESULTS_DIR})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute usage.json even if it already exists",
    )
    args = parser.parse_args()

    if not args.results_dir.is_dir():
        sys.exit(f"No results directory: {args.results_dir}")

    run_dirs = sorted(p.parent for p in args.results_dir.rglob("stdout.txt"))
    if not run_dirs:
        sys.exit(f"No runs (stdout.txt) found in {args.results_dir}")

    written = 0
    for run_dir in run_dirs:
        if write_usage(run_dir, force=args.force):
            written += 1
    print(f"Wrote usage.json for {written}/{len(run_dirs)} runs in {args.results_dir}")


if __name__ == "__main__":
    main()
