"""Thread stack allocation analysis from ELF symbols using pyelftools."""

from __future__ import annotations

import re
from pathlib import Path

# Zephyr thread stack symbol patterns.
# Current Zephyr builds emit both legacy stack symbols like z_main_stack and
# static thread symbols like _k_thread_stack_<thread_name> for K_THREAD_DEFINE.
_STACK_SYMBOL_PATTERNS = (
    re.compile(r"^(?:z_)?(?P<name>.+?)(?:_stack|_thread_stack)$"),
    re.compile(r"^_k_thread_stack_(?P<name>.+)$"),
)

# Known fixed thread names
_KNOWN_THREADS: dict[str, str] = {
    "z_main_stack": "main",
    "z_idle_stack": "idle",
    "z_idle_stacks": "idle",
    "z_sys_work_q_stack": "sysworkq",
    "z_logging_thread_stack": "logging",
    "z_shell_stack": "shell",
}


def _match_thread_stack_symbol(name: str) -> str | None:
    """Return a friendly thread name for a recognized stack symbol."""
    friendly = _KNOWN_THREADS.get(name)
    if friendly is not None:
        return friendly

    for pattern in _STACK_SYMBOL_PATTERNS:
        match = pattern.match(name)
        if match:
            return match.group("name").removeprefix("z_")

    return None


def analyze_threads(elf_path: Path) -> dict:
    """Analyse static thread stack allocations from ELF symbol table.

    Returns a plain dict suitable for JSON serialisation. Runtime stack
    high-water marks are not available statically; a note is included.
    """
    try:
        from elftools.elf.elffile import ELFFile  # type: ignore[import-untyped]
        from elftools.elf.sections import SymbolTableSection  # type: ignore[import-untyped]
    except ImportError:
        return {
            "status": "error",
            "reason": "pyelftools_not_installed",
            "hint": "pip install pyelftools",
        }

    threads: list[dict] = []

    try:
        with open(elf_path, "rb") as f:
            elf = ELFFile(f)
            symtab = elf.get_section_by_name(".symtab")
            if symtab is None or not isinstance(symtab, SymbolTableSection):
                return {
                    "status": "error",
                    "reason": "no_symbol_table",
                    "hint": "Build with CONFIG_DEBUG_OPTIMIZATIONS or without stripping.",
                }

            for sym in symtab.iter_symbols():
                name: str = sym.name
                size: int = sym["st_size"]
                if size == 0:
                    continue

                friendly = _match_thread_stack_symbol(name)
                if friendly:
                    threads.append(
                        {
                            "name": friendly,
                            "stack_symbol": name,
                            "stack_size_bytes": size,
                            "estimated_usage_bytes": None,
                        }
                    )

    except Exception as e:
        return {"status": "error", "reason": "elf_parse_failed", "message": str(e)}

    # De-duplicate by symbol name
    seen: set[str] = set()
    unique = []
    for t in threads:
        if t["stack_symbol"] not in seen:
            seen.add(t["stack_symbol"])
            unique.append(t)

    return {
        "elf": str(elf_path),
        "threads": sorted(unique, key=lambda t: t["name"]),
        "total_stack_bytes": sum(t["stack_size_bytes"] for t in unique),
        "note": (
            "Stack high-water usage requires runtime RTT/coredump analysis. "
            "Static allocation sizes are shown here."
        ),
    }
