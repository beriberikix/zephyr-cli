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
from zephyr_cli.schemas.skills import InstalledSkill, ScoredSkill, SkillEntry, SkillsIndex

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


def apply_skill(
    skill: SkillEntry,
    workspace_root: Path,
    target_path: Path,
) -> tuple[Path, list[str]]:
    """Download a skill's template assets and scripts directly into a target path.

    Skips 'SKILL.md' and moves 'assets/' and 'scripts/' contents directly
    into the target directory to automate template injection.

    Returns ``(target_path, copied_files_list)``.
    """
    target_path.mkdir(parents=True, exist_ok=True)

    files_to_fetch = skill.files if skill.files else ["SKILL.md"]
    applied_files = []

    for rel_file in files_to_fetch:
        if rel_file == "SKILL.md" or rel_file.startswith("references/"):
            continue

        url = f"{RAW_BASE}/{skill.path}/{rel_file}"
        resp = httpx.get(url, follow_redirects=True, timeout=30)
        resp.raise_for_status()

        # Place assets and scripts right in the target path
        target = target_path / Path(rel_file).name
        target.write_bytes(resp.content)
        applied_files.append(str(target.relative_to(workspace_root)))

    return target_path, applied_files


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

# Scoring weights. Pure-lexical and deterministic; locked by tests/test_suggest_eval.py.
_W_PHRASE = 5.0       # a multi-word keyword/alias appears verbatim in the query
_W_ALIAS = 4.0        # query token == an alias token (catches short acronyms: ble, bt)
_W_KEYWORD = 3.0      # query token == a keyword token
_W_NAME = 2.0         # query token == a segment of the skill name
_W_SUMMARY = 1.0      # query token (len >= 3) appears in the summary
_W_DESCRIPTION = 0.5  # query token (len >= 3) appears in the description
_W_KCONFIG = 8.0      # a --kconfig symbol matches a kconfig pattern
_W_DTS_EXACT = 8.0    # a --dts compatible matches exactly
_W_DTS_PARTIAL = 2.0  # a --dts vendor/device part overlaps

MIN_SCORE = 3.0       # absolute score floor for a result to be returned
TOP_RATIO = 0.25      # also drop results below this fraction of the top score


def _tokenize(text: str) -> list[str]:
    """Lower-case and split into tokens, keeping short tokens (ble, i2c) and '+'."""
    return [t for t in re.split(r"[^a-z0-9+]+", text.lower()) if t]


def _kconfig_to_regex(pattern: str) -> re.Pattern[str]:
    """Compile a Kconfig pattern to an anchored regex.

    Only ``*`` is a wildcard; every other character (``.`` ``_`` ``+`` ...) is
    matched literally — fixes the old ``CONFIG_BT.*``-style unescaped-dot bug.
    """
    escaped = re.escape(pattern).replace(r"\*", ".*")
    return re.compile(f"^{escaped}$")


# Function words and ultra-generic terms that must never score on their own.
_STOPWORDS = frozenset({
    "a", "an", "and", "or", "of", "in", "on", "to", "for", "is", "are", "be", "as", "at",
    "by", "from", "with", "into", "over", "after", "before", "the", "this", "that", "these",
    "those", "it", "its", "my", "your", "our", "we", "you", "they", "i", "me", "how", "do",
    "does", "when", "where", "what", "why", "which", "if", "not", "no", "but", "so", "about",
    "up", "out", "get", "set", "use", "using", "used", "need", "want", "trying", "try",
    "help", "please", "make", "new", "add", "fix", "issue", "problem", "work", "working", "code",
})


def suggest_skills(
    index: SkillsIndex,
    query: str,
    kconfig_symbols: list[str] | None = None,
    dts_compatibles: list[str] | None = None,
    max_results: int = 5,
    min_score: float = MIN_SCORE,
) -> list[ScoredSkill]:
    """Rank skills by a deterministic lexical score over query, kconfig and DTS signals."""
    all_tokens = _tokenize(query)
    query_norm = " ".join(all_tokens)
    query_tokens = [t for t in all_tokens if t not in _STOPWORDS]

    scored: list[ScoredSkill] = []

    for skill in index.skills:
        raw = 0.0
        matched: list[str] = []
        consumed: set[str] = set()  # tokens already counted via a phrase match

        # Single-word terms are matched as tokens; multi-word terms only as
        # verbatim phrases — so "hardware-in-the-loop" never leaks the token "in".
        kw_single: dict[str, str] = {}
        alias_single: dict[str, str] = {}
        phrases: list[str] = []
        for term in skill.keywords:
            toks = _tokenize(term)
            if len(toks) == 1:
                kw_single.setdefault(toks[0], term)
            elif len(toks) > 1:
                phrases.append(" ".join(toks))
        for term in skill.aliases:
            toks = _tokenize(term)
            if len(toks) == 1:
                alias_single.setdefault(toks[0], term)
            elif len(toks) > 1:
                phrases.append(" ".join(toks))
        name_segments = set(_tokenize(skill.name.replace("-", " ")))
        summary_tokens = {t for t in _tokenize(skill.summary) if t not in _STOPWORDS}

        # Phrase tier: a multi-word keyword/alias appearing verbatim in the query.
        for phrase in phrases:
            if phrase and phrase in query_norm:
                raw += _W_PHRASE
                matched.append(f"phrase:{phrase}")
                consumed.update(phrase.split())

        # Token tier: each query token scores once, at its highest-scoring tier.
        # The description is intentionally NOT matched — prose is too noisy.
        for tok in dict.fromkeys(query_tokens):  # de-duped, order-stable
            if tok in consumed:
                continue
            if tok in alias_single:
                raw += _W_ALIAS
                matched.append(f"alias:{tok}")
            elif tok in kw_single:
                raw += _W_KEYWORD
                matched.append(f"keyword:{tok}")
            elif tok in name_segments:
                raw += _W_NAME
                matched.append(f"name:{tok}")
            elif tok in summary_tokens:
                raw += _W_SUMMARY
                matched.append(f"summary:{tok}")

        # Kconfig signal: each symbol scores once if any pattern matches.
        if kconfig_symbols:
            patterns = [_kconfig_to_regex(p) for p in skill.kconfig_patterns]
            for sym in kconfig_symbols:
                if any(rx.match(sym) for rx in patterns):
                    raw += _W_KCONFIG
                    matched.append(f"kconfig:{sym}")

        # DTS signal: exact compatible match, or vendor/device part overlap.
        if dts_compatibles:
            compat_parts = {part for c in skill.dts_compatible for part in c.split(",")}
            for compat in dts_compatibles:
                if compat in skill.dts_compatible:
                    raw += _W_DTS_EXACT
                    matched.append(f"dts:{compat}")
                elif any(part in compat_parts for part in compat.split(",")):
                    raw += _W_DTS_PARTIAL
                    matched.append(f"dts~:{compat}")

        score = raw * skill.weight
        if score > 0:
            scored.append(ScoredSkill(skill=skill, score=round(score, 3), matched=matched))

    if not scored:
        return []

    scored.sort(key=lambda s: (-s.score, s.skill.name))
    cutoff = max(min_score, TOP_RATIO * scored[0].score)
    return [s for s in scored if s.score >= cutoff][:max_results]
