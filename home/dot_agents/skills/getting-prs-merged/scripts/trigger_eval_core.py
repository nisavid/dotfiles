"""Compatibility shim for the generic trigger eval core."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parents[2]
TARGET = SKILLS_ROOT / "adapting-skill-creator-to-harnesses" / "scripts" / "trigger_eval_core.py"
SPEC = importlib.util.spec_from_file_location("_adapting_trigger_eval_core", TARGET)
if SPEC is None or SPEC.loader is None:
    raise ImportError(f"cannot load trigger eval core from {TARGET}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

__all__ = [name for name in dir(MODULE) if not name.startswith("_")]
globals().update({name: getattr(MODULE, name) for name in __all__})
