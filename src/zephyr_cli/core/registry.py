"""Skills registry client.

Fetches the index.json from the skills repo, caches it locally,
and provides install / list / suggest operations.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import httpx

from zephyr_cli.core.config import ZephyrCliConfig
from zephyr_cli.schemas.skills import InstalledSkill, SkillEntry, SkillsIndex

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RAW_BASE = "https://raw.githubusercontent.com/beriberikix/zephyr-agent-skills/main"
CACHE_TTL = 3600  # seconds


# ---------------------------------------------------------------------------
# Index loading
# ---------------------------------------------------------------------------


def _registry_cache_dir(cfg: ZephyrCliConfig) -> Path:
    d = Path(cfg.data_dir) / "registry"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_index(cfg: ZephyrCliConfig, force_refresh: bool = False) -> SkillsIndex:
    """Return the skills index, using a local cache when fresh.

    Raises ``httpx.HTTPError`` on network failure.
    """
    cache_dir = _registry_cache_dir(cfg)
    index_cache = cache_dir / "index.json"
    meta_cache = cache_dir / "index.meta"

    if not force_refresh and index_cache.exists() and meta_cache.exists():
        try:
            age = time.time() - float(meta_cache.read_text().strip())
            if age < CACHE_TTL:
                return SkillsIndex.model_validate_json(index_cache.read_text())
        except (ValueError, Exception):
            pass

    resp = httpx.get(cfg.skills_registry_url, follow_redirects=True, timeout=15)
    resp.raise_for_status()

    index_cache.write_text(resp.text)
    meta_cache.write_text(str(time.time()))

    return SkillsIndex.model_validate_json(resp.text)


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


def install_skill(
    skill: SkillEntry,
    workspace_root: Path,
) -> tuple[Path, int]:
    """Download a skill's files into ``<workspace>/.zephyr/skills/<name>/``.

    Returns ``(dest_path, files_written)``.
    """
    dest = workspace_root / ".zephyr" / "skills" / skill.name
    dest.mkdir(parents=True, exist_ok=True)

    files_to_fetch = skill.files if skill.files else ["SKILL.md"]
    written = 0

    for rel_file in files_to_fetch:
        url = f"{RAW_BASE}/{skill.path}/{rel_file}"
        resp = httpx.get(url, follow_redirects=True, timeout=30)
        resp.raise_for_status()

        target = dest / rel_file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(resp.content)
        written += 1

    # Write skill metadata sidecar
    meta = {
        "name": skill.name,
        "description": skill.description,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": files_to_fetch,
    }
    (dest / ".zephyr-skill.json").write_text(json.dumps(meta, indent=2))

    return dest, written


# ---------------------------------------------------------------------------
# List installed
# ---------------------------------------------------------------------------


def list_installed(workspace_root: Path) -> list[InstalledSkill]:
    """Return skills installed in this workspace."""
    skills_dir = workspace_root / ".zephyr" / "skills"
    if not skills_dir.exists():
        return []

    result: list[InstalledSkill] = []
    for d in sorted(skills_dir.iterdir()):
        if not d.is_dir():
            continue
        meta_file = d / ".zephyr-skill.json"
        if not meta_file.exists():
            continue
        try:
            data = json.loads(meta_file.read_text())
            result.append(
                InstalledSkill(
                    name=data.get("name", d.name),
                    description=data.get("description", ""),
                    path=str(d),
                    installed_at=data.get("installed_at", ""),
                )
            )
        except (json.JSONDecodeError, KeyError):
            continue

    return result


# ---------------------------------------------------------------------------
# Suggest
# ---------------------------------------------------------------------------


def suggest_skills(
    index: SkillsIndex,
    query: str,
    kconfig_symbols: list[str] | None = None,
    dts_compatibles: list[str] | None = None,
    max_results: int = 5,
) -> list[SkillEntry]:
    """Rank and return skills relevant to *query*, kconfig symbols, or DTS compatibles."""
    query_lower = query.lower() if query else ""
    query_tokens = {t for t in re.split(r"\W+", query_lower) if len(t) > 2}

    scored: list[tuple[int, SkillEntry]] = []

    for skill in index.skills:
        score = 0

        # Match tokens against description
        desc_lower = skill.description.lower()
        for token in query_tokens:
            if token in desc_lower:
                score += 1

        # Keyword exact / partial match (weighted higher)
        for kw in skill.keywords:
            kw_lower = kw.lower()
            if kw_lower in query_lower:
                score += 3
            elif any(t in kw_lower for t in query_tokens):
                score += 1

        # Kconfig pattern match (strong signal)
        if kconfig_symbols:
            for sym in kconfig_symbols:
                for pattern in skill.kconfig_patterns:
                    regex = re.compile(pattern.replace("*", ".*"))
                    if regex.fullmatch(sym):
                        score += 5

        # DTS compatible match (strong signal)
        if dts_compatibles:
            for compat in dts_compatibles:
                if compat in skill.dts_compatible:
                    score += 5

        if score > 0:
            scored.append((score, skill))

    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:max_results]]
