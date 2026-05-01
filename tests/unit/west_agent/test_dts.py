"""Unit tests for west_agent/inspect/dts.py (Phase 2)."""

from __future__ import annotations

import pickle
import sys
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# _format_reg
# ---------------------------------------------------------------------------


class TestFormatReg:
    def test_empty_list(self):
        from zephyr_cli.west_agent.inspect.dts import _format_reg

        assert _format_reg([]) == []

    def test_single_reg(self):
        from zephyr_cli.west_agent.inspect.dts import _format_reg

        r = SimpleNamespace(addr=0x40002000, size=0x1000)
        result = _format_reg([r])
        assert len(result) == 1
        assert result[0]["addr"] == "0x40002000"
        assert result[0]["size"] == "0x1000"

    def test_reg_without_size(self):
        from zephyr_cli.west_agent.inspect.dts import _format_reg

        r = SimpleNamespace(addr=0x00000000)  # no size attribute
        result = _format_reg([r])
        assert result[0]["addr"] == "0x0"
        assert "size" not in result[0]

    def test_multiple_regs(self):
        from zephyr_cli.west_agent.inspect.dts import _format_reg

        regs = [
            SimpleNamespace(addr=0x1000, size=0x100),
            SimpleNamespace(addr=0x2000, size=0x200),
        ]
        result = _format_reg(regs)
        assert len(result) == 2
        assert result[1]["addr"] == "0x2000"


# ---------------------------------------------------------------------------
# _format_interrupts
# ---------------------------------------------------------------------------


class TestFormatInterrupts:
    def test_empty_list(self):
        from zephyr_cli.west_agent.inspect.dts import _format_interrupts

        assert _format_interrupts([]) == []

    def test_simple_irq(self):
        from zephyr_cli.west_agent.inspect.dts import _format_interrupts

        irq = SimpleNamespace(val=3, name="uart0_irq", data={})
        result = _format_interrupts([irq])
        assert result[0]["irq"] == 3
        assert result[0]["name"] == "uart0_irq"
        assert "data" not in result[0]

    def test_irq_with_data(self):
        from zephyr_cli.west_agent.inspect.dts import _format_interrupts

        irq = SimpleNamespace(val=5, name=None, data={"priority": 2})
        result = _format_interrupts([irq])
        assert result[0]["irq"] == 5
        # Integer values in data are hex-encoded per _format_interrupts
        assert result[0]["data"]["priority"] == "0x2"

    def test_int_data_values_hex_encoded(self):
        from zephyr_cli.west_agent.inspect.dts import _format_interrupts

        irq = SimpleNamespace(val=1, name=None, data={"flags": 0xFF})
        result = _format_interrupts([irq])
        assert result[0]["data"]["flags"] == "0xff"


# ---------------------------------------------------------------------------
# node_to_dict
# ---------------------------------------------------------------------------


