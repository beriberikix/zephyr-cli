"""Shared integration fixtures for west agent workflow tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from importlib import util
from pathlib import Path

import pytest


def _west_env() -> dict[str, str]:
    env = os.environ.copy()
    bin_dir = str(Path(sys.executable).resolve().parent)
    path_entries = [entry for entry in env.get("PATH", "").split(os.pathsep) if entry]
    if bin_dir not in path_entries:
        env["PATH"] = os.pathsep.join([bin_dir, *path_entries]) if path_entries else bin_dir
    return env


def _resolve_west_command(env: dict[str, str]) -> list[str]:
    if util.find_spec("west") is not None:
        return [sys.executable, "-m", "west"]

    west_path = shutil.which("west", path=env.get("PATH"))
    if west_path is not None:
        return [west_path]

    pytest.skip("Integration tests require west to be available in the active runtime or PATH.")


def _has_west_command(
    workspace_root: Path,
    west_command: list[str],
    command: str,
    env: dict[str, str],
) -> bool:
    result = subprocess.run(
        [*west_command, "help", command],
        cwd=workspace_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    combined = (result.stdout + result.stderr).lower()
    return result.returncode == 0 and f'unknown command "{command}"' not in combined


def _run_west_json(
    workspace_root: Path,
    west_command: list[str],
    env: dict[str, str],
    args: list[str],
    timeout: int = 300,
) -> dict:
    result = subprocess.run(
        [*west_command, *args],
        cwd=workspace_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, (
        f"Command failed (rc={result.returncode}): {' '.join(args)}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    return json.loads(result.stdout)


@pytest.fixture(scope="session")
def west_test_env() -> dict[str, str]:
    if not os.environ.get("ZEPHYR_BASE"):
        pytest.skip("Integration tests require ZEPHYR_BASE to be set.")
    return _west_env()


@pytest.fixture(scope="session")
def west_command(west_test_env: dict[str, str]) -> list[str]:
    return _resolve_west_command(west_test_env)


@pytest.fixture(scope="session")
def west_workspace_root(west_test_env: dict[str, str], west_command: list[str]) -> Path:
    candidates: list[Path] = []

    configured = os.environ.get("ZEPHYR_CLI_TEST_WORKSPACE")
    if configured:
        candidates.append(Path(configured).resolve())

    topdir = subprocess.run(
        [*west_command, "topdir"],
        env=west_test_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if topdir.returncode == 0:
        candidates.append(Path(topdir.stdout.strip()).resolve())

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen or not candidate.exists():
            continue
        seen.add(candidate)
        if _has_west_command(candidate, west_command, "build", west_test_env) and _has_west_command(
            candidate, west_command, "agent", west_test_env
        ):
            return candidate

    pytest.skip(
        "Integration tests require a workspace exposing both 'west build' and "
        "'west agent'. Set ZEPHYR_CLI_TEST_WORKSPACE if needed."
    )


@pytest.fixture(scope="session")
def native_sim_app(tmp_path_factory: pytest.TempPathFactory) -> Path:
    app_dir = tmp_path_factory.mktemp("west-agent-app") / "native-sim-app"
    src_dir = app_dir / "src"
    src_dir.mkdir(parents=True)

    (app_dir / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.20.0)\n"
        "find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})\n"
        "project(west_agent_native_sim_smoke)\n"
        "target_sources(app PRIVATE src/main.c)\n"
    )
    (app_dir / "prj.conf").write_text("CONFIG_PRINTK=y\n")
    (app_dir / "debug.conf").write_text("CONFIG_LOG=y\n")
    (src_dir / "main.c").write_text(
        "#include <zephyr/kernel.h>\n"
        "#include <zephyr/sys/printk.h>\n"
        "\n"
        "int main(void)\n"
        "{\n"
        '    printk("west agent native_sim smoke\\n");\n'
        "    return 0;\n"
        "}\n"
    )

    return app_dir


@pytest.fixture(scope="session")
def native_sim_build(
    tmp_path_factory: pytest.TempPathFactory,
    west_workspace_root: Path,
    west_command: list[str],
    west_test_env: dict[str, str],
    native_sim_app: Path,
) -> dict:
    build_dir = tmp_path_factory.mktemp("west-agent-build") / "native-sim"
    output = _run_west_json(
        west_workspace_root,
        west_command,
        west_test_env,
        [
            "agent",
            "build",
            "--board",
            "native_sim",
            "--source-dir",
            str(native_sim_app),
            "--build-dir",
            str(build_dir),
        ],
    )
    return {"build_dir": build_dir, "output": output}


@pytest.fixture(scope="session")
def native_sim_debug_build(
    tmp_path_factory: pytest.TempPathFactory,
    west_workspace_root: Path,
    west_command: list[str],
    west_test_env: dict[str, str],
    native_sim_app: Path,
) -> dict:
    build_dir = tmp_path_factory.mktemp("west-agent-build") / "native-sim-debug"
    output = _run_west_json(
        west_workspace_root,
        west_command,
        west_test_env,
        [
            "agent",
            "build",
            "--board",
            "native_sim",
            "--pristine",
            "--extra-conf",
            str(native_sim_app / "debug.conf"),
            "--source-dir",
            str(native_sim_app),
            "--build-dir",
            str(build_dir),
        ],
    )
    return {"build_dir": build_dir, "output": output}
