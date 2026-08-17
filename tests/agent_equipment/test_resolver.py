from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from agent_equipment.canonical import canonical_json_sha256
from agent_equipment.inventory import (
    admit_capability_discovery,
    admit_runtime_inventory,
    admit_runtime_observation,
)
from agent_equipment.model import (
    AdapterError,
    CapabilityDiscovery,
    CapabilityRecord,
    FrozenJsonObject,
    RuntimeInventory,
    RuntimeObservation,
    _runtime_inventory_digest,
    freeze_json,
    thaw_json,
)
from agent_equipment.resolver import (
    _action_operations,
    _active_route_groups,
    _component_control_diagnostics,
    _matching_capability,
    _observation_binding_diagnostics,
    _operation_matrix,
    _retirement_route_groups,
    resolve,
)
from agent_equipment.validator import load_catalog_lock

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "home/dot_config/agent-equipment/catalog-v1.json"
LOCK_PATH = ROOT / "home/dot_config/agent-equipment/lock-v1.json"
OPERATIONS = (
    "inspect",
    "install",
    "configure",
    "enable",
    "disable",
    "remove",
    "restore",
    "suppress_native_update",
)
OBSERVED_MATT_REVISION = "84fdeffd12f2ee307994d1eb6feb48173b6e0502"
OBSERVED_MATT_CONTENT_DIGEST = (
    "sha256:1b3a5b293a2d0e04748c64f6c86af0ed104a7619de68f7e2cdadc6b42b9a0d41"
)


def mutation_support(mode: str) -> dict[str, object]:
    if mode == "automated":
        return {
            "mode": "automated",
            "compare_before_mutate": True,
            "idempotency": "state_convergent",
            "compensation": "restore_captured_pre_state",
        }
    if mode == "operator_action":
        return {
            "mode": "operator_action",
            "operator_action_reference": "docs/agent-equipment/ARCHITECTURE.md",
        }
    if mode == "inspect_only":
        return {
            "mode": "inspect_only",
            "normalized_fields": ["component_states"],
        }
    return {"mode": "unavailable"}


def capability(
    harness: str,
    kind: str,
    selector: dict[str, object],
    *,
    unavailable_operation: str | None = None,
    supported_controls: tuple[str, ...] = (),
    supported_states: tuple[str, ...] | None = None,
    component_mode: str | None = None,
    native_update_control: str | None = None,
    operation_modes: dict[str, str] | None = None,
) -> CapabilityRecord:
    provider_match = {"kind": kind, **selector}
    identity = f"capability:{harness}/{kind}"
    manager_evidence: dict[str, object] = {
        "manager": (
            "standalone_skills"
            if kind == "standalone_skill"
            else "direct_mcp"
            if kind == "direct_mcp"
            else harness
        ),
        "manager_version": "test-read-only-v1",
        "observation_source": "resolver production-admission fixture",
    }
    manager_digest = canonical_json_sha256(manager_evidence)
    manager_evidence["evidence_digest"] = manager_digest
    operation_support: dict[str, object] = {}
    for operation in OPERATIONS:
        if operation == "inspect":
            operation_support[operation] = (
                {"mode": "unavailable"}
                if unavailable_operation == operation
                else {
                    "mode": "automated",
                    "normalized_fields": [
                        "component_states",
                        "configuration",
                        "enablement",
                        "immutable_content",
                        "manager_drift",
                        "native_update_control",
                        "native_update_suppression_state",
                        "observed_version",
                        "route_presence",
                    ],
                }
            )
            continue
        mode = (
            operation_modes[operation]
            if operation_modes is not None and operation in operation_modes
            else "unavailable"
            if operation == unavailable_operation
            else "operator_action"
            if kind == "native_plugin"
            and operation in {"remove", "suppress_native_update"}
            else "unavailable"
            if operation == "suppress_native_update"
            else "automated"
        )
        operation_support[operation] = mutation_support(mode)
    selected_component_mode = component_mode or (
        "automated" if supported_controls else "unavailable"
    )
    selected_supported_states = (
        supported_states
        if supported_states is not None
        else ("enabled", "disabled")
        if supported_controls
        else ()
    )
    component_support = {
        "mode": selected_component_mode,
        "selector_granularity": "equipment_identity",
        "supported_equipment_identities": list(supported_controls),
        "supported_states": list(selected_supported_states),
        "mutation_boundary": (
            "selected_component" if selected_component_mode == "automated" else "none"
        ),
    }
    selected_native_update_control = native_update_control or (
        "unknown" if kind == "native_plugin" else "not_applicable"
    )
    suppression = operation_support["suppress_native_update"]
    capability_document: dict[str, object] = {
        "contract_version": "adapter-contract-v1",
        "capability_identity": identity,
        "adapter_identity": f"adapter:{harness}/{kind}",
        "adapter_version": "1.0.0",
        "harness": harness,
        "provider_match": provider_match,
        "manager_version_evidence": manager_evidence,
        "surface_identity_rule": {
            "rule": "route_and_equipment_identity",
            "version": 1,
        },
        "operation_support": operation_support,
        "component_control_support": component_support,
        "native_update_support": {
            "native_update_control": selected_native_update_control,
            "version_observation": "automated",
            "baseline_comparison": "automated",
            "suppression": suppression,
            "suppression_scope": (
                "manager"
                if isinstance(suppression, dict)
                and suppression.get("mode") != "unavailable"
                else "none"
            ),
        },
        "record_versions": {
            "observe_request": "adapter-contract-v1",
            "runtime_observation": "adapter-contract-v1",
            "planned_action": "adapter-contract-v1",
            "mutation_receipt": "adapter-contract-v1",
            "captured_state": "agent-equipment-captured-state/v1",
        },
        "automated_control_owners": ["reconciler_owned"],
    }
    capability_digest = canonical_json_sha256(capability_document)
    capability_document["capability_digest"] = capability_digest
    document = freeze_json(capability_document)
    assert isinstance(document, FrozenJsonObject)
    return CapabilityRecord(
        document=document,
        capability_identity=identity,
        adapter_identity=f"adapter:{harness}/{kind}",
        adapter_version="1.0.0",
        harness=harness,
        capability_digest=capability_digest,
        manager_version_evidence_digest=manager_digest,
    )


def complete_capabilities() -> tuple[CapabilityRecord, ...]:
    return (
        capability(
            "claude",
            "direct_mcp",
            {"transport": "stdio", "overlay_family": "claude_json"},
            native_update_control="suppressible",
        ),
        capability(
            "claude",
            "native_plugin",
            {"manager": "claude", "scope": "user"},
            native_update_control="suppressible",
        ),
        capability("claude", "standalone_skill", {"canonical_root": "agents_skills"}),
        capability(
            "codex",
            "direct_mcp",
            {"transport": "stdio", "overlay_family": "codex_toml"},
            native_update_control="suppressible",
        ),
        capability(
            "codex",
            "native_plugin",
            {"manager": "codex", "scope": "user"},
            supported_controls=(
                "mcp:github/server",
                "other:github/codex-app",
                "skill:github/gh-address-comments",
                "skill:github/gh-fix-ci",
                "skill:github/github",
                "skill:github/yeet",
            ),
            native_update_control="unknown",
        ),
        capability("codex", "standalone_skill", {"canonical_root": "agents_skills"}),
        capability(
            "cursor",
            "direct_mcp",
            {"transport": "stdio", "overlay_family": "cursor_json"},
            native_update_control="suppressible",
        ),
        capability("cursor", "standalone_skill", {"canonical_root": "agents_skills"}),
    )


