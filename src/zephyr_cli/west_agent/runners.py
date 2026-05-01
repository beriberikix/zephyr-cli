"""Helpers for reading Zephyr build metadata from zephyr/runners.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_runners_yaml(build_dir: Path) -> dict[str, Any]:
    """Load zephyr/runners.yaml for *build_dir*.

    Prefers YAML parsing when available, but falls back to a lightweight text
    parser so the caller still gets the common fields used by zephyr-cli.
    """
    runners_yaml = build_dir / "zephyr" / "runners.yaml"
    if not runners_yaml.is_file():
        return {}

    try:
        import yaml  # type: ignore[import-untyped]

        with runners_yaml.open() as fh:
            loaded = yaml.safe_load(fh) or {}
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        pass

    return _legacy_load_runners_yaml(runners_yaml)


def runner_names(build_dir: Path) -> set[str]:
    """Return configured runner names from zephyr/runners.yaml."""
    runners = load_runners_yaml(build_dir).get("runners")
    return _extract_runner_names(runners)


def default_runner(build_dir: Path, operation: str) -> str | None:
    """Return the configured default runner for *operation*."""
    value = load_runners_yaml(build_dir).get(f"{operation}-runner")
    if isinstance(value, str) and value:
        return value
    return None


def runner_config_value(build_dir: Path, key: str) -> str | None:
    """Return a scalar entry from the runners.yaml config block."""
    config = load_runners_yaml(build_dir).get("config")
    if not isinstance(config, dict):
        return None

    value = config.get(key)
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None

    text = str(value).strip()
    return text or None


def runner_config_list(build_dir: Path, key: str) -> list[str]:
    """Return a list entry from the runners.yaml config block."""
    config = load_runners_yaml(build_dir).get("config")
    if not isinstance(config, dict):
        return []

    value = config.get(key)
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, dict):
        return []

    text = str(value).strip()
    return [text] if text else []


def _extract_runner_names(value: Any) -> set[str]:
    names: set[str] = set()

    if isinstance(value, dict):
        for key in value:
            text = str(key).strip()
            if text:
                names.add(text)
        return names

    if isinstance(value, (list, tuple, set)):
        for entry in value:
            if isinstance(entry, str):
                text = entry.strip()
                if text:
                    names.add(text)
            elif isinstance(entry, dict):
                named = entry.get("name")
                if isinstance(named, str) and named.strip():
                    names.add(named.strip())
                else:
                    for key in entry:
                        text = str(key).strip()
                        if text:
                            names.add(text)

    return names


def _legacy_load_runners_yaml(runners_yaml: Path) -> dict[str, Any]:
    data: dict[str, Any] = {"config": {}}
    current_section: str | None = None
    current_list_key: str | None = None

    try:
        raw_lines = runners_yaml.read_text().splitlines()
    except OSError:
        return {}

    for raw_line in raw_lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip())
        if indent == 0:
            current_section = None
            current_list_key = None
            if ":" not in stripped:
                continue

            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not value:
                if key == "config":
                    data["config"] = {}
                elif key == "runners":
                    data["runners"] = []
                current_section = key
                continue

            data[key] = value
            continue

        if current_section == "runners":
            runners = data.setdefault("runners", [])
            if not isinstance(runners, list):
                runners = data["runners"] = []
            if stripped.startswith("-"):
                item = stripped[1:].strip()
                if item:
                    runners.append(item)
                continue
            if ":" in stripped:
                item = stripped.split(":", 1)[0].strip()
                if item:
                    runners.append(item)
            continue

        if current_section == "config":
            config = data.setdefault("config", {})
            if not isinstance(config, dict):
                config = data["config"] = {}

            if stripped.startswith("-") and current_list_key is not None:
                values = config.setdefault(current_list_key, [])
                if isinstance(values, list):
                    item = stripped[1:].strip()
                    if item:
                        values.append(item)
                continue

            if ":" not in stripped:
                continue

            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not value:
                config[key] = []
                current_list_key = key
            else:
                config[key] = value
                current_list_key = None

    return data
