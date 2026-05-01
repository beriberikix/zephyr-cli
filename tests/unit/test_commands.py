"""Unit tests for CLI commands using typer test client."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
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
        assert len(data["zephyr_cli"]) > 0

    def test_version_format_human_differs_from_json(self):
        result = runner.invoke(app, ["version", "--format", "human"])

        assert result.exit_code == 0
        assert "zephyr_cli" in result.output
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.output)


class TestEnvCommand:
    def test_env_emits_json(self):
        result = runner.invoke(app, ["env"])
        assert result.exit_code == 0
        data = json.loads(result.output)
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

    def test_env_has_west_agent_reason_field(self):
        result = runner.invoke(app, ["env"])
        data = json.loads(result.output)
        assert "west_agent_reason" in data

    def test_env_format_human_differs_from_json(self):
        result = runner.invoke(app, ["env", "--format", "human"])

        assert result.exit_code == 0
        assert "west" in result.output
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.output)

    def test_env_prefers_runtime_context_without_venv_on_path(self, monkeypatch):
        monkeypatch.setenv("PATH", "/usr/bin:/bin")

        result = runner.invoke(app, ["env"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["west"]["available"] is True
        assert Path(data["python"]["path"]).resolve() == Path(sys.executable).resolve()


class TestSubcommandsShowHelp:
    """Phase 1 sub-apps should show help (exit 0) when invoked without args."""

    def test_sdk_shows_help(self):
        result = runner.invoke(app, ["sdk", "--help"])
        assert result.exit_code == 0
        assert "install" in result.output or "list" in result.output

    def test_skills_shows_help(self):
        result = runner.invoke(app, ["skills", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output or "install" in result.output

    def test_docs_shows_help(self):
        result = runner.invoke(app, ["docs", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output or "refresh" in result.output

    def test_create_shows_help(self):
        result = runner.invoke(app, ["create", "--help"])
        assert result.exit_code == 0
        assert "topology" in result.output.lower() or "name" in result.output.lower()

    def test_update_shows_help(self):
        result = runner.invoke(app, ["update", "--help"])
        assert result.exit_code == 0
