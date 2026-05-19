# Zephyr-CLI Benchmark & Eval Framework

Measures two things about `zephyr-cli` and its companion `zephyr-agent-skills`:

1. **Accuracy** — does an AI coding agent generate better Zephyr RTOS code
   *with* the CLI + skills + docs than *without* them?
2. **Token efficiency** — is any accuracy gain bought with excess tokens, and
   where is token waste that could be trimmed?

Accuracy and token efficiency are reported as **two parallel axes**. "Did
accuracy improve *without* token bloat" is inherently a two-variable question,
so the token metrics are never folded into the quality score.

## Design

The open-source coding agent [OpenCode](https://github.com/anomalyco/opencode)
is given identical task prompts under two conditions:

| Condition | Skills | Docs corpus | zephyr-cli in PATH |
|-----------|--------|-------------|--------------------|
| **Baseline** | disabled | not provisioned | no (stripped from PATH) |
| **Treatment** | `zephyr-agent-skills` symlinked into `.agents/skills/` | symlinked into `.agents/docs/` | yes |

Every task is run under **each model** (the framework is built to compare e.g.
Opus and Sonnet); accuracy and token metrics are reported **per model** and
never averaged across models, because token magnitudes differ wildly between
models.

## Accuracy — six scoring dimensions

Generated projects are scored by `evaluate.py` / `scoring.py`:

| Dimension | Weight | Description |
|-----------|-------:|-------------|
| Compilability | 20% | Does `west build` succeed? Warning count? |
| Correctness | 25% | Does the binary run and produce expected output? |
| Best practices | 15% | Presence of recommended patterns (e.g. `find_package(Zephyr)`) |
| API freshness | 10% | Absence of deprecated API usage |
| Completeness | 15% | Are all expected files present? |
| Config quality | 15% | Expected Kconfig symbols present in `prj.conf` |

## Token efficiency — a parallel axis

`run.py` parses the OpenCode JSONL transcript (`transcript.py`) into a
`usage.json` per run with **token aggregates** (input / output / reasoning /
cache-read / cache-write, and the processed-token total) and **process
metrics** (tool-call counts, `zephyr-cli` invocations, build attempts, failed
builds, retries, and an estimate of tokens burned in failed-build retry loops).

`efficiency.py` turns those into directional metrics — tokens per task, tokens
per quality point, cache-read ratio, tool-output token share, retry-waste
share — and `report.py` renders a per-model **verdict** crossing the two axes
(e.g. *"accuracy +6.7%, processed tokens −12.3% → Win-win"*).

## Component evals

Beyond the end-to-end benchmark, two component evals isolate specific resources:

- **Skills-suggest matcher** (`tests/test_suggest_eval.py`,
  `tests/suggest_eval.py`) — a 276-query labelled corpus measuring Recall@1/@3,
  false-positive rate, and MRR for `zephyr-cli skills suggest`. Runs in CI.
- **Docs grounding** (`docs_eval.py`, `data/docs_eval/questions.jsonl`) — a
  small hand-curated set of version-specific Zephyr questions answered with vs
  without the docs corpus on disk. *Directional only* — see the caveats in
  `docs_eval.py`.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for virtual-environment and package management
- [OpenCode](https://github.com/anomalyco/opencode) v1.14+ (`opencode` on PATH),
  authenticated for the models under test
- A configured Zephyr SDK / west workspace (for `west build` during evaluation)
- **zephyr-agent-skills** checked out as a sibling directory (`../zephyr-agent-skills`)

## Quick Start

```bash
# 0. Create a venv and install dependencies (from repo root)
uv venv .venv
source .venv/bin/activate
uv pip install -e . -e benchmarks/

# 1. Run the benchmark under both models (generates code via OpenCode)
python -m benchmarks.run \
    --models anthropic/claude-opus-4-6,anthropic/claude-sonnet-4-6 \
    --native-sim-only

# 2. Evaluate the generated projects (scores + backfills usage.json)
python -m benchmarks.evaluate

# 3. Generate the Markdown report (accuracy + token efficiency, per model)
python -m benchmarks.report --output report.md
```

All commands run from the **repository root** (`zephyr-cli/`), not from inside
`benchmarks/`.

To recompute token/process metrics over an existing result tree without
re-running agents:

```bash
python -m benchmarks.usage --force
```

## CLI Reference

### `benchmarks.run`

```
python -m benchmarks.run (--models <list> | --model <one>) [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--models` | *(required\*)* | Comma-separated `provider/model` list |
| `--model` | *(required\*)* | A single `provider/model` (alias for `--models`) |
| `--board` | `esp32s3_devkitc/esp32s3/procpu` | Board for hardware tasks |
| `--tasks` | all | Comma-separated task names |
| `--runs` | 3 | Runs per task per condition |
| `--condition` | both | `baseline`, `treatment`, or `both` |
| `--native-sim-only` | off | Skip hardware tasks |
| `--no-usage` | off | Skip deriving `usage.json` after each run |

\* one of `--models` / `--model` is required.

Results: `benchmarks/results/<model_slug>/<task>/<condition>/run_<N>/`.

### `benchmarks.usage`

```
python -m benchmarks.usage [--results-dir DIR] [--force]
```

Backfills `usage.json` (token + process metrics) for any run with a saved
`stdout.txt` transcript. Safe to re-run; `--force` recomputes existing files.

### `benchmarks.evaluate`

```
python -m benchmarks.evaluate [--results-dir DIR] [--skip-build] [--zephyr-base PATH]
```

Writes `evaluation.json` per run; generates `usage.json` if missing.

### `benchmarks.report`

```
python -m benchmarks.report [--results-dir DIR] [--output FILE]
```

Markdown report: a per-model section (quality table, token-efficiency verdict +
tables, per-task token deltas, win-rate, per-task breakdown), a cross-model
comparison table, and any component-eval artifacts (`suggest-eval.json`,
`docs-eval.json`) found in the results directory.

### `benchmarks.docs_eval`

```
python -m benchmarks.docs_eval (--models <list> | --model <one>)
```

Runs the docs grounding eval; writes `results/docs-eval.{json,md}`.

## Per-run outputs

| File | What |
|------|------|
| `metadata.json` | Provenance: task, model, condition, timing, `docs_provisioned` |
| `stdout.txt` | Verbatim OpenCode JSONL transcript |
| `usage.json` | Derived token + process metrics |
| `evaluation.json` | Quality scores across the six dimensions |

## Tasks

Twelve tasks spanning simple and medium difficulty across `native_sim` and
hardware boards. Definitions live in `tasks/*.yml`.

| Task | Board | Difficulty |
|------|-------|------------|
| `blinky` | hardware | simple |
| `hello-shell` | native_sim | simple |
| `logging-levels` | native_sim | simple |
| `thread-sync` | native_sim | simple |
| `ble-peripheral` | hardware | medium |
| `flash-storage` | hardware | medium |
| `sensor-polling` | hardware | medium |
| `wifi-http` | hardware | medium |
| `zbus-pubsub` | native_sim | medium |
| `ztest-unit` | native_sim | medium |
| `settings-shell` | native_sim | medium |
| `smf-state-machine` | native_sim | medium |

## Directory Structure

```
benchmarks/
├── README.md
├── configs/              # baseline.opencode.json, treatment.opencode.json
├── data/
│   └── docs_eval/        # questions.jsonl for the docs grounding eval
├── tasks/                # *.yml task definitions
├── tests/                # unit tests for the pure modules (transcript, …)
├── deprecated_apis.yml
├── run.py                # drives OpenCode; writes metadata + usage.json
├── transcript.py         # OpenCode JSONL → token/process metrics (pure)
├── usage.py              # backfills usage.json from saved transcripts
├── evaluate.py           # scores generated projects → evaluation.json
├── scoring.py            # the six weighted quality dimensions
├── efficiency.py         # token-efficiency metrics (pure)
├── report.py             # per-model Markdown report
├── docs_eval.py          # docs grounding component eval
└── results/              # git-ignored, generated at runtime
```
