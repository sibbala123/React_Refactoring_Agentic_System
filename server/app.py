"""
ReactRefactor — FastAPI Server
Serves the VS Code extension with smell detection and pipeline execution.

Usage:
    python server/app.py
    python server/app.py --port 7432
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

# ---------------------------------------------------------------------------
# Path bootstrap — detect_smells (scripts/) + pipeline (agentic_refactor_system/)
# ---------------------------------------------------------------------------

_SERVER_DIR        = Path(__file__).resolve().parent
_PROJECT_ROOT      = _SERVER_DIR.parent           # .../7000 project
_SCRIPTS_DIR       = _PROJECT_ROOT / "agentic_refactor_system" / "scripts"
_REACTSNIFFER_ROOT = _PROJECT_ROOT / "vendor" / "reactsniffer"

# _SCRIPTS_DIR → exposes detect_smells as a standalone importable module
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# _PROJECT_ROOT → exposes agentic_refactor_system as a proper package so that
# its internal relative imports (e.g. ...utils) resolve correctly
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from detect_smells import detect_smells as _run_detect_smells  # noqa: E402
from agentic_refactor_system.langgraph_pipeline.runner import run_task as _run_pipeline_task  # noqa: E402
from agentic_refactor_system.langgraph_pipeline.ingestion.gather_context import gather_context_for_smell as _gather_context_for_smell  # noqa: E402
from agentic_refactor_system.utils.manifest_utils import stable_task_id as _stable_task_id  # noqa: E402

# Severity lookup by smell type (detect_smells hardcodes "medium" for everything)
_SEVERITY_BY_TYPE: dict[str, str] = {
    "Large Component": "high",
    "Too Many Props": "high",
    "Direct DOM Manipulation": "medium",
    "Force Update": "medium",
    "JSX Outside the Render Method": "medium",
    "Inheritance Instead of Composition": "medium",
    "Props in Initial State": "low",
    "Uncontrolled Component": "low",
}


def _apply_severity(smells: list[dict[str, Any]]) -> None:
    for smell in smells:
        smell["severity"] = _SEVERITY_BY_TYPE.get(smell.get("smell_type", ""), "medium")


# Patterns to locate a component definition by name in JS/TS source
_COMPONENT_DEF_PATTERNS = [
    re.compile(r'(?:export\s+default\s+|export\s+)?function\s+{name}\s*[(<]'),
    re.compile(r'(?:export\s+default\s+|export\s+)?(?:const|let|var)\s+{name}\s*='),
    re.compile(r'(?:export\s+default\s+|export\s+)?class\s+{name}\b'),
]


def _find_component_range(file_path: Path, component_name: str) -> tuple[int, int] | None:
    """
    Search for a component definition in a JS/TS file by name.
    Returns (line_start, line_end) 1-indexed, or None if not found.
    line_end is found by counting braces from the definition start.
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    lines = text.splitlines()

    for template in _COMPONENT_DEF_PATTERNS:
        pattern = re.compile(
            template.pattern.replace("{name}", re.escape(component_name)),
            re.MULTILINE,
        )
        match = pattern.search(text)
        if not match:
            continue

        line_start = text[: match.start()].count("\n") + 1

        # Walk forward from line_start counting braces to find closing line
        brace_depth = 0
        found_open = False
        line_end = line_start

        for i, line in enumerate(lines[line_start - 1:], start=line_start):
            for ch in line:
                if ch == "{":
                    brace_depth += 1
                    found_open = True
                elif ch == "}":
                    brace_depth -= 1
            if found_open and brace_depth == 0:
                line_end = i
                break

        return line_start, line_end

    return None


def _enrich_smell_lines(smells: list[dict[str, Any]], workspace: Path) -> None:
    """
    Replace imprecise line ranges from ReactSniffer (always L1-N) with the
    actual component definition range found by searching the source file.
    Smells that already have precise line info (e.g. Uncontrolled Component)
    are left untouched.
    """
    imprecise_types = {"Large Component", "Too Many Props", "Inheritance Instead of Composition"}

    for smell in smells:
        if smell.get("smell_type") not in imprecise_types:
            continue
        component_name = smell.get("component_name")
        if not component_name:
            continue

        file_path = workspace / smell["file_path"]
        result = _find_component_range(file_path, component_name)
        if result:
            smell["line_start"], smell["line_end"] = result

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("reactrefactor")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="ReactRefactor Server", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration_ms = (time.time() - start) * 1000
    logger.info(f"{request.method} {request.url.path} -> {response.status_code} ({duration_ms:.0f}ms)")
    return response

