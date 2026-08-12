from __future__ import annotations

import importlib.util
from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests/fixtures/agent-equipment/schema"
SPEC = importlib.util.spec_from_file_location(
    "agent_equipment_design",
    ROOT / "scripts/agent_equipment_design.py",
)
assert SPEC is not None and SPEC.loader is not None
DESIGN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DESIGN
SPEC.loader.exec_module(DESIGN)


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def valid_pair() -> tuple[dict[str, object], dict[str, object]]:
    catalog = load_fixture("valid-catalog.json")
    lock = load_fixture("valid-lock.json")
    return catalog, lock


def managed_selection(catalog: dict[str, object]) -> dict[str, object]:
    return catalog["coverage_templates"][0]["record"]["provider_selection"]


def managed_route(catalog: dict[str, object]) -> dict[str, object]:
    return managed_selection(catalog)["routes"][0]


def manual_route(catalog: dict[str, object]) -> dict[str, object]:
    return catalog["equipment"][0]["coverage"]["claude"]["record"]["provider_selection"]["routes"][0]


def valid_retirement(catalog: dict[str, object]) -> dict[str, object]:
    route = deepcopy(managed_route(catalog))
    route["identity"] = "route:example/legacy-claude-projection"
    route["activation_group"] = "activation:example/legacy-claude-projection"
    return {
        "identity": "retirement:example/legacy-grilling-projection",
        "equipment_identity": "skill:example/grilling",
        "harness": "claude",
        "route": route,
        "surface": {
            "kind": "claude_skill_projection",
            "skill_name": "legacy-grilling",
        },
        "desired_state": "absent",
    }


def locked_record(
    lock: dict[str, object],
    equipment_identity: str = "skill:example/grilling",
    harness: str = "claude",
) -> dict[str, object]:
    return next(
        item["record"]
        for item in lock["coverage"]
        if item["equipment_identity"] == equipment_identity
        and item["harness"] == harness
    )


def locked_managed_route(lock: dict[str, object]) -> dict[str, object]:
    return locked_record(lock)["provider_selection"]["routes"][0]


