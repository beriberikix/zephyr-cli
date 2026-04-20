"""zephyr-cli env command."""

from __future__ import annotations

from typing import Annotated

import typer

from zephyr_cli.core.env import collect_env
from zephyr_cli.core.output import emit

app = typer.Typer(help="Print resolved Zephyr environment as structured output.")


@app.callback(invoke_without_command=True)
def env_cmd(
    ctx: typer.Context,
    fmt: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: json or human."),
    ] = "json",
) -> None:
    """Print the fully resolved Zephyr development environment.

    Includes SDK, west workspace, toolchains, installed skills, and all
    Zephyr-related environment variables. Always emits JSON when stdout
    is not a TTY (i.e. when called from an agent or CI pipeline).

    Examples:

      zephyr-cli env

      zephyr-cli env --format human
    """
    result = collect_env()
    emit(result, fmt=fmt)
    raise typer.Exit(0)
