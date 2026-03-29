from __future__ import annotations

import difflib
import logging
import os
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

from ..state import TaskState, STATUS_EDITING
from ..tactics import get_tactic

logger = logging.getLogger(__name__)

FILE_BLOCK_RE = re.compile(
    r"BEGIN_FILE:\s*(?P<path>[^\r\n]+)\r?\n```[^\n]*\r?\n(?P<body>.*?)\r?\n```\r?\nEND_FILE",
    re.DOTALL,
)

_SYSTEM_PROMPT = """\
You are an expert react refactoring Editor Agent executing a finalized refactor plan.
Your job is to read the files, apply the requested plan, and output the fully rewritten files.

RULES:
1. You must respect the exact Tactic, Invariants, and Expected Smell Resolution provided by the Planner.
2. If the plan includes Abort Reasons and you detect those conditions in the code, output nothing and explain the abort.
3. For each file you modify, output the entire new file content wrapped exactly in these markers:
BEGIN_FILE: <path>
```tsx
<new file content>
```
END_FILE
4. Do not output unified diffs. Output only the full file replacement for the files you touch.
"""

def edit_node(state: TaskState) -> dict[str, Any]:
    """
    Edit node — applies the refactor plan to the target files using an
    agent adapter (LLM + tool calls).
    """
    task_id = state["task_id"]
    plan = state.get("plan")
    
    if not plan or plan.get("tactic_name") == "NO_TACTIC":
        logger.info("[%s] edit | skipping, no actionable plan", task_id)
        return {
            "status": STATUS_EDITING,
            "edit_result": {"applied": False, "reason": "No actionable plan"},
            "changed_files": [],
        }

    tactic_name = plan["tactic_name"]
    tactic = get_tactic(tactic_name)
    if not tactic:
        return {
            "status": STATUS_EDITING,
            "edit_result": {"applied": False, "reason": f"Unknown tactic: {tactic_name}"},
            "changed_files": [],
        }

    target_root = Path(state["manifest_task"].get("target_root", "."))
    files_to_edit = plan.get("files_to_edit", [])
    
    logger.info("[%s] edit | tactic=%s | loading %d files", task_id, tactic_name, len(files_to_edit))

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY environment variable is not set. "
            "Set it before running the pipeline."
        )

    # Read current files
    file_contents = []
    for rel_path in files_to_edit:
        file_path = target_root / rel_path
        if file_path.exists():
            content = file_path.read_text(encoding="utf-8", errors="replace")
            file_contents.append(f"File: {rel_path}\n```\n{content}\n```")

    user_prompt = "\n\n".join([
        f"Task: {task_id}",
        "PLAN DETAILS:",
        f"Tactic: {tactic_name}",
        f"Risk Level: {plan.get('risk_level', 'unknown')}",
        f"Tactic Edit Shape:\n{tactic.get('edit_shape', '')}",
        f"Expected Resolution: {plan.get('expected_smell_resolution', '')}",
        "Preconditions for Edit:",
        *("- " + pre for pre in tactic.get("preconditions", [])),
        "Invariants to Maintain:",
        *("- " + inv for inv in plan.get("invariants", [])),
        "Abort Reasons (from plan):",
        *("- " + abr for abr in plan.get("abort_reasons", [])),
        "Abort Reasons (inherent to tactic):",
        *("- " + t_abr for t_abr in tactic.get("abort_if", [])),
        "CURRENT FILES:",
        *file_contents,
        "\nPlease output the modified files wrapped in BEGIN_FILE / END_FILE markers."
    ])

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )

    response_text = response.choices[0].message.content

    # Apply file blocks back to target_root
    changed_files = []
    diffs = {}
    if response_text:
        for match in FILE_BLOCK_RE.finditer(response_text):
            rel_path = match.group("path").strip().replace("\\", "/")
            if rel_path not in files_to_edit:
                logger.warning("[%s] edit | Skipping out-of-scope file block for %s", task_id, rel_path)
                continue
            
            file_path = (target_root / rel_path).resolve()
            # Security check to prevent path traversal
            if not str(file_path).startswith(str(target_root.resolve())):
                logger.warning("[%s] edit | Skipping unsafe file path %s", task_id, rel_path)
                continue

            old_content = ""
            if file_path.exists():
                old_content = file_path.read_text(encoding="utf-8", errors="replace")
                
            new_content = match.group("body")
            
            diff_lines = list(difflib.unified_diff(
                old_content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=rel_path,
                tofile=rel_path
            ))
            if diff_lines:
                diffs[rel_path] = "".join(diff_lines)

            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(new_content, encoding="utf-8")
            changed_files.append(rel_path)

    logger.info("[%s] edit | applied %d files", task_id, len(changed_files))

    return {
        "status": STATUS_EDITING,
        "edit_result": {
            "applied": bool(changed_files),
            "response_text": response_text,
            "diffs": diffs,
            "usage": dict(response.usage) if response.usage else {}
        },
        "changed_files": changed_files,
    }
