"""Compatibility-gated subprocess seam for the narrow hindsight-admin surface."""

from pathlib import Path
import hmac
import os
import re
import subprocess
from typing import Any, Callable, Mapping, Sequence

from .canonical import DIGEST, digest
from .file_evidence import (
    FileEvidenceError,
    file_identity,
    reject_symlink_components,
    validate_trusted_regular_file,
    verified_file_snapshot,
)

OPERATIONS = {"export-bank", "import-bank", "backup", "restore"}
BANK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
ADMIN_ENVIRONMENT_ALLOWLIST = frozenset(
    {
        "HINDSIGHT_API_DATABASE_URL",
        "LANG",
        "LC_ALL",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TZ",
    }
)
VERSION_PROBE = (
    "import importlib.metadata as metadata; "
    "print(metadata.version('hindsight-api'))"
)


class MigrationAdapterError(RuntimeError):
    pass


def _trusted_admin_executable(value: str | Path) -> tuple[str, tuple[int, ...], str]:
    path = Path(value)
    if not path.is_absolute():
        raise MigrationAdapterError("hindsight-admin executable path must be absolute")
    try:
        reject_symlink_components(path, "hindsight-admin executable", allow_missing=False)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            before = os.fstat(descriptor)
            validate_trusted_regular_file(before, "hindsight-admin executable")
            if not before.st_mode & 0o111:
                raise FileEvidenceError("hindsight-admin executable must be executable")
            first_line = os.read(descriptor, 4096).splitlines()[0]
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        current = path.lstat()
    except (FileEvidenceError, OSError, IndexError) as error:
        message = str(error) if isinstance(error, FileEvidenceError) else "hindsight-admin executable is unavailable"
        raise MigrationAdapterError(message) from None
    identity = file_identity(before)
    if identity != file_identity(after) or identity != file_identity(current):
        raise MigrationAdapterError("hindsight-admin executable identity changed")
    if not first_line.startswith(b"#!"):
        raise MigrationAdapterError("hindsight-admin executable interpreter is invalid")
    try:
        interpreter = first_line[2:].decode("utf-8")
    except UnicodeDecodeError:
        raise MigrationAdapterError("hindsight-admin executable interpreter is invalid") from None
    if not interpreter or any(character.isspace() for character in interpreter) or not Path(interpreter).is_absolute():
        raise MigrationAdapterError("hindsight-admin executable interpreter is invalid")
    return str(path), identity, interpreter


def hindsight_admin_argv(
    executable: str, operation: str, archive: str, bank_id: str | None
) -> list[str]:
    if operation in {"export-bank", "import-bank"} and (
        not isinstance(bank_id, str) or BANK_ID.fullmatch(bank_id) is None
    ):
        raise MigrationAdapterError("bank ID is required")
    if operation in {"backup", "restore"} and bank_id is not None:
        raise MigrationAdapterError("bank ID is not permitted for schema operation")
    if operation == "export-bank":
        return [
            executable, operation, "--bank", bank_id,
            "--output", archive,
        ]
    if operation == "import-bank":
        return [
            executable, operation, "--archive", archive,
            "--target-bank", bank_id,
        ]
    if operation == "backup":
        return [executable, operation, archive, "--schema", "public"]
    if operation == "restore":
        return [
            executable, operation, archive, "--schema", "public", "--yes",
        ]
    raise MigrationAdapterError("unsupported hindsight-admin operation")


