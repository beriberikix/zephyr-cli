"""native_sim direct subprocess emulation backend.

Runs ``<build_dir>/zephyr/zephyr.exe`` directly — no external tooling needed.
Detection: ``zephyr.exe`` must exist in the build directory.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from zephyr_cli.schemas.emulate import EmulateBackendName, EmulateResult, EmulateStatus
from zephyr_cli.west_agent.backends.base import EmulationBackend


class NativeSimBackend(EmulationBackend):
    """Run a native_sim application by executing zephyr.exe directly."""

    @property
    def name(self) -> str:
        return "native_sim"

    def can_run(self, build_dir: Path) -> bool:
        return (build_dir / "zephyr" / "zephyr.exe").exists()

    def run(
        self,
        build_dir: Path,
        timeout: float | None,
        extra_args: list[str],
    ) -> EmulateResult:
        exe = build_dir / "zephyr" / "zephyr.exe"
        cmd = [str(exe), *extra_args]

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
                backend=EmulateBackendName.NATIVE_SIM,
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
            if captured.strip() and not exc.stderr:
                return EmulateResult(
                    status=EmulateStatus.SESSION_CAPPED,
                    backend=EmulateBackendName.NATIVE_SIM,
                    build_dir=str(build_dir),
                    duration_seconds=round(duration, 2),
                    output=captured,
                )
            return EmulateResult(
                status=EmulateStatus.TIMEOUT,
                backend=EmulateBackendName.NATIVE_SIM,
                build_dir=str(build_dir),
                duration_seconds=round(duration, 2),
                output=captured or None,
                error=f"Emulation timed out after {timeout}s.",
            )
        except PermissionError:
            return EmulateResult(
                status=EmulateStatus.ERROR,
                backend=EmulateBackendName.NATIVE_SIM,
                build_dir=str(build_dir),
                error=f"Permission denied executing {exe}. Run: chmod +x {exe}",
            )
        except FileNotFoundError:
            return EmulateResult(
                status=EmulateStatus.ERROR,
                backend=EmulateBackendName.NATIVE_SIM,
                build_dir=str(build_dir),
                error=f"Executable not found: {exe}",
            )
