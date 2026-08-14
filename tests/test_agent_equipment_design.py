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


def literal_credential_samples() -> tuple[str, ...]:
    authorization = "Author" + "ization:"
    bearer_value = " Bear" + "er actual-secret-value"
    query_credential = "to" + "ken=actual-secret-value"
    provider_credential = "gh" + "p_" + "A" * 20
    return (
        *("gh" + prefix + "_" + "A" * 20 for prefix in "pousr"),
        "github" + "_pat_" + "A" * 20,
        "AK" + "IA" + "A" * 16,
        "s" + "k-" + "A" * 20,
        "p" + "st_" + "A" * 12 + "::" + "B" * 8,
        authorization + bearer_value,
        authorization.casefold() + " opaque-secret-value",
        "https://example.invalid/mcp?" + query_credential,
        "api_" + "key=\"actual-secret-value\"",
        "${{" + repr(provider_credential) + "}}",
        "-----BEGIN " + "PRIVATE KEY-----",
        "-----BEGIN " + "OPENSSH " + "PRIVATE KEY-----",
        "AGE-" + "SECRET-KEY-" + "A" * 32,
    )


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
            "skill_name": "grilling",
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


def bind_managed_distribution_to_direct_mcp(
    catalog: dict[str, object],
    lock: dict[str, object],
    *,
    package: str,
    channel: str,
) -> None:
    source = {
        "kind": "native_manager",
        "manager": "npx",
        "package": package,
        "channel": channel,
    }
    restore = {
        "class": "native_rolling",
        "channel": f"npm:{channel}",
        "reviewed_baseline": f"{package}@{channel}",
        "observation_source": "fixture provider selector",
        "native_update_control": "suppressible",
    }
    catalog["distributions"][0]["source"] = deepcopy(source)
    lock["distributions"][0]["source"] = deepcopy(source)
    lock["distributions"][0]["restore"] = deepcopy(restore)
    managed_route(catalog)["restore"] = deepcopy(restore)
    locked_managed_route(lock)["restore"] = deepcopy(restore)


def bind_managed_distribution_to_static_https(
    catalog: dict[str, object], lock: dict[str, object], *, url: str
) -> None:
    source = {
        "kind": "native_manager",
        "manager": "http",
        "package": url,
        "channel": "static",
    }
    restore = {
        "class": "native_rolling",
        "channel": "static",
        "reviewed_baseline": url,
        "observation_source": "fixture static credential-free endpoint",
        "native_update_control": "unsuppressible",
    }
    catalog["distributions"][0]["source"] = deepcopy(source)
    lock["distributions"][0]["source"] = deepcopy(source)
    lock["distributions"][0]["restore"] = deepcopy(restore)
    managed_route(catalog)["restore"] = deepcopy(restore)
    locked_managed_route(lock)["restore"] = deepcopy(restore)


