"""Pydantic v2 schemas for ``west agent flash`` output."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class FlashResult(BaseModel):
    status: str  # "success" | "error"
    board: str | None = None
    build_dir: str | None = None
    runner: str | None = None  # e.g. openocd, jlink, pyocd
    duration_seconds: float | None = None
    output: str | None = None
    error: str | None = None
    suppressed_warnings: list[str] = Field(default_factory=list)

    @field_validator("build_dir")
    @classmethod
    def resolve_build_dir(cls, v: str | None) -> str | None:
        if v is not None:
            return str(Path(v).resolve())
        return v
