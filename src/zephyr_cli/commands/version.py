"""zephyr-cli version command."""

from __future__ import annotations

import platform
import sys
from typing import Annotated

import typer

from zephyr_cli import __version__
from zephyr_cli.core.output import emit

app = typer.Typer(help="Print zephyr-cli version information.")


@app.callback(invoke_without_command=True)
def version_cmd(
    ctx: typer.Context,
    fmt: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: json or human."),
    ] = "json",
) -> None:
    """Print version information for zephyr-cli.

    Examples:

      zephyr-cli version

      zephyr-cli version --format human
    """
    payload = {
        "zephyr_cli": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }

    emit(payload, fmt=fmt)

    raise typer.Exit(0)
