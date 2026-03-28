"""
Unit test for critique_node.

Tests the node in isolation by constructing synthetic TaskState objects
and calling critique_node() directly — no LangGraph graph execution.

Two cases:
  1. GOOD PLAN   — specific invariants, concrete abort_reasons, passing verify.
                   Expect: passed=True, score >= 0.7
  2. VAGUE PLAN  — generic invariants, no abort_reasons, failing verify (no-op).
                   Expect: passed=False, score < 0.7, non-empty feedback

Run:
    python test_critique_node.py
"""

from __future__ import annotations

import os
import sys
from dotenv import load_dotenv

load_dotenv()

if not os.environ.get("OPENAI_API_KEY"):
    sys.exit("ERROR: OPENAI_API_KEY not set. Add it to .env and retry.")

from agentic_refactor_system.langgraph_pipeline.nodes.critique import (
    critique_node,
    CRITIQUE_THRESHOLD,
)
from agentic_refactor_system.langgraph_pipeline.state import make_initial_state

# ── Shared smell / context fixtures ───────────────────────────────────────────

_SMELL = {
    "smell_id": "test_smell_01",
    "smell_type": "Large Component",
    "file_path": "apps/studio/components/FormPatternsSidePanel.tsx",
    "component_name": "FormPatternsSidePanel",
    "line_start": 1,
    "line_end": 704,
    "severity": "high",
    "confidence": 0.92,
    "detector_metadata": {
        "details": "Component is 704 lines with 5 interleaved concerns."
    },
}

_CONTEXT = {
    "task_id": "task_test_critique_01",
    "smell_id": "test_smell_01",
    "target_file": "apps/studio/components/FormPatternsSidePanel.tsx",
    "symbol_name": "FormPatternsSidePanel",
    "line_start": 1,
    "line_end": 106,
    "primary_snippet": {
        "content": (
            "export function FormPatternsSidePanel({ open, onClose }) {\n"
            "  const form = useForm({ resolver: zodResolver(FormSchema) });\n"
            "  const { fields, append, remove } = useFieldArray({ control: form.control, name: 'redirectUris' });\n"
            "  const [logoFile, setLogoFile] = useState(null);\n"
            "  const [logoUrl, setLogoUrl] = useState('');\n"
            "  const uploadButtonRef = useRef(null);\n"
            "  const fileUploadRef = useRef(null);\n"
            "  // ... 600 more lines\n"
            "  return (\n"
            "    <Sheet open={open}>\n"
            "      <Form_Shadcn_ {...form}>\n"
            "        <form id={formId}>\n"
            "          {/* all sections */}\n"
            "        </form>\n"
            "      </Form_Shadcn_>\n"
            "      <SheetFooter><Button form={formId}>Save</Button></SheetFooter>\n"
            "    </Sheet>\n"
            "  );\n"
            "}"
        ),
        "start_line": 1,
        "end_line": 106,
    },
    "local_imports": [],
    "related_files": [],
    "relevant_context_files": ["apps/studio/components/FormPatternsSidePanel.tsx"],
}

_MANIFEST_TASK = {
    "id": "task_test_critique_01",
    "repo_name": "supabase",
    "target_file": "apps/studio/components/FormPatternsSidePanel.tsx",
    "smell_id": "test_smell_01",
    "smell_type": "Large Component",
    "allowed_edit_scope": {
        "mode": "bounded_file_and_local_imports",
        "allowed_files": ["apps/studio/components/FormPatternsSidePanel.tsx"],
    },
    "build_command": "pnpm build",
    "validation_commands": [],
    "metadata": {"severity": "high", "confidence": 0.92},
}


def _make_state(plan: dict, verification_result: dict, edit_result: dict | None = None, changed_files: list | None = None) -> dict:
    """Build a minimal TaskState dict for critique_node."""
    base = make_initial_state(
        task_id="task_test_critique_01",
        repo_name="supabase",
        target_file="apps/studio/components/FormPatternsSidePanel.tsx",
        smell=_SMELL,
        context=_CONTEXT,
        manifest_task=_MANIFEST_TASK,
    )
    base["plan"] = plan
    base["verification_result"] = verification_result
    base["edit_result"] = edit_result or {"stub": True, "applied": False}
    base["changed_files"] = changed_files or []
    base["actionability"] = {
        "label": "actionable",
        "confidence": 0.92,
        "rationale": "Component is 704 lines — extract_component applicable.",
        "no_op_acceptable": False,
        "caveats": [],
    }
    return base


