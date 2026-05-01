"""Unit tests for west_agent/inspect/kconfig.py (Phase 2)."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _make_y_sym():
    """Return a mock that behaves like kconfiglib's unconditional 'y' symbol."""
    import kconfiglib  # type: ignore[import-untyped]
    sym = MagicMock(spec=kconfiglib.Symbol)
    sym.name = "y"
    return sym


# ---------------------------------------------------------------------------
# _collect_dep_symbols
# ---------------------------------------------------------------------------


class TestCollectDepSymbols:
    """Tests for the kconfiglib expression-tree walker."""

    def test_returns_empty_for_y_symbol(self):
        pytest.importorskip("kconfiglib")
        from zephyr_cli.west_agent.inspect.kconfig import _collect_dep_symbols

        result = _collect_dep_symbols(_make_y_sym())
        assert result == []

    def test_returns_empty_for_none(self):
        pytest.importorskip("kconfiglib")
        from zephyr_cli.west_agent.inspect.kconfig import _collect_dep_symbols

        result = _collect_dep_symbols(None)
        assert result == []

    def test_single_symbol(self):
        pytest.importorskip("kconfiglib")
        import kconfiglib  # type: ignore[import-untyped]

        from zephyr_cli.west_agent.inspect.kconfig import _collect_dep_symbols
        sym = MagicMock(spec=kconfiglib.Symbol)
        sym.name = "FOO"
        result = _collect_dep_symbols(sym)
        assert result == ["CONFIG_FOO"]

    def test_AND_expression(self):
        kconfiglib = pytest.importorskip("kconfiglib")
        from zephyr_cli.west_agent.inspect.kconfig import _collect_dep_symbols

        sym_a = MagicMock(spec=kconfiglib.Symbol)
        sym_a.name = "A"
        sym_b = MagicMock(spec=kconfiglib.Symbol)
        sym_b.name = "B"
        expr = (kconfiglib.AND, sym_a, sym_b)
        result = _collect_dep_symbols(expr)
        assert "CONFIG_A" in result
        assert "CONFIG_B" in result

    def test_OR_expression(self):
        kconfiglib = pytest.importorskip("kconfiglib")
        from zephyr_cli.west_agent.inspect.kconfig import _collect_dep_symbols

        sym_a = MagicMock(spec=kconfiglib.Symbol)
        sym_a.name = "A"
        sym_b = MagicMock(spec=kconfiglib.Symbol)
        sym_b.name = "B"
        expr = (kconfiglib.OR, sym_a, sym_b)
        result = _collect_dep_symbols(expr)
        assert "CONFIG_A" in result
        assert "CONFIG_B" in result

    def test_NOT_expression(self):
        kconfiglib = pytest.importorskip("kconfiglib")
        from zephyr_cli.west_agent.inspect.kconfig import _collect_dep_symbols

        sym = MagicMock(spec=kconfiglib.Symbol)
        sym.name = "C"
        expr = (kconfiglib.NOT, sym)
        result = _collect_dep_symbols(expr)
        assert "CONFIG_C" in result

    def test_EQUAL_expression_extracts_both_sides(self):
        kconfiglib = pytest.importorskip("kconfiglib")
        from zephyr_cli.west_agent.inspect.kconfig import _collect_dep_symbols

        sym_a = MagicMock(spec=kconfiglib.Symbol)
        sym_a.name = "A"
        sym_b = MagicMock(spec=kconfiglib.Symbol)
        sym_b.name = "B"
        expr = (kconfiglib.EQUAL, sym_a, sym_b)
        result = _collect_dep_symbols(expr)
        assert "CONFIG_A" in result
        assert "CONFIG_B" in result

    def test_nested_AND_OR(self):
        kconfiglib = pytest.importorskip("kconfiglib")
        from zephyr_cli.west_agent.inspect.kconfig import _collect_dep_symbols

        sym_a = MagicMock(spec=kconfiglib.Symbol)
        sym_a.name = "A"
        sym_b = MagicMock(spec=kconfiglib.Symbol)
        sym_b.name = "B"
        sym_c = MagicMock(spec=kconfiglib.Symbol)
        sym_c.name = "C"
        # (A && B) || C
        inner = (kconfiglib.AND, sym_a, sym_b)
        expr = (kconfiglib.OR, inner, sym_c)
        result = _collect_dep_symbols(expr)
        assert "CONFIG_A" in result
        assert "CONFIG_B" in result
        assert "CONFIG_C" in result

    def test_no_name_attribute_skipped(self):
        pytest.importorskip("kconfiglib")
        from zephyr_cli.west_agent.inspect.kconfig import _collect_dep_symbols

        # Object with no 'name' attribute — just a plain object
        result = _collect_dep_symbols(42)
        assert result == []


