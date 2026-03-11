"""Generate agent-facing task prompts from manifest entries and context artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.json_utils import read_json, write_json
from utils.logging_utils import configure_logging
from utils.paths import task_dir


LOGGER = configure_logging()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def _format_context_summary(context: dict[str, Any], template_text: str) -> str:
    import_summary = "\n".join(f"- {item}" for item in context.get("local_imports", [])) or "- none"
    related_summary = "\n".join(f"- {item}" for item in context.get("related_files", [])) or "- none"
    snippet = context.get("primary_snippet", {}).get("content", "")
    return template_text.format(
        target_file=context.get("target_file", ""),
        symbol_name=context.get("symbol_name", "unknown"),
        line_start=context.get("line_start", 1),
        line_end=context.get("line_end", 1),
        primary_snippet=snippet or "(snippet unavailable)",
        import_summary=import_summary,
        related_files_summary=related_summary,
    )


def generate_prompts(run_root: Path) -> dict[str, Any]:
    manifest = read_json(run_root / "manifest.json")
    refactor_template = (PROJECT_ROOT / "prompts" / "refactor_prompt_template.txt").read_text(encoding="utf-8")
    context_template = (PROJECT_ROOT / "prompts" / "context_summary_template.txt").read_text(encoding="utf-8")

    prompt_records: list[dict[str, Any]] = []
    for task in manifest.get("tasks", []):
        task_output_dir = task_dir(run_root, task["id"])
        context = read_json(task_output_dir / "context.json")
        context_summary = _format_context_summary(context, context_template)
        prompt_text = refactor_template.format(
            task_id=task["id"],
            repo_name=task["repo_name"],
            target_root=task["target_root"],
            smell_type=task["smell_type"],
            target_file=task["target_file"],
            symbol_name=task.get("symbol_name") or "unknown",
            line_start=task.get("line_start", 1),
            line_end=task.get("line_end", 1),
            context_files_block="\n".join(f"- {item}" for item in task["relevant_context_files"]),
            allowed_scope_block=json.dumps(task["allowed_edit_scope"], indent=2, sort_keys=True),
            context_summary=context_summary,
            task_metadata_json=json.dumps(task["metadata"], indent=2, sort_keys=True),
        )
        (task_output_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")
        write_json(
            task_output_dir / "prompt_metadata.json",
            {
                "task_id": task["id"],
                "prompt_file": str(task_output_dir / "prompt.txt"),
                "context_summary_length": len(context_summary),
            },
        )
        prompt_records.append({"task_id": task["id"], "prompt_file": str(task_output_dir / "prompt.txt")})
    result = {"generated_prompts": prompt_records, "count": len(prompt_records)}
    write_json(run_root / "prompt_index.json", result)
    return result


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)
    generate_prompts(Path(args.run_root).resolve())


if __name__ == "__main__":
    main()
