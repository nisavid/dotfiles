"""Production agent-equipment package tests."""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = (
    Path(__file__).resolve().parents[2] / "home/private_dot_local/lib/agent-equipment"
)
sys.path.insert(0, str(PACKAGE_ROOT))
