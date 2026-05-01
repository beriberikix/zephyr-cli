"""zephyr-cli skills — manage Zephyr agent skills."""

from __future__ import annotations

from typing import Annotated

import typer

from zephyr_cli.core import registry as reg
from zephyr_cli.core.config import find_workspace_root, load_config
from zephyr_cli.core.output import emit, emit_error
from zephyr_cli.schemas.skills import (
    SkillInstallResult,
    SkillListResult,
    SkillSuggestResult,
)

app = typer.Typer(
    help="Manage Zephyr agent skills (list, install, show, suggest).",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt(ctx: typer.Context) -> str:
    return ctx.obj.get("format") if ctx.obj else "json"


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@app.command("list")
def skills_list(
    ctx: typer.Context,
    installed_only: Annotated[
        bool, typer.Option("--installed", help="Only show installed skills.")
    ] = False,
    fmt: Annotated[str, typer.Option("--format", "-f", help="Output format: json|human.")] = "json",
) -> None:
    """List available skills from the registry and installed skills."""
    cfg = load_config()
    ws_root = find_workspace_root()

    installed = reg.list_installed(ws_root) if ws_root else []
    available = []

    if not installed_only:
        try:
            index = reg.load_index(cfg)
            available = index.skills
        except Exception as exc:
            emit_error(f"Could not fetch skills registry: {exc}", fmt=fmt)
            raise typer.Exit(1) from exc

    result = SkillListResult(
        status="ok",
        workspace=str(ws_root) if ws_root else None,
        available=available,
        installed=installed,
    )
    emit(result, fmt=fmt)


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------


@app.command("install")
def skills_install(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Skill name to install (e.g. 'build-system').")],
    force: Annotated[
        bool, typer.Option("--force", help="Re-install even if already present.")
    ] = False,
    fmt: Annotated[str, typer.Option("--format", "-f")] = "json",
) -> None:
    """Install a skill into the current workspace."""
    cfg = load_config()
    ws_root = find_workspace_root()
    if ws_root is None:
        emit_error("Not inside a west workspace. Run 'west init' first.", fmt=fmt)
        raise typer.Exit(1)

    # Check if already installed
    if not force:
        installed = reg.list_installed(ws_root)
        if any(s.name == name for s in installed):
            emit(
                SkillInstallResult(
                    status="already_installed",
                    name=name,
                    path=str(ws_root / ".zephyr" / "skills" / name),
                    message=f"Skill '{name}' is already installed. Use --force to reinstall.",
                ),
                fmt=fmt,
            )
            return

    try:
        index = reg.load_index(cfg)
    except Exception as exc:
        emit_error(f"Could not fetch skills registry: {exc}", fmt=fmt)
        raise typer.Exit(1) from exc

    skill = next((s for s in index.skills if s.name == name), None)
    if skill is None:
        emit_error(f"Skill '{name}' not found in registry.", fmt=fmt)
        raise typer.Exit(1)

    try:
        dest, written = reg.install_skill(skill, ws_root)
        emit(
            SkillInstallResult(
                status="installed",
                name=name,
                path=str(dest),
                files_written=written,
            ),
            fmt=fmt,
        )
    except Exception as exc:
        emit_error(f"Failed to install skill '{name}': {exc}", fmt=fmt)
        raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


@app.command("show")
def skills_show(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Skill name to show.")],
    fmt: Annotated[str, typer.Option("--format", "-f")] = "json",
) -> None:
    """Show details for a skill from the registry."""
    cfg = load_config()
    try:
        index = reg.load_index(cfg)
    except Exception as exc:
        emit_error(f"Could not fetch skills registry: {exc}", fmt=fmt)
        raise typer.Exit(1) from exc

    skill = next((s for s in index.skills if s.name == name), None)
    if skill is None:
        emit_error(
            f"Skill '{name}' not found. Run 'zephyr-cli skills list' to see all skills.", fmt=fmt
        )
        raise typer.Exit(1)

    emit({"status": "ok", "skill": skill.model_dump()}, fmt=fmt)


# ---------------------------------------------------------------------------
# suggest
# ---------------------------------------------------------------------------


@app.command("suggest")
def skills_suggest(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Free-text query describing your task.")],
    kconfig: Annotated[
        str | None,
        typer.Option(
            "--kconfig", help="Comma-separated CONFIG_* symbols to match against triggers."
        ),
    ] = None,
    dts: Annotated[
        str | None,
        typer.Option("--dts", "--dts-compatible", help="Comma-separated DTS compatible strings."),
    ] = None,
    fmt: Annotated[str, typer.Option("--format", "-f")] = "json",
) -> None:
    """Suggest skills relevant to your task."""
    cfg = load_config()
    try:
        index = reg.load_index(cfg)
    except Exception as exc:
        emit_error(f"Could not fetch skills registry: {exc}", fmt=fmt)
        raise typer.Exit(1) from exc

    kconfig_symbols = [s.strip() for s in kconfig.split(",")] if kconfig else None
    dts_compatibles = [s.strip() for s in dts.split(",")] if dts else None

    suggestions = reg.suggest_skills(
        index, query, kconfig_symbols=kconfig_symbols, dts_compatibles=dts_compatibles
    )
    emit(
        SkillSuggestResult(status="ok", query=query, suggestions=suggestions),
        fmt=fmt,
    )


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


@app.command("apply")
def skills_apply(
    ctx: typer.Context,
    name: Annotated[
        str, typer.Argument(help="Skill name to apply templates from (e.g. 'connectivity-ble').")
    ],
    target: Annotated[
        str,
        typer.Option(
            "--target", "-t", help="Target directory for templates (relative to workspace)."
        ),
    ] = "src",
    fmt: Annotated[str, typer.Option("--format", "-f")] = "json",
) -> None:
    """Inject templates and assets directly from a skill into your project."""
    cfg = load_config()
    ws_root = find_workspace_root()
    if ws_root is None:
        emit_error("Not inside a west workspace. Run 'west init' first.", fmt=fmt)
        raise typer.Exit(1)

    try:
        index = reg.load_index(cfg)
    except Exception as exc:
        emit_error(f"Could not fetch skills registry: {exc}", fmt=fmt)
        raise typer.Exit(1) from exc

    skill = next((s for s in index.skills if s.name == name), None)
    if skill is None:
        emit_error(f"Skill '{name}' not found in registry.", fmt=fmt)
        raise typer.Exit(1)

    target_path = ws_root / target
    try:
        from zephyr_cli.schemas.skills import SkillApplyResult

        _, applied = reg.apply_skill(skill, ws_root, target_path)
        if not applied:
            emit(
                SkillApplyResult(
                    status="no_templates_found",
                    name=name,
                    target=str(target_path),
                    message=f"Skill '{name}' contains no code templates or assets to apply.",
                ),
                fmt=fmt,
            )
        else:
            emit(
                SkillApplyResult(
                    status="applied",
                    name=name,
                    target=str(target_path),
                    files_applied=applied,
                    message=f"Successfully injected {len(applied)} template(s) into {target}",
                ),
                fmt=fmt,
            )
    except Exception as exc:
        emit_error(f"Failed to apply templates from '{name}': {exc}", fmt=fmt)
        raise typer.Exit(1) from exc
