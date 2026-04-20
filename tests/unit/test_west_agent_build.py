"""Unit tests for west agent build command parsing and output schema."""

from __future__ import annotations

from zephyr_cli.schemas.build import BuildStatus, locate_binaries


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
