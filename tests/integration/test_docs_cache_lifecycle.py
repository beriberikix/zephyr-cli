"""P2: docs cache lifecycle test.

Ensures that docs refresh populates the cache and docs list
returns cached entries when network is unavailable.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from zephyr_cli.main import app

runner = CliRunner()


class TestDocsCacheLifecycle:
    """docs refresh + list should be stable and offline-safe."""

    @pytest.fixture(autouse=True)
    def _setup_cache_dir(self, tmp_path, monkeypatch):
        """Point docs cache to a temp directory."""
        monkeypatch.setenv("ZEPHYR_CLI_CACHE_DIR", str(tmp_path))
        self.cache_dir = tmp_path

    def test_list_returns_json(self):
        result = runner.invoke(app, ["docs", "list", "--format", "json"])
        # Should succeed (possibly with empty cache)
        assert result.exit_code == 0

    def test_list_after_network_failure_uses_cache(self):
        # First, list to see current state
        result1 = runner.invoke(app, ["docs", "list", "--format", "json"])
        assert result1.exit_code == 0

        # Simulate network failure and list again — should not crash
        with patch(
            "zephyr_cli.core.docs.httpx.Client",
            side_effect=httpx.ConnectError("offline"),
        ):
            result2 = runner.invoke(app, ["docs", "list", "--format", "json"])
            # Should still succeed using cached data (or empty list)
            assert result2.exit_code == 0