def iter_routes(value: object):
    if isinstance(value, dict):
        if {
            "identity",
            "distribution",
            "provider",
            "component_controls",
            "operations",
        }.issubset(value):
            yield value
        for item in value.values():
            yield from iter_routes(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_routes(item)


class AgentEquipmentDesignTest(unittest.TestCase):
    def test_inventory_references_the_canonical_proposal_without_redeclaring_it(
        self,
    ) -> None:
        inventory = json.loads(
            (ROOT / "docs/agent-equipment/initial-inventory.json").read_text(
                encoding="utf-8"
            )
        )

        proposed_slice = inventory["proposed_managed_slice"]
        self.assertEqual(
            proposed_slice["canonical_proposal"],
            {
                "catalog": "initial-catalog.proposed.json",
                "lock": "initial-lock.proposed.json",
            },
        )
        self.assertEqual(
            set(proposed_slice),
            {"canonical_proposal", "pending_decisions", "reviewed_inputs", "status"},
        )

    def test_selected_observed_direct_mcps_are_classified_for_adoption(self) -> None:
        inventory = json.loads(
            (ROOT / "docs/agent-equipment/initial-inventory.json").read_text(
                encoding="utf-8"
            )
        )
        result = DESIGN.load_and_validate(
            ROOT / "docs/agent-equipment/initial-catalog.proposed.json",
            ROOT / "docs/agent-equipment/initial-lock.proposed.json",
        )
        observed = {
            (item["harness"], item["name"]): item
            for item in inventory["direct_mcps"]
        }
        selected_observed: dict[tuple[str, str], dict[str, object]] = {}
        for coverage in result.coverage:
            selection = coverage.record["provider_selection"]
            if selection == "no_provider":
                continue
            preferred_route = next(
                route
                for route in selection["routes"]
                if route["identity"] == selection["preferred_route"]
            )
            provider = preferred_route["provider"]
            if provider["kind"] != "direct_mcp":
                continue
            observation_key = (coverage.harness, provider["server_name"])
            if observation_key in observed:
                selected_observed[observation_key] = observed[observation_key]

        self.assertTrue(selected_observed)
        for observation_key, observation in selected_observed.items():
            with self.subTest(observation=observation_key):
                self.assertEqual(
                    observation["classification"],
                    "proposed_managed_equipment_slice",
                )
                self.assertIn(
                    observation["ownership_intent"],
                    {
                        "propose_catalog_adoption",
                        "propose_catalog_adoption_for_retirement",
                    },
                )

    def test_initial_inventory_counts_and_classifications_are_complete(self) -> None:
        inventory = json.loads(
            (ROOT / "docs/agent-equipment/initial-inventory.json").read_text(
                encoding="utf-8"
            )
        )
        counts = inventory["counts"]

        standalone_classification_counts = dict.fromkeys(
            inventory["snapshot"]["classification_values"], 0
        )
        for group in inventory["standalone_skills"]["classification_groups"]:
            self.assertIn(group["classification"], standalone_classification_counts)
            standalone_classification_counts[group["classification"]] += len(
                group["names"]
            )
        self.assertEqual(
            standalone_classification_counts,
            counts["standalone_by_classification"],
        )

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
        self.assertEqual(
            {
                harness: sum(
                    item["harness"] == harness
                    for item in inventory["plugin_provided_mcps"]
                )
                for harness in ("claude", "codex", "cursor")
            },
            counts["plugin_provided_mcp_by_harness"],
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
        self.assertEqual(len(catalog["retirements"]), 23)
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

    def test_claude_chrome_devtools_proposal_uses_marketplace_update_control(
        self,
    ) -> None:
        catalog = json.loads(
            (ROOT / "docs/agent-equipment/initial-catalog.proposed.json").read_text(
                encoding="utf-8"
            )
        )
        lock = json.loads(
            (ROOT / "docs/agent-equipment/initial-lock.proposed.json").read_text(
                encoding="utf-8"
            )
        )

        route_groups = tuple(
            tuple(
                route
                for route in iter_routes(document)
                if route.get("identity")
                == "route:claude/chrome-devtools-plugin"
            )
            for document in (catalog, lock)
        )

        self.assertEqual(tuple(map(len, route_groups)), (1, 8))
        for routes in route_groups:
            for route in routes:
                self.assertEqual(route["restore"]["class"], "native_rolling")
                self.assertEqual(
                    route["restore"]["native_update_control"], "suppressible"
                )
                self.assertEqual(
                    route["operations"]["suppress_native_update"]["disposition"],
                    "operator_action",
                )

    def test_disabled_no_provider_component_is_controlled_but_not_active(self) -> None:
        result = DESIGN.load_and_validate(
            ROOT / "docs/agent-equipment/initial-catalog.proposed.json",
            ROOT / "docs/agent-equipment/initial-lock.proposed.json",
        )

        github_actions = tuple(
            action
            for action in result.mutation_plan or ()
            if action.route_identity == "route:codex/github-plugin"
        )

        self.assertTrue(github_actions)
        for action in github_actions:
            self.assertNotIn("skill:github/yeet", action.equipment_identities)
            self.assertIn(
                "skill:github/yeet", action.controlled_equipment_identities
            )

    def test_enabled_component_control_requires_active_same_route_coverage(self) -> None:
        catalog = json.loads(
            (ROOT / "docs/agent-equipment/initial-catalog.proposed.json").read_text(
                encoding="utf-8"
            )
        )
        lock = json.loads(
            (ROOT / "docs/agent-equipment/initial-lock.proposed.json").read_text(
                encoding="utf-8"
            )
        )
        for document in (catalog, lock):
            for route in iter_routes(document):
                if route.get("identity") != "route:codex/github-plugin":
                    continue
                next(
                    control
                    for control in route["component_controls"]
                    if control["equipment_identity"] == "skill:github/yeet"
                )["state"] = "enabled"
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "ENABLED_COMPONENT_CONTROL_COVERAGE_INVALID",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        self.assertIsNone(result.mutation_plan)

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

    def test_public_loader_rejects_a_missing_catalog_or_lock(self) -> None:
        catalog, lock = valid_pair()
        for missing_document in ("catalog", "lock"):
            with self.subTest(missing_document=missing_document):
                with TemporaryDirectory() as temporary_directory:
                    directory = Path(temporary_directory)
                    catalog_path = directory / "catalog.json"
                    lock_path = directory / "lock.json"
                    if missing_document != "catalog":
                        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
                    if missing_document != "lock":
                        lock_path.write_text(json.dumps(lock), encoding="utf-8")

                    result = DESIGN.load_and_validate(catalog_path, lock_path)

                self.assertEqual(
                    {diagnostic.code for diagnostic in result.diagnostics},
                    {"DOCUMENT_PARSE_INVALID"},
                )
                self.assertEqual(result.coverage, ())
                self.assertIsNone(result.mutation_plan)

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

    def test_loader_rejects_duplicate_object_members_before_validation(self) -> None:
        for before, after in (
            (
                '"schema_version": "catalog/v1"',
                '"schema_version": "catalog/v1", "schema_version": "catalog/v1"',
            ),
            (
                '"canonical_root": "agents_skills"',
                '"canonical_root": "agents_skills", "canonical_root": "agents_skills"',
            ),
        ):
            with self.subTest(member=before):
                catalog, lock = valid_pair()
                with TemporaryDirectory() as temporary_directory:
                    directory = Path(temporary_directory)
                    catalog_path = directory / "catalog.json"
                    lock_path = directory / "lock.json"
                    catalog_path.write_text(
                        json.dumps(catalog).replace(before, after, 1),
                        encoding="utf-8",
                    )
                    lock_path.write_text(json.dumps(lock), encoding="utf-8")

                    result = DESIGN.load_and_validate(catalog_path, lock_path)

                self.assertIn(
                    "DOCUMENT_PARSE_INVALID",
                    {diagnostic.code for diagnostic in result.diagnostics},
                )
                self.assertEqual(result.coverage, ())
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
        self.assertIn("closed local schema set is invalid", result.diagnostics[0].message)
        self.assertIsNone(result.mutation_plan)

    def test_public_validator_fails_closed_when_checked_in_schemas_are_unavailable(
        self,
    ) -> None:
        catalog, lock = valid_pair()
        with TemporaryDirectory() as temporary_directory:
            original_directory = DESIGN.SCHEMA_DIRECTORY
            DESIGN.SCHEMA_DIRECTORY = Path(temporary_directory)
            try:
                result = DESIGN.validate_design(catalog, lock)
            finally:
                DESIGN.SCHEMA_DIRECTORY = original_directory

        self.assertIn(
            "CATALOG_SCHEMA_INVALID",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        self.assertEqual(result.coverage, ())
        self.assertIsNone(result.mutation_plan)

    def test_public_validator_fails_closed_on_non_object_schema_roots(self) -> None:
        catalog, lock = valid_pair()
        for invalid_schema in ([], None):
            with self.subTest(invalid_schema=invalid_schema):
                with TemporaryDirectory() as temporary_directory:
                    schema_directory = Path(temporary_directory)
                    (schema_directory / "catalog-v1.schema.json").write_text(
                        json.dumps(invalid_schema), encoding="utf-8"
                    )
                    (schema_directory / "lock-v1.schema.json").write_text(
                        (ROOT / "docs/agent-equipment/lock-v1.schema.json").read_text(
                            encoding="utf-8"
                        ),
                        encoding="utf-8",
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
                self.assertEqual(result.coverage, ())
                self.assertIsNone(result.mutation_plan)

    def test_public_validator_rejects_unsupported_array_valued_schema_types(
        self,
    ) -> None:
        catalog, lock = valid_pair()
        with TemporaryDirectory() as temporary_directory:
            schema_directory = Path(temporary_directory)
            catalog_schema = json.loads(
                (ROOT / "docs/agent-equipment/catalog-v1.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            catalog_schema["type"] = ["object", "null"]
            (schema_directory / "catalog-v1.schema.json").write_text(
                json.dumps(catalog_schema), encoding="utf-8"
            )
            (schema_directory / "lock-v1.schema.json").write_text(
                (ROOT / "docs/agent-equipment/lock-v1.schema.json").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
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
        self.assertEqual(result.coverage, ())
        self.assertIsNone(result.mutation_plan)

    def test_public_validator_rejects_malformed_nested_schemas(self) -> None:
        catalog, lock = valid_pair()
        with TemporaryDirectory() as temporary_directory:
            schema_directory = Path(temporary_directory)
            catalog_schema = json.loads(
                (ROOT / "docs/agent-equipment/catalog-v1.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            catalog_schema["properties"]["schema_version"] = []
            (schema_directory / "catalog-v1.schema.json").write_text(
                json.dumps(catalog_schema), encoding="utf-8"
            )
            (schema_directory / "lock-v1.schema.json").write_text(
                (ROOT / "docs/agent-equipment/lock-v1.schema.json").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
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
        self.assertEqual(result.coverage, ())
        self.assertIsNone(result.mutation_plan)

    def test_public_validator_rejects_malformed_supported_schema_keywords(
        self,
    ) -> None:
        catalog, lock = valid_pair()
        for schema_name, expected_code in (
            ("catalog-v1.schema.json", "CATALOG_SCHEMA_INVALID"),
            ("lock-v1.schema.json", "LOCK_SCHEMA_INVALID"),
        ):
            with self.subTest(schema_name=schema_name):
                with TemporaryDirectory() as temporary_directory:
                    schema_directory = Path(temporary_directory)
                    for name in ("catalog-v1.schema.json", "lock-v1.schema.json"):
                        schema = json.loads(
                            (ROOT / "docs/agent-equipment" / name).read_text(
                                encoding="utf-8"
                            )
                        )
                        if name == schema_name:
                            schema["required"] = {}
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
                    expected_code,
                    {diagnostic.code for diagnostic in result.diagnostics},
                )
                self.assertEqual(result.coverage, ())
                self.assertIsNone(result.mutation_plan)

    def test_public_validator_rejects_cyclic_schema_references_without_crashing(
        self,
    ) -> None:
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
                    schema["$ref"] = "#"
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
        self.assertEqual(result.coverage, ())
        self.assertIsNone(result.mutation_plan)

    def test_public_schema_gate_distinguishes_booleans_from_integers(self) -> None:
        catalog, lock = valid_pair()
        catalog["distributions"][0]["selection"]["all"] = 1
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "CATALOG_SCHEMA_INVALID",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        self.assertEqual(result.coverage, ())
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
        self.assertEqual(len(result.mutation_plan), 6)
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

        catalog, lock = valid_pair()
        managed_route(catalog)["component_controls"] = [control, deepcopy(control)]
        locked_managed_route(lock)["component_controls"] = deepcopy(
            managed_route(catalog)["component_controls"]
        )
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "CATALOG_SCHEMA_INVALID",
            {item.code for item in result.diagnostics},
        )
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
            "command": "npx",
            "arguments": [
                {"literal": "-y"},
                {"literal": "@upstash/context7-mcp@3.2.4"},
                {
                    "secret_reference": "EXAMPLE_API_KEY",
                    "template": "Authorization:Bearer {reference}",
                },
            ],
        }
        managed_route(catalog)["provider"] = provider
        managed_route(catalog)["provenance"] = {"owner": "overlay:claude/mcp"}
        managed_route(catalog)["secret_references"] = [
            {"kind": "environment_variable", "name": "EXAMPLE_API_KEY"}
        ]
        locked_managed_route(lock)["provider"] = deepcopy(provider)
        locked_managed_route(lock)["provenance"] = deepcopy(
            managed_route(catalog)["provenance"]
        )
        locked_managed_route(lock)["secret_references"] = deepcopy(
            managed_route(catalog)["secret_references"]
        )
        bind_managed_distribution_to_direct_mcp(
            catalog, lock, package="@upstash/context7-mcp", channel="3.2.4"
        )
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)
        self.assertEqual(DESIGN.validate_design(catalog, lock).diagnostics, ())

        for invalid_arguments in (
            [
                {"secret_profile_reference": "github"},
                {"literal": "--"},
                {"literal": "npx"},
            ],
            [
                {"literal": "context7"},
                {"literal": "--"},
                {"literal": "npx"},
            ],
        ):
            with self.subTest(arguments=invalid_arguments):
                invalid_catalog = deepcopy(catalog)
                invalid_lock = deepcopy(lock)
                managed_route(invalid_catalog)["provider"]["arguments"] = (
                    invalid_arguments
                )
                locked_managed_route(invalid_lock)["provider"] = deepcopy(
                    managed_route(invalid_catalog)["provider"]
                )
                invalid_lock["catalog_digest"] = DESIGN.canonical_json_sha256(
                    invalid_catalog
                )

                result = DESIGN.validate_design(invalid_catalog, invalid_lock)

                self.assertIn(
                    "PROVIDER_CONFIGURATION_INVALID",
                    {diagnostic.code for diagnostic in result.diagnostics},
                )
                self.assertIsNone(result.mutation_plan)

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

    def test_secret_exec_profile_is_a_typed_consumed_reference(self) -> None:
        catalog, lock = valid_pair()
        provider = {
            "kind": "direct_mcp",
            "server_name": "context7",
            "transport": "stdio",
            "command": "secret-exec",
            "arguments": [
                {"secret_profile_reference": "context7"},
                {"literal": "--"},
                {"literal": "npx"},
                {"literal": "@upstash/context7-mcp@3.2.4"},
            ],
        }
        managed_route(catalog)["provider"] = deepcopy(provider)
        managed_route(catalog)["provenance"] = {"owner": "overlay:claude/mcp"}
        managed_route(catalog)["secret_references"] = [
            {"kind": "secret_profile", "name": "context7"}
        ]
        locked_managed_route(lock)["provider"] = deepcopy(provider)
        locked_managed_route(lock)["provenance"] = deepcopy(
            managed_route(catalog)["provenance"]
        )
        locked_managed_route(lock)["secret_references"] = deepcopy(
            managed_route(catalog)["secret_references"]
        )
        bind_managed_distribution_to_direct_mcp(
            catalog, lock, package="@upstash/context7-mcp", channel="3.2.4"
        )
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        self.assertEqual(DESIGN.validate_design(catalog, lock).diagnostics, ())

    def test_literal_secret_material_fails_closed_without_echoing_it(self) -> None:
        catalog, lock = valid_pair()
        secret_canary = (
            "Author" + "ization:" + " Bear" + "er secret-canary-value"
        )  # noqa: S105
        provider = {
            "kind": "direct_mcp",
            "server_name": "context7",
            "transport": "stdio",
            "command": "npx",
            "arguments": [{"literal": secret_canary}],
        }
        managed_route(catalog)["provider"] = deepcopy(provider)
        managed_route(catalog)["provenance"] = {"owner": "overlay:claude/mcp"}
        locked_managed_route(lock)["provider"] = deepcopy(provider)
        locked_managed_route(lock)["provenance"] = deepcopy(
            managed_route(catalog)["provenance"]
        )
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

    def test_literal_credential_stops_before_identifier_diagnostics_can_echo_it(
        self,
    ) -> None:
        catalog, lock = valid_pair()
        literal_credential = "gh" + "p_" + "a" * 20
        catalog["equipment"][0]["identity"] = f"skill:{literal_credential}"

        result = DESIGN.validate_design(catalog, lock)

        self.assertEqual(
            result.diagnostics,
            (
                DESIGN.Diagnostic(
                    "LITERAL_SECRET_MATERIAL",
                    "The catalog contains literal secret material; use a structured secret reference.",
                ),
            ),
        )
        self.assertNotIn(literal_credential, repr(result.diagnostics))
        self.assertEqual(result.coverage, ())
        self.assertIsNone(result.mutation_plan)

    def test_every_literal_credential_family_fails_closed_without_echoing_it(
        self,
    ) -> None:
        for literal_credential in literal_credential_samples():
            with self.subTest(family=literal_credential[:4]):
                catalog, lock = valid_pair()
                provider = {
                    "kind": "direct_mcp",
                    "server_name": "context7",
                    "transport": "stdio",
                    "command": "npx",
                    "arguments": [{"literal": literal_credential}],
                }
                managed_route(catalog)["provider"] = deepcopy(provider)
                managed_route(catalog)["provenance"] = {
                    "owner": "overlay:claude/mcp"
                }
                locked_managed_route(lock)["provider"] = deepcopy(provider)
                locked_managed_route(lock)["provenance"] = deepcopy(
                    managed_route(catalog)["provenance"]
                )
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(
                    "LITERAL_SECRET_MATERIAL",
                    {diagnostic.code for diagnostic in result.diagnostics},
                )
                self.assertTrue(
                    all(
                        literal_credential not in diagnostic.message
                        for diagnostic in result.diagnostics
                    )
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

    def test_provider_without_secret_channel_rejects_unused_references(self) -> None:
        catalog, lock = valid_pair()
        route = manual_route(catalog)
        route["secret_references"] = [
            {"kind": "secret_profile", "name": "unused"}
        ]
        locked_route = locked_record(
            lock, "plugin:example/matt", "claude"
        )["provider_selection"]["routes"][0]
        locked_route["secret_references"] = deepcopy(route["secret_references"])
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "PROVIDER_CONFIGURATION_INVALID",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        self.assertIsNone(result.mutation_plan)

    def test_http_mcp_url_rejects_embedded_credentials(self) -> None:
        catalog, lock = valid_pair()
        provider = {
            "kind": "direct_mcp",
            "server_name": "context7",
            "transport": "http",
            "url": "https://alice:secret-canary-value@example.invalid/mcp",
        }
        managed_route(catalog)["provider"] = deepcopy(provider)
        managed_route(catalog)["provenance"] = {"owner": "overlay:claude/mcp"}
        locked_managed_route(lock)["provider"] = deepcopy(provider)
        locked_managed_route(lock)["provenance"] = deepcopy(
            managed_route(catalog)["provenance"]
        )
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn("CATALOG_SCHEMA_INVALID", {d.code for d in result.diagnostics})
        self.assertIsNone(result.mutation_plan)

    def test_static_credential_free_https_mcp_endpoint_is_supported(self) -> None:
        catalog, lock = valid_pair()
        provider = {
            "kind": "direct_mcp",
            "server_name": "public-docs",
            "transport": "http",
            "url": "https://mcp.example.invalid/v1/public-docs",
        }
        managed_route(catalog)["provider"] = deepcopy(provider)
        managed_route(catalog)["provenance"] = {"owner": "overlay:claude/mcp"}
        locked_managed_route(lock)["provider"] = deepcopy(provider)
        locked_managed_route(lock)["provenance"] = deepcopy(
            managed_route(catalog)["provenance"]
        )
        bind_managed_distribution_to_static_https(
            catalog, lock, url=provider["url"]
        )
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        self.assertEqual(DESIGN.validate_design(catalog, lock).diagnostics, ())

    def test_static_https_host_policy_allows_private_endpoints_and_rejects_bad_labels(
        self,
    ) -> None:
        for valid_url in (
            "https://localhost/mcp",
            "https://127.0.0.1/mcp",
            "https://10.0.0.1/mcp",
            "https://169.254.169.254/latest/meta-data",
            "https://token.example.com/mcp",
            "https://secret.example.com/mcp",
        ):
            with self.subTest(valid_url=valid_url):
                catalog, lock = valid_pair()
                provider = {
                    "kind": "direct_mcp",
                    "server_name": "fixture",
                    "transport": "http",
                    "url": valid_url,
                }
                managed_route(catalog)["provider"] = deepcopy(provider)
                managed_route(catalog)["provenance"] = {"owner": "overlay:claude/mcp"}
                locked_managed_route(lock)["provider"] = deepcopy(provider)
                locked_managed_route(lock)["provenance"] = deepcopy(
                    managed_route(catalog)["provenance"]
                )
                bind_managed_distribution_to_static_https(
                    catalog, lock, url=valid_url
                )
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                self.assertEqual(DESIGN.validate_design(catalog, lock).diagnostics, ())

        for invalid_url in (
            "https://-.example.invalid/mcp",
            "https://example-.invalid/mcp",
            "https://example..invalid/mcp",
        ):
            with self.subTest(invalid_url=invalid_url):
                catalog, lock = valid_pair()
                provider = {
                    "kind": "direct_mcp",
                    "server_name": "fixture",
                    "transport": "http",
                    "url": invalid_url,
                }
                managed_route(catalog)["provider"] = deepcopy(provider)
                managed_route(catalog)["provenance"] = {"owner": "overlay:claude/mcp"}
                locked_managed_route(lock)["provider"] = deepcopy(provider)
                locked_managed_route(lock)["provenance"] = deepcopy(
                    managed_route(catalog)["provenance"]
                )
                bind_managed_distribution_to_static_https(
                    catalog, lock, url=invalid_url
                )
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(
                    "CATALOG_SCHEMA_INVALID",
                    {diagnostic.code for diagnostic in result.diagnostics},
                )
                self.assertIsNone(result.mutation_plan)

    def test_http_mcp_url_rejects_credential_path_segments(self) -> None:
        for url in (
            "https://example.invalid/token/secret-value",
            "https://example.invalid/Token/secret-value",
            "https://example.invalid/CLIENT-SECRET/value",
        ):
            with self.subTest(url=url):
                catalog, lock = valid_pair()
                provider = {
                    "kind": "direct_mcp",
                    "server_name": "context7",
                    "transport": "http",
                    "url": url,
                }
                managed_route(catalog)["provider"] = deepcopy(provider)
                locked_managed_route(lock)["provider"] = deepcopy(provider)
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(
                    "CATALOG_SCHEMA_INVALID",
                    {diagnostic.code for diagnostic in result.diagnostics},
                )
                self.assertIsNone(result.mutation_plan)

    def test_public_repository_uri_rejects_embedded_credentials(self) -> None:
        catalog, lock = valid_pair()
        catalog["distributions"][0]["source"]["repository"] = (
            "https://alice:secret-canary-value@example.invalid/bundle.git"
        )
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn("CATALOG_SCHEMA_INVALID", {d.code for d in result.diagnostics})
        self.assertIsNone(result.mutation_plan)

    def test_immutable_artifact_uri_rejects_credential_path_segments(self) -> None:
        catalog, lock = valid_pair()
        artifact_ref = (
            "git+https://example.invalid/bearer-secret-canary-value@"
            "0123456789abcdef0123456789abcdef01234567"
        )
        managed_route(catalog)["restore"]["artifact_ref"] = artifact_ref
        locked_managed_route(lock)["restore"]["artifact_ref"] = artifact_ref
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertTrue(
            {"CATALOG_SCHEMA_INVALID", "IMMUTABLE_RESTORE_INVALID"}
            & {diagnostic.code for diagnostic in result.diagnostics}
        )
        self.assertIsNone(result.mutation_plan)

    def test_immutable_artifact_selector_rejects_unsafe_subpaths(self) -> None:
        base_ref = (
            "git+https://example.invalid/bundle.git@"
            "0123456789abcdef0123456789abcdef01234567"
        )
        for suffix in (
            "#skills/../../etc",
            "#skills/./engineering",
            "#skills//engineering",
            "#skills/engineering,",
            "#skills/%2e%2e/%2E%2E/etc",
            "#skills%2fengineering",
            "#skills%5cengineering",
            r"#skills\engineering",
            "#skills/engineering?ref=other",
        ):
            with self.subTest(suffix=suffix):
                catalog, lock = valid_pair()
                unsafe_ref = base_ref + suffix
                managed_route(catalog)["restore"]["artifact_ref"] = unsafe_ref
                locked_managed_route(lock)["restore"]["artifact_ref"] = unsafe_ref
                lock["distributions"][0]["restore"]["artifact_ref"] = unsafe_ref
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertTrue(
                    {"CATALOG_SCHEMA_INVALID", "IMMUTABLE_RESTORE_INVALID"}
                    & {diagnostic.code for diagnostic in result.diagnostics}
                )
                self.assertIsNone(result.mutation_plan)

    def test_git_distribution_source_rejects_unsafe_revisions(self) -> None:
        for unsafe_ref in (
            "refs//heads/main",
            "../other",
            "--option",
            "feature..branch",
            "release.",
            "release.lock",
            "refs/heads/name.lock",
        ):
            with self.subTest(unsafe_ref=unsafe_ref):
                catalog, lock = valid_pair()
                catalog["distributions"][0]["source"]["ref"] = unsafe_ref
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(
                    "CATALOG_SCHEMA_INVALID",
                    {diagnostic.code for diagnostic in result.diagnostics},
                )
                self.assertIsNone(result.mutation_plan)

    def test_benign_canary_label_is_not_treated_as_secret_material(self) -> None:
        catalog, lock = valid_pair()
        managed_route(catalog)["activation_group"] = "activation:example/canary-label"
        locked_managed_route(lock)["activation_group"] = (
            "activation:example/canary-label"
        )
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

    def test_lock_distribution_source_is_an_exact_catalog_binding(self) -> None:
        for field, value in (
            ("repository", "https://other.example.invalid/bundle.git"),
            ("ref", "f" * 40),
        ):
            with self.subTest(field=field):
                catalog, lock = valid_pair()
                catalog["distributions"][0]["source"][field] = value
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(
                    "LOCK_DISTRIBUTION_SOURCE_MISMATCH",
                    {diagnostic.code for diagnostic in result.diagnostics},
                )
                self.assertIsNone(result.mutation_plan)

    def test_immutable_distribution_restore_matches_bound_git_source(self) -> None:
        for field, value in (
            ("repository", "https://other.example.invalid/bundle.git"),
            ("ref", "f" * 40),
        ):
            with self.subTest(field=field):
                catalog, lock = valid_pair()
                catalog["distributions"][0]["source"][field] = value
                lock["distributions"][0]["source"][field] = value
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(
                    "DISTRIBUTION_SOURCE_RESTORE_MISMATCH",
                    {diagnostic.code for diagnostic in result.diagnostics},
                )
                self.assertIsNone(result.mutation_plan)

    def test_native_distribution_source_matches_selected_provider(self) -> None:
        for mutation in ("package", "executable"):
            with self.subTest(mutation=mutation):
                catalog, lock = valid_pair()
                bind_managed_distribution_to_direct_mcp(
                    catalog, lock, package="example-mcp", channel="1.0.0"
                )
                provider = {
                    "kind": "direct_mcp",
                    "server_name": "example",
                    "transport": "stdio",
                    "command": "npx",
                    "arguments": [
                        {"literal": "-y"},
                        {"literal": "example-mcp@1.0.0"},
                    ],
                }
                managed_route(catalog)["provider"] = deepcopy(provider)
                managed_route(catalog)["provenance"] = {"owner": "overlay:claude/mcp"}
                managed_route(catalog)["secret_references"] = []
                locked_managed_route(lock)["provider"] = deepcopy(provider)
                locked_managed_route(lock)["provenance"] = {
                    "owner": "overlay:claude/mcp"
                }
                locked_managed_route(lock)["secret_references"] = []
                if mutation == "package":
                    catalog["distributions"][0]["source"]["package"] = (
                        "unrelated-package"
                    )
                    lock["distributions"][0]["source"] = deepcopy(
                        catalog["distributions"][0]["source"]
                    )
                else:
                    managed_route(catalog)["provider"]["command"] = "echo"
                    locked_managed_route(lock)["provider"] = deepcopy(
                        managed_route(catalog)["provider"]
                    )
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(
                    "DISTRIBUTION_SOURCE_PROVIDER_MISMATCH",
                    {diagnostic.code for diagnostic in result.diagnostics},
                )
                self.assertIsNone(result.mutation_plan)

    def test_retirement_native_source_matches_selected_executable(self) -> None:
        catalog = json.loads(
            (ROOT / "docs/agent-equipment/initial-catalog.proposed.json").read_text(
                encoding="utf-8"
            )
        )
        lock = json.loads(
            (ROOT / "docs/agent-equipment/initial-lock.proposed.json").read_text(
                encoding="utf-8"
            )
        )
        retirement = next(
            item
            for item in catalog["retirements"]
            if item["identity"] == "retirement:claude/direct-chrome-devtools"
        )
        locked_retirement = next(
            item
            for item in lock["retirements"]
            if item["identity"] == retirement["identity"]
        )
        retirement["route"]["provider"]["command"] = "echo"
        locked_retirement["route"]["provider"] = deepcopy(
            retirement["route"]["provider"]
        )
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "RETIREMENT_DISTRIBUTION_SOURCE_PROVIDER_MISMATCH",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
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
                controlled_equipment_identities=(),
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
            ("missing_compensation", "CATALOG_SCHEMA_INVALID"),
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

    def test_retirement_locator_must_match_losing_provider_and_equipment(self) -> None:
        for surface_kind, field in (
            ("direct_mcp", "server_name"),
            ("claude_skill_projection", "skill_name"),
        ):
            with self.subTest(surface_kind=surface_kind):
                catalog = json.loads(
                    (ROOT / "docs/agent-equipment/initial-catalog.proposed.json").read_text(
                        encoding="utf-8"
                    )
                )
                lock = json.loads(
                    (ROOT / "docs/agent-equipment/initial-lock.proposed.json").read_text(
                        encoding="utf-8"
                    )
                )
                catalog_retirement = next(
                    item
                    for item in catalog["retirements"]
                    if item["surface"]["kind"] == surface_kind
                )
                lock_retirement = next(
                    item
                    for item in lock["retirements"]
                    if item["identity"] == catalog_retirement["identity"]
                )
                catalog_retirement["surface"][field] = "unrelated-owned-key"
                lock_retirement["surface"][field] = "unrelated-owned-key"
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertIn(
                    "RETIREMENT_SURFACE_PROVIDER_MISMATCH",
                    {diagnostic.code for diagnostic in result.diagnostics},
                )
                self.assertIsNone(result.mutation_plan)

    def test_plugin_retirement_locator_matches_native_plugin_identity(self) -> None:
        catalog, lock = valid_pair()
        route = deepcopy(manual_route(catalog))
        route["identity"] = "route:example/legacy-native-plugin"
        route["activation_group"] = "activation:example/legacy-native-plugin"
        route["control_owner"] = "reconciler_owned"
        route["operations"]["disable"] = {
            "disposition": "automated",
            "compensation": "restore_captured_pre_state",
        }
        retirement = {
            "identity": "retirement:example/legacy-native-plugin",
            "equipment_identity": "plugin:example/matt",
            "harness": "claude",
            "route": route,
            "surface": {
                "kind": "plugin",
                "plugin_id": "unrelated-victim@official",
            },
            "desired_state": "disabled",
        }
        catalog["retirements"].append(retirement)
        lock["retirements"].append(deepcopy(retirement))
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "RETIREMENT_SURFACE_PROVIDER_MISMATCH",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        self.assertIsNone(result.mutation_plan)

    def test_retirement_provider_and_restore_match_selected_distribution(self) -> None:
        catalog, lock = valid_pair()
        route = deepcopy(manual_route(catalog))
        route["identity"] = "route:example/legacy-native-plugin"
        route["activation_group"] = "activation:example/legacy-native-plugin"
        route["control_owner"] = "reconciler_owned"
        route["provider"]["plugin_id"] = "unrelated-victim@official"
        route["provenance"]["owner"] = (
            "manager:claude-plugins/unrelated-victim@official"
        )
        route["operations"]["disable"] = {
            "disposition": "automated",
            "compensation": "restore_captured_pre_state",
        }
        retirement = {
            "identity": "retirement:example/legacy-native-plugin",
            "equipment_identity": "plugin:example/matt",
            "harness": "claude",
            "route": route,
            "surface": {
                "kind": "plugin",
                "plugin_id": "unrelated-victim@official",
            },
            "desired_state": "disabled",
        }
        catalog["retirements"].append(retirement)
        lock["retirements"].append(deepcopy(retirement))
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "RETIREMENT_DISTRIBUTION_SOURCE_PROVIDER_MISMATCH",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        self.assertIsNone(result.mutation_plan)

        catalog, lock = valid_pair()
        retirement = {
            "identity": "retirement:example/legacy-native-plugin",
            "equipment_identity": "plugin:example/matt",
            "harness": "claude",
            "route": deepcopy(manual_route(catalog)),
            "surface": {
                "kind": "plugin",
                "plugin_id": "example-matt@official",
            },
            "desired_state": "disabled",
        }
        retirement["route"]["identity"] = "route:example/legacy-native-plugin"
        retirement["route"]["activation_group"] = (
            "activation:example/legacy-native-plugin"
        )
        retirement["route"]["control_owner"] = "reconciler_owned"
        retirement["route"]["restore"]["reviewed_baseline"] = "9.9.9"
        retirement["route"]["operations"]["disable"] = {
            "disposition": "automated",
            "compensation": "restore_captured_pre_state",
        }
        catalog["retirements"].append(retirement)
        lock["retirements"].append(deepcopy(retirement))
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "RETIREMENT_DISTRIBUTION_RESTORE_MISMATCH",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
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

        self.assertIn(
            "CATALOG_SCHEMA_INVALID",
            {item.code for item in result.diagnostics},
        )
        self.assertEqual(result.coverage, ())
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
            "CATALOG_SCHEMA_INVALID",
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

    def test_provenance_owner_matches_provider_and_harness(self) -> None:
        catalog, lock = valid_pair()
        route = manual_route(catalog)
        route["provenance"]["owner"] = "overlay:cursor/mcp"
        locked_route = locked_record(
            lock, "plugin:example/matt", "claude"
        )["provider_selection"]["routes"][0]
        locked_route["provenance"]["owner"] = "overlay:cursor/mcp"
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "PROVENANCE_OWNER_INVALID",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        self.assertIsNone(result.mutation_plan)

    def test_standalone_provenance_owner_matches_selected_distribution(self) -> None:
        catalog, lock = valid_pair()
        managed_route(catalog)["provenance"]["owner"] = (
            "source:completely-unrelated"
        )
        locked_managed_route(lock)["provenance"]["owner"] = (
            "source:completely-unrelated"
        )
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "PROVENANCE_OWNER_INVALID",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        self.assertIsNone(result.mutation_plan)

    def test_native_plugin_provenance_owner_matches_exact_plugin(self) -> None:
        catalog, lock = valid_pair()
        route = manual_route(catalog)
        route["provenance"]["owner"] = (
            "manager:claude-plugins/completely-unrelated"
        )
        locked_route = locked_record(
            lock, "plugin:example/matt", "claude"
        )["provider_selection"]["routes"][0]
        locked_route["provenance"]["owner"] = (
            "manager:claude-plugins/completely-unrelated"
        )
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "PROVENANCE_OWNER_INVALID",
            {diagnostic.code for diagnostic in result.diagnostics},
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

    def test_native_rolling_plugin_remove_requires_an_exact_restore_route(self) -> None:
        catalog, lock = valid_pair()
        route = manual_route(catalog)
        route["operations"]["remove"] = {
            "disposition": "automated",
            "compensation": "restore_captured_pre_state",
        }
        locked_record(lock, "plugin:example/matt", "claude").clear()
        locked_record(lock, "plugin:example/matt", "claude").update(
            deepcopy(catalog["equipment"][0]["coverage"]["claude"]["record"])
        )
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertIn(
            "NATIVE_ROLLING_PLUGIN_REMOVAL_INVALID",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        self.assertIsNone(result.mutation_plan)

    def test_immutable_restore_binds_a_commit_selector_to_its_revision(self) -> None:
        for mutation in ("tag_revision", "different_commit_selector"):
            with self.subTest(mutation=mutation):
                catalog, lock = valid_pair()
                restore_records = (
                    managed_route(catalog)["restore"],
                    locked_managed_route(lock)["restore"],
                    lock["distributions"][0]["restore"],
                )
                if mutation == "tag_revision":
                    for restore in restore_records:
                        restore["revision"] = "v1.0.0"
                        restore["artifact_ref"] = (
                            "git+https://example.invalid/bundle.git@v1.0.0"
                        )
                else:
                    mismatched_commit = "f" * 40
                    for restore in restore_records:
                        restore["artifact_ref"] = (
                            "git+https://example.invalid/bundle.git@"
                            f"{mismatched_commit}"
                        )
                lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                result = DESIGN.validate_design(catalog, lock)

                self.assertTrue(
                    {"CATALOG_SCHEMA_INVALID", "IMMUTABLE_RESTORE_INVALID"}
                    & {diagnostic.code for diagnostic in result.diagnostics}
                )
                self.assertIsNone(result.mutation_plan)

    def test_digest_bound_catalog_and_lock_pair_accepts_reviewed_advance(self) -> None:
        catalog, lock = valid_pair()
        next_commit = "f" * 40
        next_artifact_ref = f"git+https://example.invalid/bundle.git@{next_commit}"
        next_digest = "sha256:" + "e" * 64
        for restore in (
            managed_route(catalog)["restore"],
            locked_managed_route(lock)["restore"],
            lock["distributions"][0]["restore"],
        ):
            restore["revision"] = next_commit
            restore["artifact_ref"] = next_artifact_ref
            restore["content_digest"] = next_digest
        catalog["distributions"][0]["source"]["ref"] = next_commit
        lock["distributions"][0]["source"]["ref"] = next_commit
        lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

        result = DESIGN.validate_design(catalog, lock)

        self.assertEqual(result.diagnostics, ())
        self.assertEqual(lock["catalog_digest"], DESIGN.canonical_json_sha256(catalog))

    def test_native_update_control_matches_suppression_disposition(self) -> None:
        allowed = {
            ("not_applicable", "unavailable"),
            ("unknown", "operator_action"),
            ("unknown", "unavailable"),
            ("suppressible", "automated"),
            ("suppressible", "operator_action"),
            ("suppressible", "unavailable"),
            ("unsuppressible", "unavailable"),
        }
        for control in (
            "not_applicable",
            "unknown",
            "suppressible",
            "unsuppressible",
        ):
            for disposition in ("automated", "operator_action", "unavailable"):
                with self.subTest(control=control, disposition=disposition):
                    catalog, lock = valid_pair()
                    route = managed_route(catalog)
                    locked_route = locked_managed_route(lock)
                    restore_class = (
                        "immutable"
                        if control == "not_applicable"
                        else "native_rolling"
                    )
                    if restore_class == "native_rolling":
                        restore = {
                            "class": "native_rolling",
                            "channel": "stable",
                            "reviewed_baseline": "1.2.3",
                            "observation_source": "fixture manager",
                            "native_update_control": control,
                        }
                        source = {
                            "kind": "native_manager",
                            "manager": "claude",
                            "package": "example-matt@official",
                            "channel": "stable",
                        }
                        provider = {
                            "kind": "native_plugin",
                            "manager": "claude",
                            "plugin_id": "example-matt@official",
                            "scope": "user",
                        }
                        catalog["distributions"][0]["source"] = deepcopy(source)
                        lock["distributions"][0]["source"] = deepcopy(source)
                        route["provider"] = deepcopy(provider)
                        locked_route["provider"] = deepcopy(provider)
                        route["provenance"] = {
                            "owner": "manager:claude-plugins/example-matt@official"
                        }
                        locked_route["provenance"] = deepcopy(route["provenance"])
                        route["control_owner"] = "reconciler_owned"
                        locked_route["control_owner"] = "reconciler_owned"
                        route["operations"]["remove"] = {
                            "disposition": "operator_action"
                        }
                        locked_route["operations"]["remove"] = {
                            "disposition": "operator_action"
                        }
                    else:
                        restore = deepcopy(route["restore"])
                    route["restore"] = deepcopy(restore)
                    locked_route["restore"] = deepcopy(restore)
                    lock["distributions"][0]["restore"] = deepcopy(restore)
                    route["operations"]["suppress_native_update"] = {
                        "disposition": disposition,
                        **(
                            {"compensation": "restore_captured_pre_state"}
                            if disposition == "automated"
                            else {}
                        ),
                    }
                    locked_route["operations"]["suppress_native_update"] = deepcopy(
                        route["operations"]["suppress_native_update"]
                    )
                    lock["catalog_digest"] = DESIGN.canonical_json_sha256(catalog)

                    result = DESIGN.validate_design(catalog, lock)

                    if (control, disposition) in allowed:
                        self.assertEqual(result.diagnostics, ())
                        self.assertIsNotNone(result.mutation_plan)
                    else:
                        self.assertIn(
                            "NATIVE_UPDATE_OPERATION_INVALID",
                            {diagnostic.code for diagnostic in result.diagnostics},
                        )
                        self.assertIsNone(result.mutation_plan)

    def test_secret_references_accept_environment_variables_and_opaque_profiles(self) -> None:
        catalog, lock = valid_pair()
        managed_route(catalog)["provider"] = {
            "kind": "direct_mcp",
            "server_name": "example",
            "transport": "stdio",
            "command": "secret-exec",
            "arguments": [
                {"secret_profile_reference": "context7"},
                {"literal": "--"},
                {"literal": "npx"},
                {"literal": "example-mcp@1.0.0"},
                {
                    "secret_reference": "EXAMPLE_API_KEY",
                    "template": "Authorization:Bearer {reference}",
                },
            ],
        }
        managed_route(catalog)["provenance"] = {"owner": "overlay:claude/mcp"}
        managed_route(catalog)["secret_references"] = [
            {"kind": "environment_variable", "name": "EXAMPLE_API_KEY"},
            {"kind": "secret_profile", "name": "context7"},
        ]
        locked_record(lock).clear()
        locked_record(lock).update(deepcopy(
            catalog["coverage_templates"][0]["record"]
        ))
        bind_managed_distribution_to_direct_mcp(
            catalog, lock, package="example-mcp", channel="1.0.0"
        )
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
