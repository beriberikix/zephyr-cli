"""Unit tests for west agent inspect build-dir normalization."""

from __future__ import annotations

import argparse


class TestResolveBuildDir:
    def test_normalizes_zephyr_artifact_dir_to_build_root(self, tmp_path):
        build_dir = tmp_path / "build"
        zephyr_dir = build_dir / "zephyr"
        zephyr_dir.mkdir(parents=True)
        (zephyr_dir / ".config").write_text("CONFIG_LOG=y\n")

        from zephyr_cli.west_agent import AgentCommand

        cmd = AgentCommand()
        resolved = cmd._resolve_build_dir(argparse.Namespace(build_dir=str(zephyr_dir)))

        assert resolved == build_dir.resolve()