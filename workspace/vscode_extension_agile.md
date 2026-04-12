# ReactRefactor VS Code Extension — Agile Planning Document

**Project:** ReactRefactor — Agentic Code Smell Refactoring Extension  
**Delivery Model:** Path A (Local VS Code Extension)  
**Team:** Jayanth, Soham, Ved  
**Sprint Duration:** 1 week  
**Total Sprints:** 4  
**Total Story Points:** 44

---

## Team Responsibilities

| Member | Track | Focus Area |
|---|---|---|
| **Soham** | Backend | FastAPI server, pipeline integration, concurrency, git operations |
| **Ved** | Frontend | VS Code extension UI, sidebar, progress views, TypeScript |
| **Jayanth** | Full-stack | API contract, integration glue, VS Code APIs, packaging, cost/estimate features |

---

## Architecture Summary

```
User's Machine
───────────────────────────────────────────────────────
  VS Code (TypeScript Extension)
    │  spawns on activate / kills on deactivate
    ▼
  FastAPI Server  (localhost:7432)
    │  /scan  →  ReactSniffer subprocess
    │  /fix   →  LangGraph pipeline (run_task)
    │  /progress/{job_id}  →  SSE stream
    │  /revert  →  git checkout
    ▼
  User's React Project (local disk)
    files read and written in-place
───────────────────────────────────────────────────────
```

---

## Sprint Plan Overview

```
Sprint 1 — Foundation
  Soham:   E1-S2, E2-S1
  Ved:     E1-S3, E2-S2
  Jayanth: E1-S1 (leads API contract, shared with all)

Sprint 2 — Core Features
  Soham:   E3-S1, E3-S2
  Ved:     E2-S3, E2-S4 (with Jayanth), E3-S3
  Jayanth: E2-S4, E3-S4

Sprint 3 — Results & Review
  Soham:   E4-S3
  Ved:     E4-S1, E4-S4
  Jayanth: E4-S2

Sprint 4 — Packaging & DX
  Soham:   E5-S2 (pip install side)
  Ved:     E4-S4 (finish), E5-S3
  Jayanth: E5-S1, E5-S2 (extension side), E5-S3
```

---

## Story Point Summary

| Epic | Backend (Soham) | Frontend (Ved) | Full-stack (Jayanth) | Total |
|---|---|---|---|---|
| E1 — Foundation | 2 | 2 | 2 | 6 |
| E2 — Smell Detection | 3 | 5 | 2 | 10 |
| E3 — Fix Execution | 8 | 3 | 2 | 13 |
| E4 — Results & Review | 2 | 3 | 2 | 7 |
| E5 — Packaging & DX | 1 | 2 | 5 | 8 |
| **Total** | **16** | **15** | **13** | **44** |

---

---

# EPIC 1 — Foundation

**Goal:** Prove the full communication loop (extension ↔ server) works end-to-end with stub data before building any real feature. This epic unblocks both backend and frontend tracks.

**Definition of Done:** Extension activates, spawns the Python server, calls `/health`, receives a response, and logs it to the Output Channel — all in one shot on a clean machine.

---

### E1-S1 — Define API Contract

**Assignee:** Jayanth  
**Story Points:** 2  
**Sprint:** 1  
**Track:** Both  
**Dependencies:** None  

**User Story:**  
As a development team, we want a documented API contract between the VS Code extension and the FastAPI server so that backend and frontend can develop independently without waiting on each other.

**Acceptance Criteria:**
- [ ] Markdown document `workspace/api_contract.md` defines all endpoints
- [ ] Endpoints covered: `GET /health`, `POST /scan`, `POST /fix`, `GET /progress/{job_id}`, `DELETE /jobs/{job_id}`, `POST /revert`
- [ ] Each endpoint has: method, path, request body schema, response body schema, error responses
- [ ] SSE event schema defined: `{ n, of, smell_id, file, status, tactic, node, retry_count, error }`
- [ ] Example JSON provided for every request and response
- [ ] Both Soham and Ved review and sign off before splitting into parallel tracks

**Notes:** This is a synchronous kick-off task. All three team members should review before Sprint 1 work splits.

---

### E1-S2 — FastAPI Server Scaffold

**Assignee:** Soham  
**Story Points:** 2  
**Sprint:** 1  
**Track:** Backend  
**Dependencies:** E1-S1  

**User Story:**  
As a frontend developer, I want a running FastAPI server with stub endpoints returning hardcoded responses so that I can integrate the extension against real HTTP immediately without waiting for real pipeline logic.

