"""QEMU direct subprocess emulation backend.

Uses ``west build -t run -d <build_dir>`` which invokes Zephyr's runner
framework to construct and execute the correct QEMU command for the board.

Detection: ``<build_dir>/zephyr/runners.yaml`` must exist and list ``qemu``
in its ``runners`` mapping.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from zephyr_cli.schemas.emulate import EmulateBackendName, EmulateResult, EmulateStatus
from zephyr_cli.west_agent.backends.base import EmulationBackend


class QemuBackend(EmulationBackend):
    """Run an application in QEMU via ``west build -t run``."""

    @property
    def name(self) -> str:
        return "qemu"

    def can_run(self, build_dir: Path) -> bool:
        """Return True if runners.yaml exists and lists the qemu runner."""
        runners_yaml = build_dir / "zephyr" / "runners.yaml"
        if not runners_yaml.exists():
            return False
        try:
            import yaml  # type: ignore[import-untyped]

            with open(runners_yaml) as fh:
                data = yaml.safe_load(fh) or {}
            runners = data.get("runners", {})
            return isinstance(runners, dict) and "qemu" in runners
        except Exception:
            return False

    def run(
        self,
        build_dir: Path,
        timeout: float | None,
        extra_args: list[str],
    ) -> EmulateResult:
        cmd = ["west", "build", "-t", "run", "-d", str(build_dir)]
        # extra_args passed after '--' so west doesn't consume them
        if extra_args:
            cmd += ["--", *extra_args]

        start = time.monotonic()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout if timeout and timeout > 0 else None,
            )
            duration = time.monotonic() - start
            combined = result.stdout + result.stderr
            status = EmulateStatus.SUCCESS if result.returncode == 0 else EmulateStatus.ERROR
            return EmulateResult(
                status=status,
                backend=EmulateBackendName.QEMU,
                build_dir=str(build_dir),
                duration_seconds=round(duration, 2),
                exit_code=result.returncode,
                output=combined or None,
                error=result.stderr.strip() or None if result.returncode != 0 else None,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - start
            captured: str = ""
            if exc.stdout:
                captured += exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode(errors="replace")
            if exc.stderr:
                captured += exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode(errors="replace")
            return EmulateResult(
                status=EmulateStatus.TIMEOUT,
                backend=EmulateBackendName.QEMU,
                build_dir=str(build_dir),
                duration_seconds=round(duration, 2),
                output=captured or None,
                error=f"Emulation timed out after {timeout}s.",
            )
        except FileNotFoundError:
            return EmulateResult(
                status=EmulateStatus.ERROR,
                backend=EmulateBackendName.QEMU,
                build_dir=str(build_dir),
                error="west not found. Is it installed and on PATH?",
            )
