# Zephyr CLI Agent Evaluation Findings

This is a living log from exercising zephyr-cli as an AI coding agent would use it: install the tool, discover commands, scaffold an app, iterate through build and inspection loops, and then push into network-backed and hardware-backed workflows.

## Baseline

- Date: 2026-05-01
- Repo: `beriberikix/zephyr-cli`
- Branch: `main`
- Host context at start:
  - `uv 0.11.1`
  - `cmake 4.2.3`
  - `ninja 1.13.2`
  - `ZEPHYR_BASE` unset
  - `west` initially absent from `PATH` until the evaluation venv bin directory was prefixed explicitly
- Baseline targeted tests:
  - `python -m pytest tests/integration/test_west_agent_discovery.py tests/integration/test_env_detection.py tests/integration/test_esp32_dependency_preflight.py -q`
  - Result: quiet output showed `ssssss....`, indicating the current expected discovery/env/preflight slice is at least not immediately regressing in this environment

## Confirmed Findings

### 1. `env` is highly `PATH`-sensitive and can report false negatives for tools installed in the same venv as `zephyr-cli`

- Severity: medium
- Area: environment detection / agent ergonomics
- Reproduction:
  - Without venv `PATH` prefix:
    - `/home/jonathan.beri@canonical.com/code/zephyr-cli/.venv/bin/zephyr-cli env`
  - With venv `PATH` prefix:
    - `PATH=/home/jonathan.beri@canonical.com/code/zephyr-cli/.venv/bin:$PATH /home/jonathan.beri@canonical.com/code/zephyr-cli/.venv/bin/zephyr-cli env`
- Expected:
  - When the CLI is executed from a venv-installed entry point, environment reporting should prefer the active runtime context or at least clearly distinguish `sys.executable` from `PATH` lookups.
  - `west` should not be reported unavailable if it is installed in the same venv and the command is being executed from that venv.
- Actual:
  - Without the explicit `PATH` prefix, `env` reported `west.available: false`, `west_agent_available: false`, and `python.path: /usr/bin/python3`.
  - With the explicit `PATH` prefix, the same command reported `west.available: true`, `west_agent_available: true`, and `python.path: /home/jonathan.beri@canonical.com/code/zephyr-cli/.venv/bin/python3`.
- Impact:
  - An agent can get contradictory readiness diagnostics depending on how it invokes the entry point.
  - This can lead to false blocking decisions before attempting workspace workflows.
- Recommendation:
  - Report both the runtime interpreter (`sys.executable`) and the discovered `PATH` interpreter/tools.
  - Consider checking sibling tools relative to the running interpreter's venv before treating them as unavailable.

### 2. `update --check` currently fails against PyPI with a hard 404 path

- Severity: medium
- Area: update flow / release distribution
- Reproduction:
  - `PATH=/home/jonathan.beri@canonical.com/code/zephyr-cli/.venv/bin:$PATH /home/jonathan.beri@canonical.com/code/zephyr-cli/.venv/bin/zephyr-cli update --check`
- Expected:
  - Either return the latest published version, or gracefully explain that this package/version is not published to PyPI yet.
- Actual:
  - Returned:

    ```json
    {
      "status": "error",
      "message": "Could not determine latest version from PyPI.",
      "reason": "pypi_http_404",
      "next_action": "PyPI returned HTTP 404. Try again later."
    }
    ```

- Impact:
  - The remediation is misleading if the root cause is an unpublished package or incorrect package name rather than a transient outage.
  - An agent cannot distinguish retryable infrastructure failure from product distribution state.
- Recommendation:
  - Differentiate `package_not_published` or `package_name_mismatch` from transient HTTP failures.
  - Include the exact package name queried and a more specific next action.

### 3. `env --format human` still emits JSON

- Severity: medium
- Area: output formatting / contract consistency
- Reproduction:
  - `PATH=/home/jonathan.beri@canonical.com/code/zephyr-cli/.venv/bin:$PATH /home/jonathan.beri@canonical.com/code/zephyr-cli/.venv/bin/zephyr-cli env --format human`
- Expected:
  - Human-readable rich output, or at minimum some visible change from the default JSON emission.
- Actual:
  - Output remained JSON and was indistinguishable from the default non-TTY output path.
- Impact:
  - An agent or human relying on `--format human` cannot trust that the format override is honored.
- Recommendation:
  - Validate `--format` handling consistently across all top-level commands and add explicit tests for human-format branches.

### 4. `create` generates invalid next steps for a scaffolded T1 application

