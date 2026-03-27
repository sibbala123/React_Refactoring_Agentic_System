from __future__ import annotations

from langgraph.graph import StateGraph, START, END

from .state import TaskState
from .schemas.actionability import NON_ACTIONABLE, NEEDS_REVIEW
from .nodes.classify import classify_node
from .nodes.plan import plan_node
from .nodes.edit import edit_node
from .nodes.verify import verify_node
from .nodes.finalize import finalize_node


def _route_after_classify(state: TaskState) -> str:
    """
    After the classifier runs, decide whether to proceed to planning or
    skip straight to finalize.

    - non_actionable / needs_review → finalize (task will be SKIPPED)
    - actionable or stub (None)     → plan
    """
    actionability = state.get("actionability")
    if actionability is not None and actionability["label"] in (NON_ACTIONABLE, NEEDS_REVIEW):
        return "finalize"
    return "plan"


def build_graph():
    """
    Compile and return the LangGraph pipeline.

    Linear flow (A2):
        START → classify → [route] → plan → edit → verify → finalize → END
                                   ↘ finalize (if non-actionable)

    Later stories will add retry loops and additional branching here
    without changing any node implementations.
    """
    graph = StateGraph(TaskState)

    graph.add_node("classify", classify_node)
    graph.add_node("plan", plan_node)
    graph.add_node("edit", edit_node)
    graph.add_node("verify", verify_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "classify")

    graph.add_conditional_edges(
        "classify",
        _route_after_classify,
        {"plan": "plan", "finalize": "finalize"},
    )

    graph.add_edge("plan", "edit")
    graph.add_edge("edit", "verify")
    graph.add_edge("verify", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()
