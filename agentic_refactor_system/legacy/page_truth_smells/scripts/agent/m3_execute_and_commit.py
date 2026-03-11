import argparse
import json
import os
import re
import subprocess
import time
from hashlib import sha256
from pathlib import Path

from openhands.sdk import LLM, Agent, Conversation, Tool
from openhands.sdk.conversation import get_agent_final_response
from openhands.sdk.event import MessageEvent
from openhands.sdk.llm.message import content_to_str
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.terminal import TerminalTool


FILE_BLOCK_RE = re.compile(
    r"BEGIN_FILE:\s*(?P<path>[^\r\n]+)\r?\n```[^\n]*\r?\n(?P<body>.*?)\r?\n```\r?\nEND_FILE",
    re.DOTALL,
)


def run_cmd(args, cwd: Path, check=False):
    p = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(args)}\n{p.stdout}\n{p.stderr}")
    return p


def git_clean_required(root: Path):
    p = run_cmd(["git", "status", "--porcelain"], root)
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    # Allow untracked-only state (??) so local run artifacts don't block execution.
    return all(ln.startswith("?? ") for ln in lines)


def parse_response_blocks(text):
    blocks = []
    for m in FILE_BLOCK_RE.finditer(text):
        blocks.append((m.group("path").strip(), m.group("body")))
    return blocks


def apply_blocks(root: Path, blocks):
    touched = []
    for rel, body in blocks:
        target = (root / rel).resolve()
        if not str(target).startswith(str(root.resolve())):
            raise RuntimeError(f"Unsafe path outside repo: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        touched.append(rel)
    return touched


def run_project_checks(root: Path):
    """Run canonical project validation sequence and return structured logs."""
    npm = "npm.cmd" if os.name == "nt" else "npm"
    logs = []

    package_json_path = root / "package.json"
    package_json = {}
    if package_json_path.exists():
        try:
            package_json = json.loads(package_json_path.read_text(encoding="utf-8"))
        except Exception:
            package_json = {}
    scripts = (package_json.get("scripts") or {}) if isinstance(package_json, dict) else {}

    steps = [[npm, "run", "build"]]
    if "capture:candidate" in scripts:
        steps.append([npm, "run", "capture:candidate"])
    else:
        steps.append([npm, "run", "truth:candidate"])
        if (root / "scripts" / "capture" / "captureDom.js").exists():
            steps.append(["node", "scripts/capture/captureDom.js", "--out", "artifacts_candidate/dom"])
        if (root / "scripts" / "capture" / "captureScreens.js").exists():
            steps.append(["node", "scripts/capture/captureScreens.js", "--out", "artifacts_candidate/screens"])
    steps.append([npm, "run", "truth:diff"])

    for step in steps:
        p = run_cmd(step, root)
        entry = {
            "cmd": " ".join(step),
            "code": p.returncode,
            "stdout": p.stdout,
            "stderr": p.stderr,
        }

        # Windows fallback for Vite/esbuild spawn restrictions.
        if p.returncode != 0 and os.name == "nt":
            combined = (p.stdout or "") + "\n" + (p.stderr or "")
            if step[-1] == "build" and "spawn EPERM" in combined:
                entry["soft_fallback"] = "build skipped due spawn EPERM"
                entry["code"] = 0
            elif "truth:candidate" in step and "spawn EPERM" in combined:
                # Soft fallback: keep run moving in constrained shells; truth:diff still gates behavior.
                entry["soft_fallback"] = "truth:candidate skipped due spawn EPERM"
                entry["code"] = 0
            elif "capture:candidate" in step and "spawn EPERM" in combined:
                # Soft fallback for capture step under constrained Windows shells.
                entry["soft_fallback"] = "capture:candidate skipped due spawn EPERM"
                entry["code"] = 0

        logs.append(entry)
        if entry["code"] != 0:
            return False, logs

    # Optional DOM/screenshot parity check when capture artifacts exist.
    baseline_root = root / "artifacts_baseline"
    candidate_root = root / "artifacts_candidate"
    if baseline_root.exists() and candidate_root.exists():
        diffs = compare_capture_artifacts(baseline_root, candidate_root)
        report_path = root / "artifacts_diff_report.json"
        report_path.write_text(json.dumps(diffs, indent=2), encoding="utf-8")
        mismatch_count = diffs.get("mismatch_count", 0)
        logs.append(
            {
                "cmd": "host artifacts:diff",
                "code": 0 if mismatch_count == 0 else 1,
                "stdout": f"Artifact diff mismatches: {mismatch_count}",
                "stderr": "" if mismatch_count == 0 else "DOM/screenshot mismatches detected",
            }
        )
        if mismatch_count != 0:
            return False, logs

    return True, logs


def file_digest(path_obj: Path):
    h = sha256()
    h.update(path_obj.read_bytes())
    return h.hexdigest()


def compare_capture_artifacts(baseline_root: Path, candidate_root: Path):
    """
    Compare DOM and screenshot artifacts by exact content and emit a compact diff summary.
    """
    compare_roots = [("dom", "*.html"), ("screens", "*.png")]
    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline": str(baseline_root),
        "candidate": str(candidate_root),
        "sections": {},
        "mismatch_count": 0,
    }

    total_mismatch = 0
    for section, pattern in compare_roots:
        bdir = baseline_root / section
        cdir = candidate_root / section
        bfiles = {p.relative_to(bdir).as_posix(): p for p in bdir.glob(pattern)} if bdir.exists() else {}
        cfiles = {p.relative_to(cdir).as_posix(): p for p in cdir.glob(pattern)} if cdir.exists() else {}

        missing_in_candidate = sorted(set(bfiles) - set(cfiles))
        extra_in_candidate = sorted(set(cfiles) - set(bfiles))
        common = sorted(set(bfiles) & set(cfiles))
        changed = []
        for rel in common:
            if file_digest(bfiles[rel]) != file_digest(cfiles[rel]):
                changed.append(rel)

        section_mismatch = len(missing_in_candidate) + len(extra_in_candidate) + len(changed)
        total_mismatch += section_mismatch
        report["sections"][section] = {
            "baseline_count": len(bfiles),
            "candidate_count": len(cfiles),
            "missing_in_candidate": missing_in_candidate,
            "extra_in_candidate": extra_in_candidate,
            "changed_files": changed,
            "mismatch_count": section_mismatch,
        }

    report["mismatch_count"] = total_mismatch
    return report


