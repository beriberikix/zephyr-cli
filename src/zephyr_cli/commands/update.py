"""zephyr-cli update — self-update to the latest version."""

from __future__ import annotations

import subprocess
import sys

import httpx
import typer

from zephyr_cli import __version__
from zephyr_cli.core.output import emit, emit_error

PYPI_URL = "https://pypi.org/pypi/zephyr-cli/json"


def _latest_pypi_version() -> str | None:
    try:
        resp = httpx.get(PYPI_URL, timeout=10)
        resp.raise_for_status()
        return resp.json()["info"]["version"]
    except Exception:
        return None


def update_cmd(
    fmt: str = typer.Option("json", "--format", "-f"),
    check: bool = typer.Option(False, "--check", help="Only check for updates, do not install."),
) -> None:
    """Self-update zephyr-cli to the latest PyPI release."""
    current = __version__
    latest = _latest_pypi_version()

    if latest is None:
        emit_error("Could not determine latest version from PyPI.", fmt=fmt)
        raise typer.Exit(1)

    if current == latest:
        emit(
            {"status": "up_to_date", "version": current},
            fmt=fmt,
        )
        return

    if check:
        emit(
            {"status": "update_available", "current": current, "latest": latest},
            fmt=fmt,
        )
        return

    # Attempt upgrade with uv, fall back to pip
    for cmd in [
        ["uv", "pip", "install", "--upgrade", "zephyr-cli"],
        [sys.executable, "-m", "pip", "install", "--upgrade", "zephyr-cli"],
    ]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                emit(
                    {
                        "status": "updated",
                        "from": current,
                        "to": latest,
                    },
                    fmt=fmt,
                )
                return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    emit_error("Could not find uv or pip to perform the upgrade.", fmt=fmt)
    raise typer.Exit(1)
