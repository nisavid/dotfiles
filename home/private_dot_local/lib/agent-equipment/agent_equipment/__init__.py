"""Public production API for global agent equipment desired state."""

from __future__ import annotations

import sys

from .canonical import (
    build_installed_implementation_manifest,
    byte_sha256,
    canonical_json_bytes,
    canonical_json_sha256,
    strict_load_json_bytes,
    strict_load_json_path,
)
from .model import (
    Catalog,
    CatalogLockValidation,
    CoverageRecord,
    Diagnostic,
    FrozenJsonObject,
    InstalledFile,
    InstalledImplementationManifest,
    ResolvedLock,
    ValidatedCatalogLock,
    freeze_json,
    thaw_json,
)
from .validator import load_catalog_lock, validate_catalog_lock

__all__ = (
    "Catalog",
    "CatalogLockValidation",
    "CoverageRecord",
    "Diagnostic",
    "FrozenJsonObject",
    "InstalledFile",
    "InstalledImplementationManifest",
    "ResolvedLock",
    "ValidatedCatalogLock",
    "build_installed_implementation_manifest",
    "byte_sha256",
    "canonical_json_bytes",
    "canonical_json_sha256",
    "freeze_json",
    "load_catalog_lock",
    "main",
    "strict_load_json_bytes",
    "strict_load_json_path",
    "thaw_json",
    "validate_catalog_lock",
)


def main(
    installed_implementation_manifest: InstalledImplementationManifest,
) -> int:
    """Fail closed until the production runtime commands are implemented."""

    if type(installed_implementation_manifest) is not InstalledImplementationManifest:
        raise TypeError(
            "installed_implementation_manifest must be an "
            "InstalledImplementationManifest"
        )
    print("agent-equipment: no runtime commands are available", file=sys.stderr)
    return 64