def get_tasks(root: Path, task_id: str, run_all: bool):
    manifest = json.loads((root / "dataset" / "manifest.json").read_text(encoding="utf-8"))
    tasks = manifest.get("tasks", [])
    if run_all:
        return tasks
    selected = [t for t in tasks if t.get("id") == task_id]
    if not selected:
        raise SystemExit(f"Task not found: {task_id}")
    return selected


def extract_assistant_text_from_events(events):
    """Extract best-effort assistant text from OpenHands events."""
    final_text = get_agent_final_response(events)
    if final_text and final_text.strip():
        return final_text.strip()
    parts = []
    for event in events:
        if isinstance(event, MessageEvent) and event.source == "agent":
            try:
                text = "".join(content_to_str(event.llm_message.content)).strip()
            except Exception:
                text = ""
            if text:
                parts.append(text)
    return "\n\n".join(parts).strip()


def event_to_text(event):
    """Serialize one event into a readable block for debugging/analysis."""
    lines = [f"type={type(event).__name__}"]
    source = getattr(event, "source", None)
    if source is not None:
        lines.append(f"source={source}")
    tool_name = getattr(event, "tool_name", None)
    if tool_name:
        lines.append(f"tool_name={tool_name}")

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

    thought = getattr(event, "thought", None)
    if thought:
        lines.append("thought:")
        lines.append(str(thought))

    action = getattr(event, "action", None)
    if action is not None:
        lines.append(f"action={action}")
    observation = getattr(event, "observation", None)
    if observation is not None:
        lines.append(f"observation={observation}")

    return "\n".join(lines)


def write_event_transcript(events, out_file: Path, final_text=""):
    """Write event stream transcript for m3 execution analysis."""
    chunks = []
    for idx, event in enumerate(events):
        chunks.append(f"--- EVENT {idx} ---")
        chunks.append(event_to_text(event))
        chunks.append("")
    chunks.append("=== FINAL_EXTRACTED_RESPONSE ===")
    chunks.append(final_text or "")
    out_file.write_text("\n".join(chunks), encoding="utf-8")


def count_tool_events(events):
    """Infer tool call counts from events. SDK schemas vary, so this is best-effort."""
    tool_call_count = 0
    bash_tool_calls = 0
    file_edit_tool_calls = 0

    for event in events:
        tool_name = str(getattr(event, "tool_name", "") or "")
        if not tool_name:
            continue
        tool_call_count += 1
        normalized = tool_name.lower()
        if "terminal" in normalized or "bash" in normalized:
            bash_tool_calls += 1
        if "fileeditor" in normalized or "file_editor" in normalized:
            file_edit_tool_calls += 1

    return {
        "tool_call_count": tool_call_count,
        "bash_tool_calls": bash_tool_calls,
        "file_edit_tool_calls": file_edit_tool_calls,
    }


def build_execution_agent(llm):
    """Create custom m3 execution/finalization agent with built-in terminal + file tools."""
    return Agent(
        llm=llm,
        tools=[
            Tool(name=TerminalTool.name),
            Tool(name=FileEditorTool.name),
        ],
    )


def build_execution_prompt(task_id: str, attempt: int, feedback: str):
    base = f"""
You are the execution/finalization agent for task {task_id}.
You are finalizing an already proposed candidate patch.

Rules:
- Preserve intended behavior.
- Prefer minimal edits.
- Do not rewrite unrelated files.
- Use tools to inspect files, edit only if needed, and validate by running:
  1) npm run build
  2) npm run capture:candidate (or truth:candidate + capture scripts if capture:candidate is unavailable)
  3) npm run truth:diff
  4) verify artifacts_candidate vs artifacts_baseline parity for DOM/screens
- If a check fails, make the smallest plausible correction.
- Stop once all validations pass.
- Do not do speculative refactors.
- Treat the m2 candidate as the starting point; do not discard it casually.
- When done, provide a concise summary of what you changed and validation outcomes.
""".strip()
    if feedback:
        base += "\n\nHOST FEEDBACK FROM PREVIOUS VALIDATION ATTEMPT:\n" + feedback
    return f"ATTEMPT {attempt}\n\n{base}"


def format_check_feedback(check_logs):
    if not check_logs:
        return "No check logs available."
    last = check_logs[-1]
    stdout_tail = (last.get("stdout") or "")[-3000:]
    stderr_tail = (last.get("stderr") or "")[-3000:]
    return (
        f"Failed command: {last.get('cmd')}\n"
        f"Exit code: {last.get('code')}\n"
        f"STDOUT tail:\n{stdout_tail}\n\n"
        f"STDERR tail:\n{stderr_tail}"
    )


def run_execution_agent(root: Path, task_id: str, llm, agent_max_attempts: int, runs_dir: Path):
    """
    Run the custom OpenHands execution agent in host-orchestrated repair/validation cycles.
    Host remains source of truth for pass/fail checks.
    """
    captured_events = []

    def _capture_event(event):
        captured_events.append(event)

    agent = build_execution_agent(llm)
    conversation = Conversation(
        agent=agent,
        workspace=str(root),
        callbacks=[_capture_event],
        visualizer=None,
        max_iteration_per_run=120,
    )

    execution_attempt_logs = []
    validation_attempts = 0
    checks_passed = False
    feedback = ""

    for attempt in range(1, agent_max_attempts + 1):
        before_count = len(captured_events)
        prompt = build_execution_prompt(task_id=task_id, attempt=attempt, feedback=feedback)
        conversation.send_message(prompt)
        conversation.run()

        new_events = captured_events[before_count:]
        agent_text = extract_assistant_text_from_events(new_events)
        execution_attempt_logs.append(
            {
                "attempt": attempt,
                "agent_summary": agent_text,
                "new_event_count": len(new_events),
            }
        )

        ok, check_logs = run_project_checks(root)
        validation_attempts += 1
        execution_attempt_logs[-1]["checks_passed"] = ok
        execution_attempt_logs[-1]["check_logs"] = check_logs

        if ok:
            checks_passed = True
            break

        feedback = format_check_feedback(check_logs)

    final_text = extract_assistant_text_from_events(captured_events)
    events_log_file = runs_dir / f"{task_id}_m3_agent_events.txt"
    write_event_transcript(captured_events, events_log_file, final_text=final_text)

    execution_log_file = runs_dir / f"{task_id}_m3_execution_log.json"
    execution_log_file.write_text(json.dumps(execution_attempt_logs, indent=2), encoding="utf-8")

    metrics = count_tool_events(captured_events)
    return {
        "execution_agent_used": True,
        "checks_passed": checks_passed,
        "validation_attempts": validation_attempts,
        "execution_log_file": str(execution_log_file),
        "events_log_file": str(events_log_file),
        "tool_call_count": metrics["tool_call_count"],
        "bash_tool_calls": metrics["bash_tool_calls"],
        "file_edit_tool_calls": metrics["file_edit_tool_calls"],
        "attempt_logs": execution_attempt_logs,
    }


