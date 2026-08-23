from __future__ import annotations

import csv
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..state import TaskState

logger = logging.getLogger(__name__)

# Tactics that work by deleting a named prop/state identifier entirely. These are the only
# tactics that can produce a "compiles fine, smell pattern gone, but silently deletes a real
# usage" failure — extraction tactics (extract_component, split_component, ...) never remove
# a name that the file's own logic still reads, so this check only applies here.
REMOVAL_TACTICS = frozenset({
    "remove_unused_props",
    "remove_unused_state",
    "remove_props_in_initial_state",
})

_SMELL_NAME_MAP = {
    "large component": "Large Component",
    "too many props": "Too Many Props",
    "inheritance instead of composition": "Inheritance Instead of Composition",
    "props in initial state": "Props in Initial State",
    "direct dom manipulation": "Direct DOM Manipulation",
    "force update": "Force Update",
    "jsx outside the render method": "JSX Outside the Render Method",
    "uncontrolled component": "Uncontrolled Component",
}


def _normalize_smell_name(raw: str) -> str:
    return _SMELL_NAME_MAP.get(raw.strip().lower(), raw.strip())


_TYPE_OR_INTERFACE_START_RE = re.compile(
    r"(?:type\s+\w+\s*=\s*|interface\s+\w+(?:\s+extends\s+[^{]+)?\s*)\{"
)
_STATE_ASSIGN_START_RE = re.compile(r"this\.state\s*=\s*\{")
_PROP_KEY_LINE_RE = re.compile(r"^\s*(?:readonly\s+)?([A-Za-z_$][A-Za-z0-9_$]*)\??\s*:")
_DESTRUCTURE_RE = re.compile(r"\{\s*([^{}]+?)\s*\}\s*=\s*(?:this\.)?(?:props|state)\b")
_USE_STATE_RE = re.compile(
    r"const\s*\[\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*,\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*\]\s*=\s*useState"
)


def _matching_brace_block(text: str, open_brace_idx: int) -> str:
    """Given the index of a '{', return the text between it and its matching '}'."""
    depth = 0
    for i in range(open_brace_idx, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_idx + 1:i]
    return text[open_brace_idx + 1:]


def _extract_declared_names(text: str) -> set[str]:
    """
    Heuristically collect prop/state identifier names declared in a React file:
    TS prop/state type blocks, this.state = {...} assignments, destructuring from
    props/state, and useState() pairs. Best-effort text heuristic (no real AST), tuned to
    have zero false negatives on the common patterns rather than perfect precision.
    """
    names: set[str] = set()

    for start_re in (_TYPE_OR_INTERFACE_START_RE, _STATE_ASSIGN_START_RE):
        for m in start_re.finditer(text):
            block = _matching_brace_block(text, m.end() - 1)
            for line in block.splitlines():
                key_match = _PROP_KEY_LINE_RE.match(line)
                if key_match:
                    names.add(key_match.group(1))

    for m in _DESTRUCTURE_RE.finditer(text):
        for token in m.group(1).split(","):
            token = token.strip()
            if not token or token.startswith("..."):
                continue
            # `{ a: renamed = default }` — the source key is `a`, before any `:` or `=`.
            token = token.split(":")[0].split("=")[0].strip()
            if token:
                names.add(token)

    for m in _USE_STATE_RE.finditer(text):
        names.add(m.group(1))
        names.add(m.group(2))

    return names


def _find_unsafely_removed_identifiers(before_text: str, after_text: str) -> list[str]:
    """
    Names declared as a prop/state in `before_text` that are entirely absent from
    `after_text`, AND that occurred more than once in `before_text` (i.e. had at least
    one real usage beyond their own declaration). A genuinely dead prop/state name
    occurs exactly once (its declaration) before removal.
    """
    removed = _extract_declared_names(before_text) - _extract_declared_names(after_text)
    flagged = []
    for name in removed:
        occurrences = len(re.findall(rf"\b{re.escape(name)}\b", before_text))
        if occurrences >= 2:
            flagged.append(name)
    return sorted(flagged)


