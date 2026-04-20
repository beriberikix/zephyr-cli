# zephyr-cli

Agent-optimized CLI for Zephyr RTOS.

`zephyr-cli` is the primary interface for AI coding agents and CI pipelines to interact with, scaffold, build, and inspect Zephyr RTOS projects. It consists of a global `zephyr-cli` Python package and a `west agent` workspace extension.

## Installation

```bash
pip install zephyr-cli
```

## Usage

```bash
# Print resolved environment (SDK, west, toolchains, installed skills)
zephyr-cli env

# Print version information
zephyr-cli version

# Inside a west workspace — build with structured JSON output
west agent build --board nrf52840dk/nrf52840

# Inspect resolved Kconfig
west agent inspect kconfig --symbol CONFIG_BT

# Inspect merged Devicetree
west agent inspect dts --node /soc/uart@40002000

# Analyze ROM/RAM usage
west agent inspect memory --detailed

# Analyze thread stack allocations
west agent inspect threads
```

## Status

Phase 0 (Foundation) — in active development.

- [x] `zephyr-cli env`
- [x] `zephyr-cli version`
- [x] `west agent build`
- [x] `west agent inspect kconfig`
- [x] `west agent inspect dts`
- [x] `west agent inspect memory`
- [x] `west agent inspect threads`
- [x] `west agent inspect modules`
- [ ] Skills management (`zephyr-cli skills`) — Phase 1
- [ ] Knowledge base (`zephyr-cli docs`) — Phase 1
- [ ] Emulation (`west agent emulate`) — Phase 3

## License

Apache-2.0
