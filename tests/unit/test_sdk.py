"""Unit tests for core/sdk.py and sdk commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from zephyr_cli.core import sdk as sdk_core
from zephyr_cli.core.config import ZephyrCliConfig


@pytest.fixture()
def cfg(tmp_path) -> ZephyrCliConfig:
    c = ZephyrCliConfig()
    c.data_dir = str(tmp_path / "data")
    return c


class TestListInstalled:
    def test_empty_when_no_sdks(self, cfg):
        result = sdk_core.list_installed(cfg)
        assert result == []

    def test_finds_installed_sdk(self, cfg, tmp_path):
        sdk_dir = Path(cfg.data_dir) / "sdks" / "zephyr-sdk-0.16.8"
        sdk_dir.mkdir(parents=True)
        (sdk_dir / "sdk_version").write_text("0.16.8\n")

        result = sdk_core.list_installed(cfg)
        assert len(result) == 1
        assert result[0].version == "0.16.8"
        assert not result[0].selected

    def test_marks_selected_sdk(self, cfg, tmp_path):
        sdk_dir = Path(cfg.data_dir) / "sdks" / "zephyr-sdk-0.16.8"
        sdk_dir.mkdir(parents=True)
        (sdk_dir / "sdk_version").write_text("0.16.8")
        (Path(cfg.data_dir) / "sdks" / "sdk_selected.txt").write_text("0.16.8")

        result = sdk_core.list_installed(cfg)
        assert result[0].selected is True


class TestSelectSdk:
    def test_raises_if_not_installed(self, cfg):
        with pytest.raises(FileNotFoundError, match="not installed"):
            sdk_core.select_sdk(cfg, "0.99.0")

    def test_selects_installed_sdk(self, cfg, tmp_path):
        sdk_dir = Path(cfg.data_dir) / "sdks" / "zephyr-sdk-0.16.8"
        sdk_dir.mkdir(parents=True)
        (sdk_dir / "sdk_version").write_text("0.16.8")

        result = sdk_core.select_sdk(cfg, "0.16.8")
        assert result.selected is True
        assert result.version == "0.16.8"

        # Persisted
        sel = (Path(cfg.data_dir) / "sdks" / "sdk_selected.txt").read_text().strip()
        assert sel == "0.16.8"


class TestDetectPlatform:
    def test_returns_string(self):
        plat = sdk_core._detect_platform()
        assert isinstance(plat, str)
        assert "-" in plat  # e.g. "linux-x86_64"


class TestFetchAvailable:
    def test_parses_github_response(self):
        fake_release = [
            {
                "tag_name": "v0.16.8",
                "assets": [
                    {
                        "name": "zephyr-sdk-0.16.8_linux-x86_64.tar.xz",
                        "browser_download_url": "https://example.com/full.tar.xz",
                        "size": 123456,
                    },
                    {
                        "name": "zephyr-sdk-0.16.8_linux-x86_64_minimal.tar.xz",
                        "browser_download_url": "https://example.com/minimal.tar.xz",
                        "size": 11111,
                    },
                ],
            }
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_release
        mock_resp.raise_for_status = MagicMock()

        with (
            patch("zephyr_cli.core.sdk.httpx.get", return_value=mock_resp),
            patch("zephyr_cli.core.sdk._detect_platform", return_value="linux-x86_64"),
        ):
            releases = sdk_core.fetch_available()

        assert len(releases) == 1
        assert releases[0].version == "0.16.8"
        assert "full" in releases[0].url
        assert releases[0].minimal_url is not None
