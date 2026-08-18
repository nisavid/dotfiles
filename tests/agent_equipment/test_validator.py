from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "home/private_dot_local/lib/agent-equipment"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from agent_equipment import validator
from agent_equipment.canonical import canonical_json_bytes, canonical_json_sha256
from agent_equipment.model import CatalogLockValidation, thaw_json
from agent_equipment.source_resolution import (
    MAX_AVAILABLE_EQUIPMENT,
    MAX_SOURCE_FIELD_CHARACTERS,
    MAX_SOURCE_RESOLUTION_BYTES,
)
from agent_equipment.validator import load_catalog_lock, validate_catalog_lock

DOCUMENTS = ROOT / "docs/agent-equipment"
CATALOG = DOCUMENTS / "initial-catalog.proposed.json"
LOCK = DOCUMENTS / "initial-lock.proposed.json"
FIXTURES = ROOT / "tests/fixtures/agent-equipment/schema"


def patterned_value(prefix: str, length: int) -> str:
    if length < len(prefix):
        raise ValueError("fixture length is shorter than its prefix")
    return prefix + "a" * (length - len(prefix))


def public_git_repository(length: int) -> str:
    prefix = "https://example.invalid/"
    suffix = ".git"
    if length < len(prefix) + len(suffix) + 1:
        raise ValueError("fixture repository length is too short")
    return prefix + "a" * (length - len(prefix) - len(suffix)) + suffix


def source_manifest(
    lock: dict[str, object],
    distribution_identity: str,
) -> dict[str, object]:
    return next(
        item
        for item in lock["distributions"]
        if item["distribution_identity"] == distribution_identity
    )


def reseal_source_manifest(manifest: dict[str, object]) -> None:
    available = sorted(set(manifest["available_equipment"]))
    selected = sorted(set(manifest["equipment"]))
    manifest["available_equipment"] = available
    manifest["equipment"] = selected
    manifest["membership_evidence"] = {
        "kind": "authoritative_source_listing",
        "evidence_digest": canonical_json_sha256({"available_equipment": available}),
    }
    payload = deepcopy(manifest)
    payload.pop("source_manifest_digest")
    manifest["source_manifest_digest"] = canonical_json_sha256(payload)


def retirement_manifest_digest(
    lock: dict[str, object],
    route: dict[str, object],
) -> str:
    manifest = source_manifest(lock, route["distribution"])
    return manifest["source_manifest_digest"]


