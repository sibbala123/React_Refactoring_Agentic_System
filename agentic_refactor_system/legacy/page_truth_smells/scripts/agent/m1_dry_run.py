import argparse
import csv
import json
import subprocess
from pathlib import Path


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_refactor_spec(path: Path):
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def run_cmd(args, cwd: Path):
    p = subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def is_source_file(path: str):
    p = path.lower().replace("\\", "/")
    if p.startswith("dataset/") or p.startswith("artifacts") or p.startswith("truth"):
        return False
    if p.endswith(
        (
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
            ".svg",
            ".json",
            ".html",
            ".log",
            ".txt",
            ".patch",
            ".csv",
            ".md",
            ".lock",
        )
    ):
        return False
    return p.endswith((".js", ".jsx", ".ts", ".tsx", ".css"))


def get_relevant_files(repo_root: Path, before_branch: str):
    candidates = [
        ["git", "diff", "--name-only", f"master...{before_branch}"],
        ["git", "diff", "--name-only", f"main...{before_branch}"],
    ]
    for cmd in candidates:
        code, out, _ = run_cmd(cmd, repo_root)
        files = [x.strip() for x in out.splitlines() if x.strip()]
        files = [f for f in files if is_source_file(f)]
        if code == 0 and files:
            return files, " ".join(cmd)
    return [], "none"


def build_code_context(repo_root: Path, files, max_chars=40000):
    chunks = []
    total = 0
    for rel in files:
        p = repo_root / rel
        if not p.exists() or not p.is_file():
            continue
        content = p.read_text(encoding="utf-8", errors="replace")
        block = f"===== FILE: {rel} =====\n{content}\n\n"
        if total + len(block) > max_chars:
            remaining = max_chars - total
            if remaining > 0:
                chunks.append(block[:remaining] + "\n[TRUNCATED]\n")
            break
        chunks.append(block)
        total += len(block)
    return "".join(chunks)


def build_prompt_payload(task, allowed, files, code_context):
    fallback_by_smell = {
        "Large Component": [
            "Extract smaller presentational components.",
            "Move non-UI logic into utility functions or hooks.",
            "Split state handling by concern while preserving behavior.",
        ],
        "Duplicated Code": [
            "Extract shared utility functions for repeated pure logic.",
            "Extract shared UI component for repeated markup.",
            "Parameterize repeated variants with props.",
        ],
        "Too Many Props": [
            "Group related props into objects with stable shape.",
            "Derive values locally where safe instead of passing through.",
            "Extract subcomponents to reduce prop surface.",
        ],
        "Prop Drilling": [
            "Use React context for deeply shared data/actions.",
            "Co-locate state nearer heavy consumers where safe.",
            "Introduce custom hooks to centralize shared state access.",
        ],
        "Inline Logic in Render": [
            "Move complex conditions/computations out of JSX into named helpers.",
            "Precompute render values before return.",
            "Extract repeated conditional blocks into dedicated components/functions.",
        ],
    }

    if allowed:
        allowed_text = "\n".join(
            f"- {r.get('Possible Refactoring', '').strip()}: {r.get('Definition', '').strip()}"
            for r in allowed
        )
    else:
        fallback = fallback_by_smell.get(task.get("smell", "").strip(), [])
        allowed_text = "\n".join(f"- {item}" for item in fallback) or "- (none)"
    files_text = "\n".join(f"- {f}" for f in files) or "- (none)"
    return f"""You are a senior React refactoring agent.

TASK
- Task ID: {task["id"]}
- Target smell: {task["smell"]}
- Before branch: {task["before_branch"]}
- After branch: {task["after_branch"]}
- Target routes: {task.get("routes", [])}
- Target states: {task.get("states", [])}

PRIMARY GOAL
Refactor to reduce the target smell while preserving user-visible behavior.

BEHAVIORAL INVARIANTS (MUST NOT BREAK)
1. Route behavior and navigation must remain unchanged.
2. Visible labels/text used in UI should remain unchanged.
3. Interaction flows for the listed states must remain equivalent.
4. DOM structure can be reorganized internally, but rendered output intent should match.
5. Do not introduce runtime errors, missing imports, or broken handlers.
6. Keep styling and layout behavior equivalent (no intentional visual redesign).
7. Keep existing prop contracts unless changed consistently across all call sites.

ALLOWED REFACTORINGS (USE ONLY THESE)
{allowed_text}

FILES YOU MAY EDIT
{files_text}

HARD CONSTRAINTS
1. Edit only files listed in FILES YOU MAY EDIT.
2. Do not touch generated artifacts, dataset outputs, or truth files.
3. Keep changes focused to smell reduction; avoid unrelated cleanup.
4. Preserve existing business logic and edge-case behavior.
5. No placeholder TODO code.
6. No partial snippets.

OUTPUT FORMAT (STRICT)
Return full file replacements only, no prose:
BEGIN_FILE: <relative/path>
```<language>
<full file content>
```
END_FILE
If multiple files change, emit multiple FILE blocks.
After the last file, print exactly: END_RESPONSE

CODE CONTEXT
{code_context}
"""


def run_task(root: Path, task, spec_rows, max_context: int):
    allowed = [
        r
        for r in spec_rows
        if r.get("Code Smell", "").strip() == task.get("smell", "").strip()
    ]
    files, source_cmd = get_relevant_files(root, task["before_branch"])
    code_context = build_code_context(root, files, max_chars=max_context)
    payload = build_prompt_payload(task, allowed, files, code_context)
    runs_dir = root / "scripts" / "agent" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = runs_dir / f"{task['id']}_prompt.txt"
    prompt_file.write_text(payload, encoding="utf-8")
    return {
        "task_id": task["id"],
        "smell": task["smell"],
        "before_branch": task["before_branch"],
        "after_branch": task["after_branch"],
        "source_cmd": source_cmd,
        "relevant_files": files,
        "context_len": len(code_context),
        "prompt_file": str(prompt_file),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="", help="Task id (e.g. ex05)")
    parser.add_argument("--all", action="store_true", help="Generate prompts for all tasks")
    parser.add_argument("--root", default=".", help="Path to page-truth-smells root")
    parser.add_argument("--max-context", type=int, default=40000)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    manifest_path = root / "dataset" / "manifest.json"
    spec_path = root / "dataset" / "refactoring_spec_v1.csv"
    manifest = load_json(manifest_path)
    tasks = manifest.get("tasks", [])
    spec_rows = load_refactor_spec(spec_path)
    if not spec_path.exists():
        print(f"[m1] Warning: {spec_path} not found. Using built-in fallback refactoring guidance.")

    if args.all:
        selected = tasks
    elif args.task:
        selected = [t for t in tasks if t.get("id") == args.task]
        if not selected:
            raise SystemExit(f"Task not found: {args.task}")
    else:
        raise SystemExit("Provide --task <id> or --all")

    summary = []
    for task in selected:
        result = run_task(root, task, spec_rows, args.max_context)
        summary.append(result)
        print(f"[m1] {task['id']} prompt -> {result['prompt_file']} ({result['context_len']} chars)")

    runs_dir = root / "scripts" / "agent" / "runs"
    summary_file = runs_dir / "m1_summary.json"
    summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nSaved summary: {summary_file}")


if __name__ == "__main__":
    main()
