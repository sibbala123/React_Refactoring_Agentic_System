from __future__ import annotations

import logging
from typing import Any

from ..state import TaskState, STATUS_EDITING

logger = logging.getLogger(__name__)


def edit_node(state: TaskState) -> dict[str, Any]:
    """
    Edit node — applies the refactor plan to the target files using an
    agent adapter (LLM + tool calls).

    A2: stub that records no changes and passes through.

    Future story: replace with a real agent call that reads state["plan"],
    applies file edits within the allowed scope, and populates
    state["edit_result"] and state["changed_files"].
    """
    task_id = state["task_id"]
    plan = state.get("plan")
    tactic = plan["tactic_name"] if plan else "unknown (stub)"

    logger.info("[%s] edit | tactic=%s | TODO: real agent call", task_id, tactic)

    return {
        "status": STATUS_EDITING,
        "edit_result": {"stub": True, "applied": False},
        "changed_files": [],
    }
