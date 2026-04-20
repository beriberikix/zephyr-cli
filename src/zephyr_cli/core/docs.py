"""Docs manager for zephyr-cli docs.

Downloads LLM-optimised Zephyr documentation tarballs from GitHub Releases
on beriberikix/zephyrdocs.md and caches them locally.
"""

from __future__ import annotations

import tarfile
from pathlib import Path

import httpx

from zephyr_cli.core.config import ZephyrCliConfig
from zephyr_cli.schemas.docs import DocsRelease

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RELEASES_API = "https://api.github.com/repos/beriberikix/zephyrdocs.md/releases"
_CACHE_SUBDIR = "docs"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _docs_cache(cfg: ZephyrCliConfig) -> Path:
    d = Path(cfg.data_dir) / _CACHE_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def list_cached(cfg: ZephyrCliConfig) -> list[str]:
    """Return version strings for locally cached doc packages."""
    cache = _docs_cache(cfg)
    return sorted(d.name for d in cache.iterdir() if d.is_dir())


def fetch_releases(limit: int = 10) -> list[DocsRelease]:
    """Fetch available docs releases from GitHub Releases API."""
    resp = httpx.get(RELEASES_API, params={"per_page": limit}, timeout=15)
    resp.raise_for_status()

    releases: list[DocsRelease] = []
    for rel in resp.json():
        tag = rel.get("tag_name", "")
        if not tag:
            continue
        for asset in rel.get("assets", []):
            name: str = asset["name"]
            if name.endswith("-markdown.tar.gz"):
                releases.append(
                    DocsRelease(
                        version=tag,
                        tag=tag,
                        url=asset["browser_download_url"],
                        size_bytes=asset.get("size"),
                        published_at=rel.get("published_at", ""),
                    )
                )

    return releases


# ---------------------------------------------------------------------------
# Refresh (download + extract)
# ---------------------------------------------------------------------------


def refresh(cfg: ZephyrCliConfig, version: str | None = None) -> tuple[str, Path]:
    """Download and cache a docs release.

    If *version* is None, the latest release is used.
    Returns ``(version, extracted_path)``.

    Raises ``RuntimeError`` if no releases are available.
    """
    releases = fetch_releases()
    if not releases:
        raise RuntimeError(
            "No docs releases found. "
            "The beriberikix/zephyrdocs.md repo may not have published any releases yet."
        )

    if version is not None:
        release = next((r for r in releases if r.version == version or r.tag == version), None)
        if release is None:
            raise ValueError(f"Docs version {version!r} not found in releases")
    else:
        release = releases[0]

    cache = _docs_cache(cfg)
    dest = cache / release.version
    if dest.exists():
        # Already cached
        return release.version, dest

    archive = cache / f"{release.version}.tar.gz"
    with httpx.stream("GET", release.url, follow_redirects=True, timeout=600) as resp:
        resp.raise_for_status()
        with archive.open("wb") as fh:
            for chunk in resp.iter_bytes(chunk_size=65536):
                fh.write(chunk)

    dest.mkdir()
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(dest)
    archive.unlink(missing_ok=True)

    return release.version, dest
