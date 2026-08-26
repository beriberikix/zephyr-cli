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
                "tag_name": "zephyrproject-rtos-zephyr-v4-4-0",
                "published_at": "2026-04-01T00:00:00Z",
                "assets": [
                    {
                        "name": "zephyrdocs-v4.4.0.tar.gz",
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
                "tag_name": "zephyrproject-rtos-zephyr-v4-4-0",
                "published_at": "2026-04-01T00:00:00Z",
                "assets": [
                    {
                        "name": "zephyrdocs-v4.4.0.tar.gz",
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


class TestReadManifest:
    def _bundle(self, root: Path, payload: str, nested: bool = True) -> Path:
        target = root / "markdown" if nested else root
        target.mkdir(parents=True, exist_ok=True)
        (target / "manifest.json").write_text(payload, encoding="utf-8")
        return root

    def test_reads_manifest_nested_under_bundle_root(self, tmp_path):
        self._bundle(tmp_path, '{"schema": 1, "version": "v4.4.0", "page_count": 2364}')
        manifest = docs_core.read_manifest(tmp_path)
        assert manifest is not None
        assert manifest.version == "v4.4.0"
        assert manifest.page_count == 2364

    def test_reads_manifest_at_bundle_root(self, tmp_path):
        self._bundle(tmp_path, '{"schema": 1, "version": "v4.3.1"}', nested=False)
        manifest = docs_core.read_manifest(tmp_path)
        assert manifest is not None
        assert manifest.version == "v4.3.1"

    def test_returns_none_when_absent(self, tmp_path):
        (tmp_path / "markdown").mkdir()
        assert docs_core.read_manifest(tmp_path) is None

    def test_returns_none_for_malformed_json(self, tmp_path):
        self._bundle(tmp_path, "{not json")
        assert docs_core.read_manifest(tmp_path) is None

    def test_returns_none_for_non_object(self, tmp_path):
        self._bundle(tmp_path, '["a", "b"]')
        assert docs_core.read_manifest(tmp_path) is None

    def test_ignores_unknown_fields(self, tmp_path):
        self._bundle(tmp_path, '{"schema": 1, "version": "v4.4.0", "future": {"a": 1}}')
        manifest = docs_core.read_manifest(tmp_path)
        assert manifest is not None
        assert manifest.version == "v4.4.0"


class TestRefreshUsesManifest:
    def _tarball(self, tmp_path: Path, manifest: str | None) -> Path:
        import tarfile as _tarfile

        stage = tmp_path / "stage" / "markdown"
        stage.mkdir(parents=True)
        (stage / "index.md").write_text("# Zephyr\n", encoding="utf-8")
        if manifest is not None:
            (stage / "manifest.json").write_text(manifest, encoding="utf-8")

        archive = tmp_path / "bundle.tar.gz"
        with _tarfile.open(archive, "w:gz") as tf:
            tf.add(stage, arcname="markdown")
        return archive

    def _run(self, cfg, tmp_path, archive: Path, asset_version: str):
        releases = [
            docs_core.DocsRelease(
                version=asset_version, tag="mangled-tag", url="https://example.com/b.tar.gz"
            )
        ]

        class _Resp:
            def raise_for_status(self):
                return None

            def iter_bytes(self, chunk_size=65536):
                yield archive.read_bytes()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with (
            patch.object(docs_core, "fetch_releases", return_value=releases),
            patch.object(docs_core.httpx, "stream", return_value=_Resp()),
        ):
            return docs_core.refresh(cfg)

    def test_manifest_version_wins_over_asset_name(self, cfg, tmp_path):
        archive = self._tarball(tmp_path, '{"schema": 1, "version": "v4.4.2"}')
        version, path = self._run(cfg, tmp_path, archive, asset_version="wrong-from-filename")

        assert version == "v4.4.2"
        assert path.name == "v4.4.2"
        assert (path / "markdown" / "index.md").is_file()
        assert docs_core.list_cached(cfg) == ["v4.4.2"]

    def test_falls_back_to_asset_name_without_manifest(self, cfg, tmp_path):
        archive = self._tarball(tmp_path, None)
        version, path = self._run(cfg, tmp_path, archive, asset_version="v4.1.0")

        assert version == "v4.1.0"
        assert path.name == "v4.1.0"
        assert (path / "markdown" / "index.md").is_file()

    def test_leaves_no_staging_directory_behind(self, cfg, tmp_path):
        archive = self._tarball(tmp_path, '{"schema": 1, "version": "v4.4.2"}')
        self._run(cfg, tmp_path, archive, asset_version="v4.4.2")

        cache = Path(cfg.data_dir) / "docs"
        assert [p.name for p in cache.iterdir() if p.name.startswith(".")] == []
        assert not list(cache.glob("*.tar.gz"))