**Acceptance Criteria:**
- [ ] `server/app.py` created at project root
- [ ] Server starts with `python server/app.py` and listens on `localhost:7432`
- [ ] `GET /health` returns `{ "status": "ok", "version": "0.1.0" }`
- [ ] `POST /scan` accepts `{ "workspace": "..." }` and returns hardcoded smell list (3–5 fake smells)
- [ ] `POST /fix` accepts `{ "smells": [...], "workspace": "..." }` and returns `{ "job_id": "stub-job-1" }`
- [ ] `GET /progress/{job_id}` returns a short SSE stream with 3 fake events then closes
- [ ] `DELETE /jobs/{job_id}` returns `{ "cancelled": true }`
- [ ] `POST /revert` returns `{ "success": true }`
- [ ] All requests logged to console with method, path, timestamp
- [ ] `requirements.txt` updated with `fastapi`, `uvicorn`, `sse-starlette`

**Notes:** No real pipeline logic in this story — pure scaffolding. Real logic added in E2-S1, E3-S1.

---

### E1-S3 — VS Code Extension Scaffold

**Assignee:** Ved  
**Story Points:** 2  
**Sprint:** 1  
**Track:** Frontend  
**Dependencies:** E1-S1  

**User Story:**  
As a developer, I want a barebones VS Code extension that spawns the Python server on activation and proves the HTTP connection works so that we have the full communication loop verified before building real features.

**Acceptance Criteria:**
- [ ] `extension/` directory created with valid `package.json` (name: `react-refactor`, publisher: `react-refactor-team`)
- [ ] Extension activates when a workspace folder is open
- [ ] On activation: spawns `python server/app.py` as a child process
- [ ] On deactivation: kills the server process cleanly
- [ ] Calls `GET /health` after spawn and logs response to Output Channel named "ReactRefactor"
- [ ] If Python not found: shows VS Code error notification "Python 3.8+ is required to use ReactRefactor"
- [ ] If server fails to start within 5s: shows error "ReactRefactor server failed to start"
- [ ] Extension does not crash if workspace has no `package.json` (non-React project)
- [ ] `extension/src/extension.ts` contains `activate()` and `deactivate()` exports

**Notes:** TypeScript. Use `child_process.spawn`. Server path should be relative to extension install path so it works after packaging.

---

---

# EPIC 2 — Smell Detection

**Goal:** User can open any React project, click "Scan", and see a ranked, grouped list of code smells in the VS Code sidebar. They can check which ones to fix and see a time/cost estimate.

**Definition of Done:** Running `POST /scan` against a real React project returns real ReactSniffer output, and the sidebar renders it correctly with checkboxes and an estimate.

---

### E2-S1 — Scan Endpoint (Real ReactSniffer)

**Assignee:** Soham  
**Story Points:** 3  
**Sprint:** 1  
**Track:** Backend  
**Dependencies:** E1-S2  

**User Story:**  
As the VS Code extension, I want to POST a workspace path to `/scan` and receive a ranked list of real code smells detected by ReactSniffer so that the sidebar can display actionable issues.

**Acceptance Criteria:**
- [ ] `POST /scan { "workspace": "/path/to/repo" }` runs ReactSniffer via `subprocess` on the given path
- [ ] Uses the ReactSniffer binary already in `vendor/reactsniffer/`
- [ ] Response shape: `{ "smells": [...], "total": N, "by_type": { "Large Component": N, ... }, "scan_duration_s": N }`
- [ ] Each smell object: `{ smell_id, smell_type, component_name, file_path, line_start, line_end, severity, confidence, detector_metadata }`
- [ ] Smells sorted: high severity first, then medium, then low; alphabetical within same severity
- [ ] Returns `{ "smells": [], "total": 0 }` (not an error) when no smells found
- [ ] Returns HTTP 400 with `{ "error": "workspace does not exist" }` if path invalid
- [ ] Responds within 60s for a repo up to 10,000 TS/TSX files
- [ ] Replaces stub response from E1-S2

---

### E2-S2 — Smell Sidebar Tree View

**Assignee:** Ved  
**Story Points:** 3  
**Sprint:** 1  
**Track:** Frontend  
**Dependencies:** E1-S3  

**User Story:**  
As a developer, I want to see all detected code smells grouped by type in a VS Code sidebar panel so that I can understand the full scope of issues in my project at a glance.

