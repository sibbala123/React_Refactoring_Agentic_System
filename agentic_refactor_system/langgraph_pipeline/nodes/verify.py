from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from ..state import TaskState

logger = logging.getLogger(__name__)


def _run_tsc_on_file(file_path: Path, cwd: Path) -> tuple[int, str]:
    """Run tsc --noEmit --skipLibCheck --isolatedModules on a single file."""
    try:
        res = subprocess.run(
            f'npx --yes tsc --noEmit --skipLibCheck --isolatedModules --jsx react --esModuleInterop "{file_path}"',
            cwd=cwd,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
        return res.returncode, res.stdout + res.stderr
    except subprocess.TimeoutExpired as e:
        return 1, f"TSC timeout after 30 seconds: {e}"
    except Exception as e:
        return 1, str(e)


def verify_node(state: TaskState) -> dict[str, Any]:
    task_id = state["task_id"]
    changed = state.get("changed_files") or []
    target_root_str = state["manifest_task"].get("target_root")
    target_root = Path(target_root_str) if target_root_str else None
    target_file = state["target_file"]

    no_op_check = "fail" if len(changed) == 0 else "pass"
    abs_file: Path | None = None  # resolved absolute path to the edited file

    # 1. Per-file TypeScript check
    # Run tsc --isolatedModules on just the edited file — fast (~1-2s), no whole-repo scan.
    build_check = "skipped"
    if no_op_check == "pass" and target_root and target_root.exists():
        # Resolve the absolute path to the edited file (target_file is repo-relative,
        # target_root is the package dir — walk up ancestors to find the repo root).
        target_file_path = Path(target_file.lstrip("/"))
        abs_file: Path | None = None
        candidate = target_root
        for _ in range(10):
            abs_candidate = (candidate / target_file_path).resolve()
            if abs_candidate.exists():
                abs_file = abs_candidate
                break
            candidate = candidate.parent

        if abs_file is None:
            logger.warning("[%s] verify | could not resolve absolute path for %s, skipping tsc", task_id, target_file)
        else:
            logger.info("[%s] verify | running tsc --isolatedModules on %s", task_id, abs_file)
            try:
                _, output = _run_tsc_on_file(abs_file, cwd=target_root)
                # Only count errors that reference our specific edited file.
                # This avoids failing on pre-existing errors in sibling files
                # that tsc scans due to import resolution.
                abs_file_norm = str(abs_file).replace("\\", "/").lower()
                our_errors = [
                    line for line in output.splitlines()
                    if abs_file_norm in line.replace("\\", "/").lower()
                    and "error TS" in line
                ]
                build_check = "pass" if not our_errors else "fail"
                if build_check == "fail":
                    logger.warning("[%s] verify | tsc errors in %s: %s", task_id, target_file, "\n".join(our_errors[:5]))
            except Exception as e:
                logger.error("[%s] verify | tsc exception: %s", task_id, e)
                build_check = "fail"

    # 2. Run Smell Resolution
    # Runs independently of build_check — smell resolution is orthogonal to type correctness.
    smell_resolved_check = "skipped"
    smell_type = state["smell"].get("smell_type")

    if no_op_check == "pass" and target_root and target_root.exists() and smell_type:
        reactsniffer_root = Path(__file__).resolve().parent.parent.parent.parent / "vendor" / "reactsniffer"

        # Reuse abs_file resolved above if available, otherwise re-resolve.
        if abs_file is not None:
            scan_dir = abs_file.parent
        else:
            target_file_path = Path(target_file.lstrip("/"))
            scan_dir = target_root  # fallback
            candidate = target_root
            for _ in range(10):
                abs_candidate = (candidate / target_file_path).resolve()
                if abs_candidate.exists():
                    scan_dir = abs_candidate.parent
                    break
                candidate = candidate.parent

        logger.info("[%s] verify | running reactsniffer on %s", task_id, scan_dir)
        try:
            node_cmd = f'node "{Path(reactsniffer_root) / "index.js"}" "{scan_dir}"'
            res = subprocess.run(
                node_cmd,
                cwd=target_root,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=30
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
                if "There are no components with smells" in res.stdout:
                    smell_resolved_check = "pass"
                    logger.info("[%s] verify | reactsniffer found no smells (resolved!).", task_id)
                else:
                    logger.warning("[%s] verify | reactsniffer stdout was not JSON.", task_id)
                    logger.warning("[%s] verify | res.stdout: %s", task_id, res.stdout[:500])
                    logger.warning("[%s] verify | res.stderr: %s", task_id, res.stderr[:500])
                    smell_resolved_check = "fail"
                
        except Exception as e:
            logger.error("[%s] verify | reactsniffer exception: %s", task_id, e)
            smell_resolved_check = "fail"

    passed = (
        no_op_check == "pass"
        and build_check in ("pass", "skipped")
        and smell_resolved_check in ("pass", "skipped")
    )
    if not passed:
        logger.warning("[%s] verify | checks failed -> no_op: %s, typecheck: %s, smell_resolved: %s", task_id, no_op_check, build_check, smell_resolved_check)

    return {
        "verification_result": {
            "passed": passed,
            "checks": {
                "no_op": no_op_check,
                "typecheck": build_check,
                "smell_resolved": smell_resolved_check,
            },
        }
    }
