from __future__ import annotations

from typing import Any
from typing_extensions import TypedDict

# ── Risk level constants ───────────────────────────────────────────────────────
RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

RISK_LEVELS: frozenset[str] = frozenset({RISK_LOW, RISK_MEDIUM, RISK_HIGH})


class RefactorPlan(TypedDict):
    """
    B3 — Output of the planner node.

    A bounded, tactic-specific plan produced for every actionable smell
    before any file edits are made.  The planner must refuse to emit a plan
    when the transformation would be too broad, too risky, or unclear.

    files_to_edit must be a strict subset of the allowed_edit_scope defined
    in the manifest task — the pipeline rejects any plan that names files
    outside that scope.
    """

    # Name of the refactoring tactic to apply (e.g. "extract_component",
    # "add_controlled_state").  References the tactic library (B5) by name
    # but carries no hard dependency on it at this stage.
    tactic_name: str

    # Relative paths of files the edit node is permitted to modify.
    # Must be a non-empty subset of manifest_task.allowed_edit_scope.allowed_files.
    files_to_edit: list[str]

    # Estimated risk of the transformation.  High-risk plans may be held
    # for human review rather than auto-applied.
    risk_level: str  # one of RISK_LEVELS

    # Behaviours that must be preserved after the edit.  The verifier and
    # critic enforce these (e.g. "component public props API unchanged",
    # "no new side-effects introduced").
    invariants: list[str]

    # Plain-language description of how applying this tactic resolves the
    # detected smell.  Used in the edit prompt and in the demo report.
    expected_smell_resolution: str

    # Conditions under which the edit node should abandon the attempt rather
    # than produce a partial or risky change
    # (e.g. "component is used in more than 10 call sites").
    abort_reasons: list[str]


def validate_refactor_plan(
    plan: dict[str, Any],
    allowed_files: list[str] | None = None,
) -> list[str]:
    """
    Lightweight validation without jsonschema dependency.
    Returns a list of error strings; empty list means valid.

    Pass allowed_files (from manifest_task.allowed_edit_scope.allowed_files)
    to also enforce the file-scope constraint.
    """
    errors: list[str] = []

    if not plan.get("tactic_name", "").strip():
        errors.append("tactic_name is required and must not be empty")

    files = plan.get("files_to_edit")
    if not isinstance(files, list) or len(files) == 0:
        errors.append("files_to_edit must be a non-empty list of relative paths")
    elif allowed_files is not None:
        out_of_scope = [f for f in files if f not in allowed_files]
        if out_of_scope:
            errors.append(
                f"files_to_edit contains paths outside the allowed edit scope: {out_of_scope}"
            )

    risk = plan.get("risk_level")
    if risk not in RISK_LEVELS:
        errors.append(f"risk_level must be one of {sorted(RISK_LEVELS)}, got {risk!r}")

    if not isinstance(plan.get("invariants", []), list):
        errors.append("invariants must be a list of strings")

    if not plan.get("expected_smell_resolution", "").strip():
        errors.append("expected_smell_resolution is required and must not be empty")

    if not isinstance(plan.get("abort_reasons", []), list):
        errors.append("abort_reasons must be a list of strings")

    return errors
