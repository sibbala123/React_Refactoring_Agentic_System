"""Run React smell detection and normalize results into a structured report."""

from __future__ import annotations

import argparse
import csv
import json
import re
import os
import shutil
import sys
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.json_utils import validate_schema, write_json
from utils.logging_utils import configure_logging
from utils.manifest_utils import sort_smells, within_root
from utils.paths import detector_dir, ensure_dir
from utils.subprocess_utils import run_command


LOGGER = configure_logging()
TEXT_FILE_SUFFIXES = {".js", ".jsx", ".ts", ".tsx"}
EXCLUDED_PARTS = {"node_modules", "dist", "build", "coverage", ".git", ".next", ".turbo", "__generated__", "out", ".cache"}
NON_ACTIONABLE_PATH_PATTERNS = [
    re.compile(r"(^|/)__registry__(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)scripts(/|$)", re.IGNORECASE),
    re.compile(r"\.(stories|story|test|spec)\.(jsx?|tsx?)$", re.IGNORECASE),
]
# Paths indicating shared library / design-system code — smells here are deprioritised
# (severity set to "low") rather than skipped, so users can still see them if they want.
# These patterns are intentionally generic so they work across any React project or monorepo.
LIBRARY_PATH_PATTERNS = [
    # Monorepo shared packages (Turborepo, Nx, Lerna, pnpm workspaces all use packages/)
    re.compile(r"(^|/)packages/[^/]+/", re.IGNORECASE),
    # Component-library / design-system directory names used across the industry
    re.compile(r"(^|/)design-system(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)ui-kit(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)ui-components(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)component-library(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)primitives(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)base-components(/|$)", re.IGNORECASE),
]
ACTIONABLE_SMELL_TYPES = {
    "Large Component",
    "Too Many Props",
    "Inheritance Instead of Composition",
    "Props in Initial State",
    "Direct DOM Manipulation",
    "Force Update",
    "JSX Outside the Render Method",
    "Uncontrolled Component",
}
REACT_IMPORT_NAMED_RE = re.compile(
    r"^(\s*)import\s*{(?P<named>[^}]+)}\s*from\s*['\"]react['\"]\s*;?\s*$",
    re.MULTILINE,
)
REACT_IMPORT_DEFAULT_RE = re.compile(
    r"^\s*import\s+(?P<default>[A-Za-z0-9_]+)(?:\s*,\s*{[^}]+})?\s*from\s*['\"]react['\"]\s*;?\s*$",
    re.MULTILINE,
)
REACT_IMPORT_NAMESPACE_RE = re.compile(
    r"^\s*import\s+\*\s+as\s+React\s+from\s*['\"]react['\"]\s*;?\s*$",
    re.MULTILINE,
)
DETAIL_LINE_RE = re.compile(r"Line\s+(?P<line>\d+)\s*:", re.IGNORECASE)
DETAIL_LINES_RE = re.compile(r"Lines\s+(?P<start>\d+)\s*-\s*(?P<end>\d+)", re.IGNORECASE)
DETAIL_LOC_RE = re.compile(r"LOC\s*:\s*(?P<loc>\d+)", re.IGNORECASE)


def looks_like_jsx(text: str) -> bool:
    return bool(re.search(r"<[A-Za-z][A-Za-z0-9]*[\s>/]", text))


def normalize_smell_name(smell_name: str) -> str:
    mapping = {
        "large component": "Large Component",
        "too many props": "Too Many Props",
        "inheritance instead of composition": "Inheritance Instead of Composition",
        "props in initial state": "Props in Initial State",
        "direct dom manipulation": "Direct DOM Manipulation",
        "force update": "Force Update",
        "jsx outside the render method": "JSX Outside the Render Method",
        "uncontrolled component": "Uncontrolled Component",
        "large file": "Large File",
    }
    normalized = smell_name.strip().lower()
    return mapping.get(normalized, smell_name.strip())


