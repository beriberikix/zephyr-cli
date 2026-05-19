"""Benchmark report generator — produces a Markdown summary of results.

The report is segmented **per model**: each model gets its own quality and
token-efficiency sections, and a final cross-model table puts them side by
side.  Quality and efficiency are reported as two parallel axes — see
:mod:`benchmarks.efficiency` for why they are never collapsed into one number.

Usage:
    python -m benchmarks.report [--results-dir benchmarks/results/]
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from benchmarks.efficiency import compare, condition_efficiency, delta_pct, win_rate
from benchmarks.scoring import WEIGHTS

BENCHMARKS_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BENCHMARKS_DIR / "results"

DIMENSIONS = list(WEIGHTS.keys())


# ── Loading ──────────────────────────────────────────────────────────────


def collect_evaluations(results_dir: Path) -> list[dict]:
    """Load every evaluation.json, attaching the sibling usage.json as ``usage``."""
    evals = []
    for path in sorted(results_dir.rglob("evaluation.json")):
        e = json.loads(path.read_text())
        usage_path = path.parent / "usage.json"
        if usage_path.exists():
            try:
                e["usage"] = json.loads(usage_path.read_text())
            except (json.JSONDecodeError, ValueError):
                e["usage"] = {}
        else:
            e["usage"] = {}
        evals.append(e)
    return evals


def group_by(evals: list[dict], key_fn) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for e in evals:
        groups[key_fn(e)].append(e)
    return dict(groups)


def avg(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = avg(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


# ── Formatting helpers ───────────────────────────────────────────────────


def _fmt_tokens(n: float) -> str:
    return f"{n:,.0f}"


def _fmt_ratio_pct(frac: float) -> str:
    """Format a 0..1 fraction as a percentage."""
    return f"{frac * 100:.0f}%"


def _fmt_signed_pct(pct: float) -> str:
    """Format an already-percentage value with an explicit sign."""
    return f"{pct:+.1f}%"


# ── Quality summary ──────────────────────────────────────────────────────


def render_summary_table(evals: list[dict]) -> list[str]:
    """The by-condition quality table (unchanged scoring dimensions)."""
    by_condition = group_by(evals, lambda e: e["metadata"]["condition"])
    lines = ["### Quality\n"]
    header = (
        "| Condition | "
        + " | ".join(d.replace("_", " ").title() for d in DIMENSIONS)
        + " | **Weighted** | Std |"
    )
    sep = "|-----------|" + "|".join("--------:" for _ in DIMENSIONS) + "|------------:|---:|"
    lines.append(header)
    lines.append(sep)

    for cond in ["baseline", "treatment"]:
        runs = by_condition.get(cond, [])
        if not runs:
            continue
        avgs = {d: avg([r["scores"].get(d, 0.0) for r in runs]) for d in DIMENSIONS}
        weighted_vals = [r["weighted_total"] for r in runs]
        weighted = avg(weighted_vals)
        sd = stdev(weighted_vals)
        sd_flag = " ⚠" if sd > 0.1 else ""
        cells = " | ".join(f"{avgs[d]:.2f}" for d in DIMENSIONS)
        lines.append(f"| {cond} | {cells} | **{weighted:.2f}** | {sd:.2f}{sd_flag} |")
    lines.append("")

    baseline_runs = by_condition.get("baseline", [])
    treatment_runs = by_condition.get("treatment", [])
    if baseline_runs and treatment_runs:
        b_avg = avg([r["weighted_total"] for r in baseline_runs])
        t_avg = avg([r["weighted_total"] for r in treatment_runs])
        d = t_avg - b_avg
        pct = (d / b_avg * 100) if b_avg > 0 else 0
        sign = "+" if d >= 0 else ""
        lines.append(f"**Treatment vs Baseline:** {sign}{d:.3f} ({sign}{pct:.1f}%)\n")
    return lines


# ── Token efficiency ─────────────────────────────────────────────────────


def render_efficiency_section(evals: list[dict]) -> list[str]:
    """Verdict, efficiency table, per-task token deltas, and win-rate."""
    by_condition = group_by(evals, lambda e: e["metadata"]["condition"])
    baseline = by_condition.get("baseline", [])
    treatment = by_condition.get("treatment", [])

    lines = ["### Token Efficiency\n"]
    lines.append(
        "_Directional metrics — answers whether accuracy was bought with token "
        "bloat, and where waste sits. Estimated values are marked (est)._\n"
    )

    if not (baseline and treatment):
        # Only one condition present — report its raw efficiency, no comparison.
        cond = "baseline" if baseline else "treatment"
        runs = baseline or treatment
        if runs:
            c = condition_efficiency(runs)
            lines.append(f"Only `{cond}` runs present — no A/B comparison.\n")
            lines.append(f"- Tokens/task: {_fmt_tokens(c['tokens_per_task'])}")
            lines.append(f"- Cache-read ratio: {_fmt_ratio_pct(c['cache_read_ratio'])}\n")
        return lines

    cmp = compare(baseline, treatment)
    b, t = cmp["baseline"], cmp["treatment"]

    # Verdict line.
    lines.append(
        f"**Verdict:** accuracy {_fmt_signed_pct(cmp['accuracy_delta_pct'])}, "
        f"processed tokens {_fmt_signed_pct(cmp['token_delta_pct'])} "
        f"→ _{cmp['verdict']}_\n"
    )

    # Efficiency comparison table.
    cols = [
        ("Tokens/task", lambda c: _fmt_tokens(c["tokens_per_task"])),
        ("Cache-read ratio", lambda c: _fmt_ratio_pct(c["cache_read_ratio"])),
        ("Tool-output share (est)", lambda c: _fmt_ratio_pct(c["tool_output_token_share"])),
        ("Tokens/quality-pt", lambda c: _fmt_tokens(c["tokens_per_quality_point"])),
        (
            "Tokens/successful build",
            lambda c: (
                _fmt_tokens(c["tokens_per_successful_build"])
                if c["tokens_per_successful_build"] is not None
                else "n/a"
            ),
        ),
        ("Retry-waste share (est)", lambda c: _fmt_ratio_pct(c["wasted_token_share_est"])),
        ("Build retries", lambda c: f"{c['build_retry_count']:.1f}"),
        ("zephyr-cli calls", lambda c: f"{c['zephyr_cli_invocations']:.1f}"),
    ]
    lines.append("| Condition | " + " | ".join(name for name, _ in cols) + " |")
    lines.append("|-----------|" + "|".join("--------:" for _ in cols) + "|")
    lines.append("| baseline | " + " | ".join(fn(b) for _, fn in cols) + " |")
    lines.append("| treatment | " + " | ".join(fn(t) for _, fn in cols) + " |")
    lines.append("")
    lines.append(
        f"_Efficiency delta (tokens per quality point): "
        f"{_fmt_signed_pct(cmp['efficiency_delta_pct'])} "
        f"(negative = treatment more efficient)._\n"
    )

    # Per-task token deltas.
    lines.append("**Per-task token deltas:**\n")
    lines.append(
        "| Task | Baseline tokens | Treatment tokens | Δ tokens | Δ accuracy | Treatment win? |"
    )
    lines.append(
        "|------|----------------:|-----------------:|---------:|-----------:|:--------------:|"
    )
    by_task = group_by(evals, lambda e: e["metadata"]["task"])
    for task_name in sorted(by_task.keys()):
        task_evals = by_task[task_name]
        tc = group_by(task_evals, lambda e: e["metadata"]["condition"])
        tb, tt = tc.get("baseline", []), tc.get("treatment", [])
        if not (tb and tt):
            continue
        be = condition_efficiency(tb)
        te = condition_efficiency(tt)
        d_tokens = delta_pct(be["tokens_per_task"], te["tokens_per_task"])
        d_acc = delta_pct(be["mean_quality"], te["mean_quality"])
        win = "✓" if te["mean_quality"] >= be["mean_quality"] else "✗"
        lines.append(
            f"| {task_name} | {_fmt_tokens(be['tokens_per_task'])} "
            f"| {_fmt_tokens(te['tokens_per_task'])} "
            f"| {_fmt_signed_pct(d_tokens)} | {_fmt_signed_pct(d_acc)} | {win} |"
        )
    lines.append("")

    # Win-rate.
    wr = win_rate(baseline, treatment)
    if wr["total"]:
        lines.append(
            f"**Win-rate:** treatment ≥ baseline on {wr['wins'] + wr['ties']}/"
            f"{wr['total']} task-run pairs ({wr['rate'] * 100:.0f}%).\n"
        )
    return lines


# ── Per-task quality breakdown ───────────────────────────────────────────


def render_per_task(evals: list[dict]) -> list[str]:
    lines = ["### Per-Task Breakdown\n"]
    by_task = group_by(evals, lambda e: e["metadata"]["task"])
    for task_name in sorted(by_task.keys()):
        task_evals = by_task[task_name]
        diff = task_evals[0]["metadata"].get("difficulty", "?")
        lines.append(f"#### {task_name} ({diff})\n")

        task_by_cond = group_by(task_evals, lambda e: e["metadata"]["condition"])
        header = (
            "| Condition | Runs | Build | "
            + " | ".join(d.replace("_", " ").title() for d in DIMENSIONS)
            + " | Weighted | Std |"
        )
        sep = (
            "|-----------|-----:|------:|"
            + "|".join("--------:" for _ in DIMENSIONS)
            + "|---------:|---:|"
        )
        lines.append(header)
        lines.append(sep)

        for cond in ["baseline", "treatment"]:
            runs = task_by_cond.get(cond, [])
            if not runs:
                continue
            n = len(runs)
            build_ok = sum(1 for r in runs if r["details"]["build"]["build_ok"])
            avgs = {d: avg([r["scores"].get(d, 0.0) for r in runs]) for d in DIMENSIONS}
            weighted_vals = [r["weighted_total"] for r in runs]
            weighted = avg(weighted_vals)
            sd = stdev(weighted_vals)
            sd_flag = " ⚠" if sd > 0.1 else ""
            cells = " | ".join(f"{avgs[d]:.2f}" for d in DIMENSIONS)
            lines.append(
                f"| {cond} | {n} | {build_ok}/{n} | {cells} | {weighted:.2f} | {sd:.2f}{sd_flag} |"
            )
        lines.append("")

        # Build-error details for any failing run.
        for e in task_evals:
            build = e["details"]["build"]
            if not build["build_ok"] and build.get("errors"):
                cond = e["metadata"]["condition"]
                lines.append(f"<details><summary>{cond} build errors</summary>\n")
                lines.append("```")
                for err in build["errors"][:5]:
                    lines.append(err)
                lines.append("```\n</details>\n")
    return lines


# ── Cross-model comparison ───────────────────────────────────────────────


def render_cross_model(by_model: dict[str, list[dict]]) -> list[str]:
    lines = ["## Cross-Model Comparison\n"]
    lines.append("| Model | Accuracy Δ | Token Δ | Efficiency Δ | Verdict |")
    lines.append("|-------|-----------:|--------:|-------------:|---------|")
    for model in sorted(by_model.keys()):
        evals = by_model[model]
        by_cond = group_by(evals, lambda e: e["metadata"]["condition"])
        b, t = by_cond.get("baseline", []), by_cond.get("treatment", [])
        if not (b and t):
            lines.append(f"| {model} | — | — | — | single condition only |")
            continue
        cmp = compare(b, t)
        lines.append(
            f"| {model} | {_fmt_signed_pct(cmp['accuracy_delta_pct'])} "
            f"| {_fmt_signed_pct(cmp['token_delta_pct'])} "
            f"| {_fmt_signed_pct(cmp['efficiency_delta_pct'])} "
            f"| {cmp['verdict']} |"
        )
    lines.append("")
    return lines


# ── Component evals ──────────────────────────────────────────────────────


def render_component_evals(results_dir: Path) -> list[str]:
    """Fold in standalone component-eval artifacts when present."""
    lines: list[str] = []

    suggest = results_dir / "suggest-eval.json"
    if suggest.exists():
        try:
            m = json.loads(suggest.read_text())
            lines.append("## Component Eval — skills-suggest matcher\n")
            lines.append(
                f"Corpus: {m.get('positives', '?')} positive / "
                f"{m.get('negatives', '?')} negative queries.\n"
            )
            lines.append("| Recall@1 | Recall@3 | MRR | FP-rate |")
            lines.append("|---------:|---------:|----:|--------:|")
            lines.append(
                f"| {m.get('recall_at_1', 0) * 100:.1f}% "
                f"| {m.get('recall_at_3', 0) * 100:.1f}% "
                f"| {m.get('mrr', 0):.3f} "
                f"| {m.get('false_positive_rate', 0) * 100:.1f}% |\n"
            )
        except (json.JSONDecodeError, ValueError):
            pass

    docs = results_dir / "docs-eval.json"
    if docs.exists():
        try:
            d = json.loads(docs.read_text())
            lines.append("## Component Eval — docs grounding\n")
            lines.append("| Model | With docs | Without docs | Δ |")
            lines.append("|-------|----------:|-------------:|--:|")
            for row in d.get("models", []):
                w = row.get("with_docs", {})
                wo = row.get("without_docs", {})
                wr = w.get("passed", 0) / w["total"] if w.get("total") else 0.0
                wor = wo.get("passed", 0) / wo["total"] if wo.get("total") else 0.0
                lines.append(
                    f"| {row.get('model', '?')} "
                    f"| {w.get('passed', 0)}/{w.get('total', 0)} ({wr * 100:.0f}%) "
                    f"| {wo.get('passed', 0)}/{wo.get('total', 0)} ({wor * 100:.0f}%) "
                    f"| {(wr - wor) * 100:+.0f}pp |"
                )
            lines.append("")
        except (json.JSONDecodeError, ValueError):
            pass
    return lines


# ── Top-level ────────────────────────────────────────────────────────────


def generate_report(results_dir: Path) -> str:
    evals = collect_evaluations(results_dir)
    if not evals:
        return "No evaluation results found.\n"

    lines: list[str] = []
    models = sorted({e["metadata"]["model"] for e in evals})
    agent_versions = sorted({e["metadata"].get("agent_version", "?") for e in evals})
    lines.append("# Zephyr-CLI Benchmark Report\n")
    lines.append(f"**Model(s):** {', '.join(models)}  ")
    lines.append(f"**Agent:** OpenCode {', '.join(agent_versions)}  ")
    lines.append(f"**Total runs:** {len(evals)}\n")

    by_model = group_by(evals, lambda e: e["metadata"]["model"])

    # Cross-model comparison first when there is more than one model.
    if len(by_model) > 1:
        lines.extend(render_cross_model(by_model))

    # Per-model sections — quality and efficiency never cross model boundaries.
    for model in sorted(by_model.keys()):
        model_evals = by_model[model]
        lines.append(f"## Model: {model}\n")
        lines.extend(render_summary_table(model_evals))
        lines.extend(render_efficiency_section(model_evals))
        lines.extend(render_per_task(model_evals))

    lines.extend(render_component_evals(results_dir))

    lines.append("## Scoring Weights\n")
    for dim, weight in WEIGHTS.items():
        lines.append(f"- **{dim.replace('_', ' ').title()}**: {int(weight * 100)}%")
    lines.append(
        "\n_Token-efficiency metrics are a separate axis and are not folded "
        "into the weighted quality score._"
    )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate benchmark report")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=RESULTS_DIR,
        help=f"Results directory (default: {RESULTS_DIR})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output file (default: stdout)",
    )
    args = parser.parse_args()

    report = generate_report(args.results_dir)

    if args.output:
        args.output.write_text(report)
        print(f"Report written to {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
