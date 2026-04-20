"""Output formatting helpers.

All commands support --format json (default in non-TTY) and --format human.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from pydantic import BaseModel


def is_tty() -> bool:
    return sys.stdout.isatty()


def emit(data: BaseModel | dict, fmt: str | None = None, indent: int = 2) -> None:
    """Emit structured output. fmt=None auto-detects based on TTY."""
    if fmt is None:
        fmt = "human" if is_tty() else "json"

    if fmt == "json":
        if isinstance(data, BaseModel):
            payload = data.model_dump(mode="json", exclude_none=False)
        else:
            payload = data
        print(json.dumps(payload, indent=indent))
    else:
        # Human-readable: use rich if available, otherwise pretty JSON
        try:
            from rich import print_json
            from rich.console import Console

            Console()
            if isinstance(data, BaseModel):
                payload = data.model_dump(mode="json", exclude_none=False)
            else:
                payload = data
            print_json(json.dumps(payload))
        except ImportError:
            emit(data, fmt="json")


def emit_error(message: str, fmt: str | None = None) -> None:
    """Emit a structured error envelope."""
    payload: dict[str, Any] = {"status": "error", "message": message}
    if fmt == "json" or (fmt is None and not is_tty()):
        print(json.dumps(payload))
    else:
        try:
            from rich.console import Console
            Console(stderr=True).print(f"[red]Error:[/red] {message}")
        except ImportError:
            print(f"Error: {message}", file=sys.stderr)
