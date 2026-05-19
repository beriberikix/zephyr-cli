"""Unit tests for benchmarks.transcript — the OpenCode JSONL parser.

Run from the repository root:  python -m pytest benchmarks/tests/
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.transcript import parse_transcript, parse_transcript_file

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_clean_run_token_aggregates() -> None:
    m = parse_transcript_file(FIXTURES / "clean.jsonl")
    assert m.step_count == 2
    assert m.tokens_total == 3100  # 1100 + 2000
    assert m.tokens_input == 150
    assert m.tokens_output == 350
    assert m.tokens_cache_write == 800
    assert m.tokens_cache_read == 1800
    assert m.tokens_fresh == 1300  # 150 + 350 + 0 + 800
    assert m.parse_errors == 0


def test_clean_run_process_metrics() -> None:
    m = parse_transcript_file(FIXTURES / "clean.jsonl")
    assert m.tool_calls_total == 3
    assert m.tool_calls_by_name == {"bash": 1, "write": 1, "skill": 1}
    assert m.skill_invocations == 1
    assert m.zephyr_cli_invocations == 1  # bash ran "zephyr-cli env"
    assert m.build_attempts == 0
    assert m.tokens_in_retry_loops_est == 0


def test_failed_build_then_retry() -> None:
    m = parse_transcript_file(FIXTURES / "retry.jsonl")
    assert m.build_attempts == 2
    assert m.build_failures == 1
    assert m.build_retry_count == 1
    # The two steps between the failed build and the successful retry are waste.
    assert m.tokens_in_retry_loops_est == 1100  # 500 + 600
    assert m.tokens_total == 1800  # 500 + 600 + 700


def test_malformed_lines_are_counted_not_fatal() -> None:
    m = parse_transcript_file(FIXTURES / "malformed.jsonl")
    # One non-JSON line + one JSON line that is a list (not a dict).
    assert m.parse_errors == 2
    assert m.event_count == 3  # 2 step_finish + 1 tool_use
    assert m.step_count == 2
    assert m.tokens_total == 300  # only the first step had tokens
    assert m.tool_calls_total == 1


def test_empty_and_missing_inputs() -> None:
    assert parse_transcript("").step_count == 0
    assert parse_transcript("   \n\n  ").event_count == 0
    assert parse_transcript_file(FIXTURES / "does-not-exist.jsonl").tokens_total == 0


def test_to_dict_is_json_serializable() -> None:
    import json

    m = parse_transcript_file(FIXTURES / "clean.jsonl")
    payload = json.dumps(m.to_dict())
    assert "tokens_total" in payload


def test_real_transcript_if_available() -> None:
    """Parse a real OpenCode transcript from the local results tree, if present."""
    results = REPO_ROOT / "benchmarks" / "results"
    samples = list(results.rglob("stdout.txt")) if results.is_dir() else []
    if not samples:
        pytest.skip("no local benchmark results to sample")
    m = parse_transcript_file(samples[0])
    assert m.event_count > 0
    assert m.tokens_total > 0
    assert m.step_count > 0
