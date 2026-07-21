#!/usr/bin/env python3
"""Minimal hook-test seam for the separately owned body validator."""

import sys


body = sys.stdin.read()
valid_arguments = (
    len(sys.argv) == 6
    and sys.argv[1] == "/dev/stdin"
    and sys.argv[2] == "--repository"
    and sys.argv[4] == "--pr"
)
valid_body = body == "<!-- test-canonical-change-navigation -->\n"
raise SystemExit(0 if valid_arguments and valid_body else 1)