- Severity: high
- Area: scaffolding / workflow guidance
- Reproduction:
  - Create app:
    - `PATH=/home/jonathan.beri@canonical.com/code/zephyr-cli/.venv/bin:$PATH /home/jonathan.beri@canonical.com/code/zephyr-cli/.venv/bin/zephyr-cli create agent-demo --topology T1 --board qemu_cortex_m3 --output-dir /tmp/zephyr-cli-agent-eval`
  - Follow generated next step:
    - `cd /tmp/zephyr-cli-agent-eval/agent-demo && west init -l .`
- Expected:
  - Generated next steps should be directly runnable, or should clearly describe that the app must be placed inside an existing west workspace.
- Actual:
  - `west init -l .` fails immediately with `FATAL ERROR: can't init: no west.yml found in /tmp/zephyr-cli-agent-eval/agent-demo`.
- Impact:
  - The scaffold output sends agents down a dead path before the first build.
- Recommendation:
  - Either generate a manifest-aware scaffold for standalone bootstrapping, or replace the next steps with instructions for adding the app to an existing Zephyr workspace.

### 5. `west agent build` is only practically usable in a workspace that exposes both Zephyr's west extensions and the zephyr-cli extension

- Severity: medium
- Area: workspace model / command discoverability
- Reproduction:
  - `west help agent` works in a workspace initialized from the zephyr-cli repo manifest.
  - `west help build` does not work in that same workspace.
  - `west help build` works in a Zephyr-seeded workspace.
  - `west help agent` only works in that Zephyr-seeded workspace after adding zephyr-cli as a project with `west-commands: west-commands.yml`.
- Expected:
  - The documented setup should make it clear how an agent gets both `west build` and `west agent` in one workspace.
- Actual:
  - A zephyr-cli-only workspace can discover `agent` but not Zephyr's `build`, `flash`, or `debug` extensions.
  - A Zephyr-only workspace can discover Zephyr extensions but not `agent` until zephyr-cli is added to the manifest.
- Impact:
  - The integration model is workable, but not obvious enough for first-time agent use.
- Recommendation:
  - Document the combined-workspace model explicitly, ideally with a minimal manifest snippet that includes both Zephyr and zephyr-cli.

### 6. `west agent build` surfaces missing Zephyr Python dependencies late, with only partial remediation

- Severity: medium
- Area: preflight / build diagnostics
- Reproduction:
  - In the combined workspace, run:
    - `west agent build --board qemu_cortex_m3 --source-dir /tmp/zephyr-cli-agent-eval/agent-demo --build-dir /tmp/zephyr-cli-agent-eval/build-qemu`
- Expected:
  - Preflight should catch missing Zephyr Python runtime dependencies before CMake, or the build result should cleanly identify the missing dependency and likely fix.
- Actual:
  - The first failure reported `Missing Python package: jsonschema` alongside an unhelpful extra parsed error `191 (message):`.
  - After installing `jsonschema`, the build moved forward but then failed on a Kconfig warning caused by missing module state.
- Impact:
  - The wrapper helps somewhat by noticing one missing package, but the error classification is noisy and incomplete.
- Recommendation:
  - Preflight the Zephyr Python environment more comprehensively and tighten stderr parsing so generic CMake location lines do not show up as standalone errors.

### 7. `west agent build` works well for `native_sim`, including `--pristine` and `--extra-conf`

- Severity: positive signal
- Area: build workflow
- Reproduction:
  - `west agent build --board native_sim --source-dir /tmp/zephyr-cli-agent-eval/agent-demo --build-dir /tmp/zephyr-cli-agent-eval/build-native-sim`
  - `west agent build --board native_sim --pristine --source-dir /tmp/zephyr-cli-agent-eval/agent-demo --build-dir /tmp/zephyr-cli-agent-eval/build-native-sim`
  - `west agent build --board native_sim --source-dir /tmp/zephyr-cli-agent-eval/agent-demo --build-dir /tmp/zephyr-cli-agent-eval/build-native-sim-debug --extra-conf /tmp/zephyr-cli-agent-eval/agent-demo/debug.conf`
- Actual:
  - All three succeeded and returned useful binary locations, including `.elf` and `.exe` paths.
- Impact:
  - This is a solid foundation for an agent-oriented edit/build loop on portable targets.

### 8. `inspect kconfig` fails against both plausible build-dir inputs

- Severity: high
- Area: artifact inspection / path handling
- Reproduction:
  - Build root form:
    - `west agent inspect kconfig --build-dir /tmp/zephyr-cli-agent-eval/build-native-sim --changed`
  - `zephyr/` subdir form:
    - `west agent inspect kconfig --build-dir /tmp/zephyr-cli-agent-eval/build-native-sim/zephyr --symbol CONFIG_LOG`
