"""Deterministic task and manifest helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def stable_task_id(repo_name: str, smell: dict[str, Any]) -> str:
    base = "|".join(
        [
            repo_name,
            smell.get("smell_type", "unknown"),
            smell.get("file_path", ""),
            smell.get("component_name", "") or smell.get("symbol_name", ""),
            str(smell.get("line_start", 0)),
            str(smell.get("line_end", 0)),
        ]
    )
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]
    return f"task_{digest}"


def sort_smells(smells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        smells,
        key=lambda item: (
            item.get("file_path", ""),
            item.get("line_start", 0),
            item.get("smell_type", ""),
            item.get("component_name", "") or "",
        ),
    )


def within_root(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
