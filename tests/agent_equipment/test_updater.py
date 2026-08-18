from __future__ import annotations

import json
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import override
from unittest.mock import patch

from agent_equipment import updater
from agent_equipment.canonical import canonical_json_bytes, canonical_json_sha256
from agent_equipment.model import (
    Catalog,
    FrozenJsonObject,
    ResolvedLock,
    ValidatedCatalogLock,
    freeze_json,
    thaw_json,
)
from agent_equipment.source_resolution import (
    MAX_SOURCE_FIELD_CHARACTERS,
    SourceResolutionRequest,
)
from agent_equipment.updater import propose_update
from agent_equipment.validator import validate_catalog_lock

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/agent-equipment/schema"
CATALOG = ROOT / "home/dot_config/agent-equipment/catalog-v1.json"
LOCK = ROOT / "home/dot_config/agent-equipment/lock-v1.json"


def frozen_object(document: object) -> FrozenJsonObject:
    frozen = freeze_json(document)
    if not isinstance(frozen, FrozenJsonObject):
        raise TypeError("fixture must be an object")
    return frozen


def validated_pair(catalog_path: Path, lock_path: Path) -> ValidatedCatalogLock:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    validation = validate_catalog_lock(catalog, lock)
    if validation.model is None:
        raise AssertionError(validation.diagnostics)
    return validation.model


def fixture_pair() -> ValidatedCatalogLock:
    return validated_pair(
        FIXTURES / "valid-catalog.json",
        FIXTURES / "valid-lock.json",
    )


def manifest_for(
    base: ValidatedCatalogLock,
    distribution_identity: str,
) -> dict[str, object]:
    distributions = thaw_json(base.lock.document["distributions"])
    if not isinstance(distributions, list):
        raise TypeError("fixture distributions must be a list")
    matches = [
        item
        for item in distributions
        if isinstance(item, dict)
        and item.get("distribution_identity") == distribution_identity
    ]
    if len(matches) != 1:
        raise ValueError("fixture distribution must resolve exactly once")
    return matches[0]


def facts_for_manifest(manifest: dict[str, object]) -> FrozenJsonObject:
    source = manifest.get("source")
    resolved_source = manifest.get("resolved_source")
    restore = manifest.get("restore")
    available = manifest.get("available_equipment")
    if (
        not isinstance(source, dict)
        or not isinstance(resolved_source, dict)
        or not isinstance(restore, dict)
        or not isinstance(available, list)
    ):
        raise TypeError("fixture source-manifest evidence must be complete")
    if source.get("kind") == "git":
        return frozen_object(
            {
                "kind": "git",
                "revision": resolved_source["revision"],
                "content_digest": restore["content_digest"],
                "available_equipment": available,
            }
        )
    return frozen_object(
        {
            "kind": "native_manager",
            "version": resolved_source["version"],
            "available_equipment": available,
        }
    )


def advanced_git_facts(
    base: ValidatedCatalogLock,
    distribution_identity: str,
    *,
    equipment: tuple[str, ...] | None = None,
) -> FrozenJsonObject:
    manifest = manifest_for(base, distribution_identity)
    available = manifest.get("available_equipment")
    if not isinstance(available, list):
        raise TypeError("fixture available equipment must be a list")
    return frozen_object(
        {
            "kind": "git",
            "revision": "89abcdef0123456789abcdef0123456789abcdef",
            "content_digest": f"sha256:{'3' * 64}",
            "available_equipment": list(equipment)
            if equipment is not None
            else available,
        }
    )


def advanced_native_facts(
    base: ValidatedCatalogLock,
    distribution_identity: str,
    *,
    version: str,
) -> FrozenJsonObject:
    manifest = manifest_for(base, distribution_identity)
    source = manifest.get("source")
    available = manifest.get("available_equipment")
    if not isinstance(source, dict) or not isinstance(available, list):
        raise TypeError("fixture native source evidence must be complete")
    manager = source.get("manager")
    if manager == "codex":
        typed_version = {"kind": "revision", "value": version}
    elif manager == "http":
        typed_version = {"kind": "static_source"}
    else:
        typed_version = {"kind": "semantic_version", "value": version}
    return frozen_object(
        {
            "kind": "native_manager",
            "version": typed_version,
            "available_equipment": available,
        }
    )


