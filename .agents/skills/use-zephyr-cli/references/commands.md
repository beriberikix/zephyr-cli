# zephyr-cli and west agent: Complete Command Reference

This document contains the full flag tables for every command. Load it when you need exact flag names, defaults, or option details.

---

## Table of Contents

1. [zephyr-cli env](#zephyr-cli-env)
2. [zephyr-cli create](#zephyr-cli-create)
3. [zephyr-cli sdk](#zephyr-cli-sdk)
4. [zephyr-cli skills](#zephyr-cli-skills)
5. [zephyr-cli docs](#zephyr-cli-docs)
6. [west agent build](#west-agent-build)
7. [west agent inspect](#west-agent-inspect)
8. [west agent emulate](#west-agent-emulate)
9. [west agent test](#west-agent-test)
10. [west agent flash](#west-agent-flash)
11. [west agent debug](#west-agent-debug)
12. [Environment Variables](#environment-variables)
13. [Configuration Files](#configuration-files)

---

## zephyr-cli env

Print resolved Zephyr environment (SDK, west, toolchains, installed skills).

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--format` | `-f` | `json` | `json` or `human` |

---

## zephyr-cli create

Scaffold a new Zephyr project.

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--topology` | `-t` | `T1` | `T1` (standalone), `T2` (app+MCUboot), `T3` (multi-image sysbuild) |
| `--board` | `-b` | — | Target board (used in generated next-steps) |
| `--output-dir` | `-o` | cwd | Parent directory for the new project |
| `--format` | `-f` | `json` | `json` or `human` |

---

## zephyr-cli sdk

### sdk list

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--available` | — | false | Also fetch available versions from GitHub |
| `--format` | `-f` | `json` | `json` or `human` |

### sdk install \<version\>

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--minimal` | — | false | Minimal SDK (no host tools) |
| `--format` | `-f` | `json` | `json` or `human` |

### sdk select \<version\>

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--format` | `-f` | `json` | `json` or `human` |

---

## zephyr-cli skills

### skills list

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--installed` | — | false | Only show installed skills |
| `--format` | `-f` | `json` | `json` or `human` |

### skills install \<name\>

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--force` | — | false | Re-install even if already present (overwrites local changes!) |
| `--format` | `-f` | `json` | `json` or `human` |

### skills show \<name\>

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--format` | `-f` | `json` | `json` or `human` |

### skills suggest \<query\>

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--kconfig` | — | — | Comma-separated CONFIG_* symbols to boost scoring |
| `--dts` | — | — | Comma-separated DTS compatible strings to boost scoring |
| `--limit` | — | 5 | Max suggestions returned |
| `--min-score` | — | 3.0 | Absolute score floor |
| `--format` | `-f` | `json` | `json` or `human` |

### skills apply \<name\>

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--target` | `-t` | `src` | Target directory for injected templates |
| `--format` | `-f` | `json` | `json` or `human` |

---

## zephyr-cli docs

### docs list

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--format` | `-f` | `json` | `json` or `human` |

### docs refresh

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--version` | `-v` | latest | Pin to a specific docs release |
| `--format` | `-f` | `json` | `json` or `human` |

---

## west agent build

`--format` is a **top-level `west agent` flag** — place it before the subcommand: `west agent --format json build ...`. Defaults to `json` in non-TTY contexts, `human` in TTY.

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--board` | `-b` | `$BOARD` | Board target (e.g. `nrf52840dk/nrf52840`) |
| `--build-dir` | `-d` | `build/<board-slug>` | Build output directory |
| `--pristine` | `-p` | false | Clean build |
| `--extra-conf` | — | — | Extra Kconfig .conf file (sets `OVERLAY_CONFIG`) |
| `--source-dir` | `-s` | cwd | App source directory |

---

## west agent inspect

`--format` is a top-level `west agent` flag (see above). `--build-dir` / `-d` is accepted by `kconfig`, `dts`, `memory`, and `threads` (these require a prior build). The `modules`, `bindings`, and `env` subcommands do not require a build.

### inspect kconfig

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--symbol` | — | — | Single symbol + dependency tree (e.g. `CONFIG_BT`) |
| `--search` | — | — | Regex search across symbol names |
| `--changed` | — | false | Only symbols with non-default values |
| `--build-dir` | `-d` | auto | Build directory |

### inspect dts

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--node` | — | — | Filter to a specific DTS node path |
| `--compatible` | — | — | Filter by compatible string |
| `--chosen` | — | false | Show only chosen node mappings |
| `--build-dir` | `-d` | auto | Build directory |

### inspect memory

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--detailed` | — | false | Include per-symbol breakdown |
| `--build-dir` | `-d` | auto | Build directory |

### inspect threads

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--build-dir` | `-d` | auto | Build directory |

### inspect modules

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--with-paths` | — | false | Include board/DTS/Kconfig root paths |

### inspect bindings

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--compatible` | — | — | Exact compatible string (e.g. `nordic,nrf-uart`) |
| `--search` | — | — | Regex search across all bindings |
| `--dir` | — | — | Extra bindings directory (repeatable) |

### inspect env

No additional flags. Does not require a build.

---

## west agent emulate

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--backend` | `-B` | `auto` | `qemu`, `native_sim`, `docker`, `multipass`, `remote`, `auto` |
| `--timeout` | `-t` | 30 | Kill after N seconds; 0 = no limit |
| `--build-dir` | `-d` | auto | Build directory |
| `[extra_args]` | — | — | Passed verbatim to the emulator |

---

## west agent test

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--platform` | `-p` | — | Target platform (repeatable) |
| `--test-dir` | `-T` | cwd | Test directory |
| `--outdir` | `-O` | `twister-out` | Twister output directory |
| `--build-only` | — | false | Build but don't run |
| `--timeout-multiplier` | — | 1.0 | Scale all test timeouts |
| `--inline-logs` | — | false | Include test logs in JSON output |

---

## west agent flash

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--runner` | `-r` | auto | Runner (`openocd`, `jlink`, `pyocd`, etc.) |
| `--build-dir` | `-d` | auto | Build directory |
| `[extra_args]` | — | — | Passed verbatim after `--` to `west flash` |

---

## west agent debug

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--server` | — | false | Start debug server in background; returns `{pid, gdb_port}` |
| `--gdb-port` | — | 2331 (J-Link) / 3333 (OpenOCD) | GDB server port |
| `--rtt-port` | — | — | Connect to RTT TCP port; stream as NDJSON |
| `--rtt-timeout` | — | 30 | Stop RTT after N seconds of inactivity |
| `--build-dir` | `-d` | auto | Build directory |

---

## Environment Variables

| Variable | Effect |
|----------|--------|
| `ZEPHYR_BASE` | Path to Zephyr source tree. Required for `inspect kconfig`, `dts`, `bindings`. |
| `BOARD` | Fallback board for `west agent build` if `--board` not specified. |
| `ZEPHYR_SDK_INSTALL_DIR` | SDK detection for `zephyr-cli env`. |
| `ZEPHYR_CLI_SDK_PATH` | Override SDK path. |
| `ZEPHYR_CLI_SDK_VERSION` | Override SDK version. |
| `ZEPHYR_CLI_SKILLS_REGISTRY_URL` | Override skills registry URL. |
| `ZEPHYR_CLI_FORMAT` | Override default output format globally. |
| `ZEPHYR_CLI_EMULATE_BACKEND` | Override emulation backend. |
| `ZEPHYR_CLI_REMOTE_URL` | Enable remote emulation backend. |
| `OPENOCD_SCRIPTS` | Extra OpenOCD scripts search path. |

---

## Configuration Files

### Priority (highest to lowest)

1. Environment variables (`ZEPHYR_CLI_*`)
2. Workspace config: `<workspace_root>/.zephyr/config.toml`
3. User config: `~/.config/zephyr-cli/config.toml`
4. Built-in defaults

### config.toml schema

```toml
[sdk]
path = "/opt/zephyr-sdk-0.16.8"
version = "0.16.8"

[skills]
registry_url = "https://raw.githubusercontent.com/beriberikix/zephyr-agent-skills/main/index.json"

[docs]
release_base_url = "https://github.com/beriberikix/zephyrdocs.md/releases/download"

[output]
format = "json"   # "json" | "human"

[emulate]
backend = ""      # "" = auto-detect
remote_url = ""   # set to enable "remote" backend
```

### Data directory layout

```
~/.local/share/zephyr-cli/
├── sdks/               # Installed SDK versions
├── registry/
│   ├── index.json      # Cached skills registry
│   └── index.meta      # Cache timestamp
└── docs/
    └── <version>/      # Extracted docs archives
```

### Skills directory (workspace-level)

```
<workspace_root>/.zephyr/skills/<name>/
├── SKILL.md              # Primary skill instructions
├── references/           # Optional reference docs
├── assets/               # Optional code templates
└── .zephyr-skill.json    # Install metadata (name, description, installed_at, files)
```
