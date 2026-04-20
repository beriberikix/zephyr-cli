"""zephyr-cli sdk — manage Zephyr SDK installations."""

from __future__ import annotations

from typing import Annotated

import typer

from zephyr_cli.core import sdk as sdk_core
from zephyr_cli.core.config import load_config
from zephyr_cli.core.output import emit, emit_error
from zephyr_cli.schemas.sdk import (
    SdkInstallResult,
    SdkListResult,
    SdkSelectResult,
)

app = typer.Typer(
    help="Manage Zephyr SDK installations (list, install, select).",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@app.command("list")
def sdk_list(
    ctx: typer.Context,
    available: Annotated[
        bool,
        typer.Option("--available", help="Also fetch available versions from GitHub."),
    ] = False,
    fmt: Annotated[str, typer.Option("--format", "-f")] = "json",
) -> None:
    """List installed Zephyr SDK versions."""
    cfg = load_config()
    installed = sdk_core.list_installed(cfg)
    selected = next((s.version for s in installed if s.selected), None)

    avail: list = []
    if available:
        try:
            avail = sdk_core.fetch_available()
        except Exception as exc:
            emit_error(f"Could not fetch available SDKs: {exc}", fmt=fmt)
            raise typer.Exit(1) from exc

    emit(
        SdkListResult(status="ok", installed=installed, available=avail, selected=selected),
        fmt=fmt,
    )


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------


@app.command("install")
def sdk_install(
    ctx: typer.Context,
    version: Annotated[str, typer.Argument(help="SDK version to install, e.g. '0.16.8'.")],
    minimal: Annotated[
        bool, typer.Option("--minimal", help="Download minimal SDK (no host tools).")
    ] = False,
    fmt: Annotated[str, typer.Option("--format", "-f")] = "json",
) -> None:
    """Download and install a Zephyr SDK version."""
    cfg = load_config()
    try:
        sdk = sdk_core.install_sdk(cfg, version, minimal=minimal)
        emit(
            SdkInstallResult(
                status="installed",
                version=sdk.version,
                path=sdk.path,
                message=f"SDK {sdk.version} installed to {sdk.path}",
            ),
            fmt=fmt,
        )
    except ValueError as exc:
        emit_error(str(exc), fmt=fmt)
        raise typer.Exit(1) from exc
    except Exception as exc:
        emit_error(f"SDK installation failed: {exc}", fmt=fmt)
        raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# select
# ---------------------------------------------------------------------------


@app.command("select")
def sdk_select(
    ctx: typer.Context,
    version: Annotated[str, typer.Argument(help="SDK version to activate.")],
    fmt: Annotated[str, typer.Option("--format", "-f")] = "json",
) -> None:
    """Select an installed SDK version as the active SDK."""
    cfg = load_config()
    try:
        sdk = sdk_core.select_sdk(cfg, version)
        emit(
            SdkSelectResult(
                status="selected",
                version=sdk.version,
                path=sdk.path,
                hint=f"Set ZEPHYR_SDK_INSTALL_DIR={sdk.path} or run 'west build' from this environment.",
            ),
            fmt=fmt,
        )
    except FileNotFoundError as exc:
        emit_error(str(exc), fmt=fmt)
        raise typer.Exit(1) from exc
    except Exception as exc:
        emit_error(f"SDK select failed: {exc}", fmt=fmt)
        raise typer.Exit(1) from exc
