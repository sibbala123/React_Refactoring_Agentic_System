import json
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure we import from the local package
sys.path.insert(0, str(Path(__file__).parent.parent))
from agentic_refactor_system.langgraph_pipeline.runner import run_task

def main():
    load_dotenv()
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("ERROR: OPENAI_API_KEY not set.")

    # Configure root logging so we see what the pipeline does
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")

    root = Path(r"C:\Users\Admin\Desktop\React Refactor")
    ds_dir = root / "data" / "supabase_design_system"
    
    manifest = json.loads((ds_dir / "manifest.json").read_text(encoding="utf-8"))
    context_data = json.loads((ds_dir / "context_index.json").read_text(encoding="utf-8"))
    smell_data = json.loads((ds_dir / "smell_report.json").read_text(encoding="utf-8"))
    
    # Pick the first suitable task
    task_idx = 0
    mt = manifest["tasks"][task_idx]
    
    # Critical: Override target root with the real physical supabase repo!
    # The tasks target `apps/design-system` files like `registry/default/example/data-grid-demo.tsx`
    mt["target_root"] = r"C:\Users\Admin\Desktop\supabase\apps\design-system"
    
    # We will skip the pnpm build check for this test since pnpm is not in PATH
    mt["build_command"] = ""

    tid = mt["id"]
    sid = mt["smell_id"]
    
    ctx = next((c for c in context_data["contexts"] if c["task_id"] == tid), {})
    smell = next((s for s in smell_data["smells"] if s["smell_id"] == sid), {})
    
    print("=" * 70)
    print(f"RUNNING SINGLE TASK {tid} ON PHYSICAL REPO")
    print(f"Smell: {smell.get('smell_type')} | Target: {mt['target_file']}")
    print("=" * 70)
    
    try:
        state = run_task(mt, smell, ctx, show_progress=True)
        
        print("\n\n" + "=" * 70)
        print("FINAL STATE RESULT:")
        print(f"Status: {state.get('status')}")
        
        if state.get("verification_result"):
            print("\nVerification Checks:")
            print(json.dumps(state["verification_result"]["checks"], indent=2))
            
    except Exception as e:
        print(f"\nPipeline crashed: {e}")

if __name__ == "__main__":
    main()
