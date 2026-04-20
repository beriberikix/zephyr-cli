"""Environment introspection utilities."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from zephyr_cli.schemas.env import EnvResult, SDKInfo, ToolInfo, WestInfo

# Zephyr-specific env vars surfaced for agents
_ZEPHYR_ENV_VARS = [
    "ZEPHYR_BASE",
    "ZEPHYR_SDK_INSTALL_DIR",
    "GNUARMEMB_TOOLCHAIN_PATH",
    "ZEPHYR_TOOLCHAIN_VARIANT",
    "BOARD",
    "WEST_MANIFEST_PATH",
    "WEST_TOPDIR",
    "CMAKE_PREFIX_PATH",
]


def _run_version(cmd: list[str]) -> str | None:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[0]
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def _tool_info(name: str, version_args: list[str] | None = None) -> ToolInfo:
    path = shutil.which(name)
    if path is None:
        return ToolInfo(available=False)
    version = None
    if version_args:
        version = _run_version([path, *version_args])
    return ToolInfo(path=path, version=version, available=True)


def _west_info() -> WestInfo:
    path = shutil.which("west")
    if path is None:
        return WestInfo(available=False)

    version = _run_version([path, "--version"])

    # Try to discover workspace via west topdir
    workspace_root = None
    manifest_path = None
    try:
        result = subprocess.run(
            [path, "topdir"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            workspace_root = result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    # Try manifest path
    try:
        result = subprocess.run(
            [path, "manifest", "--path"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            manifest_path = result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    return WestInfo(
        version=version,
        workspace_root=workspace_root,
        manifest_path=manifest_path,
        available=True,
    )


def _sdk_info() -> SDKInfo:
    """Detect Zephyr SDK installation."""
    sdk_path = os.environ.get("ZEPHYR_SDK_INSTALL_DIR")

    # Common default install locations
    search_paths = []
    if sdk_path:
        search_paths.append(Path(sdk_path))
    search_paths += [
        Path.home() / "zephyr-sdk",
        Path("/opt/zephyr-sdk"),
        Path.home() / ".local" / "zephyr-sdk",
    ]
    # Also search glob patterns for versioned installs
    for base in [Path.home(), Path("/opt")]:
        search_paths += list(base.glob("zephyr-sdk-*"))

    for candidate in search_paths:
        version_file = candidate / "sdk_version"
        if version_file.exists():
            version = version_file.read_text().strip()
            # List installed toolchain directories
            toolchains = sorted(
                d.name
                for d in candidate.iterdir()
                if d.is_dir() and "-zephyr-" in d.name
            )
            return SDKInfo(
                version=version,
                path=str(candidate),
                available=True,
                toolchains=toolchains,
            )

    return SDKInfo(available=False)


def _west_agent_available() -> bool:
    """Check whether the west agent extension is registered."""
    try:
        result = subprocess.run(
            ["west", "help", "agent"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _installed_skills(skills_dir: Path | None) -> list[str]:
    if skills_dir is None or not skills_dir.is_dir():
        return []
    return sorted(
        d.name
        for d in skills_dir.iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    )


def collect_env(skills_dir: Path | None = None) -> EnvResult:
    """Collect full environment state for the env command."""
    zephyr_base = os.environ.get("ZEPHYR_BASE")

    # Collect Zephyr-related env vars
    zephyr_vars = {k: v for k in _ZEPHYR_ENV_VARS if (v := os.environ.get(k))}

    west = _west_info()

    # Prefer WEST_TOPDIR from env, then from west topdir discovery
    ws_root = os.environ.get("WEST_TOPDIR") or west.workspace_root

    # Resolve skills dir
    if skills_dir is None and ws_root:
        from zephyr_cli.core.config import SKILLS_DIR_RELPATH
        skills_dir = Path(ws_root) / SKILLS_DIR_RELPATH

    return EnvResult(
        zephyr_base=zephyr_base,
        board=os.environ.get("BOARD"),
        sdk=_sdk_info(),
        west=west,
        cmake=_tool_info("cmake", ["--version"]),
        ninja=_tool_info("ninja", ["--version"]),
        python=_tool_info("python3", ["--version"]),
        zephyr_env_vars=zephyr_vars,
        skills_dir=str(skills_dir) if skills_dir else None,
        installed_skills=_installed_skills(skills_dir),
        west_agent_available=_west_agent_available(),
    )
