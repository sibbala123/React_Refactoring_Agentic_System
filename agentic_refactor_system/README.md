# Agentic Refactor System

`agentic_refactor_system/` is a drop-in research scaffold for running a structured, artifact-heavy React refactoring pipeline against arbitrary repositories.

It is designed for:

- detecting React code smells
- gathering bounded task context
- generating deterministic refactor manifests
- producing agent-ready prompts
- executing placeholder or pluggable refactor agents
- validating builds
- preserving artifacts for later analysis

The current implementation is a research prototype. It is modular, runnable, and safe by default, but it intentionally leaves production hardening, distributed orchestration, and final agent integrations behind clear adapter boundaries.

## Purpose

The system is meant to answer a research workflow like this:

1. choose a React codebase
2. detect smells with ReactSniffer
3. normalize the findings into a stable manifest
4. gather bounded task context
5. generate prompts for an editing agent
6. run refactor attempts
7. validate the build
8. preserve everything for later analysis

The core design assumption is that artifacts matter as much as code changes. Every stage writes its own outputs so you can inspect failures, rerun a single stage, compare different prompting strategies, and reproduce old runs.

## Architecture

The pipeline is split into independent stages:

1. `detect_smells.py`
2. `gather_context.py`
3. `build_manifest.py`
4. `generate_task_prompts.py`
5. `run_refactor_tasks.py`
6. `validate_build.py`
7. `summarize_results.py`
8. `run_pipeline.py` orchestrates the full flow

Each stage:

- accepts structured CLI inputs
- writes structured JSON artifacts
- can be executed independently for debugging

## End-To-End Flow

The expected flow is:

1. `detect_smells.py`
   Runs ReactSniffer on the target root, captures raw detector output, and normalizes file-level and component-level smell findings.
2. `gather_context.py`
   Expands each smell into a bounded context package using the target file, local imports, nearby siblings, and related files.
3. `build_manifest.py`
   Converts smells plus context into deterministic refactor tasks with stable task IDs and explicit edit scope.
4. `generate_task_prompts.py`
   Renders prompt text from templates, the smell metadata, and the gathered context.
5. `run_refactor_tasks.py`
   Executes each task through an agent adapter. The default adapter is non-destructive and writes simulated attempts only.
6. `validate_build.py`
   Runs the configured build command and records pass/fail status and logs per task.
7. `summarize_results.py`
   Produces `summary.json` and `summary.md` to aggregate the run.
8. `run_pipeline.py`
   Orchestrates all stages above in order.

In practice, the most common iteration loop is:

- rerun `detect_smells.py` when changing detector behavior
- rerun `generate_task_prompts.py` when tuning templates
- rerun `run_refactor_tasks.py` and `validate_build.py` when testing a new agent adapter

## Folder Structure

```text
agentic_refactor_system/
  README.md
  requirements.txt
  config/
    default_config.yaml
  prompts/
    refactor_prompt_template.txt
    critique_prompt_template.txt
    context_summary_template.txt
  scripts/
    build_manifest.py
    detect_smells.py
    gather_context.py
    generate_task_prompts.py
    run_pipeline.py
    run_refactor_tasks.py
    summarize_results.py
    validate_build.py
  schemas/
    manifest.schema.json
    run_summary.schema.json
    smell_report.schema.json
  examples/
    sample_config_supabase.yaml
    sample_manifest.json
  utils/
    __init__.py
    artifact_utils.py
    git_utils.py
    json_utils.py
    logging_utils.py
    manifest_utils.py
    paths.py
    subprocess_utils.py
  runs/
    .gitkeep
```

## Prerequisites

- Python 3.10+
- Optional: `git` for commit metadata
- Optional: Node tooling for actual build validation
- ReactSniffer checkout or installed CLI for real smell detection

Install Python dependencies:

```bash
pip install -r agentic_refactor_system/requirements.txt
```

## ReactSniffer Configuration

The detector stage supports two modes:

1. Real detector mode via `--reactsniffer-command` or a configured command template
2. Heuristic fallback mode when ReactSniffer is unavailable or returns nothing

Current preferred mode is the real ReactSniffer CLI integration using `--reactsniffer-root`.

### How the current integration works

ReactSniffer itself accepts a directory path and recursively scans source files. This system wraps it as follows:

1. create a temporary analysis copy under `runs/<run_id>/detector/reactsniffer_input/`
2. copy only JS/TS source files into that analysis tree
3. apply a small compatibility rewrite for modern React files that do not default-import `React`
4. run the real ReactSniffer CLI against that analysis directory
5. parse `components_smells.csv` and `files_smells.csv`
6. normalize the findings into `smell_report.json`

The original target repository is not modified.

### Why a staged analysis copy exists

It exists for two reasons:

- safety: no mutation of the target repo
- compatibility: upstream ReactSniffer misses some modern React file shapes unless the import shape looks more like older React code

The staged copy is not passed as file content. ReactSniffer still receives a path.

The adapter expects a command template that can reference:

- `{reactsniffer_root}`
- `{target_root}`
- `{output_path}`
- `{original_target_root}`

Example:

```bash
python agentic_refactor_system/scripts/detect_smells.py \
  --target-root /path/to/react/app \
  --output-root agentic_refactor_system/runs/demo_detect \
  --repo-name my_repo \
  --reactsniffer-root /path/to/reactsniffer \
  --disable-heuristic-fallback
```

If you need a custom wrapper command:

```bash
python agentic_refactor_system/scripts/detect_smells.py \
  --target-root /path/to/react/app \
  --output-root agentic_refactor_system/runs/demo_detect \
  --repo-name my_repo \
  --reactsniffer-root /path/to/reactsniffer \
  --reactsniffer-command "node {reactsniffer_root}/index.js {target_root}" \
  --disable-heuristic-fallback
```

For the full pipeline:

```bash
python agentic_refactor_system/scripts/run_pipeline.py \
  --target-root /path/to/react/app \
  --repo-name my_repo \
  --reactsniffer-root /path/to/reactsniffer \
  --build-command "pnpm build"
```

## Running The Pipeline

Full pipeline:

```bash
python agentic_refactor_system/scripts/run_pipeline.py \
  --target-root /path/to/react/app \
  --repo-name my_repo \
  --reactsniffer-root /path/to/reactsniffer \
  --build-command "pnpm build"
```

Dry-run without editing or builds:

```bash
python agentic_refactor_system/scripts/run_pipeline.py \
  --target-root /path/to/react/app \
  --repo-name my_repo \
  --reactsniffer-root /path/to/reactsniffer \
  --build-command "pnpm build" \
  --dry-run
```

Stage-by-stage debugging:

```bash
python agentic_refactor_system/scripts/detect_smells.py --target-root /path/to/app --output-root agentic_refactor_system/runs/demo --repo-name demo_repo --reactsniffer-root /path/to/reactsniffer --disable-heuristic-fallback
python agentic_refactor_system/scripts/gather_context.py --target-root /path/to/app --run-root agentic_refactor_system/runs/demo --repo-name demo_repo
python agentic_refactor_system/scripts/build_manifest.py --target-root /path/to/app --run-root agentic_refactor_system/runs/demo --repo-name demo_repo --build-command "pnpm build"
python agentic_refactor_system/scripts/generate_task_prompts.py --run-root agentic_refactor_system/runs/demo
python agentic_refactor_system/scripts/run_refactor_tasks.py --target-root /path/to/app --run-root agentic_refactor_system/runs/demo --dry-run
python agentic_refactor_system/scripts/validate_build.py --target-root /path/to/app --run-root agentic_refactor_system/runs/demo --build-command "pnpm build" --dry-run
python agentic_refactor_system/scripts/summarize_results.py --run-root agentic_refactor_system/runs/demo
```

## Artifact Outputs

Each run produces a deterministic artifact tree under:

