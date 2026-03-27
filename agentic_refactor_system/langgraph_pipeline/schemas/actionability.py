from __future__ import annotations

from typing import Any
from typing_extensions import TypedDict

# ── Label constants ────────────────────────────────────────────────────────────
ACTIONABLE = "actionable"
NON_ACTIONABLE = "non_actionable"
NEEDS_REVIEW = "needs_review"

ACTIONABILITY_LABELS: frozenset[str] = frozenset({ACTIONABLE, NON_ACTIONABLE, NEEDS_REVIEW})


class ActionabilityResult(TypedDict):
    """
    B1 — Output of the classifier node.

    Records whether a detected smell is worth attempting to fix before any
    planning or editing begins.  The rationale field is mandatory so that
    every decision is human-readable in the artifact record.

    Constraint: no_op_acceptable may only be True when label is
    NON_ACTIONABLE or NEEDS_REVIEW.  An actionable smell that produces no
    edits must be treated as a failure.
    """

    # One of ACTIONABILITY_LABELS.
    label: str

    # Mandatory explanation of why this label was chosen.
    rationale: str

    # Classifier confidence in the label (0.0 – 1.0).
    confidence: float

    # True only when label is non_actionable or needs_review.
    # Prevents the pipeline from counting a no-op as a success on a smell
    # that was judged fixable.
    no_op_acceptable: bool

    # Optional smell-specific warnings surfaced to the planner and verifier
    # (e.g. "controlled/uncontrolled pattern may be intentional").
    caveats: list[str]


def validate_actionability_result(result: dict[str, Any]) -> list[str]:
    """
    Lightweight validation without jsonschema dependency.
    Returns a list of error strings; empty list means valid.
    """
    errors: list[str] = []

    label = result.get("label")
    if label not in ACTIONABILITY_LABELS:
        errors.append(f"label must be one of {sorted(ACTIONABILITY_LABELS)}, got {label!r}")

    if not result.get("rationale", "").strip():
        errors.append("rationale is required and must not be empty")

    confidence = result.get("confidence")
    if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
        errors.append(f"confidence must be a float between 0.0 and 1.0, got {confidence!r}")

    no_op = result.get("no_op_acceptable")
    if not isinstance(no_op, bool):
        errors.append(f"no_op_acceptable must be a bool, got {no_op!r}")
    elif no_op and label == ACTIONABLE:
        errors.append("no_op_acceptable cannot be True when label is 'actionable'")

    if not isinstance(result.get("caveats", []), list):
        errors.append("caveats must be a list of strings")

    return errors