def _run_tsc_on_file(file_path: Path, cwd: Path) -> tuple[int, str]:
    """Run tsc --noEmit --skipLibCheck --isolatedModules on a single file."""
    try:
        res = subprocess.run(
            f'npx --yes tsc --noEmit --skipLibCheck --isolatedModules --jsx react --esModuleInterop "{file_path}"',
            cwd=cwd,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
        return res.returncode, res.stdout + res.stderr
    except subprocess.TimeoutExpired as e:
        return 1, f"TSC timeout after 30 seconds: {e}"
    except Exception as e:
        return 1, str(e)


def verify_node(state: TaskState) -> dict[str, Any]:
    task_id = state["task_id"]
    changed = state.get("changed_files") or []
    target_root_str = state["manifest_task"].get("target_root")
    target_root = Path(target_root_str) if target_root_str else None
    target_file = state["target_file"]

    no_op_check = "fail" if len(changed) == 0 else "pass"
    abs_file: Path | None = None  # resolved absolute path to the edited file

    # 1. Per-file TypeScript check
    # Run tsc --isolatedModules on just the edited file — fast (~1-2s), no whole-repo scan.
    build_check = "skipped"
    if no_op_check == "pass" and target_root and target_root.exists():
        # Resolve the absolute path to the edited file (target_file is repo-relative,
        # target_root is the package dir — walk up ancestors to find the repo root).
        target_file_path = Path(target_file.lstrip("/"))
        abs_file: Path | None = None
        candidate = target_root
        for _ in range(10):
            abs_candidate = (candidate / target_file_path).resolve()
            if abs_candidate.exists():
                abs_file = abs_candidate
                break
            candidate = candidate.parent

        if abs_file is None:
            logger.warning("[%s] verify | could not resolve absolute path for %s, skipping tsc", task_id, target_file)
        else:
            logger.info("[%s] verify | running tsc --isolatedModules on %s", task_id, abs_file)
            try:
                _, output = _run_tsc_on_file(abs_file, cwd=target_root)
                # Only count errors that reference our specific edited file.
                # This avoids failing on pre-existing errors in sibling files
                # that tsc scans due to import resolution.
                abs_file_norm = str(abs_file).replace("\\", "/").lower()
                our_errors = [
                    line for line in output.splitlines()
                    if abs_file_norm in line.replace("\\", "/").lower()
                    and "error TS" in line
                ]
                build_check = "pass" if not our_errors else "fail"
                if build_check == "fail":
                    logger.warning("[%s] verify | tsc errors in %s: %s", task_id, target_file, "\n".join(our_errors[:5]))
            except Exception as e:
                logger.error("[%s] verify | tsc exception: %s", task_id, e)
                build_check = "fail"

    # 2. Run Smell Resolution
    # Runs independently of build_check — smell resolution is orthogonal to type correctness.
    smell_resolved_check = "skipped"
    smell_type = state["smell"].get("smell_type")

    if no_op_check == "pass" and target_root and target_root.exists() and smell_type:
        reactsniffer_root = Path(__file__).resolve().parent.parent.parent.parent / "vendor" / "reactsniffer"

        # Reuse abs_file resolved above if available, otherwise re-resolve.
        if abs_file is not None:
            scan_dir = abs_file.parent
        else:
            target_file_path = Path(target_file.lstrip("/"))
            scan_dir = target_root  # fallback
            candidate = target_root
            for _ in range(10):
                abs_candidate = (candidate / target_file_path).resolve()
                if abs_candidate.exists():
                    scan_dir = abs_candidate.parent
                    break
                candidate = candidate.parent

        logger.info("[%s] verify | running reactsniffer on %s", task_id, scan_dir)
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                node_cmd = f'node "{Path(reactsniffer_root) / "index.js"}" "{scan_dir}"'
                res = subprocess.run(
                    node_cmd,
                    cwd=tmpdir,
                    shell=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=False,
                    timeout=30,
                )

                smell_resolved_check = "pass"

                components_csv = Path(tmpdir) / "components_smells.csv"
                if not components_csv.exists():
                    logger.info("[%s] verify | reactsniffer produced no components_smells.csv (resolved).", task_id)
                else:
                    abs_file_str = str(abs_file).replace("\\", "/").lower() if abs_file else ""
                    target_comp = state["smell"].get("component_name")

                    with components_csv.open("r", encoding="utf-8-sig", newline="") as fh:
                        for row in csv.DictReader(fh):
                            if _normalize_smell_name(row.get("Smell", "")) != smell_type:
                                continue
                            # Only check smells in the specific file we edited.
                            row_file = row.get("file", "").replace("\\", "/").lower()
                            if abs_file_str and abs_file_str not in row_file and row_file not in abs_file_str:
                                continue
                            # Same file — check component match.
                            found_comp = row.get("Component") or None
                            if target_comp and found_comp and target_comp != found_comp:
                                continue
                            smell_resolved_check = "fail"
                            logger.warning(
                                "[%s] verify | smell %s NOT resolved (still present in %s / %s).",
                                task_id, smell_type, row_file, found_comp,
                            )
                            break

        except Exception as e:
            logger.error("[%s] verify | reactsniffer exception: %s", task_id, e)
            smell_resolved_check = "fail"

    # 3. Removal-tactic usage-safety check (deterministic, no LLM involved).
    # remove_unused_props / remove_unused_state / remove_props_in_initial_state all work by
    # deleting a declared prop/state name outright. If that name was referenced anywhere else
    # in the original file besides its own declaration, it was not actually dead — the edit
    # likely compiles fine and clears the smell pattern while silently deleting real behaviour.
    usage_safety_check = "skipped"
    flagged_identifiers: list[str] = []
    plan = state.get("plan") or {}
    tactic_name = plan.get("tactic_name")
    if no_op_check == "pass" and tactic_name in REMOVAL_TACTICS:
        before_contents = (state.get("edit_result") or {}).get("before_contents") or {}
        before_text = before_contents.get(target_file)
        if before_text is not None and abs_file is not None and abs_file.exists():
            after_text = abs_file.read_text(encoding="utf-8", errors="replace")
            flagged_identifiers = _find_unsafely_removed_identifiers(before_text, after_text)
            usage_safety_check = "fail" if flagged_identifiers else "pass"
            if flagged_identifiers:
                logger.warning(
                    "[%s] verify | tactic=%s removed identifiers still referenced elsewhere in the original file: %s",
                    task_id, tactic_name, flagged_identifiers,
                )
        else:
            logger.warning(
                "[%s] verify | no before_contents recorded for %s, skipping usage-safety check",
                task_id, target_file,
            )

    passed = (
        no_op_check == "pass"
        and build_check in ("pass", "skipped")
        and smell_resolved_check in ("pass", "skipped")
        and usage_safety_check in ("pass", "skipped")
    )
    if not passed:
        logger.warning(
            "[%s] verify | checks failed -> no_op: %s, typecheck: %s, smell_resolved: %s, usage_safety: %s",
            task_id, no_op_check, build_check, smell_resolved_check, usage_safety_check,
        )

    return {
        "verification_result": {
            "passed": passed,
            "checks": {
                "no_op": no_op_check,
                "typecheck": build_check,
                "smell_resolved": smell_resolved_check,
                "usage_safety": usage_safety_check,
            },
            "flagged_identifiers": flagged_identifiers,
        }
    }
