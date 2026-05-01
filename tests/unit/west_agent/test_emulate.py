"""Unit tests for Phase 3 emulation: schema, QEMU backend, native_sim, auto-detect."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from zephyr_cli.schemas.emulate import EmulateBackendName, EmulateResult, EmulateStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RUNNERS_YAML_WITH_QEMU = """\
board_dir: /zephyr/boards/arm/qemu_cortex_m3
elf_file: /build/zephyr/zephyr.elf
runners:
  qemu: {}
  openocd: {}
"""

RUNNERS_YAML_NO_QEMU = """\
board_dir: /zephyr/boards/arm/nrf52840dk
elf_file: /build/zephyr/zephyr.elf
runners:
  openocd: {}
  jlink: {}
"""


def _make_build_dir(base: Path, *, with_elf: bool = True, with_exe: bool = False, runners_yaml: str | None = None) -> Path:
    zephyr = base / "zephyr"
    zephyr.mkdir(parents=True)
    if with_elf:
        (zephyr / "zephyr.elf").touch()
    if with_exe:
        (zephyr / "zephyr.exe").write_text("#!/bin/sh\nexit 0\n")
    if runners_yaml is not None:
        (zephyr / "runners.yaml").write_text(runners_yaml)
    return base


# ---------------------------------------------------------------------------
# EmulateResult schema
# ---------------------------------------------------------------------------


class TestEmulateResultSchema:
    def test_success_roundtrip(self):
        r = EmulateResult(
            status=EmulateStatus.SUCCESS,
            backend=EmulateBackendName.QEMU,
            build_dir="/build",
            duration_seconds=1.23,
            exit_code=0,
            output="Hello Zephyr!",
        )
        d = r.model_dump(mode="json")
        assert d["status"] == "success"
        assert d["backend"] == "qemu"
        assert d["exit_code"] == 0

    def test_timeout_status(self):
        r = EmulateResult(
            status=EmulateStatus.TIMEOUT,
            backend=EmulateBackendName.NATIVE_SIM,
            error="Timed out after 30s.",
        )
        assert r.status == "timeout"
        assert r.error is not None

    def test_session_capped_status(self):
        r = EmulateResult(
            status=EmulateStatus.SESSION_CAPPED,
            backend=EmulateBackendName.NATIVE_SIM,
            output="west agent native_sim smoke\n",
        )
        assert r.status == "session_capped"
        assert r.error is None

    def test_error_status(self):
        r = EmulateResult(status=EmulateStatus.ERROR, error="west not found")
        assert r.status == "error"

    def test_build_dir_resolved(self, tmp_path):
        r = EmulateResult(status=EmulateStatus.SUCCESS, build_dir=str(tmp_path / "build"))
        # Validator resolves to absolute path; may or may not exist
        assert r.build_dir is not None
        assert Path(r.build_dir).is_absolute()

    def test_optional_fields_default_none(self):
        r = EmulateResult(status=EmulateStatus.ERROR)
        assert r.backend is None
        assert r.board is None
        assert r.build_dir is None
        assert r.duration_seconds is None
        assert r.exit_code is None
        assert r.output is None
        assert r.error is None


# ---------------------------------------------------------------------------
# QemuBackend
# ---------------------------------------------------------------------------


class TestQemuBackend:
    def test_can_run_true_when_qemu_in_runners(self, tmp_path):
        from zephyr_cli.west_agent.backends.qemu import QemuBackend

        bd = _make_build_dir(tmp_path, runners_yaml=RUNNERS_YAML_WITH_QEMU)
        assert QemuBackend().can_run(bd) is True

    def test_can_run_false_when_no_qemu_runner(self, tmp_path):
        from zephyr_cli.west_agent.backends.qemu import QemuBackend

        bd = _make_build_dir(tmp_path, runners_yaml=RUNNERS_YAML_NO_QEMU)
        assert QemuBackend().can_run(bd) is False

    def test_can_run_false_when_no_runners_yaml(self, tmp_path):
        from zephyr_cli.west_agent.backends.qemu import QemuBackend

        bd = _make_build_dir(tmp_path)  # no runners.yaml
        assert QemuBackend().can_run(bd) is False

    def test_run_success(self, tmp_path):
        from zephyr_cli.west_agent.backends.qemu import QemuBackend

        bd = _make_build_dir(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Booting Zephyr...\n"
        mock_result.stderr = ""

        with patch("zephyr_cli.west_agent.backends.qemu.subprocess.run", return_value=mock_result):
            result = QemuBackend().run(bd, timeout=10.0, extra_args=[])

        assert result.status == EmulateStatus.SUCCESS
        assert result.backend == EmulateBackendName.QEMU
        assert "Booting Zephyr" in (result.output or "")
        assert result.exit_code == 0
        assert result.error is None

    def test_run_nonzero_exit_is_error(self, tmp_path):
        from zephyr_cli.west_agent.backends.qemu import QemuBackend

        bd = _make_build_dir(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "qemu: failed to launch\n"

        with patch("zephyr_cli.west_agent.backends.qemu.subprocess.run", return_value=mock_result):
            result = QemuBackend().run(bd, timeout=10.0, extra_args=[])

        assert result.status == EmulateStatus.ERROR
        assert result.exit_code == 1
        assert result.error is not None

    def test_run_timeout(self, tmp_path):
        from zephyr_cli.west_agent.backends.qemu import QemuBackend

        bd = _make_build_dir(tmp_path)
        exc = subprocess.TimeoutExpired(cmd=["west"], timeout=5.0)
        exc.stdout = b"partial output"
        exc.stderr = b""

        with patch("zephyr_cli.west_agent.backends.qemu.subprocess.run", side_effect=exc):
            result = QemuBackend().run(bd, timeout=5.0, extra_args=[])

        assert result.status == EmulateStatus.TIMEOUT
        assert "5.0s" in (result.error or "")
        assert "partial output" in (result.output or "")

    def test_run_west_not_found(self, tmp_path):
        from zephyr_cli.west_agent.backends.qemu import QemuBackend

        bd = _make_build_dir(tmp_path)
        with patch("zephyr_cli.west_agent.backends.qemu.subprocess.run", side_effect=FileNotFoundError):
            result = QemuBackend().run(bd, timeout=10.0, extra_args=[])

        assert result.status == EmulateStatus.ERROR
        assert "west" in (result.error or "").lower()

    def test_extra_args_appended(self, tmp_path):
        from zephyr_cli.west_agent.backends.qemu import QemuBackend

        bd = _make_build_dir(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        captured_cmd: list[str] = []

        def fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            return mock_result

        with patch("zephyr_cli.west_agent.backends.qemu.subprocess.run", side_effect=fake_run):
            QemuBackend().run(bd, timeout=10.0, extra_args=["-nographic"])

        assert "-nographic" in captured_cmd

    def test_name(self):
        from zephyr_cli.west_agent.backends.qemu import QemuBackend

        assert QemuBackend().name == "qemu"


# ---------------------------------------------------------------------------
# NativeSimBackend
# ---------------------------------------------------------------------------


class TestNativeSimBackend:
    def test_can_run_true_when_exe_exists(self, tmp_path):
        from zephyr_cli.west_agent.backends.native_sim import NativeSimBackend

        bd = _make_build_dir(tmp_path, with_exe=True)
        assert NativeSimBackend().can_run(bd) is True

    def test_can_run_false_when_no_exe(self, tmp_path):
        from zephyr_cli.west_agent.backends.native_sim import NativeSimBackend

        bd = _make_build_dir(tmp_path, with_exe=False)
        assert NativeSimBackend().can_run(bd) is False

    def test_run_success(self, tmp_path):
        from zephyr_cli.west_agent.backends.native_sim import NativeSimBackend

        bd = _make_build_dir(tmp_path, with_exe=True)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "PASS - test suite passed\n"
        mock_result.stderr = ""

        with patch("zephyr_cli.west_agent.backends.native_sim.subprocess.run", return_value=mock_result):
            result = NativeSimBackend().run(bd, timeout=10.0, extra_args=[])

        assert result.status == EmulateStatus.SUCCESS
        assert result.backend == EmulateBackendName.NATIVE_SIM
        assert "PASS" in (result.output or "")

    def test_run_nonzero_exit(self, tmp_path):
        from zephyr_cli.west_agent.backends.native_sim import NativeSimBackend

        bd = _make_build_dir(tmp_path, with_exe=True)
        mock_result = MagicMock()
        mock_result.returncode = 2
        mock_result.stdout = ""
        mock_result.stderr = "FAIL - assertion at line 42\n"

        with patch("zephyr_cli.west_agent.backends.native_sim.subprocess.run", return_value=mock_result):
            result = NativeSimBackend().run(bd, timeout=10.0, extra_args=[])

        assert result.status == EmulateStatus.ERROR
        assert result.exit_code == 2

    def test_run_timeout(self, tmp_path):
        from zephyr_cli.west_agent.backends.native_sim import NativeSimBackend

        bd = _make_build_dir(tmp_path, with_exe=True)
        exc = subprocess.TimeoutExpired(cmd=["zephyr.exe"], timeout=30.0)
        exc.stdout = None
        exc.stderr = None

        with patch("zephyr_cli.west_agent.backends.native_sim.subprocess.run", side_effect=exc):
            result = NativeSimBackend().run(bd, timeout=30.0, extra_args=[])

        assert result.status == EmulateStatus.TIMEOUT
        assert "30.0s" in (result.error or "")

    def test_run_timeout_with_output_is_session_capped(self, tmp_path):
        from zephyr_cli.west_agent.backends.native_sim import NativeSimBackend

        bd = _make_build_dir(tmp_path, with_exe=True)
        exc = subprocess.TimeoutExpired(cmd=["zephyr.exe"], timeout=3.0)
        exc.stdout = "*** Booting Zephyr OS ***\nwest agent native_sim smoke\n"
        exc.stderr = None

        with patch("zephyr_cli.west_agent.backends.native_sim.subprocess.run", side_effect=exc):
            result = NativeSimBackend().run(bd, timeout=3.0, extra_args=[])

        assert result.status == EmulateStatus.SESSION_CAPPED
        assert result.error is None
        assert "west agent native_sim smoke" in (result.output or "")

    def test_run_permission_error(self, tmp_path):
        from zephyr_cli.west_agent.backends.native_sim import NativeSimBackend

        bd = _make_build_dir(tmp_path, with_exe=True)
        with patch("zephyr_cli.west_agent.backends.native_sim.subprocess.run", side_effect=PermissionError):
            result = NativeSimBackend().run(bd, timeout=10.0, extra_args=[])

        assert result.status == EmulateStatus.ERROR
        assert "chmod" in (result.error or "").lower() or "permission" in (result.error or "").lower()

    def test_run_zero_timeout_means_no_limit(self, tmp_path):
        from zephyr_cli.west_agent.backends.native_sim import NativeSimBackend

        bd = _make_build_dir(tmp_path, with_exe=True)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        captured_kwargs: dict = {}

        def fake_run(cmd, **kwargs):
            captured_kwargs.update(kwargs)
            return mock_result

        with patch("zephyr_cli.west_agent.backends.native_sim.subprocess.run", side_effect=fake_run):
            NativeSimBackend().run(bd, timeout=0.0, extra_args=[])

        assert captured_kwargs.get("timeout") is None

    def test_name(self):
        from zephyr_cli.west_agent.backends.native_sim import NativeSimBackend

        assert NativeSimBackend().name == "native_sim"


# ---------------------------------------------------------------------------
# detect_backend
# ---------------------------------------------------------------------------


class TestDetectBackend:
    def test_detects_qemu_when_runners_yaml_present(self, tmp_path):
        from zephyr_cli.west_agent.backends.detect import detect_backend

        bd = _make_build_dir(tmp_path, runners_yaml=RUNNERS_YAML_WITH_QEMU)
        backend = detect_backend(bd)
        assert backend is not None
        assert backend.name == "qemu"

    def test_detects_native_sim_when_exe_present(self, tmp_path):
        from zephyr_cli.west_agent.backends.detect import detect_backend

        bd = _make_build_dir(tmp_path, with_exe=True)
        backend = detect_backend(bd)
        assert backend is not None
        assert backend.name == "native_sim"

    def test_qemu_preferred_over_native_sim(self, tmp_path):
        """QEMU is tried before native_sim per the detection priority order."""
        from zephyr_cli.west_agent.backends.detect import detect_backend

        # Build dir has both zephyr.exe AND runners.yaml with qemu
        bd = _make_build_dir(tmp_path, with_exe=True, runners_yaml=RUNNERS_YAML_WITH_QEMU)
        backend = detect_backend(bd)
        assert backend is not None
        assert backend.name == "qemu"

    def test_returns_none_when_nothing_available(self, tmp_path):
        from zephyr_cli.west_agent.backends.detect import detect_backend

        bd = _make_build_dir(tmp_path)  # no exe, no runners.yaml
        backend = detect_backend(bd)
        assert backend is None

    def test_explicit_qemu_preference(self, tmp_path):
        from zephyr_cli.west_agent.backends.detect import detect_backend

        bd = _make_build_dir(tmp_path)
        backend = detect_backend(bd, preference="qemu")
        assert backend is not None
        assert backend.name == "qemu"

    def test_explicit_native_sim_preference(self, tmp_path):
        from zephyr_cli.west_agent.backends.detect import detect_backend

        bd = _make_build_dir(tmp_path)
        backend = detect_backend(bd, preference="native_sim")
        assert backend is not None
        assert backend.name == "native_sim"

    def test_unknown_preference_raises(self, tmp_path):
        from zephyr_cli.west_agent.backends.detect import detect_backend

        with pytest.raises(ValueError, match="Unknown backend"):
            detect_backend(tmp_path, preference="invalid_backend")
