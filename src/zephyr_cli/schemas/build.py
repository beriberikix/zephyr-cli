"""Pydantic v2 schemas for build command output."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class BuildStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"


class BuildWarning(BaseModel):
    file: str
    line: int | None = None
    column: int | None = None
    message: str


class BuildError(BaseModel):
    file: str | None = None
    line: int | None = None
    column: int | None = None
    message: str
    # Raw compiler error type if parseable (e.g. "error", "fatal error")
    error_type: str | None = None
    # Actionable remediation hint for agents / users
    remediation: str | None = None


class BuildBinary(BaseModel):
    elf: str | None = None
    hex: str | None = None
    bin: str | None = None
    exe: str | None = None  # native_sim produces zephyr.exe


class BuildResult(BaseModel):
    status: BuildStatus
    board: str | None = None
    build_dir: str | None = None
    duration_seconds: float | None = None
    binary: BuildBinary = Field(default_factory=BuildBinary)
    errors: list[BuildError] = Field(default_factory=list)
    warnings: list[BuildWarning] = Field(default_factory=list)
    # Full raw stderr for agents that want to parse themselves
    raw_stderr: str | None = None

    @field_validator("build_dir")
    @classmethod
    def resolve_build_dir(cls, v: str | None) -> str | None:
        if v is not None:
            return str(Path(v).resolve())
        return v


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------

# GCC/Clang: path/to/file.c:42:10: error: message
_COMPILER_DIAG_RE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+)(?::(?P<col>\d+))?:\s*(?P<kind>warning|error|fatal error|note):\s*(?P<msg>.+)$"
)

# CMake error lines
_CMAKE_ERROR_RE = re.compile(r"^CMake Error.*?:\s*(?P<msg>.+)$")

# Python version too old (CMake find_package / Zephyr check)
_PYTHON_VERSION_RE = re.compile(
    r"(?:Could NOT find Python3.*Required is at least version "
    r"|Found unsuitable version \".*\", minimum required is \""
    r"|Python version .* is less than minimum required version )"
    r"(?P<ver>[\d.]+)",
    re.IGNORECASE,
)

# Missing Python package / west module dependency
_MISSING_PKG_RE = re.compile(
    r"(?:No module named '(?P<mod>[^']+)'"
    r"|ModuleNotFoundError: No module named '(?P<mod2>[^']+)'"
    r"|ImportError: (?P<imp>.+))",
)


def parse_build_output(
    stderr: str,
    build_dir: str | None = None,
) -> tuple[list[BuildError], list[BuildWarning]]:
    """Parse compiler and CMake output into structured errors and warnings.

    Returns (errors, warnings). Raw stderr is preserved separately on
    BuildResult so agents can always fall back to it.
    """
    errors: list[BuildError] = []
    warnings: list[BuildWarning] = []

    for raw_line in stderr.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = _COMPILER_DIAG_RE.match(line)
        if m:
            file_path = m.group("file")
            lineno = int(m.group("line"))
            col = int(m.group("col")) if m.group("col") else None
            kind = m.group("kind")
            msg = m.group("msg")

            if kind in ("error", "fatal error"):
                errors.append(
                    BuildError(
                        file=file_path,
                        line=lineno,
                        column=col,
                        message=msg,
                        error_type=kind,
                    )
                )
            elif kind == "warning":
                warnings.append(
                    BuildWarning(file=file_path, line=lineno, column=col, message=msg)
                )
            continue

        cm = _CMAKE_ERROR_RE.match(line)
        if cm:
            errors.append(BuildError(message=cm.group("msg"), error_type="cmake"))
            continue

        pm = _PYTHON_VERSION_RE.search(line)
        if pm:
            required = pm.group("ver")
            errors.append(
                BuildError(
                    message=f"Python >= {required} is required by the build system.",
                    error_type="python_version",
                    remediation=f"Install Python >= {required} or activate a compatible virtualenv.",
                )
            )
            continue

        mm = _MISSING_PKG_RE.search(line)
        if mm:
            mod = mm.group("mod") or mm.group("mod2") or mm.group("imp")
            errors.append(
                BuildError(
                    message=f"Missing Python package: {mod}",
                    error_type="missing_package",
                    remediation=f"pip install {mod}",
                )
            )
            continue

    return errors, warnings


def locate_binaries(build_dir: str) -> BuildBinary:
    """Probe a build directory for known output binary paths."""
    bd = Path(build_dir)
    zephyr_dir = bd / "zephyr"

    def maybe(p: Path) -> str | None:
        return str(p) if p.exists() else None

    return BuildBinary(
        elf=maybe(zephyr_dir / "zephyr.elf"),
        hex=maybe(zephyr_dir / "zephyr.hex"),
        bin=maybe(zephyr_dir / "zephyr.bin"),
        exe=maybe(zephyr_dir / "zephyr.exe"),
    )
