"""Docs manager for zephyr-cli docs.

Downloads LLM-optimised Zephyr documentation tarballs from GitHub Releases
on beriberikix/zephyrdocs.md and caches them locally.
"""

from __future__ import annotations

import json
import shutil
import tarfile
from pathlib import Path

import httpx
from pydantic import ValidationError

from zephyr_cli.core.config import ZephyrCliConfig
from zephyr_cli.schemas.docs import DocsManifest, DocsRelease

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RELEASES_API = "https://api.github.com/repos/beriberikix/zephyrdocs.md/releases"
_CACHE_SUBDIR = "docs"
_MANIFEST_NAME = "manifest.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _docs_cache(cfg: ZephyrCliConfig) -> Path:
    d = Path(cfg.data_dir) / _CACHE_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _find_manifest(root: Path) -> Path | None:
    """Locate manifest.json at the bundle root or one level under it."""
    direct = root / _MANIFEST_NAME
    if direct.is_file():
        return direct

    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        candidate = child / _MANIFEST_NAME
        if candidate.is_file():
            return candidate

    return None


def read_manifest(path: Path) -> DocsManifest | None:
    """Read a bundle's manifest.json, or None when it is absent or unusable.

    Bundles published before manifests existed simply do not have one, so a
    missing or malformed file is not an error.
    """
    try:
        manifest_path = _find_manifest(path)
    except OSError:
        return None

    if manifest_path is None:
        return None

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    try:
        return DocsManifest.model_validate(data)
    except ValidationError:
        return None


def _extract(archive: Path, dest: Path) -> None:
    """Extract a downloaded tarball, refusing members that escape dest."""
    with tarfile.open(archive, "r:gz") as tf:
        try:
            tf.extractall(dest, filter="data")
        except TypeError:
            # Python < 3.11.4 has no extraction filters.
            tf.extractall(dest)


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
            if not name.endswith(".tar.gz"):
                continue
            # The git tag is mangled (e.g. "zephyrproject-rtos-zephyr-v4-4-0");
            # the asset name carries the clean version, e.g.
            # "zephyrdocs-v4.4.0.tar.gz" -> "v4.4.0".
            version = name.removeprefix("zephyrdocs-").removesuffix(".tar.gz") or tag
            releases.append(
                DocsRelease(
                    version=version,
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

    # Extract to a staging directory first: the bundle names its own version in
    # manifest.json, and that is more trustworthy than the version recovered
    # from the asset filename, which is only a naming convention.
    staging = cache / f".{release.version}.incoming"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()

    try:
        _extract(archive, staging)
        archive.unlink(missing_ok=True)

        manifest = read_manifest(staging)
        version = manifest.version if manifest and manifest.version else release.version

        dest = cache / version
        if dest.exists():
            return version, dest

        staging.rename(dest)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        archive.unlink(missing_ok=True)
        raise

    return version, dest