**Acceptance Criteria:**
- [ ] Sidebar panel registered in Activity Bar with a custom icon
- [ ] Panel title: "ReactRefactor"
- [ ] "Scan Project" button at the top of the panel
- [ ] On click: calls `POST /scan` with `vscode.workspace.workspaceFolders[0].uri.fsPath`
- [ ] Tree structure: Smell Type (count) → File path → Component name (line range)
- [ ] Each tree node shows severity badge: 🔴 high / 🟡 medium / 🟢 low
- [ ] Loading spinner (tree placeholder "Scanning...") shown during scan
- [ ] Empty state message: "No smells detected. Your project looks clean!" when `total === 0`
- [ ] Error state: "Scan failed. Check Output Channel for details." on HTTP error
- [ ] Works against stub data from E1-S2 before E2-S1 is complete

---

### E2-S3 — Smell Selection with Checkboxes

**Assignee:** Ved  
**Story Points:** 2  
**Sprint:** 2  
**Track:** Frontend  
**Dependencies:** E2-S2  

**User Story:**  
As a developer, I want to check and uncheck individual smells (and select all by type) so that I have precise control over which code smells get fixed before I commit to running the pipeline.

**Acceptance Criteria:**
- [ ] Each smell leaf node in the tree has a checkbox
- [ ] Each smell type group node has a "select all / deselect all" toggle
- [ ] Checking a group header checks all its children; unchecking deselects all children
- [ ] Status bar shows: "ReactRefactor: 8 smells selected"
- [ ] "Fix Selected" button in panel toolbar — disabled when 0 smells selected
- [ ] Selection state preserved when tree is collapsed and re-expanded
- [ ] Select state resets when a new scan is run

---

### E2-S4 — Cost and Time Estimate Display

**Assignee:** Jayanth  
**Story Points:** 2  
**Sprint:** 2  
**Track:** Frontend  
**Dependencies:** E2-S3  

**User Story:**  
As a developer, I want to see an estimated processing time and API cost before I start a fix run so that I can make an informed decision about how many smells to fix at once.

**Acceptance Criteria:**
- [ ] Below the selection count in sidebar: "est. ~4 min · ~$0.05"
- [ ] Time estimate: `selected_count × 25s ÷ 3 workers` (rounded to nearest minute)
- [ ] Cost estimate: `selected_count × $0.005` (based on average pipeline token usage)
- [ ] Both values update live as user checks/unchecks smells
- [ ] Clicking "Fix Selected" shows a confirmation quick-pick: "Fix 8 smells? (~4 min, ~$0.05) [Cancel] [Confirm]"
- [ ] If 0 smells selected, estimate shows "Select smells to see estimate"

---

---

# EPIC 3 — Fix Execution

**Goal:** User clicks "Fix Selected", the pipeline runs on all selected smells with controlled concurrency, and the VS Code UI shows live per-node progress for each smell as it is processed.

**Definition of Done:** 3 smells run in parallel (different files), progress events stream live to the sidebar and Output Channel, and files on disk are updated by the time the run completes.

---

### E3-S1 — Fix Endpoint with Concurrency Control

**Assignee:** Soham  
**Story Points:** 5  
**Sprint:** 2  
**Track:** Backend  
**Dependencies:** E2-S1  

**User Story:**  
As the extension, I want to POST a list of smells to `/fix` and have the server run the LangGraph pipeline with a concurrency limit of 3 so that fixes complete in reasonable time without overloading OpenAI rate limits or causing file write conflicts.

**Acceptance Criteria:**
- [ ] `POST /fix { "smells": [...], "workspace": "..." }` returns `{ "job_id": "abc123" }` immediately (non-blocking)
- [ ] Pipeline tasks run with max 3 concurrent workers using `asyncio` + `ThreadPoolExecutor`
- [ ] Smells targeting the same file are serialized using a per-file `asyncio.Lock`
- [ ] Each task calls `runner.run_task()` with correct `manifest_task`, `smell`, `context` objects
- [ ] `context` gathered via `gather_context_for_smell()` (already in `utils/`)
- [ ] Job state stored in memory: `{ job_id, status, tasks: [{ smell_id, status, result }] }`
- [ ] `GET /jobs/{job_id}` returns full job state
- [ ] Replaces stub fix response from E1-S2
- [ ] Tested manually: run 5 smells from `experiments/metrics_run/smell_sample.json` against local Supabase clone

---