class FixtureSourceResolver:
    def __init__(
        self,
        facts: dict[str, FrozenJsonObject],
        *,
        fail_identity: str | None = None,
    ) -> None:
        self._facts = facts
        self._fail_identity = fail_identity
        self.requests: list[SourceResolutionRequest] = []

    def resolve(self, request: SourceResolutionRequest) -> FrozenJsonObject:
        self.requests.append(request)
        if request.distribution_identity == self._fail_identity:
            raise RuntimeError("fixture source resolution failed")
        facts = self._facts[request.distribution_identity]
        payload = {
            "schema_version": "source-resolution-facts/v1",
            "request_digest": request.request_digest,
            "facts": thaw_json(facts),
        }
        return frozen_object(
            payload | {"resolution_digest": canonical_json_sha256(payload)}
        )


def proposed_pair(proposal: FrozenJsonObject) -> tuple[object, object]:
    result = thaw_json(proposal)
    if not isinstance(result, dict):
        raise TypeError("proposal must be an object")
    return result["catalog"], result["lock"]


class UpdateProposalTest(unittest.TestCase):
    def test_update_rejects_an_npx_package_selector_before_resolution(self) -> None:
        base = validated_pair(CATALOG, LOCK)
        identity = "distribution:firecrawl/direct-mcp"
        invalid_package = "firecrawl-mcp@beta"
        catalog_payload = thaw_json(base.catalog.document)
        lock_payload = thaw_json(base.lock.document)
        assert isinstance(catalog_payload, dict)
        assert isinstance(lock_payload, dict)
        catalog_distribution = next(
            item
            for item in catalog_payload["distributions"]
            if item["identity"] == identity
        )
        catalog_distribution["source"]["package"] = invalid_package
        catalog_document = frozen_object(catalog_payload)
        catalog_digest = canonical_json_sha256(catalog_document)

        lock_manifest = next(
            item
            for item in lock_payload["distributions"]
            if item["distribution_identity"] == identity
        )
        lock_manifest["source"]["package"] = invalid_package
        manifest_payload = {
            key: value
            for key, value in lock_manifest.items()
            if key != "source_manifest_digest"
        }
        lock_manifest["source_manifest_digest"] = canonical_json_sha256(
            manifest_payload
        )
        lock_payload["catalog_digest"] = catalog_digest
        lock_document = frozen_object(lock_payload)
        forged_base = ValidatedCatalogLock(
            Catalog("catalog/v1", catalog_document, catalog_digest),
            ResolvedLock(
                "lock/v1",
                lock_document,
                canonical_json_sha256(lock_document),
            ),
            base.coverage,
        )

        class CountingResolver:
            def __init__(self) -> None:
                self.calls = 0

            def resolve(self, request: SourceResolutionRequest) -> FrozenJsonObject:
                del request
                self.calls += 1
                raise AssertionError("invalid source must not reach resolution")

        resolver = CountingResolver()
        with self.assertRaises(ValueError):
            propose_update(
                forged_base,
                frozen_object({"distribution": identity}),
                resolver,
            )
        self.assertEqual(resolver.calls, 0)

    def test_update_rejects_an_overlong_reviewed_artifact_subpath_at_admission(
        self,
    ) -> None:
        base = fixture_pair()
        identity = "distribution:example/bundle"
        lock_payload = thaw_json(base.lock.document)
        assert isinstance(lock_payload, dict)
        manifest = next(
            item
            for item in lock_payload["distributions"]
            if item["distribution_identity"] == identity
        )
        source = manifest["source"]
        resolved_source = manifest["resolved_source"]
        restore = manifest["restore"]
        assert isinstance(source, dict)
        assert isinstance(resolved_source, dict)
        assert isinstance(restore, dict)
        repository = source["repository"]
        revision = resolved_source["revision"]
        assert isinstance(repository, str)
        assert isinstance(revision, str)
        restore["artifact_ref"] = f"git+{repository}@{revision}#" + "a" * (
            MAX_SOURCE_FIELD_CHARACTERS + 1
        )
        manifest_payload = {
            key: value
            for key, value in manifest.items()
            if key != "source_manifest_digest"
        }
        manifest["source_manifest_digest"] = canonical_json_sha256(manifest_payload)
        lock_document = frozen_object(lock_payload)
        forged_base = ValidatedCatalogLock(
            base.catalog,
            ResolvedLock(
                "lock/v1",
                lock_document,
                canonical_json_sha256(lock_document),
            ),
            base.coverage,
        )
        resolver = FixtureSourceResolver({identity: advanced_git_facts(base, identity)})

        with self.assertRaisesRegex(
            ValueError,
            "^update source resolution failed$",
        ):
            propose_update(
                forged_base,
                frozen_object({"distribution": identity}),
                resolver,
            )
        self.assertEqual(len(resolver.requests), 1)

    def test_update_normalizes_valid_distribution_array_order(self) -> None:
        canonical_catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        canonical_lock = json.loads(LOCK.read_text(encoding="utf-8"))
        reordered_catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        reordered_lock = json.loads(LOCK.read_text(encoding="utf-8"))
        for field in (
            "distributions",
            "coverage_templates",
            "equipment",
            "retirements",
        ):
            reordered_catalog[field].reverse()
        for field in (
            "distributions",
            "source_manifest_history",
            "coverage",
            "retirements",
        ):
            reordered_lock[field].reverse()
        reordered_lock["catalog_digest"] = canonical_json_sha256(reordered_catalog)

        def proposal_for(
            catalog: object,
            lock: object,
        ) -> tuple[object, object, tuple[str, ...]]:
            validation = validate_catalog_lock(catalog, lock)
            self.assertIsNotNone(validation.model, validation.diagnostics)
            assert validation.model is not None
            facts = {
                item["distribution_identity"]: facts_for_manifest(item)
                for item in thaw_json(validation.model.lock.document["distributions"])
            }
            resolver = FixtureSourceResolver(facts)
            proposal = propose_update(
                validation.model,
                frozen_object({"all": True}),
                resolver,
            )
            proposed_catalog, proposed_lock = proposed_pair(proposal)
            proposed_validation = validate_catalog_lock(
                proposed_catalog,
                proposed_lock,
            )
            self.assertIsNotNone(
                proposed_validation.model,
                proposed_validation.diagnostics,
            )
            return (
                proposed_catalog,
                proposed_lock,
                tuple(request.distribution_identity for request in resolver.requests),
            )

        canonical_proposal = proposal_for(canonical_catalog, canonical_lock)
        reordered_proposal = proposal_for(reordered_catalog, reordered_lock)

        self.assertEqual(
            canonical_json_bytes(canonical_proposal[0]),
            canonical_json_bytes(reordered_proposal[0]),
        )
        self.assertEqual(
            canonical_json_bytes(canonical_proposal[1]),
            canonical_json_bytes(reordered_proposal[1]),
        )
        self.assertEqual(canonical_proposal[2], tuple(sorted(canonical_proposal[2])))
        self.assertEqual(reordered_proposal[2], canonical_proposal[2])

    def test_all_no_op_resolution_round_trips_every_production_source_kind(
        self,
    ) -> None:
        base = validated_pair(CATALOG, LOCK)
        facts = {
            item["distribution_identity"]: facts_for_manifest(item)
            for item in thaw_json(base.lock.document["distributions"])
        }

        proposal = propose_update(
            base,
            frozen_object({"all": True}),
            FixtureSourceResolver(facts),
        )
        catalog, lock = proposed_pair(proposal)

        self.assertEqual(catalog, thaw_json(base.catalog.document))
        self.assertEqual(lock, thaw_json(base.lock.document))
        validation = validate_catalog_lock(catalog, lock)
        self.assertIsNotNone(validation.model, validation.diagnostics)

    def test_update_emits_one_valid_atomic_full_pair_without_orphan_history(
        self,
    ) -> None:
        base = fixture_pair()
        identity = "distribution:example/bundle"
        old_catalog = base.catalog.document
        old_lock = base.lock.document
        facts = advanced_git_facts(base, identity)

        proposal = propose_update(
            base,
            frozen_object({"distribution": identity}),
            FixtureSourceResolver({identity: facts}),
        )
        catalog, lock = proposed_pair(proposal)
        validation = validate_catalog_lock(catalog, lock)

        self.assertIsNotNone(validation.model, validation.diagnostics)
        self.assertEqual(lock["source_manifest_history"], [])  # type: ignore[index]
        self.assertNotEqual(catalog, thaw_json(old_catalog))
        self.assertEqual(base.catalog.document, old_catalog)
        self.assertEqual(base.lock.document, old_lock)
        result = thaw_json(proposal)
        assert isinstance(result, dict)
        self.assertEqual(result["catalog_digest"], canonical_json_sha256(catalog))
        self.assertEqual(result["lock_digest"], canonical_json_sha256(lock))

    def test_source_wide_update_expands_complete_membership_and_coverage(self) -> None:
        base = fixture_pair()
        identity = "distribution:example/bundle"
        equipment = ("skill:example/grilling", "skill:example/new")
        facts = advanced_git_facts(
            base,
            identity,
            equipment=equipment,
        )

        proposal = propose_update(
            base,
            frozen_object({"distribution": identity}),
            FixtureSourceResolver({identity: facts}),
        )
        catalog, lock = proposed_pair(proposal)
        validation = validate_catalog_lock(catalog, lock)

        self.assertIsNotNone(validation.model, validation.diagnostics)
        coverage = lock["coverage"]  # type: ignore[index]
        self.assertEqual(
            [
                item["harness"]
                for item in coverage
                if item["equipment_identity"] == "skill:example/new"
            ],
            ["claude", "codex", "cursor"],
        )

    def test_update_preserves_only_retirement_referenced_old_manifest(self) -> None:
        base = validated_pair(CATALOG, LOCK)
        identity = "distribution:chrome-devtools/direct-mcp"
        old_manifest = manifest_for(base, identity)
        old_restore = old_manifest["restore"]
        assert isinstance(old_restore, dict)
        facts = advanced_native_facts(base, identity, version="1.8.0")

        proposal = propose_update(
            base,
            frozen_object({"distribution": identity}),
            FixtureSourceResolver({identity: facts}),
        )
        catalog, lock = proposed_pair(proposal)
        validation = validate_catalog_lock(catalog, lock)

        self.assertIsNotNone(validation.model, validation.diagnostics)
        self.assertIn(old_manifest, lock["source_manifest_history"])  # type: ignore[operator,index]
        referenced_history = {
            item["source_manifest_digest"]
            for item in lock["source_manifest_history"]  # type: ignore[index]
        }
        current_digests = {
            item["source_manifest_digest"]
            for item in lock["distributions"]  # type: ignore[index]
        }
        expected = {
            item["source_manifest_digest"]
            for item in lock["retirements"]  # type: ignore[index]
        } - current_digests
        self.assertEqual(referenced_history, expected)
        current_manifest = next(
            item
            for item in lock["distributions"]  # type: ignore[index]
            if item["distribution_identity"] == identity
        )
        current_restore = current_manifest["restore"]
        self.assertEqual(
            current_restore["observation_source"],
            old_restore["observation_source"],
        )
        self.assertEqual(
            current_restore["native_update_control"],
            old_restore["native_update_control"],
        )

    def test_update_rejects_an_opaque_resolver_value_before_proposal_emission(
        self,
    ) -> None:
        base = validated_pair(CATALOG, LOCK)
        identity = "distribution:chrome-devtools/direct-mcp"
        manifest = manifest_for(base, identity)
        available = manifest["available_equipment"]
        assert isinstance(available, list)
        canary = "V7pOpaquePrivateValue9Qx"
        facts = frozen_object(
            {
                "kind": "native_manager",
                "version": {"kind": "semantic_version", "value": canary},
                "available_equipment": available,
            }
        )

        with self.assertRaises(ValueError) as raised:
            propose_update(
                base,
                frozen_object({"distribution": identity}),
                FixtureSourceResolver({identity: facts}),
            )

        self.assertNotIn(canary, str(raised.exception))

    def test_update_redacts_a_resolver_system_exit_at_the_port(self) -> None:
        base = fixture_pair()
        identity = "distribution:example/bundle"
        canary = "V7pOpaquePrivateValue9Qx"

        class ExitingResolver:
            def resolve(self, request: SourceResolutionRequest) -> FrozenJsonObject:
                del request
                raise SystemExit(canary)

        with self.assertRaisesRegex(
            ValueError,
            "^update source resolution failed$",
        ) as raised:
            propose_update(
                base,
                frozen_object({"distribution": identity}),
                ExitingResolver(),
            )

        self.assertNotIn(canary, str(raised.exception))

    def test_update_redacts_a_delayed_resolver_system_exit_during_admission(
        self,
    ) -> None:
        base = fixture_pair()
        identity = "distribution:example/bundle"
        canary = "V7pDelayedExitPrivate9Qx"

        class DelayedExitDocument(FrozenJsonObject):
            @override
            def __iter__(self) -> Iterator[str]:
                raise SystemExit(canary)

        class DelayedExitResolver:
            def resolve(self, request: SourceResolutionRequest) -> FrozenJsonObject:
                del request
                return DelayedExitDocument(())

        with self.assertRaisesRegex(
            ValueError,
            "^update source resolution failed$",
        ) as raised:
            propose_update(
                base,
                frozen_object({"distribution": identity}),
                DelayedExitResolver(),
            )

        self.assertNotIn(canary, str(raised.exception))

    def test_update_rejects_disappearing_active_equipment_without_retirement(
        self,
    ) -> None:
        base = fixture_pair()
        identity = "distribution:example/bundle"
        replacement = advanced_git_facts(
            base,
            identity,
            equipment=("skill:example/replacement",),
        )

        with self.assertRaisesRegex(ValueError, "disappearing active equipment"):
            propose_update(
                base,
                frozen_object({"distribution": identity}),
                FixtureSourceResolver({identity: replacement}),
            )

    def test_all_update_is_deterministic_and_failure_is_atomic(self) -> None:
        base = fixture_pair()
        git_identity = "distribution:example/bundle"
        native_identity = "distribution:example/native-plugin"
        facts = {
            git_identity: advanced_git_facts(base, git_identity),
            native_identity: advanced_native_facts(
                base,
                native_identity,
                version="1.3.0",
            ),
        }
        selection = frozen_object({"all": True})

        first_resolver = FixtureSourceResolver(facts)
        second_resolver = FixtureSourceResolver(facts)
        first = propose_update(base, selection, first_resolver)
        second = propose_update(base, selection, second_resolver)

        self.assertEqual(first, second)
        expected_order = (git_identity, native_identity)
        self.assertEqual(
            tuple(request.distribution_identity for request in first_resolver.requests),
            expected_order,
        )

        original_catalog = base.catalog.document
        original_lock = base.lock.document
        failing = FixtureSourceResolver(
            facts,
            fail_identity=native_identity,
        )
        with self.assertRaisesRegex(ValueError, "^update source resolution failed$"):
            propose_update(base, selection, failing)
        self.assertEqual(base.catalog.document, original_catalog)
        self.assertEqual(base.lock.document, original_lock)

    def test_complete_proposal_is_subject_to_the_output_byte_bound(self) -> None:
        base = fixture_pair()
        identity = "distribution:example/bundle"
        resolver = FixtureSourceResolver({identity: advanced_git_facts(base, identity)})

        with (
            patch.object(updater, "MAX_UPDATE_PROPOSAL_BYTES", 1),
            self.assertRaisesRegex(ValueError, "proposal exceeds its byte bound"),
        ):
            propose_update(
                base,
                frozen_object({"distribution": identity}),
                resolver,
            )


if __name__ == "__main__":
    unittest.main()
