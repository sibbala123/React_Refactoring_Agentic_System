"""Build a deterministic refactor task manifest from smells and gathered context."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.json_utils import read_json, validate_schema, write_json
from utils.logging_utils import configure_logging
from utils.manifest_utils import sort_smells, stable_task_id
from utils.paths import task_dir


LOGGER = configure_logging()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--repo-name", required=True)
    parser.add_argument("--build-command", required=True)
    parser.add_argument("--validation-command", action="append", default=[])
    parser.add_argument("--max-tasks", type=int, default=0)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def build_manifest(
    target_root: Path,
    run_root: Path,
    repo_name: str,
    build_command: str,
    validation_commands: list[str] | None = None,
    max_tasks: int = 0,
) -> dict[str, Any]:
    smell_report = read_json(run_root / "smell_report.json")
    contexts_index = read_json(run_root / "context_index.json")
    context_lookup = {item["task_id"]: item for item in contexts_index.get("contexts", [])}

    tasks: list[dict[str, Any]] = []
    for smell in sort_smells(smell_report.get("smells", [])):
        task_id = stable_task_id(repo_name, smell)
        context = context_lookup.get(task_id, {})
        allowed_files = [smell["file_path"], *context.get("local_imports", [])]
        allowed_files = sorted(dict.fromkeys(item for item in allowed_files if item))
        task = {
            "id": task_id,
            "repo_name": repo_name,
            "target_root": str(target_root),
            "smell_id": smell["smell_id"],
            "smell_type": smell["smell_type"],
            "target_file": smell["file_path"],
            "symbol_name": smell.get("component_name"),
            "line_start": smell.get("line_start", 1),
            "line_end": smell.get("line_end", smell.get("line_start", 1)),
            "allowed_edit_scope": {
                "mode": "bounded_file_and_local_imports",
                "allowed_files": allowed_files,
            },
            "relevant_context_files": context.get("relevant_context_files", [smell["file_path"]]),
            "build_command": build_command,
            "validation_commands": validation_commands or [],
            "task_prompt_file": f"tasks/{task_id}/prompt.txt",
            "metadata": {
                "confidence": smell.get("confidence"),
                "severity": smell.get("severity"),
                "detector_metadata": smell.get("detector_metadata", {}),
                "context_file_count": len(context.get("relevant_context_files", [])),
            },
        }
        tasks.append(task)
        write_json(task_dir(run_root, task_id) / "smell.json", smell)

    if max_tasks and max_tasks > 0:
        tasks = tasks[:max_tasks]

    manifest = {
        "run_root": str(run_root),
        "repo_name": repo_name,
        "target_root": str(target_root),
        "task_count": len(tasks),
        "tasks": tasks,
    }

    write_json(run_root / "manifest.json", manifest)
    schema_errors = validate_schema(manifest, PROJECT_ROOT / "schemas" / "manifest.schema.json")
    if schema_errors:
        LOGGER.warning("Manifest schema issues: %s", schema_errors)
    return manifest


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)
    build_manifest(
        target_root=Path(args.target_root).resolve(),
        run_root=Path(args.run_root).resolve(),
        repo_name=args.repo_name,
        build_command=args.build_command,
        validation_commands=args.validation_command,
        max_tasks=args.max_tasks,
    )


if __name__ == "__main__":
    main()
