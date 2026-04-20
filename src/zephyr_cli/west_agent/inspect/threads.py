"""Thread stack allocation analysis from ELF symbols using pyelftools."""

from __future__ import annotations

import re
from pathlib import Path

# Zephyr thread stack symbol patterns
# K_THREAD_STACK_DEFINE emits: z_<name>_stack or <name>_stack
# Z_THREAD_STACK_DEFINE emits similar patterns
_STACK_SYMBOL_RE = re.compile(
    r"^(?:z_)?(?P<name>.+?)(?:_stack|_thread_stack)$"
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

                # Check known fixed thread stacks first
                friendly = _KNOWN_THREADS.get(name)
                if friendly:
                    threads.append(
                        {
                            "name": friendly,
                            "stack_symbol": name,
                            "stack_size_bytes": size,
                            "estimated_usage_bytes": None,
                        }
                    )
                    continue

                # Match generic stack symbol pattern
                m = _STACK_SYMBOL_RE.match(name)
                if m:
                    raw_name = m.group("name").lstrip("z_")
                    threads.append(
                        {
                            "name": raw_name,
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
