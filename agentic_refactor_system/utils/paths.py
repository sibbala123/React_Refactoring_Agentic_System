"""Path helpers for artifact-oriented pipeline stages."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def sanitize_name(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return sanitized.strip("_") or "run"


def utc_timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def make_run_id(repo_name: str, timestamp: str | None = None) -> str:
    return f"{timestamp or utc_timestamp_slug()}_{sanitize_name(repo_name)}"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def detector_dir(run_root: Path) -> Path:
    return ensure_dir(run_root / "detector")


def tasks_dir(run_root: Path) -> Path:
    return ensure_dir(run_root / "tasks")


def task_dir(run_root: Path, task_id: str) -> Path:
    return ensure_dir(tasks_dir(run_root) / task_id)
