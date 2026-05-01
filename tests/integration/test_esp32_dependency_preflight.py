"""Integration tests for board-family dependency preflight (Item 5)."""

from __future__ import annotations


class TestBoardDependencyPreflight:
    """Verify _preflight_board_deps resolves boards and checks tools."""

    def test_esp32_board_with_esptool(self, tmp_path, monkeypatch):
        """ESP32 board.cmake references esptool runner; verify tool check."""
        from zephyr_cli.west_agent import _preflight_board_deps

        zephyr_base = tmp_path / "zephyr"
        board_dir = zephyr_base / "boards" / "espressif" / "esp32s3_devkitc"
        board_dir.mkdir(parents=True)
        (board_dir / "board.cmake").write_text(
            "board_set_flashrunner(esp32)\n"
            "board_set_debugrunner(openocd)\n"
        )
        monkeypatch.setenv("ZEPHYR_BASE", str(zephyr_base))
        monkeypatch.setattr("shutil.which", lambda t: None)

        warnings = _preflight_board_deps("esp32s3_devkitc")
        assert len(warnings) == 2
        runners = {w["runner"] for w in warnings}
        assert "esp32" in runners
        assert "openocd" in runners

    def test_nrf_board_with_nrfjprog(self, tmp_path, monkeypatch):
        """nRF board using nrfjprog flash runner."""
        from zephyr_cli.west_agent import _preflight_board_deps

        zephyr_base = tmp_path / "zephyr"
        board_dir = zephyr_base / "boards" / "nordic" / "nrf52840dk"
        board_dir.mkdir(parents=True)
        (board_dir / "board.cmake").write_text(
            "board_set_flashrunner(nrfjprog)\n"
        )
        monkeypatch.setenv("ZEPHYR_BASE", str(zephyr_base))

        # nrfjprog not installed
        monkeypatch.setattr("shutil.which", lambda t: None)
        warnings = _preflight_board_deps("nrf52840dk")
        assert len(warnings) == 1
        assert warnings[0]["tool"] == "nrfjprog"
        assert "remediation" in warnings[0]

    def test_board_with_qualifier_stripped(self, tmp_path, monkeypatch):
        """Board identifiers like 'nrf52840dk/nrf52840' strip the qualifier."""
        from zephyr_cli.west_agent import _preflight_board_deps

        zephyr_base = tmp_path / "zephyr"
        board_dir = zephyr_base / "boards" / "nordic" / "nrf52840dk"
        board_dir.mkdir(parents=True)
        (board_dir / "board.cmake").write_text(
            "board_set_flashrunner(jlink)\n"
        )
        monkeypatch.setenv("ZEPHYR_BASE", str(zephyr_base))
        monkeypatch.setattr("shutil.which", lambda t: "/usr/bin/JLinkExe")

        warnings = _preflight_board_deps("nrf52840dk/nrf52840")
        assert warnings == []

    def test_missing_package_in_build_output(self):
        """parse_build_output catches ModuleNotFoundError from build stderr."""
        from zephyr_cli.schemas.build import parse_build_output

        stderr = (
            "Traceback (most recent call last):\n"
            "  File \"/zephyr/scripts/west_commands/runners/esp32.py\", line 7\n"
            "ModuleNotFoundError: No module named 'esptool'\n"
        )
        errors, _ = parse_build_output(stderr)
        pkg_errors = [e for e in errors if e.error_type == "missing_package"]
        assert len(pkg_errors) == 1
        assert "esptool" in pkg_errors[0].message
        assert pkg_errors[0].remediation == "pip install esptool"
