from __future__ import annotations

from langgraph.graph import StateGraph, START, END

from .state import TaskState, MAX_PLAN_RETRIES
from .schemas.actionability import NON_ACTIONABLE, NEEDS_REVIEW
from .nodes.classify import classify_node
from .nodes.plan import plan_node
from .nodes.edit import edit_node
from .nodes.verify import verify_node
from .nodes.critique import critique_node
from .nodes.finalize import finalize_node


# ── Routing functions ──────────────────────────────────────────────────────────

def _route_after_classify(state: TaskState) -> str:
    """
    After classify: skip directly to finalize for non-actionable smells,
    otherwise proceed to planning.
    """
    actionability = state.get("actionability")
    if actionability is not None and actionability["label"] in (NON_ACTIONABLE, NEEDS_REVIEW):
        return "finalize"
    return "plan"


def _route_after_plan(state: TaskState) -> str:
    """
    After plan: if the planner returned NO_TACTIC (skip_reason set) go
    straight to finalize — there is nothing to edit or verify.
    Otherwise proceed to the edit node.
    """
    if state.get("skip_reason"):
        return "finalize"
    return "edit"


def _route_after_critique(state: TaskState) -> str:
    """
    Single retry gate (Options A + B combined).

    Critique runs after verify and synthesises real verification failures
    with semantic plan analysis.  This is the only retry decision point:

    - passed        → finalize (ACCEPTED if verify also passed)
    - failed + retries remain → plan (with structured feedback)
    - failed + retry limit hit → finalize (REJECTED)
    """
    cr = state.get("critique_result") or {}
    if cr.get("passed", True):
        return "finalize"
    if state.get("retry_count", 0) < MAX_PLAN_RETRIES:
        return "plan"
    return "finalize"


# ── Graph builder ──────────────────────────────────────────────────────────────

def build_graph():
    """
    Compile and return the LangGraph pipeline.

    Full topology:

        START
          │
          ▼
        classify ───────────────────────────────────────► finalize (non-actionable)
          │ (actionable)
          ▼
         plan ──────────────────────────────────────────► finalize (NO_TACTIC)
          │ (plan produced)            ▲
          ▼                            │ retry (with feedback)
         edit                          │
          │                            │
          ▼                            │
        verify                         │
          │                            │
          ▼                            │
        critique ───────────────────────┘ (failed, retries remain)
          │ (passed)          └──────────────────────────► finalize (retry limit hit)
          ▼
        finalize
          │
          ▼
         END

    Critique runs AFTER verify so it has real verification signal (build,
    typecheck, smell-resolved) to synthesise into actionable feedback.
    Retries are triggered by actual failures, not predicted ones.

    Retry limit: MAX_PLAN_RETRIES total retries.  With the default of 3
    the pipeline makes at most 4 plan+edit+verify+critique cycles.
    """
    graph = StateGraph(TaskState)

    graph.add_node("classify", classify_node)
    graph.add_node("plan", plan_node)
    graph.add_node("edit", edit_node)
    graph.add_node("verify", verify_node)
    graph.add_node("critique", critique_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "classify")

    graph.add_conditional_edges(
        "classify",
        _route_after_classify,
        {"plan": "plan", "finalize": "finalize"},
    )

    graph.add_conditional_edges(
        "plan",
        _route_after_plan,
        {"edit": "edit", "finalize": "finalize"},
    )

    graph.add_edge("edit", "verify")
    graph.add_edge("verify", "critique")

    graph.add_conditional_edges(
        "critique",
        _route_after_critique,
        {"finalize": "finalize", "plan": "plan"},
    )

    graph.add_edge("finalize", END)

    return graph.compile()
