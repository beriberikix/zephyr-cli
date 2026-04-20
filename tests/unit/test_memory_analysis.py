"""Unit tests for memory analysis module."""

from __future__ import annotations

from zephyr_cli.west_agent.inspect.memory import (
    _build_region,
    _classify_sections,
    _parse_map_sections,
)


class TestParsMapSections:
    def test_returns_empty_for_missing_file(self, tmp_path):
        result = _parse_map_sections(tmp_path / "nonexistent.map")
        assert result == {}

    def test_parses_text_section(self, tmp_path):
        map_file = tmp_path / "zephyr.map"
        map_file.write_text(
            ".text           0x0000000000000000    0x10000\n"
            ".rodata         0x0000000000010000     0x4000\n"
        )
        result = _parse_map_sections(map_file)
        assert ".text" in result
        assert result[".text"] == 0x10000
        assert ".rodata" in result
        assert result[".rodata"] == 0x4000

    def test_ignores_zero_size_sections(self, tmp_path):
        map_file = tmp_path / "zephyr.map"
        map_file.write_text(".debug_info      0x0000000000000000    0x0\n")
        result = _parse_map_sections(map_file)
        assert ".debug_info" not in result


class TestClassifySections:
    def test_text_goes_to_rom(self):
        rom, ram = _classify_sections({".text": 1000})
        assert ".text" in rom
        assert ".text" not in ram

    def test_bss_goes_to_ram(self):
        rom, ram = _classify_sections({".bss": 500})
        assert ".bss" in ram
        assert ".bss" not in rom

    def test_data_goes_to_ram(self):
        _rom, ram = _classify_sections({".data": 200})
        assert ".data" in ram

    def test_noinit_goes_to_ram(self):
        _rom, ram = _classify_sections({".noinit": 100})
        assert ".noinit" in ram


class TestBuildRegion:
    def test_utilization_calculated(self):
        region = _build_region("FLASH", {".text": 8192}, total_bytes=65536)
        assert region.used_bytes == 8192
        assert region.total_bytes == 65536
        assert region.free_bytes == 65536 - 8192
        assert region.utilization_percent == round(8192 / 65536 * 100, 2)

    def test_sections_sorted_by_size(self):
        region = _build_region(
            "FLASH",
            {".rodata": 100, ".text": 5000, ".isr_vector": 300},
            total_bytes=None,
        )
        sizes = [s.bytes for s in region.sections]
        assert sizes == sorted(sizes, reverse=True)

    def test_no_total_uses_used_as_total(self):
        region = _build_region("SRAM", {".bss": 2048}, total_bytes=None)
        assert region.total_bytes == 2048
        assert region.free_bytes == 0
        assert region.utilization_percent == 100.0