class AgentEquipmentDesignTest(unittest.TestCase):
    def test_initial_inventory_counts_and_classifications_are_complete(self) -> None:
        inventory = json.loads(
            (ROOT / "docs/agent-equipment/initial-inventory.json").read_text(
                encoding="utf-8"
            )
        )
        counts = inventory["counts"]

        standalone_names = [
            name
            for group in inventory["standalone_skills"]["classification_groups"]
            for name in group["names"]
        ]
        self.assertEqual(len(standalone_names), counts["standalone_skills"])
        self.assertEqual(len(standalone_names), len(set(standalone_names)))

        for key, count_key in (
            ("claude_plugins", "claude_plugins"),
            ("codex_plugins", "codex_plugin_config_observations"),
        ):
            classified_ids = [
                identity
                for group in inventory[key]["classification_groups"]
                for identity in group["ids"]
            ]
            observed_ids = [item["id"] for item in inventory[key]["states"]]
            self.assertEqual(len(classified_ids), counts[count_key])
            self.assertEqual(len(classified_ids), len(set(classified_ids)))
            self.assertEqual(set(classified_ids), set(observed_ids))

        direct_mcps = inventory["direct_mcps"]
        self.assertEqual(len(direct_mcps), counts["direct_mcp_observations"])
        self.assertEqual(
            {
                harness: sum(item["harness"] == harness for item in direct_mcps)
                for harness in ("claude", "codex", "cursor")
            },
            counts["direct_mcp_by_harness"],
        )
        self.assertEqual(
            len(inventory["plugin_provided_mcps"]),
            counts["plugin_provided_mcp_observations"],
        )
        self.assertFalse(
            any(
                item["decision_state"].startswith("provisional")
                for item in inventory["proposed_managed_slice"]["mcp_decisions"]
            )
        )
        self.assertTrue(
            {
                "chrome-devtools-plugin-bundled-skills",
                "codex-github-plugin-bundled-skills",
            }.isdisjoint(
                {
                    item["id"]
                    for item in inventory["proposed_managed_slice"][
                        "pending_decisions"
                    ]
                }
            )
        )

        component_inventory = inventory["plugin_component_inventory"]
        observed_components = component_inventory["observed_plugins"]
        observed_plugin_keys = {
            (item["harness"], item["plugin_id"]) for item in observed_components
        }
        expected_plugin_keys = {
            ("claude", item["id"])
            for item in inventory["claude_plugins"]["states"]
        } | {
            ("codex", item["id"])
            for item in inventory["codex_plugins"]["states"]
        } | {("cursor", "*")}
        self.assertEqual(observed_plugin_keys, expected_plugin_keys)
        self.assertEqual(len(observed_components), len(observed_plugin_keys))
        self.assertEqual(
            component_inventory["summary"]["observed_plugin_records"],
            len(observed_components),
        )
        component_kinds = set(component_inventory["component_kinds"])
        named_component_ids: list[str] = []
        named_count = sum(
            len(plugin["components"]["known"])
            for plugin in observed_components
        )
        unnamed_count = sum(
            item["count"]
            for plugin in observed_components
            for item in plugin["components"]["counted_but_unnamed"]
        )
        for plugin in observed_components + component_inventory[
            "reviewed_not_installed_distributions"
        ]:
            components = plugin["components"]
            named = components["known"]
            named_component_ids.extend(
                item["component_identity"] for item in named
            )
            positive_kinds = {item["kind"] for item in named} | {
                item["kind"] for item in components["counted_but_unnamed"]
            }
            absent_kinds = set(components["confirmed_absent_kinds"])
            unknown_kinds = set(components["unknown_kinds"])
            self.assertEqual(
                positive_kinds | absent_kinds | unknown_kinds,
                component_kinds,
            )
            self.assertFalse(positive_kinds & absent_kinds)
            self.assertFalse(positive_kinds & unknown_kinds)
            self.assertFalse(absent_kinds & unknown_kinds)
        self.assertEqual(len(named_component_ids), len(set(named_component_ids)))
        self.assertEqual(
            component_inventory["summary"]["named_component_observations"],
            named_count,
        )
        self.assertEqual(
            component_inventory["summary"][
                "counted_but_unnamed_component_observations"
            ],
            unnamed_count,
        )

        standalone_classification = {
            name: group["classification"]
            for group in inventory["standalone_skills"]["classification_groups"]
            for name in group["names"]
        }
        self.assertEqual(
            standalone_classification["hyperframes-creative"],
            "duplicate_overlap_candidate",
        )
        computer_use = next(
            item
            for item in inventory["direct_mcps"]
            if item["harness"] == "codex" and item["name"] == "computer-use"
        )
        self.assertEqual(computer_use["classification"], "duplicate_overlap_candidate")
        self.assertEqual(
            computer_use["runtime_retirement_intent"],
            "none_without_explicit_adoption",
        )

    def test_proposed_initial_catalog_and_lock_are_complete_and_valid(self) -> None:
        catalog_path = ROOT / "docs/agent-equipment/initial-catalog.proposed.json"
        lock_path = ROOT / "docs/agent-equipment/initial-lock.proposed.json"

        result = DESIGN.load_and_validate(catalog_path, lock_path)
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        identities = {item["identity"] for item in catalog["equipment"]}

        self.assertEqual(result.diagnostics, ())
        self.assertIsNotNone(result.mutation_plan)
        self.assertEqual(
            lock["catalog_digest"], DESIGN.canonical_json_sha256(catalog)
        )
        self.assertEqual(
            len(lock["coverage"]),
            len(identities) * len(catalog["active_harnesses"]),
        )
        self.assertTrue(
            {
                "mcp:chrome-devtools/server",
                "mcp:context7/server",
                "mcp:firecrawl/server",
                "mcp:github/server",
                "mcp:greptile/server",
                "plugin:mattpocock/claude",
            }.issubset(identities)
        )
        self.assertEqual(
            len(
                {
                    identity
                    for identity in identities
                    if identity.startswith("skill:mattpocock/")
                }
            ),
            25,
        )
        self.assertEqual(len(catalog["retirements"]), 23)

        matt_record = next(
            entry.record
            for entry in result.coverage
            if entry.equipment_identity == "plugin:mattpocock/claude"
            and entry.harness == "claude"
        )
        matt_route = matt_record["provider_selection"]["routes"][0]
        self.assertEqual(
            matt_route["provider"]["plugin_id"],
            "mattpocock-skills@claude-plugins-official",
        )
        self.assertEqual(
            matt_route["restore"]["native_update_control"], "suppressible"
        )
        self.assertIn(
            "auto-update documentation",
            matt_route["restore"]["observation_source"],
        )
        self.assertEqual(
            matt_route["operations"]["suppress_native_update"]["disposition"],
            "operator_action",
        )

    def test_schemas_use_draft_2020_12_and_exact_one_of_shapes(self) -> None:
        catalog_schema = json.loads(
            (ROOT / "docs/agent-equipment/catalog-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        lock_schema = json.loads(
            (ROOT / "docs/agent-equipment/lock-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            catalog_schema["$schema"],
            "https://json-schema.org/draft/2020-12/schema",
        )
        self.assertEqual(lock_schema["$schema"], catalog_schema["$schema"])
        self.assertFalse(catalog_schema["additionalProperties"])
        self.assertFalse(lock_schema["additionalProperties"])
        self.assertIn("retirements", catalog_schema["required"])
        self.assertIn("retirements", lock_schema["required"])
        self.assertEqual(len(catalog_schema["$defs"]["coverageRecord"]["oneOf"]), 2)
        self.assertEqual(len(catalog_schema["$defs"]["restore"]["oneOf"]), 2)
        self.assertEqual(len(catalog_schema["$defs"]["selection"]["oneOf"]), 2)
        self.assertEqual(
            set(catalog_schema["$defs"]["operations"]["required"]),
            {
                "inspect",
                "install",
                "configure",
                "enable",
                "disable",
                "remove",
                "restore",
                "suppress_native_update",
            },
        )

    def test_canonical_digest_is_utf8_compact_and_key_sorted(self) -> None:
        self.assertEqual(
            DESIGN.canonical_json_sha256({"b": 1, "a": "é"}),
            "sha256:aa58fba8483623bed37c1b02edfccbdd9a53123837c20bfa4cb4049993a2872e",
        )

    def test_public_loader_validates_fixture_pair(self) -> None:
        result = DESIGN.load_and_validate(
            FIXTURES / "valid-catalog.json",
            FIXTURES / "valid-lock.json",
        )

        self.assertEqual(result.diagnostics, ())
        self.assertIsNotNone(result.mutation_plan)

    def test_public_validator_rejects_nested_catalog_schema_extensions(self) -> None:
        catalog, lock = valid_pair()
        catalog["coverage_templates"][0]["undocumented_extension"] = True
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "CATALOG_SCHEMA_INVALID",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        self.assertIsNone(result.mutation_plan)

    def test_public_validator_rejects_nested_lock_schema_extensions(self) -> None:
        catalog, lock = valid_pair()
        lock["coverage"][0]["record"]["undocumented_extension"] = True

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "LOCK_SCHEMA_INVALID",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        self.assertIsNone(result.mutation_plan)

    def test_public_validator_rejects_unimplemented_schema_keywords(self) -> None:
        catalog, lock = valid_pair()
        with TemporaryDirectory() as temporary_directory:
            schema_directory = Path(temporary_directory)
            for name in ("catalog-v1.schema.json", "lock-v1.schema.json"):
                schema = json.loads(
                    (ROOT / "docs/agent-equipment" / name).read_text(
                        encoding="utf-8"
                    )
                )
                if name == "catalog-v1.schema.json":
                    schema["futureAssertion"] = True
                (schema_directory / name).write_text(
                    json.dumps(schema), encoding="utf-8"
                )
            original_directory = DESIGN.SCHEMA_DIRECTORY
            DESIGN.SCHEMA_DIRECTORY = schema_directory
            try:
                result = DESIGN.validate_design(catalog, lock)
            finally:
                DESIGN.SCHEMA_DIRECTORY = original_directory

        self.assertIn(
            "CATALOG_SCHEMA_INVALID",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        self.assertIn("unsupported schema keyword", result.diagnostics[0].message)
        self.assertIsNone(result.mutation_plan)

    def test_public_validator_schema_fails_route_missing_identity_without_crashing(self) -> None:
        catalog, lock = valid_pair()
        managed_route(catalog).pop("identity")
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "CATALOG_SCHEMA_INVALID",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        self.assertIsNone(result.mutation_plan)

    def test_public_validator_schema_fails_non_object_documents_without_crashing(self) -> None:
        for catalog, lock, expected in (
            ([], {}, "CATALOG_SCHEMA_INVALID"),
            ({}, [], "LOCK_SCHEMA_INVALID"),
        ):
            with self.subTest(expected=expected):
                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(
                    expected,
                    {diagnostic.code for diagnostic in result.diagnostics},
                )
                self.assertIsNone(result.mutation_plan)

    def test_schema_invalid_leaf_types_fail_closed_without_crashing(self) -> None:
        mutations = (
            lambda catalog: catalog["active_harnesses"].__setitem__(0, {}),
            lambda catalog: catalog["distributions"][0].__setitem__(
                "identity", []
            ),
            lambda catalog: managed_route(catalog)["operations"]["install"].__setitem__(
                "disposition", {}
            ),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                catalog, lock = valid_pair()
                mutate(catalog)
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(
                    "CATALOG_SCHEMA_INVALID",
                    {diagnostic.code for diagnostic in result.diagnostics},
                )
                self.assertEqual(result.coverage, ())
                self.assertIsNone(result.mutation_plan)

    def test_valid_provider_and_no_provider_outcomes_resolve(self) -> None:
        catalog, lock = valid_pair()

        self.assertEqual(lock["catalog_digest"], DESIGN.canonical_json_sha256(catalog))

        result = DESIGN.validate_design(catalog, lock)

        self.assertEqual(result.diagnostics, ())
        self.assertEqual(
            [(entry.equipment_identity, entry.harness) for entry in result.coverage],
            [
                ("plugin:example/matt", "claude"),
                ("plugin:example/matt", "codex"),
                ("plugin:example/matt", "cursor"),
                ("skill:example/grilling", "claude"),
                ("skill:example/grilling", "codex"),
                ("skill:example/grilling", "cursor"),
            ],
        )
        self.assertIsNotNone(result.mutation_plan)
        self.assertEqual(
            {operation.operation for operation in result.mutation_plan},
            {
                "install",
                "configure",
                "enable",
                "disable",
                "remove",
                "restore",
                "suppress_native_update",
            },
        )
        self.assertEqual(
            {entry.record["outcome"] for entry in result.coverage},
            {
                "managed_provider",
                "manually_managed_provider",
                "intentional_omission",
                "unsupported",
            },
        )
        self.assertEqual(
            [operation.operation for operation in result.mutation_plan],
            [
                "install",
                "configure",
                "enable",
                "disable",
                "remove",
                "restore",
                "suppress_native_update",
            ],
        )

    def test_every_declared_equipment_kind_has_valid_and_invalid_examples(self) -> None:
        kinds = ("skill", "plugin", "mcp", "hook", "other")
        for kind in kinds:
            with self.subTest(kind=kind, validity="valid"):
                catalog, lock = valid_pair()
                identity = f"{kind}:example/additional"
                catalog["equipment"].append(
                    {"identity": identity, "kind": kind, "coverage": {}}
                )
                lock["distributions"][0]["equipment"].append(identity)
                for template in catalog["coverage_templates"]:
                    lock["coverage"].append(
                        {
                            "equipment_identity": identity,
                            "harness": template["harness"],
                            "record": deepcopy(template["record"]),
                        }
                    )
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                self.assertEqual(
                    DESIGN.validate_design(catalog, lock).diagnostics, ()
                )

            with self.subTest(kind=kind, validity="invalid"):
                catalog, lock = valid_pair()
                identity = f"{kind}:example/mismatched"
                mismatched_kind = "hook" if kind != "hook" else "other"
                catalog["equipment"].append(
                    {
                        "identity": identity,
                        "kind": mismatched_kind,
                        "coverage": {},
                    }
                )
                lock["distributions"][0]["equipment"].append(identity)
                for template in catalog["coverage_templates"]:
                    lock["coverage"].append(
                        {
                            "equipment_identity": identity,
                            "harness": template["harness"],
                            "record": deepcopy(template["record"]),
                        }
                    )
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(
                    "EQUIPMENT_IDENTITY_INVALID",
                    {diagnostic.code for diagnostic in result.diagnostics},
                )
                self.assertIsNone(result.mutation_plan)

    def test_shared_activation_group_produces_one_action_per_route_operation(self) -> None:
        catalog, lock = valid_pair()
        second_identity = "skill:example/research"
        lock["distributions"][0]["equipment"].append(second_identity)
        for harness, record in (
            ("claude", deepcopy(catalog["coverage_templates"][0]["record"])),
            ("codex", deepcopy(catalog["coverage_templates"][1]["record"])),
            ("cursor", deepcopy(catalog["coverage_templates"][2]["record"])),
        ):
            lock["coverage"].append(
                {
                    "equipment_identity": second_identity,
                    "harness": harness,
                    "record": record,
                }
            )

        result = DESIGN.validate_design(catalog, lock)

        self.assertEqual(result.diagnostics, ())
        self.assertEqual(len(result.mutation_plan), 7)
        self.assertTrue(
            all(
                operation.equipment_identities
                == ("skill:example/grilling", "skill:example/research")
                for operation in result.mutation_plan
            )
        )

    def test_distinct_routes_cannot_claim_one_activation_group(self) -> None:
        catalog, lock = valid_pair()
        second_identity = "skill:example/research"
        second_record = deepcopy(catalog["coverage_templates"][0]["record"])
        second_route = second_record["provider_selection"]["routes"][0]
        second_route["identity"] = "route:example/distinct-claude"
        second_record["provider_selection"][
            "preferred_route"
        ] = second_route["identity"]
        catalog["equipment"].append(
            {
                "identity": second_identity,
                "kind": "skill",
                "coverage": {"claude": {"record": second_record}},
            }
        )
        lock["distributions"][0]["equipment"].append(second_identity)
        for harness, record in (
            ("claude", deepcopy(second_record)),
            ("codex", deepcopy(catalog["coverage_templates"][1]["record"])),
            ("cursor", deepcopy(catalog["coverage_templates"][2]["record"])),
        ):
            lock["coverage"].append(
                {
                    "equipment_identity": second_identity,
                    "harness": harness,
                    "record": record,
                }
            )
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "ACTIVATION_GROUP_CONFLICT",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        self.assertIsNone(result.mutation_plan)

    def test_missing_harness_coverage_fails_closed(self) -> None:
        catalog, lock = valid_pair()
        catalog["distributions"][0]["coverage_templates"].pop("cursor")
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn("MISSING_HARNESS_COVERAGE", {item.code for item in result.diagnostics})
        self.assertIsNone(result.mutation_plan)

    def test_catalog_header_has_one_exact_versioned_shape(self) -> None:
        mutations = ("extra_field", "wrong_harness_order")
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                catalog, lock = valid_pair()
                if mutation == "extra_field":
                    catalog["derived_inventory"] = []
                else:
                    catalog["active_harnesses"] = ["codex", "claude", "cursor"]
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(
                    "CATALOG_SCHEMA_INVALID",
                    {item.code for item in result.diagnostics},
                )
                self.assertIsNone(result.mutation_plan)

    def test_catalog_identities_are_unique_by_category(self) -> None:
        mutations = (
            ("distributions", "DUPLICATE_CATALOG_IDENTITY"),
            ("coverage_templates", "DUPLICATE_CATALOG_IDENTITY"),
            ("equipment", "DUPLICATE_CATALOG_IDENTITY"),
        )
        for field, expected_code in mutations:
            with self.subTest(field=field):
                catalog, lock = valid_pair()
                catalog[field].append(deepcopy(catalog[field][0]))
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(expected_code, {item.code for item in result.diagnostics})
                self.assertIsNone(result.mutation_plan)

    def test_template_reference_must_match_target_harness(self) -> None:
        catalog, lock = valid_pair()
        catalog["distributions"][0]["coverage_templates"]["claude"] = (
            "template:bundle-codex"
        )
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn("TEMPLATE_HARNESS_MISMATCH", {item.code for item in result.diagnostics})
        self.assertIsNone(result.mutation_plan)

    def test_route_distribution_must_include_current_equipment(self) -> None:
        catalog, lock = valid_pair()
        native_restore = deepcopy(lock["distributions"][1]["restore"])
        route = managed_route(catalog)
        route["distribution"] = "distribution:example/native-plugin"
        route["restore"] = native_restore
        locked_managed_route(lock)["distribution"] = route["distribution"]
        locked_managed_route(lock)["restore"] = deepcopy(native_restore)
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "ROUTE_DISTRIBUTION_MEMBERSHIP_INVALID",
            {item.code for item in result.diagnostics},
        )
        self.assertIsNone(result.mutation_plan)

    def test_malformed_overlap_fields_return_diagnostics(self) -> None:
        catalog, lock = valid_pair()
        selection = managed_selection(catalog)
        supplementary = deepcopy(selection["routes"][0])
        supplementary["identity"] = "route:example/supplementary"
        selection["routes"].append(supplementary)
        selection["supplementary_routes"].append(supplementary["identity"])
        selection["allow_overlap"] = [
            {
                "kind": "allow_overlap",
                "supplementary_route": supplementary["identity"],
                "routes": None,
                "rationale": "Required together.",
            }
        ]
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "CATALOG_SCHEMA_INVALID",
            {item.code for item in result.diagnostics},
        )
        self.assertIsNone(result.mutation_plan)

    def test_component_controls_have_one_exact_non_conflicting_shape(self) -> None:
        catalog, lock = valid_pair()
        control = {
            "equipment_identity": "skill:example/grilling",
            "state": "enabled",
        }
        managed_route(catalog)["component_controls"] = [control]
        locked_managed_route(lock)["component_controls"] = [deepcopy(control)]
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)
        self.assertEqual(DESIGN.validate_design(catalog, lock).diagnostics, ())

        managed_route(catalog)["component_controls"].append(
            {
                "equipment_identity": "skill:example/grilling",
                "state": "disabled",
            }
        )
        locked_managed_route(lock)["component_controls"] = deepcopy(
            managed_route(catalog)["component_controls"]
        )
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn("COMPONENT_CONTROL_INVALID", {item.code for item in result.diagnostics})
        self.assertIsNone(result.mutation_plan)

    def test_active_route_cannot_disable_current_equipment_identity(self) -> None:
        catalog, lock = valid_pair()
        managed_route(catalog)["component_controls"] = [
            {
                "equipment_identity": "skill:example/grilling",
                "state": "disabled",
            }
        ]
        locked_record(lock).clear()
        locked_record(lock).update(deepcopy(
            catalog["coverage_templates"][0]["record"]
        ))
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "COMPONENT_CONTROL_INVALID",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        self.assertIsNone(result.mutation_plan)

    def test_component_control_must_belong_to_route_distribution(self) -> None:
        catalog, lock = valid_pair()
        managed_route(catalog)["component_controls"] = [
            {
                "equipment_identity": "skill:example/not-in-bundle",
                "state": "enabled",
            }
        ]
        locked_record(lock).clear()
        locked_record(lock).update(deepcopy(
            catalog["coverage_templates"][0]["record"]
        ))
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "COMPONENT_CONTROL_DISTRIBUTION_INVALID",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        self.assertIsNone(result.mutation_plan)

    def test_provider_configuration_is_typed_and_secret_safe(self) -> None:
        catalog, lock = valid_pair()
        provider = {
            "kind": "direct_mcp",
            "server_name": "context7",
            "transport": "stdio",
            "command": "secret-exec",
            "arguments": [
                {"literal": "context7"},
                {"literal": "--"},
                {"literal": "npx"},
                {"literal": "@upstash/context7-mcp@3.2.4"},
                {
                    "secret_reference": "EXAMPLE_API_KEY",
                    "template": "Authorization:Bearer {reference}",
                },
            ],
        }
        managed_route(catalog)["provider"] = provider
        managed_route(catalog)["secret_references"] = [
            {"kind": "environment_variable", "name": "EXAMPLE_API_KEY"}
        ]
        locked_managed_route(lock)["provider"] = deepcopy(provider)
        locked_managed_route(lock)["secret_references"] = deepcopy(
            managed_route(catalog)["secret_references"]
        )
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)
        self.assertEqual(DESIGN.validate_design(catalog, lock).diagnostics, ())

        managed_route(catalog)["provider"]["arguments"][-1][
            "secret_reference"
        ] = "UNDECLARED_SECRET"
        locked_managed_route(lock)["provider"] = deepcopy(
            managed_route(catalog)["provider"]
        )
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn("PROVIDER_CONFIGURATION_INVALID", {item.code for item in result.diagnostics})
        self.assertIsNone(result.mutation_plan)

    def test_literal_secret_material_fails_closed_without_echoing_it(self) -> None:
        catalog, lock = valid_pair()
        secret_canary = "Authorization: Bearer secret-canary-value"  # noqa: S105
        provider = {
            "kind": "direct_mcp",
            "server_name": "context7",
            "transport": "stdio",
            "command": "npx",
            "arguments": [{"literal": secret_canary}],
        }
        managed_route(catalog)["provider"] = deepcopy(provider)
        locked_managed_route(lock)["provider"] = deepcopy(provider)
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "LITERAL_SECRET_MATERIAL",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        self.assertTrue(
            all(secret_canary not in diagnostic.message for diagnostic in result.diagnostics)
        )
        self.assertIsNone(result.mutation_plan)

    def test_split_secret_flag_requires_structured_reference_argument(self) -> None:
        for flag in ("--api-key", "--token", "Authorization", "X-Api-Key"):
            with self.subTest(flag=flag):
                catalog, lock = valid_pair()
                literal_secret = "supersecretvalue"  # noqa: S105
                provider = {
                    "kind": "direct_mcp",
                    "server_name": "context7",
                    "transport": "stdio",
                    "command": "npx",
                    "arguments": [
                        {"literal": flag},
                        {"literal": literal_secret},
                    ],
                }
                managed_route(catalog)["provider"] = deepcopy(provider)
                locked_managed_route(lock)["provider"] = deepcopy(provider)
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(
                    "PROVIDER_CONFIGURATION_INVALID",
                    {diagnostic.code for diagnostic in result.diagnostics},
                )
                self.assertIsNone(result.mutation_plan)

    def test_benign_canary_label_is_not_treated_as_secret_material(self) -> None:
        catalog, lock = valid_pair()
        catalog["distributions"][0]["source"]["ref"] = "canary"
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        self.assertEqual(DESIGN.validate_design(catalog, lock).diagnostics, ())

    def test_catalog_source_and_namespaced_identities_are_validated(self) -> None:
        mutations = (
            ("source", "CATALOG_SCHEMA_INVALID"),
            ("distribution_identity", "CATALOG_SCHEMA_INVALID"),
            ("equipment_identity", "LOCK_SCHEMA_INVALID"),
            ("activation_group", "CATALOG_SCHEMA_INVALID"),
        )
        for mutation, expected in mutations:
            with self.subTest(mutation=mutation):
                catalog, lock = valid_pair()
                if mutation == "source":
                    catalog["distributions"][0]["source"] = {
                        "kind": "git",
                        "repository": "",
                        "ref": "",
                    }
                elif mutation == "distribution_identity":
                    catalog["distributions"][0]["identity"] = "not-namespaced"
                elif mutation == "equipment_identity":
                    lock["distributions"][0]["equipment"][0] = "not-namespaced"
                else:
                    managed_route(catalog)["activation_group"] = "not-namespaced"
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(expected, {item.code for item in result.diagnostics})
                self.assertIsNone(result.mutation_plan)

    def test_bare_outcome_and_single_route_shorthand_are_rejected(self) -> None:
        for invalid_record in (
            "intentional_omission",
            {
                "outcome": "managed_provider",
                "provider_selection": {"identity": "route:example/shorthand"},
            },
        ):
            with self.subTest(invalid_record=invalid_record):
                catalog, lock = valid_pair()
                catalog["equipment"][0]["coverage"]["codex"] = {
                    "record": deepcopy(invalid_record)
                }
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(
                    "CATALOG_SCHEMA_INVALID",
                    {item.code for item in result.diagnostics},
                )
                self.assertIsNone(result.mutation_plan)

    def test_stale_catalog_lock_digest_is_rejected(self) -> None:
        catalog, lock = valid_pair()
        catalog["equipment"][0]["identity"] = "plugin:example/renamed"

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn("LOCK_CATALOG_DIGEST_STALE", {item.code for item in result.diagnostics})
        self.assertIsNone(result.mutation_plan)

    def test_catalog_owned_retirement_plans_only_its_exact_surface_operation(self) -> None:
        catalog, lock = valid_pair()
        retirement = valid_retirement(catalog)
        catalog["retirements"].append(retirement)
        lock["retirements"].append(deepcopy(retirement))
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertEqual(result.diagnostics, ())
        self.assertIn(
            DESIGN.PlannedOperation(
                equipment_identities=("skill:example/grilling",),
                harness="claude",
                route_identity="route:example/legacy-claude-projection",
                activation_group="activation:example/legacy-claude-projection",
                operation="remove",
            ),
            result.mutation_plan,
        )

    def test_retirement_rejects_unowned_or_ambiguous_surface(self) -> None:
        mutations = (
            ("duplicate_selector", "DUPLICATE_RETIREMENT_SURFACE"),
            ("active_route", "RETIREMENT_ROUTE_ACTIVE"),
            ("unknown_equipment", "RETIREMENT_REFERENCE_INVALID"),
            ("unknown_distribution", "RETIREMENT_REFERENCE_INVALID"),
            ("invalid_state", "RETIREMENT_SURFACE_INVALID"),
            ("operator_owned", "RETIREMENT_OWNER_INVALID"),
            ("missing_compensation", "AUTOMATED_COMPENSATION_MISSING"),
        )
        for mutation, expected in mutations:
            with self.subTest(mutation=mutation):
                catalog, lock = valid_pair()
                retirement = valid_retirement(catalog)
                catalog["retirements"].append(retirement)
                if mutation == "duplicate_selector":
                    duplicate = deepcopy(retirement)
                    duplicate["identity"] = "retirement:example/duplicate"
                    duplicate["route"]["identity"] = "route:example/duplicate"
                    catalog["retirements"].append(duplicate)
                elif mutation == "active_route":
                    retirement["route"]["identity"] = managed_route(catalog)["identity"]
                elif mutation == "unknown_equipment":
                    retirement["equipment_identity"] = "skill:example/not-selected"
                elif mutation == "unknown_distribution":
                    retirement["route"]["distribution"] = "distribution:example/not-selected"
                elif mutation == "invalid_state":
                    retirement["desired_state"] = "disabled"
                elif mutation == "operator_owned":
                    retirement["route"]["control_owner"] = "operator_owned"
                else:
                    retirement["route"]["operations"]["remove"].pop("compensation")
                lock["retirements"] = deepcopy(catalog["retirements"])
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(expected, {item.code for item in result.diagnostics})
                self.assertIsNone(result.mutation_plan)

    def test_retirement_lock_must_match_catalog_exactly(self) -> None:
        catalog, lock = valid_pair()
        retirement = valid_retirement(catalog)
        catalog["retirements"].append(retirement)
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "LOCK_RETIREMENT_MISMATCH",
            {item.code for item in result.diagnostics},
        )
        self.assertIsNone(result.mutation_plan)

    def test_duplicate_or_incomplete_lock_coverage_is_rejected(self) -> None:
        mutations = ("duplicate", "missing")
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                catalog, lock = valid_pair()
                if mutation == "duplicate":
                    lock["coverage"].append(deepcopy(lock["coverage"][0]))
                    expected = "DUPLICATE_LOCK_COVERAGE"
                else:
                    lock["coverage"].pop()
                    expected = "LOCK_COVERAGE_MISMATCH"

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(expected, {item.code for item in result.diagnostics})
                self.assertIsNone(result.mutation_plan)

    def test_an_invalid_final_entry_yields_no_plan(self) -> None:
        catalog, lock = valid_pair()
        final_equipment = {
            "identity": "skill:zzz/final-invalid",
            "kind": "skill",
            "coverage": {},
        }
        final_record = deepcopy(catalog["coverage_templates"][0]["record"])
        final_record["provider_selection"]["routes"][0]["operations"]["install"].pop(
            "compensation"
        )
        final_equipment["coverage"] = {"claude": {"record": final_record}}
        catalog["equipment"].append(final_equipment)
        lock["distributions"][0]["equipment"].append(final_equipment["identity"])
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertEqual(result.coverage[-1].equipment_identity, "skill:zzz/final-invalid")
        self.assertIn(
            "AUTOMATED_COMPENSATION_MISSING",
            {item.code for item in result.diagnostics},
        )
        self.assertIsNone(result.mutation_plan)

    def test_resolution_is_deterministic_under_input_ordering(self) -> None:
        catalog, lock = valid_pair()
        expected = DESIGN.validate_design(catalog, lock)
        reordered_catalog = deepcopy(catalog)
        for key in ("distributions", "coverage_templates", "equipment"):
            reordered_catalog[key].reverse()
        reordered_lock = deepcopy(lock)
        reordered_lock["catalog_digest"] = DESIGN.canonical_json_sha256(reordered_catalog)
        reordered_lock["distributions"].reverse()
        reordered_lock["coverage"].reverse()

        actual = DESIGN.validate_design(reordered_catalog, reordered_lock)

        self.assertEqual(actual.diagnostics, expected.diagnostics)
        self.assertEqual(actual.coverage, expected.coverage)
        self.assertEqual(actual.mutation_plan, expected.mutation_plan)

    def test_duplicate_route_identity_is_rejected(self) -> None:
        catalog, lock = valid_pair()
        routes = catalog["coverage_templates"][0]["record"]["provider_selection"]["routes"]
        routes.append(deepcopy(routes[0]))
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn("DUPLICATE_ROUTE_IDENTITY", {item.code for item in result.diagnostics})
        self.assertIsNone(result.mutation_plan)

    def test_shared_route_identity_requires_one_complete_route_record(self) -> None:
        catalog, lock = valid_pair()
        second_identity = "skill:example/route-conflict"
        second_record = deepcopy(catalog["coverage_templates"][0]["record"])
        second_record["provider_selection"]["routes"][0]["provenance"] = {
            "owner": "source:example/different-owner"
        }
        catalog["equipment"].append(
            {
                "identity": second_identity,
                "kind": "skill",
                "coverage": {"claude": {"record": second_record}},
            }
        )
        lock["distributions"][0]["equipment"].append(second_identity)
        for harness, record in (
            ("claude", deepcopy(second_record)),
            ("codex", deepcopy(catalog["coverage_templates"][1]["record"])),
            ("cursor", deepcopy(catalog["coverage_templates"][2]["record"])),
        ):
            lock["coverage"].append(
                {
                    "equipment_identity": second_identity,
                    "harness": harness,
                    "record": record,
                }
            )
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "ROUTE_IDENTITY_CONFLICT",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        self.assertIsNone(result.mutation_plan)

    def test_supplementary_route_requires_exact_allow_overlap(self) -> None:
        catalog, lock = valid_pair()
        selection = managed_selection(catalog)
        supplementary = deepcopy(selection["routes"][0])
        supplementary["identity"] = "route:example/supplementary"
        selection["routes"].append(supplementary)
        selection["supplementary_routes"].append(supplementary["identity"])
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn("OVERLAP_INVALID", {item.code for item in result.diagnostics})
        self.assertIsNone(result.mutation_plan)

    def test_provider_outcome_must_match_route_control_owners(self) -> None:
        mutations = (
            (managed_route, "operator_owned", "COVERAGE_OWNER_MISMATCH"),
            (manual_route, "reconciler_owned", "COVERAGE_OWNER_MISMATCH"),
        )
        for route_getter, owner, expected_code in mutations:
            with self.subTest(owner=owner):
                catalog, lock = valid_pair()
                route_getter(catalog)["control_owner"] = owner
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(expected_code, {item.code for item in result.diagnostics})
                self.assertIsNone(result.mutation_plan)

    def test_operator_owned_route_rejects_automated_mutation(self) -> None:
        catalog, lock = valid_pair()
        manual_route(catalog)["operations"]["install"] = {
            "disposition": "automated",
            "compensation": "restore_captured_pre_state",
        }
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn("OPERATOR_AUTOMATION_INVALID", {item.code for item in result.diagnostics})
        self.assertIsNone(result.mutation_plan)

    def test_automated_mutation_requires_pre_state_compensation(self) -> None:
        catalog, lock = valid_pair()
        managed_route(catalog)["operations"]["install"] = {
            "disposition": "automated"
        }
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "AUTOMATED_COMPENSATION_MISSING",
            {item.code for item in result.diagnostics},
        )
        self.assertIsNone(result.mutation_plan)

    def test_operation_matrix_is_exact_and_complete(self) -> None:
        for operation_mutation in ("missing", "extra"):
            with self.subTest(operation_mutation=operation_mutation):
                catalog, lock = valid_pair()
                operations = managed_route(catalog)["operations"]
                if operation_mutation == "missing":
                    operations.pop("restore")
                else:
                    operations["repair"] = {"disposition": "unavailable"}
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(
                    "CATALOG_SCHEMA_INVALID",
                    {item.code for item in result.diagnostics},
                )
                self.assertIsNone(result.mutation_plan)

    def test_provenance_has_exactly_one_owner(self) -> None:
        for provenance in ({}, {"owner": "source:example/bundle", "owners": ["other"]}):
            with self.subTest(provenance=provenance):
                catalog, lock = valid_pair()
                managed_route(catalog)["provenance"] = provenance
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(
                    "CATALOG_SCHEMA_INVALID",
                    {item.code for item in result.diagnostics},
                )
                self.assertIsNone(result.mutation_plan)

    def test_immutable_restore_requires_revision_reference_digest_and_update_control(self) -> None:
        for missing_field in (
            "revision",
            "artifact_ref",
            "content_digest",
            "native_update_control",
        ):
            with self.subTest(missing_field=missing_field):
                catalog, lock = valid_pair()
                managed_route(catalog)["restore"].pop(missing_field)
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(
                    "CATALOG_SCHEMA_INVALID",
                    {item.code for item in result.diagnostics},
                )
                self.assertIsNone(result.mutation_plan)

        catalog, lock = valid_pair()
        managed_route(catalog)["restore"]["native_update_control"] = "unknown"
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "CATALOG_SCHEMA_INVALID",
            {item.code for item in result.diagnostics},
        )
        self.assertIsNone(result.mutation_plan)

    def test_native_rolling_restore_requires_reviewed_update_state(self) -> None:
        for missing_field in (
            "channel",
            "reviewed_baseline",
            "observation_source",
            "native_update_control",
        ):
            with self.subTest(missing_field=missing_field):
                catalog, lock = valid_pair()
                manual_route(catalog)["restore"].pop(missing_field)
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(
                    "CATALOG_SCHEMA_INVALID",
                    {item.code for item in result.diagnostics},
                )
                self.assertIsNone(result.mutation_plan)

    def test_secret_references_accept_environment_variables_and_opaque_profiles(self) -> None:
        catalog, lock = valid_pair()
        managed_route(catalog)["secret_references"] = [
            {"kind": "environment_variable", "name": "EXAMPLE_API_KEY"},
            {"kind": "secret_profile", "name": "context7"},
        ]
        locked_record(lock).clear()
        locked_record(lock).update(deepcopy(
            catalog["coverage_templates"][0]["record"]
        ))
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)
        self.assertEqual(DESIGN.validate_design(catalog, lock).diagnostics, ())

        for invalid_reference in (
            {"kind": "literal", "value": "not-a-secret-fixture"},
            {"kind": "file", "path": "fixture-secret-path"},
            {"kind": "secret_profile", "name": "Context 7"},
            {"kind": "environment_variable", "name": "lowercase"},
        ):
            with self.subTest(invalid_reference=invalid_reference):
                invalid_catalog = deepcopy(catalog)
                invalid_lock = deepcopy(lock)
                managed_route(invalid_catalog)["secret_references"] = [invalid_reference]
                invalid_lock["catalog_digest"] = DESIGN.canonical_json_sha256(invalid_catalog)

                result = DESIGN.validate_design(invalid_catalog, invalid_lock)

                self.assertIn(
                    "CATALOG_SCHEMA_INVALID",
                    {item.code for item in result.diagnostics},
                )
                self.assertIsNone(result.mutation_plan)


if __name__ == "__main__":
    unittest.main()
