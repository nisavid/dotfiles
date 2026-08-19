from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import agent_equipment
from agent_equipment.authoring import (
    AuthoringError,
    CatalogAdditionProposal,
    DiscoveryHarnessBinding,
    DiscoverySelection,
    TargetSelection,
    UnmanagedReport,
)
from agent_equipment.model import (
    _INSTALLED_IMPLEMENTATION_PATHS,
    CatalogLockValidation,
    FrozenJsonObject,
    InstalledFile,
    InstalledImplementationManifest,
    ValidatedCatalogLock,
    _installed_implementation_digest,
    freeze_json,
    thaw_json,
)
from agent_equipment.validator import load_catalog_lock

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = ROOT / "docs/agent-equipment"
V1_DISCOVERY_RECORD_LIMIT = 4_096
V1_DISCOVERY_FIELD_CHARACTER_LIMIT = 4_096
V1_SOURCE_FIELD_CHARACTER_LIMIT = 4_096


def frozen_object(document: object) -> FrozenJsonObject:
    frozen = freeze_json(document)
    if not isinstance(frozen, FrozenJsonObject):
        raise TypeError("fixture must be an object")
    return frozen


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


def validated_pair() -> ValidatedCatalogLock:
    result = load_catalog_lock(
        DOCUMENTS / "initial-catalog.proposed.json",
        DOCUMENTS / "initial-lock.proposed.json",
    )
    if result.model is None:
        raise AssertionError(result.diagnostics)
    return result.model


