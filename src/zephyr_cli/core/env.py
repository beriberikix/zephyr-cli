"""Environment introspection utilities."""

from __future__ import annotations

from importlib import metadata, util
import os
import shutil
import subprocess
import sys
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


def _runtime_python_info() -> ToolInfo:
    version = _run_version([sys.executable, "--version"])
    return ToolInfo(path=sys.executable, version=version, available=bool(sys.executable))


def _module_available(name: str) -> bool:
    try:
        return util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _west_command() -> tuple[list[str] | None, str | None, bool]:
    path = shutil.which("west")
    importable = _module_available("west")
    if importable:
        return [sys.executable, "-m", "west"], path, True
    if path is not None:
        return [path], path, False
    return None, None, False


def _west_info() -> WestInfo:
    # Strategy: try in-process import first (avoids PATH issues when
    # zephyr-cli and west are co-installed), then fall back to subprocess.
    workspace_root = None
    manifest_path = None
    version = None
    west_cmd, path, importable = _west_command()

    # 1. Try in-process detection via west library
    if importable:
        try:
            from west.util import west_topdir  # type: ignore[import-untyped]

            workspace_root = str(west_topdir())
        except Exception:
            pass

    # 2. Try in-process manifest path
    if importable and workspace_root is not None:
        try:
            from west.manifest import Manifest  # type: ignore[import-untyped]

            m = Manifest.from_topdir(topdir=workspace_root)
            if m.abspath:
                manifest_path = str(m.abspath)
        except Exception:
            pass

    # 3. Try subprocess as fallback for workspace discovery
    if workspace_root is None and west_cmd is not None:
        try:
            result = subprocess.run(
                [*west_cmd, "topdir"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                workspace_root = result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    if manifest_path is None and west_cmd is not None:
        try:
            result = subprocess.run(
                [*west_cmd, "manifest", "--path"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                manifest_path = result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    # Determine version
    if importable:
        try:
            version = f"West version: v{metadata.version('west')}"
        except metadata.PackageNotFoundError:
            version = None
    if version is None and west_cmd is not None:
        version = _run_version([*west_cmd, "--version"])

    # Available if west is importable, on PATH, or we resolved a workspace.
    available = importable or path is not None or workspace_root is not None

    return WestInfo(
        version=version,
        workspace_root=workspace_root,
        manifest_path=manifest_path,
        available=available,
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


def _west_agent_available() -> tuple[bool, str | None]:
    """Check whether the west agent extension is registered.

    Returns (available, reason) where reason explains why the extension
    is not available when available is False.
    """
    west_cmd, _, _ = _west_command()
    if west_cmd is None:
        return False, "west is not installed or not on PATH"
    try:
        result = subprocess.run(
            [*west_cmd, "help", "agent"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True, None
        return (
            False,
            "west agent extension is not registered in the workspace manifest; "
            "add west-commands.yml reference to your west.yml "
            "(see zephyr-cli README for setup instructions)",
        )
    except FileNotFoundError:
        return False, "west is not installed or not on PATH"
    except subprocess.TimeoutExpired:
        return False, "west help agent timed out"
    except OSError as exc:
        return False, f"OS error checking west agent: {exc}"


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

    # If WEST_TOPDIR was set but west detection missed it, patch up
    if ws_root and not west.available:
        west = WestInfo(
            version=west.version,
            workspace_root=ws_root,
            manifest_path=west.manifest_path,
            available=True,
        )

    # Resolve skills dir
    if skills_dir is None and ws_root:
        from zephyr_cli.core.config import SKILLS_DIR_RELPATH
        skills_dir = Path(ws_root) / SKILLS_DIR_RELPATH

    agent_available, agent_reason = _west_agent_available()

    return EnvResult(
        zephyr_base=zephyr_base,
        board=os.environ.get("BOARD"),
        sdk=_sdk_info(),
        west=west,
        cmake=_tool_info("cmake", ["--version"]),
        ninja=_tool_info("ninja", ["--version"]),
        python=_runtime_python_info(),
        zephyr_env_vars=zephyr_vars,
        skills_dir=str(skills_dir) if skills_dir else None,
        installed_skills=_installed_skills(skills_dir),
        west_agent_available=agent_available,
        west_agent_reason=agent_reason,
    )
