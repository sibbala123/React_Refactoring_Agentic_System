"""
Resolve the OpenAI API key from either the environment or the VS Code
extension's own settings, so standalone scripts (run_single_task.py,
experiments/validate_against_commits.py, ...) and the VS Code extension can
share a single key without updating it in two places.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


def _vscode_settings_path() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidate = Path(appdata) / "Code" / "User" / "settings.json"
        if candidate.exists():
            return candidate

    linux_candidate = Path.home() / ".config" / "Code" / "User" / "settings.json"
    if linux_candidate.exists():
        return linux_candidate

    mac_candidate = Path.home() / "Library" / "Application Support" / "Code" / "User" / "settings.json"
    if mac_candidate.exists():
        return mac_candidate

    return None


def _strip_json_comments(text: str) -> str:
    # VS Code settings.json is JSONC (allows // and /* */ comments) even though
    # it's plain JSON in the common case. Strip comments defensively before
    # falling back to a stricter parse.
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"(?<!:)//.*", "", text)
    return text


def _read_vscode_openai_key() -> str | None:
    settings_path = _vscode_settings_path()
    if settings_path is None:
        return None
    try:
        raw = settings_path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = json.loads(_strip_json_comments(raw))
        key = data.get("reactRefactor.openaiApiKey")
        return key.strip() if isinstance(key, str) and key.strip() else None
    except Exception:
        return None


def ensure_openai_api_key() -> str | None:
    """
    Make sure OPENAI_API_KEY is set in the process environment before any
    pipeline node runs.

    Precedence matches the VS Code extension's own serverManager.ts: the key
    configured in VS Code Settings (reactRefactor.openaiApiKey) wins whenever
    it's set, falling back to whatever OPENAI_API_KEY is already in the
    environment otherwise. Matching the extension's precedence means editing
    the key in exactly one place (VS Code Settings) is enough to update both
    the extension and these standalone scripts - a stale env var left over
    from before won't silently keep getting used.

    Returns the resolved key, or None if neither source has one.
    """
    vscode_key = _read_vscode_openai_key()
    if vscode_key:
        if os.environ.get("OPENAI_API_KEY") != vscode_key:
            print("[openai_key] Using OPENAI_API_KEY from VS Code's reactRefactor.openaiApiKey setting.")
        os.environ["OPENAI_API_KEY"] = vscode_key
        return vscode_key

    existing = os.environ.get("OPENAI_API_KEY")
    if existing:
        print("[openai_key] reactRefactor.openaiApiKey is not set in VS Code - falling back to the OPENAI_API_KEY environment variable.")
    return existing
