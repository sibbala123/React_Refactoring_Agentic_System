"""Validate the target repository build and record per-task validation artifacts."""

from __future__ import annotations

import argparse
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
from utils.subprocess_utils import run_command


LOGGER = configure_logging()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--build-command", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def validate_build(target_root: Path, run_root: Path, build_command: str, dry_run: bool = False) -> dict[str, Any]:
    manifest = read_json(run_root / "manifest.json")
    results: list[dict[str, Any]] = []

    for task in manifest.get("tasks", []):
        task_output_dir = task_dir(run_root, task["id"])
        build_log = task_output_dir / "build.log"
        if dry_run:
            validation = {
                "task_id": task["id"],
                "command": build_command,
                "success": None,
                "returncode": None,
                "status": "skipped",
            }
            build_log.write_text("Dry-run enabled; build validation skipped.\n", encoding="utf-8")
        else:
            result = run_command(build_command, cwd=target_root)
            build_log.write_text(
                "\n".join(
                    [
                        f"$ {result['command']}",
                        "",
                        "STDOUT:",
                        result["stdout"],
                        "",
                        "STDERR:",
                        result["stderr"],
                    ]
                ),
                encoding="utf-8",
            )
            validation = {
                "task_id": task["id"],
                "command": build_command,
                "success": result["returncode"] == 0,
                "returncode": result["returncode"],
                "status": "passed" if result["returncode"] == 0 else "failed",
            }
        validation["build_log"] = str(build_log)
        write_json(task_output_dir / "validation.json", validation)
        results.append(validation)

    write_json(run_root / "validation_results.json", {"tasks": results, "count": len(results)})
    return {"tasks": results, "count": len(results)}


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)
    validate_build(
        target_root=Path(args.target_root).resolve(),
        run_root=Path(args.run_root).resolve(),
        build_command=args.build_command,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
