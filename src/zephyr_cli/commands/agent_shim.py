from __future__ import annotations

import subprocess
import sys
from typing import Annotated

import typer

from zephyr_cli.core.output import emit


def agent_shim_cmd(
    ctx: typer.Context,
    subcommand: Annotated[
        str,
        typer.Argument(help="Agent subcommand (e.g. build, inspect, emulate, test, flash, debug)."),
    ],
    rest: Annotated[
        list[str] | None, typer.Argument(help="Additional arguments to pass to the agent.")
    ] = None,
) -> None:
    """Run a west agent command.

    This is a shim for `west agent <command>` that provides better JSON error
    output if you invoke it outside of a west workspace, rather than raw west errors.
    """
    try:
        from west.util import west_topdir
    except ImportError:
        emit(
            {
                "status": "error",
                "reason": "west_missing",
                "message": "The 'west' tool is not available in the current environment.",
            },
            fmt="json",
        )
        sys.exit(1)

    try:
        topdir = west_topdir(fall_back=False)
    except Exception:
        topdir = None

    if not topdir:
        emit(
            {
                "status": "error",
                "reason": "workspace_unavailable",
                "message": (
                    "The command was run outside of a valid West workspace or "
                    "the workspace manifest does not include zephyr-cli."
                ),
                "remediation": "Run this command from inside a project directory initialized via 'zephyr-cli create' or 'west init'.",
            },
            fmt="json",
        )
        sys.exit(1)

    args = ["west", "agent", subcommand]
    if rest:
        args.extend(rest)

    result = subprocess.run(args)
    sys.exit(result.returncode)
