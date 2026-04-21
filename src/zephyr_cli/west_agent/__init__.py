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
import subprocess
import sys
import time
from pathlib import Path
from typing import ClassVar

from west.commands import WestCommand

# ---------------------------------------------------------------------------
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

        # --- Phase 3 stubs (test / flash / debug) ---
        for name, (_, help_text) in list(self._SUBCOMMANDS.items())[3:]:
            sub.add_parser(name, help=help_text)

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
            "test": self._run_phase3_stub,
            "flash": self._run_phase3_stub,
            "debug": self._run_phase3_stub,
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

        # Construct west build command
        cmd = ["west", "build", "-s", source_dir, "-d", build_dir]
        if board:
            cmd += ["-b", board]
        if getattr(args, "pristine", False):
            cmd += ["-p"]

        env = os.environ.copy()
        extra_conf = getattr(args, "extra_conf", None)
        if extra_conf:
            env["OVERLAY_CONFIG"] = str(Path(extra_conf).resolve())

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
            return Path(bd).resolve()

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
    # Phase 3 stubs
    # ------------------------------------------------------------------

    def _run_phase3_stub(self, args: argparse.Namespace, fmt: str) -> None:
        subcommand = getattr(args, "subcommand", "unknown")
        self._emit(
            {
                "status": "not_implemented",
                "subcommand": f"west agent {subcommand}",
                "phase": 3,
                "hint": "Emulation and testing commands arrive in Phase 3.",
            },
            fmt,
        )
        raise SystemExit(1)

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


