from __future__ import annotations

import logging
import os
from typing import Any

from openai import OpenAI

from ..schemas.actionability import (
    ACTIONABLE,
    NON_ACTIONABLE,
    NEEDS_REVIEW,
    ActionabilityResult,
    validate_actionability_result,
)
from ..state import TaskState, STATUS_CLASSIFYING

logger = logging.getLogger(__name__)

# OpenAI function definition that maps exactly to ActionabilityResult.
# Using function calling guarantees structured output without fragile JSON parsing.
_CLASSIFY_FUNCTION = {
    "name": "record_actionability",
    "description": (
        "Record whether a detected React code smell is actionable, non-actionable, "
        "or needs human review before any refactoring is attempted."
    ),
    "parameters": {
        "type": "object",
        "required": ["label", "rationale", "confidence", "no_op_acceptable", "caveats"],
        "additionalProperties": False,
        "properties": {
            "label": {
                "type": "string",
                "enum": [ACTIONABLE, NON_ACTIONABLE, NEEDS_REVIEW],
                "description": (
                    "actionable: smell is genuine and safe to fix automatically. "
                    "non_actionable: pattern is intentional, a false positive, or too risky. "
                    "needs_review: ambiguous — a human should decide before editing."
                ),
            },
            "rationale": {
                "type": "string",
                "description": "Mandatory explanation of why this label was chosen. Must not be empty.",
            },
            "confidence": {
                "type": "number",
                "description": "Confidence in the label from 0.0 (uncertain) to 1.0 (certain).",
            },
            "no_op_acceptable": {
                "type": "boolean",
                "description": (
                    "True only when label is non_actionable or needs_review. "
                    "Must be false when label is actionable."
                ),
            },
            "caveats": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Smell-specific warnings for the planner and verifier (can be empty).",
            },
        },
    },
}

_SYSTEM_PROMPT = """\
You are a senior React engineer reviewing automated code smell detections.
Your job is to decide whether each detected smell is worth attempting to fix
automatically, should be skipped, or needs a human to decide.

Known React smells and their possible refactorings
---------------------------------------------------
Use this table to reason about whether a smell has a clear, bounded fix.
If the smell type matches one of these and the code snippet confirms the
pattern, it is likely actionable.

| Smell                          | Possible refactorings                                                        |
|--------------------------------|------------------------------------------------------------------------------|
| Large Component                | Split Component, Extract Component, Extract Logic to Custom Hook,            |
|                                | Extract JSX to component                                                     |
| Duplicated Code                | Extract logic to custom hook, Extract Component,                             |
|                                | Extract Higher Order Component, Replace logic with Hook                      |
| Poor Names                     | Rename Component, Rename Prop, Rename State, Move Hook                       |
| Dead Code                      | Remove unused props, Remove unused state                                     |
| Feature Envy                   | Move Method, Move Component                                                  |
| Too Many Props                 | Remove unused props, Split Component                                         |
| Poor Performance               | Migrate class component to function component, Memoize component             |
| Props in Initial State         | Remove props in initial state                                                |
| Direct DOM Manipulation        | Remove direct DOM manipulation                                               |
| Force Update                   | Remove forceUpdate()                                                         |
| Inheritance Instead of         | Use Composition instead of Inheritance                                       |
| Composition                    |                                                                              |
| JSX Outside the Render Method  | Extract JSX to component, Extract component                                  |
| Low Cohesion                   | Extract component                                                            |
| Conditional Rendering          | Extract conditional in render                                                |
| No Access State in setState()  | Replace access state in setState with callbacks                              |
| Direct Mutation of State       | Replace direct mutation of state with setState()                             |
| Dependency Smell               | Replace third-party component with own component                             |
| Prop Drilling                  | Extract logic to a custom context                                            |
| Uncontrolled Component         | Add controlled state with useState, wire value and onChange                  |

Labelling rules
---------------
Label as ACTIONABLE when:
- The smell type appears in the table above
- The code snippet confirms the pattern is genuine (not a false positive)
- At least one of the listed refactorings is applicable within the allowed file scope
- The risk of breaking behaviour is low to medium

Label as NON_ACTIONABLE when:
- The pattern looks intentional (e.g. a form deliberately using uncontrolled inputs
  because it reads values only on submit via e.target)
- The detector fired on test/demo/storybook code that should not be refactored
- The smell type is not in the table (no known bounded fix)

Label as NEEDS_REVIEW when:
- The snippet alone is not enough to determine intent
- The smell is genuine but the right refactoring is deeply ambiguous

IMPORTANT — Large Component and Too Many Props:
These two smell types almost always have a viable bounded fix (extract_component,
split_component, extract_logic_to_custom_hook, remove_unused_props).
Do NOT mark these as needs_review or non_actionable purely because the component
is large or used in many places — that is the very definition of these smells.
The planner and editor have abort conditions to handle cases where a fix is
genuinely unsafe. Default to ACTIONABLE for these two smell types unless the
code is clearly a false positive (e.g. test file, generated code).

Always provide a clear, specific rationale referencing the code. Vague
rationales like "looks fine" or "might be intentional" are not acceptable.
In the caveats field, name the specific refactoring(s) from the table you
considered and why you accepted or rejected them.
"""


