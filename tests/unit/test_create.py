"""Unit tests for core/create.py — project scaffolding."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from zephyr_cli.core.create import (
    create_project,
    next_steps,
    validate_board,
)
from zephyr_cli.main import app

runner = CliRunner()


class TestScaffoldT1:
    def test_creates_expected_files(self, tmp_path):
        _dest, files = create_project("myapp", "T1", tmp_path)
        assert set(files) == {"CMakeLists.txt", "prj.conf", "src/main.c", "README.rst"}

    def test_cmakelists_references_project_name(self, tmp_path):
        dest, _ = create_project("myapp", "T1", tmp_path)
        cmake = (dest / "CMakeLists.txt").read_text()
        assert "project(myapp)" in cmake
        assert "find_package(Zephyr" in cmake

    def test_main_c_contains_printk(self, tmp_path):
        dest, _ = create_project("hello", "T1", tmp_path)
        main_c = (dest / "src" / "main.c").read_text()
        assert "printk" in main_c
        assert "hello" in main_c

    def test_prj_conf_created(self, tmp_path):
        dest, _ = create_project("app", "T1", tmp_path)
        assert (dest / "prj.conf").exists()

    def test_readme_rst_created(self, tmp_path):
        dest, _ = create_project("app", "T1", tmp_path)
        assert (dest / "README.rst").exists()


class TestScaffoldT2:
    def test_creates_sysbuild_conf(self, tmp_path):
        dest, files = create_project("secured", "T2", tmp_path)
        assert "sysbuild.conf" in files
        sb = (dest / "sysbuild.conf").read_text()
        assert "MCUBOOT" in sb

    def test_files_list(self, tmp_path):
        _, files = create_project("app", "T2", tmp_path)
        assert set(files) == {"CMakeLists.txt", "prj.conf", "sysbuild.conf", "src/main.c", "README.rst"}


class TestScaffoldT3:
    def test_app_subdir_created(self, tmp_path):
        dest, _files = create_project("multi", "T3", tmp_path)
        assert (dest / "app" / "CMakeLists.txt").exists()
        assert (dest / "app" / "src" / "main.c").exists()

    def test_sysbuild_subdir_created(self, tmp_path):
        dest, _ = create_project("multi", "T3", tmp_path)
        assert (dest / "sysbuild" / "CMakeLists.txt").exists()

    def test_files_list(self, tmp_path):
        _, files = create_project("m", "T3", tmp_path)
        assert "app/CMakeLists.txt" in files
        assert "sysbuild/CMakeLists.txt" in files


class TestCreateProjectErrors:
    def test_raises_on_existing_directory(self, tmp_path):
        (tmp_path / "exists").mkdir()
        with pytest.raises(FileExistsError):
            create_project("exists", "T1", tmp_path)

    def test_raises_on_unknown_topology(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown topology"):
            create_project("app", "T99", tmp_path)

    def test_topology_case_insensitive(self, tmp_path):
        dest, _files = create_project("app", "t1", tmp_path)
        assert dest.exists()


class TestNextSteps:
    def test_t1_uses_plain_build(self):
        steps = next_steps("T1", "myapp")
        assert any("west build" in s and "--sysbuild" not in s for s in steps)

    def test_t2_uses_sysbuild(self):
        steps = next_steps("T2", "myapp")
        assert any("--sysbuild" in s for s in steps)

    def test_t3_uses_sysbuild(self):
        steps = next_steps("T3", "myapp")
        assert any("--sysbuild" in s for s in steps)


class TestValidateBoard:
    def test_valid_simple_board(self):
        warnings = validate_board("nrf52840dk")
        assert isinstance(warnings, list)

    def test_valid_two_part_board(self):
        warnings = validate_board("nrf52840dk/nrf52840")
        assert isinstance(warnings, list)

    def test_valid_three_part_board(self):
        warnings = validate_board("esp32s3_devkitc/esp32s3/procpu")
        assert isinstance(warnings, list)

    def test_rejects_four_part_board(self):
        with pytest.raises(ValueError, match="Invalid board identifier"):
            validate_board("a/b/c/d")

    def test_rejects_special_characters(self):
        with pytest.raises(ValueError, match="invalid characters"):
            validate_board("board@name")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError, match="invalid characters"):
            validate_board("not a board")

    def test_rejects_empty_token(self):
        with pytest.raises(ValueError, match="invalid characters"):
            validate_board("board/")

    def test_allows_hyphens_and_underscores(self):
        warnings = validate_board("my-board_v2")
        assert isinstance(warnings, list)

    def test_rejects_leading_hyphen(self):
        with pytest.raises(ValueError, match="invalid characters"):
            validate_board("-board")

    def test_includes_board_when_provided(self):
        steps = next_steps("T1", "myapp", board="nrf52840dk")
        assert any("nrf52840dk" in s for s in steps)


class TestCreateCommand:
    def test_create_t1_via_cli(self, tmp_path):
        result = runner.invoke(
            app, ["create", "myapp", "--output-dir", str(tmp_path), "--format", "json"]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "created"
        assert data["topology"] == "T1"
        assert len(data["files"]) > 0

    def test_create_t2_via_cli(self, tmp_path):
        result = runner.invoke(
            app, ["create", "myapp", "-t", "T2", "--output-dir", str(tmp_path), "--format", "json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["topology"] == "T2"
        assert "sysbuild.conf" in data["files"]

    def test_create_duplicate_fails(self, tmp_path):
        runner.invoke(app, ["create", "myapp", "--output-dir", str(tmp_path), "--format", "json"])
        result = runner.invoke(
            app, ["create", "myapp", "--output-dir", str(tmp_path), "--format", "json"]
        )
        assert result.exit_code == 1
