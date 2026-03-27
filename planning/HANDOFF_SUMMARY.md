# LangGraph Refactor Pipeline — Handoff Summary

**Date:** 2026-03-26
**Author:** Jayanth (primary implementer for this sprint segment)
**Repo:** https://github.com/sibbala123/React_Refactoring_Agentic_System
**Purpose:** Bring Soham and Ved up to speed on what has been built so far, what the architecture looks like, and exactly what to implement next.

---

## What We Are Building

An agentic React refactoring system that:
1. Detects code smells in React codebases using ReactSniffer
2. Classifies each smell as actionable/non-actionable using an LLM
3. Plans a bounded, tactic-guided refactor for actionable smells
4. Applies the edit via an agent
5. Verifies the result (build, type check, smell resolution)
6. Produces structured artifacts for every step

The existing system (`agentic_refactor_system/scripts/`) is a working linear 7-stage pipeline. **We are migrating it to LangGraph** — a graph-based orchestration framework where each stage is an explicit node. The new code lives in `agentic_refactor_system/langgraph_pipeline/`.

---

## Directory Structure (What Was Built)

```
agentic_refactor_system/
  langgraph_pipeline/               ← ALL NEW CODE IS HERE
    __init__.py
    state.py                        ← A1: TaskState TypedDict (shared state container)
    graph.py                        ← A2: LangGraph StateGraph wiring
    runner.py                       ← A2: run_task() and run_tasks() entry points
    tactics.py                      ← B5: React tactic library (23 tactics, 19 smell types)
    schemas/
      __init__.py
      actionability.py              ← B1: ActionabilityResult TypedDict + validation
      plan.py                       ← B3: RefactorPlan TypedDict + validation
    nodes/
      __init__.py
      classify.py                   ← B2: REAL classifier node (OpenAI API)
      plan.py                       ← B4 stub: returns status=planning, plan=None
      edit.py                       ← stub: returns no changes
      verify.py                     ← C4 stub: returns all checks skipped
      finalize.py                   ← REAL: determines terminal status, writes task_summary.json

  schemas/                          ← existing + 3 new JSON schemas
    langgraph_task_state.schema.json   ← A1
    actionability_result.schema.json   ← B1
    refactor_plan.schema.json          ← B3
    (existing schemas unchanged)
```

---

## Architecture: How Data Flows

```
Existing pipeline stages (unchanged):
  detect_smells.py → gather_context.py → build_manifest.py
                                              ↓
                                      manifest.json (list of tasks)
                                              ↓
                              NEW: langgraph_pipeline/runner.py
                                   run_tasks(tasks, smell_map, context_map)
                                              ↓
                              For each task → LangGraph graph:

  [START]
     ↓
  classify_node   ← reads: smell, context, manifest_task
     ↓                writes: actionability (ActionabilityResult)
  [route]
     ├── if non_actionable or needs_review → finalize_node (SKIPPED)
     └── if actionable ──────────────────→ plan_node
                                               ↓
                                          edit_node
                                               ↓
                                          verify_node
                                               ↓
                                          finalize_node → task_summary.json
                                               ↓
                                            [END]
```

---

## Key Data Contracts (Read These First)

### TaskState (`state.py`)
The single dict that flows through every node. Nodes receive the full state and return only the fields they changed.

```python
class TaskState(TypedDict):
    # Input (populated before graph runs)
    task_id: str
    repo_name: str
    target_file: str
    smell: dict          # full smell object from detect_smells.py
    context: dict        # full context object from gather_context.py
    manifest_task: dict  # full manifest task from build_manifest.py

    # Set by classify_node (B2)
    actionability: ActionabilityResult | None

    # Set by plan_node (B4) — YOUR STORY SOHAM
    plan: RefactorPlan | None

    # Set by edit_node (future)
    edit_result: dict | None
    changed_files: list[str]

    # Set by verify_node (C4/C5) — YOUR STORY SOHAM/VED
    verification_result: dict | None

    # Control flow
    status: str   # pending|classifying|planning|editing|verifying|accepted|rejected|skipped|failed
    skip_reason: str | None
    error: str | None
    retry_count: int
    artifact_paths: dict[str, str]  # node_name -> written file path
```

### ActionabilityResult (`schemas/actionability.py`)
```python
class ActionabilityResult(TypedDict):
    label: str           # "actionable" | "non_actionable" | "needs_review"
    rationale: str       # mandatory, must not be empty
    confidence: float    # 0.0 – 1.0
    no_op_acceptable: bool  # False when label is actionable
    caveats: list[str]
```

### RefactorPlan (`schemas/plan.py`)
```python
class RefactorPlan(TypedDict):
    tactic_name: str              # must match a name in tactics.py
    files_to_edit: list[str]      # must be subset of manifest allowed_files
    risk_level: str               # "low" | "medium" | "high"
    invariants: list[str]         # what must not change
    expected_smell_resolution: str
    abort_reasons: list[str]
```

