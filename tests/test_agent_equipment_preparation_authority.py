from __future__ import annotations

import base64
import copy
import hashlib
import json
import sys
import unittest
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = ROOT / "agent-equipment-preparation-authority/src"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))
INSTALLED_PACKAGE_ROOT = ROOT / "home/private_dot_local/lib/agent-equipment"
if str(INSTALLED_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(1, str(INSTALLED_PACKAGE_ROOT))

import agent_equipment_preparation as PREPARATION
from agent_equipment.secrets import contains_literal_credential

from tests import test_agent_equipment_deployment_contract as CONTRACT

SCHEMA_NAMES = (
    "adapter-contract-v1.schema.json",
    "captured-state-v1.schema.json",
    "execution-authority-v1.schema.json",
    "plan-action-set-v1.schema.json",
)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def digest(value: object) -> str:
    return byte_digest(canonical_bytes(value))


def byte_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def seal(
    document: dict[str, object], identity_field: str, identity_prefix: str
) -> None:
    identity_payload = copy.deepcopy(document)
    identity_payload.pop(identity_field, None)
    identity_payload.pop("manifest_digest", None)
    identity_payload.pop("manifest_set_digest", None)
    identity_payload.pop("adapter_manifest_digest", None)
    identity_payload.pop("adapter_manifest_set_digest", None)
    document[identity_field] = identity_prefix + digest(identity_payload)
    digest_field = {
        "adapter_manifest_identity": "adapter_manifest_digest",
        "adapter_manifest_set_identity": "adapter_manifest_set_digest",
        "manifest_set_identity": "manifest_set_digest",
    }.get(identity_field, "manifest_digest")
    digest_payload = copy.deepcopy(document)
    digest_payload.pop(digest_field, None)
    document[digest_field] = digest(digest_payload)


def schema_documents() -> dict[str, bytes]:
    directory = ROOT / "home/private_dot_local/lib/agent-equipment/schemas"
    return {name: (directory / name).read_bytes() for name in SCHEMA_NAMES}


def gate_manifest(schemas: dict[str, bytes]) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "agent-equipment-preparation-gate-manifest/v1",
        "gate_identity": "preparation-gate:agent-equipment/v1",
        "runtime_identity": "cpython:3.14.0",
        "runtime_executable_digest": "sha256:" + "1" * 64,
        "files": [
            {
                "path": "agent_equipment_preparation/__init__.py",
                "digest": "sha256:" + "2" * 64,
            },
            {
                "path": "agent_equipment_preparation/preparation.py",
                "digest": "sha256:" + "3" * 64,
            },
        ],
        "schema_digests": [
            {"name": name, "digest": byte_digest(schemas[name])}
            for name in sorted(schemas)
        ],
        "manifest_digest": "sha256:" + "0" * 64,
    }
    payload = copy.deepcopy(document)
    payload.pop("manifest_digest")
    document["manifest_digest"] = digest(payload)
    return document


def adapter_manifest(action: dict[str, object]) -> dict[str, object]:
    document: dict[str, object] = {
        "adapter_manifest_identity": (
            "preparation-adapter-manifest:sha256:" + "0" * 64
        ),
        "adapter_identity": action["adapter_identity"],
        "adapter_version": action["adapter_version"],
        "adapter_implementation_identity": (
            "adapter-implementation:fixture/claude-plugin-v1"
        ),
        "adapter_implementation_manifest_digest": "sha256:" + "4" * 64,
        "capability_binding": {
            "capability_identity": action["capability_identity"],
            "capability_digest": action["capability_digest"],
            "manager_version_evidence_digest": action[
                "manager_version_evidence_digest"
            ],
        },
        "prepare_seam": {
            "entrypoint": "prepare",
            "effect": "read_only",
            "request_record": "PrepareRequest",
            "response_record": "PreparedStateFacts",
        },
        "adapter_manifest_digest": "sha256:" + "0" * 64,
    }
    seal(
        document,
        "adapter_manifest_identity",
        "preparation-adapter-manifest:",
    )
    return document


