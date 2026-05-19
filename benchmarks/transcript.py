"""Parse OpenCode JSONL transcripts into token + process metrics.

The benchmark harness saves the agent's `--format json` output verbatim to
``stdout.txt``.  That stream is JSON Lines: one event per line, each a dict with
a top-level ``type`` and a ``part`` payload.  The events we care about:

* ``step_finish`` — ``part.tokens = {total, input, output, reasoning,
  cache:{write, read}}``.  The per-step ``total`` is the token volume of that
  single LLM call (``input + output + reasoning + cache.write + cache.read``);
  it is **not** cumulative, so the run total is the sum across steps.
* ``tool_use`` — ``part.tool`` (``bash``/``write``/``read``/``edit``/``skill``
  /``todowrite``), ``part.state.status``, ``part.state.input.command`` (for
  ``bash``), ``part.state.output``.
* ``text`` — ``part.text`` (assistant prose).

This module is intentionally pure: ``parse_transcript`` takes a string and
returns a dataclass, with no harness or filesystem coupling, so it is trivial
to unit-test against synthetic fixtures.
"""

from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# A bash command "uses zephyr-cli" if it invokes the global CLI or the
# `west agent` extension.
_ZEPHYR_CLI_RE = re.compile(r"\bzephyr-cli\b|\bwest\s+agent\b")
# A bash command counts as a build attempt.
_BUILD_RE = re.compile(r"\bwest\s+build\b|\bcmake\s+--build\b")
# Fallback signal that a tool result reported a compile/build failure even when
# the tool's own status field says "completed".
_ERROR_OUTPUT_RE = re.compile(r"\berror:", re.IGNORECASE)


@dataclass
class TranscriptMetrics:
    """Aggregated token and process metrics for one benchmark run."""

    # ── Token aggregates (summed over every `step_finish` event) ──────────
    tokens_total: int = 0  # sum of per-step `total` — processed-token volume
    tokens_input: int = 0
    tokens_output: int = 0
    tokens_reasoning: int = 0
    tokens_cache_read: int = 0
    tokens_cache_write: int = 0
    tokens_fresh: int = 0  # input + output + reasoning + cache_write
    tokens_in_retry_loops_est: int = 0  # estimate — tokens spent after a failed build

    # ── Process metrics ───────────────────────────────────────────────────
    step_count: int = 0
    tool_calls_total: int = 0
    tool_calls_failed: int = 0
    tool_calls_by_name: dict[str, int] = field(default_factory=dict)
    skill_invocations: int = 0
    zephyr_cli_invocations: int = 0
    build_attempts: int = 0
    build_failures: int = 0
    build_retry_count: int = 0
    tool_output_chars: int = 0  # raw chars of tool results — /4 ≈ tokens

    # ── Parser health ─────────────────────────────────────────────────────
    event_count: int = 0
    parse_errors: int = 0

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def _command_of(part: dict) -> str | None:
    """Extract the bash command string from a tool_use event, if any."""
    state = part.get("state")
    if not isinstance(state, dict):
        return None
    inp = state.get("input")
    if not isinstance(inp, dict):
        return None
    cmd = inp.get("command")
    return cmd if isinstance(cmd, str) else None


def parse_transcript(text: str) -> TranscriptMetrics:
    """Parse a JSONL transcript string into :class:`TranscriptMetrics`."""
    m = TranscriptMetrics()

    # State for retry-loop attribution: True once a build has failed and no
    # build has succeeded since.  step_finish token totals seen while this is
    # active are attributed to retry waste.
    retry_active = False
    last_build_failed = False

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            m.parse_errors += 1
            continue
        if not isinstance(obj, dict):
            m.parse_errors += 1
            continue

        m.event_count += 1
        etype = obj.get("type")
        part = obj.get("part")
        if not isinstance(part, dict):
            part = {}

        if etype == "step_finish":
            m.step_count += 1
            tokens = part.get("tokens")
            if isinstance(tokens, dict):
                cache = tokens.get("cache")
                cache = cache if isinstance(cache, dict) else {}
                step_input = int(tokens.get("input", 0) or 0)
                step_output = int(tokens.get("output", 0) or 0)
                step_reasoning = int(tokens.get("reasoning", 0) or 0)
                step_cache_read = int(cache.get("read", 0) or 0)
                step_cache_write = int(cache.get("write", 0) or 0)
                step_total = int(tokens.get("total", 0) or 0) or (
                    step_input + step_output + step_reasoning + step_cache_read + step_cache_write
                )
                m.tokens_input += step_input
                m.tokens_output += step_output
                m.tokens_reasoning += step_reasoning
                m.tokens_cache_read += step_cache_read
                m.tokens_cache_write += step_cache_write
                m.tokens_total += step_total
                m.tokens_fresh += step_input + step_output + step_reasoning + step_cache_write
                if retry_active:
                    m.tokens_in_retry_loops_est += step_total

        elif etype == "tool_use":
            m.tool_calls_total += 1
            name = part.get("tool") or "unknown"
            m.tool_calls_by_name[name] = m.tool_calls_by_name.get(name, 0) + 1

            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            status = state.get("status")
            failed = status == "error"
            if failed:
                m.tool_calls_failed += 1
            output = state.get("output")
            if isinstance(output, str):
                m.tool_output_chars += len(output)

            if name == "skill":
                m.skill_invocations += 1

            command = _command_of(part)
            if command:
                if _ZEPHYR_CLI_RE.search(command):
                    m.zephyr_cli_invocations += 1
                if _BUILD_RE.search(command):
                    m.build_attempts += 1
                    build_failed = failed or (
                        isinstance(output, str) and _ERROR_OUTPUT_RE.search(output) is not None
                    )
                    if last_build_failed:
                        m.build_retry_count += 1
                    if build_failed:
                        m.build_failures += 1
                        retry_active = True
                    else:
                        retry_active = False
                    last_build_failed = build_failed

    return m


def parse_transcript_file(path: str | Path) -> TranscriptMetrics:
    """Parse a transcript file. Missing files yield empty metrics."""
    p = Path(path)
    if not p.exists():
        return TranscriptMetrics()
    return parse_transcript(p.read_text(encoding="utf-8", errors="replace"))
