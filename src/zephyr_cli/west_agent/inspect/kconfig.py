"""Kconfig introspection helpers using kconfiglib.

Provides symbol-to-dict conversion with correct dependency extraction,
symbol search, and a load helper.
"""

from __future__ import annotations

import contextlib
import os
import re
import sys
from pathlib import Path


_KCONFIG_EXT_VAR_RE = re.compile(r"\$\((ZEPHYR_[A-Z0-9_]+_KCONFIG)\)")
_KCONFIG_MODULE_DIR_RE = re.compile(r"(ZEPHYR_[A-Z0-9_]+_MODULE_DIR)=([^\s\)]+)")


def _load_module_dir_env(build_dir: Path) -> dict[str, str]:
    """Parse generated module-dir assignments for the current build."""
    module_dirs_file = build_dir / "Kconfig" / "kconfig_module_dirs.cmake"
    if not module_dirs_file.is_file():
        return {}

    module_dirs: dict[str, str] = {}
    for line in module_dirs_file.read_text(encoding="utf-8").splitlines():
        match = _KCONFIG_MODULE_DIR_RE.search(line)
        if match:
            module_dirs[match.group(1)] = match.group(2)
    return module_dirs


def _resolve_module_kconfig_env(zephyr_base: str, build_dir: Path) -> dict[str, str]:
    """Resolve module-specific Kconfig variables required by Kconfig.modules."""
    refs_file = build_dir / "Kconfig" / "Kconfig.modules"
    if not refs_file.is_file():
        return {}

    required_vars = set(_KCONFIG_EXT_VAR_RE.findall(refs_file.read_text(encoding="utf-8")))
    if not required_vars:
        return {}

    module_dir_env = _load_module_dir_env(build_dir)
    modules_root = Path(zephyr_base) / "modules"
    ext_kconfig_map: dict[str, str] = {}
    if modules_root.is_dir():
        for kconfig_file in modules_root.rglob("Kconfig"):
            try:
                rel_parent = kconfig_file.relative_to(modules_root).parent.as_posix()
            except ValueError:
                continue
            sanitized = re.sub(r"[^A-Za-z0-9]", "_", rel_parent).upper()
            ext_kconfig_map[f"ZEPHYR_{sanitized}_KCONFIG"] = str(kconfig_file)

    resolved: dict[str, str] = {}
    for kconfig_var in required_vars:
        module_dir_var = kconfig_var.removesuffix("_KCONFIG") + "_MODULE_DIR"
        module_dir = module_dir_env.get(module_dir_var)
        if module_dir:
            direct_kconfig = Path(module_dir) / "zephyr" / "Kconfig"
            if direct_kconfig.is_file():
                resolved[kconfig_var] = str(direct_kconfig)
                continue

        ext_kconfig = ext_kconfig_map.get(kconfig_var)
        if ext_kconfig:
            resolved[kconfig_var] = ext_kconfig

    return resolved

# ---------------------------------------------------------------------------
# Kconfig loading
# ---------------------------------------------------------------------------


def load_kconfig(zephyr_base: str, build_dir: Path, dot_config: Path):  # type: ignore[return]
    """Load a Kconfig model from *build_dir* and apply *dot_config*.

    Returns a ``kconfiglib.Kconfig`` instance.
    Raises ``ImportError`` if kconfiglib is not installed.
    Raises ``FileNotFoundError`` if the Kconfig root cannot be located.
    """
    kconfig_scripts = Path(zephyr_base) / "scripts" / "kconfig"
    if kconfig_scripts.exists() and str(kconfig_scripts) not in sys.path:
        sys.path.insert(0, str(kconfig_scripts))

    import kconfiglib  # type: ignore[import-untyped]

    # Some builds emit a Kconfig directory under the build root rather than a
    # file kconfiglib can consume directly. Fall back to the Zephyr tree root
    # in that case.
    kconfig_root = build_dir / "Kconfig"
    if not kconfig_root.is_file():
        kconfig_root = Path(zephyr_base) / "Kconfig"
    if not kconfig_root.is_file():
        raise FileNotFoundError(f"Cannot find Kconfig root at {kconfig_root}")

    module_kconfig_env = _resolve_module_kconfig_env(zephyr_base, build_dir)

    saved_env = {
        "ZEPHYR_BASE": os.environ.get("ZEPHYR_BASE"),
        "srctree": os.environ.get("srctree"),
        "KCONFIG_BINARY_DIR": os.environ.get("KCONFIG_BINARY_DIR"),
        "KCONFIG_DOC_MODE": os.environ.get("KCONFIG_DOC_MODE"),
    }
    for key in module_kconfig_env:
        saved_env[key] = os.environ.get(key)

    os.environ["ZEPHYR_BASE"] = zephyr_base
    os.environ["srctree"] = zephyr_base
    os.environ["KCONFIG_BINARY_DIR"] = str(build_dir / "Kconfig")
    os.environ["KCONFIG_DOC_MODE"] = "1"  # suppress missing-source warnings
    os.environ.update(module_kconfig_env)

    try:
        kconf = kconfiglib.Kconfig(str(kconfig_root), warn=False, warn_to_stderr=False)
        kconf.load_config(str(dot_config))
        return kconf
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# ---------------------------------------------------------------------------
# Expression walking
# ---------------------------------------------------------------------------


