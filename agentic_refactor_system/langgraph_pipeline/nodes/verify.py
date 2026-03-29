from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from ..state import TaskState

logger = logging.getLogger(__name__)

def verify_node(state: TaskState) -> dict[str, Any]:
    task_id = state["task_id"]
    changed = state.get("changed_files") or []
    target_root_str = state["manifest_task"].get("target_root")
    target_root = Path(target_root_str) if target_root_str else None
    target_file = state["target_file"]

    no_op_check = "fail" if len(changed) == 0 else "pass"
    
    # 1. Run Build
    build_check = "skipped"
    build_cmd = state["manifest_task"].get("build_command")
    if no_op_check == "pass" and build_cmd and target_root and target_root.exists():
        logger.info("[%s] verify | running build command: %s", task_id, build_cmd)
        try:
            res = subprocess.run(
                build_cmd,
                cwd=target_root,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            build_check = "pass" if res.returncode == 0 else "fail"
            if build_check == "fail":
                logger.warning("[%s] verify | build failed: %s", task_id, res.stderr[:200])
        except Exception as e:
            logger.error("[%s] verify | build exception: %s", task_id, e)
            build_check = "fail"

    # 2. Run Smell Resolution
    smell_resolved_check = "skipped"
    smell_type = state["smell"].get("smell_type")
    
    if no_op_check == "pass" and build_check in ("pass", "skipped") and target_root and target_root.exists() and smell_type:
        reactsniffer_root = r"D:\Agentic\React_Refactoring_Agentic_System\vendor\reactsniffer"
        logger.info("[%s] verify | running reactsniffer on directory %s", task_id, Path(target_file).parent)
        try:
            node_cmd = f"node {Path(reactsniffer_root) / 'index.js'} {str(Path(target_file).parent)}"
            res = subprocess.run(
                node_cmd,
                cwd=target_root,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False
            )
            
            smell_resolved_check = "pass" # innocent until proven guilty
            try:
                # Attempt to extract JSON if there's other CLI clutter
                stdout_clean = res.stdout
                if "{" in stdout_clean:
                    stdout_clean = stdout_clean[stdout_clean.find("{"):]
                    
                output_data = json.loads(stdout_clean)
                smells = output_data.get("smells", [])
                
                for s in smells:
                    if s.get("smell_type") == smell_type:
                        target_comp = state["smell"].get("component_name")
                        found_comp = s.get("component_name")
                        
                        # Only flag if it's the identical smell on the identical component
                        if target_comp and found_comp and target_comp != found_comp:
                            continue 
                            
                        smell_resolved_check = "fail"
                        logger.warning("[%s] verify | smell %s NOT resolved (still present in reactsniffer).", task_id, smell_type)
                        break
                        
            except json.JSONDecodeError:
                logger.warning("[%s] verify | reactsniffer stdout was not JSON: %s", task_id, res.stdout[:200])
                smell_resolved_check = "fail"
                
        except Exception as e:
            logger.error("[%s] verify | reactsniffer exception: %s", task_id, e)
            smell_resolved_check = "fail"

    passed = no_op_check == "pass" and build_check in ("pass", "skipped") and smell_resolved_check in ("pass", "skipped")
    if not passed:
        logger.warning("[%s] verify | checks failed -> no_op: %s, build: %s, smell_resolved: %s", task_id, no_op_check, build_check, smell_resolved_check)

    return {
        "verification_result": {
            "passed": passed,
            "checks": {
                "no_op": no_op_check,
                "parse": "skipped",
                "build": build_check,
                "typecheck": "skipped",
                "smell_resolved": smell_resolved_check,
            },
        }
    }
