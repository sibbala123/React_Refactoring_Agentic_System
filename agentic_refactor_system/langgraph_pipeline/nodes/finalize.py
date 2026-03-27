from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..state import (
    TaskState,
    STATUS_ACCEPTED,
    STATUS_REJECTED,
    STATUS_SKIPPED,
    STATUS_FAILED,
)
from ..schemas.actionability import ACTIONABLE

logger = logging.getLogger(__name__)


def finalize_node(state: TaskState) -> dict[str, Any]:
    """
    Finalize node — determines the terminal status of a task and writes
    the task_summary.json artifact.

    This is the only A2 node with real logic because every other node
    needs a consistent exit path to aim for.

    Terminal status rules
    ---------------------
    SKIPPED  — actionability label is non_actionable or needs_review
                (routed here directly from classify without running plan/edit).
    FAILED   — an error was recorded anywhere in the pipeline.
    REJECTED — smell was actionable but no files were changed (no-op on
                an actionable task is a failure per story C3).
    ACCEPTED — at least one file was changed and verification passed.
    """
    task_id = state["task_id"]
    error = state.get("error")
    actionability = state.get("actionability")
    changed_files = state.get("changed_files") or []
    verification_result = state.get("verification_result") or {}
    skip_reason = state.get("skip_reason")

    # ── Determine terminal status ──────────────────────────────────────────────
    if error:
        terminal_status = STATUS_FAILED

    elif skip_reason or (
        actionability is not None and actionability["label"] != ACTIONABLE
    ):
        terminal_status = STATUS_SKIPPED
        if not skip_reason:
            skip_reason = (
                f"smell classified as '{actionability['label']}': "
                f"{actionability.get('rationale', '')}"
            )

    elif len(changed_files) == 0:
        # No edits on an actionable smell = rejected (C3 rule).
        terminal_status = STATUS_REJECTED

    elif not verification_result.get("passed", True):
        terminal_status = STATUS_REJECTED

    else:
        terminal_status = STATUS_ACCEPTED

    logger.info(
        "[%s] finalize | status=%s | changed_files=%d",
        task_id,
        terminal_status,
        len(changed_files),
    )

    # ── Build summary dict ─────────────────────────────────────────────────────
    summary: dict[str, Any] = {
        "task_id": task_id,
        "repo_name": state["repo_name"],
        "target_file": state["target_file"],
        "smell_type": state["smell"].get("smell_type"),
        "status": terminal_status,
        "skip_reason": skip_reason,
        "error": error,
        "actionability": state.get("actionability"),
        "plan": state.get("plan"),
        "changed_files": changed_files,
        "verification_result": verification_result,
        "artifact_paths": state.get("artifact_paths", {}),
    }

    # ── Write task_summary.json if a task dir exists ───────────────────────────
    artifact_paths: dict[str, str] = dict(state.get("artifact_paths") or {})

    task_dir_str = (state.get("artifact_paths") or {}).get("task_dir")
    if task_dir_str:
        from ...utils.json_utils import write_json  # lazy import to avoid circular dep

        summary_path = Path(task_dir_str) / "task_summary.json"
        write_json(summary_path, summary)
        artifact_paths["task_summary"] = str(summary_path)
        logger.info("[%s] wrote task_summary.json → %s", task_id, summary_path)

    return {
        "status": terminal_status,
        "skip_reason": skip_reason,
        "artifact_paths": artifact_paths,
    }