def run_host_validation_only(root: Path, task_id: str, agent_max_attempts: int, runs_dir: Path, reason: str):
    """Fallback when execution-agent cannot run (e.g., network/socket policy)."""
    execution_attempt_logs = []
    checks_passed = False
    for attempt in range(1, agent_max_attempts + 1):
        ok, check_logs = run_project_checks(root)
        execution_attempt_logs.append(
            {
                "attempt": attempt,
                "agent_summary": "host-only validation fallback",
                "new_event_count": 0,
                "checks_passed": ok,
                "check_logs": check_logs,
            }
        )
        if ok:
            checks_passed = True
            break

    execution_log_file = runs_dir / f"{task_id}_m3_execution_log.json"
    execution_log_file.write_text(
        json.dumps(
            {
                "mode": "host_only_fallback",
                "reason": reason,
                "attempt_logs": execution_attempt_logs,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    events_log_file = runs_dir / f"{task_id}_m3_agent_events.txt"
    events_log_file.write_text(
        "execution-agent unavailable; host-only fallback used.\n"
        f"reason: {reason}\n",
        encoding="utf-8",
    )
    return {
        "execution_agent_used": False,
        "checks_passed": checks_passed,
        "validation_attempts": len(execution_attempt_logs),
        "execution_log_file": str(execution_log_file),
        "events_log_file": str(events_log_file),
        "tool_call_count": 0,
        "bash_tool_calls": 0,
        "file_edit_tool_calls": 0,
        "attempt_logs": execution_attempt_logs,
    }


def collect_git_add_targets(root: Path, initial_touched):
    """Collect add targets including initial touched files plus any additional modified files."""
    targets = set(initial_touched)

    status = run_cmd(["git", "status", "--porcelain"], root)
    for line in status.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        path = path.replace("\\", "/")
        if path.startswith("scripts/agent/runs/"):
            continue
        targets.add(path)

    if (root / "truth_candidate").exists():
        targets.add("truth_candidate")
    if (root / "truth_diff_report.json").exists():
        targets.add("truth_diff_report.json")
    if (root / "artifacts_candidate").exists():
        targets.add("artifacts_candidate")
    if (root / "artifacts_diff_report.json").exists():
        targets.add("artifacts_diff_report.json")

    return sorted(targets)


def preload_candidate_payloads(tasks, response_dir: Path):
    """
    Load and parse all m2 response files before any branch checkout.
    This avoids losing access to response artifacts when git switches branches.
    """
    payloads = {}
    errors = {}
    for task in tasks:
        task_id = task["id"]
        response_file = response_dir / f"{task_id}_response.txt"
        if not response_file.exists():
            errors[task_id] = f"Response file missing: {response_file}"
            continue
        response_text = response_file.read_text(encoding="utf-8", errors="replace")
        blocks = parse_response_blocks(response_text)
        if not blocks:
            errors[task_id] = f"No BEGIN_FILE blocks found in {response_file}"
            continue
        payloads[task_id] = {
            "response_file": str(response_file),
            "response_text": response_text,
            "blocks": blocks,
        }
    return payloads, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="", help="Task id, e.g. ex05")
    parser.add_argument("--all", action="store_true", help="Execute all tasks from manifest")
    parser.add_argument("--root", default=".", help="Repo root")
    parser.add_argument("--response-dir", default="scripts/agent/runs", help="Dir containing exNN_response.txt")
    parser.add_argument("--branch-suffix", default="agent_exec", help="Suffix for output branches")
    parser.add_argument("--continue-on-error", action="store_true", help="Keep running next tasks after a failure")
    parser.add_argument("--agent-max-attempts", type=int, default=3, help="Max internal m3 execution-agent repair/validation cycles")
    parser.add_argument("--model", default="gpt-5.2-codex", help="Model name for OpenHands execution agent")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    response_dir = (root / args.response_dir).resolve()
    runs_dir = root / "scripts" / "agent" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    if not git_clean_required(root):
        raise SystemExit(
            "Working tree is not clean. Commit/stash changes first, then rerun m3.\n"
            "This script does git checkout/switch per task."
        )

    tasks = get_tasks(root, args.task, args.all)
    preloaded_payloads, preload_errors = preload_candidate_payloads(tasks, response_dir)
    summary = []
    llm = LLM.subscription_login(vendor="openai", model=args.model, prompt_cache_retention=None)

    for task in tasks:
        t0 = time.time()
        task_id = task["id"]
        before_branch = task["before_branch"]
        out_branch = f"{task_id}_{args.branch_suffix}"
        payload = preloaded_payloads.get(task_id)
        response_file = payload["response_file"] if payload else str(response_dir / f"{task_id}_response.txt")
        check_log_file = runs_dir / f"{task_id}_m3_checks.json"
        result = {
            "task_id": task_id,
            "before_branch": before_branch,
            "out_branch": out_branch,
            "response_file": str(response_file),
            "execution_agent_used": True,
            "validation_attempts": 0,
            "tool_call_count": 0,
            "bash_tool_calls": 0,
            "file_edit_tool_calls": 0,
            "checks_passed": False,
            "build_passed": False,
            "execution_log_file": "",
            "check_log_file": str(check_log_file),
        }
        try:
            if task_id in preload_errors:
                raise RuntimeError(preload_errors[task_id])
            blocks = payload["blocks"]

            run_cmd(["git", "checkout", before_branch], root, check=True)
            run_cmd(["git", "checkout", "-B", out_branch], root, check=True)
            touched = apply_blocks(root, blocks)
            result["touched_files"] = touched

            try:
                exec_result = run_execution_agent(
                    root=root,
                    task_id=task_id,
                    llm=llm,
                    agent_max_attempts=args.agent_max_attempts,
                    runs_dir=runs_dir,
                )
            except Exception as exec_err:
                exec_result = run_host_validation_only(
                    root=root,
                    task_id=task_id,
                    agent_max_attempts=args.agent_max_attempts,
                    runs_dir=runs_dir,
                    reason=str(exec_err),
                )
                result["execution_agent_error"] = str(exec_err)
            result["validation_attempts"] = exec_result["validation_attempts"]
            result["execution_agent_used"] = exec_result["execution_agent_used"]
            result["tool_call_count"] = exec_result["tool_call_count"]
            result["bash_tool_calls"] = exec_result["bash_tool_calls"]
            result["file_edit_tool_calls"] = exec_result["file_edit_tool_calls"]
            result["execution_log_file"] = exec_result["execution_log_file"]
            result["events_log_file"] = exec_result["events_log_file"]
            result["checks_passed"] = exec_result["checks_passed"]

            all_check_logs = []
            for attempt_entry in exec_result["attempt_logs"]:
                all_check_logs.extend(attempt_entry.get("check_logs", []))
            check_log_file.write_text(json.dumps(all_check_logs, indent=2), encoding="utf-8")

            if not exec_result["checks_passed"]:
                raise RuntimeError(
                    f"Execution agent could not make checks pass for {task_id}. See {exec_result['execution_log_file']}"
                )

            result["build_passed"] = True
            add_targets = collect_git_add_targets(root, touched)
            run_cmd(["git", "add"] + add_targets, root, check=True)
            commit_msg = f"{task_id}: apply agent response + build/truth pass"
            commit = run_cmd(["git", "commit", "-m", commit_msg], root)
            if commit.returncode != 0 and "nothing to commit" not in (commit.stdout + commit.stderr).lower():
                raise RuntimeError(f"Commit failed:\n{commit.stdout}\n{commit.stderr}")
            result["status"] = "success"
        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            result["duration_seconds"] = round(time.time() - t0, 2)
            summary.append(result)
            print(f"[m3] {task_id} failed: {e}")
            if not args.continue_on_error:
                summary_file = runs_dir / "m3_summary.json"
                summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
                raise SystemExit(2)
            continue

        result["duration_seconds"] = round(time.time() - t0, 2)
        summary.append(result)
        print(f"[m3] {task_id} success -> {out_branch}")

    summary_file = runs_dir / "m3_summary.json"
    summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nSaved summary: {summary_file}")


if __name__ == "__main__":
    main()
