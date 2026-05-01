"""Unit tests for west agent test, flash, and debug commands (Phase 3)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from zephyr_cli.schemas.debug import DebugResult
from zephyr_cli.schemas.flash import FlashResult
from zephyr_cli.schemas.test import TestResult, TestSummary, parse_twister_json

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_TWISTER_JSON = {
    "environment": {"zephyr_version": "3.6.0"},
    "testsuites": [
        {
            "name": "tests/kernel/common",
            "platform": "qemu_cortex_m3",
            "arch": "arm",
            "status": "passed",
            "reason": "passed",
            "execution_time": 3.14,
            "testcases": [
                {"identifier": "tests/kernel/common.bitfield", "status": "passed", "execution_time": 0.5},
                {"identifier": "tests/kernel/common.printk", "status": "passed", "execution_time": 0.3},
            ],
        },
        {
            "name": "tests/net/socket",
            "platform": "qemu_cortex_m3",
            "arch": "arm",
            "status": "failed",
            "reason": "failed",
            "execution_time": 1.0,
            "testcases": [
                {"identifier": "tests/net/socket.tcp", "status": "passed", "execution_time": 0.4},
                {"identifier": "tests/net/socket.udp", "status": "failed", "execution_time": 0.6, "log": "assertion failed"},
            ],
        },
    ],
}


def _make_build_dir(base: Path, *, with_elf: bool = True) -> Path:
    zephyr = base / "zephyr"
    zephyr.mkdir(parents=True)
    if with_elf:
        (zephyr / "zephyr.elf").touch()
    return base


def _write_runners_yaml(build_dir: Path, *, flash_runner: str | None = None, debug_runner: str | None = None) -> None:
    lines = ["# Available runners configured by board.cmake.", "runners:", "- native", ""]
    if flash_runner is not None:
        lines.extend(["# Default flash runner if --runner is not given.", f"flash-runner: {flash_runner}", ""])
    if debug_runner is not None:
        lines.extend(["# Default debug runner if --runner is not given.", f"debug-runner: {debug_runner}", ""])
    (build_dir / "zephyr" / "runners.yaml").write_text("\n".join(lines) + "\n")


def _write_openocd_runner_config(build_dir: Path, *, board_dir: Path, search_paths: list[Path]) -> None:
    runners_yaml = build_dir / "zephyr" / "runners.yaml"
    lines = runners_yaml.read_text().splitlines()
    lines.extend([
        "config:",
        f"  board_dir: {board_dir}",
        "  openocd_search:",
        *[f"    - {path}" for path in search_paths],
    ])
    runners_yaml.write_text("\n".join(lines) + "\n")


def _write_board_config(build_dir: Path, board: str) -> None:
    (build_dir / "zephyr" / ".config").write_text(f'CONFIG_BOARD="{board}"\n')


# ---------------------------------------------------------------------------
# parse_twister_json
# ---------------------------------------------------------------------------


class TestParseTwisterJson:
    def test_parses_suites(self):
        _summary, suites = parse_twister_json(SAMPLE_TWISTER_JSON)
        assert len(suites) == 2
        assert suites[0].name == "tests/kernel/common"
        assert suites[0].platform == "qemu_cortex_m3"

    def test_counts_correct(self):
        summary, _suites = parse_twister_json(SAMPLE_TWISTER_JSON)
        assert summary.passed == 3
        assert summary.failed == 1
        assert summary.total == 4
        assert summary.skipped == 0
        assert summary.error == 0

    def test_testcases_included(self):
        _, suites = parse_twister_json(SAMPLE_TWISTER_JSON)
        cases_0 = {c.identifier: c for c in suites[0].cases}
        assert "tests/kernel/common.bitfield" in cases_0
        assert cases_0["tests/kernel/common.bitfield"].status == "passed"

    def test_failed_case_has_log(self):
        _, suites = parse_twister_json(SAMPLE_TWISTER_JSON)
        cases_1 = {c.identifier: c for c in suites[1].cases}
        assert cases_1["tests/net/socket.udp"].log == "assertion failed"

    def test_empty_testsuites(self):
        summary, suites = parse_twister_json({"testsuites": []})
        assert suites == []
        assert summary.total == 0

    def test_skipped_counted(self):
        data = {
            "testsuites": [{
                "name": "t", "platform": "p",
                "testcases": [{"identifier": "t.a", "status": "skipped"}],
            }]
        }
        summary, _ = parse_twister_json(data)
        assert summary.skipped == 1
        assert summary.total == 1


# ---------------------------------------------------------------------------
# TestResult schema
# ---------------------------------------------------------------------------


class TestTestResultSchema:
    def test_roundtrip(self):
        r = TestResult(
            status="passed",
            summary=TestSummary(total=4, passed=4),
            duration_seconds=5.0,
            output_dir="/build/twister-out",
        )
        d = r.model_dump(mode="json")
        assert d["status"] == "passed"
        assert d["summary"]["passed"] == 4

    def test_output_dir_resolved(self, tmp_path):
        r = TestResult(status="passed", output_dir=str(tmp_path / "twister-out"))
        assert r.output_dir is not None
        assert Path(r.output_dir).is_absolute()

    def test_defaults_empty(self):
        r = TestResult(status="error")
        assert r.suites == []
        assert r.raw_output is None
        assert r.summary.total == 0


# ---------------------------------------------------------------------------
# FlashResult schema
# ---------------------------------------------------------------------------


class TestFlashResultSchema:
    def test_success(self):
        r = FlashResult(status="success", build_dir="/build", runner="openocd")
        assert r.status == "success"
        assert r.runner == "openocd"

    def test_error(self):
        r = FlashResult(status="error", error="no device found")
        assert r.status == "error"
        assert r.error is not None

    def test_build_dir_resolved(self, tmp_path):
        r = FlashResult(status="success", build_dir=str(tmp_path / "build"))
        assert r.build_dir is not None
        assert Path(r.build_dir).is_absolute()


# ---------------------------------------------------------------------------
# DebugResult schema
# ---------------------------------------------------------------------------


class TestDebugResultSchema:
    def test_server_mode(self):
        r = DebugResult(status="running", pid=1234, gdb_port=2331)
        assert r.status == "running"
        assert r.pid == 1234
        assert r.gdb_port == 2331

    def test_error_mode(self):
        r = DebugResult(status="error", error="west debug failed")
        assert r.status == "error"

    def test_optional_fields(self):
        r = DebugResult(status="success")
        assert r.pid is None
        assert r.rtt_port is None
        assert r.gdb_port is None


# ---------------------------------------------------------------------------
# _run_test dispatch (integration with the command handler)
# ---------------------------------------------------------------------------


class TestRunTestHandler:
    """Test _run_test via direct invocation with mocked subprocess."""

    def _make_args(self, **kwargs):
        import argparse
        ns = argparse.Namespace(
            platforms=kwargs.get("platforms", ["qemu_cortex_m3"]),
            test_dir=kwargs.get("test_dir", "."),
            outdir=kwargs.get("outdir", "twister-out"),
            build_only=kwargs.get("build_only", False),
            timeout_multiplier=kwargs.get("timeout_multiplier", 1.0),
            inline_logs=kwargs.get("inline_logs", False),
        )
        return ns

    def test_success_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ZEPHYR_BASE", "/zephyr")
        monkeypatch.setattr(
            "zephyr_cli.west_agent._preflight_python_modules",
            lambda _requirements: [],
        )

        outdir = tmp_path / "twister-out"
        outdir.mkdir()
        (outdir / "twister.json").write_text(json.dumps(SAMPLE_TWISTER_JSON))

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""

        from zephyr_cli.west_agent import AgentCommand

        cmd = AgentCommand()
        captured: list[dict] = []
        cmd._emit = lambda d, _fmt: captured.append(d)  # type: ignore[method-assign]

        args = self._make_args(outdir=str(outdir))

        with patch("zephyr_cli.west_agent.subprocess.run", return_value=mock_proc), pytest.raises(SystemExit):  # expected: sample has 1 failed case
            cmd._run_test(args, "json")

        assert len(captured) == 1
        assert captured[0]["status"] == "failed"  # one failed case in sample

    def test_west_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ZEPHYR_BASE", "/zephyr")
        monkeypatch.setattr(
            "zephyr_cli.west_agent._preflight_python_modules",
            lambda _requirements: [],
        )
        from zephyr_cli.west_agent import AgentCommand

        cmd = AgentCommand()
        captured: list[dict] = []
        cmd._emit = lambda d, _fmt: captured.append(d)  # type: ignore[method-assign]

        args = self._make_args(outdir=str(tmp_path / "twister-out"))

        with patch("zephyr_cli.west_agent.subprocess.run", side_effect=FileNotFoundError), pytest.raises(SystemExit):
            cmd._run_test(args, "json")

        assert captured[0]["reason"] == "west_not_found"

    def test_missing_zephyr_base(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ZEPHYR_BASE", raising=False)
        from zephyr_cli.west_agent import AgentCommand

        cmd = AgentCommand()
        captured: list[dict] = []
        cmd._emit = lambda d, _fmt: captured.append(d)  # type: ignore[method-assign]

        args = self._make_args(outdir=str(tmp_path / "out"))

        with pytest.raises(SystemExit):
            cmd._run_test(args, "json")

        assert captured[0]["reason"] == "ZEPHYR_BASE_not_set"

    def test_preflight_missing_python_dependencies(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ZEPHYR_BASE", "/zephyr")
        from zephyr_cli.west_agent import AgentCommand

        cmd = AgentCommand()
        captured: list[dict] = []
        cmd._emit = lambda d, _fmt: captured.append(d)  # type: ignore[method-assign]

        monkeypatch.setattr(
            "zephyr_cli.west_agent._preflight_python_modules",
            lambda _requirements: [
                {
                    "module": "psutil",
                    "package": "psutil",
                    "message": "Missing Python package: psutil",
                    "remediation": "pip install psutil",
                }
            ],
        )

        args = self._make_args(outdir=str(tmp_path / "twister-out"))

        with patch("zephyr_cli.west_agent.subprocess.run") as run_mock, pytest.raises(SystemExit):
            cmd._run_test(args, "json")

        run_mock.assert_not_called()
        assert captured[0]["reason"] == "missing_python_dependencies"
        assert captured[0]["missing_dependencies"][0]["package"] == "psutil"


# ---------------------------------------------------------------------------
# _run_flash dispatch
# ---------------------------------------------------------------------------


class TestRunFlashHandler:
    def _make_args(self, build_dir: str, **kwargs):
        import argparse
        return argparse.Namespace(
            build_dir=build_dir,
            runner=kwargs.get("runner"),
            extra_args=kwargs.get("extra_args", []),
        )

    def test_flash_success(self, tmp_path):
        bd = _make_build_dir(tmp_path)
        from zephyr_cli.west_agent import AgentCommand

        cmd = AgentCommand()
        captured: list[dict] = []
        cmd._emit = lambda d, _fmt: captured.append(d)  # type: ignore[method-assign]

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Flashing...\n"
        mock_proc.stderr = ""

        with patch("zephyr_cli.west_agent.subprocess.run", return_value=mock_proc):
            cmd._run_flash(self._make_args(str(bd)), "json")

        assert captured[0]["status"] == "success"

    def test_flash_failure(self, tmp_path):
        bd = _make_build_dir(tmp_path)
        from zephyr_cli.west_agent import AgentCommand

        cmd = AgentCommand()
        captured: list[dict] = []
        cmd._emit = lambda d, _fmt: captured.append(d)  # type: ignore[method-assign]

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = "No target found\n"

        with patch("zephyr_cli.west_agent.subprocess.run", return_value=mock_proc), pytest.raises(SystemExit):
            cmd._run_flash(self._make_args(str(bd)), "json")

        assert captured[0]["status"] == "error"

    def test_flash_with_runner(self, tmp_path):
        bd = _make_build_dir(tmp_path)
        _write_board_config(bd, "nrf52840dk/nrf52840")
        from zephyr_cli.west_agent import AgentCommand

        cmd = AgentCommand()
        cmd._emit = lambda d, _fmt: None  # type: ignore[method-assign]

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""

        captured_cmd: list[str] = []

        def fake_run(c, **kwargs):
            captured_cmd.extend(c)
            return mock_proc

        with patch("zephyr_cli.west_agent.subprocess.run", side_effect=fake_run):
            cmd._run_flash(self._make_args(str(bd), runner="jlink"), "json")

        assert "--runner" in captured_cmd
        assert "jlink" in captured_cmd

    def test_flash_populates_board_and_default_runner(self, tmp_path):
        bd = _make_build_dir(tmp_path)
        _write_board_config(bd, "esp32s3_devkitc/esp32s3/procpu")
        _write_runners_yaml(bd, flash_runner="esp32")
        from zephyr_cli.west_agent import AgentCommand

        cmd = AgentCommand()
        captured: list[dict] = []
        cmd._emit = lambda d, _fmt: captured.append(d)  # type: ignore[method-assign]

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Flashing...\n"
        mock_proc.stderr = ""

        with patch("zephyr_cli.west_agent.subprocess.run", return_value=mock_proc):
            cmd._run_flash(self._make_args(str(bd)), "json")

        assert captured[0]["board"] == "esp32s3_devkitc/esp32s3/procpu"
        assert captured[0]["runner"] == "esp32"

    def test_flash_native_runner_fails_fast_without_spawning_west(self, tmp_path):
        bd = _make_build_dir(tmp_path)
        _write_board_config(bd, "native_sim")
        _write_runners_yaml(bd, flash_runner="native")
        from zephyr_cli.west_agent import AgentCommand

        cmd = AgentCommand()
        captured: list[dict] = []
        cmd._emit = lambda d, _fmt: captured.append(d)  # type: ignore[method-assign]

        with patch("zephyr_cli.west_agent.subprocess.run") as run_mock, pytest.raises(SystemExit):
            cmd._run_flash(self._make_args(str(bd)), "json")

        run_mock.assert_not_called()
        assert captured[0]["reason"] == "native_runner_not_supported"
        assert captured[0]["board"] == "native_sim"
        assert captured[0]["runner"] == "native"


# ---------------------------------------------------------------------------
# _run_debug dispatch
# ---------------------------------------------------------------------------


class TestRunDebugHandler:
    def _make_args(self, build_dir: str, **kwargs):
        import argparse
        return argparse.Namespace(
            build_dir=build_dir,
            server=kwargs.get("server", False),
            gdb_port=kwargs.get("gdb_port"),
            rtt_port=kwargs.get("rtt_port"),
            rtt_timeout=kwargs.get("rtt_timeout", 30.0),
        )

    def test_attach_mode_success(self, tmp_path):
        bd = _make_build_dir(tmp_path)
        from zephyr_cli.west_agent import AgentCommand

        cmd = AgentCommand()
        captured: list[dict] = []
        cmd._emit = lambda d, _fmt: captured.append(d)  # type: ignore[method-assign]

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "GDB session ended\n"
        mock_proc.stderr = ""

        with patch("zephyr_cli.west_agent.subprocess.run", return_value=mock_proc):
            cmd._run_debug(self._make_args(str(bd)), "json")

        assert captured[0]["status"] == "success"

    def test_attach_mode_failure(self, tmp_path):
        bd = _make_build_dir(tmp_path)
        from zephyr_cli.west_agent import AgentCommand

        cmd = AgentCommand()
        captured: list[dict] = []
        cmd._emit = lambda d, _fmt: captured.append(d)  # type: ignore[method-assign]

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = "Could not connect to target\n"

        with patch("zephyr_cli.west_agent.subprocess.run", return_value=mock_proc), pytest.raises(SystemExit):
            cmd._run_debug(self._make_args(str(bd)), "json")

        assert captured[0]["status"] == "error"

    def test_server_mode_starts_process(self, tmp_path):
        bd = _make_build_dir(tmp_path)
        from zephyr_cli.west_agent import AgentCommand

        cmd = AgentCommand()
        captured: list[dict] = []
        cmd._emit = lambda d, _fmt: captured.append(d)  # type: ignore[method-assign]

        mock_popen = MagicMock()
        mock_popen.pid = 4242
        mock_popen.poll.return_value = None  # still running

        with patch("zephyr_cli.west_agent.subprocess.Popen", return_value=mock_popen), patch("zephyr_cli.west_agent.time.sleep"):
            cmd._run_debug(self._make_args(str(bd), server=True), "json")

        assert captured[0]["status"] == "running"
        assert captured[0]["pid"] == 4242

    def test_server_mode_exits_immediately_is_error(self, tmp_path):
        bd = _make_build_dir(tmp_path)
        from zephyr_cli.west_agent import AgentCommand

        cmd = AgentCommand()
        captured: list[dict] = []
        cmd._emit = lambda d, _fmt: captured.append(d)  # type: ignore[method-assign]

        mock_popen = MagicMock()
        mock_popen.pid = 999
        mock_popen.poll.return_value = 1  # exited immediately
        mock_popen.communicate.return_value = ("", "debugserver failed")

        with patch("zephyr_cli.west_agent.subprocess.Popen", return_value=mock_popen), patch("zephyr_cli.west_agent.time.sleep"), pytest.raises(SystemExit):
            cmd._run_debug(self._make_args(str(bd), server=True), "json")

        assert captured[0]["status"] == "error"

    def test_native_runner_fails_fast_without_spawning_west(self, tmp_path):
        bd = _make_build_dir(tmp_path)
        _write_runners_yaml(bd, debug_runner="native")
        from zephyr_cli.west_agent import AgentCommand

        cmd = AgentCommand()
        captured: list[dict] = []
        cmd._emit = lambda d, _fmt: captured.append(d)  # type: ignore[method-assign]

        with patch("zephyr_cli.west_agent.subprocess.run") as run_mock, pytest.raises(SystemExit):
            cmd._run_debug(self._make_args(str(bd)), "json")

        run_mock.assert_not_called()
        assert captured[0]["reason"] == "native_runner_not_supported"
        assert captured[0]["runner"] == "native"

    def test_missing_openocd_script_fails_fast_without_spawning_west(self, tmp_path):
        bd = _make_build_dir(tmp_path)
        _write_board_config(bd, "esp32s3_devkitc/esp32s3/procpu")
        _write_runners_yaml(bd, debug_runner="openocd")

        board_dir = tmp_path / "boards" / "espressif" / "esp32s3_devkitc"
        support_dir = board_dir / "support"
        support_dir.mkdir(parents=True)
        (support_dir / "openocd.cfg").write_text(
            "source [find interface/esp_usb_jtag.cfg]\n"
            "source [find target/esp32s3.cfg]\n"
        )

        scripts_dir = tmp_path / "openocd-scripts"
        (scripts_dir / "target").mkdir(parents=True)
        (scripts_dir / "target" / "esp32s3.cfg").write_text("# target config\n")
        _write_openocd_runner_config(bd, board_dir=board_dir, search_paths=[scripts_dir])

        from zephyr_cli.west_agent import AgentCommand

        cmd = AgentCommand()
        captured: list[dict] = []
        cmd._emit = lambda d, _fmt: captured.append(d)  # type: ignore[method-assign]

        with patch("zephyr_cli.west_agent.subprocess.run") as run_mock, pytest.raises(SystemExit):
            cmd._run_debug(self._make_args(str(bd)), "json")

        run_mock.assert_not_called()
        assert captured[0]["reason"] == "openocd_script_not_found"
        assert captured[0]["runner"] == "openocd"
        assert captured[0]["board"] == "esp32s3_devkitc/esp32s3/procpu"
        assert captured[0]["missing_scripts"] == ["interface/esp_usb_jtag.cfg"]


# ---------------------------------------------------------------------------
# Debug capability parsing
# ---------------------------------------------------------------------------


class TestDebugCapabilities:
    def test_parse_hw_breakpoints(self):
        from zephyr_cli.schemas.debug import parse_debug_output

        output = "Number of hardware breakpoints: 6\nRemote debugging using :3333\n"
        attach_status, caps = parse_debug_output(output)
        assert caps.hardware_breakpoints == 6
        assert attach_status == "connected"

    def test_parse_sw_breakpoints(self):
        from zephyr_cli.schemas.debug import parse_debug_output

        output = "software breakpoints: 4\n"
        _, caps = parse_debug_output(output)
        assert caps.software_breakpoints == 4

    def test_parse_rtt_detected(self):
        from zephyr_cli.schemas.debug import parse_debug_output

        output = "SEGGER RTT initialized\nRTT channel 0\n"
        _, caps = parse_debug_output(output)
        assert caps.rtt is True

    def test_parse_monitor_command(self):
        from zephyr_cli.schemas.debug import parse_debug_output

        output = "Use 'monitor command' to interact\n"
        _, caps = parse_debug_output(output)
        assert caps.monitor_command is True

    def test_connection_refused(self):
        from zephyr_cli.schemas.debug import parse_debug_output

        output = "Connection refused to localhost:3333\n"
        attach_status, _ = parse_debug_output(output)
        assert attach_status == "refused"

    def test_timeout_detected(self):
        from zephyr_cli.schemas.debug import parse_debug_output

        output = "Timed out waiting for target\n"
        attach_status, _ = parse_debug_output(output)
        assert attach_status == "timeout"

    def test_empty_output(self):
        from zephyr_cli.schemas.debug import parse_debug_output

        attach_status, caps = parse_debug_output("")
        assert attach_status is None
        assert caps.hardware_breakpoints is None
        assert caps.rtt is False

    def test_debug_result_has_capabilities_field(self):
        r = DebugResult(status="success")
        assert r.capabilities is not None
        assert r.capabilities.hardware_breakpoints is None
        assert r.suppressed_warnings == []

    def test_debug_result_server_started_field(self):
        r = DebugResult(status="running", server_started=True, pid=1234)
        assert r.server_started is True


# ---------------------------------------------------------------------------
# Runner warning filtering
# ---------------------------------------------------------------------------


class TestRunnerWarningFilter:
    def test_filters_esptool_warning(self):
        from zephyr_cli.west_agent import _filter_runner_output

        stderr = "WARNING: esptool v4.7 has a known issue\nFlashing...\nDone.\n"
        filtered, suppressed = _filter_runner_output(stderr)
        assert "esptool" not in filtered
        assert len(suppressed) == 1
        assert "esptool" in suppressed[0]
        assert "Flashing..." in filtered

    def test_filters_openocd_warning(self):
        from zephyr_cli.west_agent import _filter_runner_output

        stderr = "WARNING: openocd deprecated option\nTarget halted.\n"
        filtered, suppressed = _filter_runner_output(stderr)
        assert len(suppressed) == 1
        assert "Target halted." in filtered

    def test_filters_deprecated_warning(self):
        from zephyr_cli.west_agent import _filter_runner_output

        stderr = "WARNING: This option is deprecated, use --new instead\nOK\n"
        filtered, suppressed = _filter_runner_output(stderr)
        assert len(suppressed) == 1
        assert "OK" in filtered

    def test_no_false_positives(self):
        from zephyr_cli.west_agent import _filter_runner_output

        stderr = "Flashing image...\nVerify OK\n"
        filtered, suppressed = _filter_runner_output(stderr)
        assert suppressed == []
        assert "Flashing image..." in filtered

    def test_flash_result_has_suppressed_warnings(self):
        r = FlashResult(status="success", suppressed_warnings=["warning1"])
        assert r.suppressed_warnings == ["warning1"]

    def test_flash_handler_filters_warnings(self, tmp_path):
        bd = _make_build_dir(tmp_path)
        from zephyr_cli.west_agent import AgentCommand

        cmd = AgentCommand()
        captured: list[dict] = []
        cmd._emit = lambda d, _fmt: captured.append(d)  # type: ignore[method-assign]

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Flashing...\n"
        mock_proc.stderr = "WARNING: esptool noise\n"

        with patch("zephyr_cli.west_agent.subprocess.run", return_value=mock_proc):
            cmd._run_flash(
                argparse.Namespace(build_dir=str(bd), runner=None, extra_args=[]),
                "json",
            )

        assert len(captured[0]["suppressed_warnings"]) == 1
        assert "esptool" in captured[0]["suppressed_warnings"][0]


# ---------------------------------------------------------------------------
# Preflight board dependency check
# ---------------------------------------------------------------------------


class TestPreflightBoardDeps:
    def test_detects_missing_runner_tool(self, tmp_path, monkeypatch):
        from zephyr_cli.west_agent import _preflight_board_deps

        # Set up fake ZEPHYR_BASE with board dir
        zephyr_base = tmp_path / "zephyr"
        boards = zephyr_base / "boards" / "vendor" / "myboard"
        boards.mkdir(parents=True)
        (boards / "board.cmake").write_text(
            "board_set_flashrunner(openocd)\n"
        )
        monkeypatch.setenv("ZEPHYR_BASE", str(zephyr_base))
        # Ensure openocd is not on PATH
        monkeypatch.setattr("shutil.which", lambda t: None)

        warnings = _preflight_board_deps("myboard")
        assert len(warnings) == 1
        assert warnings[0]["runner"] == "openocd"
        assert warnings[0]["tool"] == "openocd"

    def test_no_warning_when_tool_exists(self, tmp_path, monkeypatch):
        from zephyr_cli.west_agent import _preflight_board_deps

        zephyr_base = tmp_path / "zephyr"
        boards = zephyr_base / "boards" / "vendor" / "myboard"
        boards.mkdir(parents=True)
        (boards / "board.cmake").write_text(
            "board_set_flashrunner(openocd)\n"
        )
        monkeypatch.setenv("ZEPHYR_BASE", str(zephyr_base))
        monkeypatch.setattr("shutil.which", lambda t: "/usr/bin/openocd")

        warnings = _preflight_board_deps("myboard")
        assert warnings == []

    def test_no_zephyr_base(self, monkeypatch):
        from zephyr_cli.west_agent import _preflight_board_deps

        monkeypatch.delenv("ZEPHYR_BASE", raising=False)
        assert _preflight_board_deps("nrf52840dk") == []

    def test_no_board(self):
        from zephyr_cli.west_agent import _preflight_board_deps

        assert _preflight_board_deps(None) == []

    def test_board_not_found(self, tmp_path, monkeypatch):
        from zephyr_cli.west_agent import _preflight_board_deps

        zephyr_base = tmp_path / "zephyr"
        (zephyr_base / "boards").mkdir(parents=True)
        monkeypatch.setenv("ZEPHYR_BASE", str(zephyr_base))
        assert _preflight_board_deps("nonexistent") == []
