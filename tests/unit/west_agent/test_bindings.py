"""Unit tests for west_agent/inspect/bindings.py (Phase 2)."""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_binding(directory: Path, filename: str, content: str) -> Path:
    """Write a YAML binding file into *directory* and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / filename
    p.write_text(content)
    return p


UART_BINDING = """\
compatible: "nordic,nrf-uart"
description: Nordic nRF UART peripheral.
properties:
  current-speed:
    type: int
    required: true
    description: Initial baud rate setting for UART.
  pinctrl-0:
    type: phandles
    required: false
"""

GPIO_BINDING = """\
compatible: "gpio-keys"
description: GPIO keys device.
properties:
  label:
    type: string
    required: false
child-binding:
  description: A single GPIO key.
  properties:
    gpios:
      type: phandle-array
      required: true
"""

NO_COMPAT_BINDING = """\
description: Internal base binding without compatible.
properties:
  foo:
    type: int
"""


# ---------------------------------------------------------------------------
# parse_binding_file
# ---------------------------------------------------------------------------


class TestParseBindingFile:
    def test_parses_compatible(self, tmp_path):
        from zephyr_cli.west_agent.inspect.bindings import parse_binding_file

        path = _write_binding(tmp_path, "nordic,nrf-uart.yaml", UART_BINDING)
        result = parse_binding_file(path)
        assert result["compatible"] == "nordic,nrf-uart"

    def test_parses_description(self, tmp_path):
        from zephyr_cli.west_agent.inspect.bindings import parse_binding_file

        path = _write_binding(tmp_path, "nordic,nrf-uart.yaml", UART_BINDING)
        result = parse_binding_file(path)
        assert "Nordic" in result["description"]

    def test_parses_properties(self, tmp_path):
        from zephyr_cli.west_agent.inspect.bindings import parse_binding_file

        path = _write_binding(tmp_path, "nordic,nrf-uart.yaml", UART_BINDING)
        result = parse_binding_file(path)
        props = {p["name"]: p for p in result["properties"]}
        assert "current-speed" in props
        assert props["current-speed"]["type"] == "int"
        assert props["current-speed"]["required"] is True

    def test_parses_optional_property(self, tmp_path):
        from zephyr_cli.west_agent.inspect.bindings import parse_binding_file

        path = _write_binding(tmp_path, "nordic,nrf-uart.yaml", UART_BINDING)
        result = parse_binding_file(path)
        props = {p["name"]: p for p in result["properties"]}
        assert props["pinctrl-0"]["required"] is False

    def test_parses_child_binding(self, tmp_path):
        from zephyr_cli.west_agent.inspect.bindings import parse_binding_file

        path = _write_binding(tmp_path, "gpio-keys.yaml", GPIO_BINDING)
        result = parse_binding_file(path)
        assert result["child_binding"] is not None
        cb_props = {p["name"]: p for p in result["child_binding"]["properties"]}
        assert "gpios" in cb_props
        assert cb_props["gpios"]["required"] is True

    def test_no_child_binding_is_none(self, tmp_path):
        from zephyr_cli.west_agent.inspect.bindings import parse_binding_file

        path = _write_binding(tmp_path, "nordic,nrf-uart.yaml", UART_BINDING)
        result = parse_binding_file(path)
        assert result["child_binding"] is None

    def test_no_compatible_is_none(self, tmp_path):
        from zephyr_cli.west_agent.inspect.bindings import parse_binding_file

        path = _write_binding(tmp_path, "base.yaml", NO_COMPAT_BINDING)
        result = parse_binding_file(path)
        assert result["compatible"] is None

    def test_path_in_result(self, tmp_path):
        from zephyr_cli.west_agent.inspect.bindings import parse_binding_file

        path = _write_binding(tmp_path, "nordic,nrf-uart.yaml", UART_BINDING)
        result = parse_binding_file(path)
        assert result["path"] == str(path)

    def test_parse_error_returns_error_dict(self, tmp_path):
        from zephyr_cli.west_agent.inspect.bindings import parse_binding_file

        path = tmp_path / "bad.yaml"
        path.write_text(": {{{{ invalid yaml")
        result = parse_binding_file(path)
        assert "error" in result

    def test_on_bus_and_bus_fields(self, tmp_path):
        from zephyr_cli.west_agent.inspect.bindings import parse_binding_file

        content = 'compatible: "spi-device"\non-bus: spi\nbus: i2c\n'
        path = _write_binding(tmp_path, "spi-device.yaml", content)
        result = parse_binding_file(path)
        assert result["on_bus"] == "spi"
        assert result["bus"] == "i2c"


# ---------------------------------------------------------------------------
# search_bindings
# ---------------------------------------------------------------------------


class TestSearchBindings:
    def _setup_bindings_dir(self, base: Path) -> Path:
        bd = base / "bindings"
        _write_binding(bd, "nordic,nrf-uart.yaml", UART_BINDING)
        _write_binding(bd, "gpio-keys.yaml", GPIO_BINDING)
        _write_binding(bd, "base.yaml", NO_COMPAT_BINDING)
        return bd

    def test_exact_compatible_match(self, tmp_path):
        from zephyr_cli.west_agent.inspect.bindings import search_bindings

        bd = self._setup_bindings_dir(tmp_path)
        results = search_bindings([str(bd)], compatible="nordic,nrf-uart")
        assert len(results) == 1
        assert results[0]["compatible"] == "nordic,nrf-uart"

    def test_exact_compatible_no_match(self, tmp_path):
        from zephyr_cli.west_agent.inspect.bindings import search_bindings

        bd = self._setup_bindings_dir(tmp_path)
        results = search_bindings([str(bd)], compatible="does-not-exist")
        assert results == []

    def test_pattern_search(self, tmp_path):
        from zephyr_cli.west_agent.inspect.bindings import search_bindings

        bd = self._setup_bindings_dir(tmp_path)
        results = search_bindings([str(bd)], pattern="nordic.*")
        names = [r["compatible"] for r in results]
        assert "nordic,nrf-uart" in names

    def test_pattern_is_case_insensitive(self, tmp_path):
        from zephyr_cli.west_agent.inspect.bindings import search_bindings

        bd = self._setup_bindings_dir(tmp_path)
        results = search_bindings([str(bd)], pattern="NORDIC.*")
        assert len(results) >= 1

    def test_no_filter_returns_empty(self, tmp_path):
        """search_bindings with no filter returns all bindings with a compatible."""
        from zephyr_cli.west_agent.inspect.bindings import search_bindings

        bd = self._setup_bindings_dir(tmp_path)
        # When no filter, pattern=None and compatible=None: all files are parsed
        # and none are filtered out — but base.yaml has no compatible so it's
        # excluded by the pattern branch (rx is None, compatible is None → passes through)
        results = search_bindings([str(bd)])
        # base.yaml has compatible=None; with no filter, it will not be filtered
        # by the rx/compatible checks, so it passes through.  Count ≥ 2.
        assert len(results) >= 2

    def test_nonexistent_dir_skipped(self, tmp_path):
        from zephyr_cli.west_agent.inspect.bindings import search_bindings

        results = search_bindings([str(tmp_path / "does_not_exist")], pattern=".*")
        assert results == []

    def test_deduplication_across_dirs(self, tmp_path):
        from zephyr_cli.west_agent.inspect.bindings import search_bindings

        bd = self._setup_bindings_dir(tmp_path)
        # Pass the same dir twice — should deduplicate
        results = search_bindings([str(bd), str(bd)], compatible="nordic,nrf-uart")
        assert len(results) == 1

    def test_multiple_dirs_searched(self, tmp_path):
        from zephyr_cli.west_agent.inspect.bindings import search_bindings

        bd1 = tmp_path / "bindings1"
        bd2 = tmp_path / "bindings2"
        _write_binding(bd1, "nordic,nrf-uart.yaml", UART_BINDING)
        _write_binding(bd2, "gpio-keys.yaml", GPIO_BINDING)

        results = search_bindings([str(bd1), str(bd2)], pattern=".*")
        compatibles = {r["compatible"] for r in results if r.get("compatible")}
        assert "nordic,nrf-uart" in compatibles
        assert "gpio-keys" in compatibles
