"""zephyr-cli version command."""

from __future__ import annotations

import json
import platform
import sys
from typing import Annotated

import typer

from zephyr_cli import __version__

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

    if fmt == "json" or not sys.stdout.isatty():
        print(json.dumps(payload, indent=2))
    else:
        try:
            from rich.console import Console
            from rich.table import Table

            console = Console()
            table = Table(show_header=False, box=None, padding=(0, 2))
            for k, v in payload.items():
                table.add_row(f"[bold]{k}[/bold]", v)
            console.print(table)
        except ImportError:
            print(json.dumps(payload, indent=2))

    raise typer.Exit(0)