- Expected:
  - One of the common build-dir forms should work against a successful build.
- Actual:
  - Build root form failed with `kconfig_load_failed` and `[Errno 21] Is a directory: '/tmp/zephyr-cli-agent-eval/build-native-sim/Kconfig'`.
  - `zephyr/` subdir form failed with `dotconfig_not_found` even though the build had completed successfully.
- Impact:
  - A major inspection surface is not reliably usable after a successful build.
- Recommendation:
  - Normalize build-dir handling internally and test both root build directories and `zephyr/` artifact subdirectories.

### 9. `inspect dts` fails due to both missing runtime deps and ambiguous build-dir pathing

- Severity: high
- Area: artifact inspection / runtime deps
- Reproduction:
  - Build root form:
    - `west agent inspect dts --build-dir /tmp/zephyr-cli-agent-eval/build-native-sim --chosen`
  - `zephyr/` subdir form:
    - `west agent inspect dts --build-dir /tmp/zephyr-cli-agent-eval/build-native-sim/zephyr --chosen`
- Expected:
  - A successful build should enable DTS inspection with a clear accepted build-dir convention.
- Actual:
  - Root build form failed with `dts_parse_failed` and `No module named 'devicetree'`.
  - `zephyr/` form failed with `dts_not_found` because the command looked for artifacts under `/zephyr/zephyr`.
- Impact:
  - DTS inspection currently requires undocumented environment setup and still appears path-fragile afterwards.
- Recommendation:
  - Add preflight for required Zephyr Python modules and normalize artifact path resolution.

### 10. `inspect threads` did not surface a statically defined worker thread

- Severity: medium
- Area: artifact inspection / completeness
- Reproduction:
  - Build a sample app containing `K_THREAD_DEFINE(agent_worker_tid, ...)` and inspect it:
    - `west agent inspect threads --build-dir /tmp/zephyr-cli-agent-eval/build-native-sim`
- Expected:
  - The static worker thread should appear alongside `main` and `idle`.
- Actual:
  - Output only contained `idle` and `main` for both the base and debug-overlay builds.
- Impact:
  - Thread inspection looks incomplete for realistic multi-threaded apps.
- Recommendation:
  - Validate symbol discovery against statically defined threads, not just core runtime stacks.

### 11. Some inspection targets are already agent-usable

- Severity: positive signal
- Area: artifact inspection
- Confirmed working commands:
  - `west agent inspect threads --build-dir /tmp/zephyr-cli-agent-eval/build-native-sim`
  - `west agent inspect env`
  - `west agent inspect modules --with-paths`
  - `west agent inspect bindings --search 'zephyr,.*'`
- Impact:
  - Even with the pathing/runtime issues above, the inspection surface is not uniformly broken; several targets already provide structured, high-value output.

### 12. `emulate` works on `native_sim`, but currently reports timeout even after the sample app completes its logs

- Severity: low
- Area: emulation / result semantics
- Reproduction:
  - `west agent emulate --backend native_sim --timeout 3 --build-dir /tmp/zephyr-cli-agent-eval/build-native-sim`
- Expected:
  - Either report a successful short emulation session with captured output, or clearly distinguish timeout-as-session-cap from failure.
- Actual:
  - The command captured the full app log successfully, including all expected worker-thread output, but returned `status: timeout` and `error: Emulation timed out after 3.0s.`
- Impact:
  - Agents may treat a productive emulation run as a hard failure.
- Recommendation:
  - Consider distinguishing `completed_with_timeout_cap` from genuine failed emulation when useful output was captured and no crash occurred.

### 13. `test` can crash through west itself when Zephyr Twister dependencies are missing

- Severity: high
- Area: test workflow / dependency handling
- Reproduction:
  - `west agent test --platform native_sim --test-dir /tmp/zephyr-cli-agent-eval/agent-demo --outdir /tmp/zephyr-cli-agent-eval/twister-out --build-only`
- Expected:
  - Graceful reporting that Twister dependencies are missing, with a clear remediation path.
- Actual:
  - West failed to import Twister due to `ModuleNotFoundError: No module named 'natsort'`, then crashed again with `AttributeError: 'NoneType' object has no attribute 'err'` while handling the extension load failure.
- Impact:
  - This is worse than a clean dependency error; the user sees an internal traceback that obscures the actionable fix.
- Recommendation:
  - Preflight Twister dependencies before invoking `west test`, or catch extension-load failures and map them to a structured missing-dependency result.

### 14. `skills install` works cleanly in a real workspace

- Severity: positive signal
- Area: skills workflow
- Reproduction:
  - `zephyr-cli skills install connectivity-ble`
  - `zephyr-cli skills list --installed`