# ---------------------------------------------------------------------------
# symbol_to_dict
# ---------------------------------------------------------------------------


class TestSymbolToDict:
    """Tests for symbol_to_dict using mocked kconfiglib symbols."""

    def _make_sym(self, name: str, value: str, orig_type=None, nodes=None, direct_dep=None, defaults=None):
        kconfiglib = pytest.importorskip("kconfiglib")
        sym = MagicMock(spec=kconfiglib.Symbol)
        sym.name = name
        sym.str_value = value
        sym.orig_type = orig_type if orig_type is not None else kconfiglib.BOOL
        sym.nodes = nodes or []
        sym.direct_dep = direct_dep if direct_dep is not None else _make_y_sym()
        sym.defaults = defaults or []
        return sym

    def test_basic_bool_symbol(self):
        pytest.importorskip("kconfiglib")
        from zephyr_cli.west_agent.inspect.kconfig import symbol_to_dict

        sym = self._make_sym("BT", "y")
        result = symbol_to_dict(sym)
        assert result["symbol"] == "CONFIG_BT"
        assert result["value"] == "y"
        assert result["type"] == "bool"

    def test_symbol_with_node_location(self):
        pytest.importorskip("kconfiglib")
        from zephyr_cli.west_agent.inspect.kconfig import symbol_to_dict

        node = SimpleNamespace(filename="Kconfig", linenr=42, prompt=("BT", None), help="Enable Bluetooth")
        sym = self._make_sym("BT", "y", nodes=[node])
        result = symbol_to_dict(sym)
        assert result["location"] == "Kconfig:42"
        assert result["prompt"] == "BT"
        assert result["help"] == "Enable Bluetooth"

    def test_symbol_no_location(self):
        pytest.importorskip("kconfiglib")
        from zephyr_cli.west_agent.inspect.kconfig import symbol_to_dict

        sym = self._make_sym("HEADLESS", "n")
        result = symbol_to_dict(sym)
        assert result["location"] is None
        assert result["help"] is None

    def test_deps_expr_none_when_unconditional(self):
        pytest.importorskip("kconfiglib")
        from zephyr_cli.west_agent.inspect.kconfig import symbol_to_dict

        sym = self._make_sym("SIMPLE", "y")
        result = symbol_to_dict(sym)
        # y means unconditional — deps_expr should be None
        assert result["deps_expr"] is None
        assert result["direct_dep_symbols"] == []

    def test_int_symbol_type(self):
        kconfiglib = pytest.importorskip("kconfiglib")
        from zephyr_cli.west_agent.inspect.kconfig import symbol_to_dict

        sym = self._make_sym("HEAP_SIZE", "1024", orig_type=kconfiglib.INT)
        result = symbol_to_dict(sym)
        assert result["type"] == "int"

    def test_hex_symbol_type(self):
        kconfiglib = pytest.importorskip("kconfiglib")
        from zephyr_cli.west_agent.inspect.kconfig import symbol_to_dict

        sym = self._make_sym("FLASH_BASE_ADDRESS", "0x00000000", orig_type=kconfiglib.HEX)
        result = symbol_to_dict(sym)
        assert result["type"] == "hex"

    def test_string_symbol_type(self):
        kconfiglib = pytest.importorskip("kconfiglib")
        from zephyr_cli.west_agent.inspect.kconfig import symbol_to_dict

        sym = self._make_sym("BOARD", "nrf52840dk", orig_type=kconfiglib.STRING)
        result = symbol_to_dict(sym)
        assert result["type"] == "string"

    def test_defaults_accept_zephyr_three_tuple_shape(self):
        kconfiglib = pytest.importorskip("kconfiglib")
        from zephyr_cli.west_agent.inspect.kconfig import symbol_to_dict

        default_sym = MagicMock(spec=kconfiglib.Symbol)
        default_sym.name = "DEFAULT_LOG"
        sym = self._make_sym("LOG", "y", defaults=[(default_sym, "COND", None)])
        result = symbol_to_dict(sym)
        assert result["defaults"]


# ---------------------------------------------------------------------------
# search_symbols / changed_symbols
# ---------------------------------------------------------------------------


