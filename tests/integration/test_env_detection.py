"""P0: env west detection correctness test.

Ensures that 'zephyr-cli env' reports accurate west availability
and workspace metadata when running inside a real west workspace.
"""

from __future__ import annotations

import json
import os

import pytest
from typer.testing import CliRunner

from zephyr_cli.main import app

runner = CliRunner()

pytestmark = pytest.mark.skipif(
    not os.environ.get("ZEPHYR_BASE"),
    reason="Integration tests require ZEPHYR_BASE to be set.",
)


class TestEnvWestDetection:
    """env command should report correct west availability in a workspace."""

    def test_west_available_true_in_workspace(self):
        result = runner.invoke(app, ["env", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["west"]["available"] is True

    def test_workspace_root_non_null(self):
        result = runner.invoke(app, ["env", "--format", "json"])
        data = json.loads(result.output)
        assert data["west"]["workspace_root"] is not None

    def test_west_agent_available_field_present(self):
        result = runner.invoke(app, ["env", "--format", "json"])
        data = json.loads(result.output)
        assert "west_agent_available" in data

    def test_west_agent_reason_field_present(self):
        result = runner.invoke(app, ["env", "--format", "json"])
        data = json.loads(result.output)
        assert "west_agent_reason" in data
