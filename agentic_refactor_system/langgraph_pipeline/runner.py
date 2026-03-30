from __future__ import annotations

import json
import logging
import traceback
from pathlib import Path
from typing import Any

from .graph import build_graph
from .progress import ProgressPrinter, print_run_summary
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
    debug_dir: Path | None = None,
    show_progress: bool = True,
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
    show_progress : bool
        Print node-level progress to stdout (default True).

    Returns
    -------
    TaskState
        The final state after the graph has run to completion.
        Inspect state["status"] for the outcome.
    """
    task_id: str     = manifest_task["id"]
    repo_name: str   = manifest_task["repo_name"]
    target_file: str = manifest_task["target_file"]
    smell_type: str  = smell.get("smell_type", "unknown")

    initial_state = make_initial_state(
        task_id=task_id,
        repo_name=repo_name,
        target_file=target_file,
        smell=smell,
        context=context,
        manifest_task=manifest_task,
    )

    if run_root is not None:
        from ..utils.paths import task_dir as get_task_dir
        t_dir = get_task_dir(run_root, task_id)
        initial_state["artifact_paths"]["task_dir"] = str(t_dir)

    logger.info("[%s] starting graph | smell=%s | file=%s", task_id, smell_type, target_file)

    printer = ProgressPrinter() if show_progress else None
    if printer:
        printer.task_start(task_id, smell_type, target_file)

    try:
        graph = _get_graph()
        final_state: TaskState = initial_state

        if debug_dir:
            debug_dir = Path(debug_dir)
            debug_dir.mkdir(parents=True, exist_ok=True)
            with open(debug_dir / "00_initial_state.json", "w", encoding="utf-8") as f:
                json.dump(initial_state, f, indent=2, default=str)

        # Use stream() so we get per-node events for progress output.
        # stream_mode="updates" yields {node_name: state_updates} dicts.
        step_idx = 1
        for event in graph.stream(initial_state, stream_mode="updates"):
            for node_name, updates in event.items():
                logger.debug("[%s] node=%s updates=%s", task_id, node_name, list(updates.keys()))
                if printer:
                    printer.node_done(node_name, updates)
                
                # Merge updates into final_state so we have the complete state at the end.
                final_state = {**final_state, **updates}
                
                if debug_dir:
                    out_path = debug_dir / f"{step_idx:02d}_{node_name}_output.json"
                    with open(out_path, "w", encoding="utf-8") as f:
                        json.dump(final_state, f, indent=2, default=str)
                    step_idx += 1

    except Exception as exc:
        logger.error("[%s] graph raised an exception: %s", task_id, exc)
        final_state = {**initial_state, "status": STATUS_FAILED, "error": traceback.format_exc()}

    if printer:
        printer.task_end(final_state)

    logger.info("[%s] finished | status=%s", task_id, final_state.get("status"))
    return final_state


def run_tasks(
    tasks: list[dict[str, Any]],
    smell_map: dict[str, dict[str, Any]],
    context_map: dict[str, dict[str, Any]],
    *,
    run_root: Path | None = None,
    show_progress: bool = True,
) -> list[TaskState]:
    """
    Run a list of manifest tasks through the pipeline sequentially.

    Parameters
    ----------
    tasks        : list of manifest task dicts
    smell_map    : task_id -> smell dict
    context_map  : task_id -> context dict
    run_root     : Path, optional
    show_progress: print node-level progress (default True)

    Returns
    -------
    list of final TaskState, one per task
    """
    results: list[TaskState] = []
    for task in tasks:
        tid     = task["id"]
        smell   = smell_map.get(tid, {})
        context = context_map.get(tid, {})
        result  = run_task(task, smell, context, run_root=run_root, show_progress=show_progress)
        results.append(result)

    if show_progress:
        print_run_summary(results)

    return results
