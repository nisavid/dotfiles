#!/usr/bin/env python3
# ruff: noqa: EXE001, F821, S102
"""Compatibility loader for the installed agent-equipment validator source."""

import sys
from pathlib import Path

_SHIM_FILE = Path(__file__).resolve()
_REPOSITORY_ROOT = _SHIM_FILE.parent.parent
_PACKAGE_ROOT = _REPOSITORY_ROOT / "home/private_dot_local/lib/agent-equipment"
_IMPLEMENTATION = _PACKAGE_ROOT / "agent_equipment/validator.py"
if str(_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_ROOT))

__package__ = "agent_equipment"
__file__ = str(_IMPLEMENTATION)
exec(compile(_IMPLEMENTATION.read_bytes(), str(_IMPLEMENTATION), "exec"), globals())
__file__ = str(_SHIM_FILE)

# Preserve the design-time API without publishing planning types from the
# installed validator module.
CoverageEntry = _CoverageEntry
PlannedOperation = _PlannedOperation
DesignValidationResult = _DesignValidationResult
load_and_validate = _load_and_validate
validate_design = _validate_design
globals().pop("__all__", None)

# Historical design tests deliberately redirect this mutable compatibility seam.
SCHEMA_DIRECTORY = _REPOSITORY_ROOT / "docs/agent-equipment"
