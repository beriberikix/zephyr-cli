"""Integration tests for successful west agent native_sim builds."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("ZEPHYR_BASE"),
    reason="Integration tests require ZEPHYR_BASE to be set.",
)


class TestWestAgentBuildNativeSim:
    def test_build_succeeds_and_reports_binaries(self, native_sim_build: dict):
        data = native_sim_build["output"]

        assert data["status"] == "success"
        assert data["board"] == "native_sim"
        assert Path(data["binary"]["elf"]).exists()
        assert Path(data["binary"]["exe"]).exists()

    def test_pristine_and_extra_conf_build_succeeds(self, native_sim_debug_build: dict):
        data = native_sim_debug_build["output"]

        assert data["status"] == "success"
        assert data["board"] == "native_sim"
        assert Path(data["binary"]["elf"]).exists()
        assert Path(data["binary"]["exe"]).exists()