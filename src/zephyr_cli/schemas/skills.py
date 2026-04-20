"""Pydantic schemas for the skills registry."""

from __future__ import annotations

from pydantic import BaseModel


class SkillEntry(BaseModel):
    """A single skill entry from the registry index."""

    name: str
    description: str
    keywords: list[str] = []
    kconfig_patterns: list[str] = []
    dts_compatible: list[str] = []
    path: str  # relative path in the repo, e.g. "skills/build-system"
    files: list[str] = []  # relative to path, e.g. ["SKILL.md", "references/west.md"]


class SkillsIndex(BaseModel):
    """The registry index downloaded from the skills repo."""

    schema_version: str = "1"
    repo: str
    updated: str
    skills: list[SkillEntry]


class InstalledSkill(BaseModel):
    """A skill installed in the workspace."""

    name: str
    description: str = ""
    path: str
    installed_at: str = ""


class SkillListResult(BaseModel):
    """Result of the skills list command."""

    status: str
    workspace: str | None = None
    available: list[SkillEntry] = []
    installed: list[InstalledSkill] = []


class SkillInstallResult(BaseModel):
    """Result of the skills install command."""

    status: str
    name: str
    path: str = ""
    files_written: int = 0
    message: str = ""


class SkillSuggestResult(BaseModel):
    """Result of the skills suggest command."""

    status: str
    query: str
    suggestions: list[SkillEntry] = []
