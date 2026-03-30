"""
Run our pipeline on the same 20 smells selected by run_comparison.py.

Reads smell_index.json, builds minimal smell/context/manifest objects
from the local Supabase source, and runs the full LangGraph pipeline.
Outputs are saved to experiments/comparison/results/pipeline/

Usage:
    python experiments/run_pipeline_comparison.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentic_refactor_system.langgraph_pipeline.runner import run_task

SUPABASE_ROOT = Path("C:/Users/jayan/supabase-master")
INDEX_FILE    = Path("experiments/comparison/smell_index.json")
OUT_DIR       = Path("experiments/comparison/results/pipeline")
MAX_SNIPPET   = 200

def extract_snippet(file_path: str, line_start: int, line_end: int) -> str:
    abs_path = SUPABASE_ROOT / file_path.lstrip("/")
    if not abs_path.exists():
        return ""
    lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
    if line_start == line_end:
        if line_start <= 1:
            chunk = lines[:MAX_SNIPPET]
        else:
            start = max(0, line_start - 80)
            end   = min(len(lines), line_start + 80)
            chunk = lines[start:end]
    else:
        start = max(0, line_start - 1)
        end   = min(len(lines), line_end + 10)
        chunk = lines[start:end][:MAX_SNIPPET]
    return "\n".join(chunk)


def build_pipeline_inputs(entry: dict) -> tuple[dict, dict, dict]:
    """Build smell, context, manifest_task from a smell_index entry."""
    file_path   = entry["file_path"]
    line_start  = entry.get("line_start") or 1
    line_end    = entry.get("line_end")   or line_start
    snippet     = extract_snippet(file_path, line_start, line_end)
    task_id     = f"task_cmp_{entry['id']}"
    smell_id    = entry.get("smell_id", f"smell_cmp_{entry['id']}")

    smell = {
        "smell_id":          smell_id,
        "smell_type":        entry["smell_type"],
        "file_path":         file_path,
        "component_name":    entry["component_name"],
        "line_start":        line_start,
        "line_end":          line_end,
        "severity":          "high",
        "confidence":        0.9,
        "detector_metadata": {},
    }

    context = {
        "task_id":                task_id,
        "smell_id":               smell_id,
        "target_file":            file_path,
        "symbol_name":            entry["component_name"],
        "line_start":             line_start,
        "line_end":               line_end,
        "primary_snippet": {
            "content":    snippet,
            "start_line": line_start,
            "end_line":   line_end,
        },
        "local_imports":          [],
        "related_files":          [],
        "relevant_context_files": [file_path],
    }

    manifest_task = {
        "id":          task_id,
        "repo_name":   "supabase",
        "target_root": str(SUPABASE_ROOT),
        "smell_id":    smell_id,
        "smell_type":  entry["smell_type"],
        "target_file": file_path,
        "allowed_edit_scope": {
            "mode":          "bounded_file_and_local_imports",
            "allowed_files": [file_path],
        },
        "build_command":          "tsc",
        "validation_commands":    [],
        "relevant_context_files": [file_path],
        "metadata": {
            "severity":   "high",
            "confidence": 0.9,
        },
    }

    return smell, context, manifest_task


def main() -> None:
    if not INDEX_FILE.exists():
        sys.exit(f"ERROR: {INDEX_FILE} not found. Run run_comparison.py first.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(INDEX_FILE) as f:
        index = json.load(f)

    print(f"\n{'='*60}")
    print(f"Running pipeline on {len(index)} smells...")
    print(f"{'='*60}\n")

    summary_rows = []

    for entry in index:
        tag = entry["id"]
        print(f"[{tag}/20] {entry['smell_type']} — {entry['component_name']}")

        smell, context, manifest_task = build_pipeline_inputs(entry)

        try:
            result = run_task(
                manifest_task=manifest_task,
                smell=smell,
                context=context,
                run_root=OUT_DIR / f"task_{tag}",
                show_progress=True,
            )
            status      = result.get("status", "unknown")
            plan        = result.get("plan") or {}
            critique    = result.get("critique_result") or {}
            changed     = result.get("changed_files") or []
            verification = result.get("verification_result") or {}

            row = {
                "id":            tag,
                "smell_type":    entry["smell_type"],
                "component":     entry["component_name"],
                "file":          entry["file_path"],
                "status":        status,
                "tactic":        plan.get("tactic_name", "—"),
                "retry_count":   result.get("retry_count", 0),
                "critique_score": critique.get("score"),
                "critique_passed": critique.get("passed"),
                "changed_files": changed,
                "verify_passed": verification.get("passed"),
                "skip_reason":   result.get("skip_reason"),
                "error":         result.get("error"),
            }
        except Exception as e:
            row = {
                "id":         tag,
                "smell_type": entry["smell_type"],
                "component":  entry["component_name"],
                "file":       entry["file_path"],
                "status":     "failed",
                "error":      str(e),
            }
            print(f"  ERROR: {e}")

        summary_rows.append(row)

        # Save per-task result
        out_file = OUT_DIR / f"result_{tag}.json"
        with open(out_file, "w") as f:
            json.dump(row, f, indent=2)

    # Save combined summary
    summary_path = Path("experiments/comparison/pipeline_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary_rows, f, indent=2)

    # Print table
    print(f"\n{'='*60}")
    print("PIPELINE RESULTS")
    print(f"{'='*60}")
    print(f"{'#':<4} {'Smell Type':<32} {'Status':<12} {'Tactic'}")
    print("-" * 80)
    for r in summary_rows:
        print(
            f"{r['id']:<4} "
            f"{r['smell_type']:<32} "
            f"{r.get('status','?'):<12} "
            f"{r.get('tactic','—')}"
        )

    counts = {}
    for r in summary_rows:
        s = r.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1
    print(f"\nSummary: {counts}")
    print(f"Results saved to {summary_path}")


if __name__ == "__main__":
    main()
