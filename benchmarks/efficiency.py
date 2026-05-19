"""Token-efficiency metrics for the benchmark — a parallel axis to quality.

The quality score in :mod:`benchmarks.scoring` is left untouched.  Efficiency is
reported separately because "did accuracy improve *without* token bloat" is
inherently a two-variable question — collapsing it into one number destroys it.

These are deliberately *directional* metrics: deltas, ratios, and a win-rate,
not precise cost accounting.  The goal is to tell whether a quality gain was
bought with excess tokens, and to point at where tokens are spent so waste can
be trimmed (cache-read ratio, tool-output share, retry-loop waste).

All functions are pure: they take the ``usage`` dicts (see :mod:`benchmarks.usage`)
and ``evaluation`` dicts (see :mod:`benchmarks.evaluate`) and return plain dicts.
"""

from __future__ import annotations

EPSILON = 1e-6
CHARS_PER_TOKEN = 4  # rough heuristic for the tool-output token estimate

# Below this absolute percentage a delta is treated as "no material change".
NEUTRAL_BAND_PCT = 1.0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _ratio(num: float, den: float) -> float:
    return num / den if den else 0.0


def _usage_of(e: dict) -> dict:
    return e.get("usage") or {}


def _weighted_of(e: dict) -> float:
    return float(e.get("weighted_total", 0.0) or 0.0)


def _build_ok_of(e: dict) -> bool:
    return bool(e.get("details", {}).get("build", {}).get("build_ok"))


def run_efficiency(usage: dict, weighted_total: float, build_ok: bool) -> dict:
    """Per-run efficiency metrics from one run's usage dict and its quality score."""
    total = usage.get("tokens_total", 0) or 0
    tool_output_tokens_est = usage.get("tool_output_chars", 0) / CHARS_PER_TOKEN
    return {
        "tokens_total": total,
        "tokens_per_quality_point": total / max(weighted_total, EPSILON),
        "tokens_per_successful_build": total if build_ok else None,
        "cache_read_ratio": _ratio(usage.get("tokens_cache_read", 0), total),
        "tool_output_token_share": _ratio(tool_output_tokens_est, total),
        "wasted_token_share_est": _ratio(usage.get("tokens_in_retry_loops_est", 0), total),
        "fresh_token_ratio": _ratio(usage.get("tokens_fresh", 0), total),
        "build_attempts": usage.get("build_attempts", 0),
        "build_retry_count": usage.get("build_retry_count", 0),
        "tool_calls_total": usage.get("tool_calls_total", 0),
        "zephyr_cli_invocations": usage.get("zephyr_cli_invocations", 0),
        "skill_invocations": usage.get("skill_invocations", 0),
    }


def condition_efficiency(evals: list[dict]) -> dict:
    """Aggregate efficiency metrics over all runs of one condition.

    *evals* are evaluation dicts with a ``usage`` key attached (see
    ``report.collect_evaluations``).
    """
    if not evals:
        return {"runs": 0}

    totals = [_usage_of(e).get("tokens_total", 0) or 0 for e in evals]
    quality = [_weighted_of(e) for e in evals]
    per_run = [run_efficiency(_usage_of(e), _weighted_of(e), _build_ok_of(e)) for e in evals]
    successful = [t for t, e in zip(totals, evals, strict=True) if _build_ok_of(e)]

    mean_tokens = _mean(totals)
    mean_quality = _mean(quality)
    return {
        "runs": len(evals),
        "tokens_per_task": mean_tokens,
        "tokens_total_sum": sum(totals),
        "mean_quality": mean_quality,
        # Ratio of means (not mean of ratios) — stable when a run scores ~0.
        "tokens_per_quality_point": mean_tokens / max(mean_quality, EPSILON),
        "tokens_per_successful_build": _mean(successful) if successful else None,
        "cache_read_ratio": _mean([r["cache_read_ratio"] for r in per_run]),
        "tool_output_token_share": _mean([r["tool_output_token_share"] for r in per_run]),
        "wasted_token_share_est": _mean([r["wasted_token_share_est"] for r in per_run]),
        "build_attempts": _mean([r["build_attempts"] for r in per_run]),
        "build_retry_count": _mean([r["build_retry_count"] for r in per_run]),
        "tool_calls_total": _mean([r["tool_calls_total"] for r in per_run]),
        "zephyr_cli_invocations": _mean([r["zephyr_cli_invocations"] for r in per_run]),
        "skill_invocations": _mean([r["skill_invocations"] for r in per_run]),
    }


