from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "agent_equipment_json_schema",
    ROOT / "scripts/agent_equipment_json_schema.py",
)
assert SPEC is not None and SPEC.loader is not None
SCHEMA = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SCHEMA
SPEC.loader.exec_module(SCHEMA)


class AgentEquipmentJsonSchemaTests(unittest.TestCase):
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

    def test_evaluates_types_values_and_scalar_constraints_exactly(self) -> None:
        rejected_cases = (
            (True, {"type": "integer"}),
            (True, {"type": "number"}),
            (1, {"type": "boolean"}),
            (None, {"type": "string"}),
            (1.0, {"const": 1}),
            (1.0, {"enum": [1]}),
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
