"""Compatibility-gated subprocess seam for the narrow hindsight-admin surface."""

import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence


DIGEST = re.compile(r"[0-9a-f]{64}\Z")
OPERATIONS = {"export-bank", "import-bank", "backup", "restore"}


class MigrationAdapterError(RuntimeError):
    pass


class AdminMigrationAdapter:
    def __init__(self, *, admin_version: str, argv_factory: Callable[[str, str, str], Sequence[str]],
                 runner: Callable[[Sequence[str]], Any], supported_versions: frozenset[str] = frozenset({"1"})) -> None:
        if admin_version not in supported_versions:
            raise MigrationAdapterError("unsupported hindsight-admin version")
        self.admin_version = admin_version
        self.argv_factory = argv_factory
        self.runner = runner
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def _restore_evidence(evidence: Mapping[str, Any] | None, archive_digest: str) -> None:
        if not isinstance(evidence, Mapping) or set(evidence) != {"disposable", "restore_verified", "artifact_digest"}:
            raise MigrationAdapterError("disposable restore evidence is required")
        if evidence["disposable"] is not True or evidence["restore_verified"] is not True:
            raise MigrationAdapterError("disposable restore evidence is not verified")
        if evidence["artifact_digest"] != archive_digest:
            raise MigrationAdapterError("disposable restore evidence digest does not match archive")

    def _run(self, operation: str, archive: str, archive_digest: str,
             evidence: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        if operation not in OPERATIONS:
            raise MigrationAdapterError("unsupported hindsight-admin operation")
        if not Path(archive).is_absolute():
            raise MigrationAdapterError("archive path must be absolute")
        if not isinstance(archive_digest, str) or not DIGEST.fullmatch(archive_digest):
            raise MigrationAdapterError("archive digest is required")
        if operation in {"import-bank", "restore"}:
            self._restore_evidence(evidence, archive_digest)
        argv = self.argv_factory(operation, archive, archive_digest)
        if isinstance(argv, (str, bytes)) or not isinstance(argv, Sequence) or not all(isinstance(arg, str) for arg in argv):
            raise MigrationAdapterError("argv factory must return an argument vector, not a shell string")
        expected = ["hindsight-admin", operation, "--archive", archive, "--sha256", archive_digest]
        if list(argv) != expected:
            raise MigrationAdapterError("hindsight-admin argv shape is not permitted")
        forbidden = ("database", "postgres", "password", "credential", "sql")
        if any(any(word in arg.lower() for word in forbidden) for arg in argv):
            raise MigrationAdapterError("database credentials and direct SQL are forbidden")
        self.calls.append({"operation": operation, "archive_digest": archive_digest})
        result = self.runner(list(argv))
        returncode = result.get("returncode") if isinstance(result, Mapping) else getattr(result, "returncode", None)
        if returncode != 0:
            raise MigrationAdapterError("hindsight-admin operation failed")
        stdout = result.get("stdout", "{}") if isinstance(result, Mapping) else getattr(result, "stdout", "{}")
        try:
            value = json.loads(stdout or "{}")
        except json.JSONDecodeError:
            raise MigrationAdapterError("hindsight-admin returned invalid JSON") from None
        return value if isinstance(value, dict) else {"result": value}

    def export_bank(self, archive: str, archive_digest: str): return self._run("export-bank", archive, archive_digest)
    def backup(self, archive: str, archive_digest: str): return self._run("backup", archive, archive_digest)
    def import_bank(self, archive: str, archive_digest: str, disposable_restore_evidence=None):
        return self._run("import-bank", archive, archive_digest, disposable_restore_evidence)
    def restore(self, archive: str, archive_digest: str, disposable_restore_evidence=None):
        return self._run("restore", archive, archive_digest, disposable_restore_evidence)