# ---------------------------------------------------------------------------
# In-memory job store + concurrency helpers
# ---------------------------------------------------------------------------

# job_id → { status, tasks, summary, ... }
_jobs: dict[str, dict[str, Any]] = {}

# job_id → asyncio.Queue of SSE event dicts (consumed by /progress in E3-S2)
_job_events: dict[str, asyncio.Queue] = {}

# relative file_path → asyncio.Lock  (prevents concurrent edits to same file)
_file_locks: dict[str, asyncio.Lock] = {}

_MAX_PIPELINE_WORKERS = 3


def _to_relative_path(file_path: str, workspace: Path) -> str:
    """Convert an absolute file path to a path relative to workspace."""
    try:
        return Path(file_path).relative_to(workspace).as_posix()
    except ValueError:
        return file_path.replace("\\", "/")


def _build_manifest_task(
    smell: dict[str, Any],
    workspace: Path,
    repo_name: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    task_id = _stable_task_id(repo_name, smell)
    allowed_files = [smell["file_path"], *context.get("local_imports", [])]
    allowed_files = sorted(dict.fromkeys(f for f in allowed_files if f))
    return {
        "id": task_id,
        "repo_name": repo_name,
        "target_root": str(workspace),
        "smell_id": smell["smell_id"],
        "smell_type": smell["smell_type"],
        "target_file": smell["file_path"],
        "symbol_name": smell.get("component_name"),
        "line_start": smell.get("line_start", 1),
        "line_end": smell.get("line_end", smell.get("line_start", 1)),
        "allowed_edit_scope": {
            "mode": "bounded_file_and_local_imports",
            "allowed_files": allowed_files,
        },
        "relevant_context_files": context.get("relevant_context_files", [smell["file_path"]]),
        "build_command": "",
        "validation_commands": [],
        "task_prompt_file": f"tasks/{task_id}/prompt.txt",
        "metadata": {
            "confidence": smell.get("confidence"),
            "severity": smell.get("severity"),
            "detector_metadata": smell.get("detector_metadata", {}),
        },
    }


async def _run_fix_job(job_id: str) -> None:
    """Background coroutine: runs all tasks for a job with max 3 concurrent workers."""
    job = _jobs[job_id]
    job["status"] = "running"
    workspace = Path(job["workspace"])
    repo_name = workspace.name
    event_queue: asyncio.Queue = _job_events[job_id]

    semaphore = asyncio.Semaphore(_MAX_PIPELINE_WORKERS)
    loop = asyncio.get_running_loop()

    async def _run_one(task_entry: dict[str, Any], smell: dict[str, Any]) -> None:
        async with semaphore:
            file_key = smell.get("file_path", "")
            if file_key not in _file_locks:
                _file_locks[file_key] = asyncio.Lock()

            task_entry["status"] = "running"
            logger.info(f"[job:{job_id}] starting task smell_id={smell['smell_id']}")

            def _node_done_cb(node_name: str, _: dict) -> None:
                loop.call_soon_threadsafe(event_queue.put_nowait, {
                    "type": "node_done",
                    "smell_id": smell["smell_id"],
                    "node": node_name,
                    "status": "done",
                })

            try:
                context = await asyncio.to_thread(
                    _gather_context_for_smell,
                    smell=smell,
                    target_root=workspace,
                    repo_name=repo_name,
                )
                manifest_task = _build_manifest_task(smell, workspace, repo_name, context)

                async with _file_locks[file_key]:
                    final_state = await asyncio.to_thread(
                        _run_pipeline_task,
                        manifest_task,
                        smell,
                        context,
                        show_progress=False,
                        on_node_done=_node_done_cb,
                    )

                status = final_state.get("status", "failed")
                plan   = final_state.get("plan") or {}
                task_entry["status"]         = status
                task_entry["tactic"]         = plan.get("tactic")
                task_entry["retry_count"]    = final_state.get("retry_count", 0)
                task_entry["critique_score"] = final_state.get("critique_score")
                raw_error = (
                    final_state.get("error")
                    or final_state.get("last_error")
                    or final_state.get("error_message")
                )
                if raw_error:
                    # Extract last non-empty line (the actual exception message)
                    lines = [l.strip() for l in str(raw_error).splitlines() if l.strip()]
                    task_entry["error"] = lines[-1] if lines else str(raw_error)
                else:
                    task_entry["error"] = None

            except Exception as exc:
                logger.error(f"[job:{job_id}] task failed: {exc}")
                task_entry["status"] = "failed"
                task_entry["error"]  = str(exc)

            job["completed_tasks"] += 1
            await event_queue.put({
                "type":           "task_done",
                "smell_id":       smell["smell_id"],
                "component_name": smell.get("component_name"),
                "file":           smell.get("file_path"),
                "status":         task_entry["status"],
                "tactic":         task_entry.get("tactic"),
                "retry_count":    task_entry.get("retry_count", 0),
                "critique_score": task_entry.get("critique_score"),
                "error":          task_entry.get("error"),
            })

    try:
        await asyncio.gather(*[
            _run_one(task_entry, smell)
            for task_entry, smell in zip(job["tasks"], job["smells"])
        ])
        statuses = [t["status"] for t in job["tasks"]]
        summary = {
            "accepted":  statuses.count("accepted"),
            "rejected":  statuses.count("rejected"),
            "skipped":   statuses.count("skipped"),
            "failed":    statuses.count("failed"),
            "cancelled": 0,
            "total":     job["total_tasks"],
        }
        job["status"]  = "complete"
        job["summary"] = summary
        await event_queue.put({"type": "run_complete", "job_id": job_id, "summary": summary})

    except asyncio.CancelledError:
        completed = job["completed_tasks"]
        job["status"] = "cancelled"
        job["summary"] = {"completed": completed, "total": job["total_tasks"]}
        await event_queue.put({
            "type":      "cancelled",
            "job_id":    job_id,
            "completed": completed,
            "total":     job["total_tasks"],
        })

    finally:
        await event_queue.put(None)  # sentinel — tells SSE stream to close

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ScanRequest(BaseModel):
    workspace: str

class FixRequest(BaseModel):
    workspace: str
    smells: list[dict[str, Any]]

class RevertRequest(BaseModel):
    workspace: str
    file: str

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Health check — called by VS Code extension on startup."""
    return {"status": "ok", "version": "0.1.0"}


@app.post("/scan")
async def scan(req: ScanRequest):
    """
    Run ReactSniffer on the workspace and return detected smells.
    Uses the agentic_refactor_system detect_smells pipeline.
    Falls back to heuristic detection if ReactSniffer is not available.
    """
    workspace = Path(req.workspace)
    if not workspace.exists() or not workspace.is_dir():
        raise HTTPException(status_code=422, detail=f"Workspace path not found: {req.workspace}")

    logger.info(f"[scan] workspace={req.workspace}")
    t0 = time.time()

    reactsniffer_root = str(_REACTSNIFFER_ROOT) if _REACTSNIFFER_ROOT.exists() else ""
    if reactsniffer_root:
        logger.info(f"[scan] ReactSniffer found at {reactsniffer_root}")
    else:
        logger.info("[scan] ReactSniffer not found — using heuristic fallback")

    tmp_dir = Path(tempfile.mkdtemp(prefix="reactrefactor_scan_"))
    try:
        report = await asyncio.to_thread(
            _run_detect_smells,
            target_root=workspace,
            output_root=tmp_dir,
            repo_name=workspace.name,
            reactsniffer_root=reactsniffer_root,
        )
    except Exception as exc:
        logger.error(f"[scan] Detection failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Scan failed: {exc}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    smells: list[dict[str, Any]] = report.get("smells", [])
    _apply_severity(smells)
    _enrich_smell_lines(smells, workspace)

    by_type: dict[str, int] = {}
    for s in smells:
        by_type[s["smell_type"]] = by_type.get(s["smell_type"], 0) + 1

    return {
        "total": len(smells),
        "scan_duration_s": round(time.time() - t0, 2),
        "by_type": by_type,
        "smells": smells,
    }


@app.post("/fix")
async def fix(req: FixRequest):
    """
    Queue a list of smells for pipeline processing.
    Returns job_id immediately; pipeline runs in background with max 3 concurrent workers.
    """
    if not req.smells:
        raise HTTPException(status_code=400, detail="smells list is empty")

    workspace = Path(req.workspace)
    if not workspace.exists() or not workspace.is_dir():
        raise HTTPException(status_code=422, detail=f"Workspace path not found: {req.workspace}")

    logger.info(f"[fix] workspace={req.workspace} smells={len(req.smells)}")

    # Normalise file_path to relative (extension sends absolute paths)
    smells = [
        {**s, "file_path": _to_relative_path(s.get("file_path", ""), workspace)}
        for s in req.smells
    ]

    job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    estimated_seconds = max(1, math.ceil(len(smells) / _MAX_PIPELINE_WORKERS)) * 25

    _jobs[job_id] = {
        "status": "queued",
        "total_tasks": len(smells),
        "completed_tasks": 0,
        "tasks": [
            {
                "smell_id": s["smell_id"],
                "component_name": s.get("component_name", "unknown"),
                "file": s.get("file_path", ""),
                "status": "queued",
                "tactic": None,
                "retry_count": 0,
                "critique_score": None,
            }
            for s in smells
        ],
        "smells": smells,
        "workspace": req.workspace,
        "summary": None,
        "task": None,
    }
    _job_events[job_id] = asyncio.Queue()

    task = asyncio.create_task(_run_fix_job(job_id))
    _jobs[job_id]["task"] = task

    return {
        "job_id": job_id,
        "total_tasks": len(smells),
        "estimated_seconds": estimated_seconds,
    }


@app.get("/progress/{job_id}")
async def progress(job_id: str, request: Request):
    """
    SSE stream of real pipeline progress events for a job.
    Emits node_done events (one per LangGraph node per task) and task_done /
    run_complete events pushed by _run_fix_job into the per-job asyncio.Queue.

    Reconnect behaviour: if the job is already complete when the client
    connects, immediately emit a run_complete event and close.
    """
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="job not found")

    async def event_generator() -> AsyncGenerator[dict, None]:
        job = _jobs[job_id]

        # Reconnect: job already finished — replay terminal event and close.
        if job["status"] == "complete":
            yield {"data": json.dumps({"type": "run_complete", "job_id": job_id, "summary": job.get("summary", {})})}
            return
        if job["status"] == "cancelled":
            yield {"data": json.dumps({
                "type":      "cancelled",
                "job_id":    job_id,
                "completed": job["completed_tasks"],
                "total":     job["total_tasks"],
            })}
            return

        queue: asyncio.Queue = _job_events[job_id]

        while True:
            if await request.is_disconnected():
                logger.info(f"[progress:{job_id}] client disconnected")
                break

            try:
                # Wait up to 15 s so we can re-check disconnect regularly
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                # Send a heartbeat so proxies don't close the connection
                yield {"data": json.dumps({"type": "ping"})}
                continue

            if event is None:
                # Sentinel pushed by _run_fix_job after run_complete
                break

            yield {"data": json.dumps(event)}

    return EventSourceResponse(event_generator())


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """Return current state of a job."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="job not found")

    job = _jobs[job_id]
    return {
        "job_id": job_id,
        "status": job["status"],
        "total_tasks": job["total_tasks"],
        "completed_tasks": job["completed_tasks"],
        "tasks": job["tasks"],
    }


@app.delete("/jobs/{job_id}")
async def cancel_job(job_id: str):
    """Cancel a running job by cancelling its asyncio task immediately."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="job not found")

    job = _jobs[job_id]
    if job["status"] in ("complete", "cancelled"):
        raise HTTPException(status_code=409, detail=f"job already {job['status']}")

    task: asyncio.Task | None = job.get("task")
    if task and not task.done():
        task.cancel()

    return {
        "cancelled": True,
        "job_id": job_id,
        "completed_before_cancel": job["completed_tasks"],
    }


@app.post("/revert")
async def revert(req: RevertRequest):
    """Revert a file to its last git commit state via git checkout -- <file>."""
    workspace = Path(req.workspace)
    if not workspace.exists():
        raise HTTPException(status_code=422, detail=f"Workspace not found: {req.workspace}")

    logger.info(f"[revert] workspace={req.workspace} file={req.file}")

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "checkout", "--", req.file],
            cwd=str(workspace),
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="git not found on PATH")

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=result.stderr.strip() or f"git checkout failed (exit {result.returncode})",
        )

    return {"success": True, "file": req.file}


@app.get("/original")
async def get_original(file: str, workspace: str):
    """Return original file content from git HEAD via git show HEAD:<file>."""
    ws = Path(workspace)
    if not ws.exists():
        raise HTTPException(status_code=422, detail=f"Workspace not found: {workspace}")

    logger.info(f"[original] workspace={workspace} file={file}")

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "show", f"HEAD:{file}"],
            cwd=str(ws),
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="git not found on PATH")

    if result.returncode != 0:
        err = result.stderr.strip()
        if "does not exist" in err or "exists on disk" in err or "pathspec" in err:
            raise HTTPException(status_code=404, detail=f"File not tracked by git: {file}")
        raise HTTPException(status_code=500, detail=err or f"git show failed (exit {result.returncode})")

    return {
        "content": result.stdout,
        "file": file,
        "commit": "HEAD",
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ReactRefactor FastAPI server")
    parser.add_argument("--port", type=int, default=7432, help="Port to listen on")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    logger.info(f"Starting ReactRefactor server on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
