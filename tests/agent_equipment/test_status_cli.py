from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import agent_equipment
from agent_equipment.canonical import canonical_json_sha256
from agent_equipment.inventory import (
    ReadOnlyAdapter,
    admit_capability_discovery,
    admit_observe_request,
)
from agent_equipment.model import (
    _INSTALLED_IMPLEMENTATION_PATHS,
    CapabilityDiscovery,
    FrozenJsonObject,
    InstalledFile,
    InstalledImplementationManifest,
    ObserveRequest,
    ValidatedCatalogLock,
    _installed_implementation_digest,
    freeze_json,
    thaw_json,
)
from agent_equipment.resolver import (
    _active_route_groups,
    _matching_capability,
    _retirement_route_groups,
)

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


def _mutation_support(disposition: object) -> dict[str, object]:
    if disposition == "automated":
        return {
            "mode": "automated",
            "compare_before_mutate": True,
            "idempotency": "state_convergent",
            "compensation": "restore_captured_pre_state",
        }
    if disposition == "operator_action":
        return {
            "mode": "operator_action",
            "operator_action_reference": "docs/agent-equipment/ARCHITECTURE.md",
        }
    return {"mode": "unavailable"}


def _provider_match(provider: FrozenJsonObject, harness: str) -> dict[str, object]:
    kind = provider.get("kind")
    if kind == "standalone_skill":
        return {"kind": kind, "canonical_root": provider.get("canonical_root")}
    if kind == "native_plugin":
        return {
            "kind": kind,
            "manager": provider.get("manager"),
            "scope": provider.get("scope"),
        }
    if kind == "direct_mcp":
        return {
            "kind": kind,
            "transport": provider.get("transport"),
            "overlay_family": {
                "claude": "claude_json",
                "codex": "codex_toml",
                "cursor": "cursor_json",
            }[harness],
        }
    raise AssertionError("unsupported test provider")


