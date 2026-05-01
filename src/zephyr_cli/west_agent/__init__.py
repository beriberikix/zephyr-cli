"""west agent: workspace-aware commands for AI agents and CI pipelines.

Registered as a west extension via entry_points["west.commands"] in
pyproject.toml. All subcommands emit structured JSON by default.

Architecture follows the pattern established by multipass-zephyr:
  - WestCommand subclass with do_add_parser / do_run
  - Workspace context via west.util.west_topdir()
  - ZEPHYR_BASE environment variable for Zephyr root
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from importlib import util
from pathlib import Path
from typing import ClassVar

from west.commands import WestCommand

# ---------------------------------------------------------------------------
# Runner warning filter - strips noisy lines from flash/debug stderr
# ---------------------------------------------------------------------------

_RUNNER_NOISE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^WARNING:\s*(?:esptool|openocd|pyocd|JLink)", re.IGNORECASE),
    re.compile(r"^\*\*\*\s*WARNING", re.IGNORECASE),
    re.compile(r"^WARNING:.*deprecated", re.IGNORECASE),
    re.compile(r"^WARNING:.*not recommended", re.IGNORECASE),
]

_BUILD_PYTHON_MODULES: list[tuple[str, str]] = [
    ("jsonschema", "jsonschema"),
]

_TWISTER_PYTHON_MODULES: list[tuple[str, str]] = [
    ("natsort", "natsort"),
    ("junitparser", "junitparser"),
    ("tabulate", "tabulate"),
    ("psutil", "psutil"),
]


def _filter_runner_output(stderr: str) -> tuple[str, list[str]]:
    """Separate actionable output from noisy runner warnings.

    Returns (filtered_stderr, suppressed_warnings).
    """
    kept: list[str] = []
    suppressed: list[str] = []
    for raw_line in stderr.splitlines():
        line = raw_line.strip()
        if any(p.search(line) for p in _RUNNER_NOISE_PATTERNS):
            suppressed.append(line)
        else:
            kept.append(raw_line)
    return "\n".join(kept), suppressed


def _preflight_python_modules(
    requirements: list[tuple[str, str]],
) -> list[dict[str, str]]:
    """Return missing Python modules for the active runtime.

    Each requirement is ``(module_name, package_name)`` so the emitted
    remediation can stay user-facing even when the import name differs.
    """
    missing: list[dict[str, str]] = []
    seen_packages: set[str] = set()

    for module_name, package_name in requirements:
        try:
            available = util.find_spec(module_name) is not None
        except (ImportError, AttributeError, ValueError):
            available = False
        if available or package_name in seen_packages:
            continue
        seen_packages.add(package_name)
        missing.append(
            {
                "module": module_name,
                "package": package_name,
                "message": f"Missing Python package: {package_name}",
                "remediation": f"pip install {package_name}",
            }
        )

    return missing


def _west_command() -> list[str] | None:
    """Return a runtime-aware west invocation."""
    if util.find_spec("west") is not None:
        return [sys.executable, "-m", "west"]

    west_path = shutil.which("west")
    if west_path is not None:
        return [west_path]

    return None


def _preflight_board_deps(board: str | None) -> list[dict[str, str]]:
    """Check if common flash/debug tools for a board family are available.

    Looks up the board directory under $ZEPHYR_BASE/boards/ and reads
    board.cmake for the default runner, then verifies the runner tool
    exists on PATH.  Returns a list of warning dicts (empty if all OK).
    """
    if not board:
        return []

    zephyr_base = os.environ.get("ZEPHYR_BASE")
    if not zephyr_base:
        return []

    boards_root = Path(zephyr_base) / "boards"
    if not boards_root.is_dir():
        return []

    # Resolve board directory: boards/<vendor>/<board>/ or boards/<board>/
    board_slug = board.split("/")[0]  # strip qualifiers like nrf52840dk/nrf52840
    board_dir: Path | None = None
    for candidate in boards_root.rglob(board_slug):
        if candidate.is_dir() and (candidate / "board.cmake").exists():
            board_dir = candidate
            break

    if board_dir is None:
        return []

    # Parse board.cmake for default runner
    board_cmake = board_dir / "board.cmake"
    runner_re = re.compile(
        r"board_set_(?:flash|debug)runner\((\w+)\)", re.IGNORECASE
    )
    runners: set[str] = set()
    try:
        for cmake_line in board_cmake.read_text().splitlines():
            m = runner_re.search(cmake_line)
            if m:
                runners.add(m.group(1).lower())
    except OSError:
        return []

    # Map runner names to CLI tool names
    runner_to_tool: dict[str, str] = {
        "openocd": "openocd",
        "jlink": "JLinkExe",
        "pyocd": "pyocd",
        "esptool": "esptool.py",
        "esp32": "esptool.py",
        "stm32cubeprogrammer": "STM32_Programmer_CLI",
        "nrfjprog": "nrfjprog",
        "dfu-util": "dfu-util",
    }

    warnings: list[dict[str, str]] = []
    for runner in runners:
        tool = runner_to_tool.get(runner, runner)
        if shutil.which(tool) is None:
            warnings.append({
                "runner": runner,
                "tool": tool,
                "message": f"Flash/debug runner '{runner}' requires '{tool}' which is not on PATH.",
                "remediation": f"Install {tool} or configure a different runner with --runner.",
            })

    return warnings
# Entry point: single 'west agent' command with subcommands
# ---------------------------------------------------------------------------


class AgentCommand(WestCommand):
    """Workspace-aware commands for AI agents and CI pipelines.

    Provides build, inspect, emulate, test, flash, and debug subcommands,
    all with structured JSON output designed for programmatic consumption.
    """

    # Subcommand registry: name -> (handler_method, help_text)
    _SUBCOMMANDS: ClassVar[dict[str, tuple[str, str]]] = {
        "build": ("_run_build", "Build the application with structured JSON output."),
        "inspect": ("_run_inspect", "Introspect workspace build artifacts."),
        "emulate": ("_run_emulate", "Launch an emulator session. [Phase 3]"),
        "test": ("_run_test", "Run the test suite via Twister. [Phase 3]"),
        "flash": ("_run_flash", "Flash to target hardware. [Phase 3]"),
        "debug": ("_run_debug", "Attach debugger. [Phase 3]"),
    }

    def __init__(self) -> None:
        super().__init__(
            "agent",
            "Workspace commands for AI agents and CI pipelines.",
            (
                "Provides build, inspect, emulate, test, flash, and debug "
                "subcommands. All output is structured JSON by default.\n\n"
                "Examples:\n"
                "  west agent build --board nrf52840dk/nrf52840\n"
                "  west agent inspect kconfig --symbol CONFIG_BT\n"
                "  west agent inspect memory --detailed\n"
                "  west agent inspect dts --node /soc/uart@40002000\n"
            ),
            accepts_unknown_args=False,
        )

    def do_add_parser(self, parser_adder: argparse._SubParsersAction) -> argparse.ArgumentParser:
        parser = parser_adder.add_parser(
            self.name,
            help=self.help,
            description=self.description,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )

        parser.add_argument(
            "--format",
            "-f",
            choices=["json", "human"],
            default=None,
            help="Output format. Defaults to json in non-TTY contexts.",
        )

        sub = parser.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")
        sub.required = True

        # --- build ---
        build_p = sub.add_parser("build", help="Build the application.")
        build_p.add_argument("--board", "-b", help="Board target (e.g. nrf52840dk/nrf52840).")
        build_p.add_argument(
            "--build-dir", "-d",
            default=None,
            help="Build directory. Defaults to build/<board-slug>.",
        )
        build_p.add_argument(
            "--pristine", "-p",
            action="store_true",
            help="Clean build (passes -p to west build).",
        )
        build_p.add_argument(
            "--extra-conf",
            metavar="FILE",
            help="Extra Kconfig .conf file (passed via OVERLAY_CONFIG).",
        )
        build_p.add_argument(
            "--source-dir", "-s",
            default=None,
            help="Application source directory. Defaults to current directory.",
        )

        # --- inspect ---
        inspect_p = sub.add_parser("inspect", help="Introspect workspace artifacts.")
        inspect_sub = inspect_p.add_subparsers(
            dest="inspect_target", metavar="TARGET"
        )
        inspect_sub.required = True

        kconfig_p = inspect_sub.add_parser("kconfig", help="Dump resolved Kconfig.")
        kconfig_p.add_argument(
            "--symbol", metavar="SYM",
            help="Filter to a single Kconfig symbol (e.g. CONFIG_BT).",
        )
        kconfig_p.add_argument(
            "--search", metavar="PATTERN",
            help="Regex to search symbol names (e.g. 'BT_.*').",
        )
        kconfig_p.add_argument(
            "--changed", action="store_true",
            help="Show only symbols explicitly set (non-default, non-n).",
        )
        kconfig_p.add_argument(
            "--build-dir", "-d", default=None,
            help="Build directory containing .config.",
        )

        dts_p = inspect_sub.add_parser("dts", help="Dump merged Devicetree as JSON.")
        dts_p.add_argument(
            "--node", metavar="PATH",
            help="Filter to a specific DTS node path (e.g. /soc/uart@40002000).",
        )
        dts_p.add_argument(
            "--compatible", metavar="COMPAT",
            help="Filter to nodes with a specific compatible string.",
        )
        dts_p.add_argument(
            "--chosen", action="store_true",
            help="Show only the chosen node mappings.",
        )
        dts_p.add_argument(
            "--build-dir", "-d", default=None,
            help="Build directory containing zephyr.dts / edt.pickle.",
        )

        memory_p = inspect_sub.add_parser("memory", help="ROM/RAM section analysis.")
        memory_p.add_argument(
            "--detailed", action="store_true",
            help="Include per-symbol breakdown.",
        )
        memory_p.add_argument(
            "--build-dir", "-d", default=None,
            help="Build directory containing zephyr.elf and zephyr.map.",
        )

        threads_p = inspect_sub.add_parser("threads", help="Thread stack allocation analysis.")
        threads_p.add_argument(
            "--build-dir", "-d", default=None,
            help="Build directory containing zephyr.elf.",
        )

        modules_p = inspect_sub.add_parser("modules", help="List west modules with metadata.")
        modules_p.add_argument(
            "--with-paths", action="store_true",
            help="Include board/DTS/Kconfig root paths from module.yml.",
        )

        bindings_p = inspect_sub.add_parser("bindings", help="Search DTS binding definitions.")
        bindings_p.add_argument(
            "--compatible", metavar="COMPAT",
            help="Exact compatible string to look up (e.g. 'nordic,nrf-uart').",
        )
        bindings_p.add_argument(
            "--search", metavar="PATTERN",
            help="Regex to search compatible strings.",
        )
        bindings_p.add_argument(
            "--dir", metavar="PATH", action="append", dest="extra_dirs",
            help="Extra bindings directory to search (may be given multiple times).",
        )

        inspect_sub.add_parser("env", help="Dump effective build environment variables.")

        # --- emulate ---
        from zephyr_cli.west_agent.backends import KNOWN_BACKENDS

        emulate_p = sub.add_parser("emulate", help="Launch an emulator session.")
        emulate_p.add_argument(
            "--backend", "-B",
            choices=KNOWN_BACKENDS,
            default="auto",
            help="Emulation backend. Defaults to auto-detect.",
        )
        emulate_p.add_argument(
            "--timeout", "-t",
            type=float,
            default=30.0,
            metavar="SECONDS",
            help="Kill emulator after SECONDS (0 = no limit). Default: 30.",
        )
        emulate_p.add_argument(
            "--build-dir", "-d",
            default=None,
            help="Build directory. Auto-detected if omitted.",
        )
        emulate_p.add_argument(
            "extra_args",
            nargs=argparse.REMAINDER,
            help="Extra arguments passed verbatim to the emulator.",
        )

        # --- test ---
        test_p = sub.add_parser("test", help="Run tests via Twister.")
        test_p.add_argument(
            "--platform", "-p",
            action="append",
            dest="platforms",
            metavar="PLATFORM",
            help="Target platform(s) (may be repeated). e.g. qemu_cortex_m3.",
        )
        test_p.add_argument(
            "--test-dir", "-T",
            default=None,
            metavar="DIR",
            help="Directory containing tests (default: current directory).",
        )
        test_p.add_argument(
            "--outdir", "-O",
            default="twister-out",
            metavar="DIR",
            help="Twister output directory (default: twister-out).",
        )
        test_p.add_argument(
            "--build-only",
            action="store_true",
            help="Build tests but do not run them.",
        )
        test_p.add_argument(
            "--timeout-multiplier",
            type=float,
            default=1.0,
            metavar="FACTOR",
            help="Multiply all test timeouts by FACTOR.",
        )
        test_p.add_argument(
            "--inline-logs",
            action="store_true",
            help="Inline test logs into the JSON output.",
        )

        # --- flash ---
        flash_p = sub.add_parser("flash", help="Flash firmware to target hardware.")
        flash_p.add_argument(
            "--runner", "-r",
            default=None,
            metavar="RUNNER",
            help="Flash runner (e.g. openocd, jlink, pyocd). Auto-detected if omitted.",
        )
        flash_p.add_argument(
            "--build-dir", "-d",
            default=None,
            help="Build directory. Auto-detected if omitted.",
        )
        flash_p.add_argument(
            "extra_args",
            nargs=argparse.REMAINDER,
            help="Extra arguments passed verbatim to west flash.",
        )

        # --- debug ---
        debug_p = sub.add_parser("debug", help="Attach debugger or stream RTT output.")
        debug_p.add_argument(
            "--server",
            action="store_true",
            help="Start debug server in background and return connection info.",
        )
        debug_p.add_argument(
            "--gdb-port",
            type=int,
            default=None,
            metavar="PORT",
            help="GDB server port (default: 2331 for J-Link, 3333 for OpenOCD).",
        )
        debug_p.add_argument(
            "--rtt-port",
            type=int,
            default=None,
            metavar="PORT",
            help="Connect to RTT TCP port and stream output as NDJSON.",
        )
        debug_p.add_argument(
            "--rtt-timeout",
            type=float,
            default=30.0,
            metavar="SECONDS",
            help="Stop RTT streaming after SECONDS of inactivity (default: 30).",
        )
        debug_p.add_argument(
            "--build-dir", "-d",
            default=None,
            help="Build directory. Auto-detected if omitted.",
        )

        return parser

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def do_run(self, args: argparse.Namespace, unknown: list[str]) -> None:
        fmt = args.format or ("json" if not sys.stdout.isatty() else "human")

        dispatch = {
            "build": self._run_build,
            "inspect": self._run_inspect,
            "emulate": self._run_emulate,
            "test": self._run_test,
            "flash": self._run_flash,
            "debug": self._run_debug,
        }
        handler = dispatch.get(args.subcommand)
        if handler:
            handler(args, fmt)
        else:
            self._emit({"status": "error", "message": f"Unknown subcommand: {args.subcommand}"}, fmt)
            raise SystemExit(1)

    # ------------------------------------------------------------------
    # west agent build
    # ------------------------------------------------------------------

    def _run_build(self, args: argparse.Namespace, fmt: str) -> None:
        from zephyr_cli.schemas.build import (
            BuildError,
            BuildResult,
            BuildStatus,
            locate_binaries,
            parse_build_output,
        )

        board = getattr(args, "board", None) or os.environ.get("BOARD")
        source_dir = getattr(args, "source_dir", None) or os.getcwd()
        source_dir = str(Path(source_dir).resolve())

        # Derive build directory
        build_dir = getattr(args, "build_dir", None)
        if build_dir is None:
            slug = (board or "default").replace("/", "_")
            build_dir = str(Path(source_dir) / "build" / slug)
        build_dir = str(Path(build_dir).resolve())

        west_cmd = _west_command()
        if west_cmd is None:
            self._emit(
                BuildResult(
                    status=BuildStatus.ERROR,
                    board=board,
                    build_dir=build_dir,
                    errors=[],
                    raw_stderr="west not found. Is it installed and on PATH?",
                ).model_dump(mode="json"),
                fmt,
            )
            raise SystemExit(1)

        # Construct west build command
        cmd = [*west_cmd, "build", "-s", source_dir, "-d", build_dir]
        if board:
            cmd += ["-b", board]
        if getattr(args, "pristine", False):
            cmd += ["-p"]

        env = os.environ.copy()
        extra_conf = getattr(args, "extra_conf", None)
        if extra_conf:
            env["OVERLAY_CONFIG"] = str(Path(extra_conf).resolve())

        # Pre-build: check for missing flash/debug tools
        dep_warnings = _preflight_board_deps(board)
        if dep_warnings:
            for w in dep_warnings:
                self._emit({"type": "preflight_warning", **w}, fmt)

        missing_python = _preflight_python_modules(_BUILD_PYTHON_MODULES)
        if missing_python:
            output = BuildResult(
                status=BuildStatus.ERROR,
                board=board,
                build_dir=build_dir,
                errors=[
                    BuildError(
                        message=item["message"],
                        error_type="missing_package",
                        remediation=item["remediation"],
                    )
                    for item in missing_python
                ],
                raw_stderr=(
                    "Missing Python packages in the active Zephyr runtime: "
                    + ", ".join(item["package"] for item in missing_python)
                ),
            )
            self._emit(output.model_dump(mode="json"), fmt)
            raise SystemExit(1)

        start = time.monotonic()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
            )
        except FileNotFoundError:
            self._emit(
                BuildResult(
                    status=BuildStatus.ERROR,
                    board=board,
                    errors=[],
                    raw_stderr="west not found. Is it installed and on PATH?",
                ).model_dump(mode="json"),
                fmt,
            )
            raise SystemExit(1) from None

        duration = time.monotonic() - start
        stderr_combined = result.stderr + result.stdout  # west mixes output

        errors, warnings = parse_build_output(stderr_combined, build_dir=build_dir)

        if result.returncode == 0:
            status = BuildStatus.SUCCESS
            binary = locate_binaries(build_dir)
        else:
            status = BuildStatus.ERROR
            binary_mod = __import__(
                "zephyr_cli.schemas.build", fromlist=["BuildBinary"]
            )
            binary = binary_mod.BuildBinary()

        output = BuildResult(
            status=status,
            board=board,
            build_dir=build_dir,
            duration_seconds=round(duration, 2),
            binary=binary,
            errors=errors,
            warnings=warnings,
            raw_stderr=result.stderr if result.returncode != 0 else None,
        )

        self._emit(output.model_dump(mode="json"), fmt)
        if result.returncode != 0:
            raise SystemExit(1)

    # ------------------------------------------------------------------
    # west agent emulate
    # ------------------------------------------------------------------

    def _run_emulate(self, args: argparse.Namespace, fmt: str) -> None:
        from zephyr_cli.west_agent.backends.detect import detect_backend

        bd = self._require_build_dir(args, fmt)
        assert bd is not None

        backend_pref: str = getattr(args, "backend", "auto")
        timeout: float = getattr(args, "timeout", 30.0)
        extra_args: list[str] = [a for a in (getattr(args, "extra_args", None) or []) if a != "--"]

        try:
            backend = detect_backend(bd, preference=backend_pref)
        except ValueError as exc:
            self._emit({"status": "error", "reason": "unknown_backend", "message": str(exc)}, fmt)
            raise SystemExit(1) from exc

        if backend is None:
            self._emit(
                {
                    "status": "error",
                    "reason": "no_backend_available",
                    "build_dir": str(bd),
                    "hint": (
                        "No emulation backend detected. "
                        "Ensure the build was done for a QEMU-capable board or native_sim, "
                        "or set ZEPHYR_CLI_REMOTE_URL."
                    ),
                },
                fmt,
            )
            raise SystemExit(1)

        result = backend.run(bd, timeout=timeout or None, extra_args=extra_args)
        self._emit(result.model_dump(mode="json"), fmt)
        if result.status != "success":
            raise SystemExit(1)

    # ------------------------------------------------------------------
    # west agent inspect
    # ------------------------------------------------------------------

    def _run_inspect(self, args: argparse.Namespace, fmt: str) -> None:
        target: str | None = getattr(args, "inspect_target", None)
        dispatch = {
            "kconfig": self._inspect_kconfig,
            "dts": self._inspect_dts,
            "memory": self._inspect_memory,
            "threads": self._inspect_threads,
            "modules": self._inspect_modules,
            "bindings": self._inspect_bindings,
            "env": self._inspect_env,
        }
        handler = dispatch.get(target) if target is not None else None
        if handler:
            handler(args, fmt)
        else:
            self._emit({"status": "error", "message": f"Unknown inspect target: {target}"}, fmt)
            raise SystemExit(1)

    def _resolve_build_dir(self, args: argparse.Namespace) -> Path | None:
        """Resolve the build directory from args, falling back to common locations."""
        bd = getattr(args, "build_dir", None)
        if bd:
            resolved = Path(bd).resolve()
            if resolved.name == "zephyr" and any(
                (resolved / name).exists()
                for name in (".config", "zephyr.elf", "edt.pickle", "zephyr.dts")
            ):
                return resolved.parent
            return resolved

        # Try common default locations
        cwd = Path.cwd()
        candidates = [
            cwd / "build",
            # Board-specific build dirs created by 'west agent build'
            *sorted(cwd.glob("build/*")),
        ]
        for candidate in candidates:
            if (candidate / "zephyr" / "zephyr.elf").exists():
                return candidate
        return None

    def _require_build_dir(self, args: argparse.Namespace, fmt: str) -> Path | None:
        bd = self._resolve_build_dir(args)
        if bd is None:
            self._emit(
                {
                    "status": "error",
                    "reason": "build_not_configured",
                    "hint": (
                        "Run 'west agent build' first, or pass --build-dir "
                        "pointing to a configured build directory."
                    ),
                },
                fmt,
            )
            raise SystemExit(1)
        return bd

    def _inspect_kconfig(self, args: argparse.Namespace, fmt: str) -> None:
        bd = self._require_build_dir(args, fmt)
        assert bd is not None

        dot_config = bd / "zephyr" / ".config"
        if not dot_config.exists():
            self._emit(
                {
                    "status": "error",
                    "reason": "dotconfig_not_found",
                    "build_dir": str(bd),
                    "hint": "The build directory exists but has not been configured yet.",
                },
                fmt,
            )
            raise SystemExit(1)

        zephyr_base = os.environ.get("ZEPHYR_BASE")
        if not zephyr_base:
            self._emit(
                {
                    "status": "error",
                    "reason": "ZEPHYR_BASE_not_set",
                    "hint": "Source zephyr-env.sh or set ZEPHYR_BASE.",
                },
                fmt,
            )
            raise SystemExit(1)

        try:
            from zephyr_cli.west_agent.inspect.kconfig import (
                changed_symbols,
                load_kconfig,
                search_symbols,
                symbol_to_dict,
            )
            kconf = load_kconfig(zephyr_base, bd, dot_config)
        except ImportError as exc:
            self._emit(
                {"status": "error", "reason": "kconfiglib_not_installed", "hint": "pip install kconfiglib"},
                fmt,
            )
            raise SystemExit(1) from exc
        except Exception as exc:
            self._emit({"status": "error", "reason": "kconfig_load_failed", "message": str(exc)}, fmt)
            raise SystemExit(1) from exc

        symbol = getattr(args, "symbol", None)
        search = getattr(args, "search", None)
        changed = getattr(args, "changed", False)

        if symbol:
            sym_name = symbol.removeprefix("CONFIG_")
            sym = kconf.syms.get(sym_name)
            if sym is None:
                self._emit(
                    {"status": "error", "reason": "symbol_not_found", "symbol": symbol},
                    fmt,
                )
                raise SystemExit(1)
            self._emit({"status": "ok", "build_dir": str(bd), "symbol": symbol_to_dict(sym)}, fmt)
        elif search:
            symbols = search_symbols(kconf, search, changed_only=changed)
            self._emit(
                {"status": "ok", "build_dir": str(bd), "pattern": search, "count": len(symbols), "symbols": symbols},
                fmt,
            )
        elif changed:
            symbols = changed_symbols(kconf)
            self._emit(
                {"status": "ok", "build_dir": str(bd), "count": len(symbols), "symbols": symbols},
                fmt,
            )
        else:
            symbols = changed_symbols(kconf)
            self._emit(
                {"status": "ok", "build_dir": str(bd), "count": len(symbols), "symbols": symbols},
                fmt,
            )

    def _inspect_dts(self, args: argparse.Namespace, fmt: str) -> None:
        bd = self._require_build_dir(args, fmt)
        assert bd is not None

        zephyr_base = os.environ.get("ZEPHYR_BASE", "")
        node_filter = getattr(args, "node", None)
        compat_filter = getattr(args, "compatible", None)
        chosen_only = getattr(args, "chosen", False)

        try:
            from zephyr_cli.west_agent.inspect.dts import get_chosen, load_edt, node_to_dict

            edt = load_edt(bd, zephyr_base)

            if chosen_only:
                self._emit(
                    {"status": "ok", "build_dir": str(bd), "chosen": get_chosen(edt)},
                    fmt,
                )
                return

            nodes = list(getattr(edt, "nodes", []))
            if node_filter:
                nodes = [n for n in nodes if n.path == node_filter]
            if compat_filter:
                nodes = [n for n in nodes if compat_filter in list(getattr(n, "compats", []) or [])]

            edt_pickle = bd / "zephyr" / "edt.pickle"
            source = "edt.pickle" if edt_pickle.exists() else "zephyr.dts"

            self._emit(
                {
                    "status": "ok",
                    "build_dir": str(bd),
                    "source": source,
                    "count": len(nodes),
                    "nodes": [node_to_dict(n) for n in nodes],
                },
                fmt,
            )
        except FileNotFoundError as exc:
            self._emit(
                {
                    "status": "error",
                    "reason": "dts_not_found",
                    "build_dir": str(bd),
                    "message": str(exc),
                    "hint": "Run 'west agent build' to generate the merged DTS.",
                },
                fmt,
            )
            raise SystemExit(1) from None
        except Exception as exc:
            self._emit(
                {
                    "status": "error",
                    "reason": "dts_parse_failed",
                    "message": str(exc),
                    "hint": "Ensure ZEPHYR_BASE is set and the build is complete.",
                },
                fmt,
            )
            raise SystemExit(1) from None

    def _inspect_memory(self, args: argparse.Namespace, fmt: str) -> None:
        bd = self._require_build_dir(args, fmt)
        assert bd is not None

        elf_path = bd / "zephyr" / "zephyr.elf"
        map_path = bd / "zephyr" / "zephyr.map"

        if not elf_path.exists():
            self._emit(
                {
                    "status": "error",
                    "reason": "elf_not_found",
                    "build_dir": str(bd),
                },
                fmt,
            )
            raise SystemExit(1)

        try:
            from zephyr_cli.west_agent.inspect.memory import analyze_memory
        except ImportError as e:
            self._emit(
                {"status": "error", "reason": "memory_analysis_unavailable", "message": str(e)},
                fmt,
            )
            raise SystemExit(1) from None

        result = analyze_memory(
            elf_path=elf_path,
            map_path=map_path if map_path.exists() else None,
            detailed=getattr(args, "detailed", False),
        )
        self._emit(result, fmt)

    def _inspect_threads(self, args: argparse.Namespace, fmt: str) -> None:
        bd = self._require_build_dir(args, fmt)
        assert bd is not None

        elf_path = bd / "zephyr" / "zephyr.elf"
        if not elf_path.exists():
            self._emit(
                {"status": "error", "reason": "elf_not_found", "build_dir": str(bd)},
                fmt,
            )
            raise SystemExit(1)

        try:
            from zephyr_cli.west_agent.inspect.threads import analyze_threads
        except ImportError as e:
            self._emit(
                {"status": "error", "reason": "thread_analysis_unavailable", "message": str(e)},
                fmt,
            )
            raise SystemExit(1) from None

        result = analyze_threads(elf_path=elf_path)
        self._emit(result, fmt)

    def _inspect_modules(self, args: argparse.Namespace, fmt: str) -> None:
        """List west modules with metadata from module.yml."""
        from zephyr_cli.west_agent.inspect.modules import list_modules

        with_paths = getattr(args, "with_paths", False)
        modules = list_modules()

        if not with_paths:
            _path_fields = {
                "board_root", "dts_root", "snippet_root",
                "soc_root", "dts_bindings_root", "kconfig", "cmake",
            }
            modules = [{k: v for k, v in m.items() if k not in _path_fields} for m in modules]

        self._emit({"status": "ok", "count": len(modules), "modules": modules}, fmt)

    def _inspect_bindings(self, args: argparse.Namespace, fmt: str) -> None:
        """Search DTS binding definitions across ZEPHYR_BASE and west modules."""
        zephyr_base = os.environ.get("ZEPHYR_BASE", "")
        if not zephyr_base:
            self._emit(
                {
                    "status": "error",
                    "reason": "ZEPHYR_BASE_not_set",
                    "hint": "Source zephyr-env.sh or set ZEPHYR_BASE.",
                },
                fmt,
            )
            raise SystemExit(1)

        from zephyr_cli.west_agent.inspect.bindings import search_bindings
        from zephyr_cli.west_agent.inspect.modules import collect_bindings_dirs

        dirs = collect_bindings_dirs(zephyr_base)
        extra_dirs: list[str] = getattr(args, "extra_dirs", None) or []
        dirs.extend(extra_dirs)

        compatible = getattr(args, "compatible", None)
        search = getattr(args, "search", None)

        if not compatible and not search:
            self._emit(
                {
                    "status": "error",
                    "reason": "no_filter",
                    "hint": "Provide --compatible or --search to filter bindings.",
                },
                fmt,
            )
            raise SystemExit(1)

        results = search_bindings(dirs, compatible=compatible, pattern=search)
        self._emit(
            {
                "status": "ok",
                "count": len(results),
                "dirs_searched": dirs,
                "bindings": results,
            },
            fmt,
        )

    def _inspect_env(self, args: argparse.Namespace, fmt: str) -> None:
        """Dump all effective build environment variables."""
        from zephyr_cli.core.env import collect_env
        result = collect_env()
        self._emit(result.model_dump(mode="json"), fmt)

    # ------------------------------------------------------------------
    # west agent test
    # ------------------------------------------------------------------

    def _run_test(self, args: argparse.Namespace, fmt: str) -> None:
        import json as _json
        import time

        from zephyr_cli.schemas.test import TestResult, TestSummary, parse_twister_json

        zephyr_base = os.environ.get("ZEPHYR_BASE")
        if not zephyr_base:
            self._emit(
                {"status": "error", "reason": "ZEPHYR_BASE_not_set", "hint": "Source zephyr-env.sh or set ZEPHYR_BASE."},
                fmt,
            )
            raise SystemExit(1)

        platforms: list[str] = getattr(args, "platforms", None) or []
        test_dir: str = getattr(args, "test_dir", None) or os.getcwd()
        outdir: str = getattr(args, "outdir", "twister-out")
        build_only: bool = getattr(args, "build_only", False)
        timeout_mult: float = getattr(args, "timeout_multiplier", 1.0)
        inline_logs: bool = getattr(args, "inline_logs", False)

        west_cmd = _west_command()
        if west_cmd is None:
            self._emit({"status": "error", "reason": "west_not_found"}, fmt)
            raise SystemExit(1)

        cmd = [
            *west_cmd,
            "twister",
            "-T", str(Path(test_dir).resolve()),
            "-O", str(Path(outdir).resolve()),
            "--timeout-multiplier", str(timeout_mult),
        ]
        for plat in platforms:
            cmd += ["-p", plat]
        if build_only:
            cmd.append("--build-only")
        if inline_logs:
            cmd.append("--inline-logs")

        missing_python = _preflight_python_modules(_TWISTER_PYTHON_MODULES)
        if missing_python:
            self._emit(
                {
                    "status": "error",
                    "reason": "missing_python_dependencies",
                    "output_dir": str(Path(outdir).resolve()),
                    "missing_dependencies": missing_python,
                    "hint": (
                        "Install the missing packages in the active Zephyr Python "
                        "environment before running west twister."
                    ),
                },
                fmt,
            )
            raise SystemExit(1)

        start = time.monotonic()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            self._emit({"status": "error", "reason": "west_not_found"}, fmt)
            raise SystemExit(1) from None
        duration = time.monotonic() - start

        # Parse twister.json if it exists
        twister_json_path = Path(outdir) / "twister.json"
        suites = []
        summary = TestSummary()
        if twister_json_path.exists():
            try:
                with open(twister_json_path) as fh:
                    raw = _json.load(fh)
                summary, suites = parse_twister_json(raw)
            except Exception:
                pass  # fall through with empty suites

        overall = "error" if proc.returncode != 0 else (
            "failed" if summary.failed or summary.error else "passed"
        )

        result = TestResult(
            status=overall,
            summary=summary,
            duration_seconds=round(duration, 2),
            output_dir=str(Path(outdir).resolve()),
            suites=suites,
            raw_output=(proc.stdout + proc.stderr) or None,
        )
        self._emit(result.model_dump(mode="json"), fmt)
        if proc.returncode != 0 or summary.failed or summary.error:
            raise SystemExit(1)

    # ------------------------------------------------------------------
    # west agent flash
    # ------------------------------------------------------------------

    def _run_flash(self, args: argparse.Namespace, fmt: str) -> None:
        import time

        from zephyr_cli.schemas.flash import FlashResult

        bd = self._require_build_dir(args, fmt)
        assert bd is not None

        runner: str | None = getattr(args, "runner", None)
        extra_args: list[str] = [a for a in (getattr(args, "extra_args", None) or []) if a != "--"]

        west_cmd = _west_command()
        if west_cmd is None:
            self._emit({"status": "error", "reason": "west_not_found"}, fmt)
            raise SystemExit(1)

        cmd = [*west_cmd, "flash", "-d", str(bd)]
        if runner:
            cmd += ["--runner", runner]
        if extra_args:
            cmd += ["--", *extra_args]

        start = time.monotonic()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            self._emit({"status": "error", "reason": "west_not_found"}, fmt)
            raise SystemExit(1) from None
        duration = time.monotonic() - start

        combined = proc.stdout + proc.stderr
        filtered, suppressed = _filter_runner_output(combined)
        status = "success" if proc.returncode == 0 else "error"

        result = FlashResult(
            status=status,
            build_dir=str(bd),
            runner=runner,
            duration_seconds=round(duration, 2),
            output=filtered or None,
            error=proc.stderr.strip() or None if proc.returncode != 0 else None,
            suppressed_warnings=suppressed,
        )
        self._emit(result.model_dump(mode="json"), fmt)
        if proc.returncode != 0:
            raise SystemExit(1)

    # ------------------------------------------------------------------
    # west agent debug
    # ------------------------------------------------------------------

    def _run_debug(self, args: argparse.Namespace, fmt: str) -> None:
        import time

        from zephyr_cli.schemas.debug import DebugResult, parse_debug_output

        bd = self._require_build_dir(args, fmt)
        assert bd is not None

        server_mode: bool = getattr(args, "server", False)
        rtt_port: int | None = getattr(args, "rtt_port", None)
        gdb_port: int | None = getattr(args, "gdb_port", None)
        rtt_timeout: float = getattr(args, "rtt_timeout", 30.0)

        west_cmd = _west_command()
        if west_cmd is None:
            self._emit({"status": "error", "reason": "west_not_found"}, fmt)
            raise SystemExit(1)

        # --- RTT streaming mode ---
        if rtt_port is not None:
            self._run_debug_rtt(bd, rtt_port, rtt_timeout, fmt)
            return

        # --- Server mode: start west debugserver in background ---
        if server_mode:
            cmd = [*west_cmd, "debugserver", "-d", str(bd)]
            if gdb_port:
                cmd += ["--gdb-port", str(gdb_port)]
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            except FileNotFoundError:
                self._emit({"status": "error", "reason": "west_not_found"}, fmt)
                raise SystemExit(1) from None

            # Wait briefly for the server to bind its port
            time.sleep(1.0)
            if proc.poll() is not None:
                out, err = proc.communicate()
                result = DebugResult(
                    status="error",
                    build_dir=str(bd),
                    output=(out + err) or None,
                    error="Debug server exited immediately.",
                    server_started=False,
                )
                self._emit(result.model_dump(mode="json"), fmt)
                raise SystemExit(1)

            result = DebugResult(
                status="running",
                build_dir=str(bd),
                pid=proc.pid,
                gdb_port=gdb_port or 2331,
                server_started=True,
            )
            self._emit(result.model_dump(mode="json"), fmt)
            return

        # --- Attach mode: west debug (blocking) ---
        start = time.monotonic()
        cmd = [*west_cmd, "debug", "-d", str(bd)]
        try:
            proc_result = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            self._emit({"status": "error", "reason": "west_not_found"}, fmt)
            raise SystemExit(1) from None
        duration = time.monotonic() - start

        combined = proc_result.stdout + proc_result.stderr
        filtered, suppressed = _filter_runner_output(combined)
        attach_status, capabilities = parse_debug_output(combined)
        status = "success" if proc_result.returncode == 0 else "error"
        result = DebugResult(
            status=status,
            build_dir=str(bd),
            duration_seconds=round(duration, 2),
            output=filtered or None,
            error=proc_result.stderr.strip() or None if proc_result.returncode != 0 else None,
            attach_status=attach_status,
            capabilities=capabilities,
            suppressed_warnings=suppressed,
        )
        self._emit(result.model_dump(mode="json"), fmt)
        if proc_result.returncode != 0:
            raise SystemExit(1)

    def _run_debug_rtt(self, bd: Path, rtt_port: int, timeout: float, fmt: str) -> None:
        """Connect to an RTT TCP server and stream output as NDJSON."""
        import socket
        import time

        try:
            sock = socket.create_connection(("localhost", rtt_port), timeout=5.0)
        except (ConnectionRefusedError, OSError) as exc:
            self._emit(
                {
                    "status": "error",
                    "reason": "rtt_connection_failed",
                    "rtt_port": rtt_port,
                    "message": str(exc),
                    "hint": "Ensure the debug server is running with RTT enabled.",
                },
                fmt,
            )
            raise SystemExit(1) from exc

        sock.settimeout(timeout)
        buf = ""
        try:
            while True:
                try:
                    chunk = sock.recv(4096)
                except TimeoutError:
                    break
                if not chunk:
                    break
                buf += chunk.decode(errors="replace")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    record = {"ts": time.time(), "channel": 0, "data": line}
                    print(json.dumps(record))
        finally:
            sock.close()

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    def _emit(self, data: dict, fmt: str) -> None:
        if fmt == "json" or not sys.stdout.isatty():
            print(json.dumps(data, indent=2, default=str))
        else:
            try:
                from rich import print_json
                print_json(json.dumps(data, default=str))
            except ImportError:
                print(json.dumps(data, indent=2, default=str))


