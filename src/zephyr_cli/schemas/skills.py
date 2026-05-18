"""Pydantic schemas for the skills registry."""

from __future__ import annotations

from pydantic import BaseModel


class SkillEntry(BaseModel):
    """A single skill entry from the registry index.

    Fields ``summary``, ``aliases`` and ``weight`` are index schema v2; they
    default so a cached v1 ``index.json`` still validates.
    """

    name: str
    description: str
    summary: str = ""  # short matcher-facing summary (index v2)
    keywords: list[str] = []
    aliases: list[str] = []  # short tokens / acronyms / synonyms (index v2)
    kconfig_patterns: list[str] = []
    dts_compatible: list[str] = []
    weight: float = 1.0  # per-skill score multiplier (index v2)
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


class ScoredSkill(BaseModel):
    """A skill with its match score, as returned by ``skills suggest``."""

    skill: SkillEntry
    score: float
    matched: list[str] = []  # hit reasons, e.g. ["alias:ble", "kconfig:CONFIG_BT_GATT"]


class SkillSuggestResult(BaseModel):
    """Result of the skills suggest command."""

    status: str
    query: str
    suggestions: list[ScoredSkill] = []


class SkillApplyResult(BaseModel):
    """Result of the skills apply command."""

    status: str
    name: str
    target: str = ""
    files_applied: list[str] = []
    message: str = ""
