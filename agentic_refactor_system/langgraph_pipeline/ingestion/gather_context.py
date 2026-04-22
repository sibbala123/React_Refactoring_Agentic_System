from __future__ import annotations

import sys
from pathlib import Path

# Ensure scripts/ (which contains the real gather_context.py) is on sys.path
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "agentic_refactor_system" / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_UTILS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "agentic_refactor_system" / "utils"
_AGENTIC_DIR = _UTILS_DIR.parent
if str(_AGENTIC_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTIC_DIR))

from gather_context import gather_context_for_smell  # noqa: F401