def adapter_manifest_set(manifests: list[dict[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "agent-equipment-preparation-adapter-manifest-set/v1",
        "adapter_manifest_set_identity": (
            "preparation-adapter-manifest-set:sha256:" + "0" * 64
        ),
        "manifests": sorted(
            copy.deepcopy(manifests),
            key=lambda item: str(item["adapter_manifest_identity"]),
        ),
        "adapter_manifest_set_digest": "sha256:" + "0" * 64,
    }
    seal(
        document,
        "adapter_manifest_set_identity",
        "preparation-adapter-manifest-set:",
    )
    return document


def empty_plan_and_capture() -> tuple[dict[str, object], dict[str, object]]:
    plan = CONTRACT.valid_plan_action_set(1)
    plan["actions"] = []
    plan["action_set_digest"] = CONTRACT.EXECUTION_AUTHORITY._plan_action_set_digest(
        plan["candidate_identity"],
        plan["implementation_manifest_digest"],
        plan["plan_digest"],
        [],
    )
    capture = CONTRACT.valid_captured_state(CONTRACT.valid_plan_action_set(1))
    capture["bindings"]["plan_action_set_digest"] = plan["action_set_digest"]
    capture["provider_routes"] = []
    capture["surfaces"] = []
    return plan, capture


def preparation_trust(
    plan: dict[str, object], capture: dict[str, object]
) -> PREPARATION.PreparationTrust:
    return PREPARATION.PreparationTrust(
        expected_candidate_identity=str(plan["candidate_identity"]),
        expected_implementation_manifest_digest=str(
            plan["implementation_manifest_digest"]
        ),
        expected_plan_digest=str(plan["plan_digest"]),
        expected_plan_action_set_digest=str(plan["action_set_digest"]),
        expected_captured_state_identity="capture:fixture/run-v1",
        expected_captured_state_digest=digest(capture),
        expected_capability_set_digest=str(
            capture["bindings"]["capability_set_digest"]
        ),
    )


def reseal_plan_and_capture(
    plan: dict[str, object], capture: dict[str, object]
) -> None:
    references_by_route = {
        route["route_id"]: route["planned_actions"]
        for route in capture["provider_routes"]
    }
    for evidence in plan["actions"]:
        action = evidence["action_payload"]
        action["desired_state_digest"] = digest(action["desired_state"])
        action["action_identity"] = PREPARATION.preparation._plan_action_identity(
            action
        )
        evidence["action_digest"] = digest(action)
        references = references_by_route[action["route_identity"]]
        matching = next(
            reference
            for reference in references
            if reference["action_identity"] == action["action_identity"]
            or len(references) == 1
        )
        matching["action_identity"] = action["action_identity"]
        matching["action_digest"] = evidence["action_digest"]
    plan["action_set_digest"] = PREPARATION.preparation._plan_action_set_digest(plan)
    capture["bindings"]["plan_action_set_digest"] = plan["action_set_digest"]


class FactsAdapter:
    def __init__(self) -> None:
        self.requests: list[bytes] = []
        self.responses: list[bytes] = []

    def prepare(self, request_bytes: bytes) -> bytes:
        self.requests.append(request_bytes)
        request = json.loads(request_bytes)
        response: dict[str, object] = {
            "contract_version": "adapter-contract-v1",
            "request_identity": request["request_identity"],
            "request_digest": request["request_digest"],
            "echo_bindings": copy.deepcopy(request["echo_bindings"]),
            "captured_pre_state": CONTRACT.normalized_state(present=False),
            "captured_pre_state_digest": digest(
                CONTRACT.normalized_state(present=False)
            ),
            "expected_post_state": CONTRACT.normalized_state(present=True),
            "expected_post_state_digest": digest(
                CONTRACT.normalized_state(present=True)
            ),
            "facts_digest": "sha256:" + "0" * 64,
        }
        payload = copy.deepcopy(response)
        payload.pop("facts_digest")
        response["facts_digest"] = digest(payload)
        response_bytes = canonical_bytes(response)
        self.responses.append(response_bytes)
        return response_bytes


class AdapterWithMutationCapability(FactsAdapter):
    def apply(self, request_bytes: bytes) -> bytes:
        del request_bytes
        raise AssertionError("a preparation handle must not expose mutation")


class RuntimeErrorAdapter(FactsAdapter):
    def prepare(self, request_bytes: bytes) -> bytes:
        self.requests.append(request_bytes)
        raise RuntimeError("simulated adapter failure")


class ForeignScopeAdapter(FactsAdapter):
    def prepare(self, request_bytes: bytes) -> bytes:
        response = json.loads(super().prepare(request_bytes))
        response["surface"] = ["surface:attacker/selected"]
        return canonical_bytes(response)


class NonCanonicalFactsAdapter(FactsAdapter):
    def prepare(self, request_bytes: bytes) -> bytes:
        response = json.loads(super().prepare(request_bytes))
        return json.dumps(response, indent=2, sort_keys=True).encode("utf-8")


class LiteralSecretFactsAdapter(FactsAdapter):
    def prepare(self, request_bytes: bytes) -> bytes:
        response = json.loads(super().prepare(request_bytes))
        pre_state = response["captured_pre_state"]
        pre_state["manager_drift"]["reviewed_baseline"] = "ghp_" + "A" * 36
        response["captured_pre_state_digest"] = digest(pre_state)
        payload = copy.deepcopy(response)
        payload.pop("facts_digest")
        response["facts_digest"] = digest(payload)
        return canonical_bytes(response)


class BearerLiteralSecretFactsAdapter(FactsAdapter):
    def prepare(self, request_bytes: bytes) -> bytes:
        response = json.loads(super().prepare(request_bytes))
        pre_state = response["captured_pre_state"]
        pre_state["manager_drift"]["reviewed_baseline"] = "Bearer " + "A" * 48
        response["captured_pre_state_digest"] = digest(pre_state)
        payload = copy.deepcopy(response)
        payload.pop("facts_digest")
        response["facts_digest"] = digest(payload)
        return canonical_bytes(response)


class ConfigureFactsAdapter(FactsAdapter):
    def __init__(
        self,
        *,
        configuration_status: str = "observed",
        configuration_digest: str | None = None,
    ) -> None:
        super().__init__()
        self._configuration_status = configuration_status
        self._configuration_digest = configuration_digest

    def prepare(self, request_bytes: bytes) -> bytes:
        request = json.loads(request_bytes)
        response = json.loads(super().prepare(request_bytes))
        desired_configuration = request["desired_state"]["configuration"]
        expected_post_state = response["expected_post_state"]
        expected_post_state["configuration"] = {
            "status": self._configuration_status,
            "digest": self._configuration_digest
            or desired_configuration["digest"],
        }
        response["expected_post_state_digest"] = digest(expected_post_state)
        payload = copy.deepcopy(response)
        payload.pop("facts_digest")
        response["facts_digest"] = digest(payload)
        return canonical_bytes(response)


class ForeignComponentFactsAdapter(FactsAdapter):
    def __init__(self, state_field: str) -> None:
        super().__init__()
        self._state_field = state_field

    def prepare(self, request_bytes: bytes) -> bytes:
        response = json.loads(super().prepare(request_bytes))
        state = response[self._state_field]
        state["component_states"] = [
            {"equipment_identity": "skill:fixture/foreign", "state": "absent"}
        ]
        response[f"{self._state_field}_digest"] = digest(state)
        payload = copy.deepcopy(response)
        payload.pop("facts_digest")
        response["facts_digest"] = digest(payload)
        return canonical_bytes(response)


class PreparationAuthorityTests(unittest.TestCase):
    def build_gate(
        self,
        directory: str,
        plan: dict[str, object],
        adapter: object,
        *,
        adapter_implementation_manifest_digest: str = "sha256:" + "4" * 64,
        gate_runtime_identity: str = "cpython:3.14.0",
        store_identity: str = "preparation-store:fixture/protected-v1",
        store_override: object | None = None,
    ) -> tuple[PREPARATION.PreparationGate, object]:
        schemas = schema_documents()
        manifest = gate_manifest(schemas)
        manifest["runtime_identity"] = gate_runtime_identity
        manifest_payload = copy.deepcopy(manifest)
        manifest_payload.pop("manifest_digest")
        manifest["manifest_digest"] = digest(manifest_payload)
        actions = plan["actions"]
        assert isinstance(actions, list)
        manifests_by_identity = {}
        for action_evidence in actions:
            adapter_document = adapter_manifest(action_evidence["action_payload"])
            adapter_document["adapter_implementation_manifest_digest"] = (
                adapter_implementation_manifest_digest
            )
            seal(
                adapter_document,
                "adapter_manifest_identity",
                "preparation-adapter-manifest:",
            )
            manifests_by_identity[
                str(adapter_document["adapter_manifest_identity"])
            ] = adapter_document
        manifests = list(manifests_by_identity.values())
        manifest_set = adapter_manifest_set(manifests)
        bound_adapters = tuple(
            PREPARATION.BoundPreparationAdapter(
                manifest_bytes=canonical_bytes(adapter_manifest_document),
                adapter=adapter,
            )
            for adapter_manifest_document in manifests
        )
        store = store_override or PREPARATION.FilePreparationStore(
            Path(directory), store_identity=store_identity
        )
        gate = PREPARATION.PreparationGate(
            gate_manifest_bytes=canonical_bytes(manifest),
            expected_gate_manifest_digest=str(manifest["manifest_digest"]),
            schema_documents=schemas,
            adapters=bound_adapters,
            expected_adapter_manifest_set_digest=str(
                manifest_set["adapter_manifest_set_digest"]
            ),
            store=store,  # type: ignore[arg-type]
        )
        return gate, store

    def test_empty_action_set_is_a_terminal_verified_noop(self) -> None:
        plan, capture = empty_plan_and_capture()
        adapter = FactsAdapter()
        with TemporaryDirectory() as directory:
            gate, store = self.build_gate(directory, plan, adapter)
            result = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                preparation_trust(plan, capture),
            )

            self.assertIsInstance(result, PREPARATION.VerifiedPreparationNoOp)
            self.assertEqual(adapter.requests, [])
            self.assertEqual(store.entry_count(), 0)
            self.assertFalse(hasattr(result, "bundle_bytes"))
            self.assertFalse(hasattr(result, "receipt_bytes"))

    def test_static_preflight_rejects_before_any_prepare_or_store_call(self) -> None:
        plan = CONTRACT.valid_plan_action_set(1)
        capture = CONTRACT.valid_captured_state(plan)
        adapter = FactsAdapter()
        trust = preparation_trust(plan, capture)
        trust = PREPARATION.PreparationTrust(
            **{
                **trust.as_dict(),
                "expected_plan_action_set_digest": "sha256:" + "9" * 64,
            }
        )
        with TemporaryDirectory() as directory:
            gate, store = self.build_gate(directory, plan, adapter)
            result = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                trust,
            )

            self.assertIsInstance(result, PREPARATION.PreparationRejection)
            self.assertEqual(adapter.requests, [])
            self.assertEqual(store.entry_count(), 0)

    def test_untyped_split_view_trust_is_rejected_before_any_effect(self) -> None:
        plan = CONTRACT.valid_plan_action_set(1)
        capture = CONTRACT.valid_captured_state(plan)
        fixed_trust = preparation_trust(plan, capture)

        class SplitViewTrust:
            def as_dict(self) -> dict[str, object]:
                return fixed_trust.as_dict()

            def __getattr__(self, name: str) -> object:
                if name == "expected_captured_state_identity":
                    return "capture:attacker/substituted-v1"
                return getattr(fixed_trust, name)

        adapter = FactsAdapter()
        with TemporaryDirectory() as directory:
            gate, store = self.build_gate(directory, plan, adapter)

            result = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                SplitViewTrust(),  # type: ignore[arg-type]
            )

            self.assertIsInstance(result, PREPARATION.PreparationRejection)
            self.assertEqual(adapter.requests, [])
            self.assertEqual(store.entry_count(), 0)

    def test_gate_uses_one_immutable_schema_view_for_validation_and_manifest(self) -> None:
        legitimate = schema_documents()
        permissive = {
            "adapter-contract-v1.schema.json": canonical_bytes(
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$defs": {
                        name: {}
                        for name in (
                            "gateManifest",
                            "adapterManifest",
                            "adapterManifestSet",
                            "capabilityBindingSet",
                            "prepareRequest",
                            "preparedStateFacts",
                        )
                    },
                }
            ),
            "captured-state-v1.schema.json": canonical_bytes(
                {"$schema": "https://json-schema.org/draft/2020-12/schema"}
            ),
            "execution-authority-v1.schema.json": canonical_bytes(
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$defs": {
                        name: {}
                        for name in (
                            "captureObservationAuthoritySet",
                            "preparedActionAuthoritySet",
                            "preparationBundle",
                            "preparationReceipt",
                        )
                    },
                }
            ),
            "plan-action-set-v1.schema.json": canonical_bytes(
                {"$schema": "https://json-schema.org/draft/2020-12/schema"}
            ),
        }

        class SplitSchemas(Mapping[str, bytes]):
            def __init__(self) -> None:
                self.reads = 0

            def __len__(self) -> int:
                return len(legitimate)

            def __iter__(self):  # type: ignore[no-untyped-def]
                return iter(legitimate)

            def __getitem__(self, key: str) -> bytes:
                return legitimate[key]

            def items(self):  # type: ignore[no-untyped-def]
                self.reads += 1
                return (
                    permissive if self.reads == 1 else legitimate
                ).items()

        plan = CONTRACT.valid_plan_action_set(1)
        action = plan["actions"][0]["action_payload"]
        manifest = gate_manifest(legitimate)
        adapter_document = adapter_manifest(action)
        manifest_set = adapter_manifest_set([adapter_document])
        split = SplitSchemas()
        with TemporaryDirectory() as directory, self.assertRaises(ValueError):
            PREPARATION.PreparationGate(
                gate_manifest_bytes=canonical_bytes(manifest),
                expected_gate_manifest_digest=str(manifest["manifest_digest"]),
                schema_documents=split,
                adapters=(
                    PREPARATION.BoundPreparationAdapter(
                        manifest_bytes=canonical_bytes(adapter_document),
                        adapter=FactsAdapter(),
                    ),
                ),
                expected_adapter_manifest_set_digest=str(
                    manifest_set["adapter_manifest_set_digest"]
                ),
                store=PREPARATION.FilePreparationStore(
                    Path(directory),
                    store_identity="preparation-store:fixture/protected-v1",
                ),
            )

        self.assertEqual(split.reads, 1)

    def test_static_preflight_rejects_an_unbound_mutable_captured_surface(self) -> None:
        plan = CONTRACT.valid_plan_action_set(1)
        capture = CONTRACT.valid_captured_state(plan)
        orphan = copy.deepcopy(capture["surfaces"][0])
        orphan["surface_id"] = "surface:fixture/orphan-preparation"
        capture["surfaces"].append(orphan)
        adapter = FactsAdapter()

        with TemporaryDirectory() as directory:
            gate, store = self.build_gate(directory, plan, adapter)
            result = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                preparation_trust(plan, capture),
            )

            self.assertIsInstance(result, PREPARATION.PreparationRejection)
            self.assertEqual(adapter.requests, [])
            self.assertEqual(store.entry_count(), 0)

    def test_static_preflight_rejects_invalid_closed_capture_bindings(self) -> None:
        def foreign_target(capture: dict[str, object]) -> None:
            capture["provider_routes"][0]["planned_actions"][0]["write_bindings"][0][
                "target_identity"
            ] = "target:sha256:" + "f" * 64

        def forbidden_write_surface(capture: dict[str, object]) -> None:
            route = capture["provider_routes"][0]
            canonical_surface = next(
                surface
                for surface in capture["surfaces"]
                if surface["kind"] == "canonical_skill_entry"
            )
            skill_binding = next(
                binding
                for binding in route["planned_actions"][0]["write_bindings"]
                if binding["surface_id"]
                == route["surface_references"]["skill_entries"][0]["surface_id"]
            )
            skill_binding["surface_id"] = canonical_surface["surface_id"]

        def duplicate_target_binding(capture: dict[str, object]) -> None:
            bindings = capture["provider_routes"][0]["planned_actions"][0][
                "write_bindings"
            ]
            bindings[1]["target_identity"] = bindings[0]["target_identity"]

        def missing_target_binding(capture: dict[str, object]) -> None:
            capture["provider_routes"][0]["planned_actions"][0]["write_bindings"].pop()

        def foreign_dependency(capture: dict[str, object]) -> None:
            capture["provider_routes"][0]["planned_actions"][0][
                "verification_dependency_bindings"
            ][0]["dependency_identity"] = "dependency:sha256:" + "f" * 64

        def missing_dependency(capture: dict[str, object]) -> None:
            capture["provider_routes"][0]["planned_actions"][0][
                "verification_dependency_bindings"
            ].clear()

        def extra_action_reference(capture: dict[str, object]) -> None:
            references = capture["provider_routes"][0]["planned_actions"]
            foreign = copy.deepcopy(references[0])
            foreign["action_identity"] = "action:sha256:" + "f" * 64
            foreign["action_digest"] = "sha256:" + "f" * 64
            references.append(foreign)

        def extra_route(capture: dict[str, object]) -> None:
            route = copy.deepcopy(capture["provider_routes"][0])
            route["route_id"] = "route:fixture/foreign-capture"
            route["planned_actions"] = []
            capture["provider_routes"].append(route)

        def operator_owned_route(capture: dict[str, object]) -> None:
            capture["provider_routes"][0]["control_owner"] = "operator_owned"

        def unrepresented_route_equipment(capture: dict[str, object]) -> None:
            equipment = capture["provider_routes"][0]["equipment_identities"]
            equipment.append("skill:fixture/unrepresented")
            equipment.sort()

        def extra_canonical_dependency(capture: dict[str, object]) -> None:
            canonical = next(
                surface
                for surface in capture["surfaces"]
                if surface["kind"] == "canonical_skill_entry"
            )
            extra = copy.deepcopy(canonical)
            extra["surface_id"] = "surface:fixture/extra-canonical-dependency"
            extra["locator"]["path"] = "~/.agents/skills/extra-canonical"
            capture["surfaces"].append(extra)
            capture["provider_routes"][0]["surface_references"][
                "canonical_skill_dependencies"
            ].append({"status": "captured", "surface_id": extra["surface_id"]})

        mutations = {
            "foreign target": foreign_target,
            "forbidden write surface": forbidden_write_surface,
            "duplicate target binding": duplicate_target_binding,
            "missing target binding": missing_target_binding,
            "foreign dependency": foreign_dependency,
            "missing dependency": missing_dependency,
            "extra action reference": extra_action_reference,
            "extra route": extra_route,
            "operator-owned route": operator_owned_route,
            "unrepresented route equipment": unrepresented_route_equipment,
            "extra canonical dependency": extra_canonical_dependency,
        }

        for name, mutate in mutations.items():
            with self.subTest(name=name), TemporaryDirectory() as directory:
                plan = CONTRACT.valid_plan_action_set(1)
                capture = CONTRACT.valid_captured_state(plan)
                mutate(capture)
                adapter = FactsAdapter()
                gate, store = self.build_gate(directory, plan, adapter)

                result = gate.prepare(
                    canonical_bytes(plan),
                    canonical_bytes(capture),
                    preparation_trust(plan, capture),
                )

                self.assertIsInstance(result, PREPARATION.PreparationRejection)
                self.assertEqual(adapter.requests, [])
                self.assertEqual(store.entry_count(), 0)

    def test_static_preflight_rejects_invalid_plan_semantics(self) -> None:
        def desired_state_overreach(
            plan: dict[str, object], capture: dict[str, object]
        ) -> None:
            del capture
            action = plan["actions"][0]["action_payload"]
            action["desired_state"]["enablement"] = "enabled"

        def undeclared_provider_secret(
            plan: dict[str, object], capture: dict[str, object]
        ) -> None:
            del capture
            action = plan["actions"][0]["action_payload"]
            provider = action["provider"]
            provider["arguments"].append(
                {"secret_reference": "TOKEN", "template": "{reference}"}
            )
            action["desired_state"] = {
                "configuration": {
                    "status": "desired",
                    "digest": digest(
                        {
                            "provider": provider,
                            "component_controls": [],
                        }
                    ),
                }
            }

        cases = {
            "operation-derived desired state": (
                CONTRACT.valid_plan_action_set,
                desired_state_overreach,
            ),
            "provider-consumed secret declaration": (
                lambda: CONTRACT.valid_provider_family_plan_action_set("direct_mcp"),
                undeclared_provider_secret,
            ),
        }
        for name, (build_plan, mutate) in cases.items():
            with self.subTest(name=name), TemporaryDirectory() as directory:
                plan = build_plan()
                capture = CONTRACT.valid_captured_state(plan)
                mutate(plan, capture)
                reseal_plan_and_capture(plan, capture)
                adapter = FactsAdapter()
                gate, store = self.build_gate(directory, plan, adapter)

                result = gate.prepare(
                    canonical_bytes(plan),
                    canonical_bytes(capture),
                    preparation_trust(plan, capture),
                )

                self.assertIsInstance(result, PREPARATION.PreparationRejection)
                self.assertEqual(adapter.requests, [])
                self.assertEqual(store.entry_count(), 0)

    def test_static_preflight_rejects_incoherent_capture_observation_and_recovery(
        self,
    ) -> None:
        def present_installation(capture: dict[str, object]) -> None:
            installation = next(
                surface
                for surface in capture["surfaces"]
                if surface["kind"] == "plugin_installation"
            )
            installation["observation"] = {
                "installed": True,
                "channel": "foreign",
                "observed_version": "9.9.9",
                "observation_source": "foreign",
            }

        def invalid_absent_skill_recovery(capture: dict[str, object]) -> None:
            skill = next(
                surface
                for surface in capture["surfaces"]
                if surface["kind"] == "claude_skill_entry"
            )
            skill["recovery"] = {"kind": "none", "reason": "verification_only"}

        for name, mutate in {
            "present native forward-install surface": present_installation,
            "absent Claude skill recovery": invalid_absent_skill_recovery,
        }.items():
            with self.subTest(name=name), TemporaryDirectory() as directory:
                plan = CONTRACT.valid_plan_action_set(1)
                capture = CONTRACT.valid_captured_state(plan)
                mutate(capture)
                adapter = FactsAdapter()
                gate, store = self.build_gate(directory, plan, adapter)

                result = gate.prepare(
                    canonical_bytes(plan),
                    canonical_bytes(capture),
                    preparation_trust(plan, capture),
                )

                self.assertIsInstance(result, PREPARATION.PreparationRejection)
                self.assertEqual(adapter.requests, [])
                self.assertEqual(store.entry_count(), 0)

    def test_static_preflight_rejects_invalid_capability_inventory(self) -> None:
        def duplicate_identity(capture: dict[str, object]) -> None:
            bindings = capture["bindings"]["capability_bindings"]
            duplicate = copy.deepcopy(bindings[0])
            duplicate["capability_digest"] = "sha256:" + "5" * 64
            duplicate["manager_version_evidence_digest"] = "sha256:" + "6" * 64
            bindings.append(duplicate)
            bindings.sort(
                key=lambda item: (
                    item["capability_identity"],
                    item["capability_digest"],
                    item["manager_version_evidence_digest"],
                )
            )
            capture["bindings"]["capability_set_digest"] = digest(bindings)

        def reverse_canonical_order(capture: dict[str, object]) -> None:
            bindings = capture["bindings"]["capability_bindings"]
            second = copy.deepcopy(bindings[0])
            second["capability_identity"] = "capability:zz-fixture-v1"
            second["capability_digest"] = "sha256:" + "5" * 64
            second["manager_version_evidence_digest"] = "sha256:" + "6" * 64
            bindings.append(second)
            canonical = sorted(
                bindings,
                key=lambda item: (
                    item["capability_identity"],
                    item["capability_digest"],
                    item["manager_version_evidence_digest"],
                ),
            )
            capture["bindings"]["capability_set_digest"] = digest(canonical)
            bindings.reverse()

        def replace_with_unbound_capability(capture: dict[str, object]) -> None:
            bindings = capture["bindings"]["capability_bindings"]
            bindings[0] = {
                "capability_identity": "capability:foreign-fixture-v1",
                "capability_digest": "sha256:" + "5" * 64,
                "manager_version_evidence_digest": "sha256:" + "6" * 64,
            }
            capture["bindings"]["capability_set_digest"] = digest(bindings)

        for name, mutate in {
            "duplicate identity": duplicate_identity,
            "reordered inventory": reverse_canonical_order,
            "unbound capability": replace_with_unbound_capability,
        }.items():
            with self.subTest(name=name), TemporaryDirectory() as directory:
                plan = CONTRACT.valid_plan_action_set(1)
                capture = CONTRACT.valid_captured_state(plan)
                mutate(capture)
                adapter = FactsAdapter()
                gate, store = self.build_gate(directory, plan, adapter)

                result = gate.prepare(
                    canonical_bytes(plan),
                    canonical_bytes(capture),
                    preparation_trust(plan, capture),
                )

                self.assertIsInstance(result, PREPARATION.PreparationRejection)
                self.assertEqual(adapter.requests, [])
                self.assertEqual(store.entry_count(), 0)

    def test_gate_rejects_an_adapter_handle_that_exposes_mutation(self) -> None:
        plan = CONTRACT.valid_plan_action_set(1)

        with TemporaryDirectory() as directory, self.assertRaises(ValueError):
            self.build_gate(
                directory,
                plan,
                AdapterWithMutationCapability(),
            )

    def test_gate_rejects_an_untyped_store_capability(self) -> None:
        plan = CONTRACT.valid_plan_action_set(1)
        adapter = FactsAdapter()

        class StoreProxy:
            def __init__(self, store: PREPARATION.FilePreparationStore) -> None:
                self._store = store

            @property
            def store_identity(self) -> str:
                return self._store.store_identity

            def commit(self, *args: object, **kwargs: object) -> object:
                return self._store.commit(*args, **kwargs)  # type: ignore[arg-type]

            def resolve_receipt(self, receipt_bytes: bytes) -> object:
                return self._store.resolve_receipt(receipt_bytes)

        with TemporaryDirectory() as directory:
            store = PREPARATION.FilePreparationStore(
                Path(directory),
                store_identity="preparation-store:fixture/protected-v1",
            )
            with self.assertRaises(ValueError):
                self.build_gate(
                    directory,
                    plan,
                    adapter,
                    store_override=StoreProxy(store),
                )

    def test_gate_calls_the_prepare_capability_bound_at_construction(self) -> None:
        plan = CONTRACT.valid_plan_action_set(1)
        capture = CONTRACT.valid_captured_state(plan)
        adapter = FactsAdapter()
        effects: list[str] = []
        with TemporaryDirectory() as directory:
            gate, store = self.build_gate(directory, plan, adapter)
            original_prepare = adapter.prepare

            def replacement(request_bytes: bytes) -> bytes:
                effects.append("mutating replacement called")
                return original_prepare(request_bytes)

            adapter.apply = replacement  # type: ignore[attr-defined]
            adapter.prepare = replacement  # type: ignore[method-assign]

            result = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                preparation_trust(plan, capture),
            )

            self.assertIsInstance(result, PREPARATION.PreparedBundleCommit)
            self.assertEqual(effects, [])
            self.assertEqual(len(adapter.requests), 1)
            self.assertEqual(store.entry_count(), 1)  # type: ignore[attr-defined]

    def test_gate_uses_store_capabilities_bound_at_construction(self) -> None:
        plan = CONTRACT.valid_plan_action_set(1)
        capture = CONTRACT.valid_captured_state(plan)
        adapter = FactsAdapter()
        effects: list[str] = []
        with TemporaryDirectory() as directory:
            gate, store = self.build_gate(directory, plan, adapter)

            def replacement_commit(*args: object, **kwargs: object) -> object:
                effects.append("replacement commit called")
                raise AssertionError((args, kwargs))

            def replacement_resolve(receipt_bytes: bytes) -> object:
                effects.append("replacement resolve called")
                raise AssertionError(receipt_bytes)

            store.commit = replacement_commit  # type: ignore[method-assign]
            store.resolve_receipt = replacement_resolve  # type: ignore[method-assign]

            first = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                preparation_trust(plan, capture),
            )
            self.assertIsInstance(first, PREPARATION.PreparedBundleCommit)
            assert isinstance(first, PREPARATION.PreparedBundleCommit)

            reused = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                preparation_trust(plan, capture),
                reuse_receipt_bytes=first.receipt_bytes,
            )

            self.assertIsInstance(reused, PREPARATION.PreparedBundleCommit)
            self.assertEqual(effects, [])
            self.assertEqual(store.entry_count(), 1)  # type: ignore[attr-defined]

    def test_external_failures_return_one_secret_free_rejection(self) -> None:
        plan = CONTRACT.valid_plan_action_set(1)
        capture = CONTRACT.valid_captured_state(plan)
        with TemporaryDirectory() as directory:
            adapter = RuntimeErrorAdapter()
            gate, store = self.build_gate(directory, plan, adapter)

            result = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                preparation_trust(plan, capture),
            )

            self.assertEqual(
                result,
                PREPARATION.PreparationRejection(
                    code="PREPARATION_REJECTED",
                    message="preparation failed closed",
                ),
            )
            self.assertEqual(len(adapter.requests), 1)
            self.assertEqual(store.entry_count(), 0)  # type: ignore[attr-defined]

        with TemporaryDirectory() as directory:
            adapter = FactsAdapter()
            store = PREPARATION.FilePreparationStore(
                Path(directory),
                store_identity="preparation-store:fixture/protected-v1",
            )
            with mock.patch.object(
                store,
                "commit",
                side_effect=RuntimeError("simulated store failure"),
            ):
                gate, _ = self.build_gate(
                    directory,
                    plan,
                    adapter,
                    store_override=store,
                )
                result = gate.prepare(
                    canonical_bytes(plan),
                    canonical_bytes(capture),
                    preparation_trust(plan, capture),
                )

            self.assertIsInstance(result, PREPARATION.PreparationRejection)
            self.assertEqual(store.entry_count(), 0)  # type: ignore[attr-defined]

        with TemporaryDirectory() as directory:
            adapter = FactsAdapter()
            gate, store = self.build_gate(directory, plan, adapter)
            first = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                preparation_trust(plan, capture),
            )
            self.assertIsInstance(first, PREPARATION.PreparedBundleCommit)
            assert isinstance(first, PREPARATION.PreparedBundleCommit)
            with mock.patch.object(
                store,
                "resolve_receipt",
                side_effect=RuntimeError("simulated resolver failure"),
            ):
                failing_gate, _ = self.build_gate(
                    directory,
                    plan,
                    adapter,
                    store_override=store,
                )
                result = failing_gate.prepare(
                    canonical_bytes(plan),
                    canonical_bytes(capture),
                    preparation_trust(plan, capture),
                    reuse_receipt_bytes=first.receipt_bytes,
                )

            self.assertIsInstance(result, PREPARATION.PreparationRejection)
            self.assertEqual(store.entry_count(), 1)  # type: ignore[attr-defined]

    def test_one_action_prepares_and_commits_one_complete_bundle(self) -> None:
        plan = CONTRACT.valid_plan_action_set(1)
        capture = CONTRACT.valid_captured_state(plan)
        adapter = FactsAdapter()
        with TemporaryDirectory() as directory:
            gate, store = self.build_gate(directory, plan, adapter)
            result = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                preparation_trust(plan, capture),
            )

            self.assertIsInstance(result, PREPARATION.PreparedBundleCommit)
            self.assertEqual(len(adapter.requests), 1)
            self.assertEqual(store.entry_count(), 1)
            resolved = store.resolve_receipt(result.receipt_bytes)
            self.assertIsNotNone(resolved)
            assert resolved is not None
            self.assertEqual(resolved.bundle_bytes, result.bundle_bytes)
            bundle = json.loads(result.bundle_bytes)
            self.assertEqual(
                bundle["schema_version"], "agent-equipment-preparation-bundle/v1"
            )
            self.assertEqual(bundle["bindings"]["store_generation"], 1)
            self.assertEqual(
                set(bundle["artifacts"]),
                {
                    "adapter_manifest_set",
                    "capability_binding_set",
                    "capture_observation_authority_set",
                    "captured_state",
                    "gate_manifest",
                    "plan_action_set",
                    "prepared_action_authority_set",
                },
            )
            for artifact in bundle["artifacts"].values():
                exact_bytes = base64.b64decode(artifact["bytes_base64"], validate=True)
                self.assertEqual(artifact["bytes_digest"], byte_digest(exact_bytes))
            captured_set = json.loads(
                base64.b64decode(
                    bundle["artifacts"]["capture_observation_authority_set"][
                        "bytes_base64"
                    ],
                    validate=True,
                )
            )
            prepared_set = json.loads(
                base64.b64decode(
                    bundle["artifacts"]["prepared_action_authority_set"][
                        "bytes_base64"
                    ],
                    validate=True,
                )
            )
            prepared = prepared_set["authorities"][0]
            observation = captured_set["observations"][0]
            self.assertEqual(
                prepared["captured_pre_state"], observation["normalized_pre_state"]
            )
            self.assertEqual(
                prepared["captured_pre_state_digest"],
                observation["normalized_pre_state_digest"],
            )
            for field in (
                "provider",
                "provider_digest",
                "operation",
                "operation_digest",
                "compensation",
                "compensation_digest",
                "desired_state",
                "desired_state_digest",
                "route_capture_binding",
            ):
                self.assertIn(field, prepared)

    def test_invalid_facts_stop_after_one_read_only_call_without_commit(self) -> None:
        plan = CONTRACT.valid_plan_action_set(1)
        capture = CONTRACT.valid_captured_state(plan)
        adapter = ForeignScopeAdapter()
        with TemporaryDirectory() as directory:
            gate, store = self.build_gate(directory, plan, adapter)
            result = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                preparation_trust(plan, capture),
            )

            self.assertIsInstance(result, PREPARATION.PreparationRejection)
            self.assertEqual(len(adapter.requests), 1)
            self.assertEqual(store.entry_count(), 0)

    def test_prepared_facts_cannot_add_foreign_controlled_components(self) -> None:
        for state_field in ("captured_pre_state", "expected_post_state"):
            with self.subTest(state_field=state_field), TemporaryDirectory() as directory:
                plan = CONTRACT.valid_plan_action_set(1)
                capture = CONTRACT.valid_captured_state(plan)
                if state_field == "expected_post_state":
                    expected_post_state = CONTRACT.normalized_state(present=True)
                    expected_post_state["component_states"] = [
                        {
                            "equipment_identity": "skill:fixture/foreign",
                            "state": "absent",
                        }
                    ]
                    capture["surfaces"][0]["recovery"][
                        "expected_pre_state_digest"
                    ] = digest(expected_post_state)
                adapter = ForeignComponentFactsAdapter(state_field)
                gate, store = self.build_gate(directory, plan, adapter)

                result = gate.prepare(
                    canonical_bytes(plan),
                    canonical_bytes(capture),
                    preparation_trust(plan, capture),
                )

                self.assertIsInstance(result, PREPARATION.PreparationRejection)
                self.assertEqual(len(adapter.requests), 1)
                self.assertEqual(store.entry_count(), 0)

    def test_byte_identical_bundle_is_reused_only_after_binding_revalidation(
        self,
    ) -> None:
        plan = CONTRACT.valid_plan_action_set(1)
        capture = CONTRACT.valid_captured_state(plan)
        adapter = FactsAdapter()
        with TemporaryDirectory() as directory:
            gate, _ = self.build_gate(directory, plan, adapter)
            first = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                preparation_trust(plan, capture),
            )
            self.assertIsInstance(first, PREPARATION.PreparedBundleCommit)
            adapter.requests.clear()
            second = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                preparation_trust(plan, capture),
                reuse_receipt_bytes=first.receipt_bytes,
            )

            self.assertIsInstance(second, PREPARATION.PreparedBundleCommit)
            self.assertTrue(second.reused)
            self.assertEqual(second.bundle_bytes, first.bundle_bytes)
            self.assertEqual(second.receipt_bytes, first.receipt_bytes)
            self.assertEqual(adapter.requests, [])

    def test_reuse_rejects_every_changed_trust_and_deployment_binding(self) -> None:
        for changed_binding in (
            "captured_state",
            "capability_set",
            "adapter_implementation",
            "gate_runtime",
            "store_identity",
        ):
            with self.subTest(changed_binding=changed_binding), TemporaryDirectory() as directory:
                plan = CONTRACT.valid_plan_action_set(1)
                capture = CONTRACT.valid_captured_state(plan)
                adapter = FactsAdapter()
                gate, store = self.build_gate(directory, plan, adapter)
                first = gate.prepare(
                    canonical_bytes(plan),
                    canonical_bytes(capture),
                    preparation_trust(plan, capture),
                )
                self.assertIsInstance(first, PREPARATION.PreparedBundleCommit)
                assert isinstance(first, PREPARATION.PreparedBundleCommit)
                adapter.requests.clear()

                trust_values = preparation_trust(plan, capture).as_dict()
                if changed_binding == "captured_state":
                    trust_values["expected_captured_state_digest"] = (
                        "sha256:" + "8" * 64
                    )
                if changed_binding == "capability_set":
                    trust_values["expected_capability_set_digest"] = (
                        "sha256:" + "9" * 64
                    )
                second_gate = gate
                if changed_binding == "adapter_implementation":
                    second_gate, _ = self.build_gate(
                        directory,
                        plan,
                        adapter,
                        adapter_implementation_manifest_digest=(
                            "sha256:" + "a" * 64
                        ),
                    )
                if changed_binding == "gate_runtime":
                    second_gate, _ = self.build_gate(
                        directory,
                        plan,
                        adapter,
                        gate_runtime_identity="cpython:3.14.1",
                    )
                if changed_binding == "store_identity":
                    second_gate, _ = self.build_gate(
                        directory,
                        plan,
                        adapter,
                        store_identity="preparation-store:fixture/other-v1",
                    )

                result = second_gate.prepare(
                    canonical_bytes(plan),
                    canonical_bytes(capture),
                    PREPARATION.PreparationTrust(**trust_values),
                    reuse_receipt_bytes=first.receipt_bytes,
                )

                self.assertIsInstance(result, PREPARATION.PreparationRejection)
                self.assertEqual(adapter.requests, [])
                self.assertEqual(store.entry_count(), 1)

    def test_native_remove_guard_must_equal_prepared_expected_post_state(self) -> None:
        plan = CONTRACT.valid_plan_action_set(1)
        capture = CONTRACT.valid_captured_state(plan)
        capture["surfaces"][0]["recovery"]["expected_pre_state_digest"] = (
            "sha256:" + "9" * 64
        )
        adapter = FactsAdapter()
        with TemporaryDirectory() as directory:
            gate, store = self.build_gate(directory, plan, adapter)
            result = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                preparation_trust(plan, capture),
            )

            self.assertIsInstance(result, PREPARATION.PreparationRejection)
            self.assertEqual(len(adapter.requests), 1)
            self.assertEqual(store.entry_count(), 0)

    def test_each_action_gets_one_manifest_bound_prepare_call(self) -> None:
        plan = CONTRACT.valid_plan_action_set(2)
        capture = CONTRACT.valid_captured_state(plan)
        adapter = FactsAdapter()
        with TemporaryDirectory() as directory:
            gate, store = self.build_gate(directory, plan, adapter)
            result = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                preparation_trust(plan, capture),
            )

            self.assertIsInstance(result, PREPARATION.PreparedBundleCommit)
            self.assertEqual(len(adapter.requests), 2)
            self.assertEqual(store.entry_count(), 1)
            requests = [json.loads(request) for request in adapter.requests]
            self.assertEqual(
                [request["echo_bindings"]["ordinal"] for request in requests],
                [0, 1],
            )
            self.assertEqual(
                len({request["request_identity"] for request in requests}), 2
            )

    def test_prepare_request_binds_exact_projection_and_action_semantics(self) -> None:
        plan = CONTRACT.valid_plan_action_set(1)
        capture = CONTRACT.valid_captured_state(plan)
        adapter = FactsAdapter()
        with TemporaryDirectory() as directory:
            gate, _ = self.build_gate(directory, plan, adapter)
            result = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                preparation_trust(plan, capture),
            )

            self.assertIsInstance(result, PREPARATION.PreparedBundleCommit)
            request = json.loads(adapter.requests[0])
            echo = request["echo_bindings"]
            self.assertEqual(
                set(echo)
                & {
                    "action_digest",
                    "route_identity",
                    "route_digest",
                    "provider_digest",
                    "operation_digest",
                    "compensation_digest",
                    "desired_state_digest",
                    "captured_projection_digest",
                },
                {
                    "action_digest",
                    "route_identity",
                    "route_digest",
                    "provider_digest",
                    "operation_digest",
                    "compensation_digest",
                    "desired_state_digest",
                    "captured_projection_digest",
                },
            )
            self.assertEqual(
                echo["captured_projection_digest"],
                digest(request["captured_projection"]),
            )

    def test_noncanonical_prepared_facts_make_no_store_commit(self) -> None:
        plan = CONTRACT.valid_plan_action_set(1)
        capture = CONTRACT.valid_captured_state(plan)
        adapter = NonCanonicalFactsAdapter()
        with TemporaryDirectory() as directory:
            gate, store = self.build_gate(directory, plan, adapter)
            result = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                preparation_trust(plan, capture),
            )

            self.assertIsInstance(result, PREPARATION.PreparationRejection)
            self.assertEqual(len(adapter.requests), 1)
            self.assertEqual(store.entry_count(), 0)

    def test_literal_secrets_in_prepared_facts_make_no_store_commit(self) -> None:
        for adapter_type in (
            LiteralSecretFactsAdapter,
            BearerLiteralSecretFactsAdapter,
        ):
            with self.subTest(adapter=adapter_type.__name__), TemporaryDirectory() as directory:
                plan = CONTRACT.valid_plan_action_set(1)
                capture = CONTRACT.valid_captured_state(plan)
                adapter = adapter_type()
                gate, store = self.build_gate(directory, plan, adapter)

                result = gate.prepare(
                    canonical_bytes(plan),
                    canonical_bytes(capture),
                    preparation_trust(plan, capture),
                )

                self.assertIsInstance(result, PREPARATION.PreparationRejection)
                self.assertEqual(len(adapter.requests), 1)
                self.assertEqual(store.entry_count(), 0)

    def test_producer_secret_policy_matches_the_controller_corpus(self) -> None:
        authorization_header = "".join(("Author", "ization"))  # noqa: FLY002
        proxy_authorization_header = "".join(  # noqa: FLY002
            ("Proxy-Author", "ization")
        )
        basic_fixture = "".join(  # noqa: FLY002
            (
                "dXNlcjpwYXNzd29yZC1maXh0",
                "dXJlLTEyMzQ1Njc4OTA=",
            )
        )
        access_token_key = "".join(("access_", "token"))  # noqa: FLY002
        client_secret_key = "".join(("client_", "secret"))  # noqa: FLY002
        session_token_key = "".join(("session", "Token"))  # noqa: FLY002
        literal_documents = (
            {"value": "Bearer " + "A" * 48},
            {
                "value": authorization_header + ": Basic " + basic_fixture
            },
            {
                "value": proxy_authorization_header + ": Digest " + "a" * 40
            },
            {
                "value": "https://example.invalid/?"
                + access_token_key
                + "="
                + "A" * 32
            },
            {client_secret_key: "literal-material-1234567890"},
            {session_token_key: "literal-material-1234567890"},
        )
        reference_documents = (
            {"client_secret_reference": "secret-reference:fixture/client"},
            {
                "authorization_identity": (
                    "apply-authorization:sha256:" + "a" * 64
                )
            },
            {"apply_authorization_digest": "sha256:" + "b" * 64},
        )

        for document in literal_documents:
            with self.subTest(literal=document):
                self.assertTrue(contains_literal_credential(document))
                self.assertTrue(
                    PREPARATION.preparation._contains_literal_secret(document)
                )
        for document in reference_documents:
            with self.subTest(reference=document):
                self.assertFalse(contains_literal_credential(document))
                self.assertFalse(
                    PREPARATION.preparation._contains_literal_secret(document)
                )

    def test_configure_preparation_accepts_only_observed_desired_configuration(
        self,
    ) -> None:
        cases = {
            "matching observed configuration": ("observed", None, True),
            "wrong observed digest": ("observed", "sha256:" + "f" * 64, False),
            "unknown configuration": ("unknown", None, False),
        }
        for name, (status, configured_digest, accepted) in cases.items():
            with self.subTest(name=name), TemporaryDirectory() as directory:
                plan = CONTRACT.valid_provider_family_plan_action_set("direct_mcp")
                capture = CONTRACT.valid_captured_state(plan)
                action = plan["actions"][0]["action_payload"]
                action["desired_state"] = {
                    "configuration": {
                        "status": "desired",
                        "digest": digest(
                            {
                                "provider": action["provider"],
                                "component_controls": [],
                            }
                        ),
                    }
                }
                reseal_plan_and_capture(plan, capture)
                adapter = ConfigureFactsAdapter(
                    configuration_status=status,
                    configuration_digest=configured_digest,
                )
                gate, store = self.build_gate(directory, plan, adapter)

                result = gate.prepare(
                    canonical_bytes(plan),
                    canonical_bytes(capture),
                    preparation_trust(plan, capture),
                )

                if accepted:
                    self.assertIsInstance(result, PREPARATION.PreparedBundleCommit)
                    self.assertEqual(store.entry_count(), 1)
                else:
                    self.assertIsInstance(result, PREPARATION.PreparationRejection)
                    self.assertEqual(store.entry_count(), 0)
                self.assertEqual(len(adapter.requests), 1)

    def test_receipt_is_authenticated_to_its_producer_owned_store(self) -> None:
        plan = CONTRACT.valid_plan_action_set(1)
        capture = CONTRACT.valid_captured_state(plan)
        adapter = FactsAdapter()
        with TemporaryDirectory() as directory, TemporaryDirectory() as foreign:
            gate, _ = self.build_gate(directory, plan, adapter)
            result = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                preparation_trust(plan, capture),
            )
            self.assertIsInstance(result, PREPARATION.PreparedBundleCommit)
            foreign_store = PREPARATION.FilePreparationStore(
                Path(foreign),
                store_identity="preparation-store:fixture/foreign-v1",
            )

            self.assertIsNone(foreign_store.resolve_receipt(result.receipt_bytes))

    def test_store_requires_an_already_provisioned_protected_root(self) -> None:
        with TemporaryDirectory() as parent:
            root = Path(parent) / "not-provisioned"

            with self.assertRaises(ValueError):
                PREPARATION.FilePreparationStore(
                    root,
                    store_identity="preparation-store:fixture/protected-v1",
                )

            self.assertFalse(root.exists())

    def test_store_rejects_a_symlink_root(self) -> None:
        with TemporaryDirectory() as parent, TemporaryDirectory() as target:
            root = Path(parent) / "store-link"
            root.symlink_to(target, target_is_directory=True)

            with self.assertRaises(ValueError):
                PREPARATION.FilePreparationStore(
                    root,
                    store_identity="preparation-store:fixture/protected-v1",
                )

    def test_gate_rejects_schema_bytes_not_bound_by_its_manifest(self) -> None:
        plan = CONTRACT.valid_plan_action_set(1)
        action = plan["actions"][0]["action_payload"]
        schemas = schema_documents()
        manifest = gate_manifest(schemas)
        adapter_document = adapter_manifest(action)
        manifest_set = adapter_manifest_set([adapter_document])
        substituted_schemas = dict(schemas)
        substituted_schemas["execution-authority-v1.schema.json"] += b"\n"

        with TemporaryDirectory() as directory, self.assertRaises(ValueError):
            PREPARATION.PreparationGate(
                gate_manifest_bytes=canonical_bytes(manifest),
                expected_gate_manifest_digest=str(manifest["manifest_digest"]),
                schema_documents=substituted_schemas,
                adapters=(
                    PREPARATION.BoundPreparationAdapter(
                        manifest_bytes=canonical_bytes(adapter_document),
                        adapter=FactsAdapter(),
                    ),
                ),
                expected_adapter_manifest_set_digest=str(
                    manifest_set["adapter_manifest_set_digest"]
                ),
                store=PREPARATION.FilePreparationStore(
                    Path(directory),
                    store_identity="preparation-store:fixture/protected-v1",
                ),
            )

    def test_store_concurrently_reuses_only_the_same_complete_envelope(self) -> None:
        plan = CONTRACT.valid_plan_action_set(1)
        capture = CONTRACT.valid_captured_state(plan)
        adapter = FactsAdapter()
        with TemporaryDirectory() as source, TemporaryDirectory() as target:
            gate, _ = self.build_gate(source, plan, adapter)
            result = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                preparation_trust(plan, capture),
            )
            self.assertIsInstance(result, PREPARATION.PreparedBundleCommit)
            bundle = json.loads(result.bundle_bytes)
            bindings = bundle["bindings"]
            store = PREPARATION.FilePreparationStore(
                Path(target),
                store_identity="preparation-store:fixture/protected-v1",
            )

            def commit() -> PREPARATION.PreparedBundleCommit:
                return store.commit(
                    result.bundle_bytes,
                    preparation_gate_identity=bindings["preparation_gate_identity"],
                    preparation_gate_manifest_digest=bindings[
                        "preparation_gate_manifest_digest"
                    ],
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                commits = list(executor.map(lambda _: commit(), range(2)))

            self.assertEqual(store.entry_count(), 1)
            self.assertEqual(sum(not item.reused for item in commits), 1)
            self.assertEqual(commits[0].receipt_bytes, commits[1].receipt_bytes)

    def test_durability_uncertainty_returns_no_receipt_and_retry_revalidates(
        self,
    ) -> None:
        plan = CONTRACT.valid_plan_action_set(1)
        capture = CONTRACT.valid_captured_state(plan)
        adapter = FactsAdapter()
        with TemporaryDirectory() as directory:
            gate, store = self.build_gate(directory, plan, adapter)
            real_fsync = PREPARATION.preparation.os.fsync
            calls = 0

            def fail_directory_fsync(descriptor: int) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated durability uncertainty")
                real_fsync(descriptor)

            with mock.patch.object(
                PREPARATION.preparation.os,
                "fsync",
                side_effect=fail_directory_fsync,
            ):
                first = gate.prepare(
                    canonical_bytes(plan),
                    canonical_bytes(capture),
                    preparation_trust(plan, capture),
                )

            self.assertIsInstance(first, PREPARATION.PreparationRejection)
            self.assertFalse(hasattr(first, "receipt_bytes"))
            self.assertEqual(store.entry_count(), 1)
            second = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                preparation_trust(plan, capture),
            )
            self.assertIsInstance(second, PREPARATION.PreparedBundleCommit)
            self.assertTrue(second.reused)
            self.assertEqual(len(adapter.requests), 2)

    def test_partial_or_corrupted_store_entry_cannot_resolve(self) -> None:
        plan = CONTRACT.valid_plan_action_set(1)
        capture = CONTRACT.valid_captured_state(plan)
        adapter = FactsAdapter()
        with TemporaryDirectory() as directory:
            gate, store = self.build_gate(directory, plan, adapter)
            result = gate.prepare(
                canonical_bytes(plan),
                canonical_bytes(capture),
                preparation_trust(plan, capture),
            )
            self.assertIsInstance(result, PREPARATION.PreparedBundleCommit)
            entries = list(Path(directory).glob("*.json"))
            self.assertEqual(len(entries), 1)
            exact_entry = entries[0].read_bytes()
            entries[0].write_bytes(exact_entry[: len(exact_entry) // 2])

            self.assertIsNone(store.resolve_receipt(result.receipt_bytes))

    def test_manifest_builders_produce_gate_constructor_inputs(self) -> None:
        schemas = schema_documents()
        plan = CONTRACT.valid_plan_action_set(1)
        action = plan["actions"][0]["action_payload"]
        gate_bytes = PREPARATION.build_gate_manifest(
            gate_identity="preparation-gate:agent-equipment/v1",
            runtime_identity="cpython:3.14.0",
            runtime_executable_digest="sha256:" + "1" * 64,
            files={
                "agent_equipment_preparation/__init__.py": b"init",
                "agent_equipment_preparation/preparation.py": b"implementation",
            },
            schema_documents=schemas,
        )
        adapter_bytes = PREPARATION.build_adapter_manifest(
            adapter_identity=str(action["adapter_identity"]),
            adapter_version=str(action["adapter_version"]),
            implementation_identity="adapter-implementation:fixture/claude-plugin-v1",
            implementation_manifest_digest="sha256:" + "4" * 64,
            capability_binding={
                "capability_identity": action["capability_identity"],
                "capability_digest": action["capability_digest"],
                "manager_version_evidence_digest": action[
                    "manager_version_evidence_digest"
                ],
            },
        )
        manifest_set_bytes = PREPARATION.build_adapter_manifest_set([adapter_bytes])

        self.assertEqual(
            json.loads(gate_bytes)["manifest_digest"],
            digest(
                {
                    key: value
                    for key, value in json.loads(gate_bytes).items()
                    if key != "manifest_digest"
                }
            ),
        )
        self.assertEqual(
            json.loads(manifest_set_bytes)["manifests"],
            [json.loads(adapter_bytes)],
        )


if __name__ == "__main__":
    unittest.main()
