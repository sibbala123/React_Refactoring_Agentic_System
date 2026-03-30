import json
import logging
import os
import sys
import time
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Ensure we import from the local package
sys.path.insert(0, str(Path(__file__).parent))
from agentic_refactor_system.langgraph_pipeline.runner import run_task

def main():
    load_dotenv()
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("ERROR: OPENAI_API_KEY not set.")

    if len(sys.argv) < 2:
        print("Usage: python run_single_task.py <target_file>")
        sys.exit(1)

    target_path = Path(sys.argv[1]).resolve()
    if not target_path.exists() or not target_path.is_file():
        print(f"Error: Target file does not exist or is not a file: {target_path}")
        sys.exit(1)

    # Configure root logging so we see what the pipeline does
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")

    print("=" * 70)
    print(f"RUNNING PIPELINE ON SINGLE FILE: {target_path}")
    print("=" * 70)

    # 1. Synthesise Manifest Task
    task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    mt = {
        "id": task_id,
        "repo_name": "local",
        "target_file": str(target_path),
        "target_root": str(target_path.parent),
        "smell_id": f"smell_{task_id}",
        "smell_type": "Generic Code Quality Refactor",
        "symbol_name": "unknown",
        "line_start": 1,
        "line_end": 500,
        "allowed_edit_scope": {
            "mode": "bounded_file_and_local_imports",
            "allowed_files": [str(target_path)],
        },
        "build_command": "",
        "validation_commands": [],
        "metadata": {
            "severity": "medium",
            "confidence": 0.8,
            "detector_metadata": {"note": "Synthesised for single-file run"}
        },
        "relevant_context_files": [str(target_path)],
    }

    # Optional: Read snippet content
    try:
        content = target_path.read_text(encoding="utf-8")
        num_lines = len(content.splitlines())
        mt["line_end"] = num_lines
    except Exception as e:
        content = f"(Failed to read file: {e})"
        num_lines = 100

    # 2. Synthesise Smell Report
    smell = {
        "smell_id": mt["smell_id"],
        "smell_type": mt["smell_type"],
        "file_path": str(target_path),
        "line_start": 1,
        "line_end": num_lines,
        "component_name": "unknown",
        "severity": "medium",
        "confidence": 0.8,
        "detector_metadata": {"note": "Synthesised for single-file run"}
    }

    # 3. Synthesise Context Object
    ctx = {
        "task_id": mt["id"],
        "smell_id": mt["smell_id"],
        "target_file": str(target_path),
        "symbol_name": "unknown",
        "line_start": 1,
        "line_end": num_lines,
        "primary_snippet": {
            "content": content,
            "start_line": 1,
            "end_line": num_lines
        },
        "local_imports": [],
        "related_files": [],
        "relevant_context_files": [str(target_path)],
    }

    # Setup specific run directory
    # E.g. runs/run_20250101_120000_button_tsx
    run_name = f"run_{task_id}_{target_path.name.replace('.', '_')}"
    runs_dir = Path(__file__).parent / "runs"
    debug_dir = runs_dir / run_name
    debug_dir.mkdir(parents=True, exist_ok=True)

    print(f"Debug traces will be saved to: {debug_dir}")
    
    try:
        # Pass debug_dir to run_task to save node-level I/O
        state = run_task(mt, smell, ctx, debug_dir=debug_dir, show_progress=True)
        
        print("\n\n" + "=" * 70)
        print("FINAL STATE RESULT:")
        print(f"Status: {state.get('status')}")
        
    except Exception as e:
        print(f"\nPipeline crashed: {e}")

    print("\nOpening debug folder...")
    # Open the folder containing the node logs
    try:
        if os.name == 'nt':
            os.startfile(debug_dir)
        elif sys.platform == 'darwin':
            import subprocess
            subprocess.Popen(['open', str(debug_dir)])
        else:
            import subprocess
            subprocess.Popen(['xdg-open', str(debug_dir)])
    except Exception as e:
        print(f"Failed to auto-open folder: {e}")

if __name__ == "__main__":
    main()
