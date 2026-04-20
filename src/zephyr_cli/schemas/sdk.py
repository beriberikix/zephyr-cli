"""Pydantic schemas for Zephyr SDK management."""

from __future__ import annotations

from pydantic import BaseModel


class SdkRelease(BaseModel):
    """A Zephyr SDK release available for download."""

    version: str
    url: str
    minimal_url: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None


class InstalledSdk(BaseModel):
    """An installed Zephyr SDK."""

    version: str
    path: str
    selected: bool = False


class SdkListResult(BaseModel):
    """Result of sdk list command."""

    status: str
    installed: list[InstalledSdk] = []
    available: list[SdkRelease] = []
    selected: str | None = None


class SdkInstallResult(BaseModel):
    """Result of sdk install command."""

    status: str
    version: str
    path: str = ""
    message: str = ""


class SdkSelectResult(BaseModel):
    """Result of sdk select command."""

    status: str
    version: str
    path: str = ""
    hint: str = ""