### E3-S2 — SSE Progress Stream

**Assignee:** Soham  
**Story Points:** 3  
**Sprint:** 2  
**Track:** Backend  
**Dependencies:** E3-S1  

**User Story:**  
As the VS Code extension, I want to receive live Server-Sent Events as each pipeline node completes so that the UI can show real-time progress without polling.

**Acceptance Criteria:**
- [ ] `GET /progress/{job_id}` returns `Content-Type: text/event-stream`
- [ ] Emits node-level event per task: `{ "type": "node_done", "smell_id": "...", "node": "classify", "status": "done" }`
- [ ] Emits task-complete event: `{ "type": "task_done", "smell_id": "...", "status": "accepted"|"rejected"|"skipped"|"failed", "tactic": "...", "retry_count": N, "file": "..." }`
- [ ] Emits final event when all tasks done: `{ "type": "run_complete", "summary": { "accepted": N, "rejected": N, "skipped": N, "failed": N, "total_cost_usd": N } }`
- [ ] Stream closes cleanly after `run_complete` event
- [ ] Client reconnecting to a finished job receives the `run_complete` event immediately
- [ ] Uses `sse-starlette` library

---

### E3-S3 — Live Progress UI

**Assignee:** Ved  
**Story Points:** 3  
**Sprint:** 2  
**Track:** Frontend  
**Dependencies:** E1-S3  

**User Story:**  
As a developer, I want to see live progress in the sidebar and Output Channel while the pipeline runs so that I know it's working and can monitor which smells are being processed.

**Acceptance Criteria:**
- [ ] On "Fix Selected" confirm: sidebar enters "running" mode
- [ ] Each selected smell shows animated spinner while being processed
- [ ] On `task_done` SSE event: spinner replaced with ✓ (accepted) / ✗ (rejected) / ↷ (skipped) / ⚠ (failed)
- [ ] VS Code status bar item shows: "ReactRefactor: Fixing 6 / 20..."
- [ ] Output Channel "ReactRefactor" logs each node event: `[SpendCapSidePanel] classify → done`
- [ ] Output Channel logs task result: `[SpendCapSidePanel] ACCEPTED — extract_component (retry 0)`
- [ ] "Cancel" button appears in panel toolbar during run — calls `DELETE /jobs/{job_id}`
- [ ] On `run_complete`: status bar clears, notification shown (see E4-S1)
- [ ] SSE consumer is non-blocking — VS Code UI stays responsive during run
- [ ] Works against stub SSE stream from E1-S2 before E3-S2 is complete

---

### E3-S4 — Cancel Running Job

**Assignee:** Jayanth  
**Story Points:** 2  
**Sprint:** 2  
**Track:** Backend  
**Dependencies:** E3-S1  

**User Story:**  
As a developer, I want to cancel a running fix job so that I can stop the pipeline mid-run if I change my mind, without corrupting any files already being edited.

**Acceptance Criteria:**
- [ ] `DELETE /jobs/{job_id}` sets a cancellation flag on the job
- [ ] Any currently-running task is allowed to complete before stopping (no mid-edit kill)
- [ ] Next pending task is not started after cancellation flag is set
- [ ] SSE stream emits: `{ "type": "cancelled", "completed": N, "cancelled": M }` then closes
- [ ] Files already edited by completed tasks remain edited on disk
- [ ] `GET /jobs/{job_id}` reflects `"status": "cancelled"` after cancellation
- [ ] Returns HTTP 404 if job ID not found
- [ ] Returns HTTP 409 if job is already complete

---

---

# EPIC 4 — Results & Review

**Goal:** After a run, the user sees a clear summary, can open a diff view for each accepted fix, and can revert individual changes they don't want to keep.

**Definition of Done:** User can complete a full fix run, inspect every change via VS Code's built-in diff editor, and revert any individual smell back to its original state with one click.

---

### E4-S1 — Run Summary Notification and Panel

**Assignee:** Ved  
**Story Points:** 2  
**Sprint:** 3  
**Track:** Frontend  
**Dependencies:** E3-S3  

**User Story:**  
As a developer, I want to see a clear summary when a fix run completes so that I immediately understand how many smells were fixed, rejected, or skipped without reading the full log.