```text
runs/<timestamp>_<repo_name>/
  config_snapshot.yaml
  git_metadata.json
  environment.json
  smell_report.json
  manifest.json
  detector/
    raw_output.txt
    normalized_smells.json
  tasks/
    <task_id>/
      smell.json
      context.json
      prompt.txt
      prompt_metadata.json
      pre_snapshot.json
      refactor_attempt1.txt
      refactor_attempt1.log
      build.log
      validation.json
      task_summary.json
  summary.json
  summary.md
```

Detector-specific artifacts also include:

- `detector/components_smells.csv` when ReactSniffer emits component findings
- `detector/files_smells.csv` when ReactSniffer emits file findings
- `detector/reactsniffer_input/` which is the staged analysis copy used for the scan

## Example: Supabase Design System

```bash
python agentic_refactor_system/scripts/run_pipeline.py \
  --target-root C:\Users\jayan\supabase-master\apps\design-system \
  --repo-name supabase_design_system \
  --reactsniffer-root C:\Users\jayan\7000 project\vendor\reactsniffer \
  --build-command "pnpm build" \
  --max-tasks 25
```

An example config is provided at [sample_config_supabase.yaml](/c:/Users/jayan/7000%20project/agentic_refactor_system/examples/sample_config_supabase.yaml).

If you want a broader scan, you can target the full repo root:

```bash
python agentic_refactor_system/scripts/detect_smells.py \
  --target-root C:\Users\jayan\supabase-master \
  --output-root agentic_refactor_system/runs/supabase_reactsniffer \
  --repo-name supabase_master \
  --reactsniffer-root C:\Users\jayan\7000 project\vendor\reactsniffer \
  --disable-heuristic-fallback
```

For day-to-day work, prefer narrower roots such as:

- `apps/design-system`
- `apps/studio`
- `apps/docs`

That keeps the finding set smaller and more actionable.

## Collaboration Guide

The repository should be treated as a research workspace, not just an app.

Recommended working style:

1. one person changes detector or parsing behavior
2. one person tunes context gathering and manifest structure
3. one person experiments with prompts and agent adapters
4. compare run artifacts instead of only comparing code diffs

Suggested collaboration rules:

- do not overwrite old run folders when comparing experiments
- use new run IDs for new detector, prompt, or adapter variants
- keep prompt changes small and attributable
- preserve raw detector outputs even if normalization changes
- keep real-agent integrations behind adapters instead of mixing them into orchestration code

If multiple contributors are working at once, agree up front on:

- target repo root
- smell types in scope
- build command
- whether edits are allowed or dry-run only
- where comparison artifacts should be stored

## Extending The System

The most likely extension points are:

- `scripts/detect_smells.py`
  for detector wrappers, better CSV parsing, or stricter filtering
- `scripts/gather_context.py`
  for code graph support or richer dependency expansion
- `scripts/run_refactor_tasks.py`
  for real OpenHands, Codex, or other agent adapters
- `prompts/`
  for different prompting strategies
- `schemas/`
  for stricter validation as the artifact model stabilizes

When adding new behavior, prefer:

- new artifact files instead of mutating old ones
- explicit metadata fields instead of hidden conventions
- deterministic IDs and ordering
- isolated script changes over implicit orchestration coupling

## Safety Model

The scaffold is safe by default:

- manifests include bounded edit scopes
- tasks record allowed files explicitly
- the default agent adapter does not apply edits
- build validation can be skipped with `--dry-run`
- all artifacts are preserved instead of overwritten in place

To support real editing agents later, plug a concrete adapter into `run_refactor_tasks.py` and preserve the existing scope checks before applying changes.

## Current Limitations

- upstream ReactSniffer has parser limitations on some modern AST shapes, so a small compatibility layer and one defensive vendor patch are currently used
- context gathering is heuristic, not graph-based
- the default agent adapter simulates execution instead of modifying code
- build validation is command-based and does not sandbox package manager side effects
- prompt critique templates are included for future agent loops but not fully exercised by the placeholder executor
- monorepo-wide scans can produce very large finding sets, so narrower app-level target roots are usually preferable
