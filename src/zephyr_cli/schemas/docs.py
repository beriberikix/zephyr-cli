"""Pydantic schemas for zephyr-cli docs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DocsManifest(BaseModel):
    """Metadata a docs bundle carries about itself, in its manifest.json."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    schema_version: int = Field(default=1, alias="schema")
    version: str = ""
    zephyr_repo: str = ""
    zephyr_ref: str = ""
    docs_base_url: str = ""
    page_count: int | None = None


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
    manifest: DocsManifest | None = None
