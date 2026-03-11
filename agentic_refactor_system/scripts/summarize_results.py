"""Aggregate run artifacts into machine-readable and Markdown summaries."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.json_utils import read_json, validate_schema, write_json
from utils.logging_utils import configure_logging


LOGGER = configure_logging()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def summarize_results(run_root: Path) -> dict[str, object]:
    smell_report = read_json(run_root / "smell_report.json")
    manifest = read_json(run_root / "manifest.json")

    task_summaries: list[dict[str, object]] = []
    builds_passed = 0
    builds_failed = 0
    builds_skipped = 0
    attempted = 0

    for task in manifest.get("tasks", []):
        task_output_dir = run_root / "tasks" / task["id"]
        task_summary_path = task_output_dir / "task_summary.json"
        validation_path = task_output_dir / "validation.json"
        task_summary = read_json(task_summary_path) if task_summary_path.exists() else {"task_id": task["id"]}
        validation = read_json(validation_path) if validation_path.exists() else {"status": "missing"}
        merged = {
            "task_id": task["id"],
            "smell_type": task["smell_type"],
            "target_file": task["target_file"],
            "agent_status": task_summary.get("agent_execution", {}).get("status", "missing"),
            "validation_status": validation.get("status", "missing"),
            "artifacts": {
                "task_summary": str(task_summary_path),
                "validation": str(validation_path),
                "prompt": str(task_output_dir / "prompt.txt"),
            },
        }
        task_summaries.append(merged)
        if merged["agent_status"] in {"simulated", "skipped"}:
            attempted += 1
        if merged["validation_status"] == "passed":
            builds_passed += 1
        elif merged["validation_status"] == "failed":
            builds_failed += 1
        elif merged["validation_status"] == "skipped":
            builds_skipped += 1

    summary = {
        "run_root": str(run_root),
        "smells_detected": smell_report.get("smell_count", 0),
        "tasks_attempted": attempted,
        "task_count": manifest.get("task_count", 0),
        "builds_passed": builds_passed,
        "builds_failed": builds_failed,
        "builds_skipped": builds_skipped,
        "tasks": task_summaries,
    }
    write_json(run_root / "summary.json", summary)

    markdown_lines = [
        "# Run Summary",
        "",
        f"- Run root: `{run_root}`",
        f"- Smells detected: {summary['smells_detected']}",
        f"- Tasks attempted: {summary['tasks_attempted']}",
        f"- Builds passed: {summary['builds_passed']}",
        f"- Builds failed: {summary['builds_failed']}",
        f"- Builds skipped: {summary['builds_skipped']}",
        "",
        "## Tasks",
        "",
    ]
    for task in task_summaries:
        markdown_lines.append(
            f"- `{task['task_id']}` | {task['smell_type']} | `{task['target_file']}` | agent={task['agent_status']} | validation={task['validation_status']}"
        )
    (run_root / "summary.md").write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")

    schema_errors = validate_schema(summary, PROJECT_ROOT / "schemas" / "run_summary.schema.json")
    if schema_errors:
        LOGGER.warning("Run summary schema issues: %s", schema_errors)
    return summary


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)
    summarize_results(Path(args.run_root).resolve())


if __name__ == "__main__":
    main()
