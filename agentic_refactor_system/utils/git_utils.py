"""Git metadata helpers with graceful fallback."""

from __future__ import annotations

import platform
from pathlib import Path

from utils.subprocess_utils import run_command


def _git_output(repo_root: Path, args: list[str]) -> str | None:
    try:
        result = run_command(["git", *args], cwd=repo_root)
    except Exception:
        return None
    if result["returncode"] != 0:
        return None
    return result["stdout"].strip() or None


def collect_git_metadata(repo_root: Path) -> dict[str, object]:
    return {
        "git_available": _git_output(repo_root, ["--version"]) is not None,
        "commit_hash": _git_output(repo_root, ["rev-parse", "HEAD"]),
        "branch": _git_output(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"]),
        "is_dirty": bool(_git_output(repo_root, ["status", "--porcelain"])),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }
