"""Configuration resolution for zephyr-cli.

Priority (highest to lowest):
  1. Environment variables (ZEPHYR_CLI_*)
  2. Workspace config  <workspace>/.zephyr/config.toml
  3. User config       ~/.config/zephyr-cli/config.toml
  4. Built-in defaults
"""

from __future__ import annotations

import os
import tomllib  # type: ignore[no-redef]
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_config_dir

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP_NAME = "zephyr-cli"
DEFAULT_SKILLS_REGISTRY_URL = (
    "https://raw.githubusercontent.com/beriberikix/zephyr-agent-skills/main/index.json"
)
DEFAULT_DOCS_RELEASE_BASE = (
    "https://github.com/beriberikix/zephyrdocs.md/releases/download"
)
WORKSPACE_CONFIG_RELPATH = ".zephyr/config.toml"
SKILLS_DIR_RELPATH = ".zephyr/skills"


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------


@dataclass
class ZephyrCliConfig:
    # SDK
    sdk_path: str | None = None
    sdk_version: str | None = None

    # Skills registry
    skills_registry_url: str = DEFAULT_SKILLS_REGISTRY_URL
    extra_registry_urls: list[str] = field(default_factory=list)

    # Docs
    docs_release_base_url: str = DEFAULT_DOCS_RELEASE_BASE

    # Output
    default_format: str = "json"  # "json" | "human"

    # Emulation backend override (empty = auto-detect)
    emulate_backend: str = ""

    # Remote emulation server URL (enables "remote" backend)
    remote_emulate_url: str = ""


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _load_toml(path: Path) -> dict:
    if path.exists():
        with open(path, "rb") as f:
            return tomllib.load(f)
    return {}


def _user_config_path() -> Path:
    return Path(user_config_dir(APP_NAME)) / "config.toml"


def _workspace_config_path() -> Path | None:
    """Walk up from cwd to find a .zephyr/config.toml."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / WORKSPACE_CONFIG_RELPATH
        if candidate.exists():
            return candidate
        # Stop at west workspace root
        if (parent / ".west").is_dir():
            return parent / WORKSPACE_CONFIG_RELPATH
    return None


def load_config() -> ZephyrCliConfig:
    """Load and merge configuration from all sources."""
    cfg = ZephyrCliConfig()

    # Layer 1: user config
    user_cfg = _load_toml(_user_config_path())
    _apply_toml(cfg, user_cfg)

    # Layer 2: workspace config
    ws_path = _workspace_config_path()
    if ws_path:
        ws_cfg = _load_toml(ws_path)
        _apply_toml(cfg, ws_cfg)

    # Layer 3: environment variables
    _apply_env(cfg)

    return cfg


def _apply_toml(cfg: ZephyrCliConfig, data: dict) -> None:
    mapping = {
        ("sdk", "path"): "sdk_path",
        ("sdk", "version"): "sdk_version",
        ("skills", "registry_url"): "skills_registry_url",
        ("skills", "extra_registries"): "extra_registry_urls",
        ("docs", "release_base_url"): "docs_release_base_url",
        ("output", "format"): "default_format",
        ("emulate", "backend"): "emulate_backend",
        ("emulate", "remote_url"): "remote_emulate_url",
    }
    for (section, key), attr in mapping.items():
        val = data.get(section, {}).get(key)
        if val is not None:
            setattr(cfg, attr, val)


def _apply_env(cfg: ZephyrCliConfig) -> None:
    env_mapping = {
        "ZEPHYR_CLI_SDK_PATH": "sdk_path",
        "ZEPHYR_CLI_SDK_VERSION": "sdk_version",
        "ZEPHYR_CLI_SKILLS_REGISTRY_URL": "skills_registry_url",
        "ZEPHYR_CLI_FORMAT": "default_format",
        "ZEPHYR_CLI_EMULATE_BACKEND": "emulate_backend",
        "ZEPHYR_CLI_REMOTE_URL": "remote_emulate_url",
    }
    for env_var, attr in env_mapping.items():
        val = os.environ.get(env_var)
        if val:
            setattr(cfg, attr, val)


# ---------------------------------------------------------------------------
# Workspace helpers
# ---------------------------------------------------------------------------


def find_workspace_root() -> Path | None:
    """Walk up from cwd to find the west workspace root (.west directory)."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".west").is_dir():
            return parent
    return None


def find_skills_dir() -> Path | None:
    """Return the workspace-local skills directory if inside a workspace."""
    root = find_workspace_root()
    if root:
        return root / SKILLS_DIR_RELPATH
    return None