def is_library_path(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/")
    return any(pattern.search(normalized) for pattern in LIBRARY_PATH_PATTERNS)


def is_non_actionable_path(relative_path: str, extra_patterns: list[str] | None = None) -> bool:
    normalized = relative_path.replace("\\", "/")
    patterns = list(NON_ACTIONABLE_PATH_PATTERNS)
    for pattern in extra_patterns or []:
        patterns.append(re.compile(pattern, re.IGNORECASE))
    return any(pattern.search(normalized) for pattern in patterns)


def normalize_details(details: str) -> str:
    return " ".join((details or "").split())


def smell_identity(smell: dict[str, Any]) -> tuple[Any, ...]:
    metadata = smell.get("detector_metadata", {})
    return (
        smell.get("smell_type"),
        smell.get("file_path"),
        smell.get("component_name"),
        int(smell.get("line_start", 1)),
        int(smell.get("line_end", 1)),
        normalize_details(str(metadata.get("details", ""))),
    )


def filter_and_dedupe_smells(
    smells: list[dict[str, Any]],
    include_large_file: bool = False,
    extra_exclude_path_pattern: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    filtered: list[dict[str, Any]] = []
    stats = {
        "input_count": len(smells),
        "kept_count": 0,
        "dropped_duplicate_count": 0,
        "dropped_non_actionable_type_count": 0,
        "dropped_non_actionable_path_count": 0,
    }

    for smell in smells:
        smell_type = normalize_smell_name(str(smell.get("smell_type", "unknown")))
        smell["smell_type"] = smell_type

        if smell_type == "Large File" and not include_large_file:
            stats["dropped_non_actionable_type_count"] += 1
            continue
        if smell_type not in ACTIONABLE_SMELL_TYPES and not (include_large_file and smell_type == "Large File"):
            stats["dropped_non_actionable_type_count"] += 1
            continue
        if is_non_actionable_path(str(smell.get("file_path", "")), extra_patterns=extra_exclude_path_pattern):
            stats["dropped_non_actionable_path_count"] += 1
            continue

        # Library/shared-package code: keep the smell but mark it low priority so it
        # sorts below application-code smells and won't be auto-selected by "Top 100".
        if is_library_path(str(smell.get("file_path", ""))):
            smell["severity"] = "low"

        identity = smell_identity(smell)
        if identity in seen:
            stats["dropped_duplicate_count"] += 1
            continue
        seen.add(identity)
        filtered.append(smell)

    stats["kept_count"] = len(filtered)
    return filtered, stats


def adapt_react_imports_for_reactsniffer(text: str) -> tuple[str, int, dict[str, Any]]:
    metadata = {"react_import_rewritten": False, "prepended_default_import": False}
    if REACT_IMPORT_DEFAULT_RE.search(text) or REACT_IMPORT_NAMESPACE_RE.search(text):
        return text, 0, metadata

    if REACT_IMPORT_NAMED_RE.search(text):
        rewritten = REACT_IMPORT_NAMED_RE.sub(r"\1import React, {\g<named>} from 'react'", text, count=1)
        metadata["react_import_rewritten"] = rewritten != text
        return rewritten, 0, metadata

    if looks_like_jsx(text):
        metadata["react_import_rewritten"] = True
        metadata["prepended_default_import"] = True
        return "import React from 'react'\n" + text, 1, metadata

    return text, 0, metadata


def create_reactsniffer_analysis_copy(target_root: Path, staging_root: Path) -> dict[str, dict[str, Any]]:
    if staging_root.exists():
        shutil.rmtree(staging_root)
    staging_root.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, dict[str, Any]] = {}

    for source_path in sorted(target_root.rglob("*")):
        relative_path = source_path.relative_to(target_root)
        if any(part in EXCLUDED_PARTS for part in relative_path.parts):
            continue
        if source_path.is_dir():
            continue

        if source_path.suffix not in TEXT_FILE_SUFFIXES:
            continue

        destination_path = staging_root / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        text = source_path.read_text(encoding="utf-8", errors="replace")
        adapted_text, line_offset, adapt_metadata = adapt_react_imports_for_reactsniffer(text)
        destination_path.write_text(adapted_text, encoding="utf-8")
        metadata[relative_path.as_posix()] = {
            "relative_path": relative_path.as_posix(),
            "staged_path": str(destination_path),
            "line_offset": line_offset,
            **adapt_metadata,
        }
    return metadata


def extract_line_range(details: str, default_end: int = 1, line_offset: int = 0) -> tuple[int, int]:
    lines_match = DETAIL_LINES_RE.search(details or "")
    if lines_match:
        start = max(1, int(lines_match.group("start")) - line_offset)
        end = max(start, int(lines_match.group("end")) - line_offset)
        return start, end

    line_matches = [int(match.group("line")) for match in DETAIL_LINE_RE.finditer(details or "")]
    if line_matches:
        adjusted = [max(1, line - line_offset) for line in line_matches]
        return min(adjusted), max(adjusted)

    return 1, max(1, default_end - line_offset)


def normalize_reactsniffer_path(
    raw_path: str,
    staging_root: Path,
    target_root: Path,
    staging_metadata: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    candidate = Path(raw_path)
    relative_path = raw_path.replace("\\", "/")
    if candidate.is_absolute() and within_root(staging_root, candidate):
        relative_path = candidate.relative_to(staging_root).as_posix()
    elif candidate.is_absolute() and within_root(target_root, candidate):
        relative_path = candidate.relative_to(target_root).as_posix()

    return relative_path, staging_metadata.get(relative_path, {"line_offset": 0})


def parse_reactsniffer_csv_outputs(
    detector_output_dir: Path,
    staging_root: Path,
    target_root: Path,
    staging_metadata: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    smells: list[dict[str, Any]] = []
    components_csv = detector_output_dir / "components_smells.csv"
    files_csv = detector_output_dir / "files_smells.csv"

    if components_csv.exists():
        with components_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                relative_path, file_metadata = normalize_reactsniffer_path(
                    row.get("file", ""),
                    staging_root=staging_root,
                    target_root=target_root,
                    staging_metadata=staging_metadata,
                )
                loc_match = DETAIL_LOC_RE.search(row.get("Details", ""))
                default_end = int(loc_match.group("loc")) if loc_match else 1
                line_start, line_end = extract_line_range(
                    row.get("Details", ""),
                    default_end=default_end,
                    line_offset=int(file_metadata.get("line_offset", 0)),
                )
                smells.append(
                    {
                        "smell_id": f"reactsniffer_component_{row.get('id', len(smells) + 1)}",
                        "smell_type": normalize_smell_name(row.get("Smell", "unknown")),
                        "file_path": relative_path,
                        "component_name": row.get("Component") or None,
                        "line_start": line_start,
                        "line_end": line_end,
                        "severity": "medium",
                        "confidence": 0.85,
                        "detector_metadata": {
                            "source": "reactsniffer_csv",
                            "details": row.get("Details", ""),
                            "raw_row": row,
                            "react_compat": {
                                "line_offset": file_metadata.get("line_offset", 0),
                                "react_import_rewritten": file_metadata.get("react_import_rewritten", False),
                                "prepended_default_import": file_metadata.get("prepended_default_import", False),
                            },
                        },
                    }
                )

    if files_csv.exists():
        with files_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                relative_path, file_metadata = normalize_reactsniffer_path(
                    row.get("File URL", row.get("Large File", "")),
                    staging_root=staging_root,
                    target_root=target_root,
                    staging_metadata=staging_metadata,
                )
                loc = int(row.get("LOC") or 1)
                smells.append(
                    {
                        "smell_id": f"reactsniffer_file_{row.get('id', len(smells) + 1)}",
                        "smell_type": "Large File",
                        "file_path": relative_path,
                        "component_name": None,
                        "line_start": 1,
                        "line_end": max(1, loc - int(file_metadata.get("line_offset", 0))),
                        "severity": "medium",
                        "confidence": 0.85,
                        "detector_metadata": {
                            "source": "reactsniffer_csv",
                            "raw_row": row,
                            "react_compat": {
                                "line_offset": file_metadata.get("line_offset", 0),
                                "react_import_rewritten": file_metadata.get("react_import_rewritten", False),
                                "prepended_default_import": file_metadata.get("prepended_default_import", False),
                            },
                        },
                    }
                )

    return smells


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--reactsniffer-root", default="")
    parser.add_argument("--reactsniffer-command", default="")
    parser.add_argument("--repo-name", default="unknown_repo")
    parser.add_argument("--smell-types", nargs="*", default=[])
    parser.add_argument("--include-large-file", action="store_true")
    parser.add_argument("--exclude-path-pattern", action="append", default=[])
    parser.add_argument("--disable-heuristic-fallback", action="store_true")
    parser.add_argument("--disable-reactsniffer-compat-copy", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def _extract_json_candidates(raw_text: str) -> list[Any]:
    candidates: list[Any] = []
    stripped = raw_text.strip()
    if not stripped:
        return candidates
    try:
        candidates.append(json.loads(stripped))
    except json.JSONDecodeError:
        pass
    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            candidates.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return candidates


def _normalize_from_json(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        smells = data.get("smells") or data.get("findings") or data.get("issues") or []
    elif isinstance(data, list):
        smells = data
    else:
        return []

    normalized: list[dict[str, Any]] = []
    for index, entry in enumerate(smells):
        if not isinstance(entry, dict):
            continue
        normalized.append(
            {
                "smell_id": str(entry.get("smell_id") or entry.get("id") or f"raw_{index:04d}"),
                "smell_type": entry.get("smell_type") or entry.get("type") or "unknown",
                "file_path": str(entry.get("file_path") or entry.get("file") or ""),
                "component_name": entry.get("component_name")
                or entry.get("component")
                or entry.get("symbol_name"),
                "line_start": int(entry.get("line_start") or entry.get("line") or 1),
                "line_end": int(entry.get("line_end") or entry.get("line") or entry.get("line_start") or 1),
                "severity": entry.get("severity") or "medium",
                "confidence": float(entry.get("confidence") or 0.5),
                "detector_metadata": entry.get("detector_metadata") or {"source": "reactsniffer_json"},
            }
        )
    return normalized


def _parse_text_line(line: str, index: int) -> dict[str, Any] | None:
    pattern = re.compile(
        r"(?P<smell>[A-Za-z0-9 _-]+).*?(?P<file>[\w./\\-]+\.(?:jsx?|tsx?))(?::(?P<start>\d+)(?:-(?P<end>\d+))?)?",
        re.IGNORECASE,
    )
    match = pattern.search(line)
    if not match:
        return None
    smell_type = match.group("smell").strip(" -:")
    file_path = match.group("file").replace("\\", "/")
    line_start = int(match.group("start") or 1)
    line_end = int(match.group("end") or line_start)
    component_match = re.search(r"component(?:=|:)\s*([A-Za-z0-9_]+)", line, re.IGNORECASE)
    severity_match = re.search(r"severity(?:=|:)\s*([A-Za-z]+)", line, re.IGNORECASE)
    confidence_match = re.search(r"confidence(?:=|:)\s*([0-9.]+)", line, re.IGNORECASE)
    return {
        "smell_id": f"text_{index:04d}",
        "smell_type": smell_type or "unknown",
        "file_path": file_path,
        "component_name": component_match.group(1) if component_match else None,
        "line_start": line_start,
        "line_end": line_end,
        "severity": (severity_match.group(1).lower() if severity_match else "medium"),
        "confidence": float(confidence_match.group(1) if confidence_match else 0.4),
        "detector_metadata": {"source": "reactsniffer_text"},
    }


def parse_reactsniffer_output(raw_text: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for candidate in _extract_json_candidates(raw_text):
        normalized.extend(_normalize_from_json(candidate))
    if normalized:
        return normalized

    for index, line in enumerate(raw_text.splitlines()):
        parsed = _parse_text_line(line, index)
        if parsed:
            normalized.append(parsed)
    return normalized


def _iter_source_files(target_root: Path) -> list[Path]:
    excluded = {"node_modules", "dist", "build", "coverage", ".git", ".next", ".turbo"}
    files: list[Path] = []
    for path in sorted(target_root.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT_FILE_SUFFIXES:
            continue
        if any(part in excluded for part in path.parts):
            continue
        files.append(path)
    return files


def _component_name_from_source(text: str, file_path: Path) -> str | None:
    patterns = [
        re.compile(r"export\s+default\s+function\s+([A-Z][A-Za-z0-9_]+)"),
        re.compile(r"export\s+function\s+([A-Z][A-Za-z0-9_]+)"),
        re.compile(r"function\s+([A-Z][A-Za-z0-9_]+)\s*\("),
        re.compile(r"const\s+([A-Z][A-Za-z0-9_]+)\s*=\s*\("),
    ]
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(1)
    if file_path.suffix in {".jsx", ".tsx"} and re.search(r"<[A-Z][A-Za-z0-9_]*", text):
        return file_path.stem
    return None


def heuristic_smells(target_root: Path) -> list[dict[str, Any]]:
    smells: list[dict[str, Any]] = []
    for index, file_path in enumerate(_iter_source_files(target_root)):
        text = file_path.read_text(encoding="utf-8", errors="replace")
        relative = file_path.relative_to(target_root).as_posix()
        lines = text.splitlines()
        component_name = _component_name_from_source(text, file_path)
        if not component_name:
            continue

        if len(lines) >= 220:
            smells.append(
                {
                    "smell_id": f"heuristic_large_{index:04d}",
                    "smell_type": "Large Component",
                    "file_path": relative,
                    "component_name": component_name,
                    "line_start": 1,
                    "line_end": len(lines),
                    "severity": "medium",
                    "confidence": 0.45,
                    "detector_metadata": {
                        "source": "heuristic_fallback",
                        "reason": "file exceeds line threshold",
                    },
                }
            )

        match = re.search(
            r"(?:function|const)\s+[A-Z][A-Za-z0-9_]*\s*(?:=\s*)?\((?P<params>[^)]*)\)",
            text,
            re.DOTALL,
        )
        if match:
            params = match.group("params")
            prop_count = len([part for part in re.split(r"[,\n]", params) if part.strip()])
            if "{" in params and "}" in params and prop_count >= 7:
                line_start = text[: match.start()].count("\n") + 1
                smells.append(
                    {
                        "smell_id": f"heuristic_props_{index:04d}",
                        "smell_type": "Too Many Props",
                        "file_path": relative,
                        "component_name": component_name,
                        "line_start": line_start,
                        "line_end": line_start,
                        "severity": "low",
                        "confidence": 0.4,
                        "detector_metadata": {
                            "source": "heuristic_fallback",
                            "reason": f"destructured parameter count={prop_count}",
                        },
                    }
                )
    return smells


def detect_smells(
    target_root: Path,
    output_root: Path,
    repo_name: str,
    reactsniffer_root: str = "",
    reactsniffer_command: str = "",
    smell_types: list[str] | None = None,
    include_large_file: bool = False,
    exclude_path_pattern: list[str] | None = None,
    disable_heuristic_fallback: bool = False,
    disable_reactsniffer_compat_copy: bool = False,
) -> dict[str, Any]:
    ensure_dir(output_root)
    detector_output_dir = detector_dir(output_root)
    raw_output_path = detector_output_dir / "raw_output.txt"
    analysis_root = target_root
    staging_metadata: dict[str, dict[str, Any]] = {}

    raw_text = ""
    command_used = ""
    returncode = None

    if reactsniffer_root and not disable_reactsniffer_compat_copy:
        analysis_root = detector_output_dir / "reactsniffer_input"
        staging_metadata = create_reactsniffer_analysis_copy(target_root, analysis_root)
        LOGGER.info("Prepared ReactSniffer compatibility copy at %s", analysis_root)

    if reactsniffer_root and not reactsniffer_command:
        reactsniffer_entry = Path(reactsniffer_root).resolve() / "index.js"
        analysis_argument = (
            Path("reactsniffer_input")
            if analysis_root != target_root
            else Path(os.path.relpath(str(target_root), str(detector_output_dir)))
        )
        command_used = f"node {reactsniffer_entry} {analysis_argument}"
        result = run_command(["node", str(reactsniffer_entry), str(analysis_argument)], cwd=detector_output_dir)
        LOGGER.info("Running ReactSniffer CLI: %s", command_used)
        returncode = result["returncode"]
        raw_text = "\n".join(
            [
                f"$ {result['command']}",
                "",
                "STDOUT:",
                result["stdout"],
                "",
                "STDERR:",
                result["stderr"],
            ]
        ).strip()
    elif reactsniffer_command:
        command_used = reactsniffer_command.format(
            reactsniffer_root=reactsniffer_root,
            target_root=str(analysis_root),
            output_path=str(detector_output_dir / "reactsniffer_output.json"),
            original_target_root=str(target_root),
        )
        LOGGER.info("Running ReactSniffer command: %s", command_used)
        result = run_command(command_used, cwd=detector_output_dir)
        returncode = result["returncode"]
        raw_text = "\n".join(
            [
                f"$ {result['command']}",
                "",
                "STDOUT:",
                result["stdout"],
                "",
                "STDERR:",
                result["stderr"],
            ]
        ).strip()
    else:
        raw_text = "ReactSniffer command not configured. Falling back to heuristic smell detection."

    raw_output_path.write_text(raw_text + "\n", encoding="utf-8")

    smells: list[dict[str, Any]] = []
    if reactsniffer_root or reactsniffer_command:
        smells = parse_reactsniffer_csv_outputs(
            detector_output_dir=detector_output_dir,
            staging_root=analysis_root,
            target_root=target_root,
            staging_metadata=staging_metadata,
        )

    if not smells and not disable_heuristic_fallback:
        LOGGER.info("No structured detector output found. Using heuristic fallback.")
        smells = heuristic_smells(target_root)

    smells, filter_stats = filter_and_dedupe_smells(
        smells,
        include_large_file=include_large_file,
        extra_exclude_path_pattern=exclude_path_pattern,
    )

    if smell_types:
        allowed = {item.lower() for item in smell_types}
        smells = [smell for smell in smells if smell["smell_type"].lower() in allowed]

    smells = sort_smells(smells)
    report = {
        "repo_name": repo_name,
        "target_root": str(target_root),
        "detector": {
            "reactsniffer_root": reactsniffer_root or None,
            "command_used": command_used or None,
            "returncode": returncode,
            "analysis_root": str(analysis_root),
            "compat_copy_enabled": bool(reactsniffer_root) and not disable_reactsniffer_compat_copy,
            "filtering": {
                "include_large_file": include_large_file,
                "exclude_path_pattern": exclude_path_pattern or [],
                "stats": filter_stats,
            },
        },
        "smells": smells,
        "smell_count": len(smells),
    }

    write_json(detector_output_dir / "normalized_smells.json", report)
    write_json(output_root / "smell_report.json", report)
    schema_errors = validate_schema(report, PROJECT_ROOT / "schemas" / "smell_report.schema.json")
    if schema_errors:
        LOGGER.warning("Smell report schema issues: %s", schema_errors)
    return report


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)
    detect_smells(
        target_root=Path(args.target_root).resolve(),
        output_root=Path(args.output_root).resolve(),
        repo_name=args.repo_name,
        reactsniffer_root=args.reactsniffer_root,
        reactsniffer_command=args.reactsniffer_command,
        smell_types=args.smell_types,
        include_large_file=args.include_large_file,
        exclude_path_pattern=args.exclude_path_pattern,
        disable_heuristic_fallback=args.disable_heuristic_fallback,
        disable_reactsniffer_compat_copy=args.disable_reactsniffer_compat_copy,
    )


if __name__ == "__main__":
    main()
