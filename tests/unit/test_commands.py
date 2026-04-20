"""Unit tests for CLI commands using typer test client."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from zephyr_cli.main import app

runner = CliRunner()


class TestVersionCommand:
    def test_version_emits_json(self):
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "zephyr_cli" in data
        assert "python" in data
        assert "platform" in data

    def test_version_contains_semver(self):
        result = runner.invoke(app, ["version"])
        data = json.loads(result.output)
        # Version should be a non-empty string
        assert len(data["zephyr_cli"]) > 0


class TestEnvCommand:
    def test_env_emits_json(self):
        result = runner.invoke(app, ["env"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        # Core keys must be present
        assert "sdk" in data
        assert "west" in data
        assert "cmake" in data
        assert "ninja" in data

    def test_env_sdk_has_available_field(self):
        result = runner.invoke(app, ["env"])
        data = json.loads(result.output)
        assert "available" in data["sdk"]

    def test_env_west_has_available_field(self):
        result = runner.invoke(app, ["env"])
        data = json.loads(result.output)
        assert "available" in data["west"]

    def test_env_installed_skills_is_list(self):
        result = runner.invoke(app, ["env"])
        data = json.loads(result.output)
        assert isinstance(data["installed_skills"], list)


class TestPlaceholderCommands:
    """Phase 1/2 commands should return not_implemented with a helpful hint."""

    def test_sdk_not_implemented(self):
        result = runner.invoke(app, ["sdk"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "not_implemented"

    def test_create_not_implemented(self):
        result = runner.invoke(app, ["create"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "not_implemented"

    def test_skills_not_implemented(self):
        result = runner.invoke(app, ["skills"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "not_implemented"

    def test_docs_not_implemented(self):
        result = runner.invoke(app, ["docs"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "not_implemented"
