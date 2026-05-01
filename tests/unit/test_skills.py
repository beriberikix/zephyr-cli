"""Unit tests for core/registry.py and skills commands."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from zephyr_cli.core.config import ZephyrCliConfig
from zephyr_cli.core.registry import (
    list_installed,
    suggest_skills,
)
from zephyr_cli.schemas.skills import SkillsIndex

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_INDEX_JSON = json.dumps(
    {
        "schema_version": "1",
        "repo": "beriberikix/zephyr-agent-skills",
        "updated": "2026-04-20",
        "skills": [
            {
                "name": "build-system",
                "description": "Build system management for Zephyr RTOS. Covers West, CMake, Kconfig.",
                "keywords": ["west", "cmake", "kconfig", "manifest", "ninja"],
                "kconfig_patterns": [],
                "dts_compatible": [],
                "path": "skills/build-system",
                "files": ["SKILL.md", "references/west.md"],
            },
            {
                "name": "connectivity-ble",
                "description": "BLE and Bluetooth management for Zephyr.",
                "keywords": ["ble", "bluetooth", "gatt", "hci"],
                "kconfig_patterns": ["CONFIG_BT.*"],
                "dts_compatible": ["nordic,nrf-radio"],
                "path": "skills/connectivity-ble",
                "files": ["SKILL.md"],
            },
            {
                "name": "storage",
                "description": "Flash storage, NVS, LittleFS for Zephyr.",
                "keywords": ["flash", "nvs", "storage", "littlefs", "fatfs"],
                "kconfig_patterns": ["CONFIG_FLASH.*", "CONFIG_NVS"],
                "dts_compatible": ["fixed-partitions", "jedec,spi-nor"],
                "path": "skills/storage",
                "files": ["SKILL.md"],
            },
        ],
    }
)


@pytest.fixture()
def sample_index() -> SkillsIndex:
    return SkillsIndex.model_validate_json(SAMPLE_INDEX_JSON)


@pytest.fixture()
def cfg(tmp_path) -> ZephyrCliConfig:
    c = ZephyrCliConfig()
    c.data_dir = str(tmp_path / "data")
    return c


# ---------------------------------------------------------------------------
# load_index
# ---------------------------------------------------------------------------


class TestLoadIndex:
    def test_loads_from_network(self, cfg):
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_INDEX_JSON
        mock_resp.raise_for_status = MagicMock()

        with patch("zephyr_cli.core.registry.httpx.get", return_value=mock_resp) as mock_get:
            from zephyr_cli.core.registry import load_index

            index = load_index(cfg, force_refresh=True)
            assert mock_get.called
            assert len(index.skills) == 3

    def test_uses_cache_when_fresh(self, cfg, tmp_path):
        # Prime the cache manually
        cache_dir = Path(cfg.data_dir) / "registry"
        cache_dir.mkdir(parents=True)
        (cache_dir / "index.json").write_text(SAMPLE_INDEX_JSON)
        (cache_dir / "index.meta").write_text(str(time.time()))  # fresh

        with patch("zephyr_cli.core.registry.httpx.get") as mock_get:
            from zephyr_cli.core.registry import load_index

            index = load_index(cfg)
            assert not mock_get.called
            assert index.skills[0].name == "build-system"

    def test_refreshes_stale_cache(self, cfg, tmp_path):
        cache_dir = Path(cfg.data_dir) / "registry"
        cache_dir.mkdir(parents=True)
        (cache_dir / "index.json").write_text(SAMPLE_INDEX_JSON)
        (cache_dir / "index.meta").write_text(str(time.time() - 7200))  # stale

        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_INDEX_JSON
        mock_resp.raise_for_status = MagicMock()

        with patch("zephyr_cli.core.registry.httpx.get", return_value=mock_resp):
            from zephyr_cli.core.registry import load_index

            index = load_index(cfg)
            assert len(index.skills) == 3


# ---------------------------------------------------------------------------
# list_installed
# ---------------------------------------------------------------------------


class TestListInstalled:
    def test_empty_when_no_skills_dir(self, tmp_path):
        result = list_installed(tmp_path)
        assert result == []

    def test_returns_installed_skills(self, tmp_path):
        skill_dir = tmp_path / ".zephyr" / "skills" / "build-system"
        skill_dir.mkdir(parents=True)
        meta = {
            "name": "build-system",
            "description": "Build system skill",
            "installed_at": "2026-04-20T00:00:00Z",
        }
        (skill_dir / ".zephyr-skill.json").write_text(json.dumps(meta))

        result = list_installed(tmp_path)
        assert len(result) == 1
        assert result[0].name == "build-system"

    def test_ignores_dirs_without_meta(self, tmp_path):
        skill_dir = tmp_path / ".zephyr" / "skills" / "orphan"
        skill_dir.mkdir(parents=True)
        # No .zephyr-skill.json

        result = list_installed(tmp_path)
        assert result == []


# ---------------------------------------------------------------------------
# suggest_skills
# ---------------------------------------------------------------------------


class TestSuggestSkills:
    def test_returns_relevant_skill_by_keyword(self, sample_index):
        results = suggest_skills(sample_index, "bluetooth le advertising")
        names = [s.name for s in results]
        assert "connectivity-ble" in names

    def test_returns_relevant_skill_by_description(self, sample_index):
        results = suggest_skills(sample_index, "cmake build kconfig")
        assert results[0].name == "build-system"

    def test_kconfig_pattern_match(self, sample_index):
        results = suggest_skills(sample_index, "", kconfig_symbols=["CONFIG_BT_ENABLED"])
        names = [s.name for s in results]
        assert "connectivity-ble" in names

    def test_dts_compatible_match(self, sample_index):
        results = suggest_skills(sample_index, "", dts_compatibles=["jedec,spi-nor"])
        names = [s.name for s in results]
        assert "storage" in names

    def test_empty_query_with_no_signals_returns_empty(self, sample_index):
        results = suggest_skills(sample_index, "")
        assert results == []

    def test_respects_max_results(self, sample_index):
        results = suggest_skills(sample_index, "zephyr", max_results=1)
        assert len(results) <= 1
