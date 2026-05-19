"""Benchmark scoring logic.

Weights and computation for the six evaluation dimensions.
"""

from __future__ import annotations

WEIGHTS = {
    "compilability": 0.20,
    "correctness": 0.25,
    "best_practices": 0.15,
    "api_freshness": 0.10,
    "completeness": 0.15,
    "config_quality": 0.15,
}


def score_compilability(build_ok: bool, warning_count: int) -> float:
    """1.0 = clean build, 0.8 = warnings only, 0.0 = build failure."""
    if not build_ok:
        return 0.0
    return 0.8 if warning_count > 0 else 1.0


def score_correctness(
    runtime_matched: int,
    runtime_total: int,
    has_runtime_check: bool,
    build_ok: bool,
) -> float:
    """Runtime output matches expected patterns. N/A → full marks if it builds."""
    if not has_runtime_check:
        return 1.0 if build_ok else 0.0
    if runtime_total == 0:
        return 1.0 if build_ok else 0.0
    return runtime_matched / runtime_total


def score_best_practices(passed: int, total: int) -> float:
    if total == 0:
        return 1.0
    return passed / total


def score_api_freshness(deprecated_hits: int) -> float:
    """1.0 if no deprecated APIs, deduct 0.25 per hit, floor at 0."""
    return max(0.0, 1.0 - 0.25 * deprecated_hits)


def score_completeness(files_present: int, files_expected: int) -> float:
    if files_expected == 0:
        return 1.0
    return files_present / files_expected


def score_config_quality(kconfig_present: int, kconfig_expected: int) -> float:
    """Ratio of expected Kconfig symbols found in prj.conf."""
    if kconfig_expected == 0:
        return 1.0
    return kconfig_present / kconfig_expected


def compute_weighted(scores: dict[str, float]) -> float:
    """Compute the weighted total from individual dimension scores."""
    total = 0.0
    for dim, weight in WEIGHTS.items():
        total += weight * scores.get(dim, 0.0)
    return round(total, 4)
