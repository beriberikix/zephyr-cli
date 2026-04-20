"""ROM/RAM memory analysis using pyelftools and linker map files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class MemorySection:
    name: str
    bytes: int
    percent_of_region: float = 0.0


@dataclass
class MemoryRegion:
    name: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    utilization_percent: float
    sections: list[MemorySection] = field(default_factory=list)


@dataclass
class MemoryResult:
    board: str | None
    elf: str
    regions: list[MemoryRegion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Map file parser
# ---------------------------------------------------------------------------

# Matches lines like:
#   .text           0x0000000000000000    0x10000 load address 0x08000000
#   .rodata         0x0000000000010000     0x4000
_SECTION_RE = re.compile(
    r"^\s*(?P<name>\.\S+)\s+"
    r"0x[0-9a-fA-F]+\s+"
    r"0x(?P<size>[0-9a-fA-F]+)"
)


def _parse_map_sections(map_path: Path) -> dict[str, int]:
    """Parse a GNU/LLVM linker map file and return {section_name: size_bytes}."""
    sections: dict[str, int] = {}
    try:
        text = map_path.read_text(errors="replace")
        for line in text.splitlines():
            m = _SECTION_RE.match(line)
            if m:
                name = m.group("name")
                size = int(m.group("size"), 16)
                if size > 0:
                    # Keep largest occurrence (sections may appear multiple times)
                    sections[name] = max(sections.get(name, 0), size)
    except OSError:
        pass
    return sections


# ---------------------------------------------------------------------------
# ELF-based analysis via pyelftools
# ---------------------------------------------------------------------------

# Zephyr section → ROM or RAM classification
_ROM_SECTIONS = {
    ".text", ".rodata", ".isr_vector", ".ARM.exidx",
    ".gnu.sgstubs", ".noinit_zephyr_last",
}
_RAM_SECTIONS = {
    ".bss", ".data", ".noinit", ".heap", ".stack",
    "._k_thread_stack_area", "._net_buf_pool_area",
}

# Fallback region sizes parsed from ELF LOAD segments (in bytes)
_KNOWN_REGION_NAMES = {
    "PT_LOAD": "FLASH",
}


def _elf_section_sizes(elf_path: Path) -> dict[str, int]:
    """Return {section_name: size_bytes} from ELF section headers."""
    from elftools.elf.elffile import ELFFile  # type: ignore[import-untyped]

    sizes: dict[str, int] = {}
    with open(elf_path, "rb") as f:
        elf = ELFFile(f)
        for section in elf.iter_sections():
            name = section.name
            size = section["sh_size"]
            if name and size > 0:
                sizes[name] = sizes.get(name, 0) + size
    return sizes


def _elf_load_segments(elf_path: Path) -> list[tuple[int, int]]:
    """Return list of (file_size, mem_size) for PT_LOAD segments."""
    from elftools.elf.elffile import ELFFile  # type: ignore[import-untyped]

    segments = []
    with open(elf_path, "rb") as f:
        elf = ELFFile(f)
        for seg in elf.iter_segments():
            if seg["p_type"] == "PT_LOAD":
                segments.append((seg["p_filesz"], seg["p_memsz"]))
    return segments


def _classify_sections(
    section_sizes: dict[str, int],
) -> tuple[dict[str, int], dict[str, int]]:
    """Split section sizes into ROM and RAM buckets using heuristics."""
    rom: dict[str, int] = {}
    ram: dict[str, int] = {}

    for name, size in section_sizes.items():
        name.split(".")[1] if name.count(".") >= 1 else name.lstrip(".")
        # Heuristics: sections with 'W' flag are typically RAM; others ROM
        if name in _RAM_SECTIONS or any(
            name.startswith(s) for s in (".bss", ".data", ".noinit", ".heap", ".stack")
        ):
            ram[name] = size
        else:
            rom[name] = size

    return rom, ram


def _build_region(
    name: str,
    section_sizes: dict[str, int],
    total_bytes: int | None,
) -> MemoryRegion:
    used = sum(section_sizes.values())
    # If we don't have a declared total, report used=total (unknown free)
    total = total_bytes if total_bytes and total_bytes >= used else used
    free = max(0, total - used)
    utilization = round(used / total * 100, 2) if total > 0 else 0.0
    sections = [
        MemorySection(
            name=k,
            bytes=v,
            percent_of_region=round(v / used * 100, 2) if used > 0 else 0.0,
        )
        for k, v in sorted(section_sizes.items(), key=lambda x: -x[1])
    ]
    return MemoryRegion(
        name=name,
        total_bytes=total,
        used_bytes=used,
        free_bytes=free,
        utilization_percent=utilization,
        sections=sections,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_memory(
    elf_path: Path,
    map_path: Path | None = None,
    detailed: bool = False,
) -> dict:
    """Analyze ROM/RAM usage from ELF and optional linker map.

    Returns a plain dict suitable for JSON serialisation.
    """
    try:
        from elftools.elf.elffile import ELFFile  # noqa: F401 - verify import
    except ImportError:
        return {
            "status": "error",
            "reason": "pyelftools_not_installed",
            "hint": "pip install pyelftools",
        }

    warnings: list[str] = []

    # Collect section sizes from ELF
    try:
        section_sizes = _elf_section_sizes(elf_path)
    except Exception as e:
        return {"status": "error", "reason": "elf_parse_failed", "message": str(e)}

    # Optionally enrich with map file data
    map_sections: dict[str, int] = {}
    if map_path:
        map_sections = _parse_map_sections(map_path)
        # Map file takes precedence for section sizes where it has data
        section_sizes.update(
            {k: v for k, v in map_sections.items() if v > 0}
        )
    else:
        warnings.append("No .map file found; section totals may be approximate.")

    rom_sections, ram_sections = _classify_sections(section_sizes)

    # Attempt to determine declared region sizes from ELF program headers
    load_segs = _elf_load_segments(elf_path)
    rom_total: int | None = sum(fs for fs, _ in load_segs) if load_segs else None
    ram_total: int | None = sum(ms - fs for fs, ms in load_segs) if load_segs else None

    regions = [
        _build_region("FLASH", rom_sections, rom_total),
        _build_region("SRAM", ram_sections, ram_total),
    ]

    # Filter empty regions
    regions = [r for r in regions if r.used_bytes > 0]

    result: dict = {
        "board": None,  # caller can inject if known
        "elf": str(elf_path),
        "regions": [
            {
                "name": r.name,
                "total_bytes": r.total_bytes,
                "used_bytes": r.used_bytes,
                "free_bytes": r.free_bytes,
                "utilization_percent": r.utilization_percent,
                "sections": (
                    [
                        {
                            "name": s.name,
                            "bytes": s.bytes,
                            "percent_of_region": s.percent_of_region,
                        }
                        for s in r.sections
                    ]
                    if detailed
                    else [
                        {"name": s.name, "bytes": s.bytes}
                        for s in r.sections
                    ]
                ),
            }
            for r in regions
        ],
    }
    if warnings:
        result["warnings"] = warnings
    return result
