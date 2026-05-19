"""Deterministic regression harness for `zephyr-cli skills suggest`.

Runs the matcher over a committed labeled query corpus and asserts accuracy
thresholds. This is the proof that skill selection works — it replaces the
unreliable LLM auto-trigger measurement.

The metric computation lives in :mod:`tests.suggest_eval` so it can also be
run as a script to emit JSON/Markdown artifacts:

    python -m tests.suggest_eval --json suggest-eval.json --md suggest-eval.md

Run `pytest tests/test_suggest_eval.py -s -q` to see the per-skill table.
"""

from __future__ import annotations

import pytest

from tests.suggest_eval import (
    compute_suggest_metrics,
    format_report,
    load_cases,
    load_index,
)

# Regression floor — locked to the tuned matcher's measured accuracy on this
# 276-query corpus (R@1 82.9%, R@3 94.6%, FP 8.3%). Floors sit a few points
# below the achieved numbers so legitimate corpus growth doesn't false-fail;
# a real matcher regression still trips them. Do not lower without re-tuning.
MIN_RECALL_AT_1 = 0.80
MIN_RECALL_AT_3 = 0.92
MAX_FALSE_POSITIVE_RATE = 0.12


@pytest.fixture(scope="module")
def metrics() -> dict:
    result = compute_suggest_metrics(load_index(), load_cases())
    print("\n" + format_report(result))
    return result


def test_recall_at_1(metrics: dict) -> None:
    assert metrics["recall_at_1"] >= MIN_RECALL_AT_1, (
        f"Recall@1 {metrics['recall_at_1']:.3f} < {MIN_RECALL_AT_1}"
    )


def test_recall_at_3(metrics: dict) -> None:
    assert metrics["recall_at_3"] >= MIN_RECALL_AT_3, (
        f"Recall@3 {metrics['recall_at_3']:.3f} < {MIN_RECALL_AT_3}"
    )


def test_false_positive_rate(metrics: dict) -> None:
    assert metrics["false_positive_rate"] <= MAX_FALSE_POSITIVE_RATE, (
        f"FP-rate {metrics['false_positive_rate']:.3f} > {MAX_FALSE_POSITIVE_RATE}"
    )
