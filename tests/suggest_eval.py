"""Skills-suggest matcher eval — metric computation and artifact emitter.

``compute_suggest_metrics()`` is the single source of truth, imported by
``tests/test_suggest_eval.py`` (the regression gate that asserts accuracy
floors).  Run it as a script to emit shareable artifacts for CI:

    python -m tests.suggest_eval --json suggest-eval.json --md suggest-eval.md
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from zephyr_cli.core.registry import suggest_skills
from zephyr_cli.schemas.skills import SkillsIndex

DATA = Path(__file__).parent / "data" / "suggest_eval"
FIXTURE = DATA / "index.fixture.json"
QUERIES = DATA / "queries.jsonl"


def load_cases(queries_path: Path = QUERIES) -> list[dict]:
    """Load the labeled query corpus (one JSON object per line)."""
    return [
        json.loads(line)
        for line in queries_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_index(fixture_path: Path = FIXTURE) -> SkillsIndex:
    """Load the frozen skills-index fixture the corpus was labeled against."""
    return SkillsIndex.model_validate_json(fixture_path.read_text(encoding="utf-8"))


def compute_suggest_metrics(index: SkillsIndex, cases: list[dict]) -> dict:
    """Run the matcher over the corpus and compute accuracy metrics.

    Returns Recall@1/@3, false-positive rate, MRR, a per-skill breakdown, and
    the list of misses / false positives.
    """
    pos = neg = hit1 = hit3 = fp = 0
    rr_sum = 0.0
    per_skill: dict[str, dict] = defaultdict(lambda: {"n": 0, "hit1": 0, "hit3": 0})
    misses: list[tuple[str, str, str]] = []

    for case in cases:
        query = case["query"]
        expected = case.get("expected")
        results = suggest_skills(
            index,
            query,
            kconfig_symbols=case.get("kconfig") or None,
            dts_compatibles=case.get("dts") or None,
        )
        names = [s.skill.name for s in results]

        if expected is None:
            neg += 1
            if names:
                fp += 1
                misses.append(("FP", query, names[0]))
            continue

        pos += 1
        stats = per_skill[expected]
        stats["n"] += 1
        if names[:1] == [expected]:
            hit1 += 1
            stats["hit1"] += 1
        if expected in names[:3]:
            hit3 += 1
            stats["hit3"] += 1
        else:
            misses.append(("MISS", query, names[0] if names else "(none)"))
        if expected in names:
            rr_sum += 1.0 / (names.index(expected) + 1)

    return {
        "positives": pos,
        "negatives": neg,
        "recall_at_1": hit1 / pos if pos else 0.0,
        "recall_at_3": hit3 / pos if pos else 0.0,
        "false_positive_rate": fp / neg if neg else 0.0,
        "mrr": rr_sum / pos if pos else 0.0,
        "per_skill": dict(per_skill),
        "misses": misses,
    }


def format_report(m: dict) -> str:
    """Plain-text report — also printed by the pytest gate under ``-s``."""
    lines = [
        "=== zephyr-cli `skills suggest` — eval ===",
        f"corpus: {m['positives']} positives, {m['negatives']} negatives",
        (
            f"Recall@1={m['recall_at_1'] * 100:.1f}%  "
            f"Recall@3={m['recall_at_3'] * 100:.1f}%  "
            f"MRR={m['mrr']:.3f}  "
            f"FP-rate={m['false_positive_rate'] * 100:.1f}%"
        ),
        f"{'skill':26}{'n':>4}{'R@1':>8}{'R@3':>8}",
    ]
    for name in sorted(m["per_skill"]):
        s = m["per_skill"][name]
        lines.append(
            f"{name:26}{s['n']:>4}"
            f"{s['hit1'] / s['n'] * 100:>7.0f}%{s['hit3'] / s['n'] * 100:>7.0f}%"
        )
    if m["misses"]:
        lines.append(f"-- {len(m['misses'])} miss/FP --")
        for kind, query, got in m["misses"]:
            lines.append(f"  [{kind}] got={got!r}  <-  {query[:72]}")
    return "\n".join(lines)


def format_markdown(m: dict) -> str:
    """Markdown report for the CI artifact."""
    lines = [
        "# Skills-Suggest Matcher Eval\n",
        f"Corpus: **{m['positives']}** positive / **{m['negatives']}** negative queries.\n",
        "| Recall@1 | Recall@3 | MRR | FP-rate |",
        "|---------:|---------:|----:|--------:|",
        (
            f"| {m['recall_at_1'] * 100:.1f}% | {m['recall_at_3'] * 100:.1f}% "
            f"| {m['mrr']:.3f} | {m['false_positive_rate'] * 100:.1f}% |\n"
        ),
        "## Per-skill\n",
        "| Skill | n | R@1 | R@3 |",
        "|-------|--:|----:|----:|",
    ]
    for name in sorted(m["per_skill"]):
        s = m["per_skill"][name]
        lines.append(
            f"| {name} | {s['n']} | {s['hit1'] / s['n'] * 100:.0f}% "
            f"| {s['hit3'] / s['n'] * 100:.0f}% |"
        )
    lines.append("")
    if m["misses"]:
        lines.append(f"## {len(m['misses'])} misses / false positives\n")
        for kind, query, got in m["misses"]:
            lines.append(f"- `[{kind}]` got `{got}` ← {query}")
        lines.append("")
    return "\n".join(lines)


def _json_safe(m: dict) -> dict:
    """Convert miss tuples to lists so the dict is JSON-serializable."""
    out = dict(m)
    out["misses"] = [list(x) for x in m["misses"]]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Skills-suggest matcher eval")
    parser.add_argument("--json", type=Path, help="Write the metrics JSON here")
    parser.add_argument("--md", type=Path, help="Write the Markdown report here")
    args = parser.parse_args()

    metrics = compute_suggest_metrics(load_index(), load_cases())
    print(format_report(metrics))

    if args.json:
        args.json.write_text(json.dumps(_json_safe(metrics), indent=2) + "\n")
        print(f"\nWrote {args.json}")
    if args.md:
        args.md.write_text(format_markdown(metrics))
        print(f"Wrote {args.md}")


if __name__ == "__main__":
    main()
