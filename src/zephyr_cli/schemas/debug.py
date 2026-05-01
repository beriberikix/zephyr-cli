"""Pydantic v2 schemas for ``west agent debug`` output."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class DebugCapabilities(BaseModel):
    """Capabilities detected from the debug session output."""

    hardware_breakpoints: int | None = None
    software_breakpoints: int | None = None
    monitor_command: bool = False
    rtt: bool = False


class DebugResult(BaseModel):
    status: str  # "running" | "success" | "error" | "timeout"
    board: str | None = None
    build_dir: str | None = None
    runner: str | None = None  # e.g. openocd, jlink, pyocd
    # Server mode fields
    pid: int | None = None
    gdb_port: int | None = None
    rtt_port: int | None = None
    # Full debug session output (non-server mode)
    output: str | None = None
    error: str | None = None
    duration_seconds: float | None = None
    # Extended status fields
    server_started: bool | None = None
    attach_status: str | None = None  # "connected" | "refused" | "timeout"
    timeout_reason: str | None = None
    capabilities: DebugCapabilities = Field(default_factory=DebugCapabilities)
    suppressed_warnings: list[str] = Field(default_factory=list)

    @field_validator("build_dir")
    @classmethod
    def resolve_build_dir(cls, v: str | None) -> str | None:
        if v is not None:
            return str(Path(v).resolve())
        return v


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------

_HW_BP_RE = re.compile(r"(?:hardware breakpoints?|hw breakpoints?)\D*(\d+)", re.IGNORECASE)
_SW_BP_RE = re.compile(r"(?:software breakpoints?|sw breakpoints?)\D*(\d+)", re.IGNORECASE)
_MONITOR_RE = re.compile(r"monitor command|mon ", re.IGNORECASE)
_RTT_RE = re.compile(r"SEGGER.*RTT|RTT.*channel", re.IGNORECASE)
_CONNECTED_RE = re.compile(r"Remote debugging using|Connected to|Halting target", re.IGNORECASE)
_REFUSED_RE = re.compile(r"Connection refused|Could not connect", re.IGNORECASE)
_TIMEOUT_RE = re.compile(r"Timed? ?out|timeout", re.IGNORECASE)


def parse_debug_output(output: str) -> tuple[str | None, DebugCapabilities]:
    """Parse GDB / debug server output for attach status and capabilities.

    Returns (attach_status, capabilities).
    """
    caps = DebugCapabilities()
    attach_status: str | None = None

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = _HW_BP_RE.search(line)
        if m:
            caps.hardware_breakpoints = int(m.group(1))

        m = _SW_BP_RE.search(line)
        if m:
            caps.software_breakpoints = int(m.group(1))

        if _MONITOR_RE.search(line):
            caps.monitor_command = True

        if _RTT_RE.search(line):
            caps.rtt = True

        if attach_status is None:
            if _CONNECTED_RE.search(line):
                attach_status = "connected"
            elif _REFUSED_RE.search(line):
                attach_status = "refused"
            elif _TIMEOUT_RE.search(line):
                attach_status = "timeout"

    return attach_status, caps
