"""P1: update check failure diagnostics test.

Ensures that 'zephyr-cli update --check' provides specific,
actionable error messages for different failure modes.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
from typer.testing import CliRunner

from zephyr_cli.main import app

runner = CliRunner()


class TestUpdateCheckFailures:
    """update --check should provide distinct errors for each failure mode."""

    def test_network_unreachable(self):
        with patch("zephyr_cli.commands.update.httpx.get", side_effect=httpx.ConnectError("refused")):
            result = runner.invoke(app, ["update", "--check"])
        assert result.exit_code != 0
        data = json.loads(result.output)
        assert data["reason"] == "network_unreachable"
        assert data["next_action"] is not None

    def test_timeout(self):
        with patch(
            "zephyr_cli.commands.update.httpx.get",
            side_effect=httpx.ReadTimeout("timed out"),
        ):
            result = runner.invoke(app, ["update", "--check"])
        assert result.exit_code != 0
        data = json.loads(result.output)
        assert data["reason"] == "timeout"
        assert "try again" in data["next_action"].lower()

    def test_http_error(self):
        mock_resp = httpx.Response(503, request=httpx.Request("GET", "https://pypi.org"))
        with patch(
            "zephyr_cli.commands.update.httpx.get",
            side_effect=httpx.HTTPStatusError("err", request=mock_resp.request, response=mock_resp),
        ):
            result = runner.invoke(app, ["update", "--check"])
        assert result.exit_code != 0
        data = json.loads(result.output)
        assert "503" in data["reason"]

    def test_malformed_response(self):
        mock_resp = httpx.Response(200, json={"unexpected": "data"}, request=httpx.Request("GET", "https://pypi.org"))
        with patch("zephyr_cli.commands.update.httpx.get", return_value=mock_resp):
            result = runner.invoke(app, ["update", "--check"])
        assert result.exit_code != 0
        data = json.loads(result.output)
        assert data["reason"] == "malformed_response"
