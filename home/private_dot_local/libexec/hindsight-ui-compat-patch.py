#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from enum import Enum
from pathlib import Path


CONTROL_PLANE_PACKAGE = "@vectorize-io/hindsight-control-plane"
BROKEN_LOCALE_MARKER = b'defaultLocale:"en",localePrefix:"never"'
PATCHED_LOCALE_MARKER = b'defaultLocale:"en",localePrefix:"always"'
BROKEN_HEALTH_CHECK = b'''        try:
            with httpx.Client(timeout=2) as client:
                response = client.get(f"{ui_url}/api/health")
                return response.status_code == 200
        except Exception:
            return False
'''
PATCHED_HEALTH_CHECK = b'''        try:
            with httpx.Client(timeout=2, follow_redirects=True, max_redirects=8) as client:
                response = client.get(f"{ui_url}/")
                return response.status_code == 200
        except Exception:
            return False
'''


class PatchError(RuntimeError):
    pass


class PatchResult(str, Enum):
    PATCHED = "patched"
    ALREADY_PATCHED = "already-patched"


def replace_atomically(path: Path, content: bytes) -> None:
    mode = path.stat().st_mode & 0o7777
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.chmod(mode)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def control_plane_version(package_dir: Path) -> str:
    manifest = package_dir / "package.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PatchError(f"failed to read package manifest: {manifest}") from exc
    if data.get("name") != CONTROL_PLANE_PACKAGE:
        raise PatchError(f"unexpected package name in {manifest}: {data.get('name')!r}")
    version = data.get("version")
    if not isinstance(version, str) or not version:
        raise PatchError(f"missing package version in {manifest}")
    return version


def patch_control_plane(package_dir: Path, expected_version: str) -> PatchResult:
    package_dir = package_dir.resolve()
    actual_version = control_plane_version(package_dir)
    if actual_version != expected_version:
        raise PatchError(
            f"expected version {expected_version} at {package_dir}, found {actual_version}"
        )

    chunk_dir = package_dir / "standalone/.next/server/edge/chunks"
    if not chunk_dir.is_dir():
        raise PatchError(f"missing standalone middleware chunks: {chunk_dir}")

    broken_matches: list[Path] = []
    patched_matches: list[Path] = []
    for path in sorted(chunk_dir.rglob("*.js")):
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise PatchError(f"failed to read middleware chunk: {path}") from exc
        broken_matches.extend([path] * content.count(BROKEN_LOCALE_MARKER))
        patched_matches.extend([path] * content.count(PATCHED_LOCALE_MARKER))

    if len(broken_matches) == 0 and len(patched_matches) == 1:
        return PatchResult.ALREADY_PATCHED
    if len(broken_matches) != 1 or patched_matches:
        raise PatchError(
            "expected exactly one unpatched locale middleware marker; "
            f"found broken={len(broken_matches)} patched={len(patched_matches)}"
        )

    path = broken_matches[0]
    content = path.read_bytes()
    replace_atomically(
        path, content.replace(BROKEN_LOCALE_MARKER, PATCHED_LOCALE_MARKER, 1)
    )
    return PatchResult.PATCHED


def embed_version(package_dir: Path) -> str:
    init_file = package_dir / "__init__.py"
    try:
        content = init_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise PatchError(f"failed to read Hindsight embed package: {init_file}") from exc
    match = re.search(r'^__version__ = "([^"]+)"$', content, re.MULTILINE)
    if match is None:
        raise PatchError(f"missing Hindsight embed version in {init_file}")
    return match.group(1)


def patch_embed(package_dir: Path, expected_version: str) -> PatchResult:
    package_dir = package_dir.resolve()
    actual_version = embed_version(package_dir)
    if actual_version != expected_version:
        raise PatchError(
            f"expected version {expected_version} at {package_dir}, found {actual_version}"
        )

    manager = package_dir / "daemon_embed_manager.py"
    try:
        content = manager.read_bytes()
    except OSError as exc:
        raise PatchError(f"failed to read Hindsight embed manager: {manager}") from exc
    broken_count = content.count(BROKEN_HEALTH_CHECK)
    patched_count = content.count(PATCHED_HEALTH_CHECK)
    if broken_count == 0 and patched_count == 1:
        return PatchResult.ALREADY_PATCHED
    if broken_count != 1 or patched_count:
        raise PatchError(
            "expected exactly one unpatched UI health check; "
            f"found broken={broken_count} patched={patched_count}"
        )

    replace_atomically(
        manager, content.replace(BROKEN_HEALTH_CHECK, PATCHED_HEALTH_CHECK, 1)
    )
    return PatchResult.PATCHED


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply guarded compatibility fixes for Hindsight UI health."
    )
    subparsers = parser.add_subparsers(dest="component", required=True)
    for component in ("control-plane", "embed"):
        subparser = subparsers.add_parser(component)
        subparser.add_argument("--package-dir", required=True, type=Path)
        subparser.add_argument("--expected-version", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    patch = patch_control_plane if args.component == "control-plane" else patch_embed
    try:
        result = patch(args.package_dir, args.expected_version)
    except PatchError as exc:
        print(f"hindsight-ui-compat-patch: {exc}", file=sys.stderr)
        return 1
    print(result.value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
