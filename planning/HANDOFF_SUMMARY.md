# LangGraph Refactor Pipeline — Handoff Summary

**Date:** 2026-03-27 *(updated)*
**Original author:** Jayanth
**Updated by:** Soham
**Repo:** https://github.com/sibbala123/React_Refactoring_Agentic_System
**Purpose:** Up-to-date reference for the full team on what is built, what is stubbed, and what remains.

---

## What We Are Building

An agentic React refactoring system that:
1. Detects code smells in React codebases using ReactSniffer
2. Classifies each smell as actionable / non-actionable using an LLM
3. Plans a bounded, tactic-guided refactor for actionable smells
4. Applies the edit via an agent
5. Verifies the result (build, type check, smell resolution)
6. Critiques the result and retries the plan up to 3 times if quality is low
7. Produces structured JSON artifacts for every step

The existing system (`agentic_refactor_system/scripts/`) is a working linear 7-stage pipeline. **We are migrating it to LangGraph** — a graph-based orchestration framework where each stage is an explicit node. All new code lives in `agentic_refactor_system/langgraph_pipeline/`.

---

## Directory Structure (Current State)

```
agentic_refactor_system/
  langgraph_pipeline/
    __init__.py
    state.py          ← A1: TaskState TypedDict + all status constants + MAX_PLAN_RETRIES
    graph.py          ← A2: Full StateGraph topology with 6 nodes + retry routing
    runner.py         ← A2: run_task() and run_tasks() entry points
    tactics.py        ← B5: 25 React tactics across 19 smell types
    progress.py       ← A5: CLI progress printer with colour support
    schemas/
      actionability.py  ← B1: ActionabilityResult TypedDict + validation
      plan.py           ← B3: RefactorPlan TypedDict + validation
    nodes/
      classify.py     ← B2: REAL — OpenAI classifier with hard gate
      plan.py         ← B4: REAL — OpenAI planner with retry feedback
      edit.py         ← B6: STUB — always returns empty changed_files
      verify.py       ← C3: REAL no-op check / C4+C5: STUB (skipped)
      critique.py     ← REAL — OpenAI plan scorer with stub-mode awareness
      finalize.py     ← REAL — terminal status logic + task_summary.json
```

---

## Architecture: How Data Flows

```
Existing pipeline (unchanged):
  detect_smells.py → gather_context.py → build_manifest.py
                                               ↓
                                       manifest.json
                                               ↓
                           NEW: langgraph_pipeline/runner.py
                                run_tasks(tasks, smell_map, context_map)
                                               ↓
                           For each task → LangGraph graph:

  [START]
     ↓
  classify_node    ← reads: smell, context, manifest_task
     ↓               writes: actionability
  [route]
     ├── non_actionable or needs_review ──────────────→ finalize_node
     └── actionable ──────────────────────────────────→ plan_node
                                                            ↓
                                                        edit_node  (STUB)
                                                            ↓
                                                        verify_node  (partial)
                                                            ↓
                                                        critique_node
                                                            ↓
                                                    [route by score]
                                                        ├── passed ──────────→ finalize_node
                                                        ├── failed + retries → plan_node (loop)
                                                        └── retry limit hit ─→ finalize_node
                                                                                     ↓
                                                                                   [END]
```

**Retry loop:** `plan → edit → verify → critique → plan` up to `MAX_PLAN_RETRIES = 3` times.
On each retry, `critique_node` writes structured feedback to `state["plan_feedback"]` which `plan_node` prepends to its next prompt.

---

## Node Status at a Glance

| Node | Story | Status | What it does |
|------|-------|--------|-------------|
| `classify_node` | B2 | **REAL** | Calls OpenAI gpt-4o-mini; hard-gates unknown smell types; returns ActionabilityResult |
| `plan_node` | B4 | **REAL** | Calls OpenAI gpt-4o-mini; picks tactic from library; handles retry feedback; returns RefactorPlan |
| `edit_node` | B6 | **STUB** | Returns `changed_files=[]`, `edit_result={"stub": True}` — no file changes ever |
| `verify_node` | C3/C4/C5 | **PARTIAL** | C3 no-op check is real; `parse`, `build`, `typecheck`, `smell_resolved` all return `"skipped"` |
| `critique_node` | — | **REAL** | Calls OpenAI gpt-4o-mini; scores plan 0.0–1.0; sets `plan_feedback` on failure; stub-mode aware |
| `finalize_node` | — | **REAL** | Determines terminal status (ACCEPTED/REJECTED/SKIPPED/FAILED); writes task_summary.json |

---

## Key Data Contracts

### TaskState (`state.py`)
```python
class TaskState(TypedDict):
    # Input
    task_id: str
    repo_name: str
    target_file: str
    smell: dict            # from detect_smells.py
    context: dict          # from gather_context.py
    manifest_task: dict    # from build_manifest.py

    # classify_node (B2)
    actionability: ActionabilityResult | None

    # plan_node (B4)
    plan: RefactorPlan | None

    # edit_node (B6 — stub)
    edit_result: dict | None
    changed_files: list[str]

    # verify_node (C3 real / C4+C5 stub)
    verification_result: dict | None

    # critique_node
    critique_result: dict | None   # {score, passed, issues, feedback, threshold}

    # Control flow
    status: str            # pending|classifying|planning|editing|critiquing|
                           #   verifying|accepted|rejected|skipped|failed
    skip_reason: str | None
    error: str | None
    retry_count: int       # incremented by plan_node on each retry
    plan_feedback: str | None  # set by critique_node; cleared by plan_node after reading

    artifact_paths: dict[str, str]   # node_name → file path
```

**Constants:**
- `MAX_PLAN_RETRIES = 3` — plan + edit + verify + critique cycles before giving up
- `CRITIQUE_THRESHOLD = 0.7` — score below this triggers a retry

### ActionabilityResult (`schemas/actionability.py`)
```python
class ActionabilityResult(TypedDict):
    label: str           # "actionable" | "non_actionable" | "needs_review"
    rationale: str       # mandatory, must not be empty
    confidence: float    # 0.0 – 1.0
    no_op_acceptable: bool
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

## The Classifier (B2)

**File:** `nodes/classify.py`

- Uses **gpt-4o-mini** with function calling, `temperature=0`
- **Hard gate first:** if `smell_type` not in `KNOWN_ACTIONABLE_SMELL_TYPES` (19 types) → returns `non_actionable` immediately, no API call
- This eliminates `Large File` (42% of supabase_full) with zero API cost
- Returns a validated `ActionabilityResult`

---

## The Planner (B4)

**File:** `nodes/plan.py`

- Uses **gpt-4o-mini** with function calling, `temperature=0`
- Receives full tactic definitions from `tactics.py` for all candidate tactics
- If model returns `tactic_name="NO_TACTIC"` → sets `skip_reason`, status=skipped
- **Retry-aware:** reads `state["plan_feedback"]`, prepends a "REVISION REQUESTED" block to the prompt, increments `retry_count`, clears `plan_feedback` after reading
- Validates plan against `allowed_files` from manifest before accepting

---

## The Tactic Library (B5)

**File:** `tactics.py` — **25 tactics** across 19 smell types.

| Smell Type | Tactic(s) |
|------------|-----------|
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

```python
from agentic_refactor_system.langgraph_pipeline.tactics import (
    get_tactic,               # get_tactic("extract_component") -> dict
    get_tactics_for_smell,    # get_tactics_for_smell("Large Component") -> [dict, ...]
    tactic_names_for_smell,   # tactic_names_for_smell("Large Component") -> ["extract_component", ...]
)
```

---

## The Critique Node

**File:** `nodes/critique.py`

- Uses **gpt-4o-mini** with function calling, `CRITIQUE_THRESHOLD = 0.7`
- Scores the plan on 5 criteria: verification results, edit adherence, invariant specificity, abort reason concreteness, tactic appropriateness
- **Stub-mode aware:** when `edit_result["stub"] == True`, skips criteria 1 and 2 (no file changes to evaluate) and scores on plan quality alone — plans with specific invariants and concrete abort_reasons score >= 0.8
- If `score < 0.7`: writes structured feedback to `state["plan_feedback"]` (includes verification failures + issue list + guidance)
- `_route_after_critique()` in graph.py then routes back to `plan_node` if retries remain

---

## What Is NOT Done Yet

### B6 — Tactic-Guided Edit Node (Ved, primary) ← HIGHEST PRIORITY
**File:** `nodes/edit.py`
**Current state:** Stub — always returns `changed_files=[]`

Must implement:
1. Read `state["plan"]` — `tactic_name`, `files_to_edit`, `invariants`, `abort_reasons`
2. Fetch full tactic: `get_tactic(state["plan"]["tactic_name"])`
3. Build prompt with: `edit_shape`, `invariants`, `abort_if`, code snippet, allowed files
4. Call LLM to generate file edits
5. Apply edits to files in workspace
6. Populate `changed_files` and `edit_result` (include `edit_result["diffs"]` for critique)

Once B6 is done, critique will be able to check edit adherence and the pipeline will produce first `ACCEPTED` outcomes.

### C4 — Build Verification (Ved, primary)
**File:** `nodes/verify.py`
**Current state:** `parse`, `build`, `typecheck` all return `"skipped"`

Must implement:
1. Run `state["manifest_task"]["build_command"]` in the repo workspace
2. Record `"pass"` or `"fail"` per check
3. Surface failures as input to critique's feedback generation

Reference: existing `validate_build.py` stage has build command execution logic.

### C2 — Curated Demo Benchmark (Soham, primary)
Create `data/benchmark.json` — 25–40 manually labeled tasks sampled from `supabase_full`:
- Fields: `smell_type`, `file_path`, `component`, `line_start`, `line_end`, `expected_actionability`, `expected_tactic`, `difficulty`, `reviewer_notes`
- Source: `data/supabase_full/detector/normalized_smells.json` (2095 smells) + `data/supabase_design_system/`
- Required for RQ1 and RQ2 in Milestone 3

### C5 — Smell-Resolution Checks (Soham, primary)
**File:** `nodes/verify.py`
**Current state:** `smell_resolved` returns `"skipped"`

Extend verify_node to confirm the target smell is no longer present after the edit. Implement independently of C4.

### C6 — Demo Report (Soham)
Blocked until D1 (end-to-end demo) is done.

### D1 — End-to-End Demo Flow (Ved)
Blocked until B6 and C4 are done.

---

## Story Status (Updated 2026-03-27)

| StoryID | Title | Owner | Status |
|---------|-------|-------|--------|
| A1 | LangGraph State Schema | Ved | **Done** |
| A2 | Minimal LangGraph Pipeline | Ved | **Done** |
| A5 | Node-Level CLI Progress | Jayanth | **Done** |
| B1 | Actionability Classification Schema | Jayanth | **Done** |
| B2 | Actionability Classifier Node | Jayanth | **Done** |
| B3 | Refactor Plan Schema | Soham | **Done** |
| B4 | Refactor Planner Node | Soham | **Done** |
| B5 | React Tactic Library | Jayanth | **Done** |
| C3 | No-Op Rejection Rule | Soham | **Done** |
| Critique Node | Plan scoring + retry loop | Jayanth | **Done** |
| B6 | Tactic-Guided Edit Node | Ved | **Done** |
| C4 | Build Verification Scaffold | Ved | **Done** |
| C2 | Curated Demo Benchmark | Soham | **Done** |
| C5 | Smell-Resolution Checks | Soham | **Done** |
| A3 | Preserve Artifact Flow | Ved | **Not Started** |
| A4 | Resume/Retry From Node | Ved | **Not Started** |
| D1 | End-to-End Demo Flow | Ved | **Done** |
| C6 | Demo Report | Soham | **Done** |

**Critical path to first ACCEPTED outcome:** B6 → D1 (COMPLETED DURING MILESTONE 3)


---

## How to Run

```bash
# activate venv
source venv/Scripts/activate   # Windows: venv\Scripts\activate

# ensure API key is set in .env
# OPENAI_API_KEY=sk-...

# run integration test (10 tasks, classify + plan + critique)
python test_pipeline.py
```

```python
from agentic_refactor_system.langgraph_pipeline.runner import run_task
from pathlib import Path

final_state = run_task(
    manifest_task=manifest["tasks"][0],
    smell=smell_report["smells"][0],
    context=context_index["contexts"][0],
    run_root=Path("agentic_refactor_system/runs/design_system_filtered"),
)

print(final_state["status"])          # "rejected" (edit stub → C3 no-op fires)
print(final_state["actionability"])   # populated by real classifier
print(final_state["plan"])            # populated by real planner
print(final_state["critique_result"]) # populated by real critique node
```

**Expected current output per task:**
```
classify   → actionable / non_actionable / needs_review
plan       → tactic + risk + invariants + abort_reasons  (if actionable)
edit       → stub (0 files changed)
verify     → FAIL  no_op=fail  (C3)
critique   → score >= 0.8 in stub mode (does not penalise for missing edits)
finalize   → REJECTED  (no file changes on actionable task)
```

---

## Environment

```bash
pip install -r requirements.txt   # langgraph openai PyYAML jsonschema typing_extensions python-dotenv
# set OPENAI_API_KEY in .env
```

Required for: `classify_node`, `plan_node`, `critique_node` (all three call OpenAI).
