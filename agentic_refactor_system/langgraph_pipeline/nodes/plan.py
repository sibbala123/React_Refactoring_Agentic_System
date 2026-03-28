from __future__ import annotations

import json
import logging
import os
from typing import Any

from openai import OpenAI

from ..schemas.plan import (
    RISK_LOW,
    RISK_MEDIUM,
    RISK_HIGH,
    RefactorPlan,
    validate_refactor_plan,
)
from ..state import TaskState, STATUS_PLANNING, STATUS_SKIPPED, MAX_PLAN_RETRIES
from ..tactics import get_tactic, tactic_names_for_smell

logger = logging.getLogger(__name__)

# OpenAI function definition that maps exactly to RefactorPlan.
_PLAN_FUNCTION = {
    "name": "record_refactor_plan",
    "description": (
        "Record a bounded, tactic-specific refactor plan for an actionable React code smell. "
        "If no tactic safely applies, call this function with tactic_name='NO_TACTIC' and "
        "explain in expected_smell_resolution why the smell cannot be planned."
    ),
    "parameters": {
        "type": "object",
        "required": [
            "tactic_name",
            "files_to_edit",
            "risk_level",
            "invariants",
            "expected_smell_resolution",
            "abort_reasons",
        ],
        "additionalProperties": False,
        "properties": {
            "tactic_name": {
                "type": "string",
                "description": (
                    "Exact name of the chosen tactic from the provided tactic list "
                    "(e.g. 'extract_component'). Use 'NO_TACTIC' if none applies."
                ),
            },
            "files_to_edit": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Relative paths of files the edit node may modify. "
                    "Must be a non-empty subset of the allowed files listed in the prompt."
                ),
            },
            "risk_level": {
                "type": "string",
                "enum": [RISK_LOW, RISK_MEDIUM, RISK_HIGH],
                "description": "Estimated risk of this transformation.",
            },
            "invariants": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Behaviours that must be preserved after the edit "
                    "(e.g. 'component public props API unchanged')."
                ),
            },
            "expected_smell_resolution": {
                "type": "string",
                "description": (
                    "Plain-language description of how applying this tactic resolves the smell. "
                    "If tactic_name is NO_TACTIC, explain why no tactic safely applies."
                ),
            },
            "abort_reasons": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Conditions under which the edit node should abandon the attempt "
                    "(e.g. 'component is used in more than 10 call sites')."
                ),
            },
        },
    },
}

_SYSTEM_PROMPT = """\
You are a senior React engineer producing a precise, bounded refactoring plan.
You will be given a detected code smell, its context, and a list of candidate
refactoring tactics with full definitions.

Your job is to pick the single best tactic and fill in a RefactorPlan.

Rules
-----
1. Only choose a tactic from the provided candidate list. Do not invent tactics.
2. files_to_edit must be a non-empty subset of the allowed files listed in the prompt.
3. Set risk_level honestly: low = routine change, medium = interface-touching, high = structural.
4. invariants must be specific to this smell instance, not generic boilerplate.
5. abort_reasons must list concrete conditions that would make the edit unsafe.
6. If no candidate tactic safely applies (e.g. preconditions are not met, risk is
   unacceptably high, or the edit scope is too narrow), return tactic_name='NO_TACTIC'
   and explain clearly in expected_smell_resolution. Do NOT force a bad plan.
"""


def _build_feedback_header(state: TaskState) -> list[str]:
    """
    Return a header block injected at the top of the user prompt when the
    plan node is being called as a retry (plan_feedback is set in state).
    """
    feedback = state.get("plan_feedback") or ""
    retry_num = state.get("retry_count", 0) + 1  # will be incremented after this call
    lines = [
        f"⚠  REVISION REQUESTED  "
        f"(attempt {retry_num + 1} of {MAX_PLAN_RETRIES + 1}  —  retry {retry_num})",
        "=" * 70,
        "",
        "Your previous plan was evaluated and found to need improvement.",
        "Please address all of the following before producing your revised plan.",
        "",
        "Feedback from previous attempt:",
        "───────────────────────────────",
        feedback,
        "",
        "─" * 70,
        "",
    ]
    return lines


