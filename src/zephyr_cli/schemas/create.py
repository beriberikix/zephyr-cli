"""Pydantic schemas for project creation (zephyr-cli create)."""

from __future__ import annotations

from pydantic import BaseModel


class CreateResult(BaseModel):
    """Result of zephyr-cli create."""

    status: str
    name: str
    topology: str  # "T1" | "T2" | "T3"
    app_path: str
    files: list[str] = []
    next_steps: list[str] = []
    message: str = ""