class TestNodeToDict:
    def _make_node(self, **kwargs):
        defaults = {
            "path": "/soc/uart@40002000",
            "compats": ["nordic,nrf-uart"],
            "status": "okay",
            "label": "uart0",
            "aliases": [],
            "binding": None,
            "regs": [],
            "interrupts": [],
            "props": {},
            "on_bus": None,
            "bus": None,
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_basic_fields_present(self):
        from zephyr_cli.west_agent.inspect.dts import node_to_dict

        node = self._make_node()
        result = node_to_dict(node)
        assert result["path"] == "/soc/uart@40002000"
        assert result["compatible"] == ["nordic,nrf-uart"]
        assert result["status"] == "okay"
        assert result["label"] == "uart0"

    def test_binding_included_when_present(self):
        from zephyr_cli.west_agent.inspect.dts import node_to_dict

        binding = SimpleNamespace(
            compatible="nordic,nrf-uart",
            description="Nordic UART",
            path="/zephyr/dts/bindings/serial/nordic,nrf-uart.yaml",
        )
        node = self._make_node(binding=binding)
        result = node_to_dict(node)
        assert result["binding"] is not None
        assert result["binding"]["compatible"] == "nordic,nrf-uart"
        assert "Nordic UART" in result["binding"]["description"]

    def test_no_binding_is_none(self):
        from zephyr_cli.west_agent.inspect.dts import node_to_dict

        node = self._make_node()
        result = node_to_dict(node)
        assert result["binding"] is None

    def test_reg_formatted(self):
        from zephyr_cli.west_agent.inspect.dts import node_to_dict

        reg = SimpleNamespace(addr=0x40002000, size=0x1000)
        node = self._make_node(regs=[reg])
        result = node_to_dict(node)
        assert result["reg"] is not None
        assert result["reg"][0]["addr"] == "0x40002000"

    def test_empty_reg_is_none(self):
        from zephyr_cli.west_agent.inspect.dts import node_to_dict

        node = self._make_node(regs=[])
        result = node_to_dict(node)
        assert result["reg"] is None

    def test_properties_bytes_serialised_as_hex(self):
        from zephyr_cli.west_agent.inspect.dts import node_to_dict

        prop = SimpleNamespace(val=b"\xde\xad\xbe\xef")
        node = self._make_node(props={"mac-address": prop})
        result = node_to_dict(node)
        assert result["properties"]["mac-address"] == "deadbeef"

    def test_error_returns_error_dict(self):
        from zephyr_cli.west_agent.inspect.dts import node_to_dict

        # A completely broken node
        class Broken:
            @property
            def path(self):
                raise RuntimeError("oops")

            @property
            def compats(self):
                raise RuntimeError("oops")

        result = node_to_dict(Broken())
        assert "error" in result

    def test_on_bus_and_provides_bus(self):
        from zephyr_cli.west_agent.inspect.dts import node_to_dict

        node = self._make_node(on_bus="i2c", bus="spi")
        result = node_to_dict(node)
        assert result["on_bus"] == "i2c"
        assert result["provides_bus"] == "spi"


# ---------------------------------------------------------------------------
# get_chosen
# ---------------------------------------------------------------------------


class TestGetChosen:
    def test_returns_path_mapping(self):
        from zephyr_cli.west_agent.inspect.dts import get_chosen

        node = SimpleNamespace(path="/soc/uart@40002000")
        edt = SimpleNamespace(chosen_nodes={"zephyr,console": node})
        result = get_chosen(edt)
        assert result["zephyr,console"] == "/soc/uart@40002000"

    def test_empty_chosen(self):
        from zephyr_cli.west_agent.inspect.dts import get_chosen

        edt = SimpleNamespace(chosen_nodes={})
        result = get_chosen(edt)
        assert result == {}

    def test_no_chosen_nodes_attr(self):
        from zephyr_cli.west_agent.inspect.dts import get_chosen

        edt = SimpleNamespace()
        result = get_chosen(edt)
        assert result == {}


# ---------------------------------------------------------------------------
# load_edt
# ---------------------------------------------------------------------------


class TestLoadEdt:
    def test_adds_zephyr_dts_scripts_before_unpickling(self, tmp_path, monkeypatch):
        from zephyr_cli.west_agent.inspect.dts import load_edt

        zephyr_base = tmp_path / "zephyr"
        dts_scripts = zephyr_base / "scripts" / "dts"
        python_devicetree = dts_scripts / "python-devicetree" / "src"
        dts_scripts.mkdir(parents=True)
        python_devicetree.mkdir(parents=True)

        build_dir = tmp_path / "build"
        edt_pickle = build_dir / "zephyr" / "edt.pickle"
        edt_pickle.parent.mkdir(parents=True)
        edt_pickle.write_bytes(b"pickle")

        sentinel = object()

        def fake_load(_fh):
            assert str(dts_scripts) in sys.path
            assert str(python_devicetree) in sys.path
            return sentinel

        monkeypatch.setattr(pickle, "load", fake_load)

        assert load_edt(build_dir, str(zephyr_base)) is sentinel

