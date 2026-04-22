"""Gather heuristic context files and snippets for each smell finding."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.json_utils import read_json, write_json
from utils.logging_utils import configure_logging
from utils.manifest_utils import stable_task_id, within_root
from utils.paths import task_dir, tasks_dir


LOGGER = configure_logging()
IMPORT_RE = re.compile(r"""^\s*import\s+.+?\s+from\s+['"](?P<source>[^'"]+)['"]""", re.MULTILINE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--repo-name", required=True)
    parser.add_argument("--max-context-files", type=int, default=8)
    parser.add_argument("--snippet-radius", type=int, default=30)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def _candidate_import_paths(base_file: Path, import_value: str) -> list[Path]:
    base_candidate = (base_file.parent / import_value).resolve()
    return [
        base_candidate,
        base_candidate.with_suffix(".js"),
        base_candidate.with_suffix(".jsx"),
        base_candidate.with_suffix(".ts"),
        base_candidate.with_suffix(".tsx"),
        base_candidate / "index.js",
        base_candidate / "index.jsx",
        base_candidate / "index.ts",
        base_candidate / "index.tsx",
    ]


def _resolve_local_imports(target_root: Path, file_path: Path) -> list[str]:
    if not file_path.exists():
        return []
    text = file_path.read_text(encoding="utf-8", errors="replace")
    resolved: list[str] = []
    for match in IMPORT_RE.finditer(text):
        source = match.group("source")
        if not source.startswith("."):
            continue
        for candidate in _candidate_import_paths(file_path, source):
            if candidate.exists() and candidate.is_file() and within_root(target_root, candidate):
                resolved.append(candidate.relative_to(target_root).as_posix())
                break
    return sorted(set(resolved))


def _find_related_files(target_root: Path, primary_file: Path) -> list[str]:
    stem = primary_file.stem
    candidates: list[str] = []
    for sibling in sorted(primary_file.parent.iterdir()):
        if not sibling.is_file() or sibling == primary_file:
            continue
        if sibling.suffix not in {".js", ".jsx", ".ts", ".tsx"}:
            continue
        candidates.append(sibling.relative_to(target_root).as_posix())
    for pattern in (f"{stem}.test.*", f"{stem}.spec.*", f"{stem}.stories.*"):
        for match in primary_file.parent.glob(pattern):
            if match.is_file():
                candidates.append(match.relative_to(target_root).as_posix())
    return sorted(set(candidates))


def _snippet_for_lines(text: str, line_start: int, line_end: int, radius: int) -> dict[str, Any]:
    lines = text.splitlines()
    start_index = max(0, line_start - 1 - radius)
    end_index = min(len(lines), line_end + radius)
    return {
        "start_line": start_index + 1,
        "end_line": end_index,
        "content": "\n".join(lines[start_index:end_index]),
    }


def gather_context_for_smell(
    smell: dict[str, Any],
    target_root: Path,
    repo_name: str,
    max_context_files: int = 8,
    snippet_radius: int = 30,
) -> dict[str, Any]:
    relative_file = smell["file_path"]
    primary_file = (target_root / relative_file).resolve()
    local_imports = _resolve_local_imports(target_root, primary_file) if primary_file.exists() else []
    related_files = _find_related_files(target_root, primary_file) if primary_file.exists() else []

    ordered_files = [relative_file, *local_imports, *related_files]
    context_files: list[str] = []
    for rel_path in ordered_files:
        if rel_path not in context_files:
            context_files.append(rel_path)
        if len(context_files) >= max_context_files:
            break

    primary_text = primary_file.read_text(encoding="utf-8", errors="replace") if primary_file.exists() else ""
    return {
        "task_id": stable_task_id(repo_name, smell),
        "smell_id": smell["smell_id"],
        "target_file": relative_file,
        "symbol_name": smell.get("component_name"),
        "line_start": smell.get("line_start", 1),
        "line_end": smell.get("line_end", smell.get("line_start", 1)),
        "local_imports": local_imports,
        "related_files": related_files,
        "relevant_context_files": context_files,
        "primary_snippet": _snippet_for_lines(
            primary_text,
            int(smell.get("line_start", 1)),
            int(smell.get("line_end", smell.get("line_start", 1))),
            snippet_radius,
        ),
    }


def gather_context(
    target_root: Path,
    run_root: Path,
    repo_name: str,
    max_context_files: int = 8,
    snippet_radius: int = 30,
) -> dict[str, Any]:
    smell_report = read_json(run_root / "smell_report.json")
    tasks_dir(run_root)
    contexts: list[dict[str, Any]] = []
    for smell in smell_report.get("smells", []):
        context = gather_context_for_smell(
            smell=smell,
            target_root=target_root,
            repo_name=repo_name,
            max_context_files=max_context_files,
            snippet_radius=snippet_radius,
        )
        contexts.append(context)
        write_json(task_dir(run_root, context["task_id"]) / "context.json", context)
    result = {"contexts": contexts, "count": len(contexts)}
    write_json(run_root / "context_index.json", result)
    return result


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)
    gather_context(
        target_root=Path(args.target_root).resolve(),
        run_root=Path(args.run_root).resolve(),
        repo_name=args.repo_name,
        max_context_files=args.max_context_files,
        snippet_radius=args.snippet_radius,
    )


if __name__ == "__main__":
    main()
