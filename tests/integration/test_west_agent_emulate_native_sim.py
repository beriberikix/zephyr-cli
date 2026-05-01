"""Integration tests for native_sim emulate timeout-cap semantics."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("ZEPHYR_BASE"),
    reason="Integration tests require ZEPHYR_BASE to be set.",
)

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestWestAgentEmulateNativeSim:
    def test_timeout_cap_with_output_is_not_treated_as_failure(
        self,
        west_command: list[str],
        west_test_env: dict[str, str],
        native_sim_build: dict,
    ):
        result = subprocess.run(
            [
                *west_command,
                "agent",
                "emulate",
                "--backend",
                "native_sim",
                "--timeout",
                "3",
                "--build-dir",
                str(native_sim_build["build_dir"]),
            ],
            cwd=REPO_ROOT,
            env=west_test_env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        data = json.loads(result.stdout)
        assert data["status"] == "session_capped"
        assert data["backend"] == "native_sim"
        assert data["build_dir"] == str(native_sim_build["build_dir"])
        assert "west agent native_sim smoke" in data["output"]
        assert data["error"] is None