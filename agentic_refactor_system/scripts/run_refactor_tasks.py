"""Run refactor tasks through pluggable refactor and critique agent adapters."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.artifact_utils import snapshot_files
from utils.json_utils import read_json, write_json
from utils.logging_utils import configure_logging
from utils.paths import task_dir
from utils.subprocess_utils import run_command


LOGGER = configure_logging()
FILE_BLOCK_RE = re.compile(
    r"BEGIN_FILE:\s*(?P<path>[^\r\n]+)\r?\n```[^\n]*\r?\n(?P<body>.*?)\r?\n```\r?\nEND_FILE",
    re.DOTALL,
)


class BaseRefactorAgentAdapter(ABC):
    """Adapter boundary for refactor agents."""

    @abstractmethod
    def execute(
        self,
        task: dict[str, Any],
        prompt_text: str,
        task_output_dir: Path,
        workspace: Path,
        attempt: int,
    ) -> dict[str, Any]:
        raise NotImplementedError


class BaseCritiqueAgentAdapter(ABC):
    """Adapter boundary for critique agents."""

    @abstractmethod
    def evaluate(
        self,
        task: dict[str, Any],
        critique_prompt_text: str,
        refactor_result: dict[str, Any],
        task_output_dir: Path,
        workspace: Path,
        attempt: int,
    ) -> dict[str, Any]:
        raise NotImplementedError


class MockRefactorAgentAdapter(BaseRefactorAgentAdapter):
    """Deterministic non-destructive refactor adapter for pipeline testing."""

    def execute(
        self,
        task: dict[str, Any],
        prompt_text: str,
        task_output_dir: Path,
        workspace: Path,
        attempt: int,
    ) -> dict[str, Any]:
        response_text = "\n".join(
            [
                f"Task: {task['id']}",
                "Adapter: mock_refactor",
                "Result: no repository edits were applied.",
                "",
                "Proposed plan:",
                f"- Inspect {task['target_file']}",
                f"- Refactor smell: {task['smell_type']}",
                "- Keep changes inside allowed scope",
                "",
                "BEGIN_FILE: " + task["target_file"],
                "```tsx",
                "// Mock adapter does not modify files. This is a placeholder artifact only.",
                "```",
                "END_FILE",
            ]
        )
        (task_output_dir / f"refactor_attempt{attempt}.txt").write_text(response_text + "\n", encoding="utf-8")
        (task_output_dir / f"refactor_attempt{attempt}.log").write_text(
            "Mock refactor adapter executed. No actual file edits were produced.\n",
            encoding="utf-8",
        )
        return {
            "status": "mock_completed",
            "adapter": "mock_refactor",
            "applied_changes": False,
            "response_text": response_text,
            "detected_file_blocks": len(FILE_BLOCK_RE.findall(response_text)),
            "notes": [
                "This adapter is for integration testing of prompt and critique flow.",
                "Swap with a real editing agent for actual code changes.",
            ],
        }


class MockCritiqueAgentAdapter(BaseCritiqueAgentAdapter):
    """Deterministic critique adapter for testing the dual-agent flow."""

    def evaluate(
        self,
        task: dict[str, Any],
        critique_prompt_text: str,
        refactor_result: dict[str, Any],
        task_output_dir: Path,
        workspace: Path,
        attempt: int,
    ) -> dict[str, Any]:
        response_text = json.dumps(
            {
                "acceptable": False,
                "score": 0.35,
                "issues": [
                    "Mock refactor adapter did not generate real edits.",
                    "No repository changes were applied, so the smell remains unresolved.",
                ],
                "recommendations": [
                    "Replace the mock refactor adapter with a real editing agent.",
                    "Require the refactor agent to emit valid full-file blocks only for allowed files.",
                ],
            },
            indent=2,
        )
        (task_output_dir / f"critique_attempt{attempt}.txt").write_text(response_text + "\n", encoding="utf-8")
        (task_output_dir / f"critique_attempt{attempt}.log").write_text(
            "Mock critique adapter executed against the refactor attempt.\n",
            encoding="utf-8",
        )
        critique = json.loads(response_text)
        critique["status"] = "mock_completed"
        critique["adapter"] = "mock_critique"
        critique["prompt_excerpt"] = critique_prompt_text[:800]
        return critique


class OpenHandsRefactorAgentAdapter(BaseRefactorAgentAdapter):
    """OpenHands-backed refactor adapter using a local SDK venv bridge."""

    def __init__(
        self,
        openhands_python: Path,
        bridge_script: Path,
        model: str = "gpt-5.2-codex",
        max_iterations: int = 80,
        force_login: bool = False,
        use_delegate: bool = False,
    ) -> None:
        self.openhands_python = openhands_python
        self.bridge_script = bridge_script
        self.model = model
        self.max_iterations = max_iterations
        self.force_login = force_login
        self.use_delegate = use_delegate

    def execute(
        self,
        task: dict[str, Any],
        prompt_text: str,
        task_output_dir: Path,
        workspace: Path,
        attempt: int,
    ) -> dict[str, Any]:
        prompt_path = task_output_dir / f"prompt_runtime_attempt{attempt}.txt"
        prompt_path.write_text(
            "\n\n".join(
                [
                    prompt_text.strip(),
                    "OpenHands runtime constraints:",
                    "- Edit files directly in the workspace if useful.",
                    "- In your final answer, output ONLY full-file BEGIN_FILE/END_FILE blocks for changed allowed files.",
                    "- Do NOT output unified diff blocks.",
                    "- Do NOT output partial snippets.",
                    "- If no safe refactor is possible, say so explicitly without fabricating edits.",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        response_path = task_output_dir / f"refactor_attempt{attempt}.txt"
        events_path = task_output_dir / f"refactor_attempt{attempt}.events.txt"
        result_path = task_output_dir / f"refactor_attempt{attempt}.result.json"
        command = [
            str(self.openhands_python),
            str(self.bridge_script),
            "--mode",
            "refactor",
            "--workspace",
            str(workspace),
            "--prompt-file",
            str(prompt_path),
            "--response-file",
            str(response_path),
            "--events-file",
            str(events_path),
            "--result-file",
            str(result_path),
            "--model",
            self.model,
            "--max-iterations",
            str(self.max_iterations),
        ]
        if self.force_login:
            command.append("--force-login")
        if self.use_delegate:
            command.append("--use-delegate")

        result = run_command(command, cwd=PROJECT_ROOT)
        (task_output_dir / f"refactor_attempt{attempt}.log").write_text(
            "\n".join(
                [
                    f"$ {result['command']}",
                    "",
                    "STDOUT:",
                    result["stdout"],
                    "",
                    "STDERR:",
                    result["stderr"],
                ]
            ),
            encoding="utf-8",
        )
        if result["returncode"] != 0 or not result_path.exists():
            raise RuntimeError(
                "OpenHands refactor agent failed. "
                f"See {task_output_dir / f'refactor_attempt{attempt}.log'} for details."
            )
        payload = read_json(result_path)
        payload["adapter"] = "openhands_refactor"
        return payload


class DirectEditorAgentAdapter(BaseRefactorAgentAdapter):
    """Zero-dependency Editor Agent perfectly matching the project tech stack, using urllib."""

    def __init__(
        self,
        model: str = "gpt-4o",
        base_url: str = "https://api.openai.com/v1",
        **kwargs: Any,
    ) -> None:
        import os
        if model == "gpt-5.2-codex":
            model = "gpt-4o"
        self.model = model
        self.api_key = os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url.rstrip("/")

    def execute(
        self,
        task: dict[str, Any],
        prompt_text: str,
        task_output_dir: Path,
        workspace: Path,
        attempt: int,
    ) -> dict[str, Any]:
        import urllib.request
        import urllib.error
        
        system_prompt = (
            "You are the Final Editor Agent. Your sole job is to execute the instructions in the finalized plan.\n"
            "Output the full updated file contents wrapped in BEGIN_FILE/END_FILE blocks.\n"
            "Example:\n"
            "BEGIN_FILE: path/to/file.tsx\n"
            "```tsx\n"
            "// ... whole file content ...\n"
            "```\n"
            "END_FILE\n"
            "Do NOT output unified diffs. Output ONLY full-file contents for allowed files."
        )

        prompt_path = task_output_dir / f"prompt_runtime_attempt{attempt}.txt"
        prompt_path.write_text(prompt_text + "\n\n" + system_prompt, encoding="utf-8")
        
        response_path = task_output_dir / f"refactor_attempt{attempt}.txt"
        result_path = task_output_dir / f"refactor_attempt{attempt}.result.json"
        
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set. Cannot run DirectEditorAgentAdapter.")
            
        data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_text}
            ],
            "temperature": 0.2,
        }
        
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
        )
        
        try:
            with urllib.request.urlopen(req) as response:
                resp_data = json.loads(response.read().decode("utf-8"))
            response_text = resp_data["choices"][0]["message"]["content"]
            
            response_path.write_text(response_text, encoding="utf-8")
            
            payload = {
                "status": "completed",
                "adapter": "direct_editor",
                "response_text": response_text,
                "model": self.model,
                "usage": resp_data.get("usage", {})
            }
            write_json(result_path, payload)
            return payload
            
        except urllib.error.URLError as e:
            (task_output_dir / f"refactor_attempt{attempt}.log").write_text(f"API Call Failed: {str(e)}", encoding="utf-8")
            raise RuntimeError(f"Direct Editor agent API call failed: {str(e)}")


class OpenHandsCritiqueAgentAdapter(BaseCritiqueAgentAdapter):
    """OpenHands-backed critique adapter using a local SDK venv bridge."""

    def __init__(
        self,
        openhands_python: Path,
        bridge_script: Path,
        model: str = "gpt-5.2-codex",
        max_iterations: int = 40,
        force_login: bool = False,
    ) -> None:
        self.openhands_python = openhands_python
        self.bridge_script = bridge_script
        self.model = model
        self.max_iterations = max_iterations
        self.force_login = force_login

    def evaluate(
        self,
        task: dict[str, Any],
        critique_prompt_text: str,
        refactor_result: dict[str, Any],
        task_output_dir: Path,
        workspace: Path,
        attempt: int,
    ) -> dict[str, Any]:
        prompt_path = task_output_dir / f"critique_prompt_runtime_attempt{attempt}.txt"
        prompt_path.write_text(
            "\n\n".join(
                [
                    critique_prompt_text.strip(),
                    "Refactor result summary:",
                    json.dumps(
                        {
                            "status": refactor_result.get("status"),
                            "changed_files": refactor_result.get("changed_files", []),
                            "response_excerpt": str(refactor_result.get("response_text", ""))[:12000],
                        },
                        indent=2,
                        sort_keys=True,
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        response_path = task_output_dir / f"critique_attempt{attempt}.txt"
        events_path = task_output_dir / f"critique_attempt{attempt}.events.txt"
        result_path = task_output_dir / f"critique_attempt{attempt}.result.json"
        command = [
            str(self.openhands_python),
            str(self.bridge_script),
            "--mode",
            "critique",
            "--workspace",
            str(workspace),
            "--prompt-file",
            str(prompt_path),
            "--response-file",
            str(response_path),
            "--events-file",
            str(events_path),
            "--result-file",
            str(result_path),
            "--model",
            self.model,
            "--max-iterations",
            str(self.max_iterations),
        ]
        if self.force_login:
            command.append("--force-login")

        result = run_command(command, cwd=PROJECT_ROOT)
        (task_output_dir / f"critique_attempt{attempt}.log").write_text(
            "\n".join(
                [
                    f"$ {result['command']}",
                    "",
                    "STDOUT:",
                    result["stdout"],
                    "",
                    "STDERR:",
                    result["stderr"],
                ]
            ),
            encoding="utf-8",
        )
        if result["returncode"] != 0 or not result_path.exists():
            raise RuntimeError(
                "OpenHands critique agent failed. "
                f"See {task_output_dir / f'critique_attempt{attempt}.log'} for details."
            )
        payload = read_json(result_path)
        critique = payload.get("critique", {})
        critique["status"] = payload.get("status")
        critique["adapter"] = "openhands_critique"
        critique["response_text"] = payload.get("response_text", "")
        critique["response_file"] = payload.get("response_file")
        critique["events_file"] = payload.get("events_file")
        critique["accumulated_cost"] = payload.get("accumulated_cost", 0.0)
        return critique


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--refactor-adapter", default="mock")
    parser.add_argument("--critique-adapter", default="mock")
    parser.add_argument("--openhands-root", default=r"C:\Users\jayan\OpenHands\software-agent-sdk")
    parser.add_argument("--openhands-python", default="")
    parser.add_argument("--openhands-model", default="gpt-5.2-codex")
    parser.add_argument("--openhands-max-iterations", type=int, default=80)
    parser.add_argument("--force-openhands-login", action="store_true")
    parser.add_argument("--use-delegate", action="store_true")
    parser.add_argument("--max-tasks", type=int, default=0)
    parser.add_argument("--task-ids", nargs="*", default=[])
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--critique-threshold", type=float, default=0.8)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def resolve_openhands_python(openhands_root: Path, explicit_python: str = "") -> Path:
    if explicit_python:
        return Path(explicit_python).resolve()

    candidates = [
        openhands_root / ".venv-win" / "Scripts" / "python.exe",
        openhands_root / ".venv" / "Scripts" / "python.exe",
        openhands_root / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
            
    # Fallback to current Python interpreter
    import sys
    LOGGER.warning("Could not find OpenHands in %s. Falling back to the current Python interpreter.", openhands_root)
    return Path(sys.executable).resolve()


def build_refactor_adapter(
    name: str,
    openhands_root: Path,
    openhands_python: Path,
    openhands_model: str,
    openhands_max_iterations: int,
    force_openhands_login: bool,
    use_delegate: bool,
) -> BaseRefactorAgentAdapter:
    normalized = name.lower()
    if normalized in {"mock", "placeholder"}:
        return MockRefactorAgentAdapter()
    if normalized == "openhands":
        return OpenHandsRefactorAgentAdapter(
            openhands_python=openhands_python,
            bridge_script=PROJECT_ROOT / "scripts" / "_openhands_sdk_bridge.py",
            model=openhands_model,
            max_iterations=openhands_max_iterations,
            force_login=force_openhands_login,
            use_delegate=use_delegate,
        )
    if normalized == "direct_editor":
        return DirectEditorAgentAdapter(
            model=openhands_model or "gpt-4o",
        )
    raise ValueError(f"Unsupported refactor adapter: {name}")


def build_critique_adapter(
    name: str,
    openhands_root: Path,
    openhands_python: Path,
    openhands_model: str,
    force_openhands_login: bool,
) -> BaseCritiqueAgentAdapter:
    normalized = name.lower()
    if normalized in {"mock", "placeholder"}:
        return MockCritiqueAgentAdapter()
    if normalized == "openhands":
        return OpenHandsCritiqueAgentAdapter(
            openhands_python=openhands_python,
            bridge_script=PROJECT_ROOT / "scripts" / "_openhands_sdk_bridge.py",
            model=openhands_model,
            force_login=force_openhands_login,
        )
    raise ValueError(f"Unsupported critique adapter: {name}")


def build_task_workspace(target_root: Path, task: dict[str, Any], task_output_dir: Path) -> Path:
    workspace = task_output_dir / "agent_workspace"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    task_scope = set(task["allowed_edit_scope"]["allowed_files"])
    task_scope.update(task.get("relevant_context_files", []))
    task_scope.add(task["target_file"])

    for rel_path in sorted(task_scope):
        source = (target_root / rel_path).resolve()
        if not source.exists() or not source.is_file():
            continue
        destination = workspace / rel_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    return workspace


def compose_retry_feedback(
    task: dict[str, Any],
    previous_refactor_result: dict[str, Any],
    previous_critique_result: dict[str, Any],
) -> str:
    return "\n\n".join(
        [
            "Retry guidance from previous attempt:",
            json.dumps(
                {
                    "task_id": task["id"],
                    "previous_changed_files": previous_refactor_result.get("changed_files", []),
                    "previous_response_excerpt": str(previous_refactor_result.get("response_text", ""))[:6000],
                    "critique_score": previous_critique_result.get("score"),
                    "critique_acceptable": previous_critique_result.get("acceptable"),
                    "issues": previous_critique_result.get("issues", []),
                    "recommendations": previous_critique_result.get("recommendations", []),
                },
                indent=2,
                sort_keys=True,
            ),
            "Produce a corrected attempt that addresses the critique exactly.",
        ]
    )


def diff_workspace_changes(pre_snapshot: dict[str, Any], workspace: Path, allowed_files: list[str]) -> list[str]:
    changed: list[str] = []
    for rel_path in sorted(set(allowed_files)):
        file_path = workspace / rel_path
        current_exists = file_path.exists() and file_path.is_file()
        before = pre_snapshot.get(rel_path, {"exists": False, "content": None})
        current_content = file_path.read_text(encoding="utf-8", errors="replace") if current_exists else None
        if current_exists != before.get("exists") or current_content != before.get("content"):
            changed.append(rel_path)
    return changed


def sync_workspace_changes(workspace: Path, target_root: Path, changed_files: list[str]) -> list[str]:
    synced: list[str] = []
    for rel_path in changed_files:
        source = workspace / rel_path
        destination = target_root / rel_path
        if not source.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        synced.append(rel_path)
    return synced


def apply_file_blocks_to_workspace(
    response_text: str,
    workspace: Path,
    allowed_files: list[str],
) -> list[str]:
    allowed = set(allowed_files)
    applied: list[str] = []
    for match in FILE_BLOCK_RE.finditer(response_text):
        rel_path = match.group("path").strip().replace("\\", "/")
        if rel_path not in allowed:
            LOGGER.warning("Skipping out-of-scope file block for %s", rel_path)
            continue
        file_path = (workspace / rel_path).resolve()
        if not str(file_path).startswith(str(workspace.resolve())):
            LOGGER.warning("Skipping unsafe file block path %s", rel_path)
            continue
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(match.group("body"), encoding="utf-8")
        applied.append(rel_path)
    return applied


def run_refactor_tasks(
    target_root: Path,
    run_root: Path,
    refactor_adapter: str = "mock",
    critique_adapter: str = "mock",
    openhands_root: Path | None = None,
    openhands_python: str = "",
    openhands_model: str = "gpt-5.2-codex",
    openhands_max_iterations: int = 80,
    force_openhands_login: bool = False,
    use_delegate: bool = False,
    max_tasks: int = 0,
    task_ids: list[str] | None = None,
    max_attempts: int = 2,
    critique_threshold: float = 0.8,
    dry_run: bool = False,
) -> dict[str, Any]:
    manifest = read_json(run_root / "manifest.json")
    resolved_openhands_root = (openhands_root or Path(r"C:\Users\jayan\OpenHands\software-agent-sdk")).resolve()
    resolved_openhands_python = resolve_openhands_python(resolved_openhands_root, openhands_python)
    refactor_runner = build_refactor_adapter(
        refactor_adapter,
        resolved_openhands_root,
        resolved_openhands_python,
        openhands_model,
        openhands_max_iterations,
        force_openhands_login,
        use_delegate,
    )
    critique_runner = build_critique_adapter(
        critique_adapter,
        resolved_openhands_root,
        resolved_openhands_python,
        openhands_model,
        force_openhands_login,
    )

    results: list[dict[str, Any]] = []
    tasks = manifest.get("tasks", [])
    if task_ids:
        allowed_task_ids = set(task_ids)
        tasks = [task for task in tasks if task["id"] in allowed_task_ids]
    if max_tasks > 0:
        tasks = tasks[:max_tasks]

    for task in tasks:
        task_output_dir = task_dir(run_root, task["id"])
        prompt_path = task_output_dir / "prompt.txt"
        critique_prompt_path = task_output_dir / "critique_prompt.txt"
        base_prompt_text = prompt_path.read_text(encoding="utf-8")
        critique_prompt_text = critique_prompt_path.read_text(encoding="utf-8") if critique_prompt_path.exists() else ""

        pre_snapshot = snapshot_files(target_root, task["allowed_edit_scope"]["allowed_files"])
        write_json(task_output_dir / "pre_snapshot.json", pre_snapshot)

        if dry_run:
            refactor_result = {
                "status": "skipped",
                "adapter": refactor_adapter,
                "applied_changes": False,
                "notes": ["Dry-run enabled; refactor agent execution skipped."],
            }
            critique_result = {
                "status": "skipped",
                "adapter": critique_adapter,
                "acceptable": None,
                "score": None,
                "issues": ["Dry-run enabled; critique agent execution skipped."],
                "recommendations": [],
            }
            (task_output_dir / "refactor_attempt1.txt").write_text(
                "Dry-run enabled. Refactor agent execution skipped.\n",
                encoding="utf-8",
            )
            (task_output_dir / "refactor_attempt1.log").write_text(
                "Dry-run enabled; no refactor adapter invocation occurred.\n",
                encoding="utf-8",
            )
            (task_output_dir / "critique_attempt1.txt").write_text(
                "Dry-run enabled. Critique agent execution skipped.\n",
                encoding="utf-8",
            )
            (task_output_dir / "critique_attempt1.log").write_text(
                "Dry-run enabled; no critique adapter invocation occurred.\n",
                encoding="utf-8",
            )
            changed_files: list[str] = []
            write_json(task_output_dir / "post_snapshot.json", pre_snapshot)
            agent_workspace = build_task_workspace(target_root, task, task_output_dir)
            attempts: list[dict[str, Any]] = []
            accepted_attempt = None
        else:
            attempts = []
            accepted_attempt = None
            retry_feedback = ""
            final_refactor_result: dict[str, Any] | None = None
            final_critique_result: dict[str, Any] | None = None
            final_workspace: Path | None = None
            changed_files = []

            for attempt in range(1, max_attempts + 1):
                agent_workspace = build_task_workspace(target_root, task, task_output_dir)
                final_workspace = agent_workspace
                prompt_text = base_prompt_text if not retry_feedback else "\n\n".join([base_prompt_text, retry_feedback])
                refactor_result = refactor_runner.execute(
                    task=task,
                    prompt_text=prompt_text,
                    task_output_dir=task_output_dir,
                    workspace=agent_workspace,
                    attempt=attempt,
                )
                file_block_applied = apply_file_blocks_to_workspace(
                    str(refactor_result.get("response_text", "")),
                    agent_workspace,
                    task["allowed_edit_scope"]["allowed_files"],
                )
                changed_files = diff_workspace_changes(
                    pre_snapshot,
                    agent_workspace,
                    task["allowed_edit_scope"]["allowed_files"],
                )
                refactor_result["changed_files"] = changed_files
                refactor_result["file_block_applied_files"] = file_block_applied
                refactor_result["applied_changes"] = bool(changed_files)
                critique_result = critique_runner.evaluate(
                    task=task,
                    critique_prompt_text=critique_prompt_text,
                    refactor_result=refactor_result,
                    task_output_dir=task_output_dir,
                    workspace=agent_workspace,
                    attempt=attempt,
                )
                accepted = bool(critique_result.get("acceptable")) and float(critique_result.get("score", 0.0)) >= critique_threshold
                attempts.append(
                    {
                        "attempt": attempt,
                        "accepted": accepted,
                        "refactor": refactor_result,
                        "critique": critique_result,
                    }
                )
                final_refactor_result = refactor_result
                final_critique_result = critique_result
                if accepted:
                    accepted_attempt = attempt
                    break
                retry_feedback = compose_retry_feedback(task, refactor_result, critique_result)

            refactor_result = final_refactor_result or {
                "status": "missing",
                "adapter": refactor_adapter,
                "applied_changes": False,
            }
            critique_result = final_critique_result or {
                "status": "missing",
                "adapter": critique_adapter,
                "acceptable": False,
                "score": 0.0,
                "issues": ["Critique result missing."],
                "recommendations": [],
            }
            agent_workspace = final_workspace or build_task_workspace(target_root, task, task_output_dir)

            if accepted_attempt is not None:
                synced_files = sync_workspace_changes(agent_workspace, target_root, changed_files)
                refactor_result["synced_files"] = synced_files
                refactor_result["applied_changes"] = bool(synced_files)
                write_json(
                    task_output_dir / "post_snapshot.json",
                    snapshot_files(target_root, task["allowed_edit_scope"]["allowed_files"]),
                )
            else:
                refactor_result["synced_files"] = []
                refactor_result["applied_changes"] = False
                changed_files = []
                write_json(task_output_dir / "post_snapshot.json", pre_snapshot)

        task_summary = {
            "task_id": task["id"],
            "target_file": task["target_file"],
            "smell_type": task["smell_type"],
            "agent_execution": {
                "refactor": refactor_result,
                "critique": critique_result,
            },
            "artifacts": {
                "prompt": str(prompt_path),
                "critique_prompt": str(critique_prompt_path),
                "pre_snapshot": str(task_output_dir / "pre_snapshot.json"),
                "post_snapshot": str(task_output_dir / "post_snapshot.json"),
                "agent_workspace": str(agent_workspace),
                "attempt_text": str(task_output_dir / "refactor_attempt1.txt"),
                "attempt_log": str(task_output_dir / "refactor_attempt1.log"),
                "critique_text": str(task_output_dir / "critique_attempt1.txt"),
                "critique_log": str(task_output_dir / "critique_attempt1.log"),
            },
            "changed_files": changed_files,
            "attempts": attempts,
            "accepted_attempt": accepted_attempt,
        }
        write_json(task_output_dir / "task_summary.json", task_summary)
        results.append(task_summary)

    write_json(
        run_root / "refactor_results.json",
        {
            "tasks": results,
            "count": len(results),
            "refactor_adapter": refactor_adapter,
            "critique_adapter": critique_adapter,
            "openhands_python": str(resolved_openhands_python),
            "openhands_model": openhands_model,
            "max_attempts": max_attempts,
            "critique_threshold": critique_threshold,
        },
    )
    return {"tasks": results, "count": len(results)}


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)
    run_refactor_tasks(
        target_root=Path(args.target_root).resolve(),
        run_root=Path(args.run_root).resolve(),
        refactor_adapter=args.refactor_adapter,
        critique_adapter=args.critique_adapter,
        openhands_root=Path(args.openhands_root).resolve(),
        openhands_python=args.openhands_python,
        openhands_model=args.openhands_model,
        openhands_max_iterations=args.openhands_max_iterations,
        force_openhands_login=args.force_openhands_login,
        use_delegate=args.use_delegate,
        max_tasks=args.max_tasks,
        task_ids=args.task_ids,
        max_attempts=args.max_attempts,
        critique_threshold=args.critique_threshold,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
