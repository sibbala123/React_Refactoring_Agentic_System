from __future__ import annotations

import logging
from typing import Any

from ..state import TaskState, STATUS_PLANNING

logger = logging.getLogger(__name__)


def plan_node(state: TaskState) -> dict[str, Any]:
    """
    Planner node — creates a bounded, tactic-specific refactor plan for
    every smell that the classifier confirmed as actionable.

    A2: stub that passes through with status=planning.
         plan remains None.

    B4: replace the body of this function with a real LLM call that
        consumes state["actionability"] and state["context"], then
        returns a populated RefactorPlan written to state["plan"].
    """
    task_id = state["task_id"]
    actionability = state.get("actionability")
    label = actionability["label"] if actionability else "unknown (stub)"

    logger.info("[%s] plan | actionability=%s | TODO: real LLM call (B4)", task_id, label)

    # B4 will return something like:
    # return {
    #     "status": STATUS_PLANNING,
    #     "plan": RefactorPlan(
    #         tactic_name="add_controlled_state",
    #         files_to_edit=["src/Form.tsx"],
    #         risk_level=RISK_LOW,
    #         invariants=["component props API unchanged"],
    #         expected_smell_resolution="Replaces uncontrolled <input> with useState hook",
    #         abort_reasons=["component used in >10 call sites"],
    #     ),
    # }

    return {"status": STATUS_PLANNING}