# ── Test cases ─────────────────────────────────────────────────────────────────

GOOD_PLAN = {
    "tactic_name": "extract_component",
    "files_to_edit": ["apps/studio/components/FormPatternsSidePanel.tsx"],
    "risk_level": "medium",
    "invariants": [
        "Form_Shadcn_ context wrapper must remain as the parent of all FormField_Shadcn_ consumers",
        "SheetFooter <Button form={formId}> must remain linked to <form id={formId}> after the split",
        "fields/append/remove from useFieldArray must be threaded to any extracted RedirectUris section",
        "uploadButtonRef and fileUploadRef must remain associated with their respective input elements",
    ],
    "expected_smell_resolution": (
        "Extracting self-contained sections (e.g. RedirectUrisSection, LogoUploadSection) "
        "reduces the component from 704 lines to under 200 while keeping all state and "
        "context wiring in the parent."
    ),
    "abort_reasons": [
        "If a section requires more than 3 props threaded from parent, reconsider the split boundary",
        "If the form context provider would end up below any FormField consumer in the tree",
        "If SheetFooter cannot be kept outside the extracted form fragment",
    ],
}

VAGUE_PLAN = {
    "tactic_name": "extract_component",
    "files_to_edit": ["apps/studio/components/FormPatternsSidePanel.tsx"],
    "risk_level": "medium",
    "invariants": [
        "Component behaviour is preserved",
        "Props API remains unchanged",
    ],
    "expected_smell_resolution": "Split the large component into smaller ones.",
    "abort_reasons": [],
}

PASSING_VERIFY = {
    "passed": True,
    "checks": {
        "no_op": "pass",
        "parse": "skipped",
        "build": "skipped",
        "typecheck": "skipped",
        "smell_resolved": "skipped",
    },
}

FAILING_VERIFY = {
    "passed": False,
    "checks": {
        "no_op": "fail",
        "parse": "skipped",
        "build": "skipped",
        "typecheck": "skipped",
        "smell_resolved": "skipped",
    },
}

DIVIDER = "-" * 64

def run_tests():
    cases = [
        {
            "name": "GOOD PLAN  + passing verify",
            "plan": GOOD_PLAN,
            "verification_result": PASSING_VERIFY,
            "expect_passed": True,
        },
        {
            "name": "VAGUE PLAN + failing verify (no-op)",
            "plan": VAGUE_PLAN,
            "verification_result": FAILING_VERIFY,
            "expect_passed": False,
        },
    ]

    all_ok = True

    print(f"\n{'='*64}")
    print("  CRITIQUE NODE UNIT TEST")
    print(f"{'='*64}\n")

    for i, case in enumerate(cases, 1):
        print(f"[{i}] {case['name']}")
        print(DIVIDER)

        state = _make_state(
            plan=case["plan"],
            verification_result=case["verification_result"],
        )

        result = critique_node(state)
        cr = result.get("critique_result", {})
        score = cr.get("score", 0.0)
        passed = cr.get("passed", False)
        issues = cr.get("issues", [])
        feedback = result.get("plan_feedback") or ""

        print(f"  score     : {score:.2f}  (threshold={CRITIQUE_THRESHOLD})")
        print(f"  passed    : {passed}")
        if issues:
            print(f"  issues    :")
            for iss in issues:
                print(f"    - {iss}")
        if feedback:
            print(f"  feedback  : {feedback[:200]}{'...' if len(feedback) > 200 else ''}")

        ok = passed == case["expect_passed"]
        status = "PASS" if ok else "FAIL"
        print(f"\n  result    : {status}  (expected passed={case['expect_passed']}, got passed={passed})")
        if not ok:
            all_ok = False
        print(DIVIDER + "\n")

    print(f"{'='*64}")
    print(f"  {'ALL TESTS PASSED' if all_ok else 'SOME TESTS FAILED'}")
    print(f"{'='*64}\n")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(run_tests())