def _fake_runtime_inputs(
    validated: ValidatedCatalogLock,
    manifest: InstalledImplementationManifest,
    *,
    command: str = "status",
) -> tuple[tuple[ReadOnlyAdapter, ...], tuple[ObserveRequest, ...], ReadOnlyAdapter]:
    active_groups = _active_route_groups(validated)
    retirement_groups = _retirement_route_groups(validated)
    groups = (*active_groups, *retirement_groups)
    group_families: dict[tuple[str, str], list[object]] = {}
    for group in groups:
        provider = group.route.get("provider")
        assert isinstance(provider, FrozenJsonObject)
        kind = provider.get("kind")
        assert isinstance(kind, str)
        group_families.setdefault((group.harness, kind), []).append(group)

    capability_records: list[dict[str, object]] = []
    for (harness, kind), family_groups in sorted(group_families.items()):
        representative = family_groups[0]
        provider = representative.route.get("provider")
        operations = representative.route.get("operations")
        restore = representative.route.get("restore")
        assert isinstance(provider, FrozenJsonObject)
        assert isinstance(operations, FrozenJsonObject)
        assert isinstance(restore, FrozenJsonObject)
        for group in family_groups[1:]:
            self_operations = group.route.get("operations")
            self_restore = group.route.get("restore")
            assert isinstance(self_operations, FrozenJsonObject)
            assert isinstance(self_restore, FrozenJsonObject)
            assert tuple(
                self_operations[operation].get("disposition")
                for operation in OPERATIONS
            ) == tuple(
                operations[operation].get("disposition") for operation in OPERATIONS
            )
            assert self_restore.get("native_update_control") == restore.get(
                "native_update_control"
            )

        controls = sorted(
            {
                identity
                for group in family_groups
                for identity in group.controlled_equipment_identities
            }
        )
        manager = (
            "standalone_skills"
            if kind == "standalone_skill"
            else "direct_mcp"
            if kind == "direct_mcp"
            else harness
        )
        manager_evidence: dict[str, object] = {
            "manager": manager,
            "manager_version": "test-read-only-v1",
            "observation_source": "fake read-only adapter",
        }
        manager_evidence["evidence_digest"] = canonical_json_sha256(manager_evidence)
        operation_support: dict[str, object] = {}
        for operation in OPERATIONS:
            disposition_record = operations[operation]
            assert isinstance(disposition_record, FrozenJsonObject)
            disposition = disposition_record.get("disposition")
            operation_support[operation] = (
                {
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
                if operation == "inspect"
                else _mutation_support(disposition)
            )
        native_control = restore.get("native_update_control")
        suppression = operation_support["suppress_native_update"]
        assert isinstance(suppression, dict)
        capability_record: dict[str, object] = {
            "contract_version": "adapter-contract-v1",
            "capability_identity": f"capability:{harness}/{kind}",
            "adapter_identity": f"adapter:test-read-only/{harness}/{kind}",
            "adapter_version": "1.0.0",
            "harness": harness,
            "provider_match": _provider_match(provider, harness),
            "manager_version_evidence": manager_evidence,
            "surface_identity_rule": {
                "rule": "route_and_equipment_identity",
                "version": 1,
            },
            "operation_support": operation_support,
            "component_control_support": {
                "mode": "automated" if controls else "unavailable",
                "selector_granularity": "equipment_identity",
                "supported_equipment_identities": controls,
                "supported_states": ["enabled", "disabled"] if controls else [],
                "mutation_boundary": "selected_component" if controls else "none",
            },
            "native_update_support": {
                "native_update_control": native_control,
                "version_observation": "automated",
                "baseline_comparison": "automated",
                "suppression": dict(suppression),
                "suppression_scope": (
                    "manager" if suppression.get("mode") != "unavailable" else "none"
                ),
            },
            "record_versions": {
                "observe_request": "adapter-contract-v1",
                "prepare_request": "adapter-contract-v1",
                "prepared_state_facts": "adapter-contract-v1",
                "runtime_observation": "adapter-contract-v1",
                "planned_action": "adapter-contract-v1",
                "mutation_receipt": "adapter-contract-v1",
                "captured_state": "agent-equipment-captured-state/v1",
                "adapter_manifest_set": "agent-equipment-preparation-adapter-manifest-set/v1",
            },
            "automated_control_owners": ["reconciler_owned"],
        }
        capability_record["capability_digest"] = canonical_json_sha256(
            capability_record
        )
        capability_records.append(capability_record)

    capability_records.sort(
        key=lambda record: (
            record["harness"],
            record["provider_match"]["kind"],  # type: ignore[index]
            record["capability_identity"],
        )
    )
    discovery = admit_capability_discovery(
        {
            "record_type": "CapabilityDiscovery",
            "result": {"status": "ok", "records": capability_records},
        }
    )
    assert isinstance(discovery, CapabilityDiscovery), discovery

    requests: list[ObserveRequest] = []
    observations: dict[str, dict[str, object]] = {}
    candidate_identity = f"candidate:{manifest.digest}"
    active_count = len(active_groups)
    for index, group in enumerate(groups):
        capability = _matching_capability(group, discovery.records)
        assert capability is not None
        request_identity = f"request:status-{index:03d}"
        identities = sorted(
            set(group.equipment_identities) | set(group.controlled_equipment_identities)
        )
        surface_scope = [
            f"surface:{group.route_identity}/{identity}" for identity in identities
        ]
        request_record = {
            "contract_version": "adapter-contract-v1",
            "request_identity": request_identity,
            "correlation_identity": "correlation:status-read-only",
            "command": command,
            "purpose": "inventory",
            "candidate_identity": candidate_identity,
            "implementation_manifest_digest": manifest.digest,
            "catalog_digest": validated.catalog.digest,
            "lock_digest": validated.lock.digest,
            "plan_digest": None,
            "capability_identity": capability.capability_identity,
            "capability_digest": capability.capability_digest,
            "manager_version_evidence_digest": (
                capability.manager_version_evidence_digest
            ),
            "harness": group.harness,
            "route_identity": group.route_identity,
            "route_digest": canonical_json_sha256(group.route),
            "route_record": thaw_json(group.route),
            "equipment_identities": list(group.equipment_identities),
            "controlled_equipment_identities": list(
                group.controlled_equipment_identities
            ),
            "activation_group": group.activation_group,
            "surface_scope": surface_scope,
            "secret_references": thaw_json(group.route)["secret_references"],
            "expected_state_digest": None,
        }
        request = admit_observe_request(
            {"record_type": "ObserveRequest", "record": request_record}
        )
        assert isinstance(request, ObserveRequest), request
        requests.append(request)

        retiring = index >= active_count
        route_restore = group.route.get("restore")
        assert isinstance(route_restore, FrozenJsonObject)
        native_control = route_restore.get("native_update_control")
        reviewed_baseline = route_restore.get("reviewed_baseline")
        native_rolling = route_restore.get("class") == "native_rolling"
        normalized_state = {
            "route_presence": "present" if retiring else "absent",
            "enablement": "enabled" if retiring else "disabled",
            "configuration": {"status": "unknown"},
            "component_states": [
                {"equipment_identity": identity, "state": "disabled"}
                for identity in group.controlled_equipment_identities
            ],
            "observed_version": (
                {"status": "observed", "value": reviewed_baseline}
                if native_rolling and retiring and type(reviewed_baseline) is str
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
                if retiring
                else {"status": "route_absent"}
            ),
            "native_update_control": native_control,
            "native_update_suppression_state": (
                "not_applicable"
                if native_control == "not_applicable"
                else "unavailable"
                if native_control == "unsuppressible"
                else "unknown"
            ),
            "manager_drift": (
                {
                    "status": "none",
                    "reviewed_baseline": reviewed_baseline,
                    "observation_source": route_restore.get("observation_source"),
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
        observations[request_identity] = {
            "record_type": "RuntimeObservation",
            "record": {
                **{
                    field: request_record[field]
                    for field in (
                        "contract_version",
                        "request_identity",
                        "correlation_identity",
                        "candidate_identity",
                        "implementation_manifest_digest",
                        "catalog_digest",
                        "lock_digest",
                        "plan_digest",
                        "capability_identity",
                        "capability_digest",
                        "manager_version_evidence_digest",
                        "harness",
                        "route_identity",
                        "route_digest",
                        "equipment_identities",
                        "controlled_equipment_identities",
                        "activation_group",
                        "surface_scope",
                    )
                },
                "control_owner": group.route.get("control_owner"),
                "observed_at": "2026-08-12T15:00:00Z",
                "result": {
                    "status": "ok",
                    "normalized_state": normalized_state,
                    "surface_evidence": [
                        {
                            "kind": "surface",
                            "identity": identity,
                            "digest": "sha256:" + "7" * 64,
                        }
                        for identity in surface_scope
                    ],
                    "captured_state": {"status": "not_applicable"},
                    "state_digest": state_digest,
                },
            },
        }

    class Adapter:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.observations = observations

        def capabilities(self) -> object:
            self.calls.append("capabilities")
            return discovery

        def observe(self, request: ObserveRequest) -> object:
            self.calls.append(f"observe:{request.request_identity}")
            return observations[request.request_identity]

        def apply(self, *_: object) -> object:
            raise AssertionError("read-only status invoked mutation")

    adapter = Adapter()
    return (adapter,), tuple(requests), adapter


def installed_manifest() -> InstalledImplementationManifest:
    files = tuple(
        InstalledFile(path, f"sha256:{index:064x}")
        for index, path in enumerate(_INSTALLED_IMPLEMENTATION_PATHS, start=1)
    )
    runtime_digest = "sha256:" + "f" * 64
    schema_version = "agent-equipment-installed-implementation/v1"
    runtime_identity = "cpython:3.12.8"
    return InstalledImplementationManifest(
        schema_version=schema_version,
        runtime_identity=runtime_identity,
        runtime_executable_digest=runtime_digest,
        files=files,
        digest=_installed_implementation_digest(
            schema_version,
            runtime_identity,
            runtime_digest,
            files,
        ),
    )


def _rewrite_request(
    request: ObserveRequest,
    **changes: object,
) -> ObserveRequest:
    document = thaw_json(request.document)
    assert isinstance(document, dict)
    document.update(changes)
    frozen = freeze_json(document)
    assert isinstance(frozen, FrozenJsonObject)
    return ObserveRequest(
        document=frozen,
        request_identity=request.request_identity,
        capability_identity=request.capability_identity,
    )


def _install_reviewed_config(root: Path) -> Path:
    home = root.resolve(strict=True) / "reviewed home"
    installed_config = home / ".config/agent-equipment"
    installed_config.mkdir(parents=True)
    shutil.copyfile(CATALOG_PATH, installed_config / "catalog-v1.json")
    shutil.copyfile(LOCK_PATH, installed_config / "lock-v1.json")
    return home


class StatusCliTests(unittest.TestCase):
    def test_exact_status_ignores_xdg_and_resolves_reviewed_home_inputs_read_only(
        self,
    ) -> None:
        manifest = installed_manifest()
        adapters: list[ReadOnlyAdapter] = []

        def runtime_inputs(
            validated: ValidatedCatalogLock,
            received_manifest: InstalledImplementationManifest,
        ) -> tuple[tuple[ReadOnlyAdapter, ...], tuple[ObserveRequest, ...]]:
            registered, requests, adapter = _fake_runtime_inputs(
                validated,
                received_manifest,
                command="status",
            )
            adapters.append(adapter)
            return registered, requests

        outputs: list[str] = []
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary).resolve(strict=True)
            home = temporary_root / "reviewed home"
            installed_config = home / ".config/agent-equipment"
            installed_config.mkdir(parents=True)
            shutil.copyfile(CATALOG_PATH, installed_config / "catalog-v1.json")
            shutil.copyfile(LOCK_PATH, installed_config / "lock-v1.json")
            for _ in range(2):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with (
                    patch.dict(
                        os.environ,
                        {
                            "HOME": str(home),
                            "XDG_CONFIG_HOME": str(temporary_root / "hostile"),
                        },
                    ),
                    patch.object(
                        agent_equipment,
                        "_status_runtime_inputs",
                        side_effect=runtime_inputs,
                    ),
                    patch.object(sys, "argv", ["agent-equipment", "status"]),
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                ):
                    status = agent_equipment.main(manifest)

                self.assertEqual(status, 0, stderr.getvalue())
                self.assertEqual(stderr.getvalue(), "")
                outputs.append(stdout.getvalue())

        self.assertEqual(outputs[0], outputs[1])
        report = json.loads(outputs[0])
        self.assertEqual(report["command"], "status")
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["implementation_manifest_digest"], manifest.digest)
        resolution = report["resolution"]
        self.assertEqual(resolution["command"], "status")
        self.assertEqual(resolution["diagnostics"], [])
        self.assertEqual(len(resolution["coverage"]), 132)
        self.assertIsNotNone(resolution["candidate_plan"])
        self.assertIsNone(resolution["mutation_plan"])
        self.assertEqual(len(adapters), 2)
        for adapter in adapters:
            calls = adapter.calls  # type: ignore[attr-defined]
            self.assertEqual(calls[0], "capabilities")
            self.assertEqual(len(calls), 40)
            self.assertTrue(all(call.startswith("observe:") for call in calls[1:]))

    def test_apply_or_verification_request_is_rejected_before_adapter_calls(
        self,
    ) -> None:
        def runtime_inputs_for(
            changes: dict[str, object],
            adapters: list[ReadOnlyAdapter],
        ) -> Callable[
            [ValidatedCatalogLock, InstalledImplementationManifest],
            tuple[tuple[ReadOnlyAdapter, ...], tuple[ObserveRequest, ...]],
        ]:
            def runtime_inputs(
                validated: ValidatedCatalogLock,
                received_manifest: InstalledImplementationManifest,
            ) -> tuple[tuple[ReadOnlyAdapter, ...], tuple[ObserveRequest, ...]]:
                registered, requests, adapter = _fake_runtime_inputs(
                    validated,
                    received_manifest,
                )
                adapters.append(adapter)
                foreign = _rewrite_request(requests[0], **changes)
                return registered, (foreign, *requests[1:])

            return runtime_inputs

        cases: dict[str, dict[str, object]] = {
            "apply": {
                "command": "apply",
                "plan_digest": "sha256:" + "a" * 64,
            },
            "verification": {
                "purpose": "verify_post_state",
                "plan_digest": "sha256:" + "a" * 64,
                "expected_state_digest": "sha256:" + "b" * 64,
            },
        }
        for case, changes in cases.items():
            with self.subTest(case=case):
                manifest = installed_manifest()
                adapters: list[ReadOnlyAdapter] = []
                stdout = io.StringIO()
                with tempfile.TemporaryDirectory() as temporary:
                    home = _install_reviewed_config(Path(temporary))
                    with (
                        patch.dict(os.environ, {"HOME": str(home)}),
                        patch.object(
                            agent_equipment,
                            "_status_runtime_inputs",
                            side_effect=runtime_inputs_for(changes, adapters),
                        ),
                        patch.object(sys, "argv", ["agent-equipment", "status"]),
                        redirect_stdout(stdout),
                    ):
                        status = agent_equipment.main(manifest)

                self.assertEqual(status, 69)
                self.assertEqual(len(adapters), 1)
                self.assertEqual(
                    adapters[0].calls,  # type: ignore[attr-defined]
                    [],
                )

    def test_foreign_manifest_request_is_rejected_before_adapter_calls(self) -> None:
        manifest = installed_manifest()
        adapters: list[ReadOnlyAdapter] = []

        def runtime_inputs(
            validated: ValidatedCatalogLock,
            received_manifest: InstalledImplementationManifest,
        ) -> tuple[tuple[ReadOnlyAdapter, ...], tuple[ObserveRequest, ...]]:
            registered, requests, adapter = _fake_runtime_inputs(
                validated,
                received_manifest,
            )
            adapters.append(adapter)
            foreign = _rewrite_request(
                requests[0],
                implementation_manifest_digest="sha256:" + "0" * 64,
            )
            return registered, (foreign, *requests[1:])

        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            home = _install_reviewed_config(Path(temporary))
            with (
                patch.dict(os.environ, {"HOME": str(home)}),
                patch.object(
                    agent_equipment,
                    "_status_runtime_inputs",
                    side_effect=runtime_inputs,
                ),
                patch.object(sys, "argv", ["agent-equipment", "status"]),
                redirect_stdout(stdout),
            ):
                status = agent_equipment.main(manifest)

        self.assertEqual(status, 69)
        self.assertEqual(len(adapters), 1)
        self.assertEqual(adapters[0].calls, [])  # type: ignore[attr-defined]

    def test_foreign_desired_state_and_mixed_run_identities_precede_adapters(
        self,
    ) -> None:
        def runtime_inputs_for(
            field: str,
            value: str,
            adapters: list[ReadOnlyAdapter],
        ) -> Callable[
            [ValidatedCatalogLock, InstalledImplementationManifest],
            tuple[tuple[ReadOnlyAdapter, ...], tuple[ObserveRequest, ...]],
        ]:
            def runtime_inputs(
                validated: ValidatedCatalogLock,
                received_manifest: InstalledImplementationManifest,
            ) -> tuple[tuple[ReadOnlyAdapter, ...], tuple[ObserveRequest, ...]]:
                registered, requests, adapter = _fake_runtime_inputs(
                    validated,
                    received_manifest,
                )
                adapters.append(adapter)
                foreign = _rewrite_request(requests[0], **{field: value})
                return registered, (foreign, *requests[1:])

            return runtime_inputs

        cases = {
            "catalog_digest": "sha256:" + "3" * 64,
            "lock_digest": "sha256:" + "4" * 64,
            "candidate_identity": "candidate:foreign",
            "correlation_identity": "correlation:foreign",
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                manifest = installed_manifest()
                adapters: list[ReadOnlyAdapter] = []

                stdout = io.StringIO()
                with tempfile.TemporaryDirectory() as temporary:
                    home = _install_reviewed_config(Path(temporary))
                    with (
                        patch.dict(os.environ, {"HOME": str(home)}),
                        patch.object(
                            agent_equipment,
                            "_status_runtime_inputs",
                            side_effect=runtime_inputs_for(field, value, adapters),
                        ),
                        patch.object(sys, "argv", ["agent-equipment", "status"]),
                        redirect_stdout(stdout),
                    ):
                        status = agent_equipment.main(manifest)

                self.assertEqual(status, 69)
                self.assertEqual(len(adapters), 1)
                self.assertEqual(adapters[0].calls, [])  # type: ignore[attr-defined]

    def test_empty_private_registry_never_reaches_the_collector(self) -> None:
        manifest = installed_manifest()
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            home = _install_reviewed_config(Path(temporary))
            with (
                patch.dict(os.environ, {"HOME": str(home)}),
                patch.object(
                    agent_equipment,
                    "collect_runtime_inventory",
                    side_effect=AssertionError("empty registry reached collector"),
                ) as collector,
                patch.object(sys, "argv", ["agent-equipment", "status"]),
                redirect_stdout(stdout),
            ):
                status = agent_equipment.main(manifest)

        self.assertEqual(status, 69)
        collector.assert_not_called()

    def test_untyped_request_set_is_rejected_before_adapter_calls(self) -> None:
        manifest = installed_manifest()
        adapters: list[ReadOnlyAdapter] = []

        def runtime_inputs(
            validated: ValidatedCatalogLock,
            received_manifest: InstalledImplementationManifest,
        ) -> object:
            registered, _, adapter = _fake_runtime_inputs(
                validated,
                received_manifest,
            )
            adapters.append(adapter)
            return registered, (object(),)

        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            home = _install_reviewed_config(Path(temporary))
            with (
                patch.dict(os.environ, {"HOME": str(home)}),
                patch.object(
                    agent_equipment,
                    "_status_runtime_inputs",
                    side_effect=runtime_inputs,
                ),
                patch.object(sys, "argv", ["agent-equipment", "status"]),
                redirect_stdout(stdout),
            ):
                status = agent_equipment.main(manifest)

        self.assertEqual(status, 69)
        self.assertEqual(len(adapters), 1)
        self.assertEqual(adapters[0].calls, [])  # type: ignore[attr-defined]

    def test_status_inventory_request_may_bind_an_expected_state_digest(self) -> None:
        manifest = installed_manifest()

        def runtime_inputs(
            validated: ValidatedCatalogLock,
            received_manifest: InstalledImplementationManifest,
        ) -> tuple[tuple[ReadOnlyAdapter, ...], tuple[ObserveRequest, ...]]:
            registered, requests, adapter = _fake_runtime_inputs(
                validated,
                received_manifest,
            )
            observations = adapter.observations  # type: ignore[attr-defined]
            first = requests[0]
            result = observations[first.request_identity]["record"]["result"]
            assert isinstance(result, dict)
            state_digest = result["state_digest"]
            bound = _rewrite_request(first, expected_state_digest=state_digest)
            return registered, (bound, *requests[1:])

        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            home = _install_reviewed_config(Path(temporary))
            with (
                patch.dict(os.environ, {"HOME": str(home)}),
                patch.object(
                    agent_equipment,
                    "_status_runtime_inputs",
                    side_effect=runtime_inputs,
                ),
                patch.object(sys, "argv", ["agent-equipment", "status"]),
                redirect_stdout(stdout),
            ):
                status = agent_equipment.main(manifest)

        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "ok")

    def test_status_fails_closed_with_one_stable_read_only_diagnostic(self) -> None:
        manifest = installed_manifest()
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(
                os.environ,
                {"HOME": str(Path(temporary).resolve(strict=True))},
            ),
            patch.object(sys, "argv", ["agent-equipment", "status"]),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = agent_equipment.main(manifest)

        self.assertEqual(status, 69)
        self.assertEqual(stderr.getvalue(), "")
        report = json.loads(stdout.getvalue())
        self.assertEqual(
            report,
            {
                "command": "status",
                "diagnostics": [
                    {
                        "code": "STATUS_RUNTIME_UNAVAILABLE",
                        "message": "Read-only status inputs are unavailable.",
                    }
                ],
                "implementation_manifest_digest": manifest.digest,
                "status": "error",
            },
        )
        self.assertEqual(
            stdout.getvalue(),
            json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n",
        )

    def test_empty_registry_fails_closed_after_reviewed_input_load(self) -> None:
        manifest = installed_manifest()
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve(strict=True)
            installed_config = home / ".config/agent-equipment"
            installed_config.mkdir(parents=True)
            shutil.copyfile(CATALOG_PATH, installed_config / "catalog-v1.json")
            shutil.copyfile(LOCK_PATH, installed_config / "lock-v1.json")
            with (
                patch.dict(os.environ, {"HOME": str(home)}),
                patch.object(sys, "argv", ["agent-equipment", "status"]),
                redirect_stdout(stdout),
            ):
                status = agent_equipment.main(manifest)

        self.assertEqual(status, 69)
        self.assertEqual(
            json.loads(stdout.getvalue())["diagnostics"],
            [
                {
                    "code": "STATUS_RUNTIME_UNAVAILABLE",
                    "message": "Read-only status inputs are unavailable.",
                }
            ],
        )

    def test_status_redacts_system_exit_from_the_private_adapter_registry(self) -> None:
        manifest = installed_manifest()
        canary = "gh" + "p_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve(strict=True)
            installed_config = home / ".config/agent-equipment"
            installed_config.mkdir(parents=True)
            shutil.copyfile(CATALOG_PATH, installed_config / "catalog-v1.json")
            shutil.copyfile(LOCK_PATH, installed_config / "lock-v1.json")
            with (
                patch.dict(os.environ, {"HOME": str(home)}),
                patch.object(
                    agent_equipment,
                    "_status_runtime_inputs",
                    side_effect=SystemExit(canary),
                ),
                patch.object(sys, "argv", ["agent-equipment", "status"]),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                status = agent_equipment.main(manifest)

        self.assertEqual(status, 69)
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn(canary, stdout.getvalue())
        self.assertEqual(
            json.loads(stdout.getvalue())["diagnostics"][0]["code"],
            "STATUS_RUNTIME_UNAVAILABLE",
        )

    def test_cli_rejects_mutation_commands_and_authority_arguments_without_echo(
        self,
    ) -> None:
        manifest = installed_manifest()
        canary = "ghp_" + "A" * 32

        rejected_arguments = (
            ["apply", "--authorization", canary],
            ["compensate", "--authorization", canary],
            ["status", "--authorization", canary],
            ["audit"],
            ["import"],
            ["adopt"],
        )
        for arguments in rejected_arguments:
            with self.subTest(arguments=arguments[:-1]):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with (
                    patch.object(
                        sys,
                        "argv",
                        ["agent-equipment", *arguments],
                    ),
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                ):
                    status = agent_equipment.main(manifest)

                self.assertEqual(status, 64)
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(
                    stderr.getvalue(),
                    "agent-equipment: invalid command or arguments\n",
                )
                self.assertNotIn(canary, stderr.getvalue())

    def test_status_seam_accepts_only_an_immutable_typed_resolution(self) -> None:
        manifest = installed_manifest()
        resolution = freeze_json(
            {
                "diagnostics": [],
                "operation_matrix": [],
                "overlays": [],
                "plan": None,
                "provider_selections": [],
            }
        )
        self.assertIsInstance(resolution, FrozenJsonObject)
        assert isinstance(resolution, FrozenJsonObject)

        status, report = agent_equipment._status_report(  # type: ignore[attr-defined]
            manifest,
            resolution=resolution,
        )

        self.assertEqual(status, 0)
        self.assertEqual(
            thaw_json(report),
            {
                "command": "status",
                "implementation_manifest_digest": manifest.digest,
                "resolution": thaw_json(resolution),
                "status": "ok",
            },
        )
        with self.assertRaises(TypeError):
            agent_equipment._status_report(  # type: ignore[attr-defined]
                manifest,
                resolution={"diagnostics": []},
            )

    def test_status_seam_redacts_a_literal_credential_before_rendering(self) -> None:
        manifest = installed_manifest()
        canary = "sk-" + "x" * 32
        resolution = freeze_json(
            {
                "diagnostics": [],
                "provider_selections": [{"api_key": canary}],
            }
        )
        self.assertIsInstance(resolution, FrozenJsonObject)
        assert isinstance(resolution, FrozenJsonObject)

        status, report = agent_equipment._status_report(  # type: ignore[attr-defined]
            manifest,
            resolution=resolution,
        )

        self.assertEqual(status, 65)
        self.assertEqual(
            thaw_json(report),
            {
                "command": "status",
                "diagnostics": [
                    {
                        "code": "STATUS_SECRET_MATERIAL",
                        "message": "Status resolution contains literal secret material.",
                    }
                ],
                "implementation_manifest_digest": manifest.digest,
                "status": "error",
            },
        )
        self.assertNotIn(canary, repr(thaw_json(report)))

    def test_status_resolution_with_fatal_diagnostics_exits_nonzero(self) -> None:
        manifest = installed_manifest()
        resolution = freeze_json(
            {
                "diagnostics": [
                    {
                        "code": "RUNTIME_OBSERVATION_MISSING",
                        "message": "Runtime inventory is incomplete.",
                    }
                ],
                "mutation_plan": None,
            }
        )
        assert isinstance(resolution, FrozenJsonObject)

        status, report = agent_equipment._status_report(  # type: ignore[attr-defined]
            manifest,
            resolution=resolution,
        )

        self.assertEqual(status, 65)
        rendered = thaw_json(report)
        self.assertEqual(rendered["status"], "error")  # type: ignore[index]
        self.assertEqual(rendered["resolution"], thaw_json(resolution))  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
