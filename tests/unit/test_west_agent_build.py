"""Unit tests for west agent build command parsing and output schema."""

from __future__ import annotations

import argparse
from unittest.mock import patch

import pytest

from zephyr_cli.schemas.build import BuildStatus, locate_binaries, parse_build_output


class TestLocateBinaries:
    def test_returns_none_for_missing_files(self, tmp_path):
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        (build_dir / "zephyr").mkdir()
        binary = locate_binaries(str(build_dir))
        assert binary.elf is None
        assert binary.hex is None
        assert binary.bin is None
        assert binary.exe is None

    def test_detects_existing_elf(self, tmp_path):
        zephyr_dir = tmp_path / "build" / "zephyr"
        zephyr_dir.mkdir(parents=True)
        elf = zephyr_dir / "zephyr.elf"
        elf.touch()
        binary = locate_binaries(str(tmp_path / "build"))
        assert binary.elf == str(elf)

    def test_detects_native_sim_exe(self, tmp_path):
        zephyr_dir = tmp_path / "build" / "zephyr"
        zephyr_dir.mkdir(parents=True)
        exe = zephyr_dir / "zephyr.exe"
        exe.touch()
        binary = locate_binaries(str(tmp_path / "build"))
        assert binary.exe == str(exe)

    def test_detects_all_artifacts(self, tmp_path):
        zephyr_dir = tmp_path / "build" / "zephyr"
        zephyr_dir.mkdir(parents=True)
        for fname in ["zephyr.elf", "zephyr.hex", "zephyr.bin"]:
            (zephyr_dir / fname).touch()
        binary = locate_binaries(str(tmp_path / "build"))
        assert binary.elf is not None
        assert binary.hex is not None
        assert binary.bin is not None


class TestBuildStatus:
    def test_success_value(self):
        assert BuildStatus.SUCCESS == "success"

    def test_error_value(self):
        assert BuildStatus.ERROR == "error"


class TestParseBuildOutputPythonVersion:
    def test_cmake_find_package_python3(self):
        stderr = (
            "CMake Error at cmake/modules/python.cmake:17:\n"
            '  Could NOT find Python3: Found unsuitable version "3.8.10", '
            'minimum required is "3.10" (found /usr/bin/python3)\n'
        )
        errors, _warnings = parse_build_output(stderr)
        assert len(errors) >= 1
        py_errs = [e for e in errors if e.error_type == "python_version"]
        assert len(py_errs) == 1
        assert "3.10" in py_errs[0].message
        assert py_errs[0].remediation is not None
        assert "3.10" in py_errs[0].remediation

    def test_python_version_less_than_minimum(self):
        stderr = "Python version 3.9.1 is less than minimum required version 3.10\n"
        errors, _ = parse_build_output(stderr)
        py_errs = [e for e in errors if e.error_type == "python_version"]
        assert len(py_errs) == 1
        assert "3.10" in py_errs[0].message

    def test_no_false_positive_on_normal_cmake(self):
        stderr = "CMake Error at CMakeLists.txt:5: some other error\n"
        errors, _ = parse_build_output(stderr)
        assert all(e.error_type != "python_version" for e in errors)


class TestParseBuildOutputMissingPackage:
    def test_no_module_named(self):
        stderr = "  No module named 'elftools'\n"
        errors, _ = parse_build_output(stderr)
        pkg_errs = [e for e in errors if e.error_type == "missing_package"]
        assert len(pkg_errs) == 1
        assert "elftools" in pkg_errs[0].message
        assert pkg_errs[0].remediation == "pip install elftools"

    def test_module_not_found_error(self):
        stderr = "ModuleNotFoundError: No module named 'intelhex'\n"
        errors, _ = parse_build_output(stderr)
        pkg_errs = [e for e in errors if e.error_type == "missing_package"]
        assert len(pkg_errs) == 1
        assert "intelhex" in pkg_errs[0].message

    def test_import_error(self):
        stderr = "ImportError: cannot import name 'foo' from 'bar'\n"
        errors, _ = parse_build_output(stderr)
        pkg_errs = [e for e in errors if e.error_type == "missing_package"]
        assert len(pkg_errs) == 1


class TestParseBuildOutputRemediation:
    def test_remediation_field_on_build_error(self):
        from zephyr_cli.schemas.build import BuildError

        e = BuildError(message="test", remediation="do this")
        assert e.remediation == "do this"

    def test_remediation_defaults_none(self):
        from zephyr_cli.schemas.build import BuildError

        e = BuildError(message="test")
        assert e.remediation is None


class TestRunBuildHandler:
    def test_preflight_missing_python_dependencies(self, tmp_path, monkeypatch):
        source_dir = tmp_path / "app"
        source_dir.mkdir()

        from zephyr_cli.west_agent import AgentCommand

        cmd = AgentCommand()
        captured: list[dict] = []
        cmd._emit = lambda d, _fmt: captured.append(d)  # type: ignore[method-assign]

        monkeypatch.setattr(
            "zephyr_cli.west_agent._preflight_python_modules",
            lambda _requirements: [
                {
                    "module": "jsonschema",
                    "package": "jsonschema",
                    "message": "Missing Python package: jsonschema",
                    "remediation": "pip install jsonschema",
                }
            ],
        )

        args = argparse.Namespace(
            board="qemu_cortex_m3",
            build_dir=str(tmp_path / "build"),
            pristine=False,
            extra_conf=None,
            source_dir=str(source_dir),
        )

        with patch("zephyr_cli.west_agent.subprocess.run") as run_mock, pytest.raises(SystemExit):
            cmd._run_build(args, "json")

        run_mock.assert_not_called()
        assert captured[0]["status"] == "error"
        assert captured[0]["errors"][0]["error_type"] == "missing_package"
        assert "jsonschema" in captured[0]["raw_stderr"]
