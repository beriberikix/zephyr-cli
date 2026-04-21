"""Backend auto-detection for ``west agent emulate``.

Priority order (per spec):
  1. macOS / Windows + Multipass available  → MultipassBackend  [Phase 3 later]
  2. Docker available + test-server image   → DockerBackend      [Phase 3 later]
  3. QEMU runner listed in runners.yaml     → QemuBackend
  4. zephyr.exe present (native_sim)        → NativeSimBackend
  5. ZEPHYR_CLI_REMOTE_URL env var set      → RemoteBackend      [Phase 3 later]
"""

from __future__ import annotations

import os
from pathlib import Path

from zephyr_cli.west_agent.backends.base import EmulationBackend
from zephyr_cli.west_agent.backends.native_sim import NativeSimBackend
from zephyr_cli.west_agent.backends.qemu import QemuBackend

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

KNOWN_BACKENDS: list[str] = ["qemu", "native_sim", "docker", "multipass", "remote", "auto"]


def detect_backend(build_dir: Path, preference: str = "auto") -> EmulationBackend | None:
    """Return the best available backend for *build_dir*.

    *preference*:
    - ``"auto"``   — run the priority-ordered detection chain
    - any other    — return that specific backend regardless of detection
      (raises ``ValueError`` for unknown names)

    Returns ``None`` if no backend is available.
    """
    if preference != "auto":
        return _get_named_backend(preference)

    # --- Phase 3 detection chain ---

    # 1. Multipass: stub (macOS/Windows only, not yet implemented)
    # 2. Docker: stub (not yet implemented)

    # 3. QEMU — runner listed in runners.yaml
    qemu = QemuBackend()
    if qemu.can_run(build_dir):
        return qemu

    # 4. native_sim — zephyr.exe present
    native = NativeSimBackend()
    if native.can_run(build_dir):
        return native

    # 5. Remote — ZEPHYR_CLI_REMOTE_URL env var (stub)
    if os.environ.get("ZEPHYR_CLI_REMOTE_URL"):
        # Phase 3 later: return RemoteBackend()
        pass

    return None


def _get_named_backend(name: str) -> EmulationBackend:
    """Return a backend instance by name, raising ValueError for unknowns."""
    registry: dict[str, type[EmulationBackend]] = {
        "qemu": QemuBackend,
        "native_sim": NativeSimBackend,
        # "docker": DockerBackend,     # Phase 3 later
        # "multipass": MultipassBackend,  # Phase 3 later
        # "remote": RemoteBackend,     # Phase 3 later
    }
    cls = registry.get(name)
    if cls is None:
        raise ValueError(f"Unknown backend '{name}'. Choose from: {', '.join(registry)}")
    return cls()
