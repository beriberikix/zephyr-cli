"""Unit tests for west agent test, flash, and debug commands (Phase 3)."""

from __future__ import annotations

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
