from __future__ import annotations

"""
Critique node — evaluates the refactor plan and edit output for quality
and safety.

Assigns a score 0.0–1.0 to the plan.  If score < CRITIQUE_THRESHOLD the
plan is sent back to plan_node with structured feedback (Option B retry
loop).  The same feedback mechanism is used when verify_node fails
(Option A retry loop) — in both cases plan_node reads state["plan_feedback"]
and incorporates it into the next attempt.
"""

import json
import logging
import os
from typing import Any

from openai import OpenAI

from ..state import TaskState, STATUS_CRITIQUING

logger = logging.getLogger(__name__)

# Plans scoring below this threshold are sent back for revision.
CRITIQUE_THRESHOLD = 0.7

_CRITIQUE_FUNCTION = {
    "name": "record_critique",
    "description": (
        "Record a quality evaluation of a refactoring plan and its resulting edits. "
        "Assign a score and, if the plan needs improvement, provide actionable feedback "
        "that the planner can use to revise it."
    ),
    "parameters": {
        "type": "object",
        "required": ["score", "passed", "issues", "feedback"],
        "additionalProperties": False,
        "properties": {
            "score": {
                "type": "number",
                "description": (
                    "Quality score 0.0–1.0 based on the rubric below.\n"
                    "0.9–1.0: excellent — specific invariants, concrete abort_reasons, tactic matches perfectly.\n"
                    "0.7–0.9: good with minor gaps.\n"
                    "0.5–0.7: significant gaps — vague invariants, missing abort_reasons, or tactic mismatch.\n"
                    "0.0–0.5: poor — fundamental problems with tactic choice or safety."
                ),
            },
            "passed": {
                "type": "boolean",
                "description": (
                    f"True if score >= {CRITIQUE_THRESHOLD}. "
                    "Set this to True only when the plan is safe and specific enough to execute."
                ),
            },
            "issues": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Specific problems found (empty list if passed=True). "
                    "Each entry must be a concrete, actionable statement — not generic advice."
                ),
            },
            "feedback": {
                "type": "string",
                "description": (
                    "Concrete guidance for the plan node to produce a better plan on the next attempt. "
                    "Address each issue directly. Empty string if passed=True."
                ),
            },
        },
    },
}

_SYSTEM_PROMPT = f"""\
You are a senior React engineer reviewing a refactoring attempt.

You receive the original refactor plan AND the verification results that ran
after the edit.  Your job is to evaluate whether the attempt succeeded and,
if not, provide concrete feedback the planner can act on immediately.

IMPORTANT — STUB MODE
---------------------
If the Edit Result section says "(Edit node is a stub)", the edit agent has
not been implemented yet.  In this case:
  - Do NOT penalise the plan for lack of file changes — that is a test
    environment limitation, not a plan deficiency.
  - Skip criteria 1 (verification results) and 2 (edit adherence) entirely.
  - Score ONLY on criteria 3, 4, and 5 below.
  - A plan with specific invariants and concrete abort_reasons should score
    >= 0.8 in stub mode even though no files were changed.

Evaluate against the following criteria:

1. VERIFICATION RESULTS  (skip in stub mode)
   Did the edit pass all verification checks?  If any check failed, explain
   exactly what the planner must change to fix it.

2. EDIT ADHERENCE  (skip in stub mode)
   Do the changed files follow the plan's stated invariants?

3. INVARIANT SPECIFICITY
   Are invariants concrete and smell-specific — not generic boilerplate?
   Bad:  "component behaviour is preserved"
   Good: "FormField_Shadcn_ children continue to receive form context via the Form_Shadcn_ wrapper"

4. ABORT REASON CONCRETENESS
   Are abort_reasons actionable conditions the edit node can actually check?
   Bad:  "if the component is too complex"
   Good: "if the component has more than 10 direct import sites across the codebase"
   An empty abort_reasons list should score no higher than 0.5.

5. TACTIC APPROPRIATENESS
   Does the chosen tactic actually address this specific smell type?

Score 0.0–1.0 according to the rubric in the function schema.
Set passed=True if and only if score >= {CRITIQUE_THRESHOLD}.

If passed=False, write specific, actionable feedback the planner can use on the next attempt.
Do NOT penalise for stub mode. Do NOT give generic advice — address the exact
deficiencies in the plan itself.
"""