class AuthoredCommandCliTests(unittest.TestCase):
    def _invoke(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(sys, "argv", ["agent-equipment", *arguments]),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = agent_equipment.main(installed_manifest())
        return status, stdout.getvalue(), stderr.getvalue()

    def test_only_the_five_public_v1_command_grammars_are_recognized(self) -> None:
        for arguments in (
            ("status",),
            ("unmanaged",),
            ("unmanaged", "codex/skill:example/tool"),
            ("add", "codex/skill:example/tool"),
            ("update",),
            ("update", "distribution:example/tools"),
            ("apply",),
        ):
            with self.subTest(arguments=arguments):
                status, stdout, stderr = self._invoke(*arguments)
                self.assertEqual(status, 69)
                self.assertEqual(stderr, "")
                self.assertEqual(json.loads(stdout)["command"], arguments[0])

        for arguments in (
            (),
            ("audit",),
            ("import",),
            ("adopt",),
            ("status", "extra"),
            ("unmanaged", "not-a-target"),
            ("add",),
            ("add", "not-a-target"),
            ("update", "all"),
            ("update", "distribution:one", "distribution:two"),
            ("apply", "authority.json"),
            ("compensate",),
        ):
            with self.subTest(arguments=arguments):
                status, stdout, stderr = self._invoke(*arguments)
                self.assertEqual(status, 64)
                self.assertEqual(stdout, "")
                self.assertEqual(
                    stderr,
                    "agent-equipment: invalid command or arguments\n",
                )

    def test_authored_commands_reject_excess_targets_before_runtime_loading(
        self,
    ) -> None:
        targets = tuple(
            f"codex/skill:example/{index:04d}"
            for index in range(V1_DISCOVERY_RECORD_LIMIT + 1)
        )
        for command in ("unmanaged", "add"):
            with (
                self.subTest(command=command),
                patch.object(
                    agent_equipment,
                    "_run_authored_discovery_command",
                    side_effect=AssertionError("runtime must remain unreachable"),
                ),
            ):
                status, stdout, stderr = self._invoke(command, *targets)
                self.assertEqual(status, 64)
                self.assertEqual(stdout, "")
                self.assertEqual(
                    stderr,
                    "agent-equipment: invalid command or arguments\n",
                )

    def test_authored_commands_enforce_the_exact_target_character_boundary(
        self,
    ) -> None:
        prefix = "codex/skill:"
        exact_target = prefix + "x" * (V1_DISCOVERY_FIELD_CHARACTER_LIMIT - len(prefix))
        oversized_target = exact_target + "x"
        self.assertEqual(len(exact_target), V1_DISCOVERY_FIELD_CHARACTER_LIMIT)
        self.assertEqual(len(oversized_target), V1_DISCOVERY_FIELD_CHARACTER_LIMIT + 1)
        for command in ("unmanaged", "add"):
            report = frozen_object({"command": command})
            with (
                self.subTest(command=command, boundary="exact"),
                patch.object(
                    agent_equipment,
                    "_run_authored_discovery_command",
                    return_value=(0, report),
                ) as operation,
            ):
                status, stdout, stderr = self._invoke(command, exact_target)
                self.assertEqual(status, 0)
                self.assertEqual(json.loads(stdout), {"command": command})
                self.assertEqual(stderr, "")
                operation.assert_called_once_with(
                    command,
                    (exact_target,),
                    installed_manifest(),
                )

            with (
                self.subTest(command=command, boundary="over"),
                patch.object(
                    agent_equipment,
                    "_run_authored_discovery_command",
                    side_effect=AssertionError("runtime must remain unreachable"),
                ),
            ):
                status, stdout, stderr = self._invoke(command, oversized_target)
                self.assertEqual(status, 64)
                self.assertEqual(stdout, "")
                self.assertEqual(
                    stderr,
                    "agent-equipment: invalid command or arguments\n",
                )

    def test_update_enforces_the_exact_selector_character_boundary(self) -> None:
        prefix = "distribution:"
        exact_selector = prefix + "x" * (V1_SOURCE_FIELD_CHARACTER_LIMIT - len(prefix))
        oversized_selector = exact_selector + "x"
        self.assertEqual(len(exact_selector), V1_SOURCE_FIELD_CHARACTER_LIMIT)
        self.assertEqual(len(oversized_selector), V1_SOURCE_FIELD_CHARACTER_LIMIT + 1)
        report = frozen_object({"command": "update"})

        with patch.object(
            agent_equipment,
            "_run_update",
            return_value=(0, report),
        ) as operation:
            status, stdout, stderr = self._invoke("update", exact_selector)

        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout), {"command": "update"})
        self.assertEqual(stderr, "")
        operation.assert_called_once()
        selection = operation.call_args.args[0]
        self.assertIsInstance(selection, FrozenJsonObject)
        self.assertEqual(dict(selection), {"distribution": exact_selector})
        self.assertEqual(operation.call_args.args[1], installed_manifest())

        with patch.object(
            agent_equipment,
            "_run_update",
            return_value=(0, report),
        ) as operation:
            status, stdout, stderr = self._invoke("update", oversized_selector)

        self.assertEqual(status, 64)
        self.assertEqual(stdout, "")
        self.assertEqual(
            stderr,
            "agent-equipment: invalid command or arguments\n",
        )
        operation.assert_not_called()

    def test_cli_accepts_every_catalog_identity_terminal_character(self) -> None:
        for suffix in (".", "_", "/", "-"):
            with self.subTest(kind="equipment", suffix=suffix):
                status, stdout, stderr = self._invoke(
                    "unmanaged",
                    f"codex/skill:example/tool{suffix}",
                )
                self.assertEqual(status, 69)
                self.assertEqual(stderr, "")
                self.assertEqual(json.loads(stdout)["command"], "unmanaged")

            with self.subTest(kind="distribution", suffix=suffix):
                status, stdout, stderr = self._invoke(
                    "update",
                    f"distribution:example/tools{suffix}",
                )
                self.assertEqual(status, 69)
                self.assertEqual(stderr, "")
                self.assertEqual(json.loads(stdout)["command"], "update")

    def test_unmanaged_without_targets_requests_every_target(self) -> None:
        manifest = installed_manifest()
        report = frozen_object({"command": "unmanaged"})
        with patch.object(
            agent_equipment,
            "_run_authored_discovery_command",
            return_value=(0, report),
        ) as operation:
            status, stdout, stderr = self._invoke("unmanaged")

        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout), {"command": "unmanaged"})
        self.assertEqual(stderr, "")
        operation.assert_called_once_with("unmanaged", None, manifest)

    def test_unmanaged_and_add_emit_the_exact_high_level_result(self) -> None:
        base = validated_pair()
        manifest = installed_manifest()
        validation = CatalogLockValidation(base, ())
        target = "codex/skill:example/tool"
        unmanaged_document = frozen_object(
            {
                "command": "unmanaged",
                "catalog_digest": base.catalog.digest,
                "lock_digest": base.lock.digest,
                "discovery_digest": "sha256:" + "1" * 64,
                "records": [],
            }
        )
        unmanaged = UnmanagedReport(
            unmanaged_document,
            (),
            "sha256:" + "1" * 64,
        )
        empty = frozen_object({})
        add_document = frozen_object(
            {
                "command": "add",
                "catalog": {},
                "lock": {},
                "proposal_identity": "sha256:" + "2" * 64,
            }
        )
        addition = CatalogAdditionProposal(
            add_document,
            empty,
            empty,
            "sha256:" + "2" * 64,
        )
        port = object()

        for command, result, function_name in (
            ("unmanaged", unmanaged, "find_unmanaged"),
            ("add", addition, "propose_add"),
        ):
            with self.subTest(command=command):
                binding = DiscoveryHarnessBinding(
                    capability_identity="capability:codex/equipment-discovery",
                    capability_digest="sha256:" + "4" * 64,
                    manager_version_evidence_digest="sha256:" + "5" * 64,
                    harness="codex",
                )
                selection = (
                    DiscoverySelection(
                        candidate_identity="candidate:sha256:" + "6" * 64,
                        implementation_manifest_digest=manifest.digest,
                        bindings=(binding,),
                        targets=(target,),
                    )
                    if command == "unmanaged"
                    else TargetSelection(
                        candidate_identity="candidate:sha256:" + "6" * 64,
                        implementation_manifest_digest=manifest.digest,
                        bindings=(binding,),
                        targets=(target,),
                    )
                )
                with (
                    patch.object(
                        agent_equipment, "load_catalog_lock", return_value=validation
                    ),
                    patch.object(
                        agent_equipment,
                        "_authoring_runtime_inputs",
                        return_value=(selection, port),
                    ) as runtime_inputs,
                    patch.object(
                        agent_equipment,
                        function_name,
                        return_value=result,
                    ) as operation,
                    patch.object(sys, "argv", ["agent-equipment", command, target]),
                    patch.object(sys, "stdout", new_callable=io.StringIO) as stdout,
                ):
                    status = agent_equipment.main(manifest)

                self.assertEqual(status, 0)
                self.assertEqual(
                    json.loads(stdout.getvalue()),
                    thaw_json(result.document),
                )
                runtime_inputs.assert_called_once_with(
                    command,
                    base,
                    manifest,
                    (target,),
                )
                operation.assert_called_once_with(base, selection, port)

    def test_authored_discovery_rejects_foreign_implementation_selection(
        self,
    ) -> None:
        base = validated_pair()
        manifest = installed_manifest()
        validation = CatalogLockValidation(base, ())
        target = "codex/skill:example/tool"
        binding = DiscoveryHarnessBinding(
            capability_identity="capability:codex/equipment-discovery",
            capability_digest="sha256:" + "4" * 64,
            manager_version_evidence_digest="sha256:" + "5" * 64,
            harness="codex",
        )
        for command, selection, function_name in (
            (
                "unmanaged",
                DiscoverySelection(
                    candidate_identity="candidate:sha256:" + "6" * 64,
                    implementation_manifest_digest="sha256:" + "7" * 64,
                    bindings=(binding,),
                    targets=(target,),
                ),
                "find_unmanaged",
            ),
            (
                "add",
                TargetSelection(
                    candidate_identity="candidate:sha256:" + "6" * 64,
                    implementation_manifest_digest="sha256:" + "7" * 64,
                    bindings=(binding,),
                    targets=(target,),
                ),
                "propose_add",
            ),
        ):
            with (
                self.subTest(command=command),
                patch.object(
                    agent_equipment, "load_catalog_lock", return_value=validation
                ),
                patch.object(
                    agent_equipment,
                    "_authoring_runtime_inputs",
                    return_value=(selection, object()),
                ),
                patch.object(
                    agent_equipment,
                    function_name,
                    side_effect=AssertionError("foreign selection must not execute"),
                ) as operation,
            ):
                status, stdout, stderr = self._invoke(command, target)

            self.assertEqual(status, 69)
            self.assertEqual(stderr, "")
            self.assertEqual(
                json.loads(stdout),
                {
                    "command": command,
                    "diagnostics": [
                        {
                            "code": f"{command.upper()}_RUNTIME_UNAVAILABLE",
                            "message": (
                                f"{command.capitalize()} runtime inputs are unavailable."
                            ),
                        }
                    ],
                    "implementation_manifest_digest": manifest.digest,
                    "status": "error",
                },
            )
            operation.assert_not_called()

    def test_update_emits_one_atomic_proposal(self) -> None:
        base = validated_pair()
        manifest = installed_manifest()
        validation = CatalogLockValidation(base, ())
        proposal = frozen_object(
            {
                "schema_version": "update-proposal/v1",
                "command": "update",
                "catalog": {},
                "lock": {},
                "proposal_digest": "sha256:" + "3" * 64,
            }
        )
        resolver = object()
        with (
            patch.object(agent_equipment, "load_catalog_lock", return_value=validation),
            patch.object(
                agent_equipment,
                "_source_resolution_runtime_input",
                return_value=resolver,
            ) as runtime_input,
            patch.object(
                agent_equipment,
                "propose_update",
                return_value=proposal,
            ) as operation,
            patch.object(
                sys,
                "argv",
                ["agent-equipment", "update", "distribution:example/tools"],
            ),
            patch.object(sys, "stdout", new_callable=io.StringIO) as stdout,
        ):
            status = agent_equipment.main(manifest)

        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout.getvalue()), thaw_json(proposal))
        runtime_input.assert_called_once_with(base, manifest)
        operation.assert_called_once()
        selection = operation.call_args.args[1]
        self.assertIsInstance(selection, FrozenJsonObject)
        self.assertEqual(
            dict(selection), {"distribution": "distribution:example/tools"}
        )

    def test_bare_update_selects_complete_membership(self) -> None:
        base = validated_pair()
        validation = CatalogLockValidation(base, ())
        proposal = frozen_object(
            {
                "schema_version": "update-proposal/v1",
                "command": "update",
                "catalog": {},
                "lock": {},
                "proposal_digest": "sha256:" + "3" * 64,
            }
        )
        resolver = object()
        with (
            patch.object(agent_equipment, "load_catalog_lock", return_value=validation),
            patch.object(
                agent_equipment,
                "_source_resolution_runtime_input",
                return_value=resolver,
            ),
            patch.object(
                agent_equipment,
                "propose_update",
                return_value=proposal,
            ) as operation,
        ):
            status, stdout, stderr = self._invoke("update")

        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout), thaw_json(proposal))
        self.assertEqual(stderr, "")
        operation.assert_called_once()
        selection = operation.call_args.args[1]
        self.assertIsInstance(selection, FrozenJsonObject)
        self.assertEqual(dict(selection), {"all": True})

    def test_cli_normalizes_target_order_and_rejects_duplicates(self) -> None:
        manifest = installed_manifest()
        report = frozen_object(
            {
                "command": "add",
                "diagnostics": [
                    {
                        "code": "ADD_RUNTIME_UNAVAILABLE",
                        "message": "Add runtime inputs are unavailable.",
                    }
                ],
                "implementation_manifest_digest": manifest.digest,
                "status": "error",
            }
        )
        alpha = "codex/skill:example/alpha"
        zeta = "codex/skill:example/zeta"
        with (
            patch.object(
                agent_equipment,
                "_run_authored_discovery_command",
                return_value=(69, report),
            ) as operation,
            patch.object(sys, "argv", ["agent-equipment", "add", zeta, alpha]),
            patch.object(sys, "stdout", new_callable=io.StringIO),
        ):
            status = agent_equipment.main(manifest)

        self.assertEqual(status, 69)
        operation.assert_called_once_with("add", (alpha, zeta), manifest)

        with (
            patch.object(
                agent_equipment,
                "_run_authored_discovery_command",
            ) as duplicate_operation,
            patch.object(sys, "argv", ["agent-equipment", "add", alpha, alpha]),
            patch.object(sys, "stderr", new_callable=io.StringIO) as stderr,
        ):
            status = agent_equipment.main(manifest)

        self.assertEqual(status, 64)
        duplicate_operation.assert_not_called()
        self.assertEqual(
            stderr.getvalue(),
            "agent-equipment: invalid command or arguments\n",
        )

    def test_authoring_errors_reject_literal_secret_messages(self) -> None:
        canary = "gh" + "p_" + "A" * 32
        with self.assertRaisesRegex(
            ValueError,
            "^authoring errors must not contain literal secrets$",
        ):
            AuthoringError("ADD_AUTHORING_POLICY_REQUIRED", canary)

    def test_authored_errors_and_secret_material_fail_closed_without_echo(self) -> None:
        base = validated_pair()
        manifest = installed_manifest()
        validation = CatalogLockValidation(base, ())
        canary = "gh" + "p_" + "A" * 32
        forged_error = object.__new__(AuthoringError)
        object.__setattr__(
            forged_error,
            "code",
            "ADD_AUTHORING_POLICY_REQUIRED",
        )
        object.__setattr__(forged_error, "message", canary)
        binding = DiscoveryHarnessBinding(
            capability_identity="capability:codex/equipment-discovery",
            capability_digest="sha256:" + "4" * 64,
            manager_version_evidence_digest="sha256:" + "5" * 64,
            harness="codex",
        )
        selection = TargetSelection(
            candidate_identity="candidate:sha256:" + "6" * 64,
            implementation_manifest_digest=manifest.digest,
            bindings=(binding,),
            targets=("codex/skill:example/tool",),
        )
        for result, expected_code in (
            (
                forged_error,
                "ADD_AUTHORING_POLICY_REQUIRED",
            ),
            (
                frozen_object({"command": "add", "proposal": canary}),
                "AUTHORED_RESULT_SECRET_MATERIAL",
            ),
        ):
            with self.subTest(expected_code=expected_code):
                with (
                    patch.object(
                        agent_equipment, "load_catalog_lock", return_value=validation
                    ),
                    patch.object(
                        agent_equipment,
                        "_authoring_runtime_inputs",
                        return_value=(selection, object()),
                    ),
                    patch.object(agent_equipment, "propose_add", return_value=result),
                ):
                    status, stdout, stderr = self._invoke(
                        "add",
                        "codex/skill:example/tool",
                    )

                self.assertEqual(status, 65)
                self.assertNotIn(canary, stdout)
                self.assertNotIn(canary, stderr)
                self.assertEqual(stderr, "")
                self.assertEqual(
                    json.loads(stdout)["diagnostics"][0]["code"],
                    expected_code,
                )


if __name__ == "__main__":
    unittest.main()
