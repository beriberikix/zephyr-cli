"""Project scaffolder for zephyr-cli create.

Three topologies:
  T1 — standalone application (minimal Zephyr app)
  T2 — app + MCUboot via sysbuild
  T3 — sysbuild multi-image (app + sidecar placeholder)
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Board validation
# ---------------------------------------------------------------------------

# Zephyr board identifiers: <board> or <board>/<soc> or <board>/<soc>/<variant>
_BOARD_TOKEN_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def validate_board(board: str) -> list[str]:
    """Validate a board identifier and return a list of warnings (may be empty).

    Raises ``ValueError`` if the board string is syntactically invalid.
    Returns warnings (not errors) if the board is not found under
    ``$ZEPHYR_BASE/boards``; out-of-tree boards are common and valid.
    """
    warnings: list[str] = []
    parts = board.split("/")
    if len(parts) > 3:
        raise ValueError(
            f"Invalid board identifier {board!r}: expected "
            "<board>, <board>/<soc>, or <board>/<soc>/<variant>."
        )
    for part in parts:
        if not _BOARD_TOKEN_RE.match(part):
            raise ValueError(
                f"Invalid board identifier {board!r}: "
                f"token {part!r} contains invalid characters. "
                "Board tokens may only contain letters, digits, hyphens, and underscores."
            )

    # Soft check: see if the board directory exists under ZEPHYR_BASE
    zephyr_base = os.environ.get("ZEPHYR_BASE")
    if zephyr_base:
        boards_dir = Path(zephyr_base) / "boards"
        if boards_dir.is_dir():
            board_name = parts[0]
            # boards/ has vendor subdirs, so search recursively
            matches = list(boards_dir.rglob(board_name))
            if not matches:
                warnings.append(
                    f"Board {board_name!r} was not found under {boards_dir}. "
                    "It may be an out-of-tree board; proceeding anyway."
                )

    return warnings

# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------


def _cmakelists(name: str) -> str:
    return (
        "cmake_minimum_required(VERSION 3.20.0)\n"
        "find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})\n"
        f"project({name})\n"
        "target_sources(app PRIVATE src/main.c)\n"
    )


def _main_c(name: str) -> str:
    return (
        "#include <zephyr/kernel.h>\n"
        "#include <zephyr/sys/printk.h>\n"
        "\n"
        "int main(void)\n"
        "{\n"
        f'    printk("Hello from {name}!\\n");\n'
        "    return 0;\n"
        "}\n"
    )


_PRJ_CONF = "# Application Kconfig fragments\nCONFIG_PRINTK=y\n"

_SYSBUILD_CONF_T2 = "# Enable MCUboot as the bootloader\nSB_CONFIG_BOOTLOADER_MCUBOOT=y\n"

_SYSBUILD_CMAKE_T3 = (
    "# sysbuild/CMakeLists.txt\n"
    "# Add extra images here, e.g.:\n"
    "#   ExternalZephyrProject_Add(\n"
    "#     APPLICATION sidecar\n"
    "#     SOURCE_DIR ${APP_DIR}/../sidecar\n"
    "#   )\n"
)


def _readme_t1(name: str) -> str:
    ul = "=" * len(name)
    return (
        f"{name}\n{ul}\n\n"
        "A minimal Zephyr RTOS application.\n\n"
        "Building\n--------\n\n"
        ".. code-block:: bash\n\n"
        "   west build -b <board> .\n\n"
        "Running\n-------\n\n"
        ".. code-block:: bash\n\n"
        "   west flash\n"
    )


def _readme_t2(name: str) -> str:
    ul = "=" * len(name)
    return (
        f"{name}\n{ul}\n\n"
        "A Zephyr RTOS application with MCUboot secure bootloader (sysbuild).\n\n"
        "Building\n--------\n\n"
        ".. code-block:: bash\n\n"
        "   west build -b <board> --sysbuild .\n\n"
        "Flashing\n--------\n\n"
        ".. code-block:: bash\n\n"
        "   west flash\n"
    )


def _readme_t3(name: str) -> str:
    ul = "=" * len(name)
    return (
        f"{name}\n{ul}\n\n"
        "A Zephyr RTOS multi-image sysbuild project.\n\n"
        "Structure\n---------\n\n"
        "- ``app/`` — primary application image\n"
        "- ``sysbuild/`` — sysbuild configuration\n\n"
        "Building\n--------\n\n"
        ".. code-block:: bash\n\n"
        "   west build -b <board> --sysbuild .\n\n"
        "Flashing\n--------\n\n"
        ".. code-block:: bash\n\n"
        "   west flash\n"
    )


# ---------------------------------------------------------------------------
# Topology builders
# ---------------------------------------------------------------------------


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def scaffold_t1(dest: Path, name: str) -> list[str]:
    """Standalone Zephyr application."""
    _write(dest / "CMakeLists.txt", _cmakelists(name))
    _write(dest / "prj.conf", _PRJ_CONF)
    _write(dest / "src" / "main.c", _main_c(name))
    _write(dest / "README.rst", _readme_t1(name))
    return ["CMakeLists.txt", "prj.conf", "src/main.c", "README.rst"]


def scaffold_t2(dest: Path, name: str) -> list[str]:
    """App + MCUboot via sysbuild."""
    _write(dest / "CMakeLists.txt", _cmakelists(name))
    _write(dest / "prj.conf", _PRJ_CONF)
    _write(dest / "sysbuild.conf", _SYSBUILD_CONF_T2)
    _write(dest / "src" / "main.c", _main_c(name))
    _write(dest / "README.rst", _readme_t2(name))
    return ["CMakeLists.txt", "prj.conf", "sysbuild.conf", "src/main.c", "README.rst"]


def scaffold_t3(dest: Path, name: str) -> list[str]:
    """Sysbuild multi-image project."""
    _write(dest / "app" / "CMakeLists.txt", _cmakelists(name))
    _write(dest / "app" / "prj.conf", _PRJ_CONF)
    _write(dest / "app" / "src" / "main.c", _main_c(name))
    _write(dest / "sysbuild" / "CMakeLists.txt", _SYSBUILD_CMAKE_T3)
    _write(dest / "README.rst", _readme_t3(name))
    return [
        "app/CMakeLists.txt",
        "app/prj.conf",
        "app/src/main.c",
        "sysbuild/CMakeLists.txt",
        "README.rst",
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

TOPOLOGY_BUILDERS = {
    "T1": scaffold_t1,
    "T2": scaffold_t2,
    "T3": scaffold_t3,
}


def create_project(
    name: str,
    topology: str,
    parent_dir: Path,
) -> tuple[Path, list[str]]:
    """Scaffold a new project and return ``(app_path, files_created)``.

    Raises ``FileExistsError`` if the target directory already exists.
    Raises ``ValueError`` for an unknown topology.
    """
    topology = topology.upper()
    if topology not in TOPOLOGY_BUILDERS:
        raise ValueError(f"Unknown topology {topology!r}. Choose from: T1, T2, T3")

    dest = parent_dir / name
    if dest.exists():
        raise FileExistsError(f"Directory '{dest}' already exists")

    dest.mkdir(parents=True)
    files = TOPOLOGY_BUILDERS[topology](dest, name)
    return dest, files


def next_steps(topology: str, name: str, board: str | None = None) -> list[str]:
    """Return recommended next-step commands for the given topology."""
    board_str = board or "<board>"
    t = topology.upper()

    build_cmd = f"west build -b {board_str} ."
    if t in ("T2", "T3"):
        build_cmd = f"west build -b {board_str} --sysbuild ."

    return [
        f"cd {name}",
        "west init -l .",
        "west update",
        build_cmd,
        "west flash",
    ]
