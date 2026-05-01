"""Output formatting helpers.

All commands support --format json (default in non-TTY) and --format human.
"""

from __future__ import annotations

import json
from pprint import pformat
import sys
from typing import Any

from pydantic import BaseModel


def is_tty() -> bool:
    return sys.stdout.isatty()


def _payload(data: BaseModel | dict) -> dict:
    if isinstance(data, BaseModel):
        return data.model_dump(mode="json", exclude_none=False)
    return data


def emit(data: BaseModel | dict, fmt: str | None = None, indent: int = 2) -> None:
    """Emit structured output. fmt=None auto-detects based on TTY."""
    if fmt is None:
        fmt = "human" if is_tty() else "json"

    payload = _payload(data)

    if fmt == "json":
        print(json.dumps(payload, indent=indent))
    else:
        # Human-readable: use rich pretty-printing if available, otherwise
        # fall back to pprint so explicit human output differs from JSON.
        try:
            from rich.console import Console
            from rich.pretty import Pretty

            Console().print(Pretty(payload, expand_all=True))
        except ImportError:
            print(pformat(payload, sort_dicts=False, width=100))


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
