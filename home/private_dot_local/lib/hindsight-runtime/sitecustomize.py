"""Install Ivan's provider policy into supported Hindsight API processes."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import stat
import subprocess
import sys


_ALLOW_ACL = re.compile(r"^\s*\d+:.*\sallow\s")


def _reject_allow_acl(path: Path, label: str) -> None:
    result = subprocess.run(
        ["/bin/ls", "-lde", os.fspath(path)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if result.returncode != 0 or any(
        _ALLOW_ACL.search(line) for line in result.stdout.splitlines()
    ):
        raise RuntimeError(f"{label} is not protected")


def _protected_directory(
    path: Path,
    label: str,
    *,
    private: bool = False,
) -> None:
    metadata = path.stat(follow_symlinks=False)
    forbidden_mode = 0o077 if private else 0o022
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & forbidden_mode
    ):
        raise RuntimeError(f"{label} is not protected")
    _reject_allow_acl(path, label)


def _protected_directory_ancestry(
    path: Path,
    root: Path,
    label: str,
    *,
    private: bool = False,
) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise RuntimeError(f"{label} is outside its protected root") from error
    current = path
    while True:
        _protected_directory(current, label, private=private)
        if current == root:
            break
        current = current.parent


def _provider_policy_path(home: Path) -> Path:
    return home / ".config/hindsight-control-plane/provider-runtime-policy.json"


def _read_protected_file(path: Path, label: str) -> bytes:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or metadata.st_nlink != 1
            or metadata.st_size > 1024 * 1024
        ):
            raise RuntimeError(f"{label} is not protected")
        _reject_allow_acl(path, label)
        chunks = bytearray()
        while len(chunks) <= 1024 * 1024:
            chunk = os.read(descriptor, min(65536, 1024 * 1024 + 1 - len(chunks)))
            if not chunk:
                break
            chunks.extend(chunk)
        if len(chunks) > 1024 * 1024:
            raise RuntimeError(f"{label} is too large")
        return bytes(chunks)
    finally:
        os.close(descriptor)


if importlib.util.find_spec("hindsight_api") is not None:
    home = Path.home()
    install_root = home / ".local/opt/hindsight-control-plane"
    releases_root = install_root / "releases"
    try:
        release = (install_root / "active").resolve(strict=True)
        release.relative_to(releases_root.resolve(strict=True))
        release_lib = release / "lib"
        _protected_directory_ancestry(
            release,
            home,
            "active Hindsight release",
        )
        _protected_directory(release_lib, "active Hindsight release library")
        sys.path.insert(0, str(release_lib))

        from hindsight_memory_control_plane.canonical import strict_json_loads
        from hindsight_memory_control_plane.provider_runtime import (
            HindsightProviderAdapter,
            ProviderRuntimePolicy,
        )

        policy_path = _provider_policy_path(home)
        policy = ProviderRuntimePolicy.load(
            strict_json_loads(
                _read_protected_file(policy_path, "Hindsight provider policy")
            )
        )
        oauth_homes = {
            "oauth-home:personal": home / ".hindsight/codex-nisavid",
            "oauth-home:work": home / ".hindsight/codex-systalyze",
        }

        def resolve_oauth_home(locator: str) -> str:
            selected = oauth_homes.get(locator)
            if selected is None:
                raise RuntimeError("unknown Hindsight OAuth-home locator")
            _protected_directory_ancestry(
                selected,
                home,
                "Hindsight OAuth home",
            )
            _protected_directory(
                selected,
                "Hindsight OAuth home",
                private=True,
            )
            auth = selected / "auth.json"
            _read_protected_file(auth, "Hindsight OAuth home")
            return str(selected)

        HindsightProviderAdapter(
            policy,
            credential_resolver=resolve_oauth_home,
        ).install()
    except Exception as error:
        raise SystemExit(
            f"Hindsight provider policy failed closed: {type(error).__name__}"
        ) from None
