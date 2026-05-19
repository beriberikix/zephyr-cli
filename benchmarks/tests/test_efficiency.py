"""Unit tests for benchmarks.efficiency.

Run from the repository root:  python -m pytest benchmarks/tests/
"""

from __future__ import annotations

import pytest

from benchmarks.efficiency import (
    compare,
    condition_efficiency,
    delta_pct,
    run_efficiency,
    verdict,
    win_rate,
)


def mk_eval(task: str, weighted: float, build_ok: bool, tokens_total: int, **usage) -> dict:
    """Build a minimal evaluation dict with a usage payload attached."""
    u = {
        "tokens_total": tokens_total,
        "tokens_cache_read": 0,
        "tokens_fresh": 0,
        "tool_output_chars": 0,
        "tokens_in_retry_loops_est": 0,
        "build_attempts": 0,
        "build_retry_count": 0,
        "tool_calls_total": 0,
        "zephyr_cli_invocations": 0,
        "skill_invocations": 0,
    }
    u.update(usage)
    return {
        "metadata": {"task": task},
        "weighted_total": weighted,
        "details": {"build": {"build_ok": build_ok}},
        "usage": u,
    }


def test_run_efficiency_basic() -> None:
    usage = {
        "tokens_total": 1000,
        "tokens_cache_read": 800,
        "tool_output_chars": 400,
        "tokens_in_retry_loops_est": 100,
        "tokens_fresh": 200,
    }
    r = run_efficiency(usage, weighted_total=0.5, build_ok=True)
    assert r["tokens_per_quality_point"] == 2000.0  # 1000 / 0.5
    assert r["tokens_per_successful_build"] == 1000
    assert r["cache_read_ratio"] == 0.8
    assert r["tool_output_token_share"] == 0.1  # (400/4) / 1000
    assert r["wasted_token_share_est"] == 0.1
    assert r["fresh_token_ratio"] == 0.2


def test_run_efficiency_failed_build_has_no_per_build_cost() -> None:
    r = run_efficiency({"tokens_total": 500}, weighted_total=0.2, build_ok=False)
    assert r["tokens_per_successful_build"] is None


def test_condition_efficiency_uses_ratio_of_means() -> None:
    evals = [
        mk_eval("a", 0.5, True, 1000),
        mk_eval("a", 0.7, True, 2000),
    ]
    c = condition_efficiency(evals)
    assert c["runs"] == 2
    assert c["tokens_per_task"] == 1500.0
    assert c["mean_quality"] == 0.6
    assert c["tokens_per_quality_point"] == 2500.0  # 1500 / 0.6


def test_delta_pct() -> None:
    assert delta_pct(100, 150) == 50.0
    assert delta_pct(100, 80) == -20.0
    assert delta_pct(0, 50) == 0.0  # undefined baseline → 0


def test_verdict_quadrants() -> None:
    assert "Win-win" in verdict(5, -5)
    assert "bought with tokens" in verdict(5, 5)
    assert verdict(5, 0) == "Better accuracy at no token cost"
    assert "accuracy dropped" in verdict(-5, -5)
    assert "Free efficiency" in verdict(0, -5)
    assert "no accuracy gain" in verdict(0, 5)
    assert "Neutral" in verdict(0, 0)


def test_win_rate_pairs_by_sorted_quality() -> None:
    baseline = [mk_eval("a", 0.5, True, 1), mk_eval("a", 0.6, True, 1)]
    treatment = [mk_eval("a", 0.7, True, 1), mk_eval("a", 0.55, True, 1)]
    wr = win_rate(baseline, treatment)
    assert wr["total"] == 2
    assert wr["wins"] == 2  # 0.55>0.5, 0.7>0.6
    assert wr["rate"] == 1.0


def test_win_rate_tolerates_unequal_run_counts() -> None:
    baseline = [mk_eval("a", 0.5, True, 1)]
    treatment = [mk_eval("a", 0.7, True, 1), mk_eval("a", 0.9, True, 1)]
    wr = win_rate(baseline, treatment)
    assert wr["total"] == 1  # zip stops at shorter side


def test_compare_end_to_end() -> None:
    baseline = [mk_eval("a", 0.5, True, 1000)]
    treatment = [mk_eval("a", 0.6, True, 1100)]
    c = compare(baseline, treatment)
    assert c["accuracy_delta_pct"] == pytest.approx(20.0)  # 0.5 → 0.6
    assert c["token_delta_pct"] == pytest.approx(10.0)  # 1000 → 1100
    assert "bought with tokens" in c["verdict"]
