"""DTS / edtlib introspection helpers.

Provides enriched node serialisation with binding metadata, register
formatting, and chosen-node extraction.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Node serialisation
# ---------------------------------------------------------------------------


def _format_reg(regs) -> list[dict]:
    """Convert an edtlib ``reg`` list to ``[{addr, size}, ...]`` dicts."""
    result: list[dict] = []
    for r in regs:
        entry: dict = {}
        addr = getattr(r, "addr", None)
        size = getattr(r, "size", None)
        if addr is not None:
            entry["addr"] = hex(addr)
        if size is not None:
            entry["size"] = hex(size)
        result.append(entry)
    return result


def _format_interrupts(irqs) -> list[dict]:
    """Convert edtlib interrupt objects to serialisable dicts."""
    result: list[dict] = []
    for irq in irqs:
        entry: dict = {}
        num = getattr(irq, "val", None)
        if num is not None:
            entry["irq"] = num
        name = getattr(irq, "name", None)
        if name:
            entry["name"] = name
        data = getattr(irq, "data", {})
        if data:
            entry["data"] = {k: (hex(v) if isinstance(v, int) else v) for k, v in data.items()}
        result.append(entry)
    return result


def node_to_dict(node) -> dict:
    """Convert an edtlib Node to a rich serialisable dict.

    Improvements over the Phase 0 version:
    - ``binding`` block: compatible, description, binding_file
    - ``reg`` formatted as ``[{addr, size}]``
    - ``interrupts`` structured list
    - Raw property values serialised safely (bytes → hex)
    """
    try:
        props: dict = {}
        for name, prop in getattr(node, "props", {}).items():
            try:
                val = prop.val
                if isinstance(val, (bytes, bytearray)):
                    val = val.hex()
                elif isinstance(val, list):
                    val = [
                        item.hex() if isinstance(item, (bytes, bytearray)) else item for item in val
                    ]
                props[name] = val
            except Exception:
                props[name] = repr(prop)

        # Binding metadata
        binding: dict | None = None
        b = getattr(node, "binding", None)
        if b is not None:
            binding = {
                "compatible": getattr(b, "compatible", None),
                "description": (getattr(b, "description", None) or "").strip() or None,
                "path": str(b.path) if getattr(b, "path", None) else None,
            }

        # Register ranges
        regs = _format_reg(getattr(node, "regs", []) or [])

        # Interrupts
        irqs = _format_interrupts(getattr(node, "interrupts", []) or [])

        # Bus info
        on_bus = getattr(node, "on_bus", None)
        bus = getattr(node, "bus", None)

        return {
            "path": getattr(node, "path", None),
            "compatible": list(getattr(node, "compats", []) or []),
            "status": getattr(node, "status", None),
            "label": getattr(node, "label", None),
            "aliases": list(getattr(node, "aliases", []) or []),
            "binding": binding,
            "reg": regs if regs else None,
            "interrupts": irqs if irqs else None,
            "on_bus": on_bus,
            "provides_bus": bus,
            "properties": props,
        }
    except Exception as exc:
        try:
            bad_path = node.path  # type: ignore[attr-defined]
        except Exception:
            bad_path = "unknown"
        return {"error": str(exc), "path": bad_path}


# ---------------------------------------------------------------------------
# Chosen nodes
# ---------------------------------------------------------------------------


def get_chosen(edt) -> dict:
    """Return the chosen node mapping as ``{alias: node_path}``."""
    chosen: dict = {}
    c = getattr(edt, "chosen_nodes", None)
    if isinstance(c, dict):
        for alias, node in c.items():
            chosen[alias] = getattr(node, "path", None)
    return chosen


# ---------------------------------------------------------------------------
# EDT loader
# ---------------------------------------------------------------------------


def load_edt(build_dir: Path, zephyr_base: str):
    """Load the EDT from ``edt.pickle`` (preferred) or raw DTS.

    Returns an edtlib ``EDT`` instance.
    Raises ``FileNotFoundError`` if neither source exists.
    Raises ``ImportError`` if edtlib cannot be located.
    """
    import pickle

    dts_scripts = Path(zephyr_base) / "scripts" / "dts"
    if dts_scripts.exists() and str(dts_scripts) not in sys.path:
        sys.path.insert(0, str(dts_scripts))
    python_devicetree = dts_scripts / "python-devicetree" / "src"
    if python_devicetree.exists() and str(python_devicetree) not in sys.path:
        sys.path.insert(0, str(python_devicetree))

    edt_pickle = build_dir / "zephyr" / "edt.pickle"
    zephyr_dts = build_dir / "zephyr" / "zephyr.dts"

    if edt_pickle.exists():
        with open(edt_pickle, "rb") as fh:
            return pickle.load(fh)

    if not zephyr_dts.exists():
        raise FileNotFoundError(
            f"Neither edt.pickle nor zephyr.dts found in {build_dir / 'zephyr'}"
        )

    try:
        import edtlib  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "edtlib not found. Set ZEPHYR_BASE or install the 'devicetree' package."
        ) from exc

    bindings_dirs = [str(Path(zephyr_base) / "dts" / "bindings")]
    return edtlib.EDT(str(zephyr_dts), bindings_dirs)
