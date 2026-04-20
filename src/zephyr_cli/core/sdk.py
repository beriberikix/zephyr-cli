"""Zephyr SDK manager.

Handles listing, downloading, extracting, and selecting Zephyr SDK versions.
SDK releases are fetched from github.com/zephyrproject-rtos/sdk-ng.
Installed SDKs live in <data_dir>/sdks/<version>/.
"""

from __future__ import annotations

import platform
import subprocess
import tarfile
from pathlib import Path

import httpx

from zephyr_cli.core.config import ZephyrCliConfig
from zephyr_cli.schemas.sdk import InstalledSdk, SdkRelease

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SDK_RELEASES_API = "https://api.github.com/repos/zephyrproject-rtos/sdk-ng/releases"
_SELECTED_FILE = "sdk_selected.txt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sdk_base(cfg: ZephyrCliConfig) -> Path:
    d = Path(cfg.data_dir) / "sdks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _detect_platform() -> str:
    """Return a platform string matching Zephyr SDK asset names."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "linux":
        arch = "x86_64" if machine in ("x86_64", "amd64") else "aarch64"
        return f"linux-{arch}"
    if system == "darwin":
        arch = "aarch64" if machine == "arm64" else "x86_64"
        return f"macos-{arch}"
    raise RuntimeError(f"Unsupported platform: {system}/{machine}")


def _read_selected(cfg: ZephyrCliConfig) -> str | None:
    sel = _sdk_base(cfg) / _SELECTED_FILE
    return sel.read_text().strip() if sel.exists() else None


def _write_selected(cfg: ZephyrCliConfig, version: str) -> None:
    (_sdk_base(cfg) / _SELECTED_FILE).write_text(version)


# ---------------------------------------------------------------------------
# List installed
# ---------------------------------------------------------------------------


def list_installed(cfg: ZephyrCliConfig) -> list[InstalledSdk]:
    """Return all installed SDKs."""
    base = _sdk_base(cfg)
    selected = _read_selected(cfg)
    result: list[InstalledSdk] = []
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        ver_file = d / "sdk_version"
        if not ver_file.exists():
            continue
        ver = ver_file.read_text().strip()
        result.append(InstalledSdk(version=ver, path=str(d), selected=(ver == selected)))
    return result


# ---------------------------------------------------------------------------
# Fetch available from GitHub
# ---------------------------------------------------------------------------


def fetch_available(limit: int = 10) -> list[SdkRelease]:
    """Return recent SDK releases from GitHub."""
    plat = _detect_platform()
    resp = httpx.get(SDK_RELEASES_API, params={"per_page": limit}, timeout=15)
    resp.raise_for_status()

    releases: list[SdkRelease] = []
    for rel in resp.json():
        version = rel.get("tag_name", "").lstrip("v")
        if not version:
            continue
        url: str | None = None
        minimal_url: str | None = None
        for asset in rel.get("assets", []):
            name: str = asset["name"]
            is_minimal = "minimal" in name
            is_toolchain = "toolchain" in name
            matches_plat = f"_{plat}" in name and name.endswith(".tar.xz")
            if matches_plat and not is_toolchain:
                if is_minimal:
                    minimal_url = asset["browser_download_url"]
                else:
                    url = asset["browser_download_url"]
        if url:
            releases.append(
                SdkRelease(version=version, url=url, minimal_url=minimal_url)
            )

    return releases


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


def install_sdk(cfg: ZephyrCliConfig, version: str, minimal: bool = False) -> InstalledSdk:
    """Download, extract, and set up a Zephyr SDK version."""
    available = fetch_available(limit=20)
    ver_norm = version.lstrip("v")
    match = next(
        (r for r in available if r.version == ver_norm or r.version == version), None
    )
    if match is None:
        raise ValueError(f"SDK version {version!r} not found in recent GitHub releases")

    download_url = (match.minimal_url if minimal and match.minimal_url else None) or match.url
    base = _sdk_base(cfg)
    archive = base / f"zephyr-sdk-{ver_norm}.tar.xz"

    # Stream download
    with httpx.stream("GET", download_url, follow_redirects=True, timeout=600) as resp:
        resp.raise_for_status()
        with archive.open("wb") as fh:
            for chunk in resp.iter_bytes(chunk_size=65536):
                fh.write(chunk)

    # Extract
    with tarfile.open(archive, "r:xz") as tf:
        tf.extractall(base)
    archive.unlink(missing_ok=True)

    # The tarball may contain a versioned root dir; normalise it
    dest = base / f"zephyr-sdk-{ver_norm}"
    if not dest.exists():
        candidates = sorted(
            d for d in base.iterdir()
            if d.is_dir() and d.name.startswith(f"zephyr-sdk-{ver_norm}")
        )
        if candidates:
            candidates[0].rename(dest)

    # Run the SDK setup script to register CMake packages
    setup = dest / "setup.sh"
    if setup.exists():
        subprocess.run(
            ["bash", str(setup), "-c"],
            cwd=str(dest),
            check=True,
            capture_output=True,
        )

    return InstalledSdk(version=ver_norm, path=str(dest), selected=False)


# ---------------------------------------------------------------------------
# Select
# ---------------------------------------------------------------------------


def select_sdk(cfg: ZephyrCliConfig, version: str) -> InstalledSdk:
    """Mark an installed SDK version as selected and persist the choice."""
    ver_norm = version.lstrip("v")
    installed = list_installed(cfg)
    match = next((s for s in installed if s.version == ver_norm), None)
    if match is None:
        raise FileNotFoundError(
            f"SDK {version!r} is not installed. Run 'zephyr-cli sdk install {version}' first."
        )
    _write_selected(cfg, ver_norm)
    return InstalledSdk(version=match.version, path=match.path, selected=True)
