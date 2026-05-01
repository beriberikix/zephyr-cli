"""Unit tests for west_agent/inspect/threads.py."""

from __future__ import annotations

from io import BytesIO
from types import ModuleType
from unittest.mock import patch


class _FakeSymbol:
    def __init__(self, name: str, size: int):
        self.name = name
        self._size = size

    def __getitem__(self, key: str) -> int:
        if key != "st_size":
            raise KeyError(key)
        return self._size


class _FakeSymbolTableSection:
    def __init__(self, symbols: list[_FakeSymbol]):
        self._symbols = symbols

    def iter_symbols(self):
        return iter(self._symbols)


class _FakeElfFile:
    symbols: list[_FakeSymbol] = []

    def __init__(self, _file_obj):
        pass

    def get_section_by_name(self, name: str):
        if name != ".symtab":
            return None
        return _FakeSymbolTableSection(self.symbols)


def _install_fake_pyelftools() -> dict[str, ModuleType]:
    elftools = ModuleType("elftools")
    elf = ModuleType("elftools.elf")
    elffile = ModuleType("elftools.elf.elffile")
    sections = ModuleType("elftools.elf.sections")
    elffile.ELFFile = _FakeElfFile
    sections.SymbolTableSection = _FakeSymbolTableSection
    return {
        "elftools": elftools,
        "elftools.elf": elf,
        "elftools.elf.elffile": elffile,
        "elftools.elf.sections": sections,
    }


class TestAnalyzeThreads:
    def test_detects_k_thread_define_stack_symbols(self, tmp_path):
        from zephyr_cli.west_agent.inspect.threads import analyze_threads

        elf_path = tmp_path / "zephyr.elf"
        elf_path.write_bytes(b"fake")

        _FakeElfFile.symbols = [
            _FakeSymbol("z_main_stack", 2048),
            _FakeSymbol("z_idle_stacks", 256),
            _FakeSymbol("_k_thread_stack_agent_worker_tid", 1024),
            _FakeSymbol("_k_thread_obj_agent_worker_tid", 112),
            _FakeSymbol("_k_thread_data_agent_worker_tid", 48),
        ]

        with patch.dict("sys.modules", _install_fake_pyelftools()):
            with patch("builtins.open", return_value=BytesIO(b"fake")):
                result = analyze_threads(elf_path)

        assert [thread["name"] for thread in result["threads"]] == [
            "agent_worker_tid",
            "idle",
            "main",
        ]
        assert result["total_stack_bytes"] == 2048 + 256 + 1024
        assert result["threads"][0]["stack_symbol"] == "_k_thread_stack_agent_worker_tid"