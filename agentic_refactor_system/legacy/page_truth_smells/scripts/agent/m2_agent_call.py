import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from openhands.sdk import LLM, Agent, Conversation, Tool
from openhands.sdk.conversation import get_agent_final_response
from openhands.sdk.event import MessageEvent
from openhands.sdk.llm.message import content_to_str
from openhands.tools.delegate import DelegateTool


FILE_BLOCK_RE = re.compile(
    r"BEGIN_FILE:\s*(?P<path>[^\r\n]+)\r?\n```[^\n]*\r?\n(?P<body>.*?)\r?\n```\r?\nEND_FILE",
    re.DOTALL,
)


def extract_assistant_text_from_events(events):
    """Extract best-effort assistant text from a list of OpenHands events."""
    final_text = get_agent_final_response(events)
    if final_text and final_text.strip():
        return final_text.strip()
    parts = []
    for event in events:
        if isinstance(event, MessageEvent) and event.source == "agent":
            text = "".join(content_to_str(event.llm_message.content)).strip()
            if text:
                parts.append(text)
    return "\n\n".join(parts).strip()


def parse_begin_file_response(text):
    blocks = []
    for match in FILE_BLOCK_RE.finditer(text):
        rel_path = match.group("path").strip()
        body = match.group("body")
        blocks.append((rel_path, body))
    return blocks


def validate_and_resolve_path(root, rel_path):
    target = (root / rel_path).resolve()
    if not str(target).startswith(str(root.resolve())):
        raise ValueError(f"Unsafe path outside repo: {rel_path}")
    return target


def apply_file_blocks(root, blocks, originals):
    touched = []
    for rel_path, body in blocks:
        target = validate_and_resolve_path(root, rel_path)
        if target.exists() and target not in originals:
            originals[target] = target.read_text(encoding="utf-8")
        elif (not target.exists()) and target not in originals:
            originals[target] = None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        touched.append(str(target))
    return touched


def restore_originals(originals):
    for path_obj, content in originals.items():
        if content is None:
            if path_obj.exists():
                path_obj.unlink()
        else:
            path_obj.write_text(content, encoding="utf-8")


def run_build(root, attempt, runs_dir, task_id):
    cmd = ["npm.cmd", "run", "build"] if os.name == "nt" else ["npm", "run", "build"]
    result = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
    build_log_file = runs_dir / f"{task_id}_build_attempt{attempt}.log"
    build_log_file.write_text(
        f"$ {' '.join(cmd)}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n",
        encoding="utf-8",
    )
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    if result.returncode != 0 and "spawn EPERM" in combined and os.name == "nt":
        esbuild_exe = root / "node_modules" / "@esbuild" / "win32-x64" / "esbuild.exe"
        entry = root / "src" / "main.jsx"
        out_file = runs_dir / f"{task_id}_esbuild_attempt{attempt}.js"
        if esbuild_exe.exists() and entry.exists():
            fallback_cmd = [
                str(esbuild_exe),
                str(entry),
                "--bundle",
                "--format=esm",
                "--outfile=" + str(out_file),
            ]
            fallback = subprocess.run(
                fallback_cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
            )
            with build_log_file.open("a", encoding="utf-8") as f:
                f.write("\n--- FALLBACK COMPILE CHECK (esbuild.exe) ---\n")
                f.write(f"$ {' '.join(fallback_cmd)}\n\n")
                f.write(f"STDOUT:\n{fallback.stdout}\n\nSTDERR:\n{fallback.stderr}\n")
                f.write(f"FALLBACK_EXIT={fallback.returncode}\n")
            if fallback.returncode == 0:
                return subprocess.CompletedProcess(cmd, 0, result.stdout, result.stderr), build_log_file
    return result, build_log_file


def append_eval_note(eval_log_file, task_id, status, details):
    if not eval_log_file:
        return
    eval_log_file.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    block = [f"\n## {ts} - {task_id} - m2 verify loop", f"- Status: {status}"]
    for line in details:
        block.append(f"- {line}")
    eval_log_file.write_text(
        eval_log_file.read_text(encoding="utf-8") + "\n".join(block) + "\n"
        if eval_log_file.exists()
        else "\n".join(block) + "\n",
        encoding="utf-8",
    )


def load_tasks(root: Path, task_id: str, run_all: bool):
    manifest = json.loads((root / "dataset" / "manifest.json").read_text(encoding="utf-8"))
    tasks = manifest.get("tasks", [])
    if run_all:
        return tasks
    if task_id:
        selected = [t for t in tasks if t.get("id") == task_id]
        if not selected:
            raise SystemExit(f"Task not found in manifest: {task_id}")
        return selected
    raise SystemExit("Provide --task <id> or --all")


def event_to_text(event):
    """Render one event into a readable line/block without assuming schema stability."""
    lines = []
    lines.append(f"type={type(event).__name__}")
    source = getattr(event, "source", None)
    if source is not None:
        lines.append(f"source={source}")

    llm_message = getattr(event, "llm_message", None)
    if llm_message is not None:
        role = getattr(llm_message, "role", None)
        if role is not None:
            lines.append(f"role={role}")
        content = getattr(llm_message, "content", None)
        if content is not None:
            try:
                text = "".join(content_to_str(content)).strip()
            except Exception:
                text = str(content)
            if text:
                lines.append("content:")
                lines.append(text)

    action = getattr(event, "action", None)
    if action is not None:
        lines.append(f"action={action}")
    observation = getattr(event, "observation", None)
    if observation is not None:
        lines.append(f"observation={observation}")
    tool_name = getattr(event, "tool_name", None)
    if tool_name is not None:
        lines.append(f"tool_name={tool_name}")

    thought = getattr(event, "thought", None)
    if thought:
        lines.append("thought:")
        lines.append(str(thought))

    return "\n".join(lines)


def write_event_transcript(events, out_file: Path, final_text=""):
    """Write a human-readable event stream transcript for analysis."""
    chunks = []
    for idx, event in enumerate(events):
        chunks.append(f"--- EVENT {idx} ---")
        chunks.append(event_to_text(event))
        chunks.append("")
    chunks.append("=== FINAL_EXTRACTED_RESPONSE ===")
    chunks.append(final_text or "")
    out_file.write_text("\n".join(chunks), encoding="utf-8")


def build_refactor_prompt(base_prompt, attempt, critique_feedback="", build_feedback="", use_delegate=False):
    sections = [base_prompt.strip()]
    sections.append(
        """
REFINEMENT LOOP CONTEXT
- Attempt: {attempt}
- You are the REFACTORING agent.
- Preserve behavior and public contracts.
- Keep edits minimal and focused.
- Keep imports/exports valid.
- Output ONLY BEGIN_FILE/END_FILE blocks with full file contents.
- After last file output exactly: END_RESPONSE
""".strip().format(attempt=attempt)
    )
    if use_delegate:
        sections.append(
            """
DELEGATION MODE
- You MUST use the delegate tool during this attempt.
- First spawn two sub-agents with ids: refactorer, verifier.
- Then delegate tasks:
  - refactorer: propose minimal behavior-preserving refactor edits.
  - verifier: check import/export correctness and output-format compliance.
- Merge useful results and produce the final BEGIN_FILE blocks.
""".strip()
        )
    if critique_feedback:
        sections.append("CRITIQUE_FEEDBACK\n" + critique_feedback.strip())
    if build_feedback:
        sections.append("BUILD_FEEDBACK\n" + build_feedback.strip())
    return "\n\n".join(sections)


def build_critique_prompt(task_id, base_prompt, candidate_text, touched_files, build_ok, build_log_tail):
    touched = "\n".join(f"- {f}" for f in touched_files) or "- (none)"
    build_status = "PASSED" if build_ok else "FAILED"
    return f"""
You are the CRITIQUE agent for task {task_id}. You are a reviewer, not an editor.

Evaluate whether the candidate refactor should be accepted.
Review for:
- task compliance
- behavior preservation risk
- import/export issues
- incomplete edits
- over-editing
- likely runtime/semantic issues

Do NOT propose rewritten files. Do NOT output BEGIN_FILE blocks.
Return STRICT JSON only with this schema:
{{
  "score": 0.0,
  "acceptable": false,
  "issues": ["..."],
  "repair_instructions": ["..."],
  "summary": "..."
}}

Task prompt context:
{base_prompt}

Touched files:
{touched}

Build status: {build_status}
Build log tail:
{build_log_tail}

Candidate response text:
{candidate_text}
""".strip()


def normalize_critique_json(raw_text):
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
    try:
        obj = json.loads(text)
    except Exception:
        return {
            "score": 0.0,
            "acceptable": False,
            "issues": ["Critique agent returned invalid JSON."],
            "repair_instructions": ["Return valid critique JSON and ensure candidate correctness."],
            "summary": "Critique output invalid.",
        }

    score = obj.get("score")
    acceptable = obj.get("acceptable")
    issues = obj.get("issues")
    repair_instructions = obj.get("repair_instructions")
    summary = obj.get("summary")

    valid = (
        isinstance(score, (int, float))
        and 0.0 <= float(score) <= 1.0
        and isinstance(acceptable, bool)
        and isinstance(issues, list)
        and all(isinstance(i, str) for i in issues)
        and isinstance(repair_instructions, list)
        and all(isinstance(i, str) for i in repair_instructions)
        and isinstance(summary, str)
    )
    if not valid:
        return {
            "score": 0.0,
            "acceptable": False,
            "issues": ["Critique agent returned schema-invalid JSON."],
            "repair_instructions": ["Return valid critique JSON and ensure candidate correctness."],
            "summary": "Critique output schema-invalid.",
        }

    return {
        "score": float(score),
        "acceptable": acceptable,
        "issues": issues,
        "repair_instructions": repair_instructions,
        "summary": summary.strip(),
    }


def run_refactor_agent(
    root,
    task_id,
    llm,
    base_prompt,
    critique_feedback,
    build_feedback,
    attempt,
    runs_dir,
    use_delegate=False,
):
    """Run specialized refactoring agent and persist attempt output + transcript."""
    tools = []
    if use_delegate:
        tools.append(Tool(name=DelegateTool.name))
    agent = Agent(llm=llm, tools=tools)
    captured_events = []

    def _capture_event(event):
        captured_events.append(event)

    conversation = Conversation(
        agent=agent,
        workspace=str(root),
        callbacks=[_capture_event],
        visualizer=None,
        max_iteration_per_run=80,
    )

    prompt = build_refactor_prompt(
        base_prompt=base_prompt,
        attempt=attempt,
        critique_feedback=critique_feedback,
        build_feedback=build_feedback,
        use_delegate=use_delegate,
    )
    conversation.send_message(prompt)
    conversation.run()

    text = extract_assistant_text_from_events(captured_events).strip()
    out_file = runs_dir / f"{task_id}_refactor_attempt{attempt}.txt"
    out_file.write_text(text + ("\n" if text else ""), encoding="utf-8")

    transcript_file = runs_dir / f"{task_id}_refactor_events_attempt{attempt}.txt"
    write_event_transcript(captured_events, transcript_file, final_text=text)
    return text, captured_events


def run_critique_agent(
    root,
    task_id,
    llm,
    base_prompt,
    candidate_text,
    touched_files,
    build_ok,
    build_log_tail,
    attempt,
    runs_dir,
):
    """Run specialized critique agent and return normalized critique JSON object."""
    agent = Agent(llm=llm, tools=[])
    captured_events = []

    def _capture_event(event):
        captured_events.append(event)

    conversation = Conversation(
        agent=agent,
        workspace=str(root),
        callbacks=[_capture_event],
        visualizer=None,
        max_iteration_per_run=80,
    )

    prompt = build_critique_prompt(
        task_id=task_id,
        base_prompt=base_prompt,
        candidate_text=candidate_text,
        touched_files=touched_files,
        build_ok=build_ok,
        build_log_tail=build_log_tail,
    )
    conversation.send_message(prompt)
    conversation.run()

    raw_text = extract_assistant_text_from_events(captured_events).strip()
    raw_file = runs_dir / f"{task_id}_critique_attempt{attempt}.txt"
    raw_file.write_text(raw_text + ("\n" if raw_text else ""), encoding="utf-8")

    transcript_file = runs_dir / f"{task_id}_critique_events_attempt{attempt}.txt"
    write_event_transcript(captured_events, transcript_file, final_text=raw_text)

    critique_obj = normalize_critique_json(raw_text)
    return critique_obj, raw_text, captured_events


