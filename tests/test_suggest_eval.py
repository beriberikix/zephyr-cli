"""Deterministic regression harness for `zephyr-cli skills suggest`.

Runs the matcher over a committed labeled query corpus and asserts accuracy
thresholds. This is the proof that skill selection works — it replaces the
unreliable LLM auto-trigger measurement.

Run `pytest tests/test_suggest_eval.py -s -q` to see the per-skill table.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

from zephyr_cli.core.registry import suggest_skills
from zephyr_cli.schemas.skills import SkillsIndex

DATA = Path(__file__).parent / "data" / "suggest_eval"
FIXTURE = DATA / "index.fixture.json"
QUERIES = DATA / "queries.jsonl"

# Regression floor — locked to the tuned matcher's measured accuracy on this
# 276-query corpus (R@1 82.9%, R@3 94.6%, FP 8.3%). Floors sit a few points
# below the achieved numbers so legitimate corpus growth doesn't false-fail;
# a real matcher regression still trips them. Do not lower without re-tuning.
MIN_RECALL_AT_1 = 0.80
MIN_RECALL_AT_3 = 0.92
MAX_FALSE_POSITIVE_RATE = 0.12


def _load_cases() -> list[dict]:
    return [
        json.loads(line)
        for line in QUERIES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.fixture(scope="module")
def metrics() -> dict:
    index = SkillsIndex.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    cases = _load_cases()

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

    result = {
        "positives": pos,
        "negatives": neg,
        "recall_at_1": hit1 / pos if pos else 0.0,
        "recall_at_3": hit3 / pos if pos else 0.0,
        "false_positive_rate": fp / neg if neg else 0.0,
        "mrr": rr_sum / pos if pos else 0.0,
        "per_skill": per_skill,
        "misses": misses,
    }
    _print_report(result)
    return result


def _print_report(m: dict) -> None:
    print("\n=== zephyr-cli `skills suggest` — eval ===")
    print(f"corpus: {m['positives']} positives, {m['negatives']} negatives")
    print(
        f"Recall@1={m['recall_at_1'] * 100:.1f}%  "
        f"Recall@3={m['recall_at_3'] * 100:.1f}%  "
        f"MRR={m['mrr']:.3f}  "
        f"FP-rate={m['false_positive_rate'] * 100:.1f}%"
    )
    print(f"{'skill':26}{'n':>4}{'R@1':>8}{'R@3':>8}")
    for name in sorted(m["per_skill"]):
        s = m["per_skill"][name]
        print(f"{name:26}{s['n']:>4}{s['hit1'] / s['n'] * 100:>7.0f}%{s['hit3'] / s['n'] * 100:>7.0f}%")
    if m["misses"]:
        print(f"-- {len(m['misses'])} miss/FP --")
        for kind, query, got in m["misses"]:
            print(f"  [{kind}] got={got!r}  <-  {query[:72]}")


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
