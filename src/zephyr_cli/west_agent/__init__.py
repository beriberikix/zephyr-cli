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
            help="Filter to a specific Kconfig symbol (e.g. CONFIG_BT).",
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
            "--build-dir", "-d", default=None,
            help="Build directory containing zephyr.dts.",
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

        inspect_sub.add_parser("modules", help="List all west modules.")

        inspect_sub.add_parser("env", help="Dump effective build environment variables.")

        # --- Phase 3 placeholders ---
        for name, (_, help_text) in list(self._SUBCOMMANDS.items())[2:]:
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
            "emulate": self._run_phase3_stub,
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

        symbol = getattr(args, "symbol", None)

        try:
            import kconfiglib  # type: ignore[import-untyped]
        except ImportError:
            self._emit(
                {
                    "status": "error",
                    "reason": "kconfiglib_not_installed",
                    "hint": "pip install kconfiglib",
                },
                fmt,
            )
            raise SystemExit(1) from None

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

        # Load Kconfig using the build's merged Kconfig root
        kconfig_file = bd / "Kconfig"
        if not kconfig_file.exists():
            # Fall back to Zephyr's top-level Kconfig
            kconfig_file = Path(zephyr_base) / "Kconfig"

        kconf = kconfiglib.Kconfig(str(kconfig_file), warn=False)
        kconf.load_config(str(dot_config))

        if symbol:
            sym_name = symbol.removeprefix("CONFIG_")
            sym = kconf.syms.get(sym_name)
            if sym is None:
                self._emit(
                    {"status": "error", "reason": "symbol_not_found", "symbol": symbol},
                    fmt,
                )
                raise SystemExit(1)
            self._emit(_kconfig_symbol_to_dict(sym), fmt)
        else:
            # Dump all non-default, set symbols
            result = {
                "build_dir": str(bd),
                "symbols": [
                    _kconfig_symbol_to_dict(sym)
                    for sym in kconf.syms.values()
                    if sym.str_value not in ("n", "")
                    and sym.orig_type != kconfiglib.UNKNOWN
                ],
            }
            self._emit(result, fmt)

    def _inspect_dts(self, args: argparse.Namespace, fmt: str) -> None:
        bd = self._require_build_dir(args, fmt)
        assert bd is not None

        zephyr_dts = bd / "zephyr" / "zephyr.dts"
        edt_pickle = bd / "zephyr" / "edt.pickle"

        if not zephyr_dts.exists():
            self._emit(
                {
                    "status": "error",
                    "reason": "zephyr_dts_not_found",
                    "build_dir": str(bd),
                    "hint": "Run 'west agent build' to generate the merged DTS.",
                },
                fmt,
            )
            raise SystemExit(1)

        node_filter = getattr(args, "node", None)

        # Use edtlib if available (preferred — gives full binding-resolved data)
        try:
            import pickle

            if edt_pickle.exists():
                with open(edt_pickle, "rb") as f:
                    edt = pickle.load(f)
                nodes = edt.nodes
                if node_filter:
                    nodes = [n for n in nodes if n.path == node_filter]
                result = {
                    "build_dir": str(bd),
                    "source": "edt.pickle",
                    "nodes": [_edt_node_to_dict(n) for n in nodes],
                }
            else:
                # Fall back to raw DTS text parse via edtlib directly
                zephyr_base = os.environ.get("ZEPHYR_BASE", "")
                bindings_dirs = [str(Path(zephyr_base) / "dts" / "bindings")]
                sys.path.insert(0, str(Path(zephyr_base) / "scripts" / "dts"))
                import edtlib  # type: ignore[import-untyped]

                edt = edtlib.EDT(str(zephyr_dts), bindings_dirs)
                nodes = edt.nodes
                if node_filter:
                    nodes = [n for n in nodes if n.path == node_filter]
                result = {
                    "build_dir": str(bd),
                    "source": "zephyr.dts",
                    "nodes": [_edt_node_to_dict(n) for n in nodes],
                }
            self._emit(result, fmt)
        except Exception as e:
            self._emit(
                {
                    "status": "error",
                    "reason": "dts_parse_failed",
                    "message": str(e),
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
        """List west modules via 'west list -f json' or parse west manifest."""
        try:
            result = subprocess.run(
                ["west", "list", "--format={name} {path} {url} {revision}"],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            self._emit(
                {"status": "error", "reason": "west_not_found"},
                fmt,
            )
            raise SystemExit(1) from None

        modules = []
        for line in result.stdout.strip().splitlines():
            parts = line.split(None, 3)
            if len(parts) >= 2:
                name, path = parts[0], parts[1]
                url = parts[2] if len(parts) > 2 else None
                revision = parts[3] if len(parts) > 3 else None
                abs_path = Path(path).resolve() if path != "None" else None
                modules.append(
                    {
                        "name": name,
                        "path": str(abs_path) if abs_path else path,
                        "url": url,
                        "revision": revision,
                        "in_tree": _is_in_zephyr_tree(abs_path),
                    }
                )

        self._emit({"modules": modules, "count": len(modules)}, fmt)

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


# ---------------------------------------------------------------------------
# DTS / Kconfig helper functions (keep __init__.py focused on dispatch)
# ---------------------------------------------------------------------------


def _kconfig_symbol_to_dict(sym: object) -> dict:
    """Convert a kconfiglib Symbol to a plain dict."""
    try:
        import kconfiglib  # type: ignore[import-untyped]
    except ImportError:
        return {}

    type_map = {
        kconfiglib.BOOL: "bool",
        kconfiglib.INT: "int",
        kconfiglib.HEX: "hex",
        kconfiglib.STRING: "string",
        kconfiglib.TRISTATE: "tristate",
    }

    def node_loc(node: object) -> str | None:
        try:
            return f"{node.filename}:{node.linenr}"  # type: ignore[attr-defined]
        except AttributeError:
            return None

    nodes = getattr(sym, "nodes", [])
    location = node_loc(nodes[0]) if nodes else None
    prompt = None
    if nodes:
        p = getattr(nodes[0], "prompt", None)
        if p:
            prompt = p[0]

    return {
        "symbol": f"CONFIG_{sym.name}",  # type: ignore[attr-defined]
        "value": sym.str_value,  # type: ignore[attr-defined]
        "type": type_map.get(sym.orig_type, "unknown"),  # type: ignore[attr-defined]
        "prompt": prompt,
        "location": location,
        "direct_dependencies": [
            f"CONFIG_{s.name}"  # type: ignore[attr-defined]
            for s in getattr(sym, "direct_dep", ()) or []
            if hasattr(s, "name")
        ],
    }


def _edt_node_to_dict(node: object) -> dict:
    """Convert an edtlib Node to a plain dict."""
    try:
        props: dict = {}
        for name, prop in getattr(node, "props", {}).items():
            try:
                val = prop.val
                # Convert bytes/bytearray to hex string for JSON serialisation
                if isinstance(val, (bytes, bytearray)):
                    val = val.hex()
                props[name] = val
            except Exception:
                props[name] = repr(prop)

        return {
            "path": getattr(node, "path", None),
            "compatible": getattr(node, "compats", []),
            "status": getattr(node, "status", None),
            "label": getattr(node, "label", None),
            "aliases": list(getattr(node, "aliases", [])),
            "properties": props,
        }
    except Exception as e:
        return {"error": str(e), "path": getattr(node, "path", "unknown")}


def _is_in_zephyr_tree(path: Path | None) -> bool:
    if path is None:
        return False
    zb = os.environ.get("ZEPHYR_BASE", "")
    if not zb:
        return False
    try:
        path.relative_to(Path(zb).parent)
        return True
    except ValueError:
        return False
