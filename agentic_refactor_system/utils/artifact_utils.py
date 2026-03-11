"""Helpers for snapshots and run-level metadata artifacts."""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

from utils.json_utils import write_json
from utils.subprocess_utils import run_command


def snapshot_files(root: Path, relative_paths: list[str]) -> dict[str, Any]:
    snapshots: dict[str, Any] = {}
    for rel_path in sorted(set(relative_paths)):
        file_path = (root / rel_path).resolve()
        if not file_path.exists() or not file_path.is_file():
            snapshots[rel_path] = {"exists": False, "content": None}
            continue
        snapshots[rel_path] = {
            "exists": True,
            "content": file_path.read_text(encoding="utf-8", errors="replace"),
        }
    return snapshots


def write_environment_metadata(run_root: Path, build_command: str = "") -> None:
    tool_versions: dict[str, Any] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    if build_command:
        manager = build_command.split()[0]
        try:
            result = run_command([manager, "--version"], cwd=run_root)
        except Exception:
            result = None
        if result and result["returncode"] == 0:
            tool_versions[manager] = result["stdout"].strip()
    write_json(run_root / "environment.json", {"tool_versions": tool_versions})