---

## The Classifier (B2) — What It Does

**File:** `langgraph_pipeline/nodes/classify.py`

- Uses **OpenAI gpt-4o-mini** with function calling
- Requires `OPENAI_API_KEY` environment variable
- **Hard gate first:** if `smell_type` not in `KNOWN_ACTIONABLE_SMELL_TYPES` → returns `non_actionable` immediately, no API call
- System prompt includes the full smell-to-refactoring reference table
- Returns a validated `ActionabilityResult`

The 19 known actionable smell types are defined in `KNOWN_ACTIONABLE_SMELL_TYPES` in `classify.py`. Any smell type outside this set is immediately non-actionable.

**Tested on:** 14 real Supabase smells across 7 types (Large File, Large Component, Uncontrolled Component, Force Update, Too Many Props, Direct DOM Manipulation, Inheritance Instead of Composition). All labels were sensible.

---

## The Tactic Library (B5) — What It Contains

**File:** `langgraph_pipeline/tactics.py`

23 tactics covering all 19 smell types. Each tactic has:
- `name` — unique ID (e.g. `"extract_component"`)
- `display_name` — human readable
- `applies_to_smells` — list of smell types it fixes
- `preconditions` — must be true before applying
- `edit_shape` — concrete description of what the edit does
- `invariants` — what must not change (enforced by verifier)
- `risks` — `"low"` | `"medium"` | `"high"`
- `abort_if` — conditions where the edit node should stop

**Smell → Tactics mapping:**
| Smell | Tactic(s) |
|-------|-----------|
| Large Component | `extract_component`, `extract_logic_to_custom_hook`, `split_component` |
| Uncontrolled Component | `add_controlled_state` |
| Too Many Props | `split_component`, `remove_unused_props` |
| Force Update | `remove_force_update` |
| Direct DOM Manipulation | `remove_direct_dom` |
| Duplicated Code | `extract_duplicated_logic_to_hook`, `extract_duplicated_jsx_to_component` |
| Poor Names | `rename_symbol` |
| Dead Code | `remove_unused_props`, `remove_unused_state` |
| Feature Envy | `move_method_to_owner` |
| Poor Performance | `memoize_component`, `migrate_class_to_function` |
| Props in Initial State | `remove_props_in_initial_state` |
| Inheritance Instead of Composition | `use_composition` |
| JSX Outside the Render Method | `extract_jsx_to_component` |
| Low Cohesion | `extract_cohesive_component` |
| Conditional Rendering | `extract_conditional_render` |
| No Access State in setState() | `use_functional_set_state` |
| Direct Mutation of State | `replace_direct_state_mutation` |
| Dependency Smell | `replace_third_party_with_own` |
| Prop Drilling | `extract_to_context` |

**Helper functions:**
```python
from agentic_refactor_system.langgraph_pipeline.tactics import (
    get_tactic,                  # get_tactic("extract_component") -> dict
    get_tactics_for_smell,       # get_tactics_for_smell("Large Component") -> [dict, ...]
    tactic_names_for_smell,      # tactic_names_for_smell("Large Component") -> ["extract_component", ...]
)
```

---

## What Is NOT Done Yet (What Soham and Ved Need to Build)

### B4 — Planner Node (Soham, primary) ← BUILD THIS NEXT

**File to edit:** `langgraph_pipeline/nodes/plan.py`
**Current state:** Stub — returns `status=planning`, `plan=None`
**What to implement:** Replace the stub body with a real OpenAI call.

The planner node must:
1. Read `state["actionability"]` (label, rationale, caveats from B2)
2. Read `state["smell"]` and `state["context"]`
3. Read `state["manifest_task"]["allowed_edit_scope"]["allowed_files"]`
4. Look up available tactics: `tactic_names_for_smell(state["smell"]["smell_type"])`
5. Call OpenAI with a function that returns a `RefactorPlan`
6. Validate with `validate_refactor_plan(raw, allowed_files=allowed_files)`
7. Return `{"status": STATUS_PLANNING, "plan": plan}`