def compose_refactor_feedback(critique_obj, build_ok, build_log_tail):
    """Compose structured feedback for the next refactor attempt."""
    lines = [
        "PREVIOUS ATTEMPT FEEDBACK",
        f"Critique summary: {critique_obj.get('summary', '')}",
        f"Critique score: {critique_obj.get('score', 0.0)}",
        "Issues:",
    ]
    issues = critique_obj.get("issues", []) or ["(none)"]
    for i in issues:
        lines.append(f"- {i}")
    lines.append("Repair instructions:")
    repairs = critique_obj.get("repair_instructions", []) or ["(none)"]
    for r in repairs:
        lines.append(f"- {r}")
    lines.append(f"Build status: {'PASSED' if build_ok else 'FAILED'}")
    if build_log_tail:
        lines.append("Build errors/log tail:")
        lines.append(build_log_tail)
    return "\n".join(lines)


def run_task(root: Path, task_id: str, args, refactor_llm, critique_llm, eval_log_file: Path):
    runs_dir = root / "scripts" / "agent" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = runs_dir / f"{task_id}_prompt.txt"
    response_file = runs_dir / f"{task_id}_response.txt"
    debug_events_file = runs_dir / f"{task_id}_events_debug.txt"

    if not prompt_file.exists():
        raise SystemExit(f"Prompt file not found: {prompt_file}")
    base_prompt = prompt_file.read_text(encoding="utf-8")

    originals = {}
    debug_lines = []
    success = False

    latest_build_feedback = ""
    latest_critique_feedback = ""
    latest_candidate_text = ""
    latest_critique_obj = {
        "score": 0.0,
        "acceptable": False,
        "issues": [],
        "repair_instructions": [],
        "summary": "",
    }
    touched_files = []
    attempts_used = 0
    final_build_passed = False

    try:
        for attempt in range(1, args.max_attempts + 1):
            attempts_used = attempt
            refactor_text, refactor_events = run_refactor_agent(
                root=root,
                task_id=task_id,
                llm=refactor_llm,
                base_prompt=base_prompt,
                critique_feedback=latest_critique_feedback,
                build_feedback=latest_build_feedback,
                attempt=attempt,
                runs_dir=runs_dir,
                use_delegate=args.use_delegate,
            )
            latest_candidate_text = refactor_text

            debug_lines.append(f"attempt={attempt}")
            debug_lines.append(f"refactor_event_count={len(refactor_events)}")

            blocks = parse_begin_file_response(refactor_text)
            if not blocks:
                latest_critique_obj = {
                    "score": 0.0,
                    "acceptable": False,
                    "issues": ["Refactor output missing valid BEGIN_FILE blocks."],
                    "repair_instructions": [
                        "Return ONLY BEGIN_FILE/END_FILE blocks with full file contents and END_RESPONSE."
                    ],
                    "summary": "Refactor output format invalid.",
                }
                latest_build_feedback = "Build status: NOT_RUN (invalid output format)."
                latest_critique_feedback = compose_refactor_feedback(
                    latest_critique_obj,
                    build_ok=False,
                    build_log_tail="No build executed due to invalid output format.",
                )
                continue

            touched_files = apply_file_blocks(root, blocks, originals)
            result, build_log_file = run_build(root, attempt, runs_dir, task_id)
            build_ok = result.returncode == 0
            final_build_passed = build_ok
            build_tail = (result.stdout + "\n" + result.stderr)[-10000:]
            latest_build_feedback = (
                f"Build status: {'PASSED' if build_ok else 'FAILED'}\n"
                f"Build log file: {build_log_file.name}\n"
                f"Build log tail:\n{build_tail}"
            )

            critique_obj, _raw_critique, critique_events = run_critique_agent(
                root=root,
                task_id=task_id,
                llm=critique_llm,
                base_prompt=base_prompt,
                candidate_text=refactor_text,
                touched_files=touched_files,
                build_ok=build_ok,
                build_log_tail=build_tail,
                attempt=attempt,
                runs_dir=runs_dir,
            )
            latest_critique_obj = critique_obj
            debug_lines.append(f"critique_event_count={len(critique_events)}")
            debug_lines.append(f"critique_score={critique_obj.get('score')}")
            debug_lines.append(f"critique_acceptable={critique_obj.get('acceptable')}")

            accepted = (
                build_ok
                and critique_obj.get("acceptable") is True
                and float(critique_obj.get("score", 0.0)) >= float(args.critique_threshold)
            )
            if accepted:
                success = True
                break

            latest_critique_feedback = compose_refactor_feedback(
                critique_obj,
                build_ok=build_ok,
                build_log_tail=build_tail,
            )

        debug_events_file.write_text("\n".join(debug_lines) + "\n", encoding="utf-8")

        if success:
            response_file.write_text(
                latest_candidate_text + ("\n" if latest_candidate_text and not latest_candidate_text.endswith("\n") else ""),
                encoding="utf-8",
            )
            append_eval_note(
                eval_log_file,
                task_id,
                "success",
                [
                    "Good: dedicated refactoring and critique agents were both exercised.",
                    "Good: host-side build validation and critique threshold both passed.",
                    "Good: final candidate satisfied multi-signal acceptance.",
                ],
            )
            status = "success"
        else:
            response_file.write_text(
                "[FAILED] Iterative refinement exhausted attempts without satisfying build+critique acceptance.\n"
                f"See logs in {runs_dir}\n",
                encoding="utf-8",
            )
            append_eval_note(
                eval_log_file,
                task_id,
                "failed",
                [
                    "Bad: candidate did not satisfy build + critique acceptance threshold.",
                    "Bad: iterative refinement exhausted attempts.",
                    f"Evidence: see per-attempt logs in {runs_dir}",
                ],
            )
            status = "failed"

        return {
            "task_id": task_id,
            "status": status,
            "response_file": str(response_file),
            "touched_files": touched_files,
            "critique_score": float(latest_critique_obj.get("score", 0.0)),
            "critique_acceptable": bool(latest_critique_obj.get("acceptable", False)),
            "build_passed": bool(final_build_passed),
            "attempts_used": attempts_used,
        }
    except Exception as e:
        response_file.write_text(f"[ERROR]\n{e}\n", encoding="utf-8")
        append_eval_note(
            eval_log_file,
            task_id,
            "error",
            [f"Bad: run crashed with exception: {e}"],
        )
        return {
            "task_id": task_id,
            "status": "error",
            "error": str(e),
            "critique_score": float(latest_critique_obj.get("score", 0.0)),
            "critique_acceptable": bool(latest_critique_obj.get("acceptable", False)),
            "build_passed": bool(final_build_passed),
            "attempts_used": attempts_used,
        }
    finally:
        if not args.keep_applied:
            restore_originals(originals)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="", help="Task id, e.g. ex05")
    parser.add_argument("--all", action="store_true", help="Run all tasks in manifest")
    parser.add_argument("--root", default=".", help="repo root")
    parser.add_argument("--max-attempts", type=int, default=3, help="max generate+repair attempts per task")
    parser.add_argument("--keep-applied", action="store_true", help="keep candidate files applied in working tree")
    parser.add_argument("--eval-log", default="", help="optional path for appending OpenHands good/bad notes")
    parser.add_argument("--model", default="gpt-5.2-codex", help="subscription model name for LLM.subscription_login")
    parser.add_argument("--critique-threshold", type=float, default=0.8, help="acceptance threshold for critique score")
    parser.add_argument("--use-delegate", action="store_true", help="enable DelegateTool for refactor agent")
    parser.add_argument("--delegate-count", type=int, default=3, help="when --use-delegate and --all are used, limit run to first N tasks")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    runs_dir = root / "scripts" / "agent" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    eval_log_file = (
        Path(args.eval_log).resolve()
        if args.eval_log
        else root.parent / "OPENHANDS_EVAL_NOTEBOOK.md"
    )
    tasks = load_tasks(root, args.task, args.all)
    if args.use_delegate and args.all and not args.task:
        tasks = tasks[: max(1, int(args.delegate_count))]
        selected = ", ".join(t["id"] for t in tasks)
        print(f"[m2] delegate mode enabled: running {len(tasks)} task(s): {selected}")

    refactor_llm = LLM.subscription_login(vendor="openai", model=args.model, prompt_cache_retention=None)
    critique_llm = LLM.subscription_login(vendor="openai", model=args.model, prompt_cache_retention=None)

    results = []
    for task in tasks:
        task_id = task["id"]
        print(f"[m2] running {task_id} ...")
        result = run_task(root, task_id, args, refactor_llm, critique_llm, eval_log_file)
        results.append(result)
        print(f"[m2] {task_id} -> {result.get('status')}")

    summary_file = runs_dir / "m2_summary.json"
    summary_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved summary: {summary_file}")


if __name__ == "__main__":
    main()
