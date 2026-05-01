"""P1: skills suggest option alias compatibility test.

Ensures that both --dts and --dts-compatible are accepted by
the skills suggest command.
"""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from zephyr_cli.main import app
from zephyr_cli.schemas.skills import SkillEntry, SkillsIndex

runner = CliRunner()

_MOCK_INDEX = SkillsIndex(
    schema_version="1",
    repo="https://github.com/example/skills",
    updated="2026-01-01T00:00:00Z",
    skills=[
        SkillEntry(
            name="test-skill",
            description="A test skill for DTS bindings.",
            keywords=["dts", "bindings"],
            path="skills/test-skill",
        ),
    ],
)


def _mock_load_index(_cfg):
    return _MOCK_INDEX


class TestSkillsSuggestOptions:
    """Both --dts and --dts-compatible should be accepted."""

    @patch("zephyr_cli.commands.skills.reg.load_index", _mock_load_index)
    def test_dts_flag_accepted(self):
        result = runner.invoke(
            app,
            ["skills", "suggest", "bindings", "--dts", "nordic,nrf-gpio"],
        )
        assert result.exit_code == 0

    @patch("zephyr_cli.commands.skills.reg.load_index", _mock_load_index)
    def test_dts_compatible_flag_accepted(self):
        result = runner.invoke(
            app,
            ["skills", "suggest", "bindings", "--dts-compatible", "nordic,nrf-gpio"],
        )
        assert result.exit_code == 0

    @patch("zephyr_cli.commands.skills.reg.load_index", _mock_load_index)
    def test_both_flags_produce_same_result(self):
        result_dts = runner.invoke(
            app,
            ["skills", "suggest", "bindings", "--dts", "nordic,nrf-gpio"],
        )
        result_compat = runner.invoke(
            app,
            ["skills", "suggest", "bindings", "--dts-compatible", "nordic,nrf-gpio"],
        )
        assert result_dts.output == result_compat.output
