"""P0: create invalid board validation test.

Ensures that 'zephyr-cli create' rejects syntactically invalid board
strings and produces actionable error output.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from zephyr_cli.main import app

runner = CliRunner()


class TestCreateBoardValidation:
    """create should reject obviously invalid board identifiers."""

    def test_rejects_board_with_spaces(self, tmp_path):
        result = runner.invoke(
            app,
            ["create", "test-proj", "--board", "not a board", "--output-dir", str(tmp_path)],
        )
        assert result.exit_code != 0
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["reason"] == "invalid_board"

    def test_rejects_board_with_special_chars(self, tmp_path):
        result = runner.invoke(
            app,
            ["create", "test-proj", "--board", "board@#!", "--output-dir", str(tmp_path)],
        )
        assert result.exit_code != 0
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["reason"] == "invalid_board"

    def test_rejects_too_many_slashes(self, tmp_path):
        result = runner.invoke(
            app,
            ["create", "test-proj", "--board", "a/b/c/d", "--output-dir", str(tmp_path)],
        )
        assert result.exit_code != 0
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_accepts_valid_simple_board(self, tmp_path):
        result = runner.invoke(
            app,
            ["create", "test-proj", "--board", "nrf52840dk", "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "created"

    def test_accepts_valid_qualified_board(self, tmp_path):
        result = runner.invoke(
            app,
            [
                "create", "test-proj2",
                "--board", "esp32s3_devkitc/esp32s3/procpu",
                "--output-dir", str(tmp_path),
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "created"

    def test_no_board_still_works(self, tmp_path):
        result = runner.invoke(
            app,
            ["create", "test-proj", "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "created"

    def test_t1_next_steps_explain_workspace_requirement(self, tmp_path):
        result = runner.invoke(
            app,
            [
                "create",
                "test-proj",
                "--board",
                "qemu_cortex_m3",
                "--output-dir",
                str(tmp_path),
            ],
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert all("west init -l ." not in step for step in data["next_steps"])
        assert "existing Zephyr workspace" in data["next_steps"][0]
        assert str(tmp_path / "test-proj") in data["next_steps"][1]

    def test_error_output_includes_board(self, tmp_path):
        result = runner.invoke(
            app,
            ["create", "test-proj", "--board", "!!!bad", "--output-dir", str(tmp_path)],
        )
        data = json.loads(result.output)
        assert data["board"] == "!!!bad"
