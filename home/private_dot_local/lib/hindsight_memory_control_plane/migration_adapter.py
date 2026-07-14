"""Compatibility-gated subprocess seam for the narrow hindsight-admin surface."""

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .canonical import DIGEST

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


class MigrationApplyAdapter:
    """HTTP reconciliation plus digest-selected full-bank archive imports."""

    IMPORT_KINDS = frozenset({"import_bank", "migrate_bank", "replace_canonical_bank"})

    def __init__(self, *, data_plane: Any, admin: AdminMigrationAdapter,
                 archives: Mapping[str, str], restore_evidence: Mapping[str, Mapping[str, Any]],
                 rollback_archive: str, rollback_archive_digest: str,
                 archive_verifier: Callable[[str, str], bool]) -> None:
        if not isinstance(admin, AdminMigrationAdapter):
            raise MigrationAdapterError("admin migration adapter is required")
        if not isinstance(archives, Mapping) or not isinstance(restore_evidence, Mapping):
            raise MigrationAdapterError("migration archive inputs are invalid")
        if not Path(rollback_archive).is_absolute() or not DIGEST.fullmatch(rollback_archive_digest):
            raise MigrationAdapterError("rollback archive binding is invalid")
        if not callable(archive_verifier):
            raise MigrationAdapterError("rollback archive verifier is required")
        self.data_plane = data_plane
        self.admin = admin
        self.archives = dict(archives)
        self.restore_evidence = dict(restore_evidence)
        self.rollback_archive = rollback_archive
        self.rollback_archive_digest = rollback_archive_digest
        self.archive_verifier = archive_verifier
        self._rollback_ids: set[str] = set()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.data_plane, name)

    def apply_action(self, action: Any) -> None:
        if action.kind not in self.IMPORT_KINDS:
            self.data_plane.apply_action(action)
            return
        archive_digest = action.details.get("archive_digest")
        archive = self.archives.get(archive_digest)
        evidence = self.restore_evidence.get(archive_digest)
        if archive is None or evidence is None:
            raise MigrationAdapterError("approved migration archive or restore evidence is unavailable")
        self.admin.import_bank(archive, archive_digest, evidence)

    def create_rollback_bundle(self, plan_digest: str, action_ids: tuple[str, ...]) -> Any:
        self.admin.backup(self.rollback_archive, self.rollback_archive_digest)
        if self.archive_verifier(self.rollback_archive, self.rollback_archive_digest) is not True:
            raise MigrationAdapterError("created rollback archive digest does not match")
        bundle = self.data_plane.create_rollback_bundle(plan_digest, action_ids)
        self._rollback_ids.add(bundle.rollback_id)
        return bundle

    def verify_rollback_bundle(self, rollback: Any) -> bool:
        if rollback.rollback_id not in self._rollback_ids:
            return False
        evidence = self.restore_evidence.get(self.rollback_archive_digest)
        try:
            AdminMigrationAdapter._restore_evidence(evidence, self.rollback_archive_digest)
        except MigrationAdapterError:
            return False
        return self.data_plane.verify_rollback_bundle(rollback)

    def restore(self, rollback: Any) -> None:
        if rollback.rollback_id not in self._rollback_ids:
            raise MigrationAdapterError("rollback bundle is not bound to the migration adapter")
        evidence = self.restore_evidence.get(self.rollback_archive_digest)
        self.admin.restore(
            self.rollback_archive, self.rollback_archive_digest, evidence,
        )
        self.data_plane.restore(rollback)
