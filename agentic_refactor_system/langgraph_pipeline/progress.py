from __future__ import annotations

"""
A5 — Node-Level CLI Progress

Prints clean, readable per-node output as a task moves through the
LangGraph pipeline.  Used by runner.py when show_progress=True.

Example output
--------------
  task_dc851cf3c2  Large Component  |  data-grid-demo.tsx
  --------------------------------------------------------
  classify   ->  actionable  (confidence=0.85)
               "Component is 144 lines with 10 props — Extract Component applicable"
  plan       ->  stub (B4 not yet implemented)
  edit       ->  stub (0 files changed)
  verify     ->  stub (all checks skipped)
  finalize   ->  REJECTED
  --------------------------------------------------------
  result: REJECTED  |  no edits made on an actionable smell

"""

import sys
from typing import Any

# ANSI colour codes — degrade gracefully on terminals that don't support them.
_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_CYAN   = "\033[36m"
_DIM    = "\033[2m"

# Terminal status -> colour
_STATUS_COLOUR = {
    "accepted":  _GREEN,
    "rejected":  _RED,
    "skipped":   _YELLOW,
    "failed":    _RED,
}


def _c(colour: str, text: str, *, use_colour: bool) -> str:
    if not use_colour:
        return text
    return f"{colour}{text}{_RESET}"


def _node_summary(node: str, updates: dict[str, Any]) -> str:
    """
    Extract the single most useful piece of information from a node's
    state updates to show on one line.
    """
    if node == "classify":
        a = updates.get("actionability")
        if a:
            label = a.get("label", "?")
            conf  = a.get("confidence", 0.0)
            return f"{label}  (confidence={conf:.2f})"
        return "ran  (no actionability written)"

    if node == "plan":
        p = updates.get("plan")
        if p:
            tactic = p.get("tactic_name", "?")
            risk   = p.get("risk_level", "?")
            return f"tactic={tactic}  risk={risk}"
        return "stub  (B4 not yet implemented)"

    if node == "edit":
        changed = updates.get("changed_files", [])
        if changed:
            return f"{len(changed)} file(s) changed: {', '.join(changed)}"
        edit_result = updates.get("edit_result") or {}
        if edit_result.get("stub"):
            return "stub  (0 files changed)"
        return "0 files changed"

    if node == "verify":
        vr = updates.get("verification_result") or {}
        if vr.get("stub"):
            return "stub  (all checks skipped)"
        checks = vr.get("checks", {})
        passed = vr.get("passed", False)
        summary = "  ".join(f"{k}={v}" for k, v in checks.items())
        return f"{'PASS' if passed else 'FAIL'}  {summary}"

    if node == "finalize":
        status = updates.get("status", "?")
        skip   = updates.get("skip_reason")
        if skip:
            return f"{status.upper()}  ({skip[:60]})"
        return status.upper()

    # Unknown future node
    return str({k: v for k, v in updates.items() if k != "artifact_paths"})[:80]


class ProgressPrinter:
    """
    Stateful printer for one task's graph execution.
    Call .task_start() once, then .node_done() for each node event,
    then .task_end() when the graph finishes.
    """

    WIDTH = 64

    def __init__(self, *, use_colour: bool = True, file=None):
        self._use_colour = use_colour and _supports_colour()
        self._file = file or sys.stdout

    def _print(self, text: str = "") -> None:
        print(text, file=self._file, flush=True)

    def task_start(self, task_id: str, smell_type: str, target_file: str) -> None:
        short_file = target_file.split("/")[-1]
        header = f"  {task_id}  {smell_type}  |  {short_file}"
        self._print()
        self._print(_c(_BOLD + _CYAN, header, use_colour=self._use_colour))
        self._print(_c(_DIM, "  " + "-" * self.WIDTH, use_colour=self._use_colour))

    def node_done(self, node: str, updates: dict[str, Any]) -> None:
        summary = _node_summary(node, updates)

        # Colour the summary based on the node and its key output
        colour = _RESET
        if node == "classify":
            label = (updates.get("actionability") or {}).get("label", "")
            colour = _GREEN if label == "actionable" else _YELLOW if label == "needs_review" else _DIM
        elif node == "finalize":
            status = updates.get("status", "")
            colour = _STATUS_COLOUR.get(status, _RESET)

        node_col = f"  {node:<10} ->  "
        self._print(
            _c(_DIM, node_col, use_colour=self._use_colour)
            + _c(colour, summary, use_colour=self._use_colour)
        )

        # Print the classifier rationale as a sub-line (most useful to see)
        if node == "classify":
            a = updates.get("actionability") or {}
            rationale = a.get("rationale", "")
            if rationale:
                truncated = rationale[:80] + ("..." if len(rationale) > 80 else "")
                self._print(
                    _c(_DIM, f"  {'':10}    \"{truncated}\"", use_colour=self._use_colour)
                )

    def task_end(self, final_state: dict[str, Any]) -> None:
        status     = final_state.get("status", "unknown")
        skip       = final_state.get("skip_reason")
        error      = final_state.get("error")
        changed    = final_state.get("changed_files") or []
        colour     = _STATUS_COLOUR.get(status, _RESET)

        self._print(_c(_DIM, "  " + "-" * self.WIDTH, use_colour=self._use_colour))

        detail = ""
        if error:
            detail = f"  error: {error.splitlines()[0][:60]}"
        elif skip:
            detail = f"  {skip[:70]}"
        elif changed:
            detail = f"  {len(changed)} file(s) edited"
        elif status == "rejected":
            detail = "  no edits made on an actionable smell"

        result_line = (
            f"  result: "
            + _c(_BOLD + colour, status.upper(), use_colour=self._use_colour)
            + _c(_DIM, detail, use_colour=self._use_colour)
        )
        self._print(result_line)
        self._print()


def _supports_colour() -> bool:
    """Return True if the current terminal likely supports ANSI colour codes."""
    if not hasattr(sys.stdout, "isatty"):
        return False
    if not sys.stdout.isatty():
        return False
    # Windows: works in Windows Terminal and VS Code; not in old cmd.exe
    import os
    if sys.platform == "win32":
        return os.environ.get("WT_SESSION") is not None or "VSCODE_PID" in os.environ or "TERM_PROGRAM" in os.environ
    return True


def print_run_summary(results: list[dict[str, Any]], *, use_colour: bool = True, file=None) -> None:
    """
    Print a compact summary table after all tasks have run.

    Example
    -------
    Run summary  (6 tasks)
    ----------------------
    accepted   1
    rejected   3
    skipped    1
    failed     1
    """
    out = file or sys.stdout
    use_colour = use_colour and _supports_colour()

    from collections import Counter
    counts = Counter(r.get("status", "unknown") for r in results)
    total  = len(results)

    print(file=out)
    print(_c(_BOLD, f"  Run summary  ({total} task{'s' if total != 1 else ''})", use_colour=use_colour), file=out)
    print(_c(_DIM, "  " + "-" * 30, use_colour=use_colour), file=out)
    for status in ("accepted", "rejected", "skipped", "failed"):
        count  = counts.get(status, 0)
        colour = _STATUS_COLOUR.get(status, _RESET)
        print(
            f"  {_c(colour, f'{status:<10}', use_colour=use_colour)}"
            f"  {_c(_BOLD, str(count), use_colour=use_colour)}",
            file=out,
        )
    print(file=out, flush=True)
