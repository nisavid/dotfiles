from __future__ import annotations

import math
import unittest
from collections.abc import Mapping
from dataclasses import FrozenInstanceError

from agent_equipment.model import (
    Catalog,
    CatalogLockValidation,
    CoverageRecord,
    Diagnostic,
    FrozenJsonObject,
    InstalledFile,
    InstalledImplementationManifest,
    ResolvedLock,
    ValidatedCatalogLock,
    _installed_implementation_digest,
    freeze_json,
    thaw_json,
)

CATALOG_DIGEST = (
    "sha256:e7cf969bd6cf82bfaec548d58743f9f4c56e670afff2556d1ebc182b1708b05b"
)
MANIFEST_PATHS = (
    "bin/agent-equipment",
    "lib/agent-equipment/agent_equipment/__init__.py",
    "lib/agent-equipment/agent_equipment/_json_schema.py",
    "lib/agent-equipment/agent_equipment/canonical.py",
    "lib/agent-equipment/agent_equipment/inventory.py",
    "lib/agent-equipment/agent_equipment/model.py",
    "lib/agent-equipment/agent_equipment/resolver.py",
    "lib/agent-equipment/agent_equipment/secrets.py",
    "lib/agent-equipment/agent_equipment/validator.py",
    "lib/agent-equipment/schemas/acceptance-evidence-v1.schema.json",
    "lib/agent-equipment/schemas/adapter-contract-v1.schema.json",
    "lib/agent-equipment/schemas/captured-state-v1.schema.json",
    "lib/agent-equipment/schemas/catalog-v1.schema.json",
    "lib/agent-equipment/schemas/execution-authority-v1.schema.json",
    "lib/agent-equipment/schemas/lock-v1.schema.json",
    "lib/agent-equipment/schemas/plan-action-set-v1.schema.json",
)


def manifest_files() -> tuple[InstalledFile, ...]:
    return tuple(
        InstalledFile(path, f"sha256:{index:064x}")
        for index, path in enumerate(MANIFEST_PATHS, start=1)
    )


def installed_manifest(
    *,
    schema_version: str = "agent-equipment-installed-implementation/v1",
    runtime_identity: str = "cpython:3.12.8",
    files: tuple[InstalledFile, ...] | None = None,
) -> InstalledImplementationManifest:
    installed_files = manifest_files() if files is None else files
    runtime_digest = "sha256:" + "f" * 64
    return InstalledImplementationManifest(
        schema_version=schema_version,
        runtime_identity=runtime_identity,
        runtime_executable_digest=runtime_digest,
        files=installed_files,
        digest=_installed_implementation_digest(
            schema_version,
            runtime_identity,
            runtime_digest,
            installed_files,
        ),
    )


