"""Integration tests for west agent inspect build-dir handling."""

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


def _inspect_json(
    workspace_root: Path,
    west_command: list[str],
    env: dict[str, str],
    args: list[str],
) -> dict:
    result = subprocess.run(
        [*west_command, *args],
        cwd=workspace_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"Command failed (rc={result.returncode}): {' '.join(args)}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    return json.loads(result.stdout)


class TestWestAgentInspectPaths:
    def test_kconfig_accepts_build_root_and_zephyr_subdir(
        self,
        west_workspace_root: Path,
        west_command: list[str],
        west_test_env: dict[str, str],
        native_sim_debug_build: dict,
    ):
        build_dir = native_sim_debug_build["build_dir"]

        root_data = _inspect_json(
            west_workspace_root,
            west_command,
            west_test_env,
            [
                "agent",
                "inspect",
                "kconfig",
                "--build-dir",
                str(build_dir),
                "--symbol",
                "CONFIG_LOG",
            ],
        )
        zephyr_data = _inspect_json(
            west_workspace_root,
            west_command,
            west_test_env,
            [
                "agent",
                "inspect",
                "kconfig",
                "--build-dir",
                str(build_dir / "zephyr"),
                "--symbol",
                "CONFIG_LOG",
            ],
        )

        assert root_data["status"] == "ok"
        assert zephyr_data["status"] == "ok"
        assert root_data["build_dir"] == str(build_dir)
        assert zephyr_data["build_dir"] == str(build_dir)
        assert root_data["symbol"]["symbol"] == "CONFIG_LOG"
        assert zephyr_data["symbol"]["symbol"] == "CONFIG_LOG"

    def test_dts_accepts_build_root_and_zephyr_subdir(
        self,
        west_workspace_root: Path,
        west_command: list[str],
        west_test_env: dict[str, str],
        native_sim_build: dict,
    ):
        build_dir = native_sim_build["build_dir"]

        root_data = _inspect_json(
            west_workspace_root,
            west_command,
            west_test_env,
            [
                "agent",
                "inspect",
                "dts",
                "--build-dir",
                str(build_dir),
                "--chosen",
            ],
        )
        zephyr_data = _inspect_json(
            west_workspace_root,
            west_command,
            west_test_env,
            [
                "agent",
                "inspect",
                "dts",
                "--build-dir",
                str(build_dir / "zephyr"),
                "--chosen",
            ],
        )

        assert root_data["status"] == "ok"
        assert zephyr_data["status"] == "ok"
        assert root_data["build_dir"] == str(build_dir)
        assert zephyr_data["build_dir"] == str(build_dir)
        assert "zephyr,console" in root_data["chosen"]
        assert root_data["chosen"] == zephyr_data["chosen"]