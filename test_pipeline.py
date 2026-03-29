"""
Integration test for classify_node → plan_node pipeline.

Uses:
  - 6 real tasks from data/supabase_design_system/ (manifest + context)
  - 4 synthesised tasks from data/supabase_full/detector/normalized_smells.json
    (diverse smell types, minimal context constructed inline)

Run:
    python test_pipeline.py
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path
from dotenv import load_dotenv

# ── Load .env ──────────────────────────────────────────────────────────────────
load_dotenv()

if not os.environ.get("OPENAI_API_KEY"):
    sys.exit("ERROR: OPENAI_API_KEY not set. Add it to .env and retry.")

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
DESIGN_SYS = ROOT / "data" / "supabase_design_system"
FULL = ROOT / "data" / "supabase_full"

# ── Load design-system data ────────────────────────────────────────────────────
manifest_data = json.loads((DESIGN_SYS / "manifest.json").read_text())
context_data = json.loads((DESIGN_SYS / "context_index.json").read_text())
smell_report = json.loads((DESIGN_SYS / "smell_report.json").read_text())

ds_tasks = manifest_data["tasks"]

# Build lookups keyed by task_id
context_by_task: dict[str, dict] = {c["task_id"]: c for c in context_data["contexts"]}
smell_by_id: dict[str, dict] = {s["smell_id"]: s for s in smell_report["smells"]}

# ── Build the 6 real tasks ────────────────────────────────────────────────────
real_tasks = []
for mt in ds_tasks:
    tid = mt["id"]
    sid = mt["smell_id"]
    ctx = context_by_task.get(tid, {})
    smell = smell_by_id.get(sid, {})
    if not smell:
        # Fall back to reconstructing from manifest metadata
        smell = {
            "smell_id": sid,
            "smell_type": mt["smell_type"],
            "file_path": mt["target_file"],
            "line_start": mt["line_start"],
            "line_end": mt["line_end"],
            "component_name": mt.get("symbol_name"),
            "severity": mt["metadata"].get("severity", "medium"),
            "confidence": mt["metadata"].get("confidence", 0.8),
            "detector_metadata": mt["metadata"].get("detector_metadata", {}),
        }
    real_tasks.append((mt, smell, ctx))

# ── Synthesise 4 extra tasks from supabase_full smells ───────────────────────
full_smells_data = json.loads((FULL / "detector" / "normalized_smells.json").read_text())
all_full_smells = full_smells_data["smells"]

# Pick one smell of each underrepresented type for diversity
TARGET_TYPES = [
    "Too Many Props",
    "Large File",
    "Direct DOM Manipulation",
    "Uncontrolled Component",
]

synth_tasks = []
used_types: set[str] = set()
for s in all_full_smells:
    stype = s["smell_type"]
    if stype in TARGET_TYPES and stype not in used_types:
        used_types.add(stype)
        task_id = f"synth_{s['smell_id']}"
        manifest_task = {
            "id": task_id,
            "repo_name": "supabase",
            "target_file": s["file_path"],
            "smell_id": s["smell_id"],
            "smell_type": stype,
            "symbol_name": s.get("component_name"),
            "line_start": s.get("line_start", 1),
            "line_end": s.get("line_end", 50),
            "allowed_edit_scope": {
                "mode": "bounded_file_and_local_imports",
                "allowed_files": [s["file_path"]],
            },
            "build_command": "pnpm build",
            "validation_commands": [],
            "metadata": {
                "severity": s.get("severity", "medium"),
                "confidence": s.get("confidence", 0.8),
                "detector_metadata": s.get("detector_metadata", {}),
            },
            "relevant_context_files": [s["file_path"]],
        }
        context = {
            "task_id": task_id,
            "smell_id": s["smell_id"],
            "target_file": s["file_path"],
            "symbol_name": s.get("component_name"),
            "line_start": s.get("line_start", 1),
            "line_end": s.get("line_end", 50),
            "primary_snippet": {
                "content": "(source file not available in test environment)",
                "start_line": s.get("line_start", 1),
                "end_line": s.get("line_end", 50),
            },
            "local_imports": [],
            "related_files": [],
            "relevant_context_files": [s["file_path"]],
        }
        synth_tasks.append((manifest_task, s, context))
    if len(used_types) == len(TARGET_TYPES):
        break

# ── Combined test set ─────────────────────────────────────────────────────────
all_test_tasks = real_tasks + synth_tasks
print(f"\n{'='*70}")
print(f"  PIPELINE TEST  —  {len(all_test_tasks)} tasks")
print(f"{'='*70}")
print(f"  {len(real_tasks)} real tasks   (supabase_design_system)")
print(f"  {len(synth_tasks)} synth tasks  (supabase_full diverse types)")
print(f"{'='*70}\n")

# ── Run pipeline ──────────────────────────────────────────────────────────────
from agentic_refactor_system.langgraph_pipeline.runner import run_task  # noqa: E402

results = []
for i, (mt, smell, ctx) in enumerate(all_test_tasks, 1):
    print(f"\n[{i:02d}/{len(all_test_tasks)}] task={mt['id']}  type={smell.get('smell_type')}  file={mt['target_file']}")
    mt["build_command"] = ""
    state = run_task(mt, smell, ctx, show_progress=True)
    results.append(state)

# ── Results table ─────────────────────────────────────────────────────────────
DIVIDER = "-" * 70
print(f"\n\n{'='*70}")
print("  RESULTS SUMMARY")
print(f"{'='*70}")

status_counts: dict[str, int] = {}

for i, (state, (mt, smell, _)) in enumerate(zip(results, all_test_tasks), 1):
    status = state.get("status", "unknown")
    status_counts[status] = status_counts.get(status, 0) + 1

    actionability = state.get("actionability") or {}
    plan = state.get("plan")
    skip_reason = state.get("skip_reason", "")
    error = state.get("error", "")

    print(f"\n[{i:02d}] {mt['id']}")
    print(f"     smell_type : {smell.get('smell_type')}")
    print(f"     file       : {mt['target_file']}")
    print(f"     status     : {status}")

    if actionability:
        print(f"     classify   : label={actionability.get('label')}  conf={actionability.get('confidence', 0):.2f}")
        rationale = actionability.get("rationale", "")
        if rationale:
            print(f"     rationale  : {textwrap.shorten(rationale, 80)}")

    if plan:
        print(f"     plan       : tactic={plan.get('tactic_name')}  risk={plan.get('risk_level')}")
        print(f"     files_edit : {plan.get('files_to_edit')}")
        resolution = plan.get("expected_smell_resolution", "")
        if resolution:
            print(f"     resolution : {textwrap.shorten(resolution, 80)}")
        if plan.get("invariants"):
            print(f"     invariants : {plan['invariants']}")
        if plan.get("abort_reasons"):
            print(f"     abort_if   : {plan['abort_reasons']}")
    elif status == "skipped" and skip_reason:
        print(f"     skip       : {textwrap.shorten(skip_reason, 80)}")
    elif error:
        print(f"     error      : {textwrap.shorten(error, 80)}")

    print(DIVIDER)

# ── Connectivity verification ─────────────────────────────────────────────────
print(f"\n{'='*70}")
print("  NODE CONNECTIVITY CHECK")
print(f"{'='*70}")

classify_ran = sum(1 for s in results if s.get("actionability") is not None)
plan_ran = sum(1 for s in results if s.get("plan") is not None)
no_tactic_skip = sum(
    1 for s in results
    if s.get("status") == "skipped" and s.get("skip_reason") and s.get("actionability") is not None
    and s["actionability"].get("label") == "actionable"
)

print(f"\n  classify_node ran   : {classify_ran}/{len(results)} tasks  {'OK' if classify_ran == len(results) else 'INCOMPLETE'}")
print(f"  plan_node ran       : {plan_ran}/{len(results)} tasks produced a plan")
print(f"  plan_node skipped   : {no_tactic_skip} tasks (NO_TACTIC — no suitable tactic)")
print(f"\n  Status breakdown:")
for status, count in sorted(status_counts.items()):
    print(f"    {status:<12}: {count}")

# Verify chain: every actionable smell that got a plan had classify run first
chain_ok = all(
    s.get("actionability") is not None
    for s in results
    if s.get("plan") is not None
)
print(f"\n  classify -> plan chain intact: {'YES' if chain_ok else 'NO - missing actionability on planned tasks'}")
print(f"\n{'='*70}\n")
