# ReactRefactor — API Contract

**Version:** 0.1.0  
**Server:** `http://localhost:7432`  
**Protocol:** HTTP/1.1 + Server-Sent Events (SSE)  
**Auth:** None (local only)

This document is the source of truth between the VS Code extension (frontend) and the FastAPI server (backend). Both tracks must agree on this before splitting work.

---

## Base URL

```
http://localhost:7432
```

All endpoints are prefixed with `/`. No versioning prefix for v0.1.

---

## Endpoints

### 1. `GET /health`

Check that the server is running.

**Request:** No body.

**Response `200`:**
```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

**Used by:** Extension on activation to confirm server is ready before showing UI.

---

### 2. `POST /scan`

Run ReactSniffer on the given workspace and return a ranked list of detected code smells.

**Request body:**
```json
{
  "workspace": "/absolute/path/to/react/project"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `workspace` | string | yes | Absolute path to the root of the React project on disk |

**Response `200`:**
```json
{
  "total": 24,
  "scan_duration_s": 12.4,
  "by_type": {
    "Large Component": 14,
    "Too Many Props": 8,
    "Direct DOM Manipulation": 2
  },
  "smells": [
    {
      "smell_id": "smell_a1b2c3d4",
      "smell_type": "Large Component",
      "component_name": "SpendCapSidePanel",
      "file_path": "apps/studio/components/ui/SpendCapSidePanel.tsx",
      "line_start": 1,
      "line_end": 704,
      "severity": "high",
      "confidence": 0.95,
      "detector_metadata": {
        "details": "Component has 704 lines"
      }
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `total` | int | Total number of smells found |
| `scan_duration_s` | float | How long the scan took in seconds |
| `by_type` | object | Count of smells per smell type |
| `smells` | array | Full list of smell objects, sorted by severity (high → medium → low) |

**Smell object fields:**

| Field | Type | Description |
|---|---|---|
| `smell_id` | string | Unique identifier for this smell |
| `smell_type` | string | One of: `Large Component`, `Too Many Props`, `Direct DOM Manipulation`, `Inheritance Instead of Composition`, `Uncontrolled Component`, `Force Update` |
| `component_name` | string | Name of the React component |
| `file_path` | string | Relative path from workspace root |
| `line_start` | int | Start line of the component |
| `line_end` | int | End line of the component |
| `severity` | string | One of: `high`, `medium`, `low` |
| `confidence` | float | 0.0–1.0 confidence score from detector |
| `detector_metadata` | object | Raw details from ReactSniffer (varies by smell type) |

**Response `400`:**
```json
{
  "error": "workspace does not exist",
  "detail": "/path/that/doesnt/exist"
}
```

**Response `200` (no smells found):**
```json
{
  "total": 0,
  "scan_duration_s": 4.1,
  "by_type": {},
  "smells": []
}
```

---

### 3. `POST /fix`

Submit a list of smells to fix. Returns a job ID immediately. Pipeline runs in the background.

**Request body:**
```json
{
  "workspace": "/absolute/path/to/react/project",
  "smells": [
    {
      "smell_id": "smell_a1b2c3d4",
      "smell_type": "Large Component",
      "component_name": "SpendCapSidePanel",
      "file_path": "apps/studio/components/ui/SpendCapSidePanel.tsx",
      "line_start": 1,
      "line_end": 704,
      "severity": "high",
      "confidence": 0.95,
      "detector_metadata": {
        "details": "Component has 704 lines"
      }
    }
  ]
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `workspace` | string | yes | Absolute path to the React project root |
| `smells` | array | yes | List of smell objects to fix (same shape as returned by `/scan`) |

**Response `200`:**
```json
{
  "job_id": "job_20260412_143022_abc123",
  "total_tasks": 8,
  "estimated_seconds": 67
}
```

| Field | Type | Description |
|---|---|---|
| `job_id` | string | Unique job identifier — use this for `/progress` and `/jobs` |
| `total_tasks` | int | Number of smells queued |
| `estimated_seconds` | int | Rough estimate: `ceil(total_tasks / 3) * 25` |

**Response `400`:**
```json
{
  "error": "smells list is empty"
}
```

---

### 4. `GET /progress/{job_id}` — SSE Stream

Stream live progress events for a running job. Uses Server-Sent Events.

**Request:** No body. Set `Accept: text/event-stream`.

**Connection:** Stays open until job completes or is cancelled. Extension must consume this as an EventSource.

---

#### SSE Event Types

All events are JSON-encoded in the `data` field.

---

**`node_done`** — emitted after each pipeline node completes within a task:
```
data: {"type":"node_done","smell_id":"smell_a1b2c3d4","node":"classify","status":"done"}
```

| Field | Values |
|---|---|
| `node` | `classify`, `plan`, `edit`, `verify`, `critique`, `finalize` |
| `status` | `done` |

---

**`task_done`** — emitted when a smell task finishes (pass or fail):
```
data: {"type":"task_done","smell_id":"smell_a1b2c3d4","component_name":"SpendCapSidePanel","file":"apps/studio/components/ui/SpendCapSidePanel.tsx","status":"accepted","tactic":"extract_component","retry_count":0,"critique_score":0.82}
```

| Field | Type | Description |
|---|---|---|
| `smell_id` | string | Which smell just finished |
| `component_name` | string | Human-readable component name |
| `file` | string | Relative file path |
| `status` | string | `accepted`, `rejected`, `skipped`, `failed` |
| `tactic` | string \| null | Tactic used (null if skipped/failed before plan) |
| `retry_count` | int | How many retries before final status |
| `critique_score` | float \| null | Final critique score (null if not reached) |
| `skip_reason` | string \| null | Reason if status is `skipped` |
| `error` | string \| null | Error message if status is `failed` |

---

**`run_complete`** — emitted when all tasks are done:
```
data: {"type":"run_complete","job_id":"job_20260412_143022_abc123","summary":{"accepted":6,"rejected":1,"skipped":1,"failed":0,"total":8,"total_cost_usd":0.042}}
```

| Field | Type | Description |
|---|---|---|
| `summary.accepted` | int | Tasks that passed critique and were written to disk |
| `summary.rejected` | int | Tasks that failed critique after all retries |
| `summary.skipped` | int | Tasks classified as non-actionable |
| `summary.failed` | int | Tasks that crashed with an error |
| `summary.total_cost_usd` | float | Total OpenAI API cost for this run |

---

**`cancelled`** — emitted when job is cancelled via `DELETE /jobs/{job_id}`:
```
data: {"type":"cancelled","job_id":"job_20260412_143022_abc123","completed":4,"cancelled":4}
```

---

**Reconnection behaviour:**  
If the client reconnects to a finished job, the server emits a single `run_complete` (or `cancelled`) event immediately then closes the stream.  
If the job is still running, the client receives all future events from that point (not a replay of past events).

---

### 5. `GET /jobs/{job_id}`

Poll the current state of a job without SSE.

**Response `200`:**
```json
{
  "job_id": "job_20260412_143022_abc123",
  "status": "running",
  "total_tasks": 8,
  "completed_tasks": 3,
  "tasks": [
    {
      "smell_id": "smell_a1b2c3d4",
      "component_name": "SpendCapSidePanel",
      "file": "apps/studio/components/ui/SpendCapSidePanel.tsx",
      "status": "accepted",
      "tactic": "extract_component",
      "retry_count": 0,
      "critique_score": 0.82
    },
    {
      "smell_id": "smell_b2c3d4e5",
      "component_name": "QueryPerformanceGrid",
      "file": "apps/studio/components/grid/QueryPerformanceGrid.tsx",
      "status": "running",
      "tactic": null,
      "retry_count": 0,
      "critique_score": null
    }
  ]
}
```

| `status` value | Meaning |
|---|---|
| `queued` | Not yet started |
| `running` | Currently processing tasks |
| `complete` | All tasks finished |
| `cancelled` | Stopped by user |

**Response `404`:**
```json
{
  "error": "job not found",
  "job_id": "job_xyz"
}
```

---

### 6. `DELETE /jobs/{job_id}`

Cancel a running job. Currently running task finishes before stopping.

**Request:** No body.

**Response `200`:**
```json
{
  "cancelled": true,
  "job_id": "job_20260412_143022_abc123",
  "completed_before_cancel": 4,
  "remaining_cancelled": 4
}
```

**Response `404`:**
```json
{
  "error": "job not found"
}
```

**Response `409`:**
```json
{
  "error": "job already complete",
  "status": "complete"
}
```

---

### 7. `POST /revert`

Revert a specific file back to its last git commit state (`git checkout -- <file>`).

**Request body:**
```json
{
  "workspace": "/absolute/path/to/react/project",
  "file": "apps/studio/components/ui/SpendCapSidePanel.tsx"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `workspace` | string | yes | Absolute path to the React project root |
| `file` | string | yes | Relative path from workspace root to the file to revert |

**Response `200`:**
```json
{
  "success": true,
  "file": "apps/studio/components/ui/SpendCapSidePanel.tsx"
}
```

**Response `200` (failure — not an HTTP error, handled gracefully):**
```json
{
  "success": false,
  "file": "apps/studio/components/ui/SpendCapSidePanel.tsx",
  "error": "file not tracked by git"
}
```

| `error` value | Cause |
|---|---|
| `file not tracked by git` | Workspace is not a git repo or file is untracked |
| `file not found` | File path does not exist on disk |
| `git command failed` | git returned a non-zero exit code (includes raw stderr) |

---

### 8. `GET /original`

Get the original (pre-refactor) content of a file from git HEAD. Used by the diff view.

**Query params:**

| Param | Type | Required | Description |
|---|---|---|---|
| `file` | string | yes | Relative file path from workspace root |
| `workspace` | string | yes | Absolute path to workspace root |

**Example:**
```
GET /original?file=apps/studio/components/ui/SpendCapSidePanel.tsx&workspace=/path/to/project
```

**Response `200`:**
```json
{
  "content": "import React from 'react'\n\nexport const SpendCapSidePanel = ...",
  "file": "apps/studio/components/ui/SpendCapSidePanel.tsx",
  "commit": "HEAD"
}
```

**Response `200` (not in git):**
```json
{
  "content": null,
  "file": "apps/studio/components/ui/SpendCapSidePanel.tsx",
  "error": "file not tracked by git"
}
```

---

## Error Response Format

All HTTP error responses follow this shape:

```json
{
  "error": "short human-readable message",
  "detail": "optional extra context"
}
```

| HTTP Status | When |
|---|---|
| `400` | Bad request — missing fields, invalid path, empty smells list |
| `404` | Job ID not found |
| `409` | Conflict — e.g. cancelling an already-complete job |
| `500` | Unexpected server error |

---

## SSE Connection Notes (for VS Code extension)

```typescript
// How to consume the SSE stream in the extension
const eventSource = new EventSource(`http://localhost:7432/progress/${jobId}`)

eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data)

  if (data.type === 'node_done') {
    // update node progress indicator for data.smell_id
  }
  if (data.type === 'task_done') {
    // update smell status icon in sidebar
  }
  if (data.type === 'run_complete') {
    eventSource.close()
    // show summary notification
  }
  if (data.type === 'cancelled') {
    eventSource.close()
  }
}

eventSource.onerror = () => {
  // server closed connection — job likely done
  eventSource.close()
}
```

---

## Smell Types Reference

Valid values for `smell_type` field:

| Smell Type | Description |
|---|---|
| `Large Component` | Component exceeds line threshold (default: 200 LOC) |
| `Too Many Props` | Component accepts more props than threshold (default: 10) |
| `Direct DOM Manipulation` | Uses `document.getElementById` / `querySelector` etc. |
| `Inheritance Instead of Composition` | Uses class inheritance where composition is preferred |
| `Uncontrolled Component` | Form inputs without controlled state |
| `Force Update` | Calls `forceUpdate()` directly |

---

## Changelog

| Version | Date | Change |
|---|---|---|
| 0.1.0 | 2026-04-12 | Initial contract |
