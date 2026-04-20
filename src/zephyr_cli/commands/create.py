"""zephyr-cli create — scaffold a new Zephyr project."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from zephyr_cli.core import create as create_core
from zephyr_cli.core.output import emit, emit_error
from zephyr_cli.schemas.create import CreateResult


def create_cmd(
    name: Annotated[str, typer.Argument(help="Project name (also used as directory name).")],
    topology: Annotated[
        str,
        typer.Option(
            "--topology",
            "-t",
            help=(
                "Project topology: "
                "T1=standalone app, "
                "T2=app+MCUboot sysbuild, "
                "T3=multi-image sysbuild."
            ),
        ),
    ] = "T1",
    board: Annotated[
        str | None,
        typer.Option("--board", "-b", help="Target board (used in generated next-steps)."),
    ] = None,
    output_dir: Annotated[
        str | None,
        typer.Option("--output-dir", "-o", help="Parent directory for the project (default: cwd)."),
    ] = None,
    fmt: Annotated[str, typer.Option("--format", "-f")] = "json",
) -> None:
    """Scaffold a new Zephyr application project (T1/T2/T3 topologies)."""
    parent = Path(output_dir).resolve() if output_dir else Path.cwd()

    try:
        app_path, files = create_core.create_project(name, topology, parent)
        steps = create_core.next_steps(topology, name, board)
        emit(
            CreateResult(
                status="created",
                name=name,
                topology=topology.upper(),
                app_path=str(app_path),
                files=files,
                next_steps=steps,
            ),
            fmt=fmt,
        )
    except FileExistsError as exc:
        emit_error(str(exc), fmt=fmt)
        raise typer.Exit(1) from exc
    except ValueError as exc:
        emit_error(str(exc), fmt=fmt)
        raise typer.Exit(1) from exc
    except Exception as exc:
        emit_error(f"Project creation failed: {exc}", fmt=fmt)
        raise typer.Exit(1) from exc