**Acceptance Criteria:**
- [ ] On `run_complete` SSE event: VS Code information notification shown: "ReactRefactor: 14 accepted · 2 rejected · 1 skipped · 1 failed"
- [ ] Notification has two actions: [View Report] [Dismiss]
- [ ] [View Report] opens a VS Code Webview panel
- [ ] Webview renders a table: # | Smell Type | Component | File | Status | Tactic | Retries
- [ ] Rejected/failed rows show reason in a tooltip or expanded row
- [ ] Webview has "Revert All Accepted" button (calls revert for each accepted smell)
- [ ] Sidebar smell icons all updated to final status after run

---

### E4-S2 — Inline Diff View per Smell

**Assignee:** Jayanth  
**Story Points:** 2  
**Sprint:** 3  
**Track:** Frontend  
**Dependencies:** E4-S1  

**User Story:**  
As a developer, I want to click an accepted smell in the sidebar and immediately see a side-by-side diff of what the pipeline changed so that I can review the refactor before deciding whether to keep it.

**Acceptance Criteria:**
- [ ] Clicking an accepted smell node in the sidebar opens VS Code's built-in diff editor
- [ ] Left panel: original file content (retrieved via `git show HEAD:<file>`)
- [ ] Right panel: current file on disk (post-refactor)
- [ ] Diff editor title: "SpendCapSidePanel.tsx — ReactRefactor diff"
- [ ] Uses `vscode.commands.executeCommand('vscode.diff', originalUri, modifiedUri, title)`
- [ ] Original content served via `GET /original?file=<path>&workspace=<workspace>` endpoint (Jayanth adds this to server)
- [ ] If file has no git history: left panel shows a message "Original not available (file not tracked by git)"
- [ ] Clicking a rejected/skipped/failed smell shows a message in Output Channel instead of diff

---

### E4-S3 — Revert Endpoint

**Assignee:** Soham  
**Story Points:** 2  
**Sprint:** 3  
**Track:** Backend  
**Dependencies:** E3-S1  

**User Story:**  
As the VS Code extension, I want to call a revert endpoint for a specific file so that the user can undo a pipeline edit without manually running git commands.

**Acceptance Criteria:**
- [ ] `POST /revert { "file": "src/SpendCapSidePanel.tsx", "workspace": "/path/to/repo" }` runs `git checkout -- <file>` on that file
- [ ] Returns `{ "success": true, "file": "src/SpendCapSidePanel.tsx" }` on success
- [ ] Returns `{ "success": false, "error": "file not tracked by git" }` if not in a git repo
- [ ] Returns `{ "success": false, "error": "file not found" }` if path doesn't exist
- [ ] `GET /original?file=<path>&workspace=<workspace>` returns original file content from `git show HEAD:<file>`
- [ ] Both endpoints work on Windows and macOS/Linux (handle path separators)
- [ ] Tested manually: edit a file, call revert, confirm file is back to original

---

### E4-S4 — Revert UI

**Assignee:** Ved  
**Story Points:** 1  
**Sprint:** 3  
**Track:** Frontend  
**Dependencies:** E4-S2, E4-S3  

**User Story:**  
As a developer, I want a revert button on each accepted smell in the sidebar so that I can undo individual fixes I don't agree with in one click.

**Acceptance Criteria:**
- [ ] "↩ Revert" inline action button visible on hover for each accepted smell in sidebar
- [ ] Clicking calls `POST /revert` with that smell's file path and workspace
- [ ] On success: smell icon changes to "↩ reverted", tooltip shows "Reverted"
- [ ] On failure: VS Code error notification shown with error message from server
- [ ] "Revert All" button in the Webview summary panel (E4-S1) — calls revert for all accepted smells sequentially
- [ ] Already-reverted smells cannot be reverted again (button disabled)

---

---

# EPIC 5 — Packaging & Developer Experience

**Goal:** The extension installs cleanly on a machine that has never run the pipeline before, detects Python automatically, installs dependencies without manual steps, and ships as a single `.vsix` file.

**Definition of Done:** A teammate with Python 3.10 and Node.js installed can install the `.vsix`, open a React project, and complete a full scan + fix run without reading any setup documentation.

---

### E5-S1 — Python Environment Detection

**Assignee:** Jayanth  
**Story Points:** 3  
**Sprint:** 4  
**Track:** Frontend  
**Dependencies:** E1-S3  

**User Story:**  
As a developer installing the extension for the first time, I want it to automatically find my Python installation so that I don't need to configure anything manually before using it.

