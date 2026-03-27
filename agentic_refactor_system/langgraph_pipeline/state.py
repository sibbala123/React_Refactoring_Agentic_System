from __future__ import annotations

from typing import Any
from typing_extensions import TypedDict

from .schemas.actionability import ActionabilityResult
from .schemas.plan import RefactorPlan

# ── Status constants ───────────────────────────────────────────────────────────
STATUS_PENDING = "pending"
STATUS_CLASSIFYING = "classifying"
STATUS_PLANNING = "planning"
STATUS_EDITING = "editing"
STATUS_VERIFYING = "verifying"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

TASK_STATUSES: frozenset[str] = frozenset({
    STATUS_PENDING,
    STATUS_CLASSIFYING,
    STATUS_PLANNING,
    STATUS_EDITING,
    STATUS_VERIFYING,
    STATUS_ACCEPTED,
    STATUS_REJECTED,
    STATUS_SKIPPED,
    STATUS_FAILED,
})


class TaskState(TypedDict):
    """
    A1 — Shared LangGraph task state.

    This TypedDict is the single state container that flows through every
    node in the LangGraph pipeline.  Each node receives the full state and
    returns a partial dict containing only the fields it updated.

    Lifecycle
    ---------
    1. Created from the existing manifest task + smell + context objects
       before the graph runs (fields under "Input").
    2. Classifier node writes actionability (B1).
    3. Planner node writes plan (B3).
    4. Edit node writes edit_result + changed_files.
    5. Verify node writes verification_result.
    6. Finalize node sets the terminal status.

    Fields typed as dict[str, Any] for nodes not yet implemented will be
    tightened to proper TypedDicts when those stories are built.
    """

    # ── Input ─────────────────────────────────────────────────────────────────
    # Stable hash-based task ID from the existing manifest (e.g. task_28cdfabba7).
    task_id: str

    # Repository name used for artifact organisation and task ID generation.
    repo_name: str

    # Relative path to the primary file containing the smell.
    target_file: str

    # Full smell object as produced by detect_smells.py.
    # Shape: {smell_id, smell_type, file_path, component_name, line_start,
    #         line_end, severity, confidence, detector_metadata}
    smell: dict[str, Any]

    # Full context object as produced by gather_context.py.
    # Shape: {task_id, smell_id, target_file, symbol_name, line_start,
    #         line_end, local_imports, related_files, relevant_context_files,
    #         primary_snippet}
    context: dict[str, Any]

    # Full manifest task object as produced by build_manifest.py.
    # Shape: {id, repo_name, target_root, smell_id, smell_type, target_file,
    #         allowed_edit_scope, relevant_context_files, build_command, ...}
    manifest_task: dict[str, Any]

    # ── Classification (written by classifier node — B2) ──────────────────────
    # None until the classifier node runs.
    actionability: ActionabilityResult | None

    # ── Plan (written by planner node — B4) ───────────────────────────────────
    # None until the planner node runs.  Only set when actionability.label
    # is ACTIONABLE.
    plan: RefactorPlan | None

    # ── Edit output (written by edit node — future story) ─────────────────────
    # Raw result dict from the agent adapter.  None until edit node runs.
    edit_result: dict[str, Any] | None

    # Relative paths of files that were actually modified by the edit node.
    changed_files: list[str]

    # ── Verification output (written by verify node — C4/C5) ──────────────────
    # None until the verify node runs.
    verification_result: dict[str, Any] | None

    # ── Critique output (written by critique node — future story) ─────────────
    # None until the critique node runs.
    critique_result: dict[str, Any] | None

    # ── Control flow ──────────────────────────────────────────────────────────
    # Current lifecycle position.  One of TASK_STATUSES.
    status: str

    # Set when status is SKIPPED; explains why the task was not attempted.
    skip_reason: str | None

    # Set when status is FAILED; records the exception or error message.
    error: str | None

    # Number of edit-verify-critique cycles attempted so far.
    retry_count: int

    # ── Artifact tracking ─────────────────────────────────────────────────────
    # Maps node name → absolute path of the artifact file written by that node.
    # e.g. {"classifier": "/runs/.../tasks/task_xxx/actionability.json"}
    artifact_paths: dict[str, str]


def make_initial_state(
    task_id: str,
    repo_name: str,
    target_file: str,
    smell: dict[str, Any],
    context: dict[str, Any],
    manifest_task: dict[str, Any],
) -> TaskState:
    """
    Build a TaskState with all input fields populated and all output fields
    set to their empty/None defaults.  Call this once per task before
    invoking the LangGraph graph.
    """
    return TaskState(
        task_id=task_id,
        repo_name=repo_name,
        target_file=target_file,
        smell=smell,
        context=context,
        manifest_task=manifest_task,
        actionability=None,
        plan=None,
        edit_result=None,
        changed_files=[],
        verification_result=None,
        critique_result=None,
        status=STATUS_PENDING,
        skip_reason=None,
        error=None,
        retry_count=0,
        artifact_paths={},
    )
