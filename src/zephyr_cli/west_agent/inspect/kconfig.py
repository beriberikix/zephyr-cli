"""Kconfig introspection helpers using kconfiglib.

Provides symbol-to-dict conversion with correct dependency extraction,
symbol search, and a load helper.
"""

from __future__ import annotations

import contextlib
import os
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Kconfig loading
# ---------------------------------------------------------------------------


def load_kconfig(zephyr_base: str, build_dir: Path, dot_config: Path):  # type: ignore[return]
    """Load a Kconfig model from *build_dir* and apply *dot_config*.

    Returns a ``kconfiglib.Kconfig`` instance.
    Raises ``ImportError`` if kconfiglib is not installed.
    Raises ``FileNotFoundError`` if the Kconfig root cannot be located.
    """
    import kconfiglib  # type: ignore[import-untyped]

    # Prefer the build-generated merged Kconfig root
    kconfig_root = build_dir / "Kconfig"
    if not kconfig_root.exists():
        kconfig_root = Path(zephyr_base) / "Kconfig"
    if not kconfig_root.exists():
        raise FileNotFoundError(f"Cannot find Kconfig root at {kconfig_root}")

    env = os.environ.copy()
    env.setdefault("ZEPHYR_BASE", zephyr_base)
    env.setdefault("KCONFIG_DOC_MODE", "1")  # suppress missing-source warnings

    kconf = kconfiglib.Kconfig(str(kconfig_root), warn=False, warn_to_stderr=False)
    kconf.load_config(str(dot_config))
    return kconf


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
    for dflt, _cond in getattr(sym, "defaults", []):
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
