"""Abstract base class for emulation backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from zephyr_cli.schemas.emulate import EmulateResult


class EmulationBackend(ABC):
    """Interface that all emulation backends must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier (e.g. 'qemu', 'native_sim')."""
        ...

    @abstractmethod
    def can_run(self, build_dir: Path) -> bool:
        """Return True if this backend can emulate the artifact in *build_dir*.

        Must not raise; return False on any detection failure.
        """
        ...

    @abstractmethod
    def run(
        self,
        build_dir: Path,
        timeout: float | None,
        extra_args: list[str],
    ) -> EmulateResult:
        """Launch the emulator and return a structured result.

        *timeout*: seconds before the process is killed (None = no limit).
        *extra_args*: passed verbatim to the emulator process.
        """
        ...
