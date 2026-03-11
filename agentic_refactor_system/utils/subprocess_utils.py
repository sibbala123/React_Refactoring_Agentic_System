"""Defensive subprocess execution helpers."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Any


def render_command(command: str | list[str]) -> str:
    if isinstance(command, str):
        return command
    return " ".join(shlex.quote(part) for part in command)


def run_command(
    command: str | list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    use_shell = isinstance(command, str)
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=use_shell,
    )
    return {
        "command": render_command(command),
        "cwd": str(cwd),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
