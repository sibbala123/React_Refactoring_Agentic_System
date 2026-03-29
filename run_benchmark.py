import json
import logging
from dotenv import load_dotenv
load_dotenv()
import random
import os
import time
from pathlib import Path
from agentic_refactor_system.langgraph_pipeline.runner import make_initial_state, _get_graph
from agentic_refactor_system.langgraph_pipeline.state import STATUS_ACCEPTED, STATUS_REJECTED, STATUS_SKIPPED, STATUS_FAILED

import openai.resources.chat.completions as comp
original_create = comp.Completions.create

class TokenTracker:
    def __init__(self):
        self.tokens = 0
tracker = TokenTracker()

def patched_create(*args, **kwargs):
    res = original_create(*args, **kwargs)
    if hasattr(res, "usage") and res.usage:
        tracker.tokens += getattr(res.usage, "total_tokens", 0)
    return res

comp.Completions.create = patched_create

# Setup Logging
logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger("benchmark")
logger.setLevel(logging.INFO)

REPO_ROOT = Path(r"C:\Users\Admin\Desktop\supabase")
TARGET_COUNT = 100

def load_real_snippet(file_path: str, start_line: int, end_line: int) -> str:
    full_path = REPO_ROOT / file_path
    if not full_path.exists():
        return ""
    try:
        lines = full_path.read_text(encoding="utf-8").splitlines()
        s_idx = max(0, start_line - 1 - 10)
        e_idx = min(len(lines), end_line + 10)
        return "\n".join(lines[s_idx:e_idx])
    except Exception:
        return ""

def generate_benchmark_tasks():
    dataset_path = Path("data/supabase_full/detector/normalized_smells.json")
    all_smells = json.loads(dataset_path.read_text(encoding="utf-8"))["smells"]
    
    valid_list = [x for x in all_smells if (REPO_ROOT / x.get("file_path", "")).exists()]
    
    if len(valid_list) >= TARGET_COUNT:
        selected_smells = random.sample(valid_list, TARGET_COUNT)
    else:
        selected_smells = valid_list
        
    tasks = []
    for s in selected_smells:
        snippet = load_real_snippet(s["file_path"], int(s.get("line_start", 1)), int(s.get("line_end", 10)))
        
        ctx = {
            "primary_snippet": {
                "content": snippet,
                "start_line": int(s.get("line_start", 1)),
                "end_line": int(s.get("line_end", 10)),
            },
            "imports": [],
            "file_exports": [],
            "local_dependencies": {}
        }
        
        mt = {
            "id": f"eval_{s['smell_id']}",
            "repo_name": "supabase",
            "target_root": str(REPO_ROOT),
            "target_file": s["file_path"],
            "build_command": "",
            "smell_type": s["smell_type"],
            "smell_id": s["smell_id"],
        }
        
        smell_obj = {
            "smell_id": s["smell_id"],
            "smell_type": s["smell_type"],
            "file_path": s["file_path"],
            "line_start": int(s.get("line_start", 1)),
            "line_end": int(s.get("line_end", 10)),
            "component_name": s.get("component_name", "Unknown"),
            "severity": "medium",
            "confidence": 0.8
        }
        tasks.append((mt, smell_obj, ctx))
        
    return tasks

def run_evaluation():
    tasks = generate_benchmark_tasks()
    logger.info(f"Generated {len(tasks)} physical execution tasks for Benchmarking...")
    
    graph = _get_graph()
    
    results = []
    
    for i, (mt, smell, ctx) in enumerate(tasks, 1):
        logger.info(f"\n[{i:03d}/{len(tasks)}] task={mt['id']}  type={smell.get('smell_type')}  file={mt['target_file']}")
        
        tracker.tokens = 0
        
        init_state = make_initial_state(
            task_id=mt["id"],
            repo_name="supabase",
            target_file=mt["target_file"],
            smell=smell,
            context=ctx,
            manifest_task=mt,
        )
        
        final_state = init_state
        plan_count = 0
        edit_count = 0
        verify_count = 0
        
        try:
            for event in graph.stream(init_state, stream_mode="updates"):
                for node_name, updates in event.items():
                    if node_name == "plan": plan_count += 1
                    if node_name == "edit": edit_count += 1
                    if node_name == "verify": verify_count += 1
                    final_state = {**final_state, **updates}
        except Exception as e:
            final_state["status"] = STATUS_FAILED
            final_state["error"] = str(e)
            
        actionability = final_state.get("actionability")
        label = actionability["label"] if actionability else "unknown"
        is_actionable = label == "actionable"
            
        is_pass_at_1 = final_state["status"] == STATUS_ACCEPTED and plan_count == 1
        is_pass_at_2 = final_state["status"] == STATUS_ACCEPTED and plan_count == 2
        is_pass_at_k = final_state["status"] == STATUS_ACCEPTED and plan_count > 2
        
        res_obj = {
            "id": mt["id"],
            "type": smell["smell_type"],
            "status": final_state["status"],
            "is_actionable": is_actionable,
            "plan_loops": plan_count,
            "edit_loops": edit_count,
            "verify_loops": verify_count,
            "pass_at_1": is_pass_at_1,
            "pass_at_2": is_pass_at_2,
            "pass_at_k": is_pass_at_k,
            "token_usage": tracker.tokens,
            "skip_reason": final_state.get("skip_reason", "")
        }
        results.append(res_obj)
        error_msg = f" | ERROR: {final_state.get('error', '')}" if final_state.get("error") else ""
        logger.info(f" -> {final_state['status']} | actionable: {is_actionable} | pass@1: {is_pass_at_1} | pass@2: {is_pass_at_2} | tokens: {tracker.tokens}{error_msg}")
        
    Path("benchmark_results_100.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    logger.info("FINISHED 100 TASKS")
    
if __name__ == "__main__":
    run_evaluation()
