from __future__ import annotations

import logging
from typing import Any

from ..state import TaskState

logger = logging.getLogger(__name__)


def verify_node(state: TaskState) -> dict[str, Any]:
    """
    Verification node — runs parse, build, typecheck, and smell-resolution
    checks after the edit node has applied changes.

    C3: explicit no-op check — fails if the edit node produced no file changes
        for a task that was classified as actionable.
    C4: replace skipped build/parse/typecheck stubs with real commands.
    C5: extend smell_resolved with real smell-resolution detection.
    """
    task_id = state["task_id"]
    changed = state.get("changed_files") or []

    # C3 — No-op rejection rule.
    # If the edit node ran but touched no files, the refactor failed to
    # produce any output. Record this as an explicit check failure so the
    # structured result reflects the reason, not just the terminal status.
    no_op_check = "fail" if len(changed) == 0 else "pass"

    if no_op_check == "fail":
        logger.info(
            "[%s] verify | no_op=fail | edit produced no file changes on an actionable task",
            task_id,
        )
    else:
        logger.info("[%s] verify | no_op=pass | changed_files=%d", task_id, len(changed))

    passed = no_op_check == "pass"

    return {
        "verification_result": {
            "passed": passed,
            "checks": {
                "no_op": no_op_check,
                "parse": "skipped",        # C4
                "build": "skipped",        # C4
                "typecheck": "skipped",    # C4
                "smell_resolved": "skipped",  # C5
            },
        }
    }
