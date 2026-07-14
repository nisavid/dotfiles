#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


repo_dir = Path(__file__).resolve().parent.parent
helper_path = repo_dir / "home/private_dot_local/libexec/hindsight-ui-compat-patch.py"
spec = importlib.util.spec_from_file_location("hindsight_ui_compat_patch", helper_path)
assert spec and spec.loader
helper = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = helper
spec.loader.exec_module(helper)


def make_control_plane(root: Path, *, version: str = "0.8.4", source: bytes | None = None) -> tuple[Path, Path]:
    package_dir = root / "node_modules/@vectorize-io/hindsight-control-plane"
    chunk = package_dir / "standalone/.next/server/edge/chunks/middleware.js"
    chunk.parent.mkdir(parents=True)
    (package_dir / "package.json").write_text(
        json.dumps({"name": helper.CONTROL_PLANE_PACKAGE, "version": version}),
        encoding="utf-8",
    )
    chunk.write_bytes(
        source
        if source is not None
        else b"before " + helper.BROKEN_LOCALE_MARKER + b" after"
    )
    chunk.chmod(0o640)
    return package_dir, chunk


with tempfile.TemporaryDirectory() as temp_dir:
    package_dir, chunk = make_control_plane(Path(temp_dir))
    assert helper.patch_control_plane(package_dir, "0.8.4") == helper.PatchResult.PATCHED
    assert helper.PATCHED_LOCALE_MARKER in chunk.read_bytes()
    assert helper.BROKEN_LOCALE_MARKER not in chunk.read_bytes()
    assert chunk.stat().st_mode & 0o777 == 0o640
    assert helper.patch_control_plane(package_dir, "0.8.4") == helper.PatchResult.ALREADY_PATCHED

with tempfile.TemporaryDirectory() as temp_dir:
    package_dir, _ = make_control_plane(Path(temp_dir), version="0.8.5")
    try:
        helper.patch_control_plane(package_dir, "0.8.4")
    except helper.PatchError as exc:
        assert "expected version 0.8.4" in str(exc)
    else:
        raise AssertionError("version mismatch unexpectedly succeeded")

with tempfile.TemporaryDirectory() as temp_dir:
    package_dir, _ = make_control_plane(Path(temp_dir), source=b"unrecognized middleware")
    try:
        helper.patch_control_plane(package_dir, "0.8.4")
    except helper.PatchError as exc:
        assert "expected exactly one" in str(exc)
    else:
        raise AssertionError("unrecognized middleware unexpectedly succeeded")

with tempfile.TemporaryDirectory() as temp_dir:
    source = helper.BROKEN_LOCALE_MARKER + b" separator " + helper.BROKEN_LOCALE_MARKER
    package_dir, _ = make_control_plane(Path(temp_dir), source=source)
    try:
        helper.patch_control_plane(package_dir, "0.8.4")
    except helper.PatchError as exc:
        assert "expected exactly one" in str(exc)
    else:
        raise AssertionError("multiple middleware markers unexpectedly succeeded")


def make_embed(root: Path, *, version: str = "0.8.4", source: bytes | None = None) -> tuple[Path, Path]:
    package_dir = root / "hindsight_embed"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text(
        f'__version__ = "{version}"\n', encoding="utf-8"
    )
    manager = package_dir / "daemon_embed_manager.py"
    manager.write_bytes(
        source
        if source is not None
        else b"prefix\n" + helper.BROKEN_HEALTH_CHECK + b"suffix\n"
    )
    manager.chmod(0o640)
    return package_dir, manager


with tempfile.TemporaryDirectory() as temp_dir:
    package_dir, manager = make_embed(Path(temp_dir))
    assert helper.patch_embed(package_dir, "0.8.4") == helper.PatchResult.PATCHED
    assert helper.PATCHED_HEALTH_CHECK in manager.read_bytes()
    assert helper.BROKEN_HEALTH_CHECK not in manager.read_bytes()
    assert manager.stat().st_mode & 0o777 == 0o640
    assert helper.patch_embed(package_dir, "0.8.4") == helper.PatchResult.ALREADY_PATCHED

with tempfile.TemporaryDirectory() as temp_dir:
    package_dir, _ = make_embed(Path(temp_dir), version="0.8.5")
    try:
        helper.patch_embed(package_dir, "0.8.4")
    except helper.PatchError as exc:
        assert "expected version 0.8.4" in str(exc)
    else:
        raise AssertionError("embed version mismatch unexpectedly succeeded")

with tempfile.TemporaryDirectory() as temp_dir:
    package_dir, _ = make_embed(Path(temp_dir), source=b"unrecognized health check")
    try:
        helper.patch_embed(package_dir, "0.8.4")
    except helper.PatchError as exc:
        assert "expected exactly one" in str(exc)
    else:
        raise AssertionError("unrecognized embed health check unexpectedly succeeded")
