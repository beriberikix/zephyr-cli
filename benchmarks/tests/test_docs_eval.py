"""Unit tests for the pure helpers in benchmarks.docs_eval.

Run from the repository root:  python -m pytest benchmarks/tests/
"""

from __future__ import annotations

from benchmarks.docs_eval import extract_answer, grade, load_questions


def test_grade_passes_when_all_expected_present() -> None:
    q = {"expect_substrings": ["native_sim"], "forbid_substrings": ["native_posix"]}
    assert grade("Use the native_sim board target.", q) is True


def test_grade_fails_on_missing_expected() -> None:
    q = {"expect_substrings": ["native_sim"], "forbid_substrings": []}
    assert grade("Use some other board.", q) is False


def test_grade_fails_on_forbidden_substring() -> None:
    q = {"expect_substrings": ["native_sim"], "forbid_substrings": ["native_posix"]}
    assert grade("Use native_sim, which replaced native_posix.", q) is False


def test_grade_any_of_group() -> None:
    q = {"expect_substrings": [["DEVICE_DT_GET", "DEVICE_DT_GET_ONE"]], "forbid_substrings": []}
    assert grade("Call DEVICE_DT_GET_ONE() instead.", q) is True
    assert grade("Call something_else() instead.", q) is False


def test_grade_is_case_insensitive() -> None:
    q = {"expect_substrings": ["ZTEST_SUITE"], "forbid_substrings": []}
    assert grade("define it with ztest_suite()", q) is True


def test_extract_answer_joins_text_events() -> None:
    stdout = (
        '{"type": "step_start", "part": {}}\n'
        '{"type": "text", "part": {"text": "First part."}}\n'
        '{"type": "tool_use", "part": {"tool": "read"}}\n'
        '{"type": "text", "part": {"text": "Second part."}}\n'
    )
    assert extract_answer(stdout) == "First part.\nSecond part."


def test_extract_answer_falls_back_to_raw_stdout() -> None:
    assert extract_answer("not json output") == "not json output"


def test_question_corpus_is_well_formed() -> None:
    questions = load_questions()
    assert len(questions) >= 10
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids)), "question ids must be unique"
    for q in questions:
        assert q["question"]
        assert q["expect_substrings"]
        assert "zephyr_version" in q