def runtime_inventory(
    validated,
    *,
    capabilities: tuple[CapabilityRecord, ...] | None = None,
    omit_route: str | None = None,
    manager_drift_route: str | None = None,
) -> tuple[RuntimeInventory, CapabilityDiscovery]:
    records = complete_capabilities() if capabilities is None else capabilities
    discovery = CapabilityDiscovery(records)
    observations: list[RuntimeObservation] = []
    groups = (*_active_route_groups(validated), *_retirement_route_groups(validated))
    active_count = len(_active_route_groups(validated))
    for index, group in enumerate(groups):
        if group.route_identity == omit_route:
            continue
        selected = _matching_capability(group, records)
        assert selected is not None
        retiring = index >= active_count
        restore = group.route.get("restore")
        assert isinstance(restore, FrozenJsonObject)
        restore_class = restore.get("class")
        reviewed_baseline = restore.get("reviewed_baseline")
        observation_source = restore.get("observation_source")
        native_rolling = restore_class == "native_rolling"
        present = retiring or group.route_identity == manager_drift_route
        component_states = [
            {"equipment_identity": identity, "state": "disabled"}
            for identity in group.controlled_equipment_identities
        ]
        normalized_state = {
            "route_presence": "present" if present else "absent",
            "enablement": "enabled" if retiring else "disabled",
            "configuration": {"status": "unknown"},
            "component_states": component_states,
            "observed_version": (
                {
                    "status": "observed",
                    "value": (
                        f"{reviewed_baseline}+changed"
                        if group.route_identity == manager_drift_route
                        else reviewed_baseline
                    ),
                }
                if native_rolling and present
                else {"status": "route_absent"}
                if native_rolling
                else {"status": "not_applicable"}
            ),
            "immutable_content": (
                {"status": "not_applicable"}
                if native_rolling
                else {
                    "status": "observed",
                    "revision": OBSERVED_MATT_REVISION,
                    "content_digest": OBSERVED_MATT_CONTENT_DIGEST,
                }
                if present
                else {"status": "route_absent"}
            ),
            "native_update_control": restore.get("native_update_control"),
            "native_update_suppression_state": (
                "not_applicable"
                if group.route.get("restore").get("native_update_control")
                == "not_applicable"
                else "unavailable"
                if group.route.get("restore").get("native_update_control")
                == "unsuppressible"
                else "unknown"
            ),
            "manager_drift": (
                {
                    "status": "changed_from_reviewed_baseline",
                    "reviewed_baseline": reviewed_baseline,
                    "observation_source": observation_source,
                }
                if group.route_identity == manager_drift_route
                else {
                    "status": "none",
                    "reviewed_baseline": reviewed_baseline,
                    "observation_source": observation_source,
                }
                if native_rolling
                else {
                    "status": "not_applicable",
                    "reviewed_baseline": None,
                    "observation_source": None,
                }
            ),
        }
        state_digest = canonical_json_sha256(normalized_state)
        surface_scope = [
            f"surface:{group.route_identity}/{identity}"
            for identity in sorted(
                set(group.equipment_identities)
                | set(group.controlled_equipment_identities)
            )
        ]
        document = freeze_json(
            {
                "contract_version": "adapter-contract-v1",
                "request_identity": f"request:resolver-{index:03d}",
                "correlation_identity": "correlation:resolver-read-only",
                "candidate_identity": "candidate:sha256:" + "1" * 64,
                "implementation_manifest_digest": "sha256:" + "2" * 64,
                "catalog_digest": validated.catalog.digest,
                "lock_digest": validated.lock.digest,
                "plan_digest": None,
                "capability_identity": selected.capability_identity,
                "capability_digest": selected.capability_digest,
                "manager_version_evidence_digest": (
                    selected.manager_version_evidence_digest
                ),
                "harness": group.harness,
                "route_identity": group.route_identity,
                "route_digest": canonical_json_sha256(group.route),
                "control_owner": group.route.get("control_owner"),
                "equipment_identities": list(group.equipment_identities),
                "controlled_equipment_identities": list(
                    group.controlled_equipment_identities
                ),
                "activation_group": group.activation_group,
                "surface_scope": surface_scope,
                "observed_at": "2026-08-12T15:00:00Z",
                "result": {
                    "status": "ok",
                    "normalized_state": normalized_state,
                    "surface_evidence": [
                        {
                            "kind": "manager",
                            "identity": identity,
                            "digest": "sha256:" + "7" * 64,
                        }
                        for identity in surface_scope
                    ],
                    "captured_state": {"status": "not_applicable"},
                    "state_digest": state_digest,
                },
            }
        )
        assert isinstance(document, FrozenJsonObject)
        observations.append(
            RuntimeObservation(
                document=document,
                request_identity=f"request:resolver-{index:03d}",
                capability_identity=selected.capability_identity,
                route_identity=group.route_identity,
                state_digest=state_digest,
            )
        )
    observation_tuple = tuple(
        sorted(
            observations,
            key=lambda observation: (
                observation.harness,
                observation.route_identity,
                observation.request_identity,
            ),
        )
    )
    inventory_digest = _runtime_inventory_digest(
        discovery,
        observation_tuple,
        "candidate:sha256:" + "1" * 64,
        "sha256:" + "2" * 64,
        validated.catalog.digest,
        validated.lock.digest,
    )
    return (
        RuntimeInventory(
            capabilities=discovery,
            observations=observation_tuple,
            candidate_identity="candidate:sha256:" + "1" * 64,
            implementation_manifest_digest="sha256:" + "2" * 64,
            catalog_digest=validated.catalog.digest,
            lock_digest=validated.lock.digest,
            digest=inventory_digest,
        ),
        discovery,
    )


def with_normalized_state(
    inventory: RuntimeInventory,
    route_identity: str,
    normalized_state: dict[str, object],
) -> RuntimeInventory:
    """Replace one observation state and reseal its inventory binding."""

    observations: list[RuntimeObservation] = []
    for observation in inventory.observations:
        if observation.route_identity != route_identity:
            observations.append(observation)
            continue
        document = thaw_json(observation.document)
        assert isinstance(document, dict)
        result = document.get("result")
        assert isinstance(result, dict)
        state_digest = canonical_json_sha256(normalized_state)
        result["normalized_state"] = normalized_state
        result["state_digest"] = state_digest
        frozen_document = freeze_json(document)
        assert isinstance(frozen_document, FrozenJsonObject)
        observations.append(
            replace(
                observation,
                document=frozen_document,
                state_digest=state_digest,
            )
        )
    observation_tuple = tuple(
        sorted(
            observations,
            key=lambda observation: (
                observation.harness,
                observation.route_identity,
                observation.request_identity,
            ),
        )
    )
    digest = _runtime_inventory_digest(
        inventory.capabilities,
        observation_tuple,
        inventory.candidate_identity,
        inventory.implementation_manifest_digest,
        inventory.catalog_digest,
        inventory.lock_digest,
    )
    return replace(inventory, observations=observation_tuple, digest=digest)


class ResolverMatrixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        validation = load_catalog_lock(CATALOG_PATH, LOCK_PATH)
        assert validation.model is not None
        cls.validated = validation.model

    def test_active_groups_preserve_complete_coverage_and_apply_controls_first(
        self,
    ) -> None:
        groups = _active_route_groups(self.validated)

        self.assertEqual(len(self.validated.coverage), 132)
        self.assertEqual(len(groups), 16)
        self.assertEqual(
            tuple((group.harness, group.route_identity) for group in groups),
            tuple(sorted((group.harness, group.route_identity) for group in groups)),
        )
        github = next(
            group
            for group in groups
            if group.route_identity == "route:codex/github-plugin"
        )
        self.assertNotIn("skill:github/yeet", github.equipment_identities)
        self.assertIn("skill:github/yeet", github.controlled_equipment_identities)
        self.assertEqual(len(github.controlled_equipment_identities), 6)
        self.assertEqual(
            github.activation_group, "activation:codex/github-plugin-with-yeet-disabled"
        )

    def test_resolver_fixtures_pass_exact_production_adapter_admission(self) -> None:
        inventory, capabilities = runtime_inventory(self.validated)

        readmitted_capabilities = admit_capability_discovery(
            thaw_json(capabilities.as_json())
        )
        readmitted_observations = tuple(
            admit_runtime_observation(
                {
                    "record_type": "RuntimeObservation",
                    "record": thaw_json(observation.document),
                }
            )
            for observation in inventory.observations
        )
        readmitted_inventory = admit_runtime_inventory(
            [thaw_json(inventory.capabilities.as_json())],
            [
                {
                    "record_type": "RuntimeObservation",
                    "record": thaw_json(observation.document),
                }
                for observation in inventory.observations
            ],
        )

        self.assertNotIsInstance(readmitted_capabilities, AdapterError)
        self.assertEqual(readmitted_capabilities, capabilities)
        self.assertNotIn(
            True,
            tuple(isinstance(item, AdapterError) for item in readmitted_observations),
        )
        self.assertEqual(readmitted_observations, inventory.observations)
        self.assertNotIsInstance(readmitted_inventory, AdapterError)
        self.assertEqual(readmitted_inventory, inventory)

    def test_resolver_rejects_schema_invalid_typed_capabilities_before_matrix(
        self,
    ) -> None:
        inventory, capabilities = runtime_inventory(self.validated)
        original = capabilities.records[0]
        forged_payload = thaw_json(original.document)
        assert isinstance(forged_payload, dict)
        forged_payload["contract_version"] = "adapter-contract-forged"
        forged_payload.pop("capability_digest")
        forged_digest = canonical_json_sha256(forged_payload)
        forged_payload["capability_digest"] = forged_digest
        forged_document = freeze_json(forged_payload)
        assert isinstance(forged_document, FrozenJsonObject)
        forged_record = replace(
            original,
            document=forged_document,
            capability_digest=forged_digest,
        )
        forged_capabilities = CapabilityDiscovery(
            (forged_record, *capabilities.records[1:])
        )

        resolution = resolve(
            "audit",
            self.validated.catalog,
            self.validated.lock,
            inventory,
            forged_capabilities,
        )

        self.assertEqual(
            tuple(diagnostic.code for diagnostic in resolution.diagnostics),
            ("CAPABILITY_DISCOVERY_INVALID",),
        )
        self.assertEqual(resolution.operation_matrix, ())
        self.assertIsNone(resolution.candidate_plan)
        self.assertIsNone(resolution.mutation_plan)

    def test_resolver_rejects_schema_invalid_typed_inventory_before_matrix(
        self,
    ) -> None:
        inventory, capabilities = runtime_inventory(self.validated)
        original = inventory.observations[0]
        forged_payload = thaw_json(original.document)
        assert isinstance(forged_payload, dict)
        forged_payload["contract_version"] = "adapter-contract-forged"
        forged_document = freeze_json(forged_payload)
        assert isinstance(forged_document, FrozenJsonObject)
        forged_observation = replace(original, document=forged_document)
        forged_observations = (forged_observation, *inventory.observations[1:])
        forged_inventory = replace(
            inventory,
            observations=forged_observations,
            digest=_runtime_inventory_digest(
                inventory.capabilities,
                forged_observations,
                inventory.candidate_identity,
                inventory.implementation_manifest_digest,
                inventory.catalog_digest,
                inventory.lock_digest,
            ),
        )

        resolution = resolve(
            "audit",
            self.validated.catalog,
            self.validated.lock,
            forged_inventory,
            capabilities,
        )

        self.assertEqual(
            tuple(diagnostic.code for diagnostic in resolution.diagnostics),
            ("RUNTIME_OBSERVATION_INVALID",),
        )
        self.assertEqual(resolution.operation_matrix, ())
        self.assertIsNone(resolution.candidate_plan)
        self.assertIsNone(resolution.mutation_plan)

    def test_only_reviewed_retirement_records_become_losing_route_groups(self) -> None:
        groups = _retirement_route_groups(self.validated)

        self.assertEqual(len(groups), 23)
        self.assertEqual(
            tuple(group.retirement_identity for group in groups),
            tuple(sorted(group.retirement_identity for group in groups)),
        )
        self.assertEqual(
            {group.desired_state for group in groups},
            {"absent"},
        )
        self.assertEqual(
            sum(
                group.route.get("provider").get("kind") == "standalone_skill"
                for group in groups
            ),
            21,
        )

    def test_every_active_and_retiring_route_selects_one_exact_capability(self) -> None:
        capabilities = complete_capabilities()
        groups = (
            *_active_route_groups(self.validated),
            *_retirement_route_groups(self.validated),
        )

        selected = tuple(_matching_capability(group, capabilities) for group in groups)

        self.assertEqual(len(selected), 39)
        self.assertNotIn(None, selected)

    def test_capabilities_cannot_broaden_catalog_operation_dispositions(self) -> None:
        group = next(
            group
            for group in _active_route_groups(self.validated)
            if group.route_identity == "route:claude/chrome-devtools-plugin"
        )
        selected = _matching_capability(group, complete_capabilities())
        assert selected is not None

        matrix, diagnostics = _operation_matrix(group, selected)

        self.assertEqual(diagnostics, ())
        operations = matrix.get("operations")
        assert isinstance(operations, FrozenJsonObject)
        configure = operations.get("configure")
        assert isinstance(configure, FrozenJsonObject)
        self.assertEqual(configure.get("catalog_disposition"), "unavailable")
        self.assertEqual(configure.get("capability_mode"), "automated")
        self.assertEqual(configure.get("effective_disposition"), "unavailable")

    def test_native_update_capability_must_match_the_reviewed_route_class(self) -> None:
        mismatched = capability(
            "claude",
            "direct_mcp",
            {"transport": "stdio", "overlay_family": "claude_json"},
            native_update_control="not_applicable",
        )
        records = tuple(
            mismatched
            if record.capability_identity == mismatched.capability_identity
            else record
            for record in complete_capabilities()
        )
        inventory, capabilities = runtime_inventory(
            self.validated,
            capabilities=records,
        )

        resolution = resolve(
            "apply",
            self.validated.catalog,
            self.validated.lock,
            inventory,
            capabilities,
        )

        self.assertIn(
            (
                "NATIVE_UPDATE_CAPABILITY_MISMATCH",
                "route:claude/direct-context7",
            ),
            tuple(
                (diagnostic.code, diagnostic.route_identity)
                for diagnostic in resolution.diagnostics
            ),
        )
        self.assertIsNone(resolution.candidate_plan)
        self.assertIsNone(resolution.mutation_plan)

    def test_native_update_suppression_requires_one_exact_capability_authority(
        self,
    ) -> None:
        original = next(
            record
            for record in complete_capabilities()
            if record.capability_identity == "capability:claude/native_plugin"
        )
        payload = thaw_json(original.document)
        assert isinstance(payload, dict)
        native_support = payload.get("native_update_support")
        assert isinstance(native_support, dict)
        native_support["suppression"] = {
            "mode": "operator_action",
            "operator_action_reference": "docs/agent-equipment/ACCEPTANCE.md",
        }
        payload.pop("capability_digest")
        digest = canonical_json_sha256(payload)
        payload["capability_digest"] = digest
        document = freeze_json(payload)
        assert isinstance(document, FrozenJsonObject)
        mismatched = replace(
            original,
            document=document,
            capability_digest=digest,
        )
        records = tuple(
            mismatched
            if record.capability_identity == mismatched.capability_identity
            else record
            for record in complete_capabilities()
        )
        inventory, capabilities = runtime_inventory(
            self.validated,
            capabilities=records,
        )

        resolution = resolve(
            "apply",
            self.validated.catalog,
            self.validated.lock,
            inventory,
            capabilities,
        )

        self.assertIn(
            (
                "NATIVE_UPDATE_SUPPRESSION_AUTHORITY_MISMATCH",
                "route:claude/chrome-devtools-plugin",
            ),
            tuple(
                (diagnostic.code, diagnostic.route_identity)
                for diagnostic in resolution.diagnostics
            ),
        )
        self.assertIsNone(resolution.candidate_plan)
        self.assertIsNone(resolution.mutation_plan)

    def test_native_rolling_version_evidence_requires_capability_authority(
        self,
    ) -> None:
        original = next(
            record
            for record in complete_capabilities()
            if record.capability_identity == "capability:codex/native_plugin"
        )

        for field in ("version_observation", "baseline_comparison"):
            with self.subTest(field=field):
                payload = thaw_json(original.document)
                assert isinstance(payload, dict)
                native_support = payload.get("native_update_support")
                assert isinstance(native_support, dict)
                native_support[field] = "unavailable"
                payload.pop("capability_digest")
                capability_digest = canonical_json_sha256(payload)
                payload["capability_digest"] = capability_digest
                document = freeze_json(payload)
                assert isinstance(document, FrozenJsonObject)
                unavailable = replace(
                    original,
                    document=document,
                    capability_digest=capability_digest,
                )
                records = tuple(
                    unavailable
                    if record.capability_identity == unavailable.capability_identity
                    else record
                    for record in complete_capabilities()
                )
                inventory, capabilities = runtime_inventory(
                    self.validated,
                    capabilities=records,
                )

                resolution = resolve(
                    "apply",
                    self.validated.catalog,
                    self.validated.lock,
                    inventory,
                    capabilities,
                )

                self.assertIn(
                    (
                        "NATIVE_ROLLING_EVIDENCE_CAPABILITY_MISSING",
                        "route:codex/github-plugin",
                    ),
                    tuple(
                        (diagnostic.code, diagnostic.route_identity)
                        for diagnostic in resolution.diagnostics
                    ),
                )
                self.assertIsNone(resolution.candidate_plan)
                self.assertIsNone(resolution.mutation_plan)

    def test_native_rolling_inspect_only_version_authority_is_sufficient(self) -> None:
        original = next(
            record
            for record in complete_capabilities()
            if record.capability_identity == "capability:codex/native_plugin"
        )
        payload = thaw_json(original.document)
        assert isinstance(payload, dict)
        native_support = payload.get("native_update_support")
        assert isinstance(native_support, dict)
        native_support["version_observation"] = "inspect_only"
        native_support["baseline_comparison"] = "inspect_only"
        payload.pop("capability_digest")
        capability_digest = canonical_json_sha256(payload)
        payload["capability_digest"] = capability_digest
        document = freeze_json(payload)
        assert isinstance(document, FrozenJsonObject)
        inspect_only = replace(
            original,
            document=document,
            capability_digest=capability_digest,
        )
        records = tuple(
            inspect_only
            if record.capability_identity == inspect_only.capability_identity
            else record
            for record in complete_capabilities()
        )
        inventory, capabilities = runtime_inventory(
            self.validated,
            capabilities=records,
        )

        resolution = resolve(
            "audit",
            self.validated.catalog,
            self.validated.lock,
            inventory,
            capabilities,
        )

        self.assertEqual(resolution.diagnostics, ())
        self.assertIsNotNone(resolution.candidate_plan)

    def test_native_update_capabilities_accept_each_reviewed_class(self) -> None:
        groups = {
            group.route_identity: group
            for group in _active_route_groups(self.validated)
        }
        suppressible = groups["route:claude/direct-context7"]
        route_payload = thaw_json(suppressible.route)
        assert isinstance(route_payload, dict)
        restore = route_payload.get("restore")
        assert isinstance(restore, dict)
        restore["native_update_control"] = "unsuppressible"
        unsuppressible_route = freeze_json(route_payload)
        assert isinstance(unsuppressible_route, FrozenJsonObject)
        unsuppressible = replace(suppressible, route=unsuppressible_route)

        cases = (
            (
                "suppressible",
                suppressible,
                capability(
                    "claude",
                    "direct_mcp",
                    {"transport": "stdio", "overlay_family": "claude_json"},
                    native_update_control="suppressible",
                ),
            ),
            (
                "unknown",
                groups["route:codex/github-plugin"],
                next(
                    record
                    for record in complete_capabilities()
                    if record.capability_identity == "capability:codex/native_plugin"
                ),
            ),
            (
                "unsuppressible",
                unsuppressible,
                capability(
                    "claude",
                    "direct_mcp",
                    {"transport": "stdio", "overlay_family": "claude_json"},
                    native_update_control="unsuppressible",
                ),
            ),
            (
                "not_applicable",
                groups["route:codex/mattpocock-standalone"],
                next(
                    record
                    for record in complete_capabilities()
                    if record.capability_identity == "capability:codex/standalone_skill"
                ),
            ),
        )

        for name, group, selected in cases:
            with self.subTest(name=name):
                _, diagnostics = _operation_matrix(group, selected)
                self.assertEqual(diagnostics, ())

    def test_unsupported_catalog_automation_is_fatal_before_planning(self) -> None:
        group = next(
            group
            for group in _active_route_groups(self.validated)
            if group.route_identity == "route:claude/chrome-devtools-plugin"
        )
        selected = capability(
            "claude",
            "native_plugin",
            {"manager": "claude", "scope": "user"},
            unavailable_operation="install",
            native_update_control="suppressible",
        )

        _, diagnostics = _operation_matrix(group, selected)

        self.assertEqual(
            tuple(diagnostic.code for diagnostic in diagnostics),
            ("ACTION_OPERATION_UNAUTHORIZED",),
        )

    def test_selected_component_controls_require_exact_capability_support(self) -> None:
        group = next(
            group
            for group in _active_route_groups(self.validated)
            if group.route_identity == "route:codex/github-plugin"
        )
        selected = _matching_capability(group, complete_capabilities())
        assert selected is not None

        self.assertEqual(_component_control_diagnostics(group, selected), ())

        incomplete = capability(
            "codex",
            "native_plugin",
            {"manager": "codex", "scope": "user"},
            supported_controls=tuple(
                identity
                for identity in group.controlled_equipment_identities
                if identity != "skill:github/yeet"
            ),
        )
        self.assertEqual(
            tuple(
                diagnostic.code
                for diagnostic in _component_control_diagnostics(group, incomplete)
            ),
            ("COMPONENT_CONTROL_UNAUTHORIZED",),
        )

        missing_selected_state = capability(
            "codex",
            "native_plugin",
            {"manager": "codex", "scope": "user"},
            supported_controls=group.controlled_equipment_identities,
            supported_states=("disabled",),
            native_update_control="unknown",
        )
        self.assertEqual(
            tuple(
                diagnostic.code
                for diagnostic in _component_control_diagnostics(
                    group, missing_selected_state
                )
            ),
            ("COMPONENT_CONTROL_UNAUTHORIZED",),
        )
        records = tuple(
            missing_selected_state
            if record.capability_identity == missing_selected_state.capability_identity
            else record
            for record in complete_capabilities()
        )
        inventory, capabilities = runtime_inventory(
            self.validated,
            capabilities=records,
        )

        resolution = resolve(
            "apply",
            self.validated.catalog,
            self.validated.lock,
            inventory,
            capabilities,
        )

        self.assertIn(
            ("COMPONENT_CONTROL_UNAUTHORIZED", group.route_identity),
            tuple(
                (diagnostic.code, diagnostic.route_identity)
                for diagnostic in resolution.diagnostics
            ),
        )
        self.assertIsNone(resolution.candidate_plan)
        self.assertIsNone(resolution.mutation_plan)

    def test_selected_component_controls_accept_the_exact_state_subset(self) -> None:
        original = next(
            group
            for group in _active_route_groups(self.validated)
            if group.route_identity == "route:codex/github-plugin"
        )
        route_payload = thaw_json(original.route)
        assert isinstance(route_payload, dict)
        controls = route_payload.get("component_controls")
        assert isinstance(controls, list)
        for control in controls:
            assert isinstance(control, dict)
            control["state"] = "disabled"
        route = freeze_json(route_payload)
        assert isinstance(route, FrozenJsonObject)
        group = replace(original, route=route)
        selected = capability(
            "codex",
            "native_plugin",
            {"manager": "codex", "scope": "user"},
            supported_controls=group.controlled_equipment_identities,
            supported_states=("disabled",),
            native_update_control="unknown",
        )

        self.assertEqual(_component_control_diagnostics(group, selected), ())

    def test_component_control_modes_follow_selected_state_dispositions(self) -> None:
        original = next(
            group
            for group in _active_route_groups(self.validated)
            if group.route_identity == "route:codex/github-plugin"
        )
        route_payload = thaw_json(original.route)
        assert isinstance(route_payload, dict)
        controls = route_payload.get("component_controls")
        operations = route_payload.get("operations")
        assert isinstance(controls, list)
        assert isinstance(operations, dict)
        for control in controls:
            assert isinstance(control, dict)
            control["state"] = "disabled"
        operations["disable"] = {"disposition": "operator_action"}
        route = freeze_json(route_payload)
        assert isinstance(route, FrozenJsonObject)
        group = replace(original, route=route)

        for mode in ("operator_action", "inspect_only"):
            with self.subTest(accepted_mode=mode):
                selected = capability(
                    "codex",
                    "native_plugin",
                    {"manager": "codex", "scope": "user"},
                    supported_controls=group.controlled_equipment_identities,
                    supported_states=("disabled",),
                    component_mode=mode,
                    native_update_control="unknown",
                    operation_modes={"disable": mode},
                )
                self.assertEqual(
                    _component_control_diagnostics(group, selected),
                    (),
                )
                _, diagnostics = _operation_matrix(group, selected)
                self.assertEqual(diagnostics, ())

        automated = capability(
            "codex",
            "native_plugin",
            {"manager": "codex", "scope": "user"},
            supported_controls=group.controlled_equipment_identities,
            supported_states=("disabled",),
            component_mode="automated",
            native_update_control="unknown",
        )
        self.assertEqual(
            tuple(
                diagnostic.code
                for diagnostic in _component_control_diagnostics(group, automated)
            ),
            ("COMPONENT_CONTROL_UNAUTHORIZED",),
        )

    def test_nonautomated_component_controls_never_authorize_configuration_drift(
        self,
    ) -> None:
        original = next(
            group
            for group in _active_route_groups(self.validated)
            if group.route_identity == "route:codex/github-plugin"
        )
        route_payload = thaw_json(original.route)
        assert isinstance(route_payload, dict)
        controls = route_payload.get("component_controls")
        operations = route_payload.get("operations")
        assert isinstance(controls, list)
        assert isinstance(operations, dict)
        for control in controls:
            assert isinstance(control, dict)
            control["state"] = "disabled"
        operations["disable"] = {"disposition": "operator_action"}
        route = freeze_json(route_payload)
        assert isinstance(route, FrozenJsonObject)
        group = replace(original, route=route)
        selected = capability(
            "codex",
            "native_plugin",
            {"manager": "codex", "scope": "user"},
            supported_controls=group.controlled_equipment_identities,
            supported_states=("disabled",),
            component_mode="operator_action",
            native_update_control="unknown",
            operation_modes={"disable": "operator_action"},
        )
        matrix, matrix_diagnostics = _operation_matrix(group, selected)
        self.assertEqual(matrix_diagnostics, ())
        inventory, _ = runtime_inventory(self.validated)
        observation = next(
            item
            for item in inventory.observations
            if item.route_identity == group.route_identity
        )

        planned_operations, diagnostics = _action_operations(
            group,
            observation,
            matrix,
            retirement=False,
        )

        self.assertEqual(planned_operations, ())
        self.assertEqual(
            tuple(diagnostic.code for diagnostic in diagnostics),
            ("DESIRED_STATE_UNREACHABLE",),
        )

    def test_observation_must_bind_the_exact_route_and_derived_read_scope(self) -> None:
        inventory, capabilities = runtime_inventory(self.validated)
        group = _active_route_groups(self.validated)[0]
        selected = _matching_capability(group, capabilities.records)
        assert selected is not None
        observation = next(
            observation
            for observation in inventory.observations
            if observation.harness == group.harness
            and observation.route_identity == group.route_identity
        )

        self.assertEqual(
            _observation_binding_diagnostics(group, selected, observation),
            (),
        )

        changed = dict(observation.document)
        changed["route_digest"] = "sha256:" + "0" * 64
        forged_document = freeze_json(changed)
        assert isinstance(forged_document, FrozenJsonObject)
        forged = replace(observation, document=forged_document)
        self.assertEqual(
            tuple(
                diagnostic.code
                for diagnostic in _observation_binding_diagnostics(
                    group, selected, forged
                )
            ),
            ("RUNTIME_OBSERVATION_BINDING_MISMATCH",),
        )

    def test_complete_inventory_resolves_deterministically_without_mutation_authority(
        self,
    ) -> None:
        inventory, capabilities = runtime_inventory(self.validated)

        first = resolve(
            "audit",
            self.validated.catalog,
            self.validated.lock,
            inventory,
            capabilities,
        )
        second = resolve(
            "audit",
            self.validated.catalog,
            self.validated.lock,
            inventory,
            capabilities,
        )

        self.assertEqual(first, second)
        self.assertEqual(first.diagnostics, ())
        self.assertEqual(len(first.coverage), 132)
        self.assertEqual(len(first.provider_selections), 132)
        self.assertEqual(len(first.operation_matrix), 39)
        self.assertEqual(len(first.overlays), 11)
        self.assertIsNotNone(first.candidate_plan)
        self.assertIsNone(first.mutation_plan)
        self.assertRegex(first.digest, r"^sha256:[0-9a-f]{64}$")

    def test_apply_resolution_returns_the_same_validated_candidate_plan(self) -> None:
        inventory, capabilities = runtime_inventory(self.validated)

        resolution = resolve(
            "apply",
            self.validated.catalog,
            self.validated.lock,
            inventory,
            capabilities,
        )

        self.assertEqual(resolution.diagnostics, ())
        self.assertIsNotNone(resolution.candidate_plan)
        self.assertIs(resolution.mutation_plan, resolution.candidate_plan)

    def test_missing_runtime_observation_returns_no_candidate_or_mutation_plan(
        self,
    ) -> None:
        inventory, capabilities = runtime_inventory(
            self.validated,
            omit_route="route:cursor/direct-github",
        )

        resolution = resolve(
            "audit",
            self.validated.catalog,
            self.validated.lock,
            inventory,
            capabilities,
        )

        self.assertEqual(
            tuple(diagnostic.code for diagnostic in resolution.diagnostics),
            ("RUNTIME_OBSERVATION_MISSING",),
        )
        self.assertIsNone(resolution.candidate_plan)
        self.assertIsNone(resolution.mutation_plan)

    def test_manager_drift_is_reported_before_any_candidate_plan(self) -> None:
        inventory, capabilities = runtime_inventory(
            self.validated,
            manager_drift_route="route:claude/mattpocock-plugin",
        )

        resolution = resolve(
            "audit",
            self.validated.catalog,
            self.validated.lock,
            inventory,
            capabilities,
        )

        self.assertIn(
            "MANAGER_DRIFT_REVIEW_REQUIRED",
            tuple(diagnostic.code for diagnostic in resolution.diagnostics),
        )
        self.assertIsNone(resolution.candidate_plan)

    def test_native_rolling_requires_exact_observed_version_before_planning(
        self,
    ) -> None:
        inventory, capabilities = runtime_inventory(self.validated)
        route_identity = "route:claude/mattpocock-plugin"
        observation = next(
            item
            for item in inventory.observations
            if item.route_identity == route_identity
        )
        document = thaw_json(observation.document)
        assert isinstance(document, dict)
        result = document.get("result")
        assert isinstance(result, dict)
        normalized = result.get("normalized_state")
        assert isinstance(normalized, dict)
        cases = (
            (
                "absent-unknown",
                {**normalized, "observed_version": {"status": "unknown"}},
            ),
            (
                "present-unknown",
                {
                    **normalized,
                    "route_presence": "present",
                    "observed_version": {"status": "unknown"},
                },
            ),
            (
                "present-wrong-baseline",
                {
                    **normalized,
                    "route_presence": "present",
                    "observed_version": {
                        "status": "observed",
                        "value": "forged-baseline",
                    },
                },
            ),
        )

        for name, state in cases:
            with self.subTest(name=name):
                changed_inventory = with_normalized_state(
                    inventory,
                    route_identity,
                    state,
                )
                resolution = resolve(
                    "audit",
                    self.validated.catalog,
                    self.validated.lock,
                    changed_inventory,
                    capabilities,
                )

                self.assertEqual(
                    tuple(diagnostic.code for diagnostic in resolution.diagnostics),
                    ("NATIVE_ROLLING_VERSION_UNVERIFIED",),
                )
                self.assertIsNone(resolution.candidate_plan)
                self.assertIsNone(resolution.mutation_plan)

    def test_immutable_content_mismatch_schedules_restore_not_configure(self) -> None:
        inventory, capabilities = runtime_inventory(self.validated)
        group = next(
            group
            for group in _active_route_groups(self.validated)
            if group.route_identity == "route:codex/mattpocock-standalone"
        )
        selected = _matching_capability(group, capabilities.records)
        assert selected is not None
        matrix, diagnostics = _operation_matrix(group, selected)
        self.assertEqual(diagnostics, ())
        observation = next(
            item
            for item in inventory.observations
            if item.route_identity == group.route_identity
        )
        document = thaw_json(observation.document)
        assert isinstance(document, dict)
        result = document.get("result")
        assert isinstance(result, dict)
        normalized = result.get("normalized_state")
        assert isinstance(normalized, dict)
        restore = thaw_json(group.route.get("restore"))
        assert isinstance(restore, dict)
        changed_inventory = with_normalized_state(
            inventory,
            group.route_identity,
            {
                **normalized,
                "route_presence": "present",
                "enablement": "not_applicable",
                "observed_version": {"status": "not_applicable"},
                "immutable_content": {
                    "status": "observed",
                    "revision": "0" * 40,
                    "content_digest": restore["content_digest"],
                },
                "manager_drift": {
                    "status": "not_applicable",
                    "reviewed_baseline": None,
                    "observation_source": None,
                },
            },
        )
        changed_observation = next(
            item
            for item in changed_inventory.observations
            if item.route_identity == group.route_identity
        )

        operations, action_diagnostics = _action_operations(
            group,
            changed_observation,
            matrix,
            retirement=False,
        )

        self.assertEqual(action_diagnostics, ())
        self.assertEqual(operations, ("restore",))

    def test_nonautomated_immutable_restore_never_becomes_executable(self) -> None:
        inventory, _ = runtime_inventory(self.validated)
        original_group = next(
            group
            for group in _active_route_groups(self.validated)
            if group.route_identity == "route:codex/mattpocock-standalone"
        )
        observation = next(
            item
            for item in inventory.observations
            if item.route_identity == original_group.route_identity
        )
        document = thaw_json(observation.document)
        assert isinstance(document, dict)
        result = document.get("result")
        assert isinstance(result, dict)
        normalized = result.get("normalized_state")
        assert isinstance(normalized, dict)
        restore = thaw_json(original_group.route.get("restore"))
        assert isinstance(restore, dict)
        changed_inventory = with_normalized_state(
            inventory,
            original_group.route_identity,
            {
                **normalized,
                "route_presence": "present",
                "enablement": "not_applicable",
                "observed_version": {"status": "not_applicable"},
                "immutable_content": {
                    "status": "observed",
                    "revision": "0" * 40,
                    "content_digest": restore["content_digest"],
                },
                "manager_drift": {
                    "status": "not_applicable",
                    "reviewed_baseline": None,
                    "observation_source": None,
                },
            },
        )
        changed_observation = next(
            item
            for item in changed_inventory.observations
            if item.route_identity == original_group.route_identity
        )

        for mode in ("operator_action", "unavailable"):
            with self.subTest(mode=mode):
                route = thaw_json(original_group.route)
                assert isinstance(route, dict)
                operations = route.get("operations")
                assert isinstance(operations, dict)
                operations["restore"] = (
                    {
                        "disposition": "operator_action",
                        "operator_action_reference": (
                            "docs/agent-equipment/ARCHITECTURE.md"
                        ),
                    }
                    if mode == "operator_action"
                    else {"disposition": "unavailable"}
                )
                frozen_route = freeze_json(route)
                assert isinstance(frozen_route, FrozenJsonObject)
                group = replace(original_group, route=frozen_route)
                selected = capability(
                    "codex",
                    "standalone_skill",
                    {"canonical_root": "agents_skills"},
                    operation_modes={"restore": mode},
                )
                matrix, matrix_diagnostics = _operation_matrix(group, selected)
                self.assertEqual(matrix_diagnostics, ())

                action_operations, action_diagnostics = _action_operations(
                    group,
                    changed_observation,
                    matrix,
                    retirement=False,
                )

                self.assertEqual(action_operations, ())
                self.assertEqual(
                    tuple(diagnostic.code for diagnostic in action_diagnostics),
                    ("DESIRED_STATE_UNREACHABLE",),
                )

    def test_immutable_active_content_is_exactly_reconciled_and_verified(self) -> None:
        inventory, capabilities = runtime_inventory(self.validated)
        route_identity = "route:codex/mattpocock-standalone"
        group = next(
            group
            for group in _active_route_groups(self.validated)
            if group.route_identity == route_identity
        )
        restore = thaw_json(group.route.get("restore"))
        assert isinstance(restore, dict)
        observation = next(
            item
            for item in inventory.observations
            if item.route_identity == route_identity
        )
        document = thaw_json(observation.document)
        assert isinstance(document, dict)
        result = document.get("result")
        assert isinstance(result, dict)
        normalized = result.get("normalized_state")
        assert isinstance(normalized, dict)
        exact_content = {
            "status": "observed",
            "revision": restore["revision"],
            "content_digest": restore["content_digest"],
        }
        absent_resolution = resolve(
            "audit",
            self.validated.catalog,
            self.validated.lock,
            inventory,
            capabilities,
        )
        self.assertEqual(absent_resolution.diagnostics, ())
        assert absent_resolution.candidate_plan is not None
        absent_operations = tuple(
            node.definition.get("operation")
            for node in absent_resolution.candidate_plan.nodes
            if node.kind == "mutation"
            and node.definition.get("route_identity") == route_identity
        )
        self.assertIn("install", absent_operations)
        self.assertNotIn("restore", absent_operations)
        base_present = {
            **normalized,
            "route_presence": "present",
            "enablement": "not_applicable",
            "observed_version": {"status": "not_applicable"},
            "manager_drift": {
                "status": "not_applicable",
                "reviewed_baseline": None,
                "observation_source": None,
            },
        }
        cases = (
            ("exact", exact_content, False),
            (
                "revision-drift",
                {**exact_content, "revision": "0" * 40},
                True,
            ),
            (
                "content-drift",
                {**exact_content, "content_digest": "sha256:" + "0" * 64},
                True,
            ),
        )

        for name, immutable_content, expects_restore in cases:
            with self.subTest(name=name):
                changed = with_normalized_state(
                    inventory,
                    route_identity,
                    {**base_present, "immutable_content": immutable_content},
                )
                resolution = resolve(
                    "audit",
                    self.validated.catalog,
                    self.validated.lock,
                    changed,
                    capabilities,
                )

                self.assertEqual(resolution.diagnostics, ())
                assert resolution.candidate_plan is not None
                operations = tuple(
                    node.definition.get("operation")
                    for node in resolution.candidate_plan.nodes
                    if node.kind == "mutation"
                    and node.definition.get("route_identity") == route_identity
                )
                self.assertEqual("restore" in operations, expects_restore)
                self.assertNotIn("configure", operations)
                restore_nodes = tuple(
                    node
                    for node in resolution.candidate_plan.nodes
                    if node.kind == "mutation"
                    and node.definition.get("route_identity") == route_identity
                    and node.definition.get("operation") == "restore"
                )
                if expects_restore:
                    self.assertEqual(len(restore_nodes), 1)
                    self.assertEqual(
                        restore_nodes[0].definition.get("desired_state"),
                        freeze_json({"route_presence": "present"}),
                    )
                final = next(
                    node
                    for node in resolution.candidate_plan.nodes
                    if node.definition.get("purpose") == "final_coverage"
                )
                coverage_predicate = final.definition.get("coverage_predicate")
                assert isinstance(coverage_predicate, FrozenJsonObject)
                route_predicates = coverage_predicate.get("route_state_predicates")
                assert type(route_predicates) is tuple
                route_predicate = next(
                    predicate
                    for predicate in route_predicates
                    if isinstance(predicate, FrozenJsonObject)
                    and predicate.get("route_identity") == route_identity
                )
                normalized_predicate = route_predicate.get("normalized_state_predicate")
                assert isinstance(normalized_predicate, FrozenJsonObject)
                expected = normalized_predicate.get("expected")
                assert isinstance(expected, FrozenJsonObject)
                self.assertEqual(
                    expected.get("immutable_content"), freeze_json(exact_content)
                )

    def test_immutable_and_native_rolling_evidence_cannot_cross_classes(self) -> None:
        inventory, capabilities = runtime_inventory(self.validated)
        immutable_route = "route:codex/mattpocock-standalone"
        native_route = "route:codex/github-plugin"

        immutable_observation = next(
            item
            for item in inventory.observations
            if item.route_identity == immutable_route
        )
        immutable_document = thaw_json(immutable_observation.document)
        assert isinstance(immutable_document, dict)
        immutable_result = immutable_document.get("result")
        assert isinstance(immutable_result, dict)
        immutable_state = immutable_result.get("normalized_state")
        assert isinstance(immutable_state, dict)
        immutable_group = next(
            group
            for group in _active_route_groups(self.validated)
            if group.route_identity == immutable_route
        )
        immutable_restore = thaw_json(immutable_group.route.get("restore"))
        assert isinstance(immutable_restore, dict)

        native_observation = next(
            item
            for item in inventory.observations
            if item.route_identity == native_route
        )
        native_document = thaw_json(native_observation.document)
        assert isinstance(native_document, dict)
        native_result = native_document.get("result")
        assert isinstance(native_result, dict)
        native_state = native_result.get("normalized_state")
        assert isinstance(native_state, dict)
        native_group = next(
            group
            for group in _active_route_groups(self.validated)
            if group.route_identity == native_route
        )
        native_restore = thaw_json(native_group.route.get("restore"))
        assert isinstance(native_restore, dict)

        cases = (
            (
                "immutable-unknown",
                immutable_route,
                {
                    **immutable_state,
                    "route_presence": "present",
                    "enablement": "not_applicable",
                    "observed_version": {"status": "not_applicable"},
                    "immutable_content": {"status": "unknown"},
                },
                "IMMUTABLE_CONTENT_UNVERIFIED",
            ),
            (
                "immutable-partial",
                immutable_route,
                {
                    **immutable_state,
                    "route_presence": "partial",
                    "enablement": "not_applicable",
                    "observed_version": {"status": "not_applicable"},
                    "immutable_content": {"status": "unknown"},
                },
                "RUNTIME_STATE_INDETERMINATE",
            ),
            (
                "immutable-presence-unknown",
                immutable_route,
                {
                    **immutable_state,
                    "route_presence": "unknown",
                    "enablement": "not_applicable",
                    "observed_version": {"status": "not_applicable"},
                    "immutable_content": {"status": "unknown"},
                },
                "RUNTIME_STATE_INDETERMINATE",
            ),
            (
                "immutable-version",
                immutable_route,
                {
                    **immutable_state,
                    "route_presence": "present",
                    "enablement": "not_applicable",
                    "observed_version": {"status": "observed", "value": "1.0.0"},
                    "immutable_content": {
                        "status": "observed",
                        "revision": immutable_restore["revision"],
                        "content_digest": immutable_restore["content_digest"],
                    },
                },
                "IMMUTABLE_CONTENT_UNVERIFIED",
            ),
            (
                "native-immutable-content",
                native_route,
                {
                    **native_state,
                    "route_presence": "present",
                    "enablement": "enabled",
                    "observed_version": {
                        "status": "observed",
                        "value": native_restore["reviewed_baseline"],
                    },
                    "immutable_content": {
                        "status": "observed",
                        "revision": "0" * 40,
                        "content_digest": "sha256:" + "0" * 64,
                    },
                    "manager_drift": {
                        "status": "none",
                        "reviewed_baseline": native_restore["reviewed_baseline"],
                        "observation_source": native_restore["observation_source"],
                    },
                },
                "IMMUTABLE_CONTENT_UNVERIFIED",
            ),
        )

        for name, route_identity, state, expected_code in cases:
            with self.subTest(name=name):
                changed = with_normalized_state(inventory, route_identity, state)
                resolution = resolve(
                    "audit",
                    self.validated.catalog,
                    self.validated.lock,
                    changed,
                    capabilities,
                )

                self.assertEqual(
                    tuple(diagnostic.code for diagnostic in resolution.diagnostics),
                    (expected_code,),
                )
                self.assertIsNone(resolution.candidate_plan)
                self.assertIsNone(resolution.mutation_plan)

    def test_immutable_retirement_deletes_only_exact_reviewed_content(self) -> None:
        inventory, capabilities = runtime_inventory(self.validated)
        route_identity = "route:claude/retire-matt-tdd"
        group = next(
            group
            for group in _retirement_route_groups(self.validated)
            if group.route_identity == route_identity
        )
        restore = thaw_json(group.route.get("restore"))
        assert isinstance(restore, dict)
        observation = next(
            item
            for item in inventory.observations
            if item.route_identity == route_identity
        )
        document = thaw_json(observation.document)
        assert isinstance(document, dict)
        result = document.get("result")
        assert isinstance(result, dict)
        normalized = result.get("normalized_state")
        assert isinstance(normalized, dict)
        exact = normalized["immutable_content"]
        cases = (
            ("exact", normalized, (), True),
            (
                "absent",
                {
                    **normalized,
                    "route_presence": "absent",
                    "enablement": "not_applicable",
                    "immutable_content": {"status": "route_absent"},
                },
                (),
                False,
            ),
            (
                "revision-mismatch",
                {
                    **normalized,
                    "immutable_content": {**exact, "revision": "0" * 40},
                },
                ("IMMUTABLE_CONTENT_UNVERIFIED",),
                False,
            ),
            (
                "content-mismatch",
                {
                    **normalized,
                    "immutable_content": {
                        **exact,
                        "content_digest": "sha256:" + "0" * 64,
                    },
                },
                ("IMMUTABLE_CONTENT_UNVERIFIED",),
                False,
            ),
            (
                "unknown",
                {**normalized, "immutable_content": {"status": "unknown"}},
                ("IMMUTABLE_CONTENT_UNVERIFIED",),
                False,
            ),
        )

        for name, state, expected_diagnostics, expects_remove in cases:
            with self.subTest(name=name):
                changed = with_normalized_state(inventory, route_identity, state)
                resolution = resolve(
                    "audit",
                    self.validated.catalog,
                    self.validated.lock,
                    changed,
                    capabilities,
                )
                self.assertEqual(
                    tuple(diagnostic.code for diagnostic in resolution.diagnostics),
                    expected_diagnostics,
                )
                operations = (
                    ()
                    if resolution.candidate_plan is None
                    else tuple(
                        node.definition.get("operation")
                        for node in resolution.candidate_plan.nodes
                        if node.kind == "mutation"
                        and node.definition.get("route_identity") == route_identity
                    )
                )
                self.assertEqual("remove" in operations, expects_remove)

    def test_immutable_selection_requires_content_inspection_capability(self) -> None:
        original = next(
            record
            for record in complete_capabilities()
            if record.capability_identity == "capability:codex/standalone_skill"
        )
        payload = thaw_json(original.document)
        assert isinstance(payload, dict)
        operation_support = payload.get("operation_support")
        assert isinstance(operation_support, dict)
        inspect_support = operation_support.get("inspect")
        assert isinstance(inspect_support, dict)
        normalized_fields = inspect_support.get("normalized_fields")
        assert isinstance(normalized_fields, list)
        inspect_support["normalized_fields"] = [
            field for field in normalized_fields if field != "immutable_content"
        ]
        payload.pop("capability_digest")
        capability_digest = canonical_json_sha256(payload)
        payload["capability_digest"] = capability_digest
        document = freeze_json(payload)
        assert isinstance(document, FrozenJsonObject)
        incomplete = replace(
            original,
            document=document,
            capability_digest=capability_digest,
        )
        records = tuple(
            incomplete
            if record.capability_identity == incomplete.capability_identity
            else record
            for record in complete_capabilities()
        )
        inventory, capabilities = runtime_inventory(
            self.validated,
            capabilities=records,
        )

        resolution = resolve(
            "audit",
            self.validated.catalog,
            self.validated.lock,
            inventory,
            capabilities,
        )

        self.assertIn(
            (
                "IMMUTABLE_CONTENT_CAPABILITY_MISSING",
                "route:codex/mattpocock-standalone",
            ),
            tuple(
                (diagnostic.code, diagnostic.route_identity)
                for diagnostic in resolution.diagnostics
            ),
        )
        self.assertIsNone(resolution.candidate_plan)
        self.assertIsNone(resolution.mutation_plan)

    def test_immutable_evidence_changes_plan_digest_but_not_permutation_result(
        self,
    ) -> None:
        inventory, capabilities = runtime_inventory(self.validated)
        route_identity = "route:codex/mattpocock-standalone"
        group = next(
            group
            for group in _active_route_groups(self.validated)
            if group.route_identity == route_identity
        )
        restore = thaw_json(group.route.get("restore"))
        assert isinstance(restore, dict)
        observation = next(
            item
            for item in inventory.observations
            if item.route_identity == route_identity
        )
        document = thaw_json(observation.document)
        assert isinstance(document, dict)
        result = document.get("result")
        assert isinstance(result, dict)
        normalized = result.get("normalized_state")
        assert isinstance(normalized, dict)
        base_present = {
            **normalized,
            "route_presence": "present",
            "enablement": "not_applicable",
            "observed_version": {"status": "not_applicable"},
            "manager_drift": {
                "status": "not_applicable",
                "reviewed_baseline": None,
                "observation_source": None,
            },
        }
        changed_inventories = tuple(
            with_normalized_state(
                inventory,
                route_identity,
                {
                    **base_present,
                    "immutable_content": {
                        "status": "observed",
                        "revision": revision,
                        "content_digest": content_digest,
                    },
                },
            )
            for revision, content_digest in (
                ("0" * 40, restore["content_digest"]),
                (restore["revision"], "sha256:" + "0" * 64),
            )
        )
        resolutions = tuple(
            resolve(
                "audit",
                self.validated.catalog,
                self.validated.lock,
                changed,
                capabilities,
            )
            for changed in changed_inventories
        )

        self.assertEqual(tuple(result.diagnostics for result in resolutions), ((), ()))
        plans = tuple(result.candidate_plan for result in resolutions)
        self.assertNotIn(None, plans)
        self.assertEqual(len({plan.digest for plan in plans if plan is not None}), 2)
        self.assertEqual(
            tuple(
                tuple(
                    node.definition.get("operation")
                    for node in plan.nodes
                    if node.kind == "mutation"
                    and node.definition.get("route_identity") == route_identity
                )
                for plan in plans
                if plan is not None
            ),
            (("restore",), ("restore",)),
        )
        first_inventory = changed_inventories[0]
        permuted = admit_runtime_inventory(
            [thaw_json(first_inventory.capabilities.as_json())],
            [
                {
                    "record_type": "RuntimeObservation",
                    "record": thaw_json(observation.document),
                }
                for observation in reversed(first_inventory.observations)
            ],
        )
        self.assertEqual(permuted, first_inventory)
        assert isinstance(permuted, RuntimeInventory)
        self.assertEqual(
            resolve(
                "audit",
                self.validated.catalog,
                self.validated.lock,
                permuted,
                capabilities,
            ),
            resolutions[0],
        )

    def test_configure_is_scheduled_only_when_exact_desired_configuration_drifts(
        self,
    ) -> None:
        inventory, capabilities = runtime_inventory(self.validated)
        group = next(
            group
            for group in _active_route_groups(self.validated)
            if group.route_identity == "route:codex/github-plugin"
        )
        observation = next(
            observation
            for observation in inventory.observations
            if observation.route_identity == group.route_identity
        )
        document = thaw_json(observation.document)
        assert isinstance(document, dict)
        result = document.get("result")
        assert isinstance(result, dict)
        normalized = result.get("normalized_state")
        assert isinstance(normalized, dict)
        restore = thaw_json(group.route.get("restore"))
        assert isinstance(restore, dict)
        desired_configuration = {
            "status": "observed",
            "digest": canonical_json_sha256(
                {
                    "provider": group.route.get("provider"),
                    "component_controls": group.route.get("component_controls"),
                }
            ),
        }
        exact_state = {
            **normalized,
            "route_presence": "present",
            "enablement": "enabled",
            "observed_version": {
                "status": "observed",
                "value": restore["reviewed_baseline"],
            },
            "configuration": desired_configuration,
            "component_states": sorted(
                thaw_json(group.route.get("component_controls")),
                key=lambda component: component["equipment_identity"],
            ),
        }

        cases = (
            ("converged", exact_state, False),
            (
                "stale-configuration",
                {
                    **exact_state,
                    "configuration": {
                        "status": "observed",
                        "digest": "sha256:" + "0" * 64,
                    },
                },
                True,
            ),
            (
                "stale-component-state",
                {
                    **exact_state,
                    "component_states": [
                        {
                            **component,
                            "state": (
                                "disabled"
                                if component["state"] == "enabled"
                                else "enabled"
                            ),
                        }
                        if index == 0
                        else component
                        for index, component in enumerate(
                            exact_state["component_states"]
                        )
                    ],
                },
                True,
            ),
        )
        for name, state, expects_configure in cases:
            with self.subTest(name=name):
                changed_inventory = with_normalized_state(
                    inventory,
                    group.route_identity,
                    state,
                )
                resolution = resolve(
                    "audit",
                    self.validated.catalog,
                    self.validated.lock,
                    changed_inventory,
                    capabilities,
                )
                self.assertEqual(resolution.diagnostics, ())
                assert resolution.candidate_plan is not None
                operations = tuple(
                    node.definition.get("operation")
                    for node in resolution.candidate_plan.nodes
                    if node.kind == "mutation"
                    and node.definition.get("route_identity") == group.route_identity
                )
                self.assertEqual("configure" in operations, expects_configure)

    def test_provider_switch_graph_verifies_winner_before_every_losing_retirement(
        self,
    ) -> None:
        inventory, capabilities = runtime_inventory(self.validated)
        resolution = resolve(
            "audit",
            self.validated.catalog,
            self.validated.lock,
            inventory,
            capabilities,
        )
        assert resolution.candidate_plan is not None
        nodes = resolution.candidate_plan.nodes
        matt_readiness = next(
            node
            for node in nodes
            if node.definition.get("purpose") == "projector_readiness"
        )
        matt_activation = next(
            node
            for node in nodes
            if node.definition.get("purpose") == "winner_activation"
            and node.definition.get("route_identity")
            == "route:claude/mattpocock-plugin"
        )
        matt_actions = tuple(
            node
            for node in nodes
            if node.kind == "mutation"
            and node.definition.get("route_identity")
            == "route:claude/mattpocock-plugin"
        )
        losing_actions = tuple(
            node
            for node in nodes
            if node.kind == "mutation"
            and "retire-matt" in str(node.definition.get("route_identity"))
        )

        self.assertEqual(len(losing_actions), 21)
        self.assertIn(matt_readiness.identity, matt_actions[0].dependencies)
        self.assertIn(matt_actions[-1].identity, matt_activation.dependencies)
        self.assertTrue(
            all(
                matt_activation.identity in action.dependencies
                for action in losing_actions
            )
        )
        verification_nodes = tuple(
            node for node in nodes if node.kind == "verification"
        )
        self.assertTrue(verification_nodes)
        self.assertTrue(
            all(
                "checkpoint" not in repr(node.definition) for node in verification_nodes
            )
        )

    def test_projector_readiness_is_one_exact_desired_catalog_policy(self) -> None:
        inventory, capabilities = runtime_inventory(self.validated)
        resolution = resolve(
            "audit",
            self.validated.catalog,
            self.validated.lock,
            inventory,
            capabilities,
        )
        assert resolution.candidate_plan is not None
        readiness_nodes = tuple(
            node
            for node in resolution.candidate_plan.nodes
            if node.definition.get("purpose") == "projector_readiness"
        )
        self.assertEqual(len(readiness_nodes), 1)
        readiness = readiness_nodes[0]
        predicate = readiness.definition.get("projector_policy_predicate")
        self.assertIsInstance(predicate, FrozenJsonObject)
        assert isinstance(predicate, FrozenJsonObject)
        desired_policy = predicate.get("desired_policy")
        self.assertIsInstance(desired_policy, FrozenJsonObject)
        assert isinstance(desired_policy, FrozenJsonObject)

        included: list[str] = []
        all_claude_skills: list[str] = []
        for coverage in self.validated.coverage:
            if (
                coverage.harness != "claude"
                or not coverage.equipment_identity.startswith("skill:")
            ):
                continue
            all_claude_skills.append(coverage.equipment_identity)
            selection = coverage.record.get("provider_selection")
            if not isinstance(selection, FrozenJsonObject):
                continue
            preferred = selection.get("preferred_route")
            routes = selection.get("routes")
            assert type(routes) is tuple
            route = next(item for item in routes if item.get("identity") == preferred)
            provider = route.get("provider")
            assert isinstance(provider, FrozenJsonObject)
            if provider.get("kind") == "standalone_skill":
                included.append(coverage.equipment_identity)
        expected_included = tuple(sorted(included))
        expected_excluded = tuple(sorted(set(all_claude_skills) - set(included)))
        matt_group = next(
            group
            for group in _active_route_groups(self.validated)
            if group.route_identity == "route:claude/mattpocock-plugin"
        )
        matt_skills = tuple(
            identity
            for identity in matt_group.equipment_identities
            if identity.startswith("skill:")
        )

        self.assertEqual(predicate.get("operator"), "equals")
        self.assertEqual(desired_policy.get("mode"), "catalog_driven")
        self.assertEqual(desired_policy.get("harness"), "claude")
        self.assertEqual(
            desired_policy.get("control_surface"),
            "surface:claude/standalone-skill-projector",
        )
        self.assertEqual(
            desired_policy.get("included_skill_identities"), expected_included
        )
        self.assertEqual(
            desired_policy.get("excluded_skill_identities"), expected_excluded
        )
        self.assertTrue(set(matt_skills) <= set(expected_excluded))
        self.assertEqual(
            desired_policy.get("implementation_manifest_digest"),
            inventory.implementation_manifest_digest,
        )
        self.assertEqual(
            readiness.definition.get("read_surface_scope"),
            ("surface:claude/standalone-skill-projector",),
        )
        self.assertEqual(readiness.definition.get("harness"), "")
        self.assertEqual(readiness.definition.get("route_identity"), "")
        self.assertIsNone(readiness.definition.get("capability_identity"))
        self.assertIsNone(readiness.definition.get("capability_digest"))
        self.assertNotIn("normalized_state_predicate", readiness.definition)
        policy_payload = thaw_json(desired_policy)
        assert isinstance(policy_payload, dict)
        policy_digest = policy_payload.pop("policy_digest")
        self.assertEqual(policy_digest, canonical_json_sha256(policy_payload))
        self.assertEqual(
            readiness.definition.get("predicate_digest"),
            canonical_json_sha256(predicate),
        )
        self.assertNotIn("observed_version", repr(predicate))

    def test_native_rolling_verification_requires_the_reviewed_version_and_drift(
        self,
    ) -> None:
        inventory, capabilities = runtime_inventory(self.validated)
        resolution = resolve(
            "audit",
            self.validated.catalog,
            self.validated.lock,
            inventory,
            capabilities,
        )
        self.assertEqual(resolution.diagnostics, ())
        assert resolution.candidate_plan is not None
        route_identity = "route:claude/mattpocock-plugin"
        expected_version = freeze_json({"status": "observed", "value": "1.2.3"})
        expected_drift = freeze_json(
            {
                "status": "none",
                "reviewed_baseline": "1.2.3",
                "observation_source": (
                    "Claude official marketplace, auto-update documentation, "
                    "and upstream plugin manifest"
                ),
            }
        )
        winner = next(
            node
            for node in resolution.candidate_plan.nodes
            if node.definition.get("purpose") == "winner_activation"
            and node.definition.get("route_identity") == route_identity
        )
        winner_predicate = winner.definition.get("normalized_state_predicate")
        assert isinstance(winner_predicate, FrozenJsonObject)
        winner_expected = winner_predicate.get("expected")
        assert isinstance(winner_expected, FrozenJsonObject)

        final = next(
            node
            for node in resolution.candidate_plan.nodes
            if node.definition.get("purpose") == "final_coverage"
        )
        coverage_predicate = final.definition.get("coverage_predicate")
        assert isinstance(coverage_predicate, FrozenJsonObject)
        route_predicates = coverage_predicate.get("route_state_predicates")
        assert type(route_predicates) is tuple
        final_route = next(
            record
            for record in route_predicates
            if isinstance(record, FrozenJsonObject)
            and record.get("route_identity") == route_identity
        )
        final_predicate = final_route.get("normalized_state_predicate")
        assert isinstance(final_predicate, FrozenJsonObject)
        final_expected = final_predicate.get("expected")
        assert isinstance(final_expected, FrozenJsonObject)

        for expected in (winner_expected, final_expected):
            self.assertEqual(expected.get("observed_version"), expected_version)
            self.assertEqual(expected.get("manager_drift"), expected_drift)

    def test_verification_definitions_embed_complete_digest_bound_predicates(
        self,
    ) -> None:
        inventory, capabilities = runtime_inventory(self.validated)
        resolution = resolve(
            "audit",
            self.validated.catalog,
            self.validated.lock,
            inventory,
            capabilities,
        )
        self.assertEqual(resolution.diagnostics, ())
        assert resolution.candidate_plan is not None
        verification_nodes = tuple(
            node
            for node in resolution.candidate_plan.nodes
            if node.kind == "verification"
        )
        route_verifications = tuple(
            node
            for node in verification_nodes
            if node.definition.get("purpose") == "winner_activation"
        )
        self.assertTrue(route_verifications)
        for node in route_verifications:
            predicate = node.definition.get("normalized_state_predicate")
            self.assertIsInstance(predicate, FrozenJsonObject)
            assert isinstance(predicate, FrozenJsonObject)
            self.assertIn(predicate.get("operator"), {"equals", "contains"})
            self.assertIsInstance(predicate.get("expected"), FrozenJsonObject)
            self.assertEqual(
                node.definition.get("predicate_digest"),
                canonical_json_sha256(predicate),
            )
            self.assertTrue(node.definition.get("active_equipment_identities"))
            self.assertIsInstance(
                node.definition.get("controlled_equipment_identities"), tuple
            )
            self.assertTrue(node.definition.get("activation_group"))
            self.assertTrue(node.definition.get("read_surface_scope"))

        final = next(
            node
            for node in verification_nodes
            if node.definition.get("purpose") == "final_coverage"
        )
        coverage_predicate = final.definition.get("coverage_predicate")
        self.assertIsInstance(coverage_predicate, FrozenJsonObject)
        assert isinstance(coverage_predicate, FrozenJsonObject)
        self.assertEqual(coverage_predicate.get("operator"), "all")
        self.assertEqual(
            final.definition.get("predicate_digest"),
            canonical_json_sha256(coverage_predicate),
        )
        coverage_membership = coverage_predicate.get("coverage_membership")
        self.assertEqual(coverage_membership, resolution.provider_selections)
        self.assertEqual(len(coverage_membership), 132)
        active_membership = coverage_predicate.get("active_activation_membership")
        self.assertEqual(
            active_membership,
            final.definition.get("active_activation_membership"),
        )
        self.assertEqual(len(active_membership), 16)
        route_predicates = coverage_predicate.get("route_state_predicates")
        self.assertEqual(len(route_predicates), 39)
        complete_scope = tuple(
            sorted(
                {
                    surface
                    for route_predicate in route_predicates
                    for surface in route_predicate.get("read_surface_scope")
                }
            )
        )
        self.assertEqual(
            coverage_predicate.get("read_surface_scope"),
            complete_scope,
        )
        self.assertEqual(final.definition.get("read_surface_scope"), complete_scope)
        self.assertTrue(
            all(
                isinstance(
                    route_predicate.get("normalized_state_predicate"),
                    FrozenJsonObject,
                )
                for route_predicate in route_predicates
            )
        )

    def test_unsupported_automated_action_closes_cat_10_end_to_end(self) -> None:
        records = list(complete_capabilities())
        records[1] = capability(
            "claude",
            "native_plugin",
            {"manager": "claude", "scope": "user"},
            unavailable_operation="install",
        )
        inventory, capabilities = runtime_inventory(
            self.validated,
            capabilities=tuple(records),
        )

        resolution = resolve(
            "apply",
            self.validated.catalog,
            self.validated.lock,
            inventory,
            capabilities,
        )

        self.assertIn(
            "ACTION_OPERATION_UNAUTHORIZED",
            tuple(diagnostic.code for diagnostic in resolution.diagnostics),
        )
        self.assertIsNone(resolution.candidate_plan)
        self.assertIsNone(resolution.mutation_plan)


if __name__ == "__main__":
    unittest.main()