- Actual:
  - The skill installed into `/tmp/zephyr-combined-ws/.zephyr/skills/connectivity-ble` and then appeared in `--installed` output with path and timestamp metadata.
- Impact:
  - The core skills installation path is agent-usable when a workspace is present.

### 15. ESP32-S3 wrapper build succeeds once workspace state and Python deps are complete

- Severity: positive signal
- Area: hardware build workflow
- Reproduction:
  - Sync `hal_espressif` into the workspace and ensure `ESP_IDF_PATH` points at it.
  - Install `esptool>=5.0.2` in the active west Python runtime.
  - Run:
    - `west agent build --board esp32s3_devkitc/esp32s3/procpu --pristine --source-dir /tmp/zephyr-cli-agent-eval/agent-demo --build-dir /tmp/zephyr-cli-agent-eval/build-esp32s3`
- Actual:
  - The build succeeded and returned `zephyr.elf` and `zephyr.bin` paths.
- Impact:
  - The wrapper can support a real ESP32 target once the Zephyr workspace and Python runtime are fully provisioned.

### 16. ESP32 flash succeeded, but the structured result omitted useful fields

- Severity: medium
- Area: hardware flash workflow / output schema
- Reproduction:
  - `west agent flash --build-dir /tmp/zephyr-cli-agent-eval/build-esp32s3`
- Actual:
  - Flash succeeded end-to-end on `/dev/ttyUSB0` using the `esp32` runner.
  - Output included chip detection, write progress, verify success, and hard reset.
  - The structured result still reported `board: null` and `runner: null`.
- Impact:
  - The command works, but an agent loses important structured context that is plainly available in the raw output.
- Recommendation:
  - Populate `board` and `runner` in success results when they are known.

### 17. ESP32 debug reaches OpenOCD, then fails on missing board interface config

- Severity: medium
- Area: hardware debug workflow
- Reproduction:
  - `west agent debug --server --build-dir /tmp/zephyr-cli-agent-eval/build-esp32s3`
- Actual:
  - The wrapper rebuilt, selected the `openocd` runner, and launched OpenOCD.
  - OpenOCD then failed with `Can't find interface/esp_usb_jtag.cfg` from the board support config.
  - The wrapper returned a structured error with captured output.
- Impact:
  - Debug progresses farther than the native-sim `gdbserver` case and gives a concrete board-specific failure, but still depends on host OpenOCD script availability beyond what the CLI preflights.
- Recommendation:
  - Add preflight or clearer remediation for OpenOCD script/interface availability on ESP32 boards.

### 18. `test` remains blocked by a chain of unpreflighted Twister Python dependencies

- Severity: high
- Area: test workflow / dependency management
- Reproduction:
  - After installing `natsort`, `junitparser`, and `tabulate`, rerun:
    - `west agent test --platform native_sim --test-dir /tmp/zephyr-cli-agent-eval/agent-demo --outdir /tmp/zephyr-cli-agent-eval/twister-out --build-only`
- Actual:
  - The next failure became `ModuleNotFoundError: No module named 'psutil'`.
  - West still followed that with the same secondary `AttributeError: 'NoneType' object has no attribute 'err'` while handling extension import failure.
- Impact:
  - The command remains unusable without manually discovering and installing a moving set of Twister dependencies.
- Recommendation:
  - Replace the current trial-and-error import failures with an explicit Twister dependency check and a consolidated remediation list.

## Positive Signals So Far

- `zephyr-cli --help` is clear and concise for the global command surface.
- `sdk list --available` returned structured, useful output from the live GitHub release feed.
- `skills suggest "add BLE support" --kconfig CONFIG_BT` returned relevant ranked suggestions with enough metadata to be agent-usable.
- `docs list` returned cached and available docs metadata cleanly.
- `create` now rejects obviously invalid board strings early with a useful `invalid_board` error.
- `docs refresh` completed successfully and returned a usable cache path.
- `skills show connectivity-ble` returned a structured skill payload that is practical for agent consumption.
- A moderately richer `native_sim` app with multiple source files, logging, a worker thread, and an extra debug config overlay built successfully through `west agent build`.
- The same sample app also built successfully for `esp32s3_devkitc/esp32s3/procpu` once the combined workspace and runtime dependencies were set up.
- The ESP32 flash path worked against a connected board on `/dev/ttyUSB0`.

## Next Branches To Execute

- Exercise `docs refresh`, `skills show`, and additional human-format output paths.
- Scaffold a temporary moderately complex sample app with `create`.
- Locate or provision a real Zephyr workspace so `west agent` workflows can be exercised end to end.
- Run the ESP32 hardware pass once board identity and runner access are confirmed.