"""West module analysis.

Parses ``zephyr/module.yml`` from each west module directory to extract
capabilities: board roots, DTS roots, Kconfig files, snippet roots, etc.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# module.yml parsing
# ---------------------------------------------------------------------------


def parse_module_yml(module_path: Path) -> dict:
    """Parse ``<module>/zephyr/module.yml`` and return a structured dict.

    Returns ``{}`` if the file does not exist or cannot be parsed.
    The module.yml schema (simplified) is::

        name: my-module
        build:
          kconfig: Kconfig
          cmake: CMakeLists.txt
          settings:
            board_root: boards
            dts_root: dts
            snippet_root: snippets
            soc_root: soc
    """
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return {"error": "pyyaml not installed"}

    module_yml = module_path / "zephyr" / "module.yml"
    if not module_yml.exists():
        return {}

    try:
        with open(module_yml) as fh:
            data = yaml.safe_load(fh) or {}
    except Exception as exc:
        return {"error": f"parse error: {exc}"}

    build = data.get("build", {}) or {}
    settings = build.get("settings", {}) or {}

    result: dict = {
        "name": data.get("name"),
        "kconfig": str(module_path / build["kconfig"]) if build.get("kconfig") else None,
        "cmake": str(module_path / build["cmake"]) if build.get("cmake") else None,
        "board_root": str(module_path / settings["board_root"]) if settings.get("board_root") else None,
        "dts_root": str(module_path / settings["dts_root"]) if settings.get("dts_root") else None,
        "snippet_root": str(module_path / settings["snippet_root"]) if settings.get("snippet_root") else None,
        "soc_root": str(module_path / settings["soc_root"]) if settings.get("soc_root") else None,
    }

    # Derive additional bindings directories
    if result["dts_root"]:
        bindings_dir = Path(result["dts_root"]) / "bindings"
        if bindings_dir.exists():
            result["dts_bindings_root"] = str(bindings_dir)

    return result


# ---------------------------------------------------------------------------
# Module listing
# ---------------------------------------------------------------------------


def list_modules() -> list[dict]:
    """Return all west modules with parsed module.yml metadata.

    Falls back to ``west list`` output; returns an error entry if west
    is not available.
    """
    try:
        proc = subprocess.run(
            ["west", "list", "--format={name} {path} {url} {revision}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        return [{"error": "west not found on PATH"}]
    except subprocess.TimeoutExpired:
        return [{"error": "west list timed out"}]

    modules: list[dict] = []
    for line in proc.stdout.strip().splitlines():
        parts = line.split(None, 3)
        if not parts:
            continue
        name = parts[0]
        path_str = parts[1] if len(parts) > 1 else ""
        url = parts[2] if len(parts) > 2 else None
        revision = parts[3] if len(parts) > 3 else None

        module_path = Path(path_str).resolve() if path_str and path_str != "None" else None

        entry: dict = {
            "name": name,
            "path": str(module_path) if module_path else path_str,
            "url": url,
            "revision": revision,
        }

        if module_path and module_path.exists():
            meta = parse_module_yml(module_path)
            entry.update(meta)
            entry["name"] = entry.get("name") or name  # prefer module.yml name

        modules.append(entry)

    return modules


# ---------------------------------------------------------------------------
# Bindings directory discovery
# ---------------------------------------------------------------------------


def collect_bindings_dirs(zephyr_base: str) -> list[str]:
    """Return all DTS bindings directories from Zephyr + west modules."""
    dirs: list[str] = []

    # Zephyr's own bindings
    zb_bindings = Path(zephyr_base) / "dts" / "bindings"
    if zb_bindings.exists():
        dirs.append(str(zb_bindings))

    # Module-contributed bindings
    for mod in list_modules():
        bd = mod.get("dts_bindings_root")
        if bd and Path(bd).exists():
            dirs.append(bd)

    return dirs
