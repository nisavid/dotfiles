from __future__ import annotations

import hashlib
import json
import shutil
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "home/private_dot_local/lib/agent-equipment"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from agent_equipment import validator
from agent_equipment._json_schema import (
    validate_document,
    validate_schema_documents,
)

DOCUMENTS = ROOT / "docs/agent-equipment"
INSTALLED_SCHEMAS = ROOT / "home/private_dot_local/lib/agent-equipment/schemas"
SCHEMA_NAMES = (
    "adapter-contract-v1.schema.json",
    "execution-authority-v1.schema.json",
)


def normalized_state() -> dict[str, object]:
    return {
        "route_presence": "present",
        "enablement": "enabled",
        "configuration": {"status": "not_applicable"},
        "component_states": [],
        "observed_version": {"status": "not_applicable"},
        "immutable_content": {
            "status": "observed",
            "revision": "a" * 40,
            "content_digest": "sha256:" + "b" * 64,
        },
        "native_update_control": "not_applicable",
        "native_update_suppression_state": "not_applicable",
        "manager_drift": {
            "status": "not_applicable",
            "reviewed_baseline": None,
            "observation_source": None,
        },
    }


class ImmutableContentSchemaTests(unittest.TestCase):
    def validate_normalized_state(
        self,
        schema_name: str,
        document: object,
    ) -> bool:
        with TemporaryDirectory() as directory:
            schema_directory = Path(directory)
            root_name = "normalized-state-root.json"
            root_schema = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$ref": f"{schema_name}#/$defs/normalizedState",
            }
            (schema_directory / root_name).write_text(
                json.dumps(root_schema),
                encoding="utf-8",
            )
            shutil.copyfile(
                DOCUMENTS / schema_name,
                schema_directory / schema_name,
            )
            allowed = {root_name, schema_name}
            if schema_name == "adapter-contract-v1.schema.json":
                catalog_name = "catalog-v1.schema.json"
                shutil.copyfile(
                    DOCUMENTS / catalog_name,
                    schema_directory / catalog_name,
                )
                allowed.add(catalog_name)
            return validate_document(
                document,
                schema_directory=schema_directory,
                root_schema_name=root_name,
                allowed_schema_names=frozenset(allowed),
            )

    def assert_state_valid_for_both_contracts(self, state: object) -> None:
        for schema_name in SCHEMA_NAMES:
            with self.subTest(schema=schema_name):
                self.assertTrue(self.validate_normalized_state(schema_name, state))

    def assert_state_invalid_for_both_contracts(self, state: object) -> None:
        for schema_name in SCHEMA_NAMES:
            with self.subTest(schema=schema_name):
                self.assertFalse(self.validate_normalized_state(schema_name, state))

    def test_normalized_state_requires_closed_immutable_content_evidence(
        self,
    ) -> None:
        base = normalized_state()
        self.assert_state_valid_for_both_contracts(base)

        revision_64 = deepcopy(base)
        revision_64_content = revision_64["immutable_content"]
        assert isinstance(revision_64_content, dict)
        revision_64_content["revision"] = "c" * 64
        self.assert_state_valid_for_both_contracts(revision_64)

        truthfully_unknown = deepcopy(base)
        truthfully_unknown["immutable_content"] = {"status": "unknown"}
        self.assert_state_valid_for_both_contracts(truthfully_unknown)

        for status in ("route_absent", "unknown", "not_applicable"):
            with self.subTest(status=status):
                tagged = deepcopy(base)
                tagged["immutable_content"] = {"status": status}
                if status == "route_absent":
                    tagged["route_presence"] = "absent"
                elif status == "unknown":
                    tagged["route_presence"] = "partial"
                self.assert_state_valid_for_both_contracts(tagged)

        invalid_states: list[tuple[str, dict[str, object]]] = []
        missing = deepcopy(base)
        del missing["immutable_content"]
        invalid_states.append(("missing", missing))

        for label, immutable_content in (
            ("partial-observed", {"status": "observed", "revision": "a" * 40}),
            (
                "short-revision",
                {
                    "status": "observed",
                    "revision": "a" * 39,
                    "content_digest": "sha256:" + "b" * 64,
                },
            ),
            (
                "uppercase-revision",
                {
                    "status": "observed",
                    "revision": "A" * 40,
                    "content_digest": "sha256:" + "b" * 64,
                },
            ),
            (
                "invalid-digest",
                {
                    "status": "observed",
                    "revision": "a" * 40,
                    "content_digest": "sha256:" + "g" * 64,
                },
            ),
            ("tag-with-payload", {"status": "unknown", "revision": "a" * 40}),
        ):
            candidate = deepcopy(base)
            candidate["immutable_content"] = immutable_content
            invalid_states.append((label, candidate))

        observed_while_absent = deepcopy(base)
        observed_while_absent["route_presence"] = "absent"
        invalid_states.append(("observed-while-absent", observed_while_absent))

        observed_while_partial = deepcopy(base)
        observed_while_partial["route_presence"] = "partial"
        invalid_states.append(("observed-while-partial", observed_while_partial))

        absent_while_present = deepcopy(base)
        absent_while_present["immutable_content"] = {"status": "route_absent"}
        invalid_states.append(("route-absent-while-present", absent_while_present))

        unknown_while_absent = deepcopy(base)
        unknown_while_absent["route_presence"] = "absent"
        unknown_while_absent["immutable_content"] = {"status": "unknown"}
        invalid_states.append(("unknown-while-absent", unknown_while_absent))

        for label, candidate in invalid_states:
            with self.subTest(case=label):
                self.assert_state_invalid_for_both_contracts(candidate)

    def test_observed_version_accepts_closed_not_applicable_tag(self) -> None:
        state = normalized_state()
        self.assert_state_valid_for_both_contracts(state)

        invalid = deepcopy(state)
        invalid["observed_version"] = {
            "status": "not_applicable",
            "value": "must-not-be-present",
        }
        self.assert_state_invalid_for_both_contracts(invalid)

    def test_absent_observed_version_requires_an_absent_route(self) -> None:
        absent = normalized_state()
        absent["route_presence"] = "absent"
        absent["observed_version"] = {"status": "route_absent"}
        absent["immutable_content"] = {"status": "not_applicable"}
        self.assert_state_valid_for_both_contracts(absent)

        for route_presence in ("present", "partial", "unknown"):
            with self.subTest(route_presence=route_presence):
                invalid = deepcopy(absent)
                invalid["route_presence"] = route_presence
                self.assert_state_invalid_for_both_contracts(invalid)

    def test_authoritative_and_installed_schemas_are_valid_and_digest_pinned(
        self,
    ) -> None:
        for schema_name in SCHEMA_NAMES:
            with self.subTest(schema=schema_name):
                authoritative_bytes = (DOCUMENTS / schema_name).read_bytes()
                installed_bytes = (INSTALLED_SCHEMAS / schema_name).read_bytes()
                self.assertEqual(installed_bytes, authoritative_bytes)
                self.assertEqual(
                    hashlib.sha256(authoritative_bytes).hexdigest(),
                    validator.EXPECTED_SCHEMA_SHA256[schema_name],
                )

                schema_document = json.loads(authoritative_bytes)
                allowed_documents = {schema_name: schema_document}
                if schema_name == "adapter-contract-v1.schema.json":
                    catalog_name = "catalog-v1.schema.json"
                    allowed_documents[catalog_name] = json.loads(
                        (DOCUMENTS / catalog_name).read_bytes()
                    )
                self.assertTrue(
                    validate_schema_documents(
                        allowed_documents,
                        allowed_schema_names=frozenset(allowed_documents),
                    )
                )


if __name__ == "__main__":
    unittest.main()