The function definition for the OpenAI call should match `RefactorPlan` exactly (same pattern as the classifier's `_CLASSIFY_FUNCTION`).

The prompt should include:
- The smell details and code snippet
- The actionability rationale (from B2)
- The list of available tactic names for this smell type (from `tactic_names_for_smell`)
- The full tactic definition for each candidate (from `get_tactic(name)`)
- The allowed file scope

If no tactic applies or the planner judges the edit too risky, it should set `skip_reason` and return `status=skipped` rather than producing a bad plan.

---

### A3 — Preserve Existing Artifact Flow in LangGraph (Ved, primary)

**What to implement:** Each node that produces output should write a JSON artifact into the existing run directory structure (`runs/{run_id}/tasks/{task_id}/`).

The `task_dir` path is already recorded in `state["artifact_paths"]["task_dir"]` when `run_task()` is called with `run_root`. Nodes should write their outputs like:

```python
from pathlib import Path
from ....utils.json_utils import write_json

task_dir = Path(state["artifact_paths"].get("task_dir", ""))
if task_dir:
    write_json(task_dir / "actionability.json", actionability)
    state["artifact_paths"]["classify"] = str(task_dir / "actionability.json")
```

**Finalize node already does this** for `task_summary.json` — use it as a reference.

---

### C4 — Verification Scaffold (Ved, primary)

**File to edit:** `langgraph_pipeline/nodes/verify.py`
**Current state:** Stub — all checks return "skipped"
**What to implement:**
1. Read `state["plan"]["invariants"]` — these are the things that must not change
2. Run the configured build command from `state["manifest_task"]["build_command"]`
3. Record structured results: `{"passed": bool, "checks": {"build": "pass"|"fail"|"skipped", ...}}`
4. Return `{"verification_result": result}`

Reference: the existing `validate_build.py` stage has build command execution logic to reuse.

---

### C3 — No-Op Rejection Rule (Soham, primary)

Already partially enforced in `finalize_node` — if `changed_files == []` and label was `actionable`, status becomes `REJECTED`. Soham needs to:
1. Confirm this rule is correctly applied
2. Add it to the verification node as an explicit check so it appears in `verification_result["checks"]`

---

### B6 — Tactic-Guided Edit Prompts (Ved, primary)

**File to edit:** `langgraph_pipeline/nodes/edit.py`
**Current state:** Stub — records no changes
**What to implement:**
1. Read `state["plan"]` — `tactic_name`, `files_to_edit`, `invariants`, `abort_reasons`
2. Fetch the full tactic definition: `get_tactic(state["plan"]["tactic_name"])`
3. Build a prompt that includes: tactic `edit_shape`, `invariants`, `abort_if`, code snippet, allowed files
4. Call the LLM (OpenAI) to generate the file edits
5. Apply edits to the files in the agent workspace
6. Populate `changed_files` and `edit_result`

---

### C2 — Curated Demo Benchmark (Soham, primary)

Create a JSON/CSV benchmark of 25-40 labeled tasks from the Supabase design system run. Each task should have:
- `smell_type`, `file_path`, `component`, `line_start`, `line_end`
- `actionability_label` (expected: actionable/non_actionable)
- `expected_tactic` (from the tactic library)
- `difficulty` (easy/medium/hard)
- `reviewer_notes`

Source data: `agentic_refactor_system/runs/design_system_filtered/manifest.json` (6 tasks) and `runs/supabase_reactsniffer2/detector/normalized_smells.json` (2095 smells to sample from).

---

## How to Run the Pipeline Today

```python
from agentic_refactor_system.langgraph_pipeline.runner import run_task

# Single task
final_state = run_task(
    manifest_task=manifest["tasks"][0],
    smell=smell_report["smells"][0],
    context=context_index["contexts"][0],
    run_root=Path("agentic_refactor_system/runs/design_system_filtered"),
)
print(final_state["status"])        # "rejected" (no edits yet — edit node is stub)
print(final_state["actionability"]) # populated by real classifier
print(final_state["plan"])          # None until B4 is implemented
```

---

## Environment Setup

```bash
pip install langgraph openai PyYAML jsonschema typing_extensions
export OPENAI_API_KEY=sk-your-key   # required for classify_node
```

---

## Story Status at Handoff

| StoryID | Title | Owner | Status |
|---------|-------|-------|--------|
| A1 | LangGraph State Schema | Ved | **Done** |
| B1 | Actionability Classification Schema | Jayanth | **Done** |
| B3 | Refactor Plan Schema | Soham | **Done** |
| A2 | Minimal LangGraph Pipeline | Ved | **Done** |
| B2 | Actionability Classifier Node | Jayanth | **Done** |
| B5 | React Tactic Library | Jayanth | **Done** |
| B4 | Refactor Planner Node | Soham | **Not Started** ← next priority |
| A3 | Preserve Artifact Flow | Ved | **Not Started** ← next priority |
| C4 | Verification Scaffold | Ved | **Not Started** |
| C2 | Curated Demo Benchmark | Soham | **Not Started** |
| C3 | No-Op Rejection Rule | Soham | **Partial** (in finalize_node) |
| B6 | Tactic-Guided Edit Prompts | Ved | **Not Started** (blocked on B4, B5 ✓) |
| C5 | Smell-Resolution Checks | Soham | **Not Started** |
| A4 | Resume/Retry From Node | Ved | **Not Started** |
| A5 | Node-Level CLI Progress | Jayanth | **Not Started** |
| D1 | End-to-End Demo Flow | Ved | **Not Started** |
| C6 | Demo Report | Soham | **Not Started** |
