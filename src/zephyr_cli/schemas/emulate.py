"""Pydantic v2 schemas for emulate command output."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, field_validator


class EmulateStatus(StrEnum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    ERROR = "error"


class EmulateBackendName(StrEnum):
    QEMU = "qemu"
    NATIVE_SIM = "native_sim"
    DOCKER = "docker"
    MULTIPASS = "multipass"
    REMOTE = "remote"


class EmulateResult(BaseModel):
    status: EmulateStatus
    backend: EmulateBackendName | None = None
    board: str | None = None
    build_dir: str | None = None
    duration_seconds: float | None = None
    exit_code: int | None = None
    # Captured output from the emulator's stdio
    output: str | None = None
    # Human-readable error description (populated on error/timeout)
    error: str | None = None

    @field_validator("build_dir")
    @classmethod
    def resolve_build_dir(cls, v: str | None) -> str | None:
        if v is not None:
            return str(Path(v).resolve())
        return v
