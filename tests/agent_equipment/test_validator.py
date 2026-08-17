from __future__ import annotations

import json
import sys
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
from agent_equipment.canonical import canonical_json_sha256
from agent_equipment.model import CatalogLockValidation, thaw_json
from agent_equipment.validator import load_catalog_lock, validate_catalog_lock

DOCUMENTS = ROOT / "docs/agent-equipment"
CATALOG = DOCUMENTS / "initial-catalog.proposed.json"
LOCK = DOCUMENTS / "initial-lock.proposed.json"
FIXTURES = ROOT / "tests/fixtures/agent-equipment/schema"


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
            "sha256:72c06dd6869c4cd10bcfe8cff3f9a2b269fd21eab0917974f34d70671af696bd",
        )
        self.assertEqual(
            result.model.lock.digest,
            "sha256:a0bd41ba4206b1a49fc1e0704b9d78a2003176b6d7882340a39d54fbc269cc34",
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

    def test_file_loading_rejects_ambiguous_and_non_json_documents(self) -> None:
        lock_bytes = LOCK.read_bytes()
        invalid_catalogs = (
            b'{"duplicate":1,"duplicate":2}',
            b'{"nonfinite":NaN}',
            b"\xff",
        )
        for payload in invalid_catalogs:
            with self.subTest(payload=payload), TemporaryDirectory() as directory:
                root = Path(directory)
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
        lock["distributions"][1]["equipment"].append("skill:example/grilling")
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
        lock["distributions"][1]["equipment"].append("skill:example/grilling")
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
        extra_distribution["identity"] = "distribution:example/unbound"
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