def _build_user_prompt(state: TaskState) -> str:
    smell = state["smell"]
    plan = state.get("plan") or {}
    context = state["context"]
    snippet = context.get("primary_snippet", {})
    changed_files = state.get("changed_files") or []
    edit_result = state.get("edit_result") or {}

    lines: list[str] = [
        f"Repository: {state['repo_name']}",
        f"File:       {state['target_file']}",
        f"Component:  {smell.get('component_name') or 'unknown'}",
        f"Smell type: {smell.get('smell_type', 'unknown')}",
        f"Lines:      {smell.get('line_start')} - {smell.get('line_end')}",
        "",
        "Refactor Plan",
        "─────────────",
        f"Tactic:                    {plan.get('tactic_name', 'unknown')}",
        f"Risk level:                {plan.get('risk_level', 'unknown')}",
        f"Files to edit:             {plan.get('files_to_edit', [])}",
        f"Expected smell resolution: {plan.get('expected_smell_resolution', '')}",
    ]

    invariants = plan.get("invariants") or []
    if invariants:
        lines.append("Invariants:")
        for inv in invariants:
            lines.append(f"  - {inv}")
    else:
        lines.append("Invariants: (none listed)")

    abort_reasons = plan.get("abort_reasons") or []
    if abort_reasons:
        lines.append("Abort reasons:")
        for ar in abort_reasons:
            lines.append(f"  - {ar}")
    else:
        lines.append("Abort reasons: (none listed)")

    # ── Verification results ───────────────────────────────────────────────────
    verification_result = state.get("verification_result") or {}
    vr_passed = verification_result.get("passed", None)
    vr_checks = verification_result.get("checks", {})

    lines += ["", "Verification Results", "────────────────────"]
    if not verification_result:
        lines.append("(Verification did not run)")
    else:
        lines.append(f"Overall: {'PASS' if vr_passed else 'FAIL'}")
        for check_name, check_result in vr_checks.items():
            lines.append(f"  {check_name:<16}: {check_result}")

    # ── Edit result ────────────────────────────────────────────────────────────
    lines += ["", "Edit Result", "───────────"]
    if edit_result.get("stub"):
        lines.append(
            "(Edit node is a stub — no files were changed. "
            "Evaluate plan specificity and whether it could guide a real edit.)"
        )
        # Show the original snippet so critique can assess plan specificity.
        code = (snippet.get("content") or "").strip()
        if code:
            lines += [
                "",
                f"Original code (lines {snippet.get('start_line')} – {snippet.get('end_line')}):",
                "```",
                code,
                "```",
            ]
    elif changed_files:
        lines.append(f"Files changed: {changed_files}")
        # B6: When the real edit node is implemented, populate edit_result with
        # per-file diffs so critique can check invariant adherence directly.
        # Expected shape:
        #   edit_result["diffs"] = {"path/to/file.tsx": "<unified diff string>"}
        diffs: dict = edit_result.get("diffs") or {}
        if diffs:
            for fpath, diff in diffs.items():
                lines += [
                    "",
                    f"Diff — {fpath}:",
                    "```diff",
                    diff,
                    "```",
                ]
        else:
            lines.append(
                "(No diffs available — edit node should populate "
                "edit_result['diffs'] for full invariant adherence checks.)"
            )
    else:
        lines.append("No files were changed.")

    return "\n".join(lines)


def critique_node(state: TaskState) -> dict[str, Any]:
    """
    Critique node (Option B).

    Scores the refactor plan 0.0–1.0 using an LLM judge.  If
    score < CRITIQUE_THRESHOLD the plan is flagged and structured feedback
    is written to state["plan_feedback"] so the plan node can revise it on
    the next attempt.

    Early exit: if no plan is in state (e.g. planner returned NO_TACTIC and
    set skip_reason), returns passed=True immediately without an LLM call.

    Reads from state:  plan, edit_result, changed_files, smell, context
    Writes to state:   critique_result, plan_feedback, status
    """
    task_id = state["task_id"]

    # Early exit — nothing to critique when planner skipped this task.
    if state.get("skip_reason") or not state.get("plan"):
        logger.info("[%s] critique | skipping (no plan / already skipped)", task_id)
        return {
            "status": STATUS_CRITIQUING,
            "critique_result": {
                "score": 1.0,
                "passed": True,
                "issues": [],
                "feedback": "",
                "threshold": CRITIQUE_THRESHOLD,
                "skipped": True,
            },
            "plan_feedback": None,
        }

    plan = state["plan"]
    tactic = plan.get("tactic_name", "unknown")
    logger.info("[%s] critique | tactic=%s | calling OpenAI", task_id, tactic)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY environment variable is not set. "
            "Set it before running the pipeline."
        )

    client = OpenAI(api_key=api_key)
    user_prompt = _build_user_prompt(state)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        functions=[_CRITIQUE_FUNCTION],
        function_call={"name": "record_critique"},
        temperature=0,
    )

    raw: dict[str, Any] = json.loads(
        response.choices[0].message.function_call.arguments
    )

    score = float(raw.get("score", 0.0))
    issues = list(raw.get("issues") or [])
    feedback_str = str(raw.get("feedback") or "").strip()

    # Reconcile passed flag with threshold (model may be inconsistent).
    passed = score >= CRITIQUE_THRESHOLD

    critique_result: dict[str, Any] = {
        "score": score,
        "passed": passed,
        "issues": issues,
        "feedback": feedback_str,
        "threshold": CRITIQUE_THRESHOLD,
    }

    logger.info(
        "[%s] critique | score=%.2f | passed=%s | issues=%d",
        task_id,
        score,
        passed,
        len(issues),
    )

    # Build plan_feedback combining verify results + critique analysis.
    plan_feedback: str | None = None
    if not passed:
        parts: list[str] = [
            f"Critique score: {score:.2f}  (threshold: {CRITIQUE_THRESHOLD})",
        ]
        # Surface any hard verification failures first — these are objective.
        vr = state.get("verification_result") or {}
        if not vr.get("passed", True):
            vr_checks = vr.get("checks", {})
            failed_checks = [k for k, v in vr_checks.items() if v not in ("pass", "skipped")]
            if failed_checks:
                parts.append("\nVerification failures:")
                for fc in failed_checks:
                    parts.append(f"  - {fc}: {vr_checks[fc]}")
        if issues:
            parts.append("\nPlan quality issues:")
            for issue in issues:
                parts.append(f"  - {issue}")
        if feedback_str:
            parts.append(f"\nGuidance:\n{feedback_str}")
        plan_feedback = "\n".join(parts)

    return {
        "status": STATUS_CRITIQUING,
        "critique_result": critique_result,
        "plan_feedback": plan_feedback,
    }
