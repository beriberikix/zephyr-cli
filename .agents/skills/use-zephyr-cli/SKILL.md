---
name: use-zephyr-cli
description: >
  Guides AI agents to correctly use zephyr-cli and the west agent extension when
  working on Zephyr RTOS projects. Covers building, inspecting (Kconfig, Devicetree,
  memory, threads), emulating, testing, flashing, debugging, and safely managing
  Zephyr domain skills and documentation. Use this skill whenever the user is working
  on a Zephyr project, mentions west builds, Kconfig symbols, devicetree overlays,
  board targets, Zephyr SDK, flashing firmware, QEMU emulation, Twister tests, or
  asks about any zephyr-cli or west agent command — even if they don't name the tool
  explicitly. Also use when the user wants to find or install Zephyr skills, refresh
  Zephyr docs, or scaffold a new Zephyr project.
---

# Using zephyr-cli and west agent

This skill teaches you how to use two complementary tools for Zephyr RTOS development:

- **`zephyr-cli`** — A global CLI for environment inspection, SDK management, project scaffolding, skills, and docs. Works anywhere.
- **`west agent`** — A west extension for build, inspect, emulate, test, flash, and debug. Requires a west workspace.

Both tools emit **structured JSON by default** when stdout is not a TTY (i.e., when you're piping output or running programmatically). This is intentional — JSON output is precise and parseable, so prefer it when you need to extract data. Use `--format human` only when showing output directly to the user.

For the full flag reference for every command, read `references/commands.md` in this skill's directory.

---

## First step: Orient yourself

Before doing anything else in a Zephyr workspace, run:

```bash
zephyr-cli env --format json
```

This tells you:
- Whether the Zephyr SDK is installed and which version is active
- Whether `west` is available and initialized
- The workspace root path
- Which Zephyr skills are already installed
- The docs cache status

Parse this output to understand what's available before suggesting installations or builds. If `ZEPHYR_BASE` isn't set or `west` isn't initialized, address that first.

---

## Building firmware

```bash
west agent --format json build --board <board>
```

Note: `--format` is a top-level `west agent` flag — it goes *before* the subcommand.

Key patterns:
- Always specify `--board` explicitly (e.g., `nrf52840dk/nrf52840`, `qemu_cortex_m3`). Don't rely on the `$BOARD` env var — it may not be set.
- Use `--pristine` for clean rebuilds when changing boards or after significant config changes.
- Apply extra Kconfig settings via `--extra-conf myoverlay.conf` — this sets `OVERLAY_CONFIG` and merges with the project's `prj.conf`.
- The build directory defaults to `build/<board-slug>`. Override with `--build-dir` if needed.
- Build errors come back as structured JSON — check `errors[].message` for actionable error details and `raw_stderr` for the full build log. Don't try to parse raw log output.

---

## Inspecting the build

`west agent inspect` has several subcommands. Some require build artifacts (`kconfig`, `dts`, `memory`, `threads`) — build first before using those. Others (`modules`, `bindings`, `env`) work without a prior build.

### Kconfig

Use `inspect kconfig` to understand what's enabled and why:

```bash
# Look up a specific symbol and its dependency tree
west agent --format json inspect kconfig --symbol CONFIG_BT

# Search for symbols by regex pattern
west agent --format json inspect kconfig --search 'BT_.*'

# See only what the developer explicitly changed from defaults
west agent --format json inspect kconfig --changed
```

The `--symbol` output includes the dependency chain, which is invaluable for understanding *why* a symbol is enabled or disabled. When a user asks "why can't I enable X?", use `--symbol` to trace the dependency tree.

### Devicetree

```bash
# Dump the full merged DTS as JSON
west agent --format json inspect dts

# Filter to a specific node
west agent --format json inspect dts --node /soc/i2c@40003000

# Find nodes by compatible string (e.g., all SPI controllers)
west agent --format json inspect dts --compatible nordic,nrf-spim

# Show chosen node mappings (zephyr,console, zephyr,shell-uart, etc.)
west agent --format json inspect dts --chosen
```

### Memory, threads, modules, bindings

```bash
# ROM/RAM usage summary (add --detailed for per-symbol breakdown)
west agent --format json inspect memory

# Thread stack allocations
west agent --format json inspect threads

# List west modules with metadata (add --with-paths for full paths)
west agent --format json inspect modules

# Search DTS bindings by compatible string or regex
west agent --format json inspect bindings --compatible nordic,nrf-uart
west agent --format json inspect bindings --search 'spi.*controller'
```

---

## Managing Zephyr skills

Zephyr skills are modular knowledge packs (markdown files with optional code templates) that provide current, Zephyr-specific guidance on topics like BLE GATT setup, devicetree overlays, or power management. They live in `.zephyr/skills/<name>/` in the workspace.

### The anti-clobber rule

Installed skills may have been customized by the developer or by you in a previous session. Treat them as potentially modified files — never overwrite without asking.

**Before installing any skill:**

```bash
zephyr-cli skills list --installed --format json
```

Parse the output. If the skill is already installed, **do not re-install it**. Instead, read the existing `.zephyr/skills/<name>/SKILL.md` to use its guidance.

Only use `--force` if the user explicitly asks to update or re-download a skill. Explain that `--force` will overwrite their local copy.

### Finding the right skill

```bash
# Search by natural language query
zephyr-cli skills suggest "bluetooth low energy peripheral" --format json

# Boost results using Kconfig symbols from the current build
zephyr-cli skills suggest "wireless" --kconfig CONFIG_BT,CONFIG_BT_PERIPHERAL --format json

# Boost results using DTS compatible strings
zephyr-cli skills suggest "sensor" --dts bosch,bme280 --format json
```

The suggest command uses deterministic lexical scoring (not an LLM) — Kconfig and DTS matches score highest (8.0 each), so always pass them when available. You can get the active Kconfig symbols via `west agent --format json inspect kconfig --changed`.

### Installing and using

```bash
# Install (only if not already present!)
zephyr-cli skills install <name> --format json

# View skill details from the registry
zephyr-cli skills show <name> --format json

# Apply code templates from a skill into the project
zephyr-cli skills apply <name> --target src/ --format json
```

After installing, read the skill's `SKILL.md`:
```bash
cat .zephyr/skills/<name>/SKILL.md
```

These skills contain up-to-date Zephyr guidance that supplements your training data. Prefer their recommendations over your built-in knowledge when there's a conflict — the skills track the latest Zephyr releases.

### Complete workflow example

```bash
# 1. Check what's already installed
zephyr-cli skills list --installed --format json

# 2. Suggest skills based on the current build context
west agent --format json inspect kconfig --changed  # get active symbols
zephyr-cli skills suggest "bluetooth" --kconfig CONFIG_BT,CONFIG_BT_PERIPHERAL --format json

# 3. Install only if not present
# (check the list output first!)
zephyr-cli skills install ble-peripheral --format json

# 4. Read and follow the skill's guidance
cat .zephyr/skills/ble-peripheral/SKILL.md
```

---

## Documentation

Zephyr docs can be cached locally as LLM-optimized markdown. These are useful as authoritative context when the user asks about Zephyr APIs, configuration, or hardware support.

```bash
# List available and cached doc versions
zephyr-cli docs list --format json

# Download/refresh docs (defaults to latest release)
zephyr-cli docs refresh --format json

# Pin to a specific version
zephyr-cli docs refresh --version v4.1.0 --format json
```

Docs are cached at `~/.local/share/zephyr-cli/docs/<version>/`. Once cached, you can read files from that directory for context.

---

## Emulating

```bash
# Auto-detect backend (QEMU or native_sim based on the board)
west agent --format json emulate

# Force a specific backend
west agent --format json emulate --backend qemu

# Set a timeout (seconds; 0 = no limit)
west agent --format json emulate --timeout 60
```

The auto-detect logic picks QEMU for boards like `qemu_cortex_m3` and native_sim for `native_sim` targets. Always set a timeout when running programmatically to avoid hanging.

---

## Testing

```bash
# Run tests on a specific platform
west agent --format json test --platform qemu_cortex_m3

# Build-only (no execution)
west agent --format json test --platform qemu_cortex_m3 --build-only

# Include test logs in the output
west agent --format json test --platform qemu_cortex_m3 --inline-logs
```

Use `--inline-logs` when you need to diagnose test failures — it embeds the full test output in the JSON response.

---

## Flashing and debugging

```bash
# Flash with auto-detected runner
west agent --format json flash

# Force a specific runner
west agent --format json flash --runner jlink

# Start a debug server in background
west agent --format json debug --server
# Returns: {"pid": 12345, "gdb_port": 2331}

# Stream RTT output as newline-delimited JSON
west agent --format json debug --rtt-port 19021 --rtt-timeout 30
```

---

## Scaffolding new projects

```bash
# Create a standalone (T1) project
zephyr-cli create my-app --board nrf52840dk/nrf52840 --format json

# Create with MCUboot (T2) or multi-image sysbuild (T3)
zephyr-cli create my-app --topology T2 --board nrf52840dk/nrf52840 --format json
```

After scaffolding, follow the generated next-steps in the output to initialize the workspace.

---

## SDK management

```bash
# List installed SDKs (add --available to check GitHub for new versions)
zephyr-cli sdk list --available --format json

# Install a specific version
zephyr-cli sdk install 0.16.8 --format json

# Set the active SDK
zephyr-cli sdk select 0.16.8 --format json
```

---

## Key principles to remember

1. **JSON first.** Always use `--format json` when you need to parse output. Human format is for display only.
2. **Orient before acting.** Run `zephyr-cli env` at the start of every session to understand the workspace state.
3. **Don't clobber skills.** Check `skills list --installed` before installing. Never use `--force` without the user's explicit request.
4. **Use Kconfig/DTS context for skill discovery.** The `--kconfig` and `--dts` flags on `skills suggest` give much better results than plain text queries.
5. **Read installed skills.** After installing a skill, read its `SKILL.md` — it contains current best practices that may be newer than your training data.
6. **Build before inspecting (some subcommands).** The `kconfig`, `dts`, `memory`, and `threads` inspect subcommands require build artifacts. `modules`, `bindings`, and `env` work without a build.
7. **Set timeouts on emulation.** Always pass `--timeout` when running `west agent emulate` programmatically to avoid indefinite hangs.
