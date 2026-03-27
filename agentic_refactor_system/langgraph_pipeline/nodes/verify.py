from __future__ import annotations

import logging
from typing import Any

from ..state import TaskState

logger = logging.getLogger(__name__)


def verify_node(state: TaskState) -> dict[str, Any]:
    """
    Verification node — runs parse, build, typecheck, and smell-resolution
    checks after the edit node has applied changes.

    A2: stub that records a pass with no real checks performed.

    C4: replace with a real verification scaffold that runs the configured
        build command and records structured pass/fail per check type.
    C5: extend with smell-resolution checks that confirm the target smell
        is no longer present after the edit.
    """
    task_id = state["task_id"]
    changed = state.get("changed_files", [])

    logger.info("[%s] verify | changed_files=%d | TODO: real verification (C4/C5)", task_id, len(changed))

    return {
        "verification_result": {
            "stub": True,
            "passed": True,
            "checks": {
                "parse": "skipped",
                "build": "skipped",
                "typecheck": "skipped",
                "smell_resolved": "skipped",
            },
        }
    }
