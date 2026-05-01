# zephyr-cli

Agent-optimized CLI for Zephyr RTOS.

`zephyr-cli` is the primary interface for AI coding agents and CI pipelines to interact with, scaffold, build, and inspect Zephyr RTOS projects. It consists of a global `zephyr-cli` Python package and a `west agent` workspace extension.

All commands emit **structured JSON by default** in non-TTY contexts. Pass `--format human` (or pipe through a TTY) for human-readable output.

## Requirements

- Python ≥ 3.11
- [west](https://docs.zephyrproject.org/latest/develop/west/index.html) ≥ 1.2
- `ZEPHYR_BASE` set (source `zephyr-env.sh`) for workspace commands

## Installation

```bash
pip install zephyr-cli
# or with uv (recommended)
uv tool install zephyr-cli
```

## Enable `west agent` in a workspace

`west` discovers extension commands from `west-commands.yml` referenced by the workspace manifest.

```bash
# from the zephyr-cli repo root
west init -l .
west update

# verify command is discoverable
west help agent
```

For end-to-end `west agent build`, `flash`, and `debug` flows, use a combined
Zephyr workspace that includes both Zephyr and `zephyr-cli` in the manifest.
A repo-only checkout can expose `west agent` while still missing Zephyr's own
`west build`, `west flash`, and `west debug` extension commands.

## Global commands (`zephyr-cli`)

These commands work anywhere — no west workspace required.

```bash
# Print resolved environment (SDK, west, toolchains, installed skills)
zephyr-cli env

# Print version information
zephyr-cli version

# Scaffold a new project (T1 = standalone, T2 = app+MCUboot, T3 = multi-image sysbuild)
zephyr-cli create my-app --topology T1 --board nrf52840dk/nrf52840

# --- SDK management ---
zephyr-cli sdk list                      # List installed SDKs
zephyr-cli sdk list --available          # Also fetch available versions from GitHub
zephyr-cli sdk install 0.16.8            # Download and install SDK 0.16.8
zephyr-cli sdk install 0.16.8 --minimal  # Minimal SDK (no host tools)
zephyr-cli sdk select 0.16.8             # Set active SDK version

# --- Skills management ---
zephyr-cli skills list                   # List registry + installed skills
zephyr-cli skills list --installed       # Only show installed skills
zephyr-cli skills install build-system   # Install a skill into .zephyr/skills/
zephyr-cli skills install build-system --force
zephyr-cli skills show build-system      # Show skill details
zephyr-cli skills suggest "add BLE support" --kconfig CONFIG_BT

# --- Documentation cache ---
zephyr-cli docs list                     # List cached + available docs releases
zephyr-cli docs refresh                  # Download/update latest docs
zephyr-cli docs refresh --version 3.7.0  # Pin to a specific release

# Self-update
zephyr-cli update
```

## Workspace commands (`west agent`)

These commands require an initialized west workspace and a prior `west agent build`.

```bash
# Build with structured JSON output
west agent build --board nrf52840dk/nrf52840
west agent build --board nrf52840dk/nrf52840 --pristine
west agent build --board nrf52840dk/nrf52840 --extra-conf debug.conf
west agent build --board nrf52840dk/nrf52840 --build-dir build/custom

# --- Inspect ---
west agent inspect kconfig                           # Dump changed Kconfig symbols
west agent inspect kconfig --symbol CONFIG_BT        # Single symbol + dependency tree
west agent inspect kconfig --search 'BT_.*'          # Regex search
west agent inspect kconfig --changed                 # Symbols explicitly set (non-default)

west agent inspect dts                               # Dump full merged Devicetree as JSON
west agent inspect dts --node /soc/uart@40002000     # Filter to a specific node
west agent inspect dts --compatible nordic,nrf-uart  # Filter by compatible string
west agent inspect dts --chosen                      # Show chosen node mappings only

west agent inspect memory                            # ROM/RAM section analysis
west agent inspect memory --detailed                 # Include per-symbol breakdown

west agent inspect threads                           # Thread stack allocation analysis

west agent inspect modules                           # List west modules with metadata
west agent inspect modules --with-paths              # Include board/DTS/Kconfig root paths

west agent inspect bindings --compatible nordic,nrf-uart  # Look up a DTS binding
west agent inspect bindings --search 'nordic,nrf-.*'      # Regex search across all bindings
west agent inspect bindings --compatible nordic,nrf-uart --dir /extra/bindings

west agent inspect env                               # Dump effective build environment variables

# --- Emulate ---
west agent emulate                                   # Auto-detect backend (QEMU or native_sim)
west agent emulate --backend qemu --timeout 60
west agent emulate --backend native_sim
west agent emulate --backend native_sim --timeout 3  # May return status=session_capped

# --- Test ---
west agent test --platform qemu_cortex_m3
west agent test --platform qemu_cortex_m3 --platform native_posix
west agent test --test-dir tests/ --outdir twister-out
west agent test --build-only
west agent test --inline-logs --timeout-multiplier 2.0

# --- Flash ---
west agent flash                                     # Auto-detect runner
west agent flash --runner openocd
west agent flash --runner jlink -- --speed 4000

# --- Debug ---
west agent debug                                     # Attach (blocking)
west agent debug --server                            # Start debug server in background → {pid, gdb_port}
west agent debug --server --gdb-port 3333
west agent debug --rtt-port 19021                    # Stream RTT output as NDJSON
west agent debug --rtt-port 19021 --rtt-timeout 60

# Override output format for any command
west agent build --board nrf52840dk/nrf52840 --format human
```

### Workspace notes

- `west agent flash` and `west agent debug` return `native_runner_not_supported`
  for `native` runners. Use `west agent emulate` for `native_sim` builds.
- Structured flash and debug results include `build_dir`, `board`, and `runner`
  metadata so agents can key off the active build target without reparsing the
  build directory.
- `west agent emulate --timeout ...` can return `session_capped` when the app
  produced useful output before the requested time cap elapsed.
- For ESP32 debug, if the board support config references a missing OpenOCD
  script such as `interface/esp_usb_jtag.cfg`, `west agent debug` returns
  `openocd_script_not_found` before launch. Set `OPENOCD_SCRIPTS` to a scripts
  directory that contains the required interface files.

## GitHub Actions reusable workflow

```yaml
jobs:
  zephyr:
    uses: beriberikix/zephyr-cli/.github/workflows/zephyr-build.yml@main
    with:
      board: nrf52840dk/nrf52840
      app-dir: app/
      zephyr-sdk-version: "0.16.8"
      run-tests: true
      emulate: true
```

**Inputs:** `board`, `app-dir`, `zephyr-sdk-version`, `run-tests`, `emulate`  
**Outputs:** `build-status`, `test-status`, `emulate-status`

## Architecture

- **`zephyr-cli`** — global Typer application; manages environment, SDK, project scaffolding, skills, and docs.
- **`west agent`** — west extension discovered via `west-commands.yml` + workspace `west.yml`; all workspace commands in one `WestCommand` subclass.
- **Skills** install into `<workspace>/.zephyr/skills/`; registry at `beriberikix/zephyr-agent-skills`.
- **SDK** installs to `<data_dir>/sdks/` via `platformdirs`.
- **Emulation backends** auto-detected in priority order: QEMU (`runners.yaml`) → native_sim → Docker → Multipass → remote (`ZEPHYR_CLI_REMOTE_URL`).
- **JSON output** is the default in any non-TTY context; `--format human` opts in to rich-formatted output.

## License

Apache-2.0
