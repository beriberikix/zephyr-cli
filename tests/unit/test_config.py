"""Unit tests for config resolution."""

from __future__ import annotations

import os
from unittest.mock import patch

from zephyr_cli.core.config import (
    DEFAULT_SKILLS_REGISTRY_URL,
    ZephyrCliConfig,
    _apply_env,
)


class TestZephyrCliConfigDefaults:
    def test_default_registry_url(self):
        cfg = ZephyrCliConfig()
        assert cfg.skills_registry_url == DEFAULT_SKILLS_REGISTRY_URL

    def test_default_format_is_json(self):
        cfg = ZephyrCliConfig()
        assert cfg.default_format == "json"

    def test_default_emulate_backend_is_empty(self):
        cfg = ZephyrCliConfig()
        assert cfg.emulate_backend == ""


class TestEnvVarOverride:
    def test_sdk_path_override(self):
        cfg = ZephyrCliConfig()
        with patch.dict(os.environ, {"ZEPHYR_CLI_SDK_PATH": "/opt/my-sdk"}):
            _apply_env(cfg)
        assert cfg.sdk_path == "/opt/my-sdk"

    def test_emulate_backend_override(self):
        cfg = ZephyrCliConfig()
        with patch.dict(os.environ, {"ZEPHYR_CLI_EMULATE_BACKEND": "docker"}):
            _apply_env(cfg)
        assert cfg.emulate_backend == "docker"

    def test_format_override(self):
        cfg = ZephyrCliConfig()
        with patch.dict(os.environ, {"ZEPHYR_CLI_FORMAT": "human"}):
            _apply_env(cfg)
        assert cfg.default_format == "human"

    def test_no_env_vars_leaves_defaults(self):
        cfg = ZephyrCliConfig()
        # Patch out all relevant env vars
        clean_env = {
            k: v for k, v in os.environ.items()
            if not k.startswith("ZEPHYR_CLI_")
        }
        with patch.dict(os.environ, clean_env, clear=True):
            _apply_env(cfg)
        assert cfg.sdk_path is None
        assert cfg.emulate_backend == ""