**Acceptance Criteria:**
- [ ] On activation: check for Python via `ms-python.python` VS Code extension API first
- [ ] Fallback: try `python3`, then `python` on system PATH
- [ ] Log detected Python path and version to Output Channel: "Using Python 3.11.2 at /usr/bin/python3"
- [ ] If Python < 3.8: show error "ReactRefactor requires Python 3.8 or higher. Found: 3.7.x"
- [ ] If no Python found: show error notification with button [Select Python Interpreter] that opens VS Code's interpreter picker
- [ ] Detected path stored in extension workspace state for subsequent activations
- [ ] Works on Windows (python.exe), macOS (/usr/bin/python3), Linux
- [ ] Server spawned using the detected Python path (not hardcoded `python`)

---

### E5-S2 — Automatic Dependency Installation

**Assignee:** Jayanth  
**Story Points:** 3  
**Sprint:** 4  
**Track:** Full-stack  
**Dependencies:** E5-S1  

**User Story:**  
As a developer installing the extension for the first time, I want Python dependencies installed automatically on first activation so that I don't need to manually run `pip install` before using the extension.

**Acceptance Criteria:**
- [ ] On first activation (no `.deps_installed` marker file): run `pip install -r requirements.txt` using detected Python
- [ ] Progress shown in Output Channel: "ReactRefactor: Installing dependencies (first run)..."
- [ ] VS Code status bar shows "ReactRefactor: Setting up..." during install
- [ ] On success: write `.deps_installed` marker, show "ReactRefactor: Ready"
- [ ] On failure: show error notification with manual install command: "Run: pip install -r requirements.txt"
- [ ] On subsequent activations: skip install check (marker file present)
- [ ] `requirements.txt` includes: `fastapi`, `uvicorn`, `sse-starlette`, `openai`, `langgraph`, `python-dotenv`
- [ ] Server only spawned after dependencies confirmed installed

---

### E5-S3 — Extension Packaging as VSIX

**Assignee:** Jayanth  
**Story Points:** 2  
**Sprint:** 4  
**Track:** Frontend  
**Dependencies:** All epics complete  

**User Story:**  
As a team member, I want to install the extension from a `.vsix` file so that I can share and test the full extension without publishing to the VS Code Marketplace.

**Acceptance Criteria:**
- [ ] `vsce package` runs without errors and produces `react-refactor-0.1.0.vsix`
- [ ] `.vsix` installs via VS Code "Install from VSIX" without errors
- [ ] Python `server/` directory bundled inside `.vsix` under `server/`
- [ ] `vendor/reactsniffer/` bundled inside `.vsix` under `vendor/`
- [ ] `requirements.txt` bundled at extension root
- [ ] `.vscodeignore` excludes: `node_modules/`, `runs/`, `data/`, `experiments/`, `*.pyc`, `__pycache__/`
- [ ] `extension/package.json` has: correct `name`, `displayName`, `publisher`, `version`, `engines.vscode`
- [ ] Extension activates correctly after install from `.vsix` on Windows and macOS
- [ ] `extension/README.md` covers: prerequisites (Python 3.8+, Node.js), install steps, usage walkthrough

---

---

## Dependency Graph

```
E1-S1 (API Contract)
   ├──► E1-S2 (Server Scaffold) ──► E2-S1 (Scan Real) ──► E3-S1 (Fix + Concurrency)
   │                                                              ├──► E3-S2 (SSE)
   │                                                              └──► E3-S4 (Cancel)
   │
   └──► E1-S3 (Extension Scaffold) ──► E2-S2 (Sidebar) ──► E2-S3 (Selection)
                                                               └──► E2-S4 (Estimate)
                                    ──► E3-S3 (Progress UI)
                                    ──► E5-S1 (Python Detect) ──► E5-S2 (Deps Install)

E3-S1 + E3-S2 + E3-S3 ──► E4-S1 (Summary)
                        ──► E4-S2 (Diff View) ──► E4-S4 (Revert UI)
                        ──► E4-S3 (Revert Endpoint)

All Epics ──► E5-S3 (Packaging)
```

---

## Definition of Ready (before a story can be started)

- User story written with acceptance criteria
- Dependencies completed or have stub replacements
- Assignee has access to the repo and correct branch
- API contract signed off (for stories touching HTTP)

## Definition of Done (before a story can be marked complete)

- All acceptance criteria checked off
- Code reviewed by at least one other team member
- No new `console.error` / unhandled exceptions introduced
- Story tested against local Supabase clone (for backend) or real workspace (for frontend)
- PR merged to `langgraph-pipeline` branch