class ImmutableJsonTest(unittest.TestCase):
    def test_freeze_json_recursively_detaches_and_immutabilizes_json(self) -> None:
        source = {"outer": [{"b": 2, "a": "value"}]}

        frozen = freeze_json(source)
        source["outer"][0]["a"] = "changed"

        self.assertIsInstance(frozen, Mapping)
        assert isinstance(frozen, FrozenJsonObject)
        self.assertEqual(
            thaw_json(frozen),
            {"outer": [{"a": "value", "b": 2}]},
        )
        with self.assertRaises(TypeError):
            frozen["outer"] = ()  # type: ignore[index]
        outer = frozen["outer"]
        assert isinstance(outer, tuple)
        nested = outer[0]
        assert isinstance(nested, FrozenJsonObject)
        with self.assertRaises(TypeError):
            nested["a"] = "changed"  # type: ignore[index]

    def test_freeze_json_rejects_values_outside_closed_json(self) -> None:
        for value in (
            b"bytes",
            {"set"},
            {1: "non-string key"},
            "\ud800",
            math.nan,
            math.inf,
            -math.inf,
        ):
            with (
                self.subTest(value=repr(value)),
                self.assertRaises((TypeError, ValueError)),
            ):
                freeze_json(value)

    def test_catalog_lock_models_are_typed_slotted_and_frozen(self) -> None:
        catalog_document = freeze_json({"schema_version": "catalog/v1"})
        lock_document = freeze_json(
            {
                "schema_version": "lock/v1",
                "catalog_digest": CATALOG_DIGEST,
                "coverage": [
                    {
                        "equipment_identity": "skill:example",
                        "harness": "codex",
                        "record": {},
                    }
                ],
            }
        )
        self.assertIsInstance(catalog_document, Mapping)
        self.assertIsInstance(lock_document, Mapping)
        assert isinstance(catalog_document, FrozenJsonObject)
        assert isinstance(lock_document, FrozenJsonObject)
        catalog = Catalog(
            "catalog/v1",
            catalog_document,
            CATALOG_DIGEST,
        )
        lock = ResolvedLock(
            "lock/v1",
            lock_document,
            "sha256:c7d25693bb2dccb80d79c6a09ee62c563f994bcb675ad58e71d411a0f1e5fb49",
        )
        coverage_document = freeze_json({})
        self.assertIsInstance(coverage_document, FrozenJsonObject)
        assert isinstance(coverage_document, FrozenJsonObject)
        coverage = CoverageRecord("skill:example", "codex", coverage_document)
        validated = ValidatedCatalogLock(catalog, lock, (coverage,))

        result = CatalogLockValidation(validated, ())

        self.assertIs(result.model, validated)
        self.assertEqual(result.diagnostics, ())
        self.assertFalse(hasattr(result, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            result.model = None  # type: ignore[misc]
        diagnostic = Diagnostic("INVALID", "The pair is invalid.")
        with self.assertRaises(ValueError):
            CatalogLockValidation(validated, (diagnostic,))
        with self.assertRaises(ValueError):
            CatalogLockValidation(None, ())

    def test_diagnostic_requires_code_and_message_but_accepts_missing_context(
        self,
    ) -> None:
        for code, message in ((None, "message"), ("CODE", None)):
            with (
                self.subTest(code=code, message=message),
                self.assertRaises(TypeError),
            ):
                Diagnostic(code, message)  # type: ignore[arg-type]

        self.assertEqual(
            Diagnostic("CODE", "message"),
            Diagnostic(
                "CODE",
                "message",
                equipment_identity=None,
                harness=None,
                route_identity=None,
            ),
        )

    def test_public_model_constructors_reject_mutable_json_members(self) -> None:
        with self.assertRaises(TypeError):
            FrozenJsonObject((("mutable", []),))  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            Catalog(
                "catalog/v1",
                {"mutable": []},  # type: ignore[arg-type]
                "sha256:" + "1" * 64,
            )
        with self.assertRaises(TypeError):
            CatalogLockValidation(None, ({"mutable": []},))  # type: ignore[arg-type]

    def test_catalog_and_lock_reject_forged_document_digests(self) -> None:
        cases = (
            (Catalog, "catalog/v1", freeze_json({"schema_version": "catalog/v1"})),
            (ResolvedLock, "lock/v1", freeze_json({"schema_version": "lock/v1"})),
        )
        for model_type, schema_version, document in cases:
            for digest in ("invalid", "sha256:" + "0" * 64):
                with (
                    self.subTest(model=model_type.__name__, digest=digest),
                    self.assertRaises(ValueError),
                ):
                    model_type(
                        schema_version,
                        document,  # type: ignore[arg-type]
                        digest,
                    )

    def test_public_models_reject_contradictory_schema_and_lock_bindings(self) -> None:
        catalog_document = freeze_json({"schema_version": "catalog/v1"})
        lock_document = freeze_json(
            {
                "schema_version": "lock/v1",
                "catalog_digest": "sha256:" + "0" * 64,
                "coverage": [],
            }
        )
        assert isinstance(catalog_document, FrozenJsonObject)
        assert isinstance(lock_document, FrozenJsonObject)

        with self.assertRaises(ValueError):
            Catalog("lock/v1", catalog_document, CATALOG_DIGEST)
        with self.assertRaises(ValueError):
            ResolvedLock(
                "catalog/v1",
                lock_document,
                "sha256:f690d300b967ce274d9542580bb7c8b738fc3f546170134716f6174994c8ed14",
            )

        catalog = Catalog("catalog/v1", catalog_document, CATALOG_DIGEST)
        lock = ResolvedLock(
            "lock/v1",
            lock_document,
            "sha256:f690d300b967ce274d9542580bb7c8b738fc3f546170134716f6174994c8ed14",
        )
        with self.assertRaises(ValueError):
            ValidatedCatalogLock(catalog, lock, ())

    def test_validated_model_rejects_unsorted_duplicate_or_incomplete_coverage(
        self,
    ) -> None:
        catalog_document = freeze_json({"schema_version": "catalog/v1"})
        lock_document = freeze_json(
            {
                "schema_version": "lock/v1",
                "catalog_digest": CATALOG_DIGEST,
                "coverage": [
                    {
                        "equipment_identity": "skill:a",
                        "harness": "codex",
                        "record": {},
                    },
                    {
                        "equipment_identity": "skill:b",
                        "harness": "codex",
                        "record": {},
                    },
                ],
            }
        )
        assert isinstance(catalog_document, FrozenJsonObject)
        assert isinstance(lock_document, FrozenJsonObject)
        catalog = Catalog("catalog/v1", catalog_document, CATALOG_DIGEST)
        lock = ResolvedLock(
            "lock/v1",
            lock_document,
            "sha256:e17a08d86eaf56b9cce936f31b9e4f9702ffed9fc5a1e5b1ae910d5d5466b428",
        )
        empty_record = freeze_json({})
        assert isinstance(empty_record, FrozenJsonObject)
        first = CoverageRecord("skill:a", "codex", empty_record)
        second = CoverageRecord("skill:b", "codex", empty_record)

        for coverage in ((second, first), (first, first), (first,)):
            with self.subTest(coverage=coverage), self.assertRaises(ValueError):
                ValidatedCatalogLock(catalog, lock, coverage)

    def test_installed_manifest_exposes_a_closed_immutable_digest_payload(self) -> None:
        manifest = installed_manifest()

        document = manifest.as_json()

        self.assertEqual(
            thaw_json(document),
            {
                "files": [
                    {"digest": f"sha256:{index:064x}", "path": path}
                    for index, path in enumerate(MANIFEST_PATHS, start=1)
                ],
                "runtime_executable_digest": "sha256:" + "f" * 64,
                "runtime_identity": "cpython:3.12.8",
                "schema_version": "agent-equipment-installed-implementation/v1",
            },
        )
        self.assertNotIn("digest", document)
        with self.assertRaises(TypeError):
            document["files"][0]["path"] = "changed"  # type: ignore[index]

    def test_installed_manifest_rejects_false_runtime_or_inventory(self) -> None:
        for runtime_identity in ("pypy:3.12.8", "cpython:3.11.9", ""):
            with (
                self.subTest(runtime_identity=runtime_identity),
                self.assertRaises(ValueError),
            ):
                installed_manifest(runtime_identity=runtime_identity)

        for files in ((), manifest_files()[:-1], manifest_files()[::-1]):
            with self.subTest(files=files), self.assertRaises(ValueError):
                installed_manifest(files=files)

        with self.assertRaises(ValueError):
            installed_manifest(
                schema_version="agent-equipment-installed-implementation/v2"
            )

    def test_installed_manifest_rejects_malformed_or_forged_digests(self) -> None:
        for digest in (
            "not-a-digest",
            "sha256:" + "A" * 64,
            "sha256:" + "0" * 63,
        ):
            with self.subTest(file_digest=digest), self.assertRaises(ValueError):
                InstalledFile("agent_equipment/model.py", digest)

        with self.assertRaises(ValueError):
            InstalledImplementationManifest(
                schema_version="agent-equipment-installed-implementation/v1",
                runtime_identity="cpython:3.12.8",
                runtime_executable_digest="invalid",
                files=(),
                digest="sha256:" + "0" * 64,
            )

        with self.assertRaises(ValueError):
            InstalledImplementationManifest(
                schema_version="agent-equipment-installed-implementation/v1",
                runtime_identity="cpython:3.12.8",
                runtime_executable_digest="sha256:" + "1" * 64,
                files=(),
                digest="invalid",
            )

        with self.assertRaises(ValueError):
            InstalledImplementationManifest(
                schema_version="agent-equipment-installed-implementation/v1",
                runtime_identity="cpython:3.12.8",
                runtime_executable_digest="sha256:" + "1" * 64,
                files=manifest_files(),
                digest="sha256:" + "0" * 64,
            )


if __name__ == "__main__":
    unittest.main()
