from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any

from .graph import build_graph
from .state import TaskState, STATUS_FAILED, make_initial_state

logger = logging.getLogger(__name__)

# Compiled graph — built once at module load and reused across tasks.
_GRAPH = None


def _get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


def run_task(
    manifest_task: dict[str, Any],
    smell: dict[str, Any],
    context: dict[str, Any],
    *,
    run_root: Path | None = None,
) -> TaskState:
    """
    Run a single task through the LangGraph pipeline.

    Parameters
    ----------
    manifest_task : dict
        Full manifest task object from build_manifest.py.
    smell : dict
        Full smell object from detect_smells.py.
    context : dict
        Full context object from gather_context.py.
    run_root : Path, optional
        Root directory of the current pipeline run.  When provided,
        the task directory path is recorded in artifact_paths["task_dir"]
        so that finalize_node can write task_summary.json into the
        existing folder structure.

    Returns
    -------
    TaskState
        The final state after the graph has run to completion.
        Inspect state["status"] for the outcome.
    """
    task_id: str = manifest_task["id"]
    repo_name: str = manifest_task["repo_name"]
    target_file: str = manifest_task["target_file"]

    # Build initial state from the three input dicts.
    initial_state = make_initial_state(
        task_id=task_id,
        repo_name=repo_name,
        target_file=target_file,
        smell=smell,
        context=context,
        manifest_task=manifest_task,
    )

    # Record the task directory so finalize_node can write artifacts.
    if run_root is not None:
        from ..utils.paths import task_dir as get_task_dir

        t_dir = get_task_dir(run_root, task_id)
        initial_state["artifact_paths"]["task_dir"] = str(t_dir)

    logger.info(
        "[%s] starting graph | smell=%s | file=%s",
        task_id,
        smell.get("smell_type", "unknown"),
        target_file,
    )

    try:
        graph = _get_graph()
        final_state: TaskState = graph.invoke(initial_state)
    except Exception as exc:
        logger.error("[%s] graph raised an exception: %s", task_id, exc)
        # Return a minimal failed state rather than crashing the caller.
        initial_state["status"] = STATUS_FAILED
        initial_state["error"] = traceback.format_exc()
        return initial_state

    logger.info("[%s] finished | status=%s", task_id, final_state.get("status"))
    return final_state


def run_tasks(
    tasks: list[dict[str, Any]],
    smell_map: dict[str, dict[str, Any]],
    context_map: dict[str, dict[str, Any]],
    *,
    run_root: Path | None = None,
) -> list[TaskState]:
    """
    Run a list of manifest tasks through the pipeline sequentially.

    Parameters
    ----------
    tasks : list of manifest task dicts
    smell_map : task_id → smell dict
    context_map : task_id → context dict
    run_root : Path, optional

    Returns
    -------
    list of final TaskState, one per task
    """
    results: list[TaskState] = []
    for task in tasks:
        tid = task["id"]
        smell = smell_map.get(tid, {})
        context = context_map.get(tid, {})
        result = run_task(task, smell, context, run_root=run_root)
        results.append(result)
    return results