class AdminMigrationAdapter:
    WORKING_DIRECTORY = "/"

    def __init__(self, *, admin_executable: str,
                 argv_factory: Callable[[str, str, str, str | None], Sequence[str]],
                 runner: Callable[..., Any], environment: Mapping[str, str] | None = None,
                 supported_versions: frozenset[str] = frozenset({"0.8.4"})) -> None:
        executable, identity, interpreter = _trusted_admin_executable(admin_executable)
        if not callable(argv_factory) or not callable(runner):
            raise MigrationAdapterError("hindsight-admin process seams are required")
        source_environment = dict(environment or {})
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in source_environment.items()):
            raise MigrationAdapterError("hindsight-admin environment is invalid")
        self.admin_executable = executable
        self._executable_identity = identity
        self._interpreter = interpreter
        self._environment = {
            key: source_environment[key]
            for key in sorted(ADMIN_ENVIRONMENT_ALLOWLIST & source_environment.keys())
        }
        self.argv_factory = argv_factory
        self.runner = runner
        self.calls: list[dict[str, Any]] = []
        probe = self._invoke([interpreter, "-I", "-c", VERSION_PROBE], timeout=30)
        self._require_executable_identity()
        version = self._result_field(probe, "stdout")
        if self._result_field(probe, "returncode") != 0 or not isinstance(version, str):
            raise MigrationAdapterError("hindsight-admin version probe failed")
        self.admin_version = version.strip()
        if self.admin_version not in supported_versions:
            raise MigrationAdapterError("unsupported hindsight-admin version")

    @staticmethod
    def _result_field(result: Any, field: str) -> Any:
        return result.get(field) if isinstance(result, Mapping) else getattr(result, field, None)

    def _invoke(self, argv: Sequence[str], *, timeout: int) -> Any:
        try:
            return self.runner(
                list(argv),
                cwd=self.WORKING_DIRECTORY,
                env=dict(self._environment),
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise MigrationAdapterError("hindsight-admin operation timed out") from None
        except Exception:
            raise MigrationAdapterError("hindsight-admin operation failed") from None

    def _require_executable_identity(self) -> None:
        executable, identity, interpreter = _trusted_admin_executable(self.admin_executable)
        if (
            executable != self.admin_executable
            or identity != self._executable_identity
            or interpreter != self._interpreter
        ):
            raise MigrationAdapterError("hindsight-admin executable identity changed")

    @staticmethod
    def _restore_evidence(
        evidence: Mapping[str, Any] | None,
        archive_digest: str,
        expected_evidence_digest: str,
    ) -> None:
        if not isinstance(evidence, Mapping) or set(evidence) != {
            "schema_version", "artifact_digest", "verification_receipt_digest",
        }:
            raise MigrationAdapterError("disposable restore evidence is required")
        if evidence["schema_version"] != 1:
            raise MigrationAdapterError("disposable restore evidence is not verified")
        if evidence["artifact_digest"] != archive_digest:
            raise MigrationAdapterError("disposable restore evidence digest does not match archive")
        receipt_digest = evidence["verification_receipt_digest"]
        if not isinstance(receipt_digest, str) or DIGEST.fullmatch(receipt_digest) is None:
            raise MigrationAdapterError("disposable restore evidence receipt is invalid")
        if (
            not isinstance(expected_evidence_digest, str)
            or DIGEST.fullmatch(expected_evidence_digest) is None
            or not hmac.compare_digest(digest(dict(evidence)), expected_evidence_digest)
        ):
            raise MigrationAdapterError("disposable restore evidence digest does not match plan")

    def _run(self, operation: str, archive: str, archive_digest: str,
             bank_id: str | None = None,
             expected_evidence_digest: str | None = None,
             evidence: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        if operation not in OPERATIONS:
            raise MigrationAdapterError("unsupported hindsight-admin operation")
        if not Path(archive).is_absolute():
            raise MigrationAdapterError("archive path must be absolute")
        if not isinstance(archive_digest, str) or not DIGEST.fullmatch(archive_digest):
            raise MigrationAdapterError("archive digest is required")
        if operation in {"export-bank", "import-bank"}:
            if not isinstance(bank_id, str) or BANK_ID.fullmatch(bank_id) is None:
                raise MigrationAdapterError("bank ID is required")
        elif bank_id is not None:
            raise MigrationAdapterError("bank ID is not permitted for schema operation")
        if operation in {"import-bank", "restore"}:
            self._restore_evidence(
                evidence, archive_digest, str(expected_evidence_digest)
            )
        self._require_executable_identity()
        argv = self.argv_factory(self.admin_executable, operation, archive, bank_id)
        if isinstance(argv, (str, bytes)) or not isinstance(argv, Sequence) or not all(isinstance(arg, str) for arg in argv):
            raise MigrationAdapterError("argv factory must return an argument vector, not a shell string")
        expected = hindsight_admin_argv(self.admin_executable, operation, archive, bank_id)
        if list(argv) != expected:
            raise MigrationAdapterError("hindsight-admin argv shape is not permitted")
        self.calls.append({
            "operation": operation,
            "archive_digest": archive_digest,
            **({"bank_id": bank_id} if bank_id is not None else {}),
        })
        result = self._invoke(list(argv), timeout=300)
        self._require_executable_identity()
        returncode = self._result_field(result, "returncode")
        if returncode != 0:
            raise MigrationAdapterError("hindsight-admin operation failed")
        return {"completed": True}

    def export_bank(self, archive: str, archive_digest: str, source_bank: str):
        return self._run("export-bank", archive, archive_digest, source_bank)
    def backup(self, archive: str, archive_digest: str): return self._run("backup", archive, archive_digest)
    def import_bank(self, archive: str, archive_digest: str, target_bank: str,
                    expected_evidence_digest: str,
                    disposable_restore_evidence=None):
        return self._run(
            "import-bank", archive, archive_digest, target_bank,
            expected_evidence_digest, disposable_restore_evidence,
        )
    def restore(self, archive: str, archive_digest: str,
                expected_evidence_digest: str, disposable_restore_evidence=None):
        return self._run(
            "restore", archive, archive_digest,
            expected_evidence_digest=expected_evidence_digest,
            evidence=disposable_restore_evidence,
        )


class MigrationApplyAdapter:
    """HTTP reconciliation plus digest-selected full-bank archive imports."""

    IMPORT_KINDS = frozenset({"import_bank", "migrate_bank", "replace_canonical_bank"})

    def __init__(self, *, data_plane: Any, admin: AdminMigrationAdapter,
                 archives: Mapping[str, str], restore_evidence: Mapping[str, Mapping[str, Any]],
                 rollback_archive: str, rollback_archive_digest: str,
                 rollback_restore_evidence_digest: str,
                 archive_verifier: Callable[[str, str], bool]) -> None:
        if not isinstance(admin, AdminMigrationAdapter):
            raise MigrationAdapterError("admin migration adapter is required")
        if not isinstance(archives, Mapping) or not isinstance(restore_evidence, Mapping):
            raise MigrationAdapterError("migration archive inputs are invalid")
        if not Path(rollback_archive).is_absolute() or not DIGEST.fullmatch(rollback_archive_digest):
            raise MigrationAdapterError("rollback archive binding is invalid")
        if (
            not isinstance(rollback_restore_evidence_digest, str)
            or DIGEST.fullmatch(rollback_restore_evidence_digest) is None
        ):
            raise MigrationAdapterError("rollback restore evidence binding is invalid")
        if not callable(archive_verifier):
            raise MigrationAdapterError("rollback archive verifier is required")
        self.data_plane = data_plane
        self.admin = admin
        self.archives = dict(archives)
        self.restore_evidence = {
            key: dict(value) if isinstance(value, Mapping) else value
            for key, value in restore_evidence.items()
        }
        self.rollback_archive = rollback_archive
        self.rollback_archive_digest = rollback_archive_digest
        self.rollback_restore_evidence_digest = rollback_restore_evidence_digest
        self.archive_verifier = archive_verifier
        self._rollback_ids: set[str] = set()

    def _require_archive_digest(self, archive: str, archive_digest: str) -> None:
        try:
            verified = self.archive_verifier(archive, archive_digest)
        except Exception:
            verified = False
        if verified is not True:
            raise MigrationAdapterError("archive digest does not match plan")

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
        target_bank = action.details.get("target_bank")
        if not isinstance(target_bank, Mapping):
            raise MigrationAdapterError("migration target bank is unavailable")
        self._require_archive_digest(archive, archive_digest)
        try:
            with verified_file_snapshot(
                archive, "migration archive", archive_digest,
            ) as snapshot:
                self.admin.import_bank(
                    snapshot, archive_digest, target_bank.get("bank_id"),
                    action.details.get("restore_evidence_digest"), evidence,
                )
        except FileEvidenceError:
            raise MigrationAdapterError(
                "migration archive snapshot verification failed"
            ) from None

    def create_rollback_bundle(self, plan_digest: str, action_ids: tuple[str, ...]) -> Any:
        self.admin.backup(self.rollback_archive, self.rollback_archive_digest)
        self._require_archive_digest(
            self.rollback_archive, self.rollback_archive_digest,
        )
        bundle = self.data_plane.create_rollback_bundle(plan_digest, action_ids)
        self._rollback_ids.add(bundle.rollback_id)
        return bundle

    def verify_rollback_bundle(self, rollback: Any) -> bool:
        if rollback.rollback_id not in self._rollback_ids:
            return False
        evidence = self.restore_evidence.get(self.rollback_archive_digest)
        try:
            AdminMigrationAdapter._restore_evidence(
                evidence,
                self.rollback_archive_digest,
                self.rollback_restore_evidence_digest,
            )
        except MigrationAdapterError:
            return False
        return self.data_plane.verify_rollback_bundle(rollback)

    def restore(self, rollback: Any) -> None:
        if rollback.rollback_id not in self._rollback_ids:
            raise MigrationAdapterError("rollback bundle is not bound to the migration adapter")
        evidence = self.restore_evidence.get(self.rollback_archive_digest)
        self._require_archive_digest(
            self.rollback_archive, self.rollback_archive_digest,
        )
        try:
            with verified_file_snapshot(
                self.rollback_archive,
                "rollback archive",
                self.rollback_archive_digest,
            ) as snapshot:
                self.admin.restore(
                    snapshot,
                    self.rollback_archive_digest,
                    self.rollback_restore_evidence_digest,
                    evidence,
                )
        except FileEvidenceError:
            raise MigrationAdapterError(
                "rollback archive snapshot verification failed"
            ) from None
        self.data_plane.restore(rollback)
