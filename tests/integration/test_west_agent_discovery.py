"""P0: west agent discoverability test.

Ensures that 'west help agent' succeeds and lists expected subcommands
after zephyr-cli is properly installed with its west-commands.yml manifest.
"""

from __future__ import annotations

import os
import subprocess

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("ZEPHYR_BASE"),
    reason="Integration tests require ZEPHYR_BASE to be set.",
)


class TestWestAgentDiscoverability:
    """Ensure west agent command is visible and executable."""

    def test_west_help_agent_succeeds(self):
        result = subprocess.run(
            ["west", "help", "agent"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"'west help agent' failed (rc={result.returncode}): {result.stderr}"
        )

    def test_help_lists_subcommands(self):
        result = subprocess.run(
            ["west", "help", "agent"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        expected_subcommands = ["build", "inspect", "emulate", "test", "flash", "debug"]
        for sub in expected_subcommands:
            assert sub in result.stdout, f"Subcommand '{sub}' not found in 'west help agent' output"
