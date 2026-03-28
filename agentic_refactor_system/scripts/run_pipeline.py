"""Orchestrate the full agentic refactor research pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from build_manifest import build_manifest
from detect_smells import detect_smells
from gather_context import gather_context
from generate_task_prompts import generate_prompts
from run_refactor_tasks import run_refactor_tasks
from summarize_results import summarize_results
from validate_build import validate_build
from utils.artifact_utils import write_environment_metadata
from utils.git_utils import collect_git_metadata
from utils.json_utils import read_yaml, write_json, write_yaml
from utils.logging_utils import configure_logging
from utils.paths import ensure_dir, make_run_id


LOGGER = configure_logging()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", required=True)
    parser.add_argument("--repo-name", required=True)
    parser.add_argument("--reactsniffer-root", default="")
    parser.add_argument("--reactsniffer-command", default="")
    parser.add_argument("--build-command", required=True)
    parser.add_argument("--output-root", default=str(PROJECT_ROOT / "runs"))
    parser.add_argument("--max-tasks", type=int, default=0)
    parser.add_argument("--smell-types", nargs="*", default=[])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "default_config.yaml"))
    parser.add_argument("--agent-adapter", default="placeholder")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def run_pipeline(args: argparse.Namespace) -> Path:
    config = read_yaml(Path(args.config).resolve())
    target_root = Path(args.target_root).resolve()
    output_root = Path(args.output_root).resolve()
    ensure_dir(output_root)

    run_id = make_run_id(args.repo_name)
    run_root = ensure_dir(output_root / run_id)

    config_snapshot = {
        "cli_args": vars(args),
        "default_config": config,
        "resolved": {
            "target_root": str(target_root),
            "output_root": str(output_root),
            "build_command": args.build_command,
            "reactsniffer_command": args.reactsniffer_command,
        },
    }
    write_yaml(run_root / "config_snapshot.yaml", config_snapshot)
    write_json(run_root / "git_metadata.json", collect_git_metadata(target_root))
    write_environment_metadata(run_root, build_command=args.build_command)

    LOGGER.info("Stage 1/7: detect smells")
    detect_smells(
        target_root=target_root,
        output_root=run_root,
        repo_name=args.repo_name,
        reactsniffer_root=args.reactsniffer_root,
        reactsniffer_command=args.reactsniffer_command,
        smell_types=args.smell_types,
        disable_heuristic_fallback=not config.get("detector", {}).get("heuristic_fallback", True),
    )

    LOGGER.info("Stage 2/7: gather context")
    gather_context(
        target_root=target_root,
        run_root=run_root,
        repo_name=args.repo_name,
        max_context_files=config.get("context", {}).get("max_context_files", 8),
        snippet_radius=config.get("context", {}).get("snippet_radius", 30),
    )

    LOGGER.info("Stage 3/7: build manifest")
    build_manifest(
        target_root=target_root,
        run_root=run_root,
        repo_name=args.repo_name,
        build_command=args.build_command,
        validation_commands=config.get("manifest", {}).get("validation_commands", []),
        max_tasks=args.max_tasks,
    )

    LOGGER.info("Stage 4/7: generate prompts")
    generate_prompts(run_root)

    LOGGER.info("Stage 5/7: run refactor tasks")
    run_refactor_tasks(
        target_root=target_root,
        run_root=run_root,
        refactor_adapter=args.agent_adapter,
        dry_run=args.dry_run,
    )

    LOGGER.info("Stage 6/7: validate build")
    validate_build(
        target_root=target_root,
        run_root=run_root,
        build_command=args.build_command,
        dry_run=args.dry_run,
    )

    LOGGER.info("Stage 7/7: summarize results")
    summarize_results(run_root)
    return run_root


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)
    run_root = run_pipeline(args)
    LOGGER.info("Pipeline completed. Artifacts at %s", run_root)


if __name__ == "__main__":
    main()
