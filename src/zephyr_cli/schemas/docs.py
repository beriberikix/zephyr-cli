"""Pydantic schemas for zephyr-cli docs."""

from __future__ import annotations

from pydantic import BaseModel


class DocsRelease(BaseModel):
    """A published docs release."""

    version: str
    tag: str
    url: str
    size_bytes: int | None = None
    published_at: str = ""


class DocsListResult(BaseModel):
    """Result of docs list command."""

    status: str
    cached: list[str] = []
    available: list[DocsRelease] = []
    cache_dir: str = ""


class DocsRefreshResult(BaseModel):
    """Result of docs refresh command."""

    status: str
    version: str = ""
    path: str = ""
    message: str = ""
