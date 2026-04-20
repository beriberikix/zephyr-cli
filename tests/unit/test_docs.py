"""Unit tests for core/docs.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from zephyr_cli.core import docs as docs_core
from zephyr_cli.core.config import ZephyrCliConfig


@pytest.fixture()
def cfg(tmp_path) -> ZephyrCliConfig:
    c = ZephyrCliConfig()
    c.data_dir = str(tmp_path / "data")
    return c


class TestListCached:
    def test_empty_when_no_cache(self, cfg):
        result = docs_core.list_cached(cfg)
        assert result == []

    def test_returns_cached_versions(self, cfg):
        cache = Path(cfg.data_dir) / "docs"
        (cache / "v4.4.0").mkdir(parents=True)
        (cache / "v4.3.0").mkdir(parents=True)

        result = docs_core.list_cached(cfg)
        assert "v4.4.0" in result
        assert "v4.3.0" in result


class TestFetchReleases:
    def test_parses_github_response(self):
        fake_releases = [
            {
                "tag_name": "v4.4.0",
                "published_at": "2026-04-01T00:00:00Z",
                "assets": [
                    {
                        "name": "zephyrproject-rtos-zephyr-v4-4-0-markdown.tar.gz",
                        "browser_download_url": "https://example.com/docs.tar.gz",
                        "size": 999999,
                    }
                ],
            }
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_releases
        mock_resp.raise_for_status = MagicMock()

        with patch("zephyr_cli.core.docs.httpx.get", return_value=mock_resp):
            releases = docs_core.fetch_releases()

        assert len(releases) == 1
        assert releases[0].version == "v4.4.0"
        assert releases[0].url.endswith(".tar.gz")

    def test_returns_empty_when_no_releases(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()

        with patch("zephyr_cli.core.docs.httpx.get", return_value=mock_resp):
            releases = docs_core.fetch_releases()

        assert releases == []


class TestRefresh:
    def test_raises_when_no_releases(self, cfg):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()

        with (
            patch("zephyr_cli.core.docs.httpx.get", return_value=mock_resp),
            pytest.raises(RuntimeError, match="No docs releases"),
        ):
            docs_core.refresh(cfg)

    def test_raises_for_unknown_version(self, cfg):
        fake_releases = [
            {
                "tag_name": "v4.4.0",
                "published_at": "2026-04-01T00:00:00Z",
                "assets": [
                    {
                        "name": "zephyrproject-rtos-zephyr-v4-4-0-markdown.tar.gz",
                        "browser_download_url": "https://example.com/docs.tar.gz",
                        "size": 1,
                    }
                ],
            }
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_releases
        mock_resp.raise_for_status = MagicMock()

        with (
            patch("zephyr_cli.core.docs.httpx.get", return_value=mock_resp),
            pytest.raises(ValueError, match="not found"),
        ):
            docs_core.refresh(cfg, version="v9.9.9")
