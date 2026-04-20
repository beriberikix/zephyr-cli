"""zephyr-cli: Agent-optimized CLI for Zephyr RTOS.

Entry point for the global `zephyr-cli` command. Workspace-level operations
(build, inspect, emulate, test, flash, debug) are provided by the `west agent`
extension, registered via entry_points["west.commands"].
"""

from __future__ import annotations

import typer

from zephyr_cli.commands.env import app as env_app
from zephyr_cli.commands.version import app as version_app

app = typer.Typer(
    name="zephyr-cli",
    help=(
        "Agent-optimized CLI for Zephyr RTOS.\n\n"
        "Global commands manage the environment, SDK, project scaffolding, "
        "skills, and documentation. Workspace commands (build, inspect, "
        "emulate, test, flash, debug) are available via [bold]west agent[/bold] "
        "once inside a west workspace."
    ),
    rich_markup_mode="rich",
    no_args_is_help=True,
    add_completion=True,
)

app.add_typer(env_app, name="env")
app.add_typer(version_app, name="version")


# ---------------------------------------------------------------------------
# Placeholder sub-commands for future phases
# ---------------------------------------------------------------------------


@app.command("sdk")
def sdk_cmd(
    ctx: typer.Context,
) -> None:
    """[Phase 1] Manage Zephyr SDK installations. (Not yet implemented)"""
    typer.echo(
        '{"status": "not_implemented", "phase": 1, '
        '"hint": "SDK management arrives in Phase 1."}'
    )
    raise typer.Exit(1)


@app.command("create")
def create_cmd(
    ctx: typer.Context,
) -> None:
    """[Phase 1] Scaffold a new Zephyr workspace. (Not yet implemented)"""
    typer.echo(
        '{"status": "not_implemented", "phase": 1, '
        '"hint": "Project scaffolding arrives in Phase 1."}'
    )
    raise typer.Exit(1)


@app.command("skills")
def skills_cmd(
    ctx: typer.Context,
) -> None:
    """[Phase 1] Manage Zephyr agent skills. (Not yet implemented)"""
    typer.echo(
        '{"status": "not_implemented", "phase": 1, '
        '"hint": "Skills management arrives in Phase 1."}'
    )
    raise typer.Exit(1)


@app.command("docs")
def docs_cmd(
    ctx: typer.Context,
) -> None:
    """[Phase 2] Search the Zephyr knowledge base. (Not yet implemented)"""
    typer.echo(
        '{"status": "not_implemented", "phase": 2, '
        '"hint": "Knowledge base search arrives in Phase 2."}'
    )
    raise typer.Exit(1)


@app.command("update")
def update_cmd() -> None:
    """[Phase 1] Self-update zephyr-cli to the latest version. (Not yet implemented)"""
    typer.echo(
        '{"status": "not_implemented", "phase": 1, '
        '"hint": "Self-update arrives in Phase 1."}'
    )
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
