"""Integration tests — require a real west workspace and Zephyr SDK.

These tests are skipped in standard CI unless ZEPHYR_BASE is set.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("ZEPHYR_BASE"),
    reason="Integration tests require ZEPHYR_BASE to be set.",
)
