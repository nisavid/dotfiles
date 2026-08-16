#!/usr/bin/env python3
# ruff: noqa: EXE001, S102
"""Compatibility loader for the installed agent-equipment secret policy."""

import sys
from pathlib import Path

_SHIM_FILE = Path(__file__).resolve()
_REPOSITORY_ROOT = _SHIM_FILE.parent.parent
_PACKAGE_ROOT = _REPOSITORY_ROOT / "home/private_dot_local/lib/agent-equipment"
_IMPLEMENTATION = _PACKAGE_ROOT / "agent_equipment/secrets.py"
if str(_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_ROOT))

__package__ = "agent_equipment"
__file__ = str(_IMPLEMENTATION)
exec(compile(_IMPLEMENTATION.read_bytes(), str(_IMPLEMENTATION), "exec"), globals())
__file__ = str(_SHIM_FILE)