def delta_pct(baseline: float, treatment: float) -> float:
    """Percentage change from baseline to treatment. 0 baseline → 0%."""
    if not baseline:
        return 0.0
    return (treatment - baseline) / abs(baseline) * 100.0


def verdict(accuracy_delta_pct: float, token_delta_pct: float) -> str:
    """One-line label crossing the accuracy and token axes."""
    band = NEUTRAL_BAND_PCT
    acc_up = accuracy_delta_pct > band
    acc_down = accuracy_delta_pct < -band
    tok_up = token_delta_pct > band
    tok_down = token_delta_pct < -band

    if acc_up and tok_down:
        return "Win-win: more accurate and fewer tokens"
    if acc_up and tok_up:
        return "Quality bought with tokens — judge by tokens/quality-point"
    if acc_up:
        return "Better accuracy at no token cost"
    if acc_down:
        return "Regression: accuracy dropped"
    if tok_down:
        return "Free efficiency: same accuracy, fewer tokens"
    if tok_up:
        return "Regression: more tokens, no accuracy gain"
    return "Neutral: no material change"


def compare(baseline_evals: list[dict], treatment_evals: list[dict]) -> dict:
    """Compare baseline vs treatment efficiency. Both lists are for one model."""
    b = condition_efficiency(baseline_evals)
    t = condition_efficiency(treatment_evals)
    accuracy_delta = delta_pct(b.get("mean_quality", 0.0), t.get("mean_quality", 0.0))
    token_delta = delta_pct(b.get("tokens_per_task", 0.0), t.get("tokens_per_task", 0.0))
    efficiency_delta = delta_pct(
        b.get("tokens_per_quality_point", 0.0), t.get("tokens_per_quality_point", 0.0)
    )
    return {
        "baseline": b,
        "treatment": t,
        "accuracy_delta_pct": accuracy_delta,
        "token_delta_pct": token_delta,
        # Negative efficiency delta = treatment spends fewer tokens per quality point.
        "efficiency_delta_pct": efficiency_delta,
        "verdict": verdict(accuracy_delta, token_delta),
    }


def win_rate(baseline_evals: list[dict], treatment_evals: list[dict]) -> dict:
    """Fraction of (task, run) pairs where treatment quality >= baseline.

    Runs are paired per task by sorted quality order, which tolerates unequal
    run counts between conditions.
    """

    def by_task(evals: list[dict]) -> dict[str, list[float]]:
        groups: dict[str, list[float]] = {}
        for e in evals:
            task = e.get("metadata", {}).get("task", "?")
            groups.setdefault(task, []).append(_weighted_of(e))
        return groups

    b_tasks = by_task(baseline_evals)
    t_tasks = by_task(treatment_evals)
    wins = ties = total = 0
    for task in b_tasks.keys() & t_tasks.keys():
        b_sorted = sorted(b_tasks[task])
        t_sorted = sorted(t_tasks[task])
        # Unequal run counts are tolerated — zip stops at the shorter side.
        for bw, tw in zip(b_sorted, t_sorted, strict=False):
            total += 1
            if tw > bw:
                wins += 1
            elif tw == bw:
                ties += 1
    return {
        "wins": wins,
        "ties": ties,
        "total": total,
        "rate": (wins + ties) / total if total else 0.0,
    }
