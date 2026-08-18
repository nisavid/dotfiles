from __future__ import annotations

import importlib.util
import json
import sys
import time
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
AGENT_EQUIPMENT_DOCUMENTS = ROOT / "docs/agent-equipment"
MAX_SOURCE_FIELD_CHARACTERS = 4096
MAX_SOURCE_MANIFEST_EQUIPMENT = 16_384
SPEC = importlib.util.spec_from_file_location(
    "agent_equipment_json_schema",
    ROOT / "scripts/agent_equipment_json_schema.py",
)
assert SPEC is not None and SPEC.loader is not None
SCHEMA = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SCHEMA
SPEC.loader.exec_module(SCHEMA)


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


class AgentEquipmentJsonSchemaTests(unittest.TestCase):
    def validate_agent_equipment_document(
        self,
        document: object,
        root_schema_name: str,
    ) -> bool:
        return SCHEMA.validate_document(
            document,
            schema_directory=AGENT_EQUIPMENT_DOCUMENTS,
            root_schema_name=root_schema_name,
            allowed_schema_names=frozenset(
                {"catalog-v1.schema.json", "lock-v1.schema.json"}
            ),
        )

    def validate(
        self,
        document: object,
        schemas: dict[str, object],
        *,
        root: str = "root.json",
        allowed: frozenset[str] | None = None,
    ) -> bool:
        with TemporaryDirectory() as directory:
            schema_directory = Path(directory)
            for name, schema in schemas.items():
                (schema_directory / name).write_text(
                    json.dumps(schema), encoding="utf-8"
                )
            return SCHEMA.validate_document(
                document,
                schema_directory=schema_directory,
                root_schema_name=root,
                allowed_schema_names=(allowed or frozenset(schemas)),
            )

    def validate_raw(
        self,
        document: object,
        schemas: dict[str, bytes],
        *,
        root: str = "root.json",
        allowed: frozenset[str] | None = None,
    ) -> bool:
        with TemporaryDirectory() as directory:
            schema_directory = Path(directory)
            for name, payload in schemas.items():
                (schema_directory / name).write_bytes(payload)
            return SCHEMA.validate_document(
                document,
                schema_directory=schema_directory,
                root_schema_name=root,
                allowed_schema_names=(allowed or frozenset(schemas)),
            )

    def validate_catalog_definition(self, definition: str, document: object) -> bool:
        catalog_schema = json.loads(
            (AGENT_EQUIPMENT_DOCUMENTS / "catalog-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        return self.validate(
            document,
            {
                "root.json": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$ref": f"catalog-v1.schema.json#/$defs/{definition}",
                },
                "catalog-v1.schema.json": catalog_schema,
            },
        )

    def test_validates_one_document_through_a_temporary_root_schema(self) -> None:
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
            "additionalProperties": False,
        }

        self.assertTrue(self.validate({"name": "Ada"}, {"root.json": schema}))
        self.assertFalse(self.validate({"name": 3}, {"root.json": schema}))

    def test_checked_in_catalog_and_lock_match_the_source_manifest_contract(
        self,
    ) -> None:
        catalog = json.loads(
            (AGENT_EQUIPMENT_DOCUMENTS / "initial-catalog.proposed.json").read_text(
                encoding="utf-8"
            )
        )
        lock = json.loads(
            (AGENT_EQUIPMENT_DOCUMENTS / "initial-lock.proposed.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertTrue(
            self.validate_agent_equipment_document(
                catalog,
                "catalog-v1.schema.json",
            )
        )
        self.assertTrue(
            self.validate_agent_equipment_document(lock, "lock-v1.schema.json")
        )

    def test_catalog_tracking_policy_rejects_resolved_source_literals(self) -> None:
        catalog = json.loads(
            (AGENT_EQUIPMENT_DOCUMENTS / "initial-catalog.proposed.json").read_text(
                encoding="utf-8"
            )
        )
        invalid_git = deepcopy(catalog)
        invalid_git["distributions"][-1]["source"]["ref"] = "a" * 40
        invalid_head = deepcopy(catalog)
        invalid_head["distributions"][-1]["source"]["branch"] = "HEAD"
        invalid_native = deepcopy(catalog)
        native_distribution = next(
            item
            for item in invalid_native["distributions"]
            if item["identity"] == "distribution:chrome-devtools/direct-mcp"
        )
        native_distribution["source"]["channel"] = "latest"

        for label, document in (
            ("resolved git ref", invalid_git),
            ("HEAD branch", invalid_head),
            ("latest native channel", invalid_native),
        ):
            with self.subTest(case=label):
                self.assertFalse(
                    self.validate_agent_equipment_document(
                        document,
                        "catalog-v1.schema.json",
                    )
                )

    def test_npx_package_cannot_embed_the_separate_channel_selector(self) -> None:
        valid_sources = (
            {
                "kind": "native_manager",
                "manager": "npx",
                "package": "tool",
            },
            {
                "kind": "native_manager",
                "manager": "npx",
                "package": "@example/tool",
            },
            {
                "kind": "native_manager",
                "manager": "claude",
                "package": "tool@reviewed-registry",
            },
            {
                "kind": "native_manager",
                "manager": "codex",
                "package": "tool@reviewed-registry",
            },
            {
                "kind": "native_manager",
                "manager": "cursor",
                "package": "tool@reviewed-registry",
            },
        )
        for source in valid_sources:
            with self.subTest(source=source):
                self.assertTrue(self.validate_catalog_definition("source", source))

        for package in ("tool@beta", "tool@1.2.3"):
            with self.subTest(package=package):
                self.assertFalse(
                    self.validate_catalog_definition(
                        "source",
                        {
                            "kind": "native_manager",
                            "manager": "npx",
                            "package": package,
                        },
                    )
                )

    def test_source_policy_schema_admits_only_closed_manager_specific_forms(
        self,
    ) -> None:
        accepted = (
            {"kind": "git", "repository": "https://example.invalid/tool.git"},
            {
                "kind": "git",
                "repository": "https://example.invalid/tool.git",
                "branch": "release/v1",
            },
            {
                "kind": "native_manager",
                "manager": "npx",
                "package": "tool",
            },
            {
                "kind": "native_manager",
                "manager": "npx",
                "package": "@scope/tool",
            },
            {
                "kind": "native_manager",
                "manager": "claude",
                "package": "tool@official",
                "channel": "stable",
            },
            {
                "kind": "native_manager",
                "manager": "codex",
                "package": "github@openai-curated",
                "channel": "openai-curated",
            },
            {
                "kind": "native_manager",
                "manager": "cursor",
                "package": "tool@official",
                "channel": "stable",
            },
            {
                "kind": "native_manager",
                "manager": "http",
                "package": "https://mcp.example.invalid/v1",
                "channel": "static",
            },
        )
        rejected = (
            {"kind": "git", "repository": "https://example.invalid/tool"},
            {
                "kind": "native_manager",
                "manager": "pip",
                "package": "letters",
            },
            {
                "kind": "native_manager",
                "manager": "npx",
                "package": "https://example.invalid/tool",
            },
            {
                "kind": "native_manager",
                "manager": "npx",
                "package": "tool",
                "channel": "latest",
            },
            {
                "kind": "native_manager",
                "manager": "http",
                "package": "https://user:" + "secret@" + "mcp.example.invalid/v1",
                "channel": "static",
            },
            {
                "kind": "native_manager",
                "manager": "http",
                "package": "https://mcp.example.invalid/TO" + "KEN-value",
                "channel": "static",
            },
            {
                "kind": "native_manager",
                "manager": "http",
                "package": "https://mcp.example.invalid/v1?to" + "ken=value",
                "channel": "static",
            },
            {
                "kind": "native_manager",
                "manager": "http",
                "package": "https://mcp.example.invalid/v1",
                "channel": "stable",
            },
        )

        for source in accepted:
            with self.subTest(admitted=source):
                self.assertTrue(self.validate_catalog_definition("source", source))
        for source in rejected:
            with self.subTest(rejected=source):
                self.assertFalse(self.validate_catalog_definition("source", source))

    def test_resolved_source_schema_contains_only_fact_specific_tagged_versions(
        self,
    ) -> None:
        accepted = (
            {"kind": "git", "revision": "0" * 40},
            {
                "kind": "native_manager",
                "version": {"kind": "semantic_version", "value": "1.2.3"},
            },
            {
                "kind": "native_manager",
                "version": {
                    "kind": "semantic_version",
                    "value": "1.2.3-rc.1+build.7",
                },
            },
            {
                "kind": "native_manager",
                "version": {
                    "kind": "semantic_version",
                    "value": "1.2.3+" + "A" * 249,
                },
            },
            {
                "kind": "native_manager",
                "version": {"kind": "revision", "value": "11c74d6b"},
            },
            {
                "kind": "native_manager",
                "version": {"kind": "static_source"},
            },
        )
        rejected = (
            {
                "kind": "git",
                "repository": "https://example.invalid/tool.git",
                "revision": "0" * 40,
            },
            {
                "kind": "native_manager",
                "manager": "npx",
                "version": {"kind": "semantic_version", "value": "1.2.3"},
            },
            {
                "kind": "native_manager",
                "version": {"kind": "semantic_version", "value": "01.2.3"},
            },
            {
                "kind": "native_manager",
                "version": {
                    "kind": "semantic_version",
                    "value": "1.2.3+" + "A" * 250,
                },
            },
            {
                "kind": "native_manager",
                "version": {"kind": "revision", "value": "deadbeef"},
            },
            {
                "kind": "native_manager",
                "version": {"kind": "revision", "value": "11c74d6"},
            },
            {
                "kind": "native_manager",
                "version": {"kind": "static_source", "value": "static"},
            },
        )

        for resolved in accepted:
            with self.subTest(admitted=resolved):
                self.assertTrue(
                    self.validate_catalog_definition("resolvedSource", resolved)
                )
        for resolved in rejected:
            with self.subTest(rejected=resolved):
                self.assertFalse(
                    self.validate_catalog_definition("resolvedSource", resolved)
                )

    def test_native_restore_schema_rejects_unreviewable_observation_text(self) -> None:
        lock = json.loads(
            (AGENT_EQUIPMENT_DOCUMENTS / "initial-lock.proposed.json").read_text(
                encoding="utf-8"
            )
        )
        for observation_source in (
            "V7p!opaque.private.value!9Qx",
            "a" * 256,
            "line one\nline two",
        ):
            with self.subTest(observation_source=observation_source):
                invalid = deepcopy(lock)
                invalid["distributions"][0]["restore"]["observation_source"] = (
                    observation_source
                )
                self.assertFalse(
                    self.validate_agent_equipment_document(
                        invalid,
                        "lock-v1.schema.json",
                    )
                )

    def test_source_manifest_schema_enforces_complete_string_bounds(self) -> None:
        lock = json.loads(
            (AGENT_EQUIPMENT_DOCUMENTS / "initial-lock.proposed.json").read_text(
                encoding="utf-8"
            )
        )
        baseline = next(
            item for item in lock["distributions"] if item["source"]["kind"] == "git"
        )
        repository = baseline["source"]["repository"]
        revision = baseline["resolved_source"]["revision"]
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
        maximum["source"]["branch"] = "a" * MAX_SOURCE_FIELD_CHARACTERS
        maximum["restore"]["artifact_ref"] = artifact_prefix + "a" * (
            MAX_SOURCE_FIELD_CHARACTERS - len(artifact_prefix)
        )
        self.assertTrue(self.validate_catalog_definition("sourceManifest", maximum))

        over_limit = MAX_SOURCE_FIELD_CHARACTERS + 1
        for label in (
            "artifact_ref",
            "distribution_identity",
            "equipment_identity",
            "branch",
            "repository",
        ):
            invalid = deepcopy(baseline)
            if label == "artifact_ref":
                invalid["restore"]["artifact_ref"] = artifact_prefix + "a" * over_limit
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
                invalid["source"]["branch"] = "a" * over_limit
            else:
                oversized_repository = public_git_repository(over_limit)
                invalid["source"]["repository"] = oversized_repository
                invalid["restore"]["artifact_ref"] = (
                    f"git+{oversized_repository}@{revision}"
                )
            with self.subTest(field=label):
                self.assertFalse(
                    self.validate_catalog_definition("sourceManifest", invalid)
                )

        maximum_package = "a" * 126 + "@" + "b" * 128
        over_limit_package = "a" * 127 + "@" + "b" * 128
        self.assertTrue(
            self.validate_catalog_definition(
                "source",
                {
                    "kind": "native_manager",
                    "manager": "claude",
                    "package": maximum_package,
                },
            )
        )
        self.assertFalse(
            self.validate_catalog_definition(
                "source",
                {
                    "kind": "native_manager",
                    "manager": "claude",
                    "package": over_limit_package,
                },
            )
        )

        native_restore = {
            "class": "native_rolling",
            "channel": "stable",
            "reviewed_baseline": "1.2.3",
            "observation_source": "reviewed plugin list",
            "native_update_control": "suppressible",
        }
        for field in ("channel", "reviewed_baseline"):
            with self.subTest(restore_field=field):
                self.assertFalse(
                    self.validate_catalog_definition(
                        "restore",
                        native_restore | {field: "a" * over_limit},
                    )
                )

    def test_source_manifest_schema_enforces_equipment_item_ceiling(self) -> None:
        identities = [
            f"other:source-limit/{index:05d}"
            for index in range(MAX_SOURCE_MANIFEST_EQUIPMENT + 1)
        ]

        self.assertTrue(
            self.validate_catalog_definition(
                "equipmentIdentityList",
                identities[:MAX_SOURCE_MANIFEST_EQUIPMENT],
            )
        )
        self.assertFalse(
            self.validate_catalog_definition("equipmentIdentityList", identities)
        )

        catalog_schema = json.loads(
            (AGENT_EQUIPMENT_DOCUMENTS / "catalog-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        source_manifest_properties = catalog_schema["$defs"]["sourceManifest"][
            "properties"
        ]
        for field in ("available_equipment", "equipment"):
            with self.subTest(field=field):
                self.assertEqual(
                    source_manifest_properties[field],
                    {"$ref": "#/$defs/equipmentIdentityList"},
                )

    def test_source_manifest_completeness_history_and_digest_fields_are_required(
        self,
    ) -> None:
        lock = json.loads(
            (AGENT_EQUIPMENT_DOCUMENTS / "initial-lock.proposed.json").read_text(
                encoding="utf-8"
            )
        )
        mutations: list[tuple[str, dict[str, object]]] = []
        for field in (
            "resolved_source",
            "available_equipment",
            "membership_evidence",
            "source_manifest_digest",
        ):
            document = deepcopy(lock)
            document["distributions"][0].pop(field)
            mutations.append((field, document))
        missing_history = deepcopy(lock)
        missing_history.pop("source_manifest_history")
        mutations.append(("source_manifest_history", missing_history))
        malformed_history = deepcopy(lock)
        malformed_history["source_manifest_history"] = [
            {"source_manifest_digest": "sha256:" + "0" * 64}
        ]
        mutations.append(("closed source_manifest_history", malformed_history))

        for label, document in mutations:
            with self.subTest(field=label):
                self.assertFalse(
                    self.validate_agent_equipment_document(
                        document,
                        "lock-v1.schema.json",
                    )
                )

    def test_catalog_retirements_require_a_source_manifest_digest(self) -> None:
        catalog = json.loads(
            (AGENT_EQUIPMENT_DOCUMENTS / "initial-catalog.proposed.json").read_text(
                encoding="utf-8"
            )
        )
        catalog["retirements"][0].pop("source_manifest_digest")

        self.assertFalse(
            self.validate_agent_equipment_document(
                catalog,
                "catalog-v1.schema.json",
            )
        )

    def test_rejects_malformed_or_nonlocal_schema_inputs(self) -> None:
        malformed_files = (
            b'{"type":"string","type":"number"}',
            b'{"minimum":NaN}',
            b'{"minimum":1e10000}',
            b"\xff",
            b"[]",
        )
        for payload in malformed_files:
            with self.subTest(payload=payload):
                self.assertFalse(self.validate_raw("value", {"root.json": payload}))

        self.assertFalse(
            self.validate(
                "value",
                {"root.json": {"type": "string"}},
                allowed=frozenset({"missing.json"}),
            )
        )
        self.assertFalse(
            self.validate(
                "value",
                {
                    "root.json": {"type": "string"},
                    "unused.json": {"unsupported": True},
                },
            )
        )

    def test_rejects_non_json_in_memory_documents(self) -> None:
        schema = {"type": "object"}
        cyclic: dict[str, object] = {}
        cyclic["self"] = cyclic
        documents = (
            {1: "non-string key"},
            {"tuple": (1, 2)},
            {"nan": float("nan")},
            {"infinity": float("inf")},
            cyclic,
        )
        for document in documents:
            with self.subTest(document=type(document).__name__):
                self.assertFalse(self.validate(document, {"root.json": schema}))

    def test_rejects_non_unicode_scalar_strings_and_object_keys(self) -> None:
        invalid_documents = (
            "\ud800",
            "\udfff",
            "prefix\ud800suffix",
            {"\ud800": "value"},
            {"nested": ["\udc00"]},
        )
        for document in invalid_documents:
            with self.subTest(document=repr(document)):
                self.assertFalse(self.validate(document, {"root.json": {}}))

        self.assertTrue(
            self.validate(
                {"\U0010ffff": "\U0001f642"},
                {"root.json": {"type": "object"}},
            )
        )

        strict_loaded_surrogate_schemas = (
            b'{"$defs":{"bad":{"const":"\\ud800"}},"type":"string"}',
            b'{"$defs":{"\\ud800":{}},"type":"string"}',
        )
        for schema in strict_loaded_surrogate_schemas:
            with self.subTest(schema=schema):
                self.assertFalse(self.validate_raw("value", {"root.json": schema}))

    def test_preflights_the_value_shape_of_every_supported_keyword(self) -> None:
        malformed_schemas = {
            "schema dialect type": {"$schema": 1},
            "unsupported schema dialect": {"$schema": "draft-seven"},
            "identifier metadata": {"$id": 1},
            "title metadata": {"title": []},
            "definitions": {"$defs": []},
            "reference": {"$ref": 1},
            "null type declaration": {"type": None},
            "required": {"required": {}},
            "properties": {"properties": []},
            "additional properties": {"additionalProperties": "false"},
            "unevaluated properties": {"unevaluatedProperties": "false"},
            "items": {"items": []},
            "enum container": {"enum": {}},
            "empty enum": {"enum": []},
            "duplicate enum": {"enum": ["x", "x"]},
            "pattern type": {"pattern": 1},
            "pattern syntax": {"pattern": "["},
            "format type": {"format": 1},
            "unsupported format": {"format": "email"},
            "minimum length": {"minLength": True},
            "minimum": {"minimum": True},
            "minimum items": {"minItems": -1},
            "maximum items": {"maxItems": 1.5},
            "minimum properties": {"minProperties": "1"},
            "unique items": {"uniqueItems": "true"},
            "one of container": {"oneOf": {}},
            "empty one of": {"oneOf": []},
            "all of child": {"allOf": [True]},
            "empty all of": {"allOf": []},
            "if": {"if": []},
            "then": {"then": []},
            "else": {"else": []},
        }
        for label, schema in malformed_schemas.items():
            with self.subTest(label=label):
                self.assertFalse(self.validate("value", {"root.json": schema}))

        self.assertFalse(self.validate_raw("value", {"root.json": b'{"const":NaN}'}))

    def test_validates_schema_ids_with_only_optional_empty_fragments(self) -> None:
        checked_in_schemas = (
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((ROOT / "docs/agent-equipment").glob("*.schema.json"))
        )
        checked_in_ids = tuple(
            schema["$id"] for schema in checked_in_schemas if "$id" in schema
        )
        valid_ids = checked_in_ids + (
            "root.json",
            "root.json#",
            "root.json#\n",
            "../schemas/root.json",
            "#",
            "",
            "https://exa mple.invalid/root.json",
            "https://[broken/root.json",
            "https://example.invalid/%zz",
            "root[1].json",
            "root.json?[query]",
            "https://first@second@example.invalid/root.json",
            "https://example.invalid:port/root.json",
            ":relative",
            "1scheme:relative",
            "\\server\\schema.json",
        )
        for schema_id in valid_ids:
            with self.subTest(schema_id=schema_id):
                self.assertTrue(
                    self.validate(
                        "value",
                        {"root.json": {"$id": schema_id, "type": "string"}},
                    )
                )

        invalid_ids = (
            "#fragment",
            "root.json#fragment",
            "root.json##",
            "##",
            "root.json#fragment#",
        )
        for schema_id in invalid_ids:
            with self.subTest(schema_id=schema_id):
                self.assertFalse(
                    self.validate(
                        "value",
                        {"root.json": {"$id": schema_id, "type": "string"}},
                    )
                )

    def test_rejects_nested_schema_ids_in_the_closed_local_subset(self) -> None:
        nested_cases = (
            (
                {"name": "value"},
                {
                    "type": "object",
                    "properties": {"name": {"$id": "nested.json", "type": "string"}},
                },
            ),
            (
                "value",
                {
                    "$defs": {"name": {"$id": "nested.json#", "type": "string"}},
                    "$ref": "#/$defs/name",
                },
            ),
            (
                "value",
                {"allOf": [{"$id": "nested.json", "type": "string"}]},
            ),
        )
        for document, schema in nested_cases:
            with self.subTest(schema=schema):
                self.assertFalse(self.validate(document, {"root.json": schema}))

    def test_preflight_visits_unselected_definitions_and_branches(self) -> None:
        malformed_locations = (
            {"$defs": {"unused": {"unknown": True}}},
            {"oneOf": [{"const": "value"}, {"items": []}]},
            {"allOf": [{"const": "value"}, {"if": []}]},
            {"if": {"const": "other"}, "else": {"properties": []}},
        )
        for schema in malformed_locations:
            with self.subTest(schema=schema):
                self.assertFalse(self.validate("value", {"root.json": schema}))

    def test_accepts_each_supported_keyword_with_a_well_formed_value(self) -> None:
        valid_cases = {
            "metadata": (
                "value",
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$id": "https://example.invalid/root.json",
                    "title": "Root",
                },
            ),
            "definition and reference": (
                "value",
                {
                    "$defs": {"text": {"type": "string"}},
                    "$ref": "#/$defs/text",
                },
            ),
            "array": (
                ["a"],
                {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 2,
                    "uniqueItems": True,
                },
            ),
            "object": (
                {"name": "Ada"},
                {
                    "type": "object",
                    "required": ["name"],
                    "properties": {"name": {"type": "string"}},
                    "additionalProperties": False,
                    "minProperties": 1,
                },
            ),
            "string": (
                "2026-08-13T04:00:00Z",
                {
                    "type": "string",
                    "pattern": "^2026-",
                    "format": "date-time",
                    "minLength": 1,
                },
            ),
            "number": (2, {"type": "number", "minimum": 1}),
            "const and enum": ("x", {"const": "x", "enum": ["x", "y"]}),
            "combiners": (
                "x",
                {
                    "oneOf": [{"const": "x"}, {"const": "y"}],
                    "allOf": [{"type": "string"}, {"minLength": 1}],
                },
            ),
            "condition": (
                "x",
                {
                    "if": {"const": "x"},
                    "then": {"type": "string"},
                    "else": {"type": "number"},
                },
            ),
            "unevaluated properties": (
                {},
                {"type": "object", "unevaluatedProperties": False},
            ),
            "null": (None, {"type": "null"}),
        }
        for label, (document, schema) in valid_cases.items():
            with self.subTest(label=label):
                self.assertTrue(self.validate(document, {"root.json": schema}))

    def test_accepts_annotation_keywords_without_applying_their_values(self) -> None:
        schema = {
            "type": "string",
            "description": {"ignored": True},
            "$comment": ["ignored"],
            "examples": {"ignored": "value"},
            "default": {"ignored": "value"},
            "deprecated": "ignored",
        }

        self.assertTrue(self.validate("value", {"root.json": schema}))
        self.assertFalse(self.validate(3, {"root.json": schema}))

    def test_accepts_nonnegative_integer_valued_float_schema_limits(self) -> None:
        instances = {
            "minLength": "x",
            "minItems": ["x"],
            "maxItems": [],
            "minProperties": {"name": "x"},
        }
        for keyword, instance in instances.items():
            for limit in (1.0, -0.0):
                with self.subTest(keyword=keyword, limit=limit):
                    self.assertTrue(
                        self.validate(instance, {"root.json": {keyword: limit}})
                    )

            for limit in (1.5, -1.0, float("inf")):
                with self.subTest(keyword=keyword, limit=limit):
                    self.assertFalse(
                        self.validate(instance, {"root.json": {keyword: limit}})
                    )

    def test_evaluates_types_values_and_scalar_constraints_exactly(self) -> None:
        rejected_cases = (
            (True, {"type": "integer"}),
            (True, {"type": "number"}),
            (1, {"type": "boolean"}),
            (None, {"type": "string"}),
            ("short", {"minLength": 6}),
            ("abc", {"pattern": "^[0-9]+$"}),
            (0, {"minimum": 1}),
            ("2026-02-30T00:00:00Z", {"format": "date-time"}),
            ("2026-08-13T04:00:00", {"format": "date-time"}),
        )
        for document, schema in rejected_cases:
            with self.subTest(document=document, schema=schema):
                self.assertFalse(self.validate(document, {"root.json": schema}))

        huge_integer = 10**1000
        self.assertTrue(
            self.validate(
                huge_integer,
                {"root.json": {"type": "integer", "minimum": huge_integer}},
            )
        )

    def test_validates_and_evaluates_finite_maximum(self) -> None:
        accepted_cases = (
            (2, {"maximum": 2}),
            (2.0, {"maximum": 2}),
            (1, {"maximum": 1.0}),
            (True, {"maximum": 0}),
        )
        for document, schema in accepted_cases:
            with self.subTest(document=document, schema=schema):
                self.assertTrue(self.validate(document, {"root.json": schema}))

        self.assertFalse(self.validate(2, {"root.json": {"maximum": 1}}))
        for maximum in (True, "1", float("inf"), float("nan")):
            with self.subTest(maximum=maximum):
                self.assertFalse(
                    self.validate("value", {"root.json": {"maximum": maximum}})
                )

    def test_validates_rfc3339_date_times_with_year_zero_and_offsets(self) -> None:
        schema = {"type": "string", "format": "date-time"}
        accepted = (
            "0000-01-01T00:00:00Z",
            "0000-02-29t23:59:59z",
            "2000-02-29T12:34:56.123+23:59",
            "2026-08-13T04:00:00-00:00",
            "2026-08-13T04:00:00,123Z",
            "2026-08-13t04:00:00,123z",
        )
        for value in accepted:
            with self.subTest(value=value):
                self.assertTrue(self.validate(value, {"root.json": schema}))

        rejected = (
            "1900-02-29T00:00:00Z",
            "2026-02-30T00:00:00Z",
            "2026-01-01T24:00:00Z",
            "2026-01-01T00:00:60Z",
            "2026-01-01T00:00:00+24:00",
            "2026-01-01T00:00:00+00:60",
            "2026-01-01T00:00:00",
            "2026-08-13T04:00:00Z\n",
            "2026-08-13T04:00:00,123Z\n",
            "2026-08-13T04:00:00Z\r\n",
            "2026-01-01T00:00:00Z\n\n",
            "2026-01-01T00:00:00Z\r",
        )
        for value in rejected:
            with self.subTest(value=value):
                self.assertFalse(self.validate(value, {"root.json": schema}))

    def test_uses_json_schema_numeric_equality_and_integer_semantics(self) -> None:
        accepted_cases = (
            (1.0, {"type": "integer"}),
            (1.0, {"const": 1}),
            (1.0, {"enum": [1]}),
            ([True, 1], {"type": "array", "uniqueItems": True}),
        )
        for document, schema in accepted_cases:
            with self.subTest(document=document, schema=schema):
                self.assertTrue(self.validate(document, {"root.json": schema}))

        rejected_cases = (
            (1.5, {"type": "integer"}),
            ([1, 1.0], {"type": "array", "uniqueItems": True}),
            (1, {"oneOf": [{"const": 1}, {"const": 1.0}]}),
            (True, {"const": 1}),
            (1, {"const": True}),
        )
        for document, schema in rejected_cases:
            with self.subTest(document=document, schema=schema):
                self.assertFalse(self.validate(document, {"root.json": schema}))

        self.assertFalse(self.validate("value", {"root.json": {"enum": [1, 1.0]}}))

    def test_unique_items_handles_wide_structured_arrays(self) -> None:
        values = [
            {"identity": f"item:{index}", "coordinates": [index, index + 1]}
            for index in range(4_000)
        ]
        schema = {"type": "array", "uniqueItems": True}

        self.assertTrue(self.validate(values, {"root.json": schema}))
        self.assertFalse(
            self.validate(
                [*values, {"coordinates": [3999.0, 4000.0], "identity": "item:3999"}],
                {"root.json": schema},
            )
        )

    def test_unique_items_resists_python_integer_hash_collisions(self) -> None:
        values = [index * sys.hash_info.modulus for index in range(10_000)]
        schema = {"type": "array", "uniqueItems": True}

        started = time.perf_counter()
        self.assertTrue(self.validate(values, {"root.json": schema}))
        self.assertFalse(self.validate([*values, values[-1]], {"root.json": schema}))
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 1.0)

        huge_integer = 10**10_000
        self.assertTrue(
            self.validate([huge_integer, -huge_integer], {"root.json": schema})
        )

    def test_evaluates_array_and_object_constraints(self) -> None:
        rejected_cases = (
            (["x", 1], {"items": {"type": "string"}}),
            ([], {"minItems": 1}),
            ([1, 2], {"maxItems": 1}),
            ([1, 1], {"uniqueItems": True}),
            ({}, {"required": ["name"]}),
            ({}, {"minProperties": 1}),
            ({"name": 1}, {"properties": {"name": {"type": "string"}}}),
            ({"extra": 1}, {"additionalProperties": False}),
            ({"extra": 1}, {"unevaluatedProperties": False}),
        )
        for document, schema in rejected_cases:
            with self.subTest(document=document, schema=schema):
                self.assertFalse(self.validate(document, {"root.json": schema}))

    def test_evaluates_combiners_and_conditionals(self) -> None:
        cases = (
            (False, "x", {"allOf": [{"type": "string"}, {"const": "y"}]}),
            (False, "x", {"oneOf": [{"type": "string"}, {"const": "x"}]}),
            (True, "x", {"oneOf": [{"const": "x"}, {"const": "y"}]}),
            (
                False,
                {"kind": "text", "value": 1},
                {
                    "if": {"properties": {"kind": {"const": "text"}}},
                    "then": {"properties": {"value": {"type": "string"}}},
                    "else": {"properties": {"value": {"type": "number"}}},
                },
            ),
            (
                True,
                {"kind": "number", "value": 1},
                {
                    "if": {"properties": {"kind": {"const": "text"}}},
                    "then": {"properties": {"value": {"type": "string"}}},
                    "else": {"properties": {"value": {"type": "number"}}},
                },
            ),
        )
        for expected, document, schema in cases:
            with self.subTest(document=document, schema=schema):
                self.assertEqual(
                    expected,
                    self.validate(document, {"root.json": schema}),
                )

    def test_resolves_only_allowlisted_local_schema_references(self) -> None:
        common = {
            "$defs": {
                "base": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {"id": {"type": "string"}},
                }
            }
        }
        root = {
            "allOf": [
                {"$ref": "common.json#/$defs/base"},
                {
                    "type": "object",
                    "required": ["kind"],
                    "properties": {"kind": {"const": "example"}},
                },
            ],
            "unevaluatedProperties": False,
        }
        schemas = {"root.json": root, "common.json": common}

        self.assertTrue(self.validate({"id": "1", "kind": "example"}, schemas))
        self.assertFalse(
            self.validate({"id": "1", "kind": "example", "extra": True}, schemas)
        )
        self.assertFalse(
            self.validate(
                {"id": "1", "kind": "example"},
                schemas,
                allowed=frozenset({"root.json"}),
            )
        )
        for reference in (
            "missing.json#/$defs/base",
            "../common.json#/$defs/base",
            "https://example.invalid/common.json#/$defs/base",
            "common.json#/$defs/missing",
            "common.json#/%24defs/base",
        ):
            with self.subTest(reference=reference):
                self.assertFalse(
                    self.validate(
                        {},
                        {
                            "root.json": {"$ref": reference},
                            "common.json": common,
                        },
                    )
                )
        self.assertFalse(
            self.validate(
                {},
                {
                    "root.json": {"$ref": "common.json#/oneOf/" + "9" * 5000},
                    "common.json": {"oneOf": [{}]},
                },
            )
        )

    def test_resolves_escaped_local_json_pointer_tokens(self) -> None:
        schema = {
            "$defs": {"path/name~schema": {"const": "matched"}},
            "$ref": "#/$defs/path~1name~0schema",
        }

        self.assertTrue(self.validate("matched", {"root.json": schema}))
        self.assertFalse(self.validate("other", {"root.json": schema}))

    def test_rejects_reference_cycles_without_recursing(self) -> None:
        cycles = (
            {"root.json": {"$ref": "#"}},
            {
                "root.json": {"$ref": "other.json#"},
                "other.json": {"$ref": "root.json#"},
            },
            {
                "root.json": {
                    "$defs": {"recursive": {"$ref": "#"}},
                    "type": "string",
                }
            },
        )
        for schemas in cycles:
            with self.subTest(schemas=schemas):
                self.assertFalse(self.validate("value", schemas))

        deeply_nested = b'{"properties":{"value":' * 1200 + b"{}" + b"}}" * 1200
        self.assertFalse(self.validate_raw("value", {"root.json": deeply_nested}))


if __name__ == "__main__":
    unittest.main()
