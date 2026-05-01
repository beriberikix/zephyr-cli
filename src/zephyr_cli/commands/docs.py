"""zephyr-cli docs — manage Zephyr documentation cache."""

from __future__ import annotations

from typing import Annotated

import typer

from zephyr_cli.core import docs as docs_core
from zephyr_cli.core.config import load_config
from zephyr_cli.core.output import emit, emit_error
from zephyr_cli.schemas.docs import DocsListResult, DocsRefreshResult

app = typer.Typer(
    help="Manage cached Zephyr documentation (list, refresh).",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@app.command("list")
def docs_list(
    ctx: typer.Context,
    fmt: Annotated[str, typer.Option("--format", "-f")] = "json",
) -> None:
    """List cached docs packages and available releases."""
    cfg = load_config()
    from pathlib import Path

    cached = docs_core.list_cached(cfg)
    available: list = []
    try:
        available = docs_core.fetch_releases()
    except Exception as exc:
        # Non-fatal: report what we know locally
        emit_error(f"Could not fetch docs releases: {exc}", fmt=fmt)

    emit(
        DocsListResult(
            status="ok",
            cached=cached,
            available=available,
            cache_dir=str(Path(cfg.data_dir) / "docs"),
        ),
        fmt=fmt,
    )


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------


@app.command("refresh")
def docs_refresh(
    ctx: typer.Context,
    version: Annotated[
        str | None,
        typer.Option(
            "--version", "-v", help="Specific docs version/tag to download. Defaults to latest."
        ),
    ] = None,
    fmt: Annotated[str, typer.Option("--format", "-f")] = "json",
) -> None:
    """Download (or update) the Zephyr documentation cache."""
    cfg = load_config()
    try:
        ver, path = docs_core.refresh(cfg, version=version)
        emit(
            DocsRefreshResult(
                status="ok",
                version=ver,
                path=str(path),
                message=f"Docs {ver} cached at {path}",
            ),
            fmt=fmt,
        )
    except RuntimeError as exc:
        emit_error(str(exc), fmt=fmt)
        raise typer.Exit(1) from exc
    except ValueError as exc:
        emit_error(str(exc), fmt=fmt)
        raise typer.Exit(1) from exc
    except Exception as exc:
        emit_error(f"Docs refresh failed: {exc}", fmt=fmt)
        raise typer.Exit(1) from exc