def _build_user_prompt(state: TaskState) -> str:
    smell = state["smell"]
    context = state["context"]
    actionability = state["actionability"]
    snippet = context.get("primary_snippet", {})

    smell_type = smell.get("smell_type", "unknown")
    allowed_files: list[str] = (
        state["manifest_task"]
        .get("allowed_edit_scope", {})
        .get("allowed_files", [state["target_file"]])
    )

    lines: list[str] = [
        f"Repository: {state['repo_name']}",
        f"File:       {state['target_file']}",
        f"Component:  {smell.get('component_name') or 'unknown'}",
        f"Smell type: {smell_type}",
        f"Lines:      {smell.get('line_start')} - {smell.get('line_end')}",
        "",
        "Classifier verdict",
        "------------------",
        f"Label:      {actionability['label']}",
        f"Confidence: {actionability['confidence']:.2f}",
        f"Rationale:  {actionability['rationale']}",
    ]

    if actionability.get("caveats"):
        lines.append("Caveats:")
        for c in actionability["caveats"]:
            lines.append(f"  - {c}")

    lines += [
        "",
        "Allowed files the edit node may touch:",
    ]
    for f in allowed_files:
        lines.append(f"  - {f}")

    code = snippet.get("content", "").strip()
    if code:
        lines += [
            "",
            f"Code snippet (lines {snippet.get('start_line')} - {snippet.get('end_line')}):",
            "```",
            code,
            "```",
        ]
    else:
        lines.append("\n(No code snippet available)")

    details = smell.get("detector_metadata", {}).get("details", "")
    if details:
        lines += ["", f"Detector details: {details}"]

    # Append full tactic definitions for all candidates
    candidate_names = tactic_names_for_smell(smell_type)
    if candidate_names:
        lines += [
            "",
            "Candidate tactics for this smell type",
            "--------------------------------------",
        ]
        for name in candidate_names:
            tactic = get_tactic(name)
            if not tactic:
                continue
            lines += [
                f"Tactic: {tactic['name']} — {tactic['display_name']}",
                f"  edit_shape:    {tactic['edit_shape']}",
                f"  preconditions: {'; '.join(tactic['preconditions'])}",
                f"  invariants:    {'; '.join(tactic['invariants'])}",
                f"  risks:         {tactic['risks']}",
                f"  abort_if:      {'; '.join(tactic['abort_if'])}",
                "",
            ]
    else:
        lines += ["", "(No candidate tactics found for this smell type — use NO_TACTIC)"]

    body = "\n".join(lines)

    # Prepend feedback header when this is a retry attempt.
    if state.get("plan_feedback"):
        header = "\n".join(_build_feedback_header(state))
        return header + body

    return body


def plan_node(state: TaskState) -> dict[str, Any]:
    """
    B4 — Planner node.

    Calls the OpenAI API with a function-calling prompt to produce a bounded,
    tactic-specific RefactorPlan for every smell the classifier confirmed as
    actionable.

    Reads from state:  actionability, smell, context, manifest_task, repo_name, target_file
    Writes to state:   plan, status  (and skip_reason when no tactic applies)
    """
    task_id = state["task_id"]
    smell_type = state["smell"].get("smell_type", "unknown")
    actionability = state.get("actionability")
    label = actionability["label"] if actionability else "unknown"
    is_retry = bool(state.get("plan_feedback"))

    logger.info(
        "[%s] plan | smell_type=%s | actionability=%s | retry=%s | calling OpenAI",
        task_id,
        smell_type,
        label,
        is_retry,
    )

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
        functions=[_PLAN_FUNCTION],
        function_call={"name": "record_refactor_plan"},
        temperature=0,
    )

    raw: dict[str, Any] = json.loads(
        response.choices[0].message.function_call.arguments
    )

    # If the model determined no tactic safely applies, skip this task.
    if raw.get("tactic_name") == "NO_TACTIC":
        reason = raw.get("expected_smell_resolution", "Planner found no applicable tactic.")
        logger.info("[%s] plan | NO_TACTIC -> skipping | reason=%s", task_id, reason[:120])
        result: dict = {
            "status": STATUS_SKIPPED,
            "skip_reason": reason,
        }
        if is_retry:
            result["retry_count"] = state.get("retry_count", 0) + 1
            result["plan_feedback"] = None
        return result

    allowed_files: list[str] = (
        state["manifest_task"]
        .get("allowed_edit_scope", {})
        .get("allowed_files", [state["target_file"]])
    )

    errors = validate_refactor_plan(raw, allowed_files=allowed_files)
    if errors:
        raise ValueError(
            f"[{task_id}] OpenAI returned an invalid RefactorPlan: {errors}\nraw={raw}"
        )

    plan: RefactorPlan = {
        "tactic_name": raw["tactic_name"],
        "files_to_edit": list(raw["files_to_edit"]),
        "risk_level": raw["risk_level"],
        "invariants": list(raw.get("invariants", [])),
        "expected_smell_resolution": raw["expected_smell_resolution"],
        "abort_reasons": list(raw.get("abort_reasons", [])),
    }

    logger.info(
        "[%s] plan | tactic=%s | risk=%s | files=%s | retry=%s",
        task_id,
        plan["tactic_name"],
        plan["risk_level"],
        plan["files_to_edit"],
        is_retry,
    )

    final: dict = {
        "status": STATUS_PLANNING,
        "plan": plan,
    }
    # On retry: increment counter and clear the consumed feedback.
    if is_retry:
        final["retry_count"] = state.get("retry_count", 0) + 1
        final["plan_feedback"] = None
    return final
