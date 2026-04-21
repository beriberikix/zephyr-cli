"""Pydantic v2 schemas for ``west agent test`` (Twister) output."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class TestCase(BaseModel):
    identifier: str
    status: str  # passed / failed / skipped / error / blocked
    duration: float | None = None
    log: str | None = None


class TestSuite(BaseModel):
    name: str
    platform: str | None = None
    arch: str | None = None
    status: str | None = None
    reason: str | None = None
    duration: float | None = None
    cases: list[TestCase] = Field(default_factory=list)


class TestSummary(BaseModel):
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    error: int = 0


class TestResult(BaseModel):
    # "passed" if all suites passed, "failed" if any failed, "error" on
    # Twister invocation failure.
    status: str
    summary: TestSummary = Field(default_factory=TestSummary)
    duration_seconds: float | None = None
    output_dir: str | None = None
    suites: list[TestSuite] = Field(default_factory=list)
    # Full Twister stderr/stdout for agents that want to parse themselves
    raw_output: str | None = None

    @field_validator("output_dir")
    @classmethod
    def resolve_output_dir(cls, v: str | None) -> str | None:
        if v is not None:
            return str(Path(v).resolve())
        return v


# ---------------------------------------------------------------------------
# Twister JSON parser
# ---------------------------------------------------------------------------


def parse_twister_json(data: dict) -> tuple[TestSummary, list[TestSuite]]:
    """Convert a ``twister.json`` dict into (summary, suites)."""
    suites: list[TestSuite] = []
    summary = TestSummary()

    for ts in data.get("testsuites", []):
        cases: list[TestCase] = []
        for tc in ts.get("testcases", []):
            cases.append(
                TestCase(
                    identifier=tc.get("identifier", ""),
                    status=tc.get("status", "unknown"),
                    duration=tc.get("execution_time"),
                    log=tc.get("log") or None,
                )
            )
            status = tc.get("status", "unknown")
            if status == "passed":
                summary.passed += 1
            elif status == "failed":
                summary.failed += 1
            elif status in ("skipped", "filtered"):
                summary.skipped += 1
            else:
                summary.error += 1
            summary.total += 1

        suites.append(
            TestSuite(
                name=ts.get("name", ""),
                platform=ts.get("platform"),
                arch=ts.get("arch"),
                status=ts.get("status"),
                reason=ts.get("reason"),
                duration=ts.get("execution_time"),
                cases=cases,
            )
        )

    return summary, suites
