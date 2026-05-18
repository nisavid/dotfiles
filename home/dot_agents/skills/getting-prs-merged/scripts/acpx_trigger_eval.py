#!/usr/bin/env python3
"""Compatibility wrapper for the generic ACPX trigger eval runner."""

from __future__ import annotations

import os
import sys
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SKILLS_ROOT = Path(__file__).resolve().parents[2]
TARGET = SKILLS_ROOT / "adapting-skill-creator-to-harnesses" / "scripts" / "acpx_trigger_eval.py"


def has_skill_dir(args: list[str]) -> bool:
    return any(arg == "--skill-dir" or arg.startswith("--skill-dir=") for arg in args)


def main() -> None:
    args = sys.argv[1:]
    if not has_skill_dir(args):
        args = ["--skill-dir", str(SKILL_DIR), *args]
    os.execv(sys.executable, [sys.executable, str(TARGET), *args])


if __name__ == "__main__":
    main()
