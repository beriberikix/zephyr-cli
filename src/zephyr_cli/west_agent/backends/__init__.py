"""West agent emulation backends.

Public surface:
    detect_backend(build_dir, preference="auto") -> EmulationBackend | None
    KNOWN_BACKENDS: list[str]
"""

from zephyr_cli.west_agent.backends.base import EmulationBackend
from zephyr_cli.west_agent.backends.detect import KNOWN_BACKENDS, detect_backend
from zephyr_cli.west_agent.backends.native_sim import NativeSimBackend
from zephyr_cli.west_agent.backends.qemu import QemuBackend

__all__ = [
    "KNOWN_BACKENDS",
    "EmulationBackend",
    "NativeSimBackend",
    "QemuBackend",
    "detect_backend",
]