# Canonical set of smell types that have at least one known bounded refactoring.
# Any smell type NOT in this set is immediately marked non_actionable without
# making an LLM call — there is no point asking the model to classify something
# we have no tactic for.
KNOWN_ACTIONABLE_SMELL_TYPES: frozenset[str] = frozenset({
    "Large Component",
    "Duplicated Code",
    "Poor Names",
    "Dead Code",
    "Feature Envy",
    "Too Many Props",
    "Poor Performance",
    "Props in Initial State",
    "Direct DOM Manipulation",
    "Force Update",
    "Inheritance Instead of Composition",
    "JSX Outside the Render Method",
    "Low Cohesion",
    "Conditional Rendering",
    "No Access State in setState()",
    "Direct Mutation of State",
    "Dependency Smell",
    "Prop Drilling",
    "Uncontrolled Component",
})


def _build_user_prompt(state: TaskState) -> str:
    smell = state["smell"]
    context = state["context"]
    snippet = context.get("primary_snippet", {})

    lines: list[str] = [
        f"Repository: {state['repo_name']}",
        f"File: {state['target_file']}",
        f"Component: {smell.get('component_name') or 'unknown'}",
        f"Smell type: {smell.get('smell_type')}",
        f"Lines: {smell.get('line_start')} - {smell.get('line_end')}",
        f"Detector confidence: {smell.get('confidence', 'unknown')}",
        "",
        "Allowed files the agent may edit:",
    ]

    allowed = (
        state["manifest_task"]
        .get("allowed_edit_scope", {})
        .get("allowed_files", [state["target_file"]])
    )
    for f in allowed:
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

    return "\n".join(lines)


def classify_node(state: TaskState) -> dict[str, Any]:
    """
    B2 — Classifier node.

    Calls the OpenAI API with a function-calling prompt to determine whether
    the detected smell is actionable, non_actionable, or needs_review.

    Reads from state:  smell, context, manifest_task, repo_name, target_file
    Writes to state:   actionability, status
    """
    task_id = state["task_id"]
    smell_type = state["smell"].get("smell_type", "unknown")

    # Hard gate: if the smell type has no known refactoring in our table,
    # skip the LLM call entirely and return non_actionable immediately.
    if smell_type not in KNOWN_ACTIONABLE_SMELL_TYPES:
        logger.info(
            "[%s] classify | smell_type=%r not in known smell table -> non_actionable (no LLM call)",
            task_id,
            smell_type,
        )
        return {
            "status": STATUS_CLASSIFYING,
            "actionability": ActionabilityResult(
                label=NON_ACTIONABLE,
                rationale=(
                    f"Smell type '{smell_type}' is not in the known refactoring table. "
                    "No bounded automated fix exists for this pattern."
                ),
                confidence=1.0,
                no_op_acceptable=True,
                caveats=[f"Unknown smell type: {smell_type!r}"],
            ),
        }

    logger.info("[%s] classify | smell_type=%s | calling OpenAI", task_id, smell_type)

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
        functions=[_CLASSIFY_FUNCTION],
        function_call={"name": "record_actionability"},
        temperature=0,
    )

    import json
    raw: dict[str, Any] = json.loads(
        response.choices[0].message.function_call.arguments
    )

    errors = validate_actionability_result(raw)
    if errors:
        raise ValueError(
            f"[{task_id}] OpenAI returned an invalid ActionabilityResult: {errors}\nraw={raw}"
        )

    actionability: ActionabilityResult = {
        "label": raw["label"],
        "rationale": raw["rationale"],
        "confidence": float(raw["confidence"]),
        "no_op_acceptable": bool(raw["no_op_acceptable"]),
        "caveats": list(raw.get("caveats", [])),
    }

    logger.info(
        "[%s] classify | label=%s | confidence=%.2f | rationale=%s",
        task_id,
        actionability["label"],
        actionability["confidence"],
        actionability["rationale"][:80],
    )

    return {
        "status": STATUS_CLASSIFYING,
        "actionability": actionability,
    }
