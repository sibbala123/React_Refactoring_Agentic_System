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
import logging
import time
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

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
    logger.info(f"{request.method} {request.url.path} → {response.status_code} ({duration_ms:.0f}ms)")
    return response

# ---------------------------------------------------------------------------
# In-memory job store
# ---------------------------------------------------------------------------

# job_id → { status, tasks, summary }
_jobs: dict[str, dict[str, Any]] = {}

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
# Stub data
# ---------------------------------------------------------------------------

STUB_SMELLS = [
    {
        "smell_id": "smell_stub_001",
        "smell_type": "Large Component",
        "component_name": "SpendCapSidePanel",
        "file_path": "apps/studio/components/ui/SpendCapSidePanel.tsx",
        "line_start": 1,
        "line_end": 704,
        "severity": "high",
        "confidence": 0.95,
        "detector_metadata": {"details": "Component has 704 lines"},
    },
    {
        "smell_id": "smell_stub_002",
        "smell_type": "Too Many Props",
        "component_name": "QueryPerformanceGrid",
        "file_path": "apps/studio/components/grid/QueryPerformanceGrid.tsx",
        "line_start": 1,
        "line_end": 312,
        "severity": "high",
        "confidence": 0.90,
        "detector_metadata": {"details": "Number of props: 27"},
    },
    {
        "smell_id": "smell_stub_003",
        "smell_type": "Large Component",
        "component_name": "FormPatternsSidePanel",
        "file_path": "apps/studio/components/ui/FormPatternsSidePanel.tsx",
        "line_start": 1,
        "line_end": 521,
        "severity": "high",
        "confidence": 0.92,
        "detector_metadata": {"details": "Component has 521 lines"},
    },
    {
        "smell_id": "smell_stub_004",
        "smell_type": "Direct DOM Manipulation",
        "component_name": "MarkdownEditor",
        "file_path": "apps/studio/components/editor/MarkdownEditor.tsx",
        "line_start": 44,
        "line_end": 89,
        "severity": "medium",
        "confidence": 0.85,
        "detector_metadata": {"details": "Uses document.getElementById"},
    },
    {
        "smell_id": "smell_stub_005",
        "smell_type": "Uncontrolled Component",
        "component_name": "ProjectConfigForm",
        "file_path": "apps/studio/components/settings/ProjectConfigForm.tsx",
        "line_start": 12,
        "line_end": 98,
        "severity": "medium",
        "confidence": 0.80,
        "detector_metadata": {"details": "Uncontrolled input: ref instead of state"},
    },
]

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
    STUB: returns hardcoded smells regardless of workspace path.
    Real implementation: E2-S1 (Soham).
    """
    logger.info(f"[scan] workspace={req.workspace}")

    # TODO (E2-S1): replace with real ReactSniffer subprocess call
    by_type: dict[str, int] = {}
    for s in STUB_SMELLS:
        by_type[s["smell_type"]] = by_type.get(s["smell_type"], 0) + 1

    return {
        "total": len(STUB_SMELLS),
        "scan_duration_s": 2.1,
        "by_type": by_type,
        "smells": STUB_SMELLS,
    }


@app.post("/fix")
async def fix(req: FixRequest):
    """
    Queue a list of smells for pipeline processing.
    STUB: creates a job entry and returns job_id immediately.
    Real implementation: E3-S1 (Soham).
    """
    if not req.smells:
        raise HTTPException(status_code=400, detail="smells list is empty")

    logger.info(f"[fix] workspace={req.workspace} smells={len(req.smells)}")

    job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    estimated_seconds = max(1, len(req.smells) // 3) * 25

    _jobs[job_id] = {
        "status": "queued",
        "total_tasks": len(req.smells),
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
            for s in req.smells
        ],
        "smells": req.smells,
        "workspace": req.workspace,
        "summary": None,
        "cancel_flag": False,
    }

    # TODO (E3-S1): kick off real pipeline workers here

    return {
        "job_id": job_id,
        "total_tasks": len(req.smells),
        "estimated_seconds": estimated_seconds,
    }


@app.get("/progress/{job_id}")
async def progress(job_id: str, request: Request):
    """
    SSE stream of pipeline progress events for a job.
    STUB: emits fake node_done + task_done events then run_complete.
    Real implementation: E3-S2 (Soham).
    """
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="job not found")

    async def event_generator() -> AsyncGenerator[dict, None]:
        job = _jobs[job_id]
        job["status"] = "running"

        # TODO (E3-S2): replace with real SSE events from pipeline workers
        for task in job["tasks"]:
            if await request.is_disconnected():
                break

            smell_id = task["smell_id"]
            component = task["component_name"]

            # Simulate node-level progress
            for node in ["classify", "plan", "edit", "verify", "critique", "finalize"]:
                await asyncio.sleep(0.3)
                yield {
                    "data": {
                        "type": "node_done",
                        "smell_id": smell_id,
                        "node": node,
                        "status": "done",
                    }
                }

            # Simulate task completion
            task["status"] = "accepted"
            task["tactic"] = "extract_component"
            task["critique_score"] = 0.82
            job["completed_tasks"] += 1

            yield {
                "data": {
                    "type": "task_done",
                    "smell_id": smell_id,
                    "component_name": component,
                    "file": task["file"],
                    "status": "accepted",
                    "tactic": "extract_component",
                    "retry_count": 0,
                    "critique_score": 0.82,
                    "skip_reason": None,
                    "error": None,
                }
            }

        # Final summary
        summary = {
            "accepted": job["completed_tasks"],
            "rejected": 0,
            "skipped": 0,
            "failed": 0,
            "total": job["total_tasks"],
            "total_cost_usd": round(job["total_tasks"] * 0.005, 4),
        }
        job["status"] = "complete"
        job["summary"] = summary

        yield {
            "data": {
                "type": "run_complete",
                "job_id": job_id,
                "summary": summary,
            }
        }

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
    """
    Cancel a running job.
    Real implementation: E3-S4 (Jayanth).
    """
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="job not found")

    job = _jobs[job_id]
    if job["status"] == "complete":
        raise HTTPException(status_code=409, detail="job already complete")

    completed = job["completed_tasks"]
    remaining = job["total_tasks"] - completed

    # TODO (E3-S4): set cancel_flag so workers stop picking up new tasks
    job["status"] = "cancelled"
    job["cancel_flag"] = True

    return {
        "cancelled": True,
        "job_id": job_id,
        "completed_before_cancel": completed,
        "remaining_cancelled": remaining,
    }


@app.post("/revert")
async def revert(req: RevertRequest):
    """
    Revert a file to its last git commit state.
    STUB: always returns success.
    Real implementation: E4-S3 (Soham).
    """
    logger.info(f"[revert] workspace={req.workspace} file={req.file}")

    # TODO (E4-S3): run  git checkout -- <file>  in req.workspace
    return {"success": True, "file": req.file}


@app.get("/original")
async def get_original(file: str, workspace: str):
    """
    Return original file content from git HEAD.
    STUB: returns placeholder content.
    Real implementation: E4-S3 (Soham).
    """
    logger.info(f"[original] workspace={workspace} file={file}")

    # TODO (E4-S3): run  git show HEAD:<file>  in workspace
    return {
        "content": f"// Original content of {file} would appear here (git HEAD)\n",
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