def _collect_dep_symbols(expr) -> list[str]:  # type: ignore[return]
    """Walk a kconfiglib boolean expression tree and collect symbol names.

    kconfiglib represents the unconditional "always true" expression as the
    special ``y`` Symbol (``expr.name == "y"``).  There is no module-level
    ``kconfiglib.T`` constant in recent versions.
    """
    try:
        import kconfiglib  # type: ignore[import-untyped]
    except ImportError:
        return []

    # Unconditional "always true" — the y Symbol or None
    if expr is None:
        return []
    if isinstance(expr, kconfiglib.Symbol) and expr.name == "y":
        return []
    if isinstance(expr, tuple):
        op = expr[0]
        if op in (kconfiglib.AND, kconfiglib.OR):
            return _collect_dep_symbols(expr[1]) + _collect_dep_symbols(expr[2])
        if op == kconfiglib.NOT:
            return _collect_dep_symbols(expr[1])
        if op in (
            kconfiglib.EQUAL,
            kconfiglib.UNEQUAL,
            kconfiglib.LESS,
            kconfiglib.LESS_EQUAL,
            kconfiglib.GREATER,
            kconfiglib.GREATER_EQUAL,
        ):
            result: list[str] = []
            for item in [expr[1], expr[2]]:
                if hasattr(item, "name") and item.name:
                    result.append(f"CONFIG_{item.name}")
            return result
        if hasattr(expr[0], "name") and expr[0].name:
            return [f"CONFIG_{expr[0].name}"]
    if hasattr(expr, "name") and getattr(expr, "name", None):
        return [f"CONFIG_{expr.name}"]  # type: ignore[union-attr]
    return []


# ---------------------------------------------------------------------------
# Symbol serialisation
# ---------------------------------------------------------------------------


def symbol_to_dict(sym) -> dict:  # type: ignore[return]
    """Convert a kconfiglib Symbol to a serialisable dict.

    Improvements over the Phase 0 version:
    - Correct dependency extraction via expression tree walker
    - Human-readable ``deps_expr`` string (e.g. "CONFIG_A && !CONFIG_B")
    - ``help`` text from the first Kconfig node
    - ``default`` value
    - ``choices`` for CHOICE symbols
    """
    try:
        import kconfiglib  # type: ignore[import-untyped]
    except ImportError:
        return {}

    type_map = {
        kconfiglib.BOOL: "bool",
        kconfiglib.INT: "int",
        kconfiglib.HEX: "hex",
        kconfiglib.STRING: "string",
        kconfiglib.TRISTATE: "tristate",
        kconfiglib.UNKNOWN: "unknown",
    }

    nodes = getattr(sym, "nodes", [])
    location: str | None = None
    prompt: str | None = None
    help_text: str | None = None

    if nodes:
        n = nodes[0]
        with contextlib.suppress(AttributeError):
            location = f"{n.filename}:{n.linenr}"
        p = getattr(n, "prompt", None)
        if p:
            prompt = p[0]
        h = getattr(n, "help", None)
        if h:
            help_text = h.strip()

    direct_dep = getattr(sym, "direct_dep", None)
    deps_expr = ""
    dep_symbols: list[str] = []
    if direct_dep is not None:
        try:
            deps_expr = kconfiglib.expr_str(direct_dep)
            dep_symbols = list(dict.fromkeys(_collect_dep_symbols(direct_dep)))
        except Exception:
            pass

    # Default values (first defaults that is reachable)
    defaults: list[str] = []
    for default_entry in getattr(sym, "defaults", []):
        if not default_entry:
            continue
        dflt = default_entry[0]
        with contextlib.suppress(Exception):
            defaults.append(kconfiglib.expr_str(dflt))

    return {
        "symbol": f"CONFIG_{sym.name}",
        "value": sym.str_value,
        "type": type_map.get(getattr(sym, "orig_type", kconfiglib.UNKNOWN), "unknown"),
        "prompt": prompt,
        "help": help_text,
        "location": location,
        "defaults": defaults,
        "deps_expr": deps_expr if deps_expr not in ("y", "") else None,
        "direct_dep_symbols": dep_symbols,
    }


# ---------------------------------------------------------------------------
# Symbol search
# ---------------------------------------------------------------------------


def search_symbols(kconf, pattern: str, changed_only: bool = False) -> list[dict]:
    """Return symbols whose name matches *pattern* (case-insensitive regex).

    If *changed_only* is True, only symbols whose value is explicitly set
    (non-default, non-empty, non-"n") are returned.
    """
    try:
        import kconfiglib  # type: ignore[import-untyped]
    except ImportError:
        return []

    rx = re.compile(pattern, re.IGNORECASE)
    results: list[dict] = []

    for name, sym in kconf.syms.items():
        if sym.orig_type == kconfiglib.UNKNOWN:
            continue
        if not rx.search(name):
            continue
        if changed_only and sym.str_value in ("n", ""):
            continue
        results.append(symbol_to_dict(sym))

    return results


# ---------------------------------------------------------------------------
# Changed symbols dump
# ---------------------------------------------------------------------------


def changed_symbols(kconf) -> list[dict]:
    """Return all non-default / explicitly-set symbols."""
    try:
        import kconfiglib  # type: ignore[import-untyped]
    except ImportError:
        return []

    return [
        symbol_to_dict(sym)
        for sym in kconf.syms.values()
        if sym.str_value not in ("n", "")
        and getattr(sym, "orig_type", kconfiglib.UNKNOWN) != kconfiglib.UNKNOWN
    ]
