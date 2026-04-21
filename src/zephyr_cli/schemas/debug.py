"""Pydantic v2 schemas for ``west agent debug`` output."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, field_validator


class DebugResult(BaseModel):
    status: str  # "running" | "success" | "error" | "timeout"
    build_dir: str | None = None
    # Server mode fields
    pid: int | None = None
    gdb_port: int | None = None
    rtt_port: int | None = None
    # Full debug session output (non-server mode)
    output: str | None = None
    error: str | None = None
    duration_seconds: float | None = None

    @field_validator("build_dir")
    @classmethod
    def resolve_build_dir(cls, v: str | None) -> str | None:
        if v is not None:
            return str(Path(v).resolve())
        return v