class CatalogLockValidatorTests(unittest.TestCase):
    def fixture_pair(self) -> tuple[dict[str, object], dict[str, object]]:
        return (
            json.loads((FIXTURES / "valid-catalog.json").read_text(encoding="utf-8")),
            json.loads((FIXTURES / "valid-lock.json").read_text(encoding="utf-8")),
        )

    def bind_catalog_digest(
        self,
        catalog: dict[str, object],
        lock: dict[str, object],
    ) -> None:
        lock["catalog_digest"] = canonical_json_sha256(catalog)

    def test_installed_validator_exposes_only_the_no_plan_api(self) -> None:
        self.assertEqual(
            validator.__all__,
            ("load_catalog_lock", "validate_catalog_lock"),
        )
        for legacy_name in (
            "CoverageEntry",
            "PlannedOperation",
            "DesignValidationResult",
            "load_and_validate",
            "validate_design",
        ):
            with self.subTest(name=legacy_name):
                self.assertFalse(hasattr(validator, legacy_name))

    def test_public_validation_does_not_construct_a_mutation_plan(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        lock = json.loads(LOCK.read_text(encoding="utf-8"))

        with patch.object(
            validator,
            "_construct_mutation_plan",
            side_effect=AssertionError("public validation constructed a mutation plan"),
        ):
            loaded = load_catalog_lock(CATALOG, LOCK)
            validated = validate_catalog_lock(catalog, lock)

        for result in (loaded, validated):
            self.assertEqual(result.diagnostics, ())
            self.assertIsNotNone(result.model)
            assert result.model is not None
            self.assertEqual(len(result.model.coverage), 132)

    def test_reviewed_proposal_returns_one_immutable_no_plan_model(self) -> None:
        result = load_catalog_lock(CATALOG, LOCK)

        self.assertIsInstance(result, CatalogLockValidation)
        self.assertEqual(result.diagnostics, ())
        self.assertIsNotNone(result.model)
        assert result.model is not None
        self.assertEqual(
            result.model.catalog.digest,
            "sha256:b580775ec1ea54029d8eda747dd98e49824de952ba326d344c6186e56cfee05d",
        )
        self.assertEqual(
            result.model.lock.digest,
            "sha256:1f493d7f74f249e65242fa45f340a23cf2ff8a26949b524ef269d78b76851a0a",
        )
        self.assertEqual(len(result.model.coverage), 132)
        self.assertEqual(
            len({entry.equipment_identity for entry in result.model.coverage}),
            44,
        )
        self.assertEqual(
            result.model.catalog.schema_version,
            "catalog/v1",
        )
        self.assertEqual(result.model.lock.schema_version, "lock/v1")
        self.assertFalse(hasattr(result, "mutation_plan"))
        self.assertFalse(hasattr(result.model, "mutation_plan"))

        detached = thaw_json(result.model.catalog.document)
        detached["schema_version"] = "changed"
        self.assertEqual(
            thaw_json(result.model.catalog.document)["schema_version"],
            "catalog/v1",
        )

    def test_git_branch_admission_matches_the_installed_schema(self) -> None:
        schema = json.loads(
            (validator.SCHEMA_DIRECTORY / "catalog-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        branch_pattern = schema["$defs"]["gitBranch"]["pattern"]

        for branch, expected in (
            ("main", True),
            ("release/v1.2.3", True),
            ("feature/source-manifests", True),
            ("HEAD", False),
            ("refs//heads/main", False),
            ("../other", False),
            ("--option", False),
            ("feature..branch", False),
            ("release.", False),
            ("release.lock", False),
            ("refs/heads/name.lock", False),
            ("feature/.hidden", False),
            ("feature\\escape", False),
            ("a" * MAX_SOURCE_FIELD_CHARACTERS, True),
            ("a" * (MAX_SOURCE_FIELD_CHARACTERS + 1), False),
        ):
            with self.subTest(branch=branch):
                schema_accepts = re.search(branch_pattern, branch) is not None
                self.assertEqual(schema_accepts, expected)
                self.assertEqual(
                    validator._git_branch_is_valid(branch),
                    expected,
                )

    def test_native_package_admission_is_manager_specific(self) -> None:
        maximum_package = "a" * 126 + "@" + "b" * 128
        over_limit_package = "a" * 127 + "@" + "b" * 128
        cases = (
            (
                {
                    "kind": "native_manager",
                    "manager": "npx",
                    "package": "tool",
                },
                True,
            ),
            (
                {
                    "kind": "native_manager",
                    "manager": "npx",
                    "package": "@example/tool",
                },
                True,
            ),
            (
                {
                    "kind": "native_manager",
                    "manager": "npx",
                    "package": "tool@beta",
                },
                False,
            ),
            (
                {
                    "kind": "native_manager",
                    "manager": "claude",
                    "package": "tool@reviewed-registry",
                },
                True,
            ),
            (
                {
                    "kind": "native_manager",
                    "manager": "codex",
                    "package": "tool@reviewed-registry",
                },
                True,
            ),
            (
                {
                    "kind": "native_manager",
                    "manager": "cursor",
                    "package": "tool@reviewed-registry",
                },
                True,
            ),
            (
                {
                    "kind": "native_manager",
                    "manager": "claude",
                    "package": maximum_package,
                },
                True,
            ),
            (
                {
                    "kind": "native_manager",
                    "manager": "claude",
                    "package": over_limit_package,
                },
                False,
            ),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(validator._catalog_source_is_valid(source), expected)

    def test_source_manifest_semantics_reject_invalid_resolution_evidence(
        self,
    ) -> None:
        cases: list[tuple[str, dict[str, object], dict[str, object], str]] = []

        catalog, lock = self.fixture_pair()
        source_manifest(lock, "distribution:example/bundle")[
            "source_manifest_digest"
        ] = "sha256:" + "0" * 64
        cases.append(
            ("stale manifest digest", catalog, lock, "LOCK_DISTRIBUTION_INVALID")
        )

        catalog, lock = self.fixture_pair()
        manifest = source_manifest(lock, "distribution:example/bundle")
        manifest["membership_evidence"]["evidence_digest"] = "sha256:" + "0" * 64
        payload = deepcopy(manifest)
        payload.pop("source_manifest_digest")
        manifest["source_manifest_digest"] = canonical_json_sha256(payload)
        cases.append(
            (
                "stale membership evidence",
                catalog,
                lock,
                "LOCK_DISTRIBUTION_INVALID",
            )
        )

        catalog, lock = self.fixture_pair()
        manifest = source_manifest(lock, "distribution:example/bundle")
        manifest["available_equipment"].append("skill:example/new")
        reseal_source_manifest(manifest)
        cases.append(
            (
                "incomplete source-wide selection",
                catalog,
                lock,
                "DISTRIBUTION_SELECTION_INVALID",
            )
        )

        catalog, lock = self.fixture_pair()
        manifest = source_manifest(lock, "distribution:example/bundle")
        manifest["equipment"].append("skill:example/not-available")
        reseal_source_manifest(manifest)
        cases.append(
            (
                "selected equipment absent from authoritative membership",
                catalog,
                lock,
                "LOCK_DISTRIBUTION_INVALID",
            )
        )

        catalog, lock = self.fixture_pair()
        manifest = source_manifest(lock, "distribution:example/native-plugin")
        manifest["resolved_source"]["version"] = {
            "kind": "revision",
            "value": "11c74d6b",
        }
        reseal_source_manifest(manifest)
        cases.append(
            (
                "resolved version kind differs from manager policy",
                catalog,
                lock,
                "LOCK_DISTRIBUTION_INVALID",
            )
        )

        for label, invalid_catalog, invalid_lock, expected_code in cases:
            with self.subTest(case=label):
                first = validate_catalog_lock(invalid_catalog, invalid_lock)
                second = validate_catalog_lock(invalid_catalog, invalid_lock)
                codes = {diagnostic.code for diagnostic in first.diagnostics}

                self.assertEqual(first, second)
                self.assertIsNone(first.model)
                self.assertIn(expected_code, codes)
                self.assertNotIn("CATALOG_SCHEMA_INVALID", codes)
                self.assertNotIn("LOCK_SCHEMA_INVALID", codes)

    def test_source_manifest_semantics_enforce_complete_string_bounds(self) -> None:
        _, lock = self.fixture_pair()
        baseline = source_manifest(lock, "distribution:example/bundle")
        source = baseline["source"]
        resolved_source = baseline["resolved_source"]
        restore = baseline["restore"]
        assert isinstance(source, dict)
        assert isinstance(resolved_source, dict)
        assert isinstance(restore, dict)
        repository = source["repository"]
        revision = resolved_source["revision"]
        assert isinstance(repository, str)
        assert isinstance(revision, str)
        artifact_prefix = f"git+{repository}@{revision}#"

        maximum = deepcopy(baseline)
        maximum["distribution_identity"] = patterned_value(
            "distribution:",
            MAX_SOURCE_FIELD_CHARACTERS,
        )
        maximum_equipment = patterned_value(
            "skill:",
            MAX_SOURCE_FIELD_CHARACTERS,
        )
        maximum["available_equipment"] = [maximum_equipment]
        maximum["equipment"] = [maximum_equipment]
        maximum["restore"]["artifact_ref"] = artifact_prefix + "a" * (
            MAX_SOURCE_FIELD_CHARACTERS - len(artifact_prefix)
        )
        reseal_source_manifest(maximum)
        self.assertTrue(validator._source_manifest_is_valid(maximum))

        over_limit = MAX_SOURCE_FIELD_CHARACTERS + 1
        for label in (
            "artifact_ref",
            "distribution_identity",
            "equipment_identity",
            "branch",
            "repository",
        ):
            invalid = deepcopy(baseline)
            invalid_source = invalid["source"]
            invalid_restore = invalid["restore"]
            assert isinstance(invalid_source, dict)
            assert isinstance(invalid_restore, dict)
            if label == "artifact_ref":
                invalid_restore["artifact_ref"] = artifact_prefix + "a" * over_limit
            elif label == "distribution_identity":
                invalid["distribution_identity"] = patterned_value(
                    "distribution:",
                    over_limit,
                )
            elif label == "equipment_identity":
                identity = patterned_value("skill:", over_limit)
                invalid["available_equipment"] = [identity]
                invalid["equipment"] = [identity]
            elif label == "branch":
                invalid_source["branch"] = "a" * over_limit
            else:
                oversized_repository = public_git_repository(over_limit)
                invalid_source["repository"] = oversized_repository
                invalid_restore["artifact_ref"] = (
                    f"git+{oversized_repository}@{revision}"
                )
            reseal_source_manifest(invalid)
            with self.subTest(field=label):
                self.assertFalse(validator._source_manifest_is_valid(invalid))

        native_restore = {
            "class": "native_rolling",
            "channel": "stable",
            "reviewed_baseline": "1.2.3",
            "observation_source": "reviewed plugin list",
            "native_update_control": "suppressible",
        }
        for field in ("channel", "reviewed_baseline"):
            with self.subTest(field=field):
                self.assertFalse(
                    validator._restore_is_valid(
                        native_restore | {field: "a" * over_limit}
                    )
                )

    def test_source_manifest_semantics_enforce_equipment_item_ceiling(self) -> None:
        identities = [
            f"other:source-limit/{index:05d}"
            for index in range(MAX_AVAILABLE_EQUIPMENT + 1)
        ]

        self.assertTrue(
            validator._source_manifest_equipment_is_valid(
                identities[:MAX_AVAILABLE_EQUIPMENT]
            )
        )
        self.assertFalse(validator._source_manifest_equipment_is_valid(identities))

    def test_persisted_source_manifest_enforces_canonical_byte_ceiling(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        distribution = next(
            item
            for item in catalog["distributions"]
            if "equipment" in item["selection"]
        )
        manifest = source_manifest(lock, distribution["identity"])
        long_identities = [
            patterned_value("other:a", MAX_SOURCE_FIELD_CHARACTERS - 5) + f"{index:05d}"
            for index in range(1025)
        ]
        manifest["available_equipment"] = [
            *manifest["equipment"],
            *long_identities,
        ]
        reseal_source_manifest(manifest)
        self.assertGreater(
            len(canonical_json_bytes(manifest)),
            MAX_SOURCE_RESOLUTION_BYTES,
        )

        result = validate_catalog_lock(catalog, lock)

        self.assertIsNone(result.model)
        self.assertIn(
            "LOCK_DISTRIBUTION_INVALID",
            {diagnostic.code for diagnostic in result.diagnostics},
        )

    def test_source_resolution_semantics_tie_policy_fact_and_restore(self) -> None:
        valid_cases = (
            (
                {"kind": "native_manager", "manager": "npx", "package": "tool"},
                {
                    "kind": "native_manager",
                    "version": {"kind": "semantic_version", "value": "1.2.3"},
                },
                {
                    "class": "native_rolling",
                    "channel": "npm:1.2.3",
                    "reviewed_baseline": "tool@1.2.3",
                    "observation_source": "reviewed npm selector",
                    "native_update_control": "suppressible",
                },
            ),
            (
                {
                    "kind": "native_manager",
                    "manager": "codex",
                    "package": "github@openai-curated",
                    "channel": "openai-curated",
                },
                {
                    "kind": "native_manager",
                    "version": {"kind": "revision", "value": "11c74d6b"},
                },
                {
                    "class": "native_rolling",
                    "channel": "openai-curated",
                    "reviewed_baseline": "11c74d6b",
                    "observation_source": "codex plugin list",
                    "native_update_control": "unknown",
                },
            ),
            (
                {
                    "kind": "native_manager",
                    "manager": "cursor",
                    "package": "tool@official",
                    "channel": "stable",
                },
                {
                    "kind": "native_manager",
                    "version": {"kind": "semantic_version", "value": "2.0.0-rc.1"},
                },
                {
                    "class": "native_rolling",
                    "channel": "stable",
                    "reviewed_baseline": "2.0.0-rc.1",
                    "observation_source": "cursor plugin list",
                    "native_update_control": "unknown",
                },
            ),
            (
                {
                    "kind": "native_manager",
                    "manager": "http",
                    "package": "https://mcp.example.invalid/v1",
                    "channel": "static",
                },
                {
                    "kind": "native_manager",
                    "version": {"kind": "static_source"},
                },
                {
                    "class": "native_rolling",
                    "channel": "static",
                    "reviewed_baseline": "https://mcp.example.invalid/v1",
                    "observation_source": "reviewed static endpoint",
                    "native_update_control": "unsuppressible",
                },
            ),
        )
        for source, resolved, restore in valid_cases:
            with self.subTest(valid=(source, resolved)):
                self.assertTrue(validator._catalog_source_is_valid(source))
                self.assertTrue(
                    validator._resolved_source_matches_policy(source, resolved)
                )
                self.assertTrue(
                    validator._resolved_source_matches_restore(
                        source,
                        resolved,
                        restore,
                    )
                )

        codex_source, _, codex_restore = valid_cases[1]
        invalid_cases = (
            (
                codex_source,
                {
                    "kind": "native_manager",
                    "version": {"kind": "revision", "value": "deadbeef"},
                },
                codex_restore,
            ),
            (
                codex_source,
                {
                    "kind": "native_manager",
                    "version": {"kind": "semantic_version", "value": "1.2.3"},
                },
                codex_restore,
            ),
            (
                valid_cases[0][0],
                valid_cases[0][1],
                valid_cases[0][2] | {"reviewed_baseline": "unrelated-package@1.2.3"},
            ),
            (
                valid_cases[3][0],
                valid_cases[3][1],
                valid_cases[3][2]
                | {"reviewed_baseline": "https://other.example.invalid/v1"},
            ),
        )
        for source, resolved, restore in invalid_cases:
            with self.subTest(invalid=(source, resolved, restore)):
                self.assertFalse(
                    validator._resolved_source_matches_policy(source, resolved)
                    and validator._resolved_source_matches_restore(
                        source,
                        resolved,
                        restore,
                    )
                )

    def test_native_restore_observation_source_is_bounded_public_prose(self) -> None:
        restore = {
            "class": "native_rolling",
            "channel": "stable",
            "reviewed_baseline": "1.2.3",
            "observation_source": "reviewed plugin list, cached manifest",
            "native_update_control": "suppressible",
        }
        self.assertTrue(validator._restore_is_valid(restore))
        for observation_source in (
            "V7p!opaque.private.value!9Qx",
            "a" * 256,
            "line one\nline two",
        ):
            with self.subTest(observation_source=observation_source):
                self.assertFalse(
                    validator._restore_is_valid(
                        restore | {"observation_source": observation_source}
                    )
                )

    def test_semantic_version_length_bound_matches_source_admission(self) -> None:
        source = {
            "kind": "native_manager",
            "manager": "npx",
            "package": "tool",
        }
        maximum = "1.2.3+" + "A" * 249
        over_limit = "1.2.3+" + "A" * 250

        self.assertTrue(
            validator._resolved_source_matches_policy(
                source,
                {
                    "kind": "native_manager",
                    "version": {"kind": "semantic_version", "value": maximum},
                },
            )
        )
        self.assertFalse(
            validator._resolved_source_matches_policy(
                source,
                {
                    "kind": "native_manager",
                    "version": {"kind": "semantic_version", "value": over_limit},
                },
            )
        )

    def test_npx_source_manifest_requires_one_exact_invocation_selector(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        manifest = next(
            item
            for item in lock["distributions"]
            if item["source"].get("manager") == "npx"
        )
        expected_selector = manifest["restore"]["reviewed_baseline"]

        def duplicate_selectors(value: object) -> int:
            duplicated = 0
            if isinstance(value, dict):
                arguments = value.get("arguments")
                if value.get("kind") == "direct_mcp" and isinstance(arguments, list):
                    matches = [
                        argument
                        for argument in arguments
                        if argument == {"literal": expected_selector}
                    ]
                    if matches:
                        arguments.append(deepcopy(matches[0]))
                        duplicated += 1
                for child in value.values():
                    duplicated += duplicate_selectors(child)
            elif isinstance(value, list):
                for child in value:
                    duplicated += duplicate_selectors(child)
            return duplicated

        self.assertGreater(duplicate_selectors(catalog), 0)
        self.assertGreater(duplicate_selectors(lock), 0)
        self.bind_catalog_digest(catalog, lock)

        result = validate_catalog_lock(catalog, lock)

        self.assertIsNone(result.model)
        self.assertIn(
            "DISTRIBUTION_SOURCE_PROVIDER_MISMATCH",
            {diagnostic.code for diagnostic in result.diagnostics},
        )

    def test_unreferenced_template_still_binds_current_source_manifest(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        template = next(
            item
            for item in catalog["coverage_templates"]
            if any(
                route.get("provider", {}).get("command") == "npx"
                for route in item["record"]["provider_selection"]["routes"]
            )
        )
        unused = deepcopy(template)
        unused["identity"] = "template:unused/review"
        route = unused["record"]["provider_selection"]["routes"][0]
        route["identity"] = "route:unused/review"
        route["activation_group"] = "activation:unused/review"
        unused["record"]["provider_selection"]["preferred_route"] = route["identity"]
        route["restore"]["channel"] = "npm:9.9.9"
        route["restore"]["reviewed_baseline"] = "unrelated-package@9.9.9"
        catalog["coverage_templates"].append(unused)
        self.bind_catalog_digest(catalog, lock)

        result = validate_catalog_lock(catalog, lock)

        self.assertIsNone(result.model)
        self.assertTrue(
            {
                "DISTRIBUTION_SOURCE_PROVIDER_MISMATCH",
                "LOCK_DISTRIBUTION_INVALID",
            }
            & {diagnostic.code for diagnostic in result.diagnostics}
        )

    def test_unreferenced_template_is_fully_structurally_validated(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        template = next(
            item
            for item in catalog["coverage_templates"]
            if item["record"]["outcome"] == "managed_provider"
            and any(
                operation["disposition"] == "automated"
                for route in item["record"]["provider_selection"]["routes"]
                for operation in route["operations"].values()
            )
        )
        unused = deepcopy(template)
        unused["identity"] = "template:unused/structurally-invalid"
        route = unused["record"]["provider_selection"]["routes"][0]
        route["identity"] = "route:unused/structurally-invalid"
        route["activation_group"] = "activation:unused/structurally-invalid"
        route["control_owner"] = "operator_owned"
        unused["record"]["provider_selection"]["preferred_route"] = route["identity"]
        catalog["coverage_templates"].append(unused)
        self.bind_catalog_digest(catalog, lock)

        result = validate_catalog_lock(catalog, lock)

        self.assertIsNone(result.model)
        self.assertIn(
            "OPERATOR_AUTOMATION_INVALID",
            {diagnostic.code for diagnostic in result.diagnostics},
        )

    def test_retirement_binds_exact_history_and_rejects_missing_or_orphan_history(
        self,
    ) -> None:
        catalog, lock = self.fixture_pair()
        old_manifest = deepcopy(source_manifest(lock, "distribution:example/bundle"))
        retirement_route = deepcopy(
            catalog["coverage_templates"][0]["record"]["provider_selection"]["routes"][
                0
            ]
        )
        retirement_route["identity"] = "route:example/legacy-claude-projection"
        retirement_route["activation_group"] = (
            "activation:example/legacy-claude-projection"
        )
        retirement = {
            "identity": "retirement:example/legacy-grilling-projection",
            "equipment_identity": "skill:example/grilling",
            "harness": "claude",
            "route": retirement_route,
            "surface": {
                "kind": "claude_skill_projection",
                "skill_name": "grilling",
            },
            "desired_state": "absent",
            "source_manifest_digest": old_manifest["source_manifest_digest"],
        }
        catalog["retirements"].append(retirement)
        lock["retirements"].append(deepcopy(retirement))
        lock["source_manifest_history"] = [old_manifest]

        current_manifest = source_manifest(lock, "distribution:example/bundle")
        revision = "89abcdef0123456789abcdef0123456789abcdef"
        current_manifest["resolved_source"]["revision"] = revision
        current_manifest["restore"] = {
            "class": "immutable",
            "revision": revision,
            "artifact_ref": ("git+https://example.invalid/bundle.git@" + revision),
            "content_digest": "sha256:" + "2" * 64,
            "native_update_control": "not_applicable",
        }
        reseal_source_manifest(current_manifest)
        active_record = catalog["coverage_templates"][0]["record"]
        active_record["provider_selection"]["routes"][0]["restore"] = deepcopy(
            current_manifest["restore"]
        )
        next(
            item
            for item in lock["coverage"]
            if item["equipment_identity"] == "skill:example/grilling"
            and item["harness"] == "claude"
        )["record"] = deepcopy(active_record)
        self.bind_catalog_digest(catalog, lock)

        valid = validate_catalog_lock(catalog, lock)
        self.assertEqual(valid.diagnostics, ())
        self.assertIsNotNone(valid.model)

        missing = deepcopy(lock)
        missing["source_manifest_history"] = []
        missing_codes = {
            diagnostic.code
            for diagnostic in validate_catalog_lock(catalog, missing).diagnostics
        }
        self.assertIn("RETIREMENT_SOURCE_MANIFEST_INVALID", missing_codes)
        self.assertIn("SOURCE_MANIFEST_HISTORY_INVALID", missing_codes)

        orphan = deepcopy(old_manifest)
        orphan_revision = "fedcba9876543210fedcba9876543210fedcba98"
        orphan["resolved_source"]["revision"] = orphan_revision
        orphan["restore"]["revision"] = orphan_revision
        orphan["restore"]["artifact_ref"] = (
            "git+https://example.invalid/bundle.git@" + orphan_revision
        )
        reseal_source_manifest(orphan)
        extra = deepcopy(lock)
        extra["source_manifest_history"].append(orphan)
        extra_codes = {
            diagnostic.code
            for diagnostic in validate_catalog_lock(catalog, extra).diagnostics
        }
        self.assertIn("SOURCE_MANIFEST_HISTORY_INVALID", extra_codes)

    def test_file_loading_rejects_ambiguous_and_non_json_documents(self) -> None:
        lock_bytes = LOCK.read_bytes()
        invalid_catalogs = (
            b'{"duplicate":1,"duplicate":2}',
            b'{"nonfinite":NaN}',
            b"\xff",
        )
        for payload in invalid_catalogs:
            with self.subTest(payload=payload), TemporaryDirectory() as directory:
                root = Path(directory).resolve(strict=True)
                catalog_path = root / "catalog.json"
                lock_path = root / "lock.json"
                catalog_path.write_bytes(payload)
                lock_path.write_bytes(lock_bytes)

                result = load_catalog_lock(catalog_path, lock_path)

                self.assertIsNone(result.model)
                self.assertEqual(
                    tuple(diagnostic.code for diagnostic in result.diagnostics),
                    ("DOCUMENT_PARSE_INVALID",),
                )

    def test_file_loading_rejects_oversized_documents_before_json_parsing(
        self,
    ) -> None:
        original_loader = validator.strict_load_json_bytes
        cases = (
            ("catalog", 4 * 1024 * 1024),
            ("lock", 16 * 1024 * 1024),
        )
        for role, maximum_bytes in cases:
            with self.subTest(role=role), TemporaryDirectory() as directory:
                root = Path(directory).resolve(strict=True)
                catalog_path = root / "catalog.json"
                lock_path = root / "lock.json"
                shutil.copyfile(CATALOG, catalog_path)
                shutil.copyfile(LOCK, lock_path)
                oversized = catalog_path if role == "catalog" else lock_path
                with oversized.open("wb") as stream:
                    stream.truncate(maximum_bytes + 1)

                oversized_parse_calls = 0

                def reject_oversized_parse(payload: bytes) -> object:
                    nonlocal oversized_parse_calls
                    if len(payload) > 4 * 1024 * 1024:
                        oversized_parse_calls += 1
                        raise AssertionError("oversized input reached JSON parsing")
                    return original_loader(payload)

                with patch.object(
                    validator,
                    "strict_load_json_bytes",
                    side_effect=reject_oversized_parse,
                ):
                    result = load_catalog_lock(catalog_path, lock_path)

                self.assertIsNone(result.model)
                self.assertEqual(
                    tuple(diagnostic.code for diagnostic in result.diagnostics),
                    ("DOCUMENT_CAPTURE_INVALID",),
                )
                self.assertEqual(
                    result.diagnostics[0].message,
                    "Catalog and lock inputs must be stable, size-bounded, "
                    "unique regular files reached without symbolic links.",
                )
                self.assertEqual(oversized_parse_calls, 0)

    def test_file_loading_rejects_symlinked_and_hardlinked_leaves(self) -> None:
        for kind in ("symlink", "hardlink"):
            with self.subTest(kind=kind), TemporaryDirectory() as directory:
                root = Path(directory).resolve(strict=True)
                source = root / "catalog-source.json"
                catalog_path = root / "catalog.json"
                lock_path = root / "lock.json"
                shutil.copyfile(CATALOG, source)
                shutil.copyfile(LOCK, lock_path)
                if kind == "symlink":
                    catalog_path.symlink_to(source.name)
                else:
                    os.link(source, catalog_path)

                result = load_catalog_lock(catalog_path, lock_path)

                self.assertIsNone(result.model)
                self.assertEqual(
                    tuple(diagnostic.code for diagnostic in result.diagnostics),
                    ("DOCUMENT_CAPTURE_INVALID",),
                )

    @unittest.skipUnless(
        hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW"),
        "requires safe POSIX directory descriptors",
    )
    def test_file_loading_rejects_a_symlinked_parent_directory(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve(strict=True)
            actual = root / "actual"
            actual.mkdir()
            shutil.copyfile(CATALOG, actual / "catalog.json")
            shutil.copyfile(LOCK, actual / "lock.json")
            linked = root / "linked"
            linked.symlink_to(actual, target_is_directory=True)

            result = load_catalog_lock(
                linked / "catalog.json",
                linked / "lock.json",
            )

        self.assertIsNone(result.model)
        self.assertEqual(
            tuple(diagnostic.code for diagnostic in result.diagnostics),
            ("DOCUMENT_CAPTURE_INVALID",),
        )

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX FIFO support")
    def test_file_loading_rejects_a_fifo_without_blocking(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve(strict=True)
            catalog_path = root / "catalog.json"
            lock_path = root / "lock.json"
            os.mkfifo(catalog_path)
            shutil.copyfile(LOCK, lock_path)
            script = (
                "from pathlib import Path; "
                "from agent_equipment.validator import load_catalog_lock; "
                f"result=load_catalog_lock(Path({str(catalog_path)!r}), "
                f"Path({str(lock_path)!r})); "
                "print(result.diagnostics[0].code)"
            )
            environment = os.environ | {"PYTHONPATH": str(PACKAGE_ROOT)}

            completed = subprocess.run(
                [sys.executable, "-c", script],
                env=environment,
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "DOCUMENT_CAPTURE_INVALID\n")

    def test_file_loading_rejects_a_nonregular_directory(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve(strict=True)
            catalog_path = root / "catalog.json"
            lock_path = root / "lock.json"
            catalog_path.mkdir()
            shutil.copyfile(LOCK, lock_path)

            result = load_catalog_lock(catalog_path, lock_path)

        self.assertIsNone(result.model)
        self.assertEqual(
            tuple(diagnostic.code for diagnostic in result.diagnostics),
            ("DOCUMENT_CAPTURE_INVALID",),
        )

    @unittest.skipUnless(
        hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_NONBLOCK"),
        "requires safe POSIX descriptor flags",
    )
    def test_file_loading_holds_and_closes_nofollow_descriptors(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve(strict=True)
            catalog_path = root / "catalog.json"
            lock_path = root / "lock.json"
            shutil.copyfile(CATALOG, catalog_path)
            shutil.copyfile(LOCK, lock_path)
            original_open = os.open
            original_close = os.close
            opened_descriptors: list[tuple[int, int]] = []
            closed_descriptors: list[int] = []

            def record_open(
                path: str | Path,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                if dir_fd is None:
                    descriptor = original_open(path, flags, mode)
                else:
                    descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
                opened_descriptors.append((descriptor, flags))
                return descriptor

            def record_close(descriptor: int) -> None:
                closed_descriptors.append(descriptor)
                original_close(descriptor)

            with (
                patch.object(validator.os, "open", side_effect=record_open),
                patch.object(validator.os, "close", side_effect=record_close),
            ):
                result = load_catalog_lock(catalog_path, lock_path)

        self.assertIsNotNone(result.model, result.diagnostics)
        descriptor_numbers = [descriptor for descriptor, _ in opened_descriptors]
        open_flags = [flags for _, flags in opened_descriptors]
        self.assertGreater(len(opened_descriptors), 2)
        self.assertEqual(len(closed_descriptors), len(descriptor_numbers))
        self.assertCountEqual(closed_descriptors, descriptor_numbers)
        self.assertTrue(
            all(flags & os.O_NOFOLLOW for flags in open_flags),  # type: ignore[attr-defined]
        )
        leaf_flags = [flags for flags in open_flags if flags & os.O_NONBLOCK]
        parent_flags = [flags for flags in open_flags if not flags & os.O_NONBLOCK]
        self.assertEqual(len(leaf_flags), 2)
        self.assertTrue(parent_flags)
        self.assertTrue(
            all(flags & os.O_DIRECTORY for flags in parent_flags),  # type: ignore[attr-defined]
        )
        self.assertTrue(
            all(not flags & os.O_DIRECTORY for flags in leaf_flags),  # type: ignore[attr-defined]
        )

    def test_file_loading_rejects_path_swap_and_in_place_change_after_reads(
        self,
    ) -> None:
        for race in ("path-swap", "in-place-change"):
            with self.subTest(race=race), TemporaryDirectory() as directory:
                root = Path(directory).resolve(strict=True)
                catalog_path = root / "catalog.json"
                lock_path = root / "lock.json"
                replacement = root / "replacement.json"
                shutil.copyfile(CATALOG, catalog_path)
                shutil.copyfile(CATALOG, replacement)
                shutil.copyfile(LOCK, lock_path)
                script = textwrap.dedent(
                    f"""
                    from pathlib import Path
                    from unittest.mock import patch
                    import agent_equipment.validator as validator

                    catalog_path = Path({str(catalog_path)!r})
                    lock_path = Path({str(lock_path)!r})
                    replacement = Path({str(replacement)!r})
                    race = {race!r}
                    original_reader = validator._read_bounded_document_descriptor
                    calls = 0

                    def read_and_race(descriptor: int, *, maximum_bytes: int) -> bytes:
                        global calls
                        payload = original_reader(
                            descriptor,
                            maximum_bytes=maximum_bytes,
                        )
                        calls += 1
                        if calls == 2:
                            if race == "path-swap":
                                replacement.replace(catalog_path)
                            else:
                                with catalog_path.open("ab") as stream:
                                    stream.write(b"\\n")
                        return payload

                    with patch.object(
                        validator,
                        "_read_bounded_document_descriptor",
                        side_effect=read_and_race,
                    ):
                        result = validator.load_catalog_lock(catalog_path, lock_path)

                    print(calls)
                    print(result.diagnostics[0].code)
                    """
                )
                environment = os.environ | {"PYTHONPATH": str(PACKAGE_ROOT)}
                completed = subprocess.run(
                    [sys.executable, "-c", script],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )

                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(completed.stdout, "2\nDOCUMENT_CAPTURE_INVALID\n")

    @unittest.skipUnless(
        hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW"),
        "requires safe POSIX directory descriptors",
    )
    def test_file_loading_rejects_a_parent_path_swap_after_reads(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve(strict=True)
            original_parent = root / "config"
            original_parent.mkdir()
            catalog_path = original_parent / "catalog.json"
            lock_path = original_parent / "lock.json"
            shutil.copyfile(CATALOG, catalog_path)
            shutil.copyfile(LOCK, lock_path)

            replacement_parent = root / "replacement"
            replacement_parent.mkdir()
            shutil.copyfile(CATALOG, replacement_parent / "catalog.json")
            shutil.copyfile(LOCK, replacement_parent / "lock.json")
            moved_parent = root / "config-original"
            original_reader = validator._read_bounded_document_descriptor
            read_calls = 0

            def read_and_swap_parent(
                descriptor: int,
                *,
                maximum_bytes: int,
            ) -> bytes:
                nonlocal read_calls
                payload = original_reader(
                    descriptor,
                    maximum_bytes=maximum_bytes,
                )
                read_calls += 1
                if read_calls == 2:
                    original_parent.rename(moved_parent)
                    replacement_parent.rename(original_parent)
                return payload

            with patch.object(
                validator,
                "_read_bounded_document_descriptor",
                side_effect=read_and_swap_parent,
            ):
                result = load_catalog_lock(catalog_path, lock_path)

        self.assertEqual(read_calls, 2)
        self.assertIsNone(result.model)
        self.assertEqual(
            tuple(diagnostic.code for diagnostic in result.diagnostics),
            ("DOCUMENT_CAPTURE_INVALID",),
        )

    def test_representative_catalog_failures_return_diagnostics_without_a_plan(
        self,
    ) -> None:
        catalog, lock = self.fixture_pair()
        cases: list[tuple[str, dict[str, object], dict[str, object], str]] = []

        stale_lock = deepcopy(lock)
        stale_lock["catalog_digest"] = "sha256:" + "0" * 64
        cases.append(("stale lock", catalog, stale_lock, "LOCK_CATALOG_DIGEST_STALE"))

        bare_provider = deepcopy(catalog)
        bare_provider["equipment"][0]["coverage"]["claude"]["record"] = {
            "outcome": "managed_provider",
            "provider_selection": "no_provider",
        }
        cases.append(
            (
                "provider outcome without route",
                bare_provider,
                lock,
                "CATALOG_SCHEMA_INVALID",
            )
        )

        missing_compensation = deepcopy(catalog)
        del missing_compensation["coverage_templates"][0]["record"][
            "provider_selection"
        ]["routes"][0]["operations"]["install"]["compensation"]
        compensation_lock = deepcopy(lock)
        compensation_lock["catalog_digest"] = canonical_json_sha256(
            missing_compensation
        )
        cases.append(
            (
                "automated mutation without compensation",
                missing_compensation,
                compensation_lock,
                "CATALOG_SCHEMA_INVALID",
            )
        )

        non_string_route_identity = deepcopy(catalog)
        non_string_route_identity["coverage_templates"][0]["record"][
            "provider_selection"
        ]["routes"][0]["identity"] = None
        non_string_route_lock = deepcopy(lock)
        non_string_route_lock["catalog_digest"] = canonical_json_sha256(
            non_string_route_identity
        )
        cases.append(
            (
                "non-string route identity",
                non_string_route_identity,
                non_string_route_lock,
                "CATALOG_SCHEMA_INVALID",
            )
        )

        for label, invalid_catalog, invalid_lock, expected_code in cases:
            with self.subTest(case=label):
                first = validate_catalog_lock(invalid_catalog, invalid_lock)
                second = validate_catalog_lock(invalid_catalog, invalid_lock)

                self.assertIsNone(first.model)
                self.assertEqual(first, second)
                self.assertIn(
                    expected_code,
                    {diagnostic.code for diagnostic in first.diagnostics},
                )
                self.assertFalse(hasattr(first, "mutation_plan"))

    def test_public_validation_cross_field_mutation_matrix_is_deterministic(
        self,
    ) -> None:
        cases: list[tuple[str, dict[str, object], dict[str, object], str]] = []

        catalog, lock = self.fixture_pair()
        catalog["distributions"][0]["coverage_templates"]["claude"] = (
            "template:bundle-codex"
        )
        self.bind_catalog_digest(catalog, lock)
        cases.append(("template harness", catalog, lock, "TEMPLATE_HARNESS_MISMATCH"))

        catalog, lock = self.fixture_pair()
        route = catalog["coverage_templates"][0]["record"]["provider_selection"][
            "routes"
        ][0]
        locked_route = lock["coverage"][3]["record"]["provider_selection"]["routes"][0]
        native_restore = deepcopy(lock["distributions"][1]["restore"])
        route["distribution"] = "distribution:example/native-plugin"
        route["restore"] = native_restore
        route["provenance"] = {"owner": "source:example/native-plugin"}
        locked_route.update(
            {
                "distribution": route["distribution"],
                "restore": deepcopy(route["restore"]),
                "provenance": deepcopy(route["provenance"]),
            }
        )
        self.bind_catalog_digest(catalog, lock)
        cases.append(
            (
                "route distribution membership",
                catalog,
                lock,
                "ROUTE_DISTRIBUTION_MEMBERSHIP_INVALID",
            )
        )

        catalog, lock = self.fixture_pair()
        selection = catalog["coverage_templates"][0]["record"]["provider_selection"]
        supplementary = deepcopy(selection["routes"][0])
        supplementary["identity"] = "route:example/supplementary"
        supplementary["activation_group"] = "activation:example/supplementary"
        selection["routes"].append(supplementary)
        selection["supplementary_routes"].append(supplementary["identity"])
        self.bind_catalog_digest(catalog, lock)
        cases.append(("unlisted overlap", catalog, lock, "OVERLAP_INVALID"))

        catalog, lock = self.fixture_pair()
        shared_group = catalog["coverage_templates"][0]["record"]["provider_selection"][
            "routes"
        ][0]["activation_group"]
        manual_route = catalog["equipment"][0]["coverage"]["claude"]["record"][
            "provider_selection"
        ]["routes"][0]
        locked_manual_route = lock["coverage"][0]["record"]["provider_selection"][
            "routes"
        ][0]
        manual_route["activation_group"] = shared_group
        locked_manual_route["activation_group"] = shared_group
        self.bind_catalog_digest(catalog, lock)
        cases.append(("activation group", catalog, lock, "ACTIVATION_GROUP_CONFLICT"))

        catalog, lock = self.fixture_pair()
        control = {
            "equipment_identity": "skill:example/grilling",
            "state": "disabled",
        }
        catalog["coverage_templates"][0]["record"]["provider_selection"]["routes"][0][
            "component_controls"
        ] = [control]
        lock["coverage"][3]["record"]["provider_selection"]["routes"][0][
            "component_controls"
        ] = [deepcopy(control)]
        self.bind_catalog_digest(catalog, lock)
        cases.append(("component control", catalog, lock, "COMPONENT_CONTROL_INVALID"))

        catalog, lock = self.fixture_pair()
        invalid_owner = {"owner": "source:example/unrelated"}
        catalog["coverage_templates"][0]["record"]["provider_selection"]["routes"][0][
            "provenance"
        ] = invalid_owner
        lock["coverage"][3]["record"]["provider_selection"]["routes"][0][
            "provenance"
        ] = deepcopy(invalid_owner)
        self.bind_catalog_digest(catalog, lock)
        cases.append(("provenance", catalog, lock, "PROVENANCE_OWNER_INVALID"))

        catalog, lock = self.fixture_pair()
        retirement_route = deepcopy(
            catalog["coverage_templates"][0]["record"]["provider_selection"]["routes"][
                0
            ]
        )
        retirement_route["identity"] = "route:example/legacy-claude-projection"
        retirement_route["activation_group"] = (
            "activation:example/legacy-claude-projection"
        )
        retirement_route["control_owner"] = "operator_owned"
        retirement = {
            "identity": "retirement:example/legacy-grilling-projection",
            "equipment_identity": "skill:example/grilling",
            "harness": "claude",
            "route": retirement_route,
            "surface": {
                "kind": "claude_skill_projection",
                "skill_name": "grilling",
            },
            "desired_state": "absent",
            "source_manifest_digest": retirement_manifest_digest(
                lock, retirement_route
            ),
        }
        catalog["retirements"].append(retirement)
        lock["retirements"].append(deepcopy(retirement))
        self.bind_catalog_digest(catalog, lock)
        cases.append(("retirement owner", catalog, lock, "RETIREMENT_OWNER_INVALID"))

        catalog, lock = self.fixture_pair()
        lock["coverage"].pop()
        cases.append(("lock coverage", catalog, lock, "LOCK_COVERAGE_MISMATCH"))

        catalog, lock = self.fixture_pair()
        catalog["equipment"][0]["coverage"]["claude"]["record"]["provider_selection"][
            "routes"
        ][0]["control_owner"] = "reconciler_owned"
        lock["coverage"][0]["record"]["provider_selection"]["routes"][0][
            "control_owner"
        ] = "reconciler_owned"
        self.bind_catalog_digest(catalog, lock)
        cases.append(("route owner", catalog, lock, "COVERAGE_OWNER_MISMATCH"))

        for label, invalid_catalog, invalid_lock, expected_code in cases:
            with self.subTest(case=label):
                catalog_before = deepcopy(invalid_catalog)
                lock_before = deepcopy(invalid_lock)

                first = validate_catalog_lock(invalid_catalog, invalid_lock)
                second = validate_catalog_lock(invalid_catalog, invalid_lock)

                self.assertEqual(invalid_catalog, catalog_before)
                self.assertEqual(invalid_lock, lock_before)
                self.assertEqual(first, second)
                self.assertIsNone(first.model)
                self.assertIn(
                    expected_code,
                    {diagnostic.code for diagnostic in first.diagnostics},
                )
                self.assertFalse(hasattr(first, "mutation_plan"))

    def test_public_validation_rejects_each_remaining_cross_field_mutation(
        self,
    ) -> None:
        cases: list[
            tuple[
                str,
                dict[str, object],
                dict[str, object],
                str,
                bool,
            ]
        ] = []

        catalog, lock = self.fixture_pair()
        catalog["equipment"].append(
            {
                "identity": "skill:example/unselected",
                "kind": "skill",
                "coverage": {},
            }
        )
        self.bind_catalog_digest(catalog, lock)
        cases.append(
            (
                "equipment override outside resolved selection",
                catalog,
                lock,
                "EQUIPMENT_SELECTION_INVALID",
                True,
            )
        )

        catalog, lock = self.fixture_pair()
        catalog["distributions"][1]["selection"]["equipment"].append(
            "skill:example/grilling"
        )
        catalog["distributions"][1]["coverage_templates"]["claude"] = (
            "template:bundle-claude"
        )
        ambiguous_manifest = lock["distributions"][1]
        ambiguous_manifest["available_equipment"].append("skill:example/grilling")
        ambiguous_manifest["equipment"].append("skill:example/grilling")
        reseal_source_manifest(ambiguous_manifest)
        lock["coverage"] = [
            item
            for item in lock["coverage"]
            if not (
                item["equipment_identity"] == "skill:example/grilling"
                and item["harness"] == "claude"
            )
        ]
        self.bind_catalog_digest(catalog, lock)
        cases.append(
            (
                "ambiguous distribution templates",
                catalog,
                lock,
                "AMBIGUOUS_COVERAGE_TEMPLATE",
                True,
            )
        )

        catalog, lock = self.fixture_pair()
        omission = catalog["equipment"][0]["coverage"]["codex"]["record"]
        omission["provider_selection"] = deepcopy(
            catalog["coverage_templates"][0]["record"]["provider_selection"]
        )
        self.bind_catalog_digest(catalog, lock)
        cases.append(
            (
                "omission with provider selection",
                catalog,
                lock,
                "CATALOG_SCHEMA_INVALID",
                False,
            )
        )

        catalog, lock = self.fixture_pair()
        selection = catalog["coverage_templates"][0]["record"]["provider_selection"]
        selection["preferred_route"] = "route:example/not-listed"
        next(
            item
            for item in lock["coverage"]
            if item["equipment_identity"] == "skill:example/grilling"
            and item["harness"] == "claude"
        )["record"] = deepcopy(catalog["coverage_templates"][0]["record"])
        self.bind_catalog_digest(catalog, lock)
        cases.append(
            (
                "preferred route outside route enumeration",
                catalog,
                lock,
                "COVERAGE_RECORD_INVALID",
                True,
            )
        )

        catalog, lock = self.fixture_pair()
        selection = catalog["coverage_templates"][0]["record"]["provider_selection"]
        unlisted_supplementary = deepcopy(selection["routes"][0])
        unlisted_supplementary["identity"] = "route:example/not-enumerated"
        unlisted_supplementary["activation_group"] = "activation:example/not-enumerated"
        selection["routes"].append(unlisted_supplementary)
        next(
            item
            for item in lock["coverage"]
            if item["equipment_identity"] == "skill:example/grilling"
            and item["harness"] == "claude"
        )["record"] = deepcopy(catalog["coverage_templates"][0]["record"])
        self.bind_catalog_digest(catalog, lock)
        cases.append(
            (
                "supplementary route omitted from route enumeration",
                catalog,
                lock,
                "COVERAGE_RECORD_INVALID",
                True,
            )
        )

        overlap_catalog, overlap_lock = self.fixture_pair()
        overlap_selection = overlap_catalog["coverage_templates"][0]["record"][
            "provider_selection"
        ]
        supplementary = deepcopy(overlap_selection["routes"][0])
        supplementary["identity"] = "route:example/supplementary"
        supplementary["activation_group"] = "activation:example/supplementary"
        overlap_selection["routes"].append(supplementary)
        overlap_selection["supplementary_routes"].append(supplementary["identity"])
        preferred_identity = overlap_selection["preferred_route"]
        supplementary_identity = supplementary["identity"]
        complete_route_set = [preferred_identity, supplementary_identity]
        valid_exception = {
            "kind": "allow_overlap",
            "supplementary_route": supplementary_identity,
            "routes": complete_route_set,
            "rationale": "Both routes are intentionally active.",
        }
        overlap_mutations = (
            (
                "overlap supplementary field mismatch",
                [
                    {
                        **valid_exception,
                        "supplementary_route": preferred_identity,
                    }
                ],
            ),
            (
                "overlap complete route-set mismatch",
                [
                    {
                        **valid_exception,
                        "routes": [
                            supplementary_identity,
                            "route:example/unrelated",
                        ],
                    }
                ],
            ),
            (
                "extra overlap exception",
                [
                    valid_exception,
                    {
                        **valid_exception,
                        "supplementary_route": preferred_identity,
                    },
                ],
            ),
        )
        for label, exceptions in overlap_mutations:
            catalog = deepcopy(overlap_catalog)
            lock = deepcopy(overlap_lock)
            catalog["coverage_templates"][0]["record"]["provider_selection"][
                "allow_overlap"
            ] = deepcopy(exceptions)
            next(
                item
                for item in lock["coverage"]
                if item["equipment_identity"] == "skill:example/grilling"
                and item["harness"] == "claude"
            )["record"] = deepcopy(catalog["coverage_templates"][0]["record"])
            self.bind_catalog_digest(catalog, lock)
            cases.append((label, catalog, lock, "OVERLAP_INVALID", True))

        retirement_catalog, retirement_lock = self.fixture_pair()
        retirement_route = deepcopy(
            retirement_catalog["coverage_templates"][0]["record"]["provider_selection"][
                "routes"
            ][0]
        )
        retirement_route["identity"] = "route:example/legacy-claude-projection"
        retirement_route["activation_group"] = (
            "activation:example/legacy-claude-projection"
        )
        retirement = {
            "identity": "retirement:example/legacy-grilling-projection",
            "equipment_identity": "skill:example/grilling",
            "harness": "claude",
            "route": retirement_route,
            "surface": {
                "kind": "claude_skill_projection",
                "skill_name": "grilling",
            },
            "desired_state": "absent",
            "source_manifest_digest": retirement_manifest_digest(
                retirement_lock, retirement_route
            ),
        }

        catalog = deepcopy(retirement_catalog)
        lock = deepcopy(retirement_lock)
        catalog["retirements"].extend((deepcopy(retirement), deepcopy(retirement)))
        lock["retirements"] = deepcopy(catalog["retirements"])
        self.bind_catalog_digest(catalog, lock)
        cases.append(
            (
                "duplicate retirement identity",
                catalog,
                lock,
                "RETIREMENT_IDENTITY_INVALID",
                True,
            )
        )

        catalog = deepcopy(retirement_catalog)
        lock = deepcopy(retirement_lock)
        nonautomated_retirement = deepcopy(retirement)
        nonautomated_retirement["route"]["operations"]["remove"] = {
            "disposition": "unavailable"
        }
        catalog["retirements"].append(nonautomated_retirement)
        lock["retirements"] = deepcopy(catalog["retirements"])
        self.bind_catalog_digest(catalog, lock)
        cases.append(
            (
                "retirement operation is not automated",
                catalog,
                lock,
                "RETIREMENT_OPERATION_INVALID",
                True,
            )
        )

        catalog, lock = self.fixture_pair()
        mismatched_manifest = lock["distributions"][1]
        mismatched_manifest["available_equipment"].append("skill:example/grilling")
        mismatched_manifest["equipment"].append("skill:example/grilling")
        reseal_source_manifest(mismatched_manifest)
        self.bind_catalog_digest(catalog, lock)
        cases.append(
            (
                "explicit selection differs from resolved membership",
                catalog,
                lock,
                "DISTRIBUTION_SELECTION_INVALID",
                True,
            )
        )

        catalog, lock = self.fixture_pair()
        extra_distribution = deepcopy(lock["distributions"][0])
        extra_distribution["distribution_identity"] = "distribution:example/unbound"
        reseal_source_manifest(extra_distribution)
        lock["distributions"].append(extra_distribution)
        self.bind_catalog_digest(catalog, lock)
        cases.append(
            (
                "lock contains an unbound distribution",
                catalog,
                lock,
                "LOCK_DISTRIBUTION_INVALID",
                True,
            )
        )

        catalog, lock = self.fixture_pair()
        route_restore = catalog["coverage_templates"][0]["record"][
            "provider_selection"
        ]["routes"][0]["restore"]
        route_restore["content_digest"] = "sha256:" + "2" * 64
        next(
            item
            for item in lock["coverage"]
            if item["equipment_identity"] == "skill:example/grilling"
            and item["harness"] == "claude"
        )["record"] = deepcopy(catalog["coverage_templates"][0]["record"])
        self.bind_catalog_digest(catalog, lock)
        cases.append(
            (
                "active route restore differs from resolved restore",
                catalog,
                lock,
                "LOCK_DISTRIBUTION_INVALID",
                True,
            )
        )

        for label, invalid_catalog, invalid_lock, expected_code, semantic in cases:
            with self.subTest(case=label):
                catalog_before = deepcopy(invalid_catalog)
                lock_before = deepcopy(invalid_lock)

                first = validate_catalog_lock(invalid_catalog, invalid_lock)
                second = validate_catalog_lock(invalid_catalog, invalid_lock)
                codes = {diagnostic.code for diagnostic in first.diagnostics}

                self.assertEqual(invalid_catalog, catalog_before)
                self.assertEqual(invalid_lock, lock_before)
                self.assertEqual(first, second)
                self.assertIsNone(first.model)
                self.assertIn(expected_code, codes)
                if semantic:
                    self.assertNotIn("CATALOG_SCHEMA_INVALID", codes)
                    self.assertNotIn("LOCK_SCHEMA_INVALID", codes)
                self.assertFalse(hasattr(first, "mutation_plan"))


if __name__ == "__main__":
    unittest.main()
