"""Pydantic v2 schemas for environment introspection output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ToolInfo(BaseModel):
    path: str | None = None
    version: str | None = None
    available: bool = False


class SDKInfo(BaseModel):
    version: str | None = None
    path: str | None = None
    available: bool = False
    toolchains: list[str] = Field(default_factory=list)


class WestInfo(BaseModel):
    version: str | None = None
    workspace_root: str | None = None
    manifest_path: str | None = None
    available: bool = False


class EnvResult(BaseModel):
    zephyr_base: str | None = None
    board: str | None = None
    sdk: SDKInfo = Field(default_factory=SDKInfo)
    west: WestInfo = Field(default_factory=WestInfo)
    cmake: ToolInfo = Field(default_factory=ToolInfo)
    ninja: ToolInfo = Field(default_factory=ToolInfo)
    python: ToolInfo = Field(default_factory=ToolInfo)
    # Raw env vars relevant to Zephyr, for agent inspection
    zephyr_env_vars: dict[str, str] = Field(default_factory=dict)
    # Skills context
    skills_dir: str | None = None
    installed_skills: list[str] = Field(default_factory=list)
    # West agent extension availability
    west_agent_available: bool = False
    west_agent_reason: str | None = None
