"""zephyr-cli: Agent-optimized CLI for Zephyr RTOS.

Entry point for the global `zephyr-cli` command. Workspace-level operations
(build, inspect, emulate, test, flash, debug) are provided by the `west agent`
extension, registered via entry_points["west.commands"].
"""

from __future__ import annotations

import typer

from zephyr_cli.commands.create import create_cmd
from zephyr_cli.commands.docs import app as docs_app
from zephyr_cli.commands.env import app as env_app
from zephyr_cli.commands.sdk import app as sdk_app
from zephyr_cli.commands.skills import app as skills_app
from zephyr_cli.commands.update import update_cmd
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
app.add_typer(skills_app, name="skills")
app.add_typer(sdk_app, name="sdk")
app.command("create")(create_cmd)
app.add_typer(docs_app, name="docs")
app.command("update")(update_cmd)


if __name__ == "__main__":
    app()