class TestSearchSymbols:
    def _make_kconf(self, syms: dict):
        """Build a minimal mock kconf object."""
        pytest.importorskip("kconfiglib")
        kconf = MagicMock()
        kconf.syms = syms
        return kconf

    def _make_sym(self, name: str, value: str, orig_type=None):
        kconfiglib = pytest.importorskip("kconfiglib")
        sym = MagicMock(spec=kconfiglib.Symbol)
        sym.name = name
        sym.str_value = value
        sym.orig_type = orig_type if orig_type is not None else kconfiglib.BOOL
        sym.nodes = []
        sym.direct_dep = _make_y_sym()
        sym.defaults = []
        return sym

    def test_search_returns_matching_symbols(self):
        pytest.importorskip("kconfiglib")
        from zephyr_cli.west_agent.inspect.kconfig import search_symbols

        syms = {
            "BT": self._make_sym("BT", "y"),
            "BT_LE": self._make_sym("BT_LE", "y"),
            "WIFI": self._make_sym("WIFI", "n"),
        }
        kconf = self._make_kconf(syms)
        results = search_symbols(kconf, "BT.*")
        names = [r["symbol"] for r in results]
        assert "CONFIG_BT" in names
        assert "CONFIG_BT_LE" in names
        assert "CONFIG_WIFI" not in names

    def test_search_is_case_insensitive(self):
        pytest.importorskip("kconfiglib")
        from zephyr_cli.west_agent.inspect.kconfig import search_symbols

        syms = {"BT_ENABLED": self._make_sym("BT_ENABLED", "y")}
        kconf = self._make_kconf(syms)
        results = search_symbols(kconf, "bt_enabled")
        assert len(results) == 1

    def test_search_changed_only_skips_n(self):
        pytest.importorskip("kconfiglib")
        from zephyr_cli.west_agent.inspect.kconfig import search_symbols

        syms = {
            "BT": self._make_sym("BT", "y"),
            "BT_HCI": self._make_sym("BT_HCI", "n"),
        }
        kconf = self._make_kconf(syms)
        results = search_symbols(kconf, "BT.*", changed_only=True)
        names = [r["symbol"] for r in results]
        assert "CONFIG_BT" in names
        assert "CONFIG_BT_HCI" not in names

    def test_changed_symbols_excludes_n_and_empty(self):
        pytest.importorskip("kconfiglib")
        from zephyr_cli.west_agent.inspect.kconfig import changed_symbols

        syms = {
            "BT": self._make_sym("BT", "y"),
            "WIFI": self._make_sym("WIFI", "n"),
            "BOARD": self._make_sym("BOARD", ""),
        }
        kconf = self._make_kconf(syms)
        results = changed_symbols(kconf)
        names = [r["symbol"] for r in results]
        assert "CONFIG_BT" in names
        assert "CONFIG_WIFI" not in names
        assert "CONFIG_BOARD" not in names


# ---------------------------------------------------------------------------
# load_kconfig
# ---------------------------------------------------------------------------


class TestLoadKconfig:
    def test_uses_zephyr_tree_root_and_build_env(self, tmp_path, monkeypatch):
        from zephyr_cli.west_agent.inspect.kconfig import load_kconfig

        zephyr_base = tmp_path / "zephyr"
        (zephyr_base / "scripts" / "kconfig").mkdir(parents=True)
        (zephyr_base / "Kconfig").write_text("mainmenu \"Zephyr\"\n")

        build_dir = tmp_path / "build"
        (build_dir / "Kconfig").mkdir(parents=True)
        dot_config = build_dir / "zephyr" / ".config"
        dot_config.parent.mkdir(parents=True)
        dot_config.write_text("CONFIG_LOG=y\n")

        calls: dict = {}

        class FakeKconfig:
            def __init__(self, filename, warn=False, warn_to_stderr=False):
                calls["filename"] = filename
                calls["env"] = {
                    "ZEPHYR_BASE": os.environ.get("ZEPHYR_BASE"),
                    "srctree": os.environ.get("srctree"),
                    "KCONFIG_BINARY_DIR": os.environ.get("KCONFIG_BINARY_DIR"),
                    "KCONFIG_DOC_MODE": os.environ.get("KCONFIG_DOC_MODE"),
                }

            def load_config(self, path):
                calls["config"] = path

        monkeypatch.setitem(sys.modules, "kconfiglib", SimpleNamespace(Kconfig=FakeKconfig))
        monkeypatch.delenv("ZEPHYR_BASE", raising=False)
        monkeypatch.delenv("srctree", raising=False)
        monkeypatch.delenv("KCONFIG_BINARY_DIR", raising=False)
        monkeypatch.delenv("KCONFIG_DOC_MODE", raising=False)

        load_kconfig(str(zephyr_base), build_dir, dot_config)

        assert calls["filename"] == str(zephyr_base / "Kconfig")
        assert calls["config"] == str(dot_config)
        assert calls["env"] == {
            "ZEPHYR_BASE": str(zephyr_base),
            "srctree": str(zephyr_base),
            "KCONFIG_BINARY_DIR": str(build_dir / "Kconfig"),
            "KCONFIG_DOC_MODE": "1",
        }
        assert os.environ.get("ZEPHYR_BASE") is None
        assert os.environ.get("srctree") is None
        assert os.environ.get("KCONFIG_BINARY_DIR") is None
        assert os.environ.get("KCONFIG_DOC_MODE") is None

