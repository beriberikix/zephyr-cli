"""Unit tests for west_agent/inspect/modules.py (Phase 2)."""

from __future__ import annotations

from unittest.mock import patch

# ---------------------------------------------------------------------------
# parse_module_yml
# ---------------------------------------------------------------------------


class TestParseModuleYml:
    def test_returns_empty_when_no_file(self, tmp_path):
        from zephyr_cli.west_agent.inspect.modules import parse_module_yml

        result = parse_module_yml(tmp_path)
        assert result == {}

    def test_parses_full_module_yml(self, tmp_path):
        from zephyr_cli.west_agent.inspect.modules import parse_module_yml

        zephyr_dir = tmp_path / "zephyr"
        zephyr_dir.mkdir()
        (zephyr_dir / "module.yml").write_text(
            """
name: my-module
build:
  kconfig: Kconfig
  cmake: CMakeLists.txt
  settings:
    board_root: boards
    dts_root: dts
    snippet_root: snippets
    soc_root: soc
"""
        )
        result = parse_module_yml(tmp_path)
        assert result["name"] == "my-module"
        assert result["kconfig"] == str(tmp_path / "Kconfig")
        assert result["cmake"] == str(tmp_path / "CMakeLists.txt")
        assert result["board_root"] == str(tmp_path / "boards")
        assert result["dts_root"] == str(tmp_path / "dts")
        assert result["snippet_root"] == str(tmp_path / "snippets")
        assert result["soc_root"] == str(tmp_path / "soc")

    def test_parses_minimal_module_yml(self, tmp_path):
        from zephyr_cli.west_agent.inspect.modules import parse_module_yml

        zephyr_dir = tmp_path / "zephyr"
        zephyr_dir.mkdir()
        (zephyr_dir / "module.yml").write_text("name: minimal\n")
        result = parse_module_yml(tmp_path)
        assert result["name"] == "minimal"
        assert result["kconfig"] is None
        assert result["board_root"] is None

    def test_dts_bindings_root_added_when_dir_exists(self, tmp_path):
        from zephyr_cli.west_agent.inspect.modules import parse_module_yml

        zephyr_dir = tmp_path / "zephyr"
        zephyr_dir.mkdir()
        # Create the dts/bindings directory
        bindings_dir = tmp_path / "dts" / "bindings"
        bindings_dir.mkdir(parents=True)
        (zephyr_dir / "module.yml").write_text(
            "name: with-bindings\nbuild:\n  settings:\n    dts_root: dts\n"
        )
        result = parse_module_yml(tmp_path)
        assert result.get("dts_bindings_root") == str(bindings_dir)

    def test_dts_bindings_root_absent_when_dir_missing(self, tmp_path):
        from zephyr_cli.west_agent.inspect.modules import parse_module_yml

        zephyr_dir = tmp_path / "zephyr"
        zephyr_dir.mkdir()
        # dts/bindings does NOT exist
        (zephyr_dir / "module.yml").write_text(
            "name: no-bindings\nbuild:\n  settings:\n    dts_root: dts\n"
        )
        result = parse_module_yml(tmp_path)
        assert "dts_bindings_root" not in result

    def test_invalid_yaml_returns_error(self, tmp_path):
        from zephyr_cli.west_agent.inspect.modules import parse_module_yml

        zephyr_dir = tmp_path / "zephyr"
        zephyr_dir.mkdir()
        (zephyr_dir / "module.yml").write_text(": bad: yaml: {{{{")
        result = parse_module_yml(tmp_path)
        assert "error" in result


# ---------------------------------------------------------------------------
# list_modules
# ---------------------------------------------------------------------------


class TestListModules:
    def test_returns_module_list(self, tmp_path):
        from zephyr_cli.west_agent.inspect.modules import list_modules

        west_output = f"zephyr {tmp_path} https://github.com/zephyrproject-rtos/zephyr v3.6.0\n"

        # Create a minimal module.yml so parse_module_yml returns something
        zephyr_dir = tmp_path / "zephyr"
        zephyr_dir.mkdir()
        (zephyr_dir / "module.yml").write_text("name: zephyr\n")

        mock_proc = type("Proc", (), {"stdout": west_output, "returncode": 0})()
        with patch("zephyr_cli.west_agent.inspect.modules.subprocess.run", return_value=mock_proc):
            modules = list_modules()

        assert len(modules) == 1
        assert modules[0]["name"] == "zephyr"
        assert modules[0]["url"] == "https://github.com/zephyrproject-rtos/zephyr"
        assert modules[0]["revision"] == "v3.6.0"

    def test_returns_error_entry_when_west_not_found(self):

        from zephyr_cli.west_agent.inspect.modules import list_modules

        with patch(
            "zephyr_cli.west_agent.inspect.modules.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            modules = list_modules()

        assert len(modules) == 1
        assert "error" in modules[0]
        assert "west" in modules[0]["error"]

    def test_empty_west_output(self):
        from zephyr_cli.west_agent.inspect.modules import list_modules

        mock_proc = type("Proc", (), {"stdout": "", "returncode": 0})()
        with patch("zephyr_cli.west_agent.inspect.modules.subprocess.run", return_value=mock_proc):
            modules = list_modules()

        assert modules == []


# ---------------------------------------------------------------------------
# collect_bindings_dirs
# ---------------------------------------------------------------------------


class TestCollectBindingsDirs:
    def test_includes_zephyr_bindings(self, tmp_path):
        from zephyr_cli.west_agent.inspect.modules import collect_bindings_dirs

        bindings_dir = tmp_path / "dts" / "bindings"
        bindings_dir.mkdir(parents=True)

        # No modules — just Zephyr tree
        mock_proc = type("Proc", (), {"stdout": "", "returncode": 0})()
        with patch("zephyr_cli.west_agent.inspect.modules.subprocess.run", return_value=mock_proc):
            dirs = collect_bindings_dirs(str(tmp_path))

        assert str(bindings_dir) in dirs

    def test_skips_nonexistent_zephyr_bindings(self, tmp_path):
        from zephyr_cli.west_agent.inspect.modules import collect_bindings_dirs

        # dts/bindings doesn't exist in tmp_path
        mock_proc = type("Proc", (), {"stdout": "", "returncode": 0})()
        with patch("zephyr_cli.west_agent.inspect.modules.subprocess.run", return_value=mock_proc):
            dirs = collect_bindings_dirs(str(tmp_path))

        assert dirs == []

    def test_includes_module_bindings(self, tmp_path):
        from zephyr_cli.west_agent.inspect.modules import collect_bindings_dirs

        # Zephyr's bindings
        zb_bindings = tmp_path / "dts" / "bindings"
        zb_bindings.mkdir(parents=True)

        # A module with its own bindings
        mod_path = tmp_path / "modules" / "mymod"
        mod_bindings = mod_path / "dts" / "bindings"
        mod_bindings.mkdir(parents=True)
        mod_zephyr = mod_path / "zephyr"
        mod_zephyr.mkdir(parents=True)
        (mod_zephyr / "module.yml").write_text(
            "name: mymod\nbuild:\n  settings:\n    dts_root: dts\n"
        )

        west_output = f"mymod {mod_path} https://example.com/mymod main\n"
        mock_proc = type("Proc", (), {"stdout": west_output, "returncode": 0})()
        with patch("zephyr_cli.west_agent.inspect.modules.subprocess.run", return_value=mock_proc):
            dirs = collect_bindings_dirs(str(tmp_path))

        assert str(zb_bindings) in dirs
        assert str(mod_bindings) in dirs
