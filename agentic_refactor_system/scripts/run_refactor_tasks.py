"""Run refactor tasks through a pluggable agent adapter."""

from __future__ import annotations

import argparse
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.artifact_utils import snapshot_files
from utils.json_utils import read_json, write_json
from utils.logging_utils import configure_logging
from utils.paths import task_dir


LOGGER = configure_logging()


class BaseAgentAdapter(ABC):
    """Adapter boundary for future OpenHands, Codex, or custom agents."""

    @abstractmethod
    def execute(self, task: dict[str, Any], prompt_text: str, task_output_dir: Path) -> dict[str, Any]:
        raise NotImplementedError


class PlaceholderAgentAdapter(BaseAgentAdapter):
    """Non-destructive adapter that records a simulated attempt.

    TODO:
    - Implement OpenHandsAgentAdapter
    - Implement CodexAgentAdapter
    - Preserve scope checks before applying any generated edits
    """

    def execute(self, task: dict[str, Any], prompt_text: str, task_output_dir: Path) -> dict[str, Any]:
        attempt_text = "\n".join(
            [
                f"Task: {task['id']}",
                "Adapter: placeholder",
                "Result: simulated_only",
                "No repository edits were applied.",
                "",
                "Prompt excerpt:",
                prompt_text[:2000],
            ]
        )
        (task_output_dir / "refactor_attempt1.txt").write_text(attempt_text + "\n", encoding="utf-8")
        (task_output_dir / "refactor_attempt1.log").write_text(
            "Placeholder adapter executed. No code changes were generated.\n",
            encoding="utf-8",
        )
        return {
            "status": "simulated",
            "adapter": "placeholder",
            "applied_changes": False,
            "notes": [
                "Placeholder adapter does not edit files.",
                "Use this artifact set to integrate a real agent later.",
            ],
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--agent-adapter", default="placeholder")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def build_adapter(name: str) -> BaseAgentAdapter:
    normalized = name.lower()
    if normalized == "placeholder":
        return PlaceholderAgentAdapter()
    raise ValueError(f"Unsupported agent adapter: {name}")


def run_refactor_tasks(
    target_root: Path,
    run_root: Path,
    agent_adapter: str = "placeholder",
    dry_run: bool = False,
) -> dict[str, Any]:
    manifest = read_json(run_root / "manifest.json")
    adapter = build_adapter(agent_adapter)

    results: list[dict[str, Any]] = []
    for task in manifest.get("tasks", []):
        task_output_dir = task_dir(run_root, task["id"])
        prompt_path = task_output_dir / "prompt.txt"
        prompt_text = prompt_path.read_text(encoding="utf-8")
        pre_snapshot = snapshot_files(target_root, task["allowed_edit_scope"]["allowed_files"])
        write_json(task_output_dir / "pre_snapshot.json", pre_snapshot)

        if dry_run:
            execution = {
                "status": "skipped",
                "adapter": agent_adapter,
                "applied_changes": False,
                "notes": ["Dry-run enabled; agent execution skipped."],
            }
            (task_output_dir / "refactor_attempt1.txt").write_text(
                "Dry-run enabled. Refactor agent execution skipped.\n",
                encoding="utf-8",
            )
            (task_output_dir / "refactor_attempt1.log").write_text(
                "Dry-run enabled; no adapter invocation occurred.\n",
                encoding="utf-8",
            )
        else:
            execution = adapter.execute(task=task, prompt_text=prompt_text, task_output_dir=task_output_dir)

        task_summary = {
            "task_id": task["id"],
            "target_file": task["target_file"],
            "smell_type": task["smell_type"],
            "agent_execution": execution,
            "artifacts": {
                "prompt": str(prompt_path),
                "pre_snapshot": str(task_output_dir / "pre_snapshot.json"),
                "attempt_text": str(task_output_dir / "refactor_attempt1.txt"),
                "attempt_log": str(task_output_dir / "refactor_attempt1.log"),
            },
        }
        write_json(task_output_dir / "task_summary.json", task_summary)
        results.append(task_summary)

    write_json(run_root / "refactor_results.json", {"tasks": results, "count": len(results)})
    return {"tasks": results, "count": len(results)}


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)
    run_refactor_tasks(
        target_root=Path(args.target_root).resolve(),
        run_root=Path(args.run_root).resolve(),
        agent_adapter=args.agent_adapter,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
