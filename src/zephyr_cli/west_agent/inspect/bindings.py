"""DTS bindings search and inspection.

Searches binding YAML files across ZEPHYR_BASE/dts/bindings and any
module-contributed bindings directories.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Binding parsing
# ---------------------------------------------------------------------------


def parse_binding_file(path: Path) -> dict:
    """Parse a single binding YAML file and return a structured dict.

    Returns ``{"error": "...", "path": str}`` on failure.
    """
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return {"error": "pyyaml not installed", "path": str(path)}

    try:
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
    except Exception as exc:
        return {"error": f"parse error: {exc}", "path": str(path)}

    compatible = data.get("compatible")
    description = (data.get("description") or "").strip() or None
    properties: list[dict] = []

    for prop_name, prop_def in (data.get("properties") or {}).items():
        if not isinstance(prop_def, dict):
            continue
        properties.append(
            {
                "name": prop_name,
                "type": prop_def.get("type"),
                "required": bool(prop_def.get("required", False)),
                "description": (prop_def.get("description") or "").strip() or None,
                "default": prop_def.get("default"),
                "enum": prop_def.get("enum"),
                "const": prop_def.get("const"),
            }
        )

    child_binding: dict | None = None
    cb = data.get("child-binding")
    if cb and isinstance(cb, dict):
        cb_props = []
        for cp_name, cp_def in (cb.get("properties") or {}).items():
            if isinstance(cp_def, dict):
                cb_props.append(
                    {
                        "name": cp_name,
                        "type": cp_def.get("type"),
                        "required": bool(cp_def.get("required", False)),
                        "description": (cp_def.get("description") or "").strip() or None,
                    }
                )
        child_binding = {
            "description": (cb.get("description") or "").strip() or None,
            "properties": cb_props,
        }

    return {
        "compatible": compatible,
        "description": description,
        "path": str(path),
        "properties": properties,
        "child_binding": child_binding,
        "on_bus": data.get("on-bus"),
        "bus": data.get("bus"),
    }


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def search_bindings(
    bindings_dirs: list[str],
    compatible: str | None = None,
    pattern: str | None = None,
) -> list[dict]:
    """Search binding files across *bindings_dirs*.

    Filters:
    - *compatible*: exact match on the ``compatible`` field (fast path via filename)
    - *pattern*: case-insensitive regex matched against the compatible string or filename

    Returns a list of parsed binding dicts.  Does **not** recurse into
    ``include:`` directives — this is a search, not a full binding load.
    """
    rx = re.compile(pattern, re.IGNORECASE) if pattern else None

    results: list[dict] = []
    seen: set[str] = set()

    for bindings_dir in bindings_dirs:
        bd = Path(bindings_dir)
        if not bd.exists():
            continue

        for yaml_file in sorted(bd.rglob("*.yaml")):
            key = str(yaml_file.resolve())
            if key in seen:
                continue

            # Fast filename filter when searching by compatible
            if compatible:
                # Binding filenames are often <vendor>,<device>.yaml
                stem = yaml_file.stem
                if compatible not in stem and compatible not in str(yaml_file):
                    # Still need to check inside — but skip obviously unrelated files
                    # by checking the filename first for speed
                    pass  # fall through to full parse below

            binding = parse_binding_file(yaml_file)
            if "error" in binding:
                continue

            compat = binding.get("compatible")

            if compatible:
                if compat != compatible:
                    continue
            elif rx:
                target = compat or yaml_file.stem
                if not rx.search(target):
                    continue

            seen.add(key)
            results.append(binding)

    return results
