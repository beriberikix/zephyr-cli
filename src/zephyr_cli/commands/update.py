"""zephyr-cli update — self-update to the latest version."""

from __future__ import annotations

import subprocess
import sys

import httpx
import typer

from zephyr_cli import __version__
from zephyr_cli.core.output import emit, emit_error

PYPI_URL = "https://pypi.org/pypi/zephyr-cli/json"


def _latest_pypi_version() -> tuple[str | None, str | None, str | None]:
    """Fetch latest version from PyPI.

    Returns (version, error_reason, next_action).
    """
    try:
        resp = httpx.get(PYPI_URL, timeout=10)
        resp.raise_for_status()
        return resp.json()["info"]["version"], None, None
    except httpx.ConnectError:
        return None, "network_unreachable", "Check your internet connection and try again."
    except httpx.TimeoutException:
        return None, "timeout", "PyPI did not respond in time. Try again later."
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return (
                None,
                "package_not_published",
                "zephyr-cli is not published on PyPI yet. Use the local checkout or install from source.",
            )
        return (
            None,
            f"pypi_http_{exc.response.status_code}",
            f"PyPI returned HTTP {exc.response.status_code}. Try again later.",
        )
    except (KeyError, ValueError):
        return None, "malformed_response", "PyPI returned an unexpected payload."
    except Exception:
        return None, "unknown", "An unexpected error occurred querying PyPI."


def update_cmd(
    fmt: str = typer.Option("json", "--format", "-f"),
    check: bool = typer.Option(False, "--check", help="Only check for updates, do not install."),
) -> None:
    """Self-update zephyr-cli to the latest PyPI release."""
    current = __version__
    latest, error_reason, next_action = _latest_pypi_version()

    if latest is None:
        emit(
            {
                "status": "error",
                "message": "Could not determine latest version from PyPI.",
                "reason": error_reason,
                "next_action": next_action,
            },
            fmt=fmt,
        )
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
