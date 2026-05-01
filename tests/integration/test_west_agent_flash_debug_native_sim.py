"""Integration tests for native_sim flash/debug fail-fast behavior."""

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


def _run_agent(
    west_command: list[str],
    env: dict[str, str],
    args: list[str],
) -> tuple[int, dict]:
    result = subprocess.run(
        [*west_command, *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode, json.loads(result.stdout)


class TestWestAgentNativeSimFlashDebug:
    def test_flash_fails_fast_for_native_runner(
        self,
        west_command: list[str],
        west_test_env: dict[str, str],
        native_sim_build: dict,
    ):
        rc, data = _run_agent(
            west_command,
            west_test_env,
            [
                "agent",
                "flash",
                "--build-dir",
                str(native_sim_build["build_dir"] / "zephyr"),
            ],
        )

        assert rc == 1
        assert data["status"] == "error"
        assert data["reason"] == "native_runner_not_supported"
        assert data["build_dir"] == str(native_sim_build["build_dir"])
        assert data["runner"] == "native"
        assert "west agent emulate" in data["hint"]

    def test_debug_fails_fast_for_native_runner(
        self,
        west_command: list[str],
        west_test_env: dict[str, str],
        native_sim_build: dict,
    ):
        rc, data = _run_agent(
            west_command,
            west_test_env,
            [
                "agent",
                "debug",
                "--build-dir",
                str(native_sim_build["build_dir"] / "zephyr"),
            ],
        )

        assert rc == 1
        assert data["status"] == "error"
        assert data["reason"] == "native_runner_not_supported"
        assert data["build_dir"] == str(native_sim_build["build_dir"])
        assert data["runner"] == "native"
        assert "west agent emulate" in data["hint"]