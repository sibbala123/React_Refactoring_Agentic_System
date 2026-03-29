import os
from pathlib import Path
from agentic_refactor_system.langgraph_pipeline.nodes.edit import edit_node
from agentic_refactor_system.langgraph_pipeline.tactics import get_tactic

def test_edit():
    target_root = Path("./dummy_repo")
    target_root.mkdir(exist_ok=True)
    
    test_file = target_root / "test.tsx"
    test_file.write_text("""
import React from 'react';
export function DataGridDemo() {
  const data = [1, 2, 3];
  return (
    <div>
      {data.map(d => <span>{d}</span>)}
    </div>
  );
}
    """.strip(), encoding="utf-8")

    state = {
        "task_id": "test_tsk",
        "manifest_task": {"target_root": str(target_root)},
        "plan": {
            "tactic_name": "extract_component",
            "files_to_edit": ["test.tsx"],
            "risk_level": "medium",
            "expected_smell_resolution": "Extracted DataGrid to its own component",
            "invariants": ["Keep props same"],
            "abort_reasons": []
        }
    }
    
    print("Testing edit node...")
    result = edit_node(state)
    
    print("RESULT:")
    print("applied:", result["edit_result"]["applied"])
    if "diffs" in result["edit_result"]:
        print("diffs:", result["edit_result"]["diffs"])
        
if __name__ == "__main__":
    if "OPENAI_API_KEY" in os.environ:
        test_edit()
    else:
        print("Skipping LLM call due to missing API key")
