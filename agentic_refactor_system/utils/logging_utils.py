"""Structured logger setup."""

from __future__ import annotations

import logging
import sys


def configure_logging(verbose: bool = False) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
        force=True,
    )
    return logging.getLogger("agentic_refactor_system")
