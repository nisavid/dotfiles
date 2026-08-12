from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "docs/agent-equipment/captured-state-v1.schema.json"
PLAN_ACTION_SET_SCHEMA = (
    ROOT / "docs/agent-equipment/plan-action-set-v1.schema.json"
)
FIXTURE = (
    ROOT / "tests/fixtures/agent-equipment/schema/valid-captured-state.json"
)
PLAN_ACTION_SET_FIXTURE = (
    ROOT / "tests/fixtures/agent-equipment/schema/valid-plan-action-set.json"
)
SPEC = importlib.util.spec_from_file_location(
    "agent_equipment_captured_state",
    ROOT / "scripts/agent_equipment_captured_state.py",
)
assert SPEC is not None and SPEC.loader is not None
CAPTURED_STATE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CAPTURED_STATE
SPEC.loader.exec_module(CAPTURED_STATE)


CAPABILITY_BINDING = {
    "capability_identity": "capability:claude-native-plugin-v1",
    "capability_digest": "sha256:" + "3" * 64,
    "manager_version_evidence_digest": "sha256:" + "4" * 64,
}
CANDIDATE_IDENTITY = "candidate:fixture/controller-v1"
IMPLEMENTATION_MANIFEST_DIGEST = "sha256:" + "a" * 64
PLUGIN_INSTALLATION_TARGET = {
    "target_identity": "target:sha256:" + "0" * 64,
    "write_surface_identity": (
        "surface:route:fixture/claude-plugin/plugin:fixture/example"
    ),
    "surface_kind": "plugin_installation",
    "locator": {
        "manager": "claude",
        "native_identity": "example@fixture",
        "scope": "user",
    },
}
PLUGIN_INSTALLATION_TARGET["target_identity"] = (
    CAPTURED_STATE.write_target_identity(PLUGIN_INSTALLATION_TARGET)
)
CLAUDE_SKILL_TARGET = {
    "target_identity": "target:sha256:" + "0" * 64,
    "write_surface_identity": (
        "surface:route:fixture/claude-plugin/skill:fixture/example"
    ),
    "surface_kind": "claude_skill_entry",
    "equipment_identity": "skill:fixture/example",
    "locator": {"path": "~/.claude/skills/example"},
}
CLAUDE_SKILL_TARGET["target_identity"] = CAPTURED_STATE.write_target_identity(
    CLAUDE_SKILL_TARGET
)
PLAN_ACTION_PAYLOAD = {
    "action_identity": (
        "action:sha256:8b668d90aa623f6dcb459a029ee8af002d434a3a4ba3991c61c158a135268a35"
    ),
    "ordinal": 0,
    "candidate_identity": CANDIDATE_IDENTITY,
    "implementation_manifest_digest": IMPLEMENTATION_MANIFEST_DIGEST,
    "catalog_digest": "sha256:" + "0" * 64,
    "lock_digest": "sha256:" + "1" * 64,
    "plan_digest": "sha256:" + "2" * 64,
    "capability_identity": CAPABILITY_BINDING["capability_identity"],
    "capability_digest": CAPABILITY_BINDING["capability_digest"],
    "manager_version_evidence_digest": CAPABILITY_BINDING[
        "manager_version_evidence_digest"
    ],
    "adapter_identity": "adapter:fixture/claude-plugin",
    "adapter_version": "1.0.0",
    "harness": "claude",
    "route_identity": "route:fixture/claude-plugin",
    "route_digest": "sha256:" + "8" * 64,
    "provider": {
        "kind": "native_plugin",
        "manager": "claude",
        "plugin_id": "example@fixture",
        "scope": "user",
    },
    "equipment_identities": [
        "plugin:fixture/example",
        "skill:fixture/example",
    ],
    "controlled_equipment_identities": [],
    "activation_group": "activation:fixture/claude-plugin",
    "surface_scope": [
        "surface:route:fixture/claude-plugin/plugin:fixture/example",
        "surface:route:fixture/claude-plugin/skill:fixture/example",
    ],
    "write_targets": sorted(
        [
            copy.deepcopy(PLUGIN_INSTALLATION_TARGET),
            copy.deepcopy(CLAUDE_SKILL_TARGET),
        ],
        key=lambda target: target["target_identity"],
    ),
    "operation": "install",
    "operation_disposition": "automated",
    "desired_state": {"route_presence": "present"},
    "desired_state_digest": (
        "sha256:3551741a7b3b074876114f983f07b523d180ab1d82bd088875eb390d1e838ede"
    ),
    "expected_post_state_digest": "sha256:" + "9" * 64,
    "secret_references": [],
    "preconditions": {
        "candidate_identity": CANDIDATE_IDENTITY,
        "implementation_manifest_digest": IMPLEMENTATION_MANIFEST_DIGEST,
        "catalog_digest": "sha256:" + "0" * 64,
        "lock_digest": "sha256:" + "1" * 64,
        "plan_digest": "sha256:" + "2" * 64,
        "route_digest": "sha256:" + "8" * 64,
        "capability_digest": CAPABILITY_BINDING["capability_digest"],
        "manager_version_evidence_digest": CAPABILITY_BINDING[
            "manager_version_evidence_digest"
        ],
        "adapter_identity": "adapter:fixture/claude-plugin",
        "adapter_version": "1.0.0",
        "control_owner": "reconciler_owned",
        "activation_group": "activation:fixture/claude-plugin",
        "surface_scope": [
            "surface:route:fixture/claude-plugin/plugin:fixture/example",
            "surface:route:fixture/claude-plugin/skill:fixture/example",
        ],
        "prepared_checkpoint_required": True,
        "compare_before_mutate": True,
    },
    "verification_dependencies": [
        {
            "relationship": "canonical_skill_projection",
            "dependency_identity": "dependency:fixture/canonical-skill",
            "write_surface_identity": (
                "surface:route:fixture/claude-plugin/skill:fixture/example"
            ),
            "equipment_identity": "skill:fixture/example",
            "target_locator": {"path": "~/.agents/skills/example"},
        }
    ],
    "compensation": {
        "kind": "restore_captured_pre_state",
        "captured_state_version": "agent-equipment-captured-state/v1",
    },
}
PLAN_ACTION_DIGEST = (
    "sha256:fcf1a7236d2e4f41dc1b427e74f8551ad1230a2362c3ed404e1f1cdd8d6091c2"
)
FORGED_ACTION_IDENTITY = "action:sha256:" + "f" * 64
PLAN_ACTION_SET_DIGEST = (
    "sha256:9bb22725fddc7dc0487f33b92c589b1ab2214b4632ee7ac3f958f5f49daeebb7"
)
EMPTY_PLAN_ACTION_SET_DIGEST = (
    "sha256:c80f8f66c4280ad58da22bcf3793b4be64a96d9641dc85e288413751e6e5416e"
)


def authoritative_plan_action_set() -> dict[str, object]:
    return {
        "schema_version": "agent-equipment-plan-action-set/v1",
        "candidate_identity": CANDIDATE_IDENTITY,
        "implementation_manifest_digest": IMPLEMENTATION_MANIFEST_DIGEST,
        "plan_digest": "sha256:" + "2" * 64,
        "actions": [
            {
                "action_payload": copy.deepcopy(PLAN_ACTION_PAYLOAD),
                "action_digest": PLAN_ACTION_DIGEST,
            }
        ],
        "action_set_digest": PLAN_ACTION_SET_DIGEST,
    }


def empty_authoritative_plan_action_set() -> dict[str, object]:
    return {
        "schema_version": "agent-equipment-plan-action-set/v1",
        "candidate_identity": CANDIDATE_IDENTITY,
        "implementation_manifest_digest": IMPLEMENTATION_MANIFEST_DIGEST,
        "plan_digest": "sha256:" + "2" * 64,
        "actions": [],
        "action_set_digest": EMPTY_PLAN_ACTION_SET_DIGEST,
    }


def rehash_authoritative_plan_action_set(
    authority: dict[str, object],
) -> None:
    for evidence in authority["actions"]:
        evidence["action_digest"] = CAPTURED_STATE.plan_action_digest(
            evidence["action_payload"]
        )
    authority["action_set_digest"] = CAPTURED_STATE.plan_action_set_digest(
        authority["candidate_identity"],
        authority["implementation_manifest_digest"],
        authority["plan_digest"],
        authority["actions"],
    )


def validate_document(
    document: object,
    plan_action_set: object | None = None,
) -> tuple[object, ...]:
    authoritative = (
        authoritative_plan_action_set()
        if plan_action_set is None
        else plan_action_set
    )
    return CAPTURED_STATE.validate_captured_state(
        document,
        authoritative,
        expected_candidate_identity=CANDIDATE_IDENTITY,
        expected_implementation_manifest_digest=IMPLEMENTATION_MANIFEST_DIGEST,
    )


def validation_cli_args(
    plan_action_set_path: Path,
    manifest_path: Path,
    *,
    candidate_identity: str = CANDIDATE_IDENTITY,
    implementation_manifest_digest: str = IMPLEMENTATION_MANIFEST_DIGEST,
) -> list[str]:
    return [
        sys.executable,
        str(ROOT / "scripts/agent_equipment_captured_state.py"),
        "--authoritative-plan-actions",
        str(plan_action_set_path),
        "--expected-candidate-identity",
        candidate_identity,
        "--expected-implementation-manifest-digest",
        implementation_manifest_digest,
        str(manifest_path),
    ]


def run_check_jsonschema(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uvx",
            "--from",
            "check-jsonschema==0.35.0",
            "check-jsonschema",
            *arguments,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def valid_document() -> dict[str, object]:
    return {
        "schema_version": "agent-equipment-captured-state/v1",
        "migration_id": "fixture-captured-state",
        "captured_at": "2026-08-12T00:00:00Z",
        "bindings": {
            "candidate_identity": CANDIDATE_IDENTITY,
            "implementation_manifest_digest": IMPLEMENTATION_MANIFEST_DIGEST,
            "catalog_digest": "sha256:" + "0" * 64,
            "lock_digest": "sha256:" + "1" * 64,
            "plan_digest": "sha256:" + "2" * 64,
            "plan_action_set_digest": PLAN_ACTION_SET_DIGEST,
            "capability_bindings": [copy.deepcopy(CAPABILITY_BINDING)],
            "capability_set_digest": (
                "sha256:7a13e2a65f207f4cd99b9d85186bf3b87241befbc11fbfd959c1f925bddfeb41"
            ),
        },
        "provider_routes": [
            {
                "route_id": "route:fixture/claude-plugin",
                "route_digest": "sha256:" + "8" * 64,
                "harness": "claude",
                "equipment_identities": [
                    "plugin:fixture/example",
                    "skill:fixture/example",
                ],
                "controlled_equipment_identities": [],
                "control_owner": "reconciler_owned",
                "provenance_owner": "source:fixture/claude-marketplace",
                "capability_binding": copy.deepcopy(CAPABILITY_BINDING),
                "planned_actions": [
                    {
                        "action_identity": PLAN_ACTION_PAYLOAD["action_identity"],
                        "action_digest": PLAN_ACTION_DIGEST,
                        "write_bindings": sorted(
                            [
                                {
                                    "target_identity": (
                                        PLUGIN_INSTALLATION_TARGET[
                                            "target_identity"
                                        ]
                                    ),
                                    "surface_id": (
                                        "surface:fixture/plugin-installation"
                                    ),
                                },
                                {
                                    "target_identity": CLAUDE_SKILL_TARGET[
                                        "target_identity"
                                    ],
                                    "surface_id": (
                                        "surface:fixture/claude-skill"
                                    ),
                                },
                            ],
                            key=lambda binding: binding["target_identity"],
                        ),
                        "verification_dependency_bindings": [
                            {
                                "dependency_identity": (
                                    "dependency:fixture/canonical-skill"
                                ),
                                "surface_id": (
                                    "surface:fixture/canonical-skill"
                                ),
                            }
                        ],
                    }
                ],
                "restore_evidence": {
                    "restore_class": "native_rolling",
                    "channel": "official-marketplace",
                    "observed_version": {"status": "route_absent"},
                    "observation_source": "claude plugin list",
                    "native_update_control": "unknown",
                    "exact_prior_artifact_restore": False,
                },
                "surface_references": {
                    "installation": {
                        "status": "captured",
                        "surface_id": "surface:fixture/plugin-installation",
                    },
                    "enablement": {"status": "not_applicable"},
                    "projector": {"status": "not_applicable"},
                    "mcp_selections": [],
                    "plugin_selections": [],
                    "skill_entries": [
                        {
                            "status": "captured",
                            "surface_id": "surface:fixture/claude-skill",
                        }
                    ],
                    "canonical_skill_dependencies": [
                        {
                            "status": "captured",
                            "surface_id": "surface:fixture/canonical-skill",
                        }
                    ],
                },
            }
        ],
        "surfaces": [
            {
                "surface_id": "surface:fixture/plugin-installation",
                "kind": "plugin_installation",
                "route_id": "route:fixture/claude-plugin",
                "mutation_policy": "reconciler_owned",
                "provenance": {
                    "classification": "native_manager",
                    "evidence": [
                        {
                            "source": "claude plugin list",
                            "state_digest": "sha256:" + "5" * 64,
                        }
                    ],
                },
                "locator": {
                    "manager": "claude",
                    "native_identity": "example@fixture",
                    "scope": "user",
                },
                "observation": {"installed": False},
                "recovery": {
                    "kind": "native_inverse",
                    "inverse_operation": "remove",
                    "expected_pre_state_digest": PLAN_ACTION_PAYLOAD[
                        "expected_post_state_digest"
                    ],
                },
            },
            {
                "surface_id": "surface:fixture/canonical-skill",
                "kind": "canonical_skill_entry",
                "route_id": "route:fixture/claude-plugin",
                "equipment_identity": "skill:fixture/example",
                "mutation_policy": "forbidden",
                "provenance": {
                    "classification": "unmanaged",
                    "evidence": [
                        {
                            "source": "lstat",
                            "state_digest": "sha256:" + "6" * 64,
                        }
                    ],
                },
                "locator": {"path": "~/.agents/skills/example"},
                "observation": {"entry_type": "absent"},
                "recovery": {"kind": "none", "reason": "verification_only"},
            },
            {
                "surface_id": "surface:fixture/claude-skill",
                "kind": "claude_skill_entry",
                "route_id": "route:fixture/claude-plugin",
                "equipment_identity": "skill:fixture/example",
                "mutation_policy": "reconciler_owned",
                "provenance": {
                    "classification": "catalog_owned_projection",
                    "evidence": [
                        {
                            "source": "lstat",
                            "state_digest": "sha256:" + "7" * 64,
                        }
                    ],
                },
                "locator": {"path": "~/.claude/skills/example"},
                "observation": {"entry_type": "absent"},
                "recovery": {"kind": "none", "reason": "absent_noop"},
            },
        ],
    }


class CapturedStateValidationTest(unittest.TestCase):
    def test_schema_and_fixture_are_valid(self) -> None:
        metaschema = run_check_jsonschema(
            "--check-metaschema",
            str(SCHEMA),
            str(PLAN_ACTION_SET_SCHEMA),
        )
        self.assertEqual(0, metaschema.returncode, metaschema.stdout + metaschema.stderr)

        fixture = run_check_jsonschema("--schemafile", str(SCHEMA), str(FIXTURE))
        self.assertEqual(0, fixture.returncode, fixture.stdout + fixture.stderr)

        plan_action_fixture = run_check_jsonschema(
            "--schemafile",
            str(PLAN_ACTION_SET_SCHEMA),
            str(PLAN_ACTION_SET_FIXTURE),
        )
        self.assertEqual(
            0,
            plan_action_fixture.returncode,
            plan_action_fixture.stdout + plan_action_fixture.stderr,
        )

        captured_document = json.loads(FIXTURE.read_text(encoding="utf-8"))
        plan_action_set = json.loads(
            PLAN_ACTION_SET_FIXTURE.read_text(encoding="utf-8")
        )
        self.assertEqual(
            CAPTURED_STATE.validate_captured_state(
                captured_document,
                plan_action_set,
                expected_candidate_identity=CANDIDATE_IDENTITY,
                expected_implementation_manifest_digest=(
                    IMPLEMENTATION_MANIFEST_DIGEST
                ),
            ),
            (),
        )

    def test_schema_rejects_skill_root_and_ownership_conflation(self) -> None:
        cases: list[dict[str, object]] = []
        fixture_document = json.loads(FIXTURE.read_text(encoding="utf-8"))

        canonical_mutable = copy.deepcopy(fixture_document)
        canonical_mutable["surfaces"][1]["mutation_policy"] = "reconciler_owned"
        cases.append(canonical_mutable)

        canonical_wrong_root = copy.deepcopy(fixture_document)
        canonical_wrong_root["surfaces"][1]["locator"][
            "path"
        ] = "~/.claude/skills/example"
        cases.append(canonical_wrong_root)

        claude_forbidden = copy.deepcopy(fixture_document)
        claude_forbidden["surfaces"][2]["mutation_policy"] = "forbidden"
        cases.append(claude_forbidden)

        claude_wrong_root = copy.deepcopy(fixture_document)
        claude_wrong_root["surfaces"][2]["locator"][
            "path"
        ] = "~/.agents/skills/example"
        cases.append(claude_wrong_root)

        extra_nested_field = copy.deepcopy(fixture_document)
        extra_nested_field["surfaces"][2]["locator"]["unexpected"] = True
        cases.append(extra_nested_field)

        extra_forward_action_field = copy.deepcopy(fixture_document)
        extra_forward_action_field["provider_routes"][0]["planned_actions"][0][
            "unexpected"
        ] = True
        cases.append(extra_forward_action_field)

        invalid_forward_action_digest = copy.deepcopy(fixture_document)
        invalid_forward_action_digest["provider_routes"][0]["planned_actions"][0][
            "action_digest"
        ] = "not-a-digest"
        cases.append(invalid_forward_action_digest)

        invalid_plan_action_set_digest = copy.deepcopy(fixture_document)
        invalid_plan_action_set_digest["bindings"][
            "plan_action_set_digest"
        ] = "not-a-digest"
        cases.append(invalid_plan_action_set_digest)

        self_asserted_plan_evidence = copy.deepcopy(fixture_document)
        self_asserted_plan_evidence["plan_action_evidence"] = []
        cases.append(self_asserted_plan_evidence)

        for surface_index, root in (
            (1, "~/.agents/skills/"),
            (2, "~/.claude/skills/"),
        ):
            for basename in ("", ".", "..", "nested/name", "nested\\name", "nul\0name"):
                invalid_basename = copy.deepcopy(fixture_document)
                invalid_basename["surfaces"][surface_index]["locator"]["path"] = (
                    root + basename
                )
                cases.append(invalid_basename)

        with tempfile.TemporaryDirectory() as directory:
            for index, document in enumerate(cases):
                path = Path(directory) / f"invalid-{index}.json"
                path.write_text(json.dumps(document), encoding="utf-8")
                result = run_check_jsonschema("--schemafile", str(SCHEMA), str(path))
                with self.subTest(index=index):
                    self.assertNotEqual(0, result.returncode)

    def test_skill_paths_reject_traversal_and_platform_separators_semantically(
        self,
    ) -> None:
        for root in ("~/.agents/skills/", "~/.claude/skills/"):
            for basename in ("", ".", "..", "nested/name", "nested\\name", "nul\0name"):
                with self.subTest(root=root, basename=repr(basename)):
                    self.assertFalse(
                        CAPTURED_STATE._is_skill_path(root + basename, root)
                    )

    def test_plan_action_set_schema_is_closed(self) -> None:
        fixture_document = json.loads(
            PLAN_ACTION_SET_FIXTURE.read_text(encoding="utf-8")
        )
        cases: list[dict[str, object]] = []

        extra_top_level = copy.deepcopy(fixture_document)
        extra_top_level["unexpected"] = True
        cases.append(extra_top_level)

        extra_action_field = copy.deepcopy(fixture_document)
        extra_action_field["actions"][0]["action_payload"]["unexpected"] = True
        cases.append(extra_action_field)

        invalid_set_digest = copy.deepcopy(fixture_document)
        invalid_set_digest["action_set_digest"] = "not-a-digest"
        cases.append(invalid_set_digest)

        invalid_action_identity = copy.deepcopy(fixture_document)
        invalid_action_identity["actions"][0]["action_payload"][
            "action_identity"
        ] = "action:not-canonical"
        cases.append(invalid_action_identity)

        for field in (
            "candidate_identity",
            "implementation_manifest_digest",
        ):
            missing_top_binding = copy.deepcopy(fixture_document)
            del missing_top_binding[field]
            cases.append(missing_top_binding)

            missing_action_binding = copy.deepcopy(fixture_document)
            del missing_action_binding["actions"][0]["action_payload"][field]
            cases.append(missing_action_binding)

            missing_precondition_binding = copy.deepcopy(fixture_document)
            del missing_precondition_binding["actions"][0]["action_payload"][
                "preconditions"
            ][field]
            cases.append(missing_precondition_binding)

        selection_without_equipment = copy.deepcopy(fixture_document)
        selection_target = selection_without_equipment["actions"][0][
            "action_payload"
        ]["write_targets"][0]
        selection_target["surface_kind"] = "mcp_selection"
        selection_target["locator"] = {
            "owner": "claude",
            "source": "settings",
            "key_path": ["mcpServers", "context7"],
        }
        selection_target.pop("equipment_identity", None)
        cases.append(selection_without_equipment)

        with tempfile.TemporaryDirectory() as directory:
            for index, document in enumerate(cases):
                path = Path(directory) / f"invalid-plan-action-set-{index}.json"
                path.write_text(json.dumps(document), encoding="utf-8")
                result = run_check_jsonschema(
                    "--schemafile",
                    str(PLAN_ACTION_SET_SCHEMA),
                    str(path),
                )
                with self.subTest(index=index):
                    self.assertNotEqual(0, result.returncode)

    def test_plan_action_projection_represents_secret_safe_mcp_providers(self) -> None:
        stdio = copy.deepcopy(PLAN_ACTION_PAYLOAD)
        stdio["provider"] = {
            "kind": "direct_mcp",
            "server_name": "context7",
            "transport": "stdio",
            "command": "secret-exec",
            "arguments": [
                {"secret_profile_reference": "context7"},
                {"literal": "ctx7"},
            ],
        }
        stdio["secret_references"] = [
            {"kind": "secret_profile", "name": "context7"}
        ]
        stdio["equipment_identities"] = ["mcp:fixture/context7"]
        stdio["surface_scope"] = [
            "surface:route:fixture/claude-plugin/mcp:fixture/context7"
        ]
        stdio["preconditions"]["surface_scope"] = copy.deepcopy(
            stdio["surface_scope"]
        )
        stdio_target = {
            "target_identity": "target:sha256:" + "0" * 64,
            "write_surface_identity": stdio["surface_scope"][0],
            "surface_kind": "mcp_selection",
            "equipment_identity": "mcp:fixture/context7",
            "locator": {
                "owner": "claude",
                "source": "settings",
                "key_path": ["mcpServers", "context7"],
            },
        }
        stdio_target["target_identity"] = CAPTURED_STATE.write_target_identity(
            stdio_target
        )
        selection_without_equipment = copy.deepcopy(stdio_target)
        del selection_without_equipment["equipment_identity"]
        self.assertFalse(
            CAPTURED_STATE._has_write_target_shape(selection_without_equipment)
        )
        stdio["write_targets"] = [stdio_target]
        stdio_digest = CAPTURED_STATE.plan_action_digest(stdio)
        diagnostics, _, _ = CAPTURED_STATE._validate_plan_action_evidence(
            [{"action_payload": stdio, "action_digest": stdio_digest}],
            CANDIDATE_IDENTITY,
            IMPLEMENTATION_MANIFEST_DIGEST,
            stdio["plan_digest"],
        )
        self.assertEqual(diagnostics, [])

        for hostile_url in (
            "https://user@example.com/mcp",
            "https://example.com/token-secret",
            "https://example.com/Token/secret-value",
            "https://example.com/CLIENT-SECRET/value",
            "https://example.com/mcp?api_key=x",
            "https://-.example/mcp",
            "https://example..com/mcp",
            "https://example.com/./mcp",
            "https://example.com/../mcp",
        ):
            with self.subTest(hostile_url=hostile_url):
                http = copy.deepcopy(PLAN_ACTION_PAYLOAD)
                http["provider"] = {
                    "kind": "direct_mcp",
                    "server_name": "hostile",
                    "transport": "http",
                    "url": hostile_url,
                }
                authority = authoritative_plan_action_set()
                authority["actions"][0]["action_payload"] = http
                codes = {
                    diagnostic.code
                    for diagnostic in validate_document(valid_document(), authority)
                }
                self.assertIn(
                    "AUTHORITATIVE_PLAN_ACTION_SET_SCHEMA_INVALID",
                    codes,
                )

        for safe_url in (
            "https://example.com/mcp",
            "https://localhost/mcp",
            "https://127.0.0.1/mcp",
            "https://token.example.com/mcp",
            "https://secret.example.com/mcp",
        ):
            with self.subTest(safe_url=safe_url):
                safe_http = copy.deepcopy(PLAN_ACTION_PAYLOAD)
                safe_http["provider"] = {
                    "kind": "direct_mcp",
                    "server_name": "context7",
                    "transport": "http",
                    "url": safe_url,
                }
                self.assertTrue(CAPTURED_STATE.plan_action_digest(safe_http))

    def test_capability_set_digest_uses_sorted_closed_bindings(self) -> None:
        bindings = [
            {
                "capability_identity": "capability:z",
                "capability_digest": "sha256:" + "2" * 64,
                "manager_version_evidence_digest": "sha256:" + "3" * 64,
            },
            {
                "capability_identity": "capability:a",
                "capability_digest": "sha256:" + "0" * 64,
                "manager_version_evidence_digest": "sha256:" + "1" * 64,
            },
        ]

        self.assertEqual(
            CAPTURED_STATE.capability_set_digest(bindings),
            "sha256:702339ddafaa1955802f16a4fd72556465767cba0f2246387a56324430872131",
        )
        self.assertEqual(
            CAPTURED_STATE.capability_set_digest(list(reversed(bindings))),
            "sha256:702339ddafaa1955802f16a4fd72556465767cba0f2246387a56324430872131",
        )
        bindings[0]["unexpected"] = "not part of the closed binding"
        with self.assertRaises(ValueError):
            CAPTURED_STATE.capability_set_digest(bindings)

    def test_plan_action_digest_covers_the_closed_canonical_payload(self) -> None:
        self.assertEqual(
            CAPTURED_STATE.plan_action_identity(PLAN_ACTION_PAYLOAD),
            PLAN_ACTION_PAYLOAD["action_identity"],
        )
        self.assertEqual(
            CAPTURED_STATE.plan_action_digest(PLAN_ACTION_PAYLOAD),
            PLAN_ACTION_DIGEST,
        )

        payload = copy.deepcopy(PLAN_ACTION_PAYLOAD)
        payload["unexpected"] = "not part of the closed action evidence"
        with self.assertRaises(ValueError):
            CAPTURED_STATE.plan_action_digest(payload)

        combined_payload = copy.deepcopy(PLAN_ACTION_PAYLOAD)
        combined_payload["desired_state"] = {
            "route_presence": "present",
            "enablement": "enabled",
        }
        combined_payload["desired_state_digest"] = (
            "sha256:42176224e7ed4c5db475b4d9f40e7ad59b15e1d407e0c335e697b6e97e612a2d"
        )
        combined_payload["action_identity"] = CAPTURED_STATE.plan_action_identity(
            combined_payload
        )
        self.assertTrue(CAPTURED_STATE.plan_action_digest(combined_payload))

        self.assertEqual(
            CAPTURED_STATE.plan_action_set_digest(
                CANDIDATE_IDENTITY,
                IMPLEMENTATION_MANIFEST_DIGEST,
                PLAN_ACTION_PAYLOAD["plan_digest"],
                authoritative_plan_action_set()["actions"],
            ),
            PLAN_ACTION_SET_DIGEST,
        )

    def test_candidate_implementation_binding_prevents_cross_candidate_reuse(
        self,
    ) -> None:
        unchanged_a_under_b = CAPTURED_STATE.validate_captured_state(
            valid_document(),
            authoritative_plan_action_set(),
            expected_candidate_identity="candidate:fixture/controller-v2",
            expected_implementation_manifest_digest="sha256:" + "b" * 64,
        )
        self.assertIn(
            "TRUSTED_CANDIDATE_IDENTITY_MISMATCH",
            {diagnostic.code for diagnostic in unchanged_a_under_b},
        )
        self.assertIn(
            "TRUSTED_IMPLEMENTATION_MANIFEST_DIGEST_MISMATCH",
            {diagnostic.code for diagnostic in unchanged_a_under_b},
        )

        substituted_candidate = authoritative_plan_action_set()
        substituted_candidate["candidate_identity"] = (
            "candidate:fixture/controller-v2"
        )
        substituted_candidate["actions"][0]["action_payload"][
            "candidate_identity"
        ] = substituted_candidate["candidate_identity"]
        substituted_candidate["actions"][0]["action_payload"]["preconditions"][
            "candidate_identity"
        ] = substituted_candidate["candidate_identity"]
        rehash_authoritative_plan_action_set(substituted_candidate)
        substituted_candidate_codes = {
            diagnostic.code
            for diagnostic in validate_document(
                valid_document(),
                substituted_candidate,
            )
        }
        self.assertIn(
            "CANDIDATE_IDENTITY_MISMATCH",
            substituted_candidate_codes,
        )

        substituted_manifest = authoritative_plan_action_set()
        substituted_manifest["implementation_manifest_digest"] = (
            "sha256:" + "b" * 64
        )
        substituted_manifest["actions"][0]["action_payload"][
            "implementation_manifest_digest"
        ] = substituted_manifest["implementation_manifest_digest"]
        substituted_manifest["actions"][0]["action_payload"]["preconditions"][
            "implementation_manifest_digest"
        ] = substituted_manifest["implementation_manifest_digest"]
        rehash_authoritative_plan_action_set(substituted_manifest)
        substituted_manifest_codes = {
            diagnostic.code
            for diagnostic in validate_document(
                valid_document(),
                substituted_manifest,
            )
        }
        self.assertIn(
            "IMPLEMENTATION_MANIFEST_DIGEST_MISMATCH",
            substituted_manifest_codes,
        )
        self.assertIn(
            "TRUSTED_IMPLEMENTATION_MANIFEST_DIGEST_MISMATCH",
            substituted_manifest_codes,
        )

        fully_coordinated_b = copy.deepcopy(substituted_candidate)
        fully_coordinated_b["implementation_manifest_digest"] = (
            "sha256:" + "b" * 64
        )
        fully_coordinated_b["actions"][0]["action_payload"][
            "implementation_manifest_digest"
        ] = fully_coordinated_b["implementation_manifest_digest"]
        fully_coordinated_b["actions"][0]["action_payload"]["preconditions"][
            "implementation_manifest_digest"
        ] = fully_coordinated_b["implementation_manifest_digest"]
        rehash_authoritative_plan_action_set(fully_coordinated_b)
        fully_coordinated_capture = valid_document()
        fully_coordinated_capture["bindings"]["candidate_identity"] = (
            fully_coordinated_b["candidate_identity"]
        )
        fully_coordinated_capture["bindings"][
            "implementation_manifest_digest"
        ] = fully_coordinated_b["implementation_manifest_digest"]
        fully_coordinated_capture["bindings"]["plan_action_set_digest"] = (
            fully_coordinated_b["action_set_digest"]
        )
        fully_coordinated_capture["provider_routes"][0]["planned_actions"][0][
            "action_digest"
        ] = fully_coordinated_b["actions"][0]["action_digest"]
        coordinated_under_a = CAPTURED_STATE.validate_captured_state(
            fully_coordinated_capture,
            fully_coordinated_b,
            expected_candidate_identity=CANDIDATE_IDENTITY,
            expected_implementation_manifest_digest=(
                IMPLEMENTATION_MANIFEST_DIGEST
            ),
        )
        self.assertIn(
            "TRUSTED_CANDIDATE_IDENTITY_MISMATCH",
            {diagnostic.code for diagnostic in coordinated_under_a},
        )
        coordinated_under_b = CAPTURED_STATE.validate_captured_state(
            fully_coordinated_capture,
            fully_coordinated_b,
            expected_candidate_identity=fully_coordinated_b[
                "candidate_identity"
            ],
            expected_implementation_manifest_digest=fully_coordinated_b[
                "implementation_manifest_digest"
            ],
        )
        self.assertEqual(coordinated_under_b, ())

        empty_a = empty_authoritative_plan_action_set()
        empty_capture = valid_document()
        empty_capture["provider_routes"][0]["planned_actions"] = []
        empty_capture["provider_routes"][0]["control_owner"] = "operator_owned"
        empty_capture["surfaces"][0]["mutation_policy"] = "operator_owned"
        empty_capture["surfaces"][0]["recovery"] = {
            "kind": "none",
            "reason": "absent_noop",
        }
        empty_capture["surfaces"][2]["mutation_policy"] = "operator_owned"
        empty_capture["bindings"]["plan_action_set_digest"] = empty_a[
            "action_set_digest"
        ]
        empty_under_b = CAPTURED_STATE.validate_captured_state(
            empty_capture,
            empty_a,
            expected_candidate_identity="candidate:fixture/controller-v2",
            expected_implementation_manifest_digest="sha256:" + "b" * 64,
        )
        self.assertIn(
            "TRUSTED_CANDIDATE_IDENTITY_MISMATCH",
            {diagnostic.code for diagnostic in empty_under_b},
        )

        mismatched_action = authoritative_plan_action_set()
        mismatched_action["actions"][0]["action_payload"][
            "candidate_identity"
        ] = "candidate:fixture/controller-v2"
        rehash_authoritative_plan_action_set(mismatched_action)
        mismatched_action_document = valid_document()
        mismatched_action_document["bindings"]["plan_action_set_digest"] = (
            mismatched_action["action_set_digest"]
        )
        mismatched_action_document["provider_routes"][0]["planned_actions"][0][
            "action_digest"
        ] = mismatched_action["actions"][0]["action_digest"]
        mismatched_action_codes = {
            diagnostic.code
            for diagnostic in validate_document(
                mismatched_action_document,
                mismatched_action,
            )
        }
        self.assertIn(
            "PLAN_ACTION_CANDIDATE_IDENTITY_MISMATCH",
            mismatched_action_codes,
        )

        mismatched_action_manifest = authoritative_plan_action_set()
        mismatched_action_manifest["actions"][0]["action_payload"][
            "implementation_manifest_digest"
        ] = "sha256:" + "b" * 64
        rehash_authoritative_plan_action_set(mismatched_action_manifest)
        mismatched_action_manifest_document = valid_document()
        mismatched_action_manifest_document["bindings"][
            "plan_action_set_digest"
        ] = mismatched_action_manifest["action_set_digest"]
        mismatched_action_manifest_document["provider_routes"][0][
            "planned_actions"
        ][0]["action_digest"] = mismatched_action_manifest["actions"][0][
            "action_digest"
        ]
        self.assertIn(
            "PLAN_ACTION_IMPLEMENTATION_MANIFEST_DIGEST_MISMATCH",
            {
                diagnostic.code
                for diagnostic in validate_document(
                    mismatched_action_manifest_document,
                    mismatched_action_manifest,
                )
            },
        )

        captured_candidate = valid_document()
        captured_candidate["bindings"]["candidate_identity"] = (
            "candidate:fixture/controller-v2"
        )
        self.assertIn(
            "CANDIDATE_IDENTITY_MISMATCH",
            {
                diagnostic.code
                for diagnostic in validate_document(captured_candidate)
            },
        )

        captured_manifest = valid_document()
        captured_manifest["bindings"]["implementation_manifest_digest"] = (
            "sha256:" + "b" * 64
        )
        self.assertIn(
            "IMPLEMENTATION_MANIFEST_DIGEST_MISMATCH",
            {
                diagnostic.code
                for diagnostic in validate_document(captured_manifest)
            },
        )

        self.assertNotEqual(
            CAPTURED_STATE.plan_action_set_digest(
                CANDIDATE_IDENTITY,
                IMPLEMENTATION_MANIFEST_DIGEST,
                empty_a["plan_digest"],
                [],
            ),
            CAPTURED_STATE.plan_action_set_digest(
                "candidate:fixture/controller-v2",
                "sha256:" + "b" * 64,
                empty_a["plan_digest"],
                [],
            ),
        )

    def test_valid_manifest_has_no_semantic_diagnostics(self) -> None:
        self.assertEqual(validate_document(valid_document()), ())

    def test_full_plan_projection_binds_all_automated_action_authority(self) -> None:
        mutations: list[tuple[str, object, str]] = [
            (
                "route_digest",
                "sha256:" + "f" * 64,
                "FORWARD_ACTION_ROUTE_DIGEST_MISMATCH",
            ),
            ("harness", "codex", "PLAN_ACTION_HARNESS_MISMATCH"),
            (
                "adapter_identity",
                "adapter:fixture/other",
                "PLAN_ACTION_PRECONDITION_BINDING_MISMATCH",
            ),
            (
                "adapter_version",
                "9.9.9",
                "PLAN_ACTION_PRECONDITION_BINDING_MISMATCH",
            ),
            (
                "capability_digest",
                "sha256:" + "f" * 64,
                "PLAN_ACTION_AUTHORITY_BINDING_MISMATCH",
            ),
            (
                "controlled_equipment_identities",
                ["skill:fixture/controlled"],
                "PLAN_ACTION_EQUIPMENT_MISMATCH",
            ),
        ]
        for field, value, expected_code in mutations:
            with self.subTest(field=field):
                authoritative = authoritative_plan_action_set()
                payload = authoritative["actions"][0]["action_payload"]
                payload[field] = value
                authoritative["actions"][0]["action_digest"] = (
                    CAPTURED_STATE.plan_action_digest(payload)
                )
                authoritative["action_set_digest"] = (
                    CAPTURED_STATE.plan_action_set_digest(
                        authoritative["candidate_identity"],
                        authoritative["implementation_manifest_digest"],
                        authoritative["plan_digest"],
                        authoritative["actions"],
                    )
                )
                document = valid_document()
                document["bindings"]["plan_action_set_digest"] = authoritative[
                    "action_set_digest"
                ]
                document["provider_routes"][0]["planned_actions"][0][
                    "action_digest"
                ] = authoritative["actions"][0]["action_digest"]
                codes = {
                    diagnostic.code
                    for diagnostic in validate_document(document, authoritative)
                }
                self.assertIn(expected_code, codes)

        for provider_field, provider_value in (
            ("manager", "codex"),
            ("plugin_id", "other@fixture"),
        ):
            with self.subTest(provider_field=provider_field):
                authoritative = authoritative_plan_action_set()
                payload = authoritative["actions"][0]["action_payload"]
                payload["provider"][provider_field] = provider_value
                authoritative["actions"][0]["action_digest"] = (
                    CAPTURED_STATE.plan_action_digest(payload)
                )
                authoritative["action_set_digest"] = (
                    CAPTURED_STATE.plan_action_set_digest(
                        authoritative["candidate_identity"],
                        authoritative["implementation_manifest_digest"],
                        authoritative["plan_digest"],
                        authoritative["actions"],
                    )
                )
                document = valid_document()
                document["bindings"]["plan_action_set_digest"] = authoritative[
                    "action_set_digest"
                ]
                document["provider_routes"][0]["planned_actions"][0][
                    "action_digest"
                ] = authoritative["actions"][0]["action_digest"]
                codes = {
                    diagnostic.code
                    for diagnostic in validate_document(document, authoritative)
                }
                self.assertIn("PLAN_ACTION_NATIVE_TARGET_MISMATCH", codes)

        invalid_scope_authority = authoritative_plan_action_set()
        invalid_scope_authority["actions"][0]["action_payload"]["provider"][
            "scope"
        ] = "project"
        self.assertIn(
            "AUTHORITATIVE_PLAN_ACTION_SET_SCHEMA_INVALID",
            {
                diagnostic.code
                for diagnostic in validate_document(
                    valid_document(), invalid_scope_authority
                )
            },
        )

        for operation in (
            "install",
            "configure",
            "enable",
            "disable",
            "remove",
            "restore",
            "suppress_native_update",
        ):
            payload = copy.deepcopy(PLAN_ACTION_PAYLOAD)
            payload["operation"] = operation
            payload["action_identity"] = CAPTURED_STATE.plan_action_identity(payload)
            self.assertTrue(CAPTURED_STATE.plan_action_digest(payload))

        native_remove_authority = authoritative_plan_action_set()
        native_remove_payload = native_remove_authority["actions"][0][
            "action_payload"
        ]
        native_remove_payload["operation"] = "remove"
        native_remove_payload["action_identity"] = (
            CAPTURED_STATE.plan_action_identity(native_remove_payload)
        )
        native_remove_authority["actions"][0]["action_digest"] = (
            CAPTURED_STATE.plan_action_digest(native_remove_payload)
        )
        native_remove_authority["action_set_digest"] = (
            CAPTURED_STATE.plan_action_set_digest(
                native_remove_authority["candidate_identity"],
                native_remove_authority["implementation_manifest_digest"],
                native_remove_authority["plan_digest"],
                native_remove_authority["actions"],
            )
        )
        native_remove_document = valid_document()
        native_remove_document["bindings"]["plan_action_set_digest"] = (
            native_remove_authority["action_set_digest"]
        )
        native_remove_document["provider_routes"][0]["planned_actions"][0][
            "action_identity"
        ] = native_remove_payload["action_identity"]
        native_remove_document["provider_routes"][0]["planned_actions"][0][
            "action_digest"
        ] = native_remove_authority["actions"][0]["action_digest"]
        native_remove_codes = {
            diagnostic.code
            for diagnostic in validate_document(
                native_remove_document,
                native_remove_authority,
            )
        }
        self.assertIn(
            "NATIVE_ROLLING_REMOVE_AUTOMATION_INVALID",
            native_remove_codes,
        )

    def test_action_write_scope_and_canonical_dependencies_are_bijective(self) -> None:
        cases: list[tuple[str, dict[str, object], dict[str, object]]] = []

        missing_canonical = valid_document()
        del missing_canonical["surfaces"][1]
        missing_canonical["provider_routes"][0]["surface_references"][
            "canonical_skill_dependencies"
        ] = []
        cases.append(
            (
                "CANONICAL_DEPENDENCY_DANGLING",
                missing_canonical,
                authoritative_plan_action_set(),
            )
        )

        duplicate_dependency_authority = authoritative_plan_action_set()
        duplicate_dependency_authority["actions"][0]["action_payload"][
            "verification_dependencies"
        ].append(
            copy.deepcopy(
                duplicate_dependency_authority["actions"][0]["action_payload"][
                    "verification_dependencies"
                ][0]
            )
        )
        duplicate_dependency_document = valid_document()
        cases.append(
            (
                "AUTHORITATIVE_PLAN_ACTION_SET_SCHEMA_INVALID",
                duplicate_dependency_document,
                duplicate_dependency_authority,
            )
        )

        relabeled_claude_target = valid_document()
        relabeled_claude_target["surfaces"][2]["locator"][
            "path"
        ] = "~/.claude/skills/other"
        cases.append(
            (
                "PLAN_ACTION_WRITE_TARGET_MISMATCH",
                relabeled_claude_target,
                authoritative_plan_action_set(),
            )
        )

        swapped_target_binding = valid_document()
        bindings = swapped_target_binding["provider_routes"][0][
            "planned_actions"
        ][0]["write_bindings"]
        bindings[0]["surface_id"], bindings[1]["surface_id"] = (
            bindings[1]["surface_id"],
            bindings[0]["surface_id"],
        )
        cases.append(
            (
                "PLAN_ACTION_WRITE_TARGET_MISMATCH",
                swapped_target_binding,
                authoritative_plan_action_set(),
            )
        )

        mismatch_authority = authoritative_plan_action_set()
        mismatch_authority["actions"][0]["action_payload"][
            "verification_dependencies"
        ][0]["equipment_identity"] = "skill:fixture/other"
        mismatch_payload = mismatch_authority["actions"][0]["action_payload"]
        mismatch_authority["actions"][0]["action_digest"] = (
            CAPTURED_STATE.plan_action_digest(mismatch_payload)
        )
        mismatch_authority["action_set_digest"] = (
            CAPTURED_STATE.plan_action_set_digest(
                mismatch_authority["candidate_identity"],
                mismatch_authority["implementation_manifest_digest"],
                mismatch_authority["plan_digest"],
                mismatch_authority["actions"],
            )
        )
        mismatch_document = valid_document()
        mismatch_document["bindings"]["plan_action_set_digest"] = mismatch_authority[
            "action_set_digest"
        ]
        mismatch_document["provider_routes"][0]["planned_actions"][0][
            "action_digest"
        ] = mismatch_authority["actions"][0]["action_digest"]
        cases.append(
            (
                "CANONICAL_DEPENDENCY_MISMATCH",
                mismatch_document,
                mismatch_authority,
            )
        )

        target_mismatch_authority = authoritative_plan_action_set()
        target_mismatch_authority["actions"][0]["action_payload"][
            "verification_dependencies"
        ][0]["target_locator"]["path"] = "~/.agents/skills/other"
        target_mismatch_payload = target_mismatch_authority["actions"][0][
            "action_payload"
        ]
        target_mismatch_authority["actions"][0]["action_digest"] = (
            CAPTURED_STATE.plan_action_digest(target_mismatch_payload)
        )
        target_mismatch_authority["action_set_digest"] = (
            CAPTURED_STATE.plan_action_set_digest(
                target_mismatch_authority["candidate_identity"],
                target_mismatch_authority["implementation_manifest_digest"],
                target_mismatch_authority["plan_digest"],
                target_mismatch_authority["actions"],
            )
        )
        target_mismatch_document = valid_document()
        target_mismatch_document["bindings"]["plan_action_set_digest"] = (
            target_mismatch_authority["action_set_digest"]
        )
        target_mismatch_document["provider_routes"][0]["planned_actions"][0][
            "action_digest"
        ] = target_mismatch_authority["actions"][0]["action_digest"]
        cases.append(
            (
                "CANONICAL_DEPENDENCY_MISMATCH",
                target_mismatch_document,
                target_mismatch_authority,
            )
        )

        missing_action_write = authoritative_plan_action_set()
        plugin_logical_surface = (
            "surface:route:fixture/claude-plugin/plugin:fixture/example"
        )
        missing_action_write["actions"][0]["action_payload"]["surface_scope"] = [
            plugin_logical_surface
        ]
        missing_action_write["actions"][0]["action_payload"]["preconditions"][
            "surface_scope"
        ] = [plugin_logical_surface]
        missing_action_write["actions"][0]["action_payload"]["write_targets"] = [
            copy.deepcopy(PLUGIN_INSTALLATION_TARGET)
        ]
        missing_action_write["actions"][0]["action_payload"][
            "verification_dependencies"
        ] = []
        missing_payload = missing_action_write["actions"][0]["action_payload"]
        missing_action_write["actions"][0]["action_digest"] = (
            CAPTURED_STATE.plan_action_digest(missing_payload)
        )
        missing_action_write["action_set_digest"] = (
            CAPTURED_STATE.plan_action_set_digest(
                missing_action_write["candidate_identity"],
                missing_action_write["implementation_manifest_digest"],
                missing_action_write["plan_digest"],
                missing_action_write["actions"],
            )
        )
        missing_write_document = valid_document()
        missing_write_document["bindings"]["plan_action_set_digest"] = (
            missing_action_write["action_set_digest"]
        )
        missing_write_document["provider_routes"][0]["planned_actions"][0][
            "action_digest"
        ] = missing_action_write["actions"][0]["action_digest"]
        missing_write_document["provider_routes"][0]["planned_actions"][0][
            "write_bindings"
        ] = [
            binding
            for binding in missing_write_document["provider_routes"][0][
                "planned_actions"
            ][0]["write_bindings"]
            if binding["target_identity"]
            == PLUGIN_INSTALLATION_TARGET["target_identity"]
        ]
        missing_write_document["provider_routes"][0]["planned_actions"][0][
            "verification_dependency_bindings"
        ] = []
        cases.append(
            (
                "MUTABLE_SURFACE_ACTION_OWNERSHIP_MISMATCH",
                missing_write_document,
                missing_action_write,
            )
        )

        operator_rewrite = valid_document()
        operator_rewrite["provider_routes"][0]["control_owner"] = "operator_owned"
        operator_rewrite["surfaces"][0]["mutation_policy"] = "operator_owned"
        operator_rewrite["surfaces"][2]["mutation_policy"] = "operator_owned"
        cases.append(
            (
                "AUTOMATED_ACTION_ROUTE_OWNERSHIP_INVALID",
                operator_rewrite,
                authoritative_plan_action_set(),
            )
        )

        selection_authority = authoritative_plan_action_set()
        selection_payload = selection_authority["actions"][0]["action_payload"]
        selection_payload["equipment_identities"] = [
            "mcp:fixture/context7",
            "plugin:fixture/example",
        ]
        selection_identity = (
            "surface:route:fixture/claude-plugin/mcp:fixture/context7"
        )
        selection_target = {
            "target_identity": "target:sha256:" + "0" * 64,
            "write_surface_identity": selection_identity,
            "surface_kind": "mcp_selection",
            "equipment_identity": "mcp:fixture/context7",
            "locator": {
                "owner": "claude",
                "source": "settings",
                "key_path": ["mcpServers", "context7"],
            },
        }
        selection_target["target_identity"] = (
            CAPTURED_STATE.write_target_identity(selection_target)
        )
        selection_payload["surface_scope"] = sorted(
            [
                PLUGIN_INSTALLATION_TARGET["write_surface_identity"],
                selection_identity,
            ]
        )
        selection_payload["preconditions"]["surface_scope"] = copy.deepcopy(
            selection_payload["surface_scope"]
        )
        selection_payload["write_targets"] = sorted(
            [
                copy.deepcopy(PLUGIN_INSTALLATION_TARGET),
                selection_target,
            ],
            key=lambda target: target["target_identity"],
        )
        selection_payload["verification_dependencies"] = []
        selection_authority["actions"][0]["action_digest"] = (
            CAPTURED_STATE.plan_action_digest(selection_payload)
        )
        selection_authority["action_set_digest"] = (
            CAPTURED_STATE.plan_action_set_digest(
                selection_authority["candidate_identity"],
                selection_authority["implementation_manifest_digest"],
                selection_authority["plan_digest"],
                selection_authority["actions"],
            )
        )

        selection_document = valid_document()
        selection_document["bindings"]["plan_action_set_digest"] = (
            selection_authority["action_set_digest"]
        )
        selection_route = selection_document["provider_routes"][0]
        selection_route["equipment_identities"] = copy.deepcopy(
            selection_payload["equipment_identities"]
        )
        selection_route["planned_actions"][0]["action_digest"] = (
            selection_authority["actions"][0]["action_digest"]
        )
        selection_route["planned_actions"][0]["write_bindings"] = sorted(
            [
                {
                    "target_identity": PLUGIN_INSTALLATION_TARGET[
                        "target_identity"
                    ],
                    "surface_id": "surface:fixture/plugin-installation",
                },
                {
                    "target_identity": selection_target["target_identity"],
                    "surface_id": "surface:fixture/mcp-selection",
                },
            ],
            key=lambda binding: binding["target_identity"],
        )
        selection_route["planned_actions"][0][
            "verification_dependency_bindings"
        ] = []
        selection_route["surface_references"]["mcp_selections"] = [
            {
                "status": "captured",
                "surface_id": "surface:fixture/mcp-selection",
            }
        ]
        selection_route["surface_references"]["skill_entries"] = []
        selection_route["surface_references"][
            "canonical_skill_dependencies"
        ] = []
        selection_surface = copy.deepcopy(selection_document["surfaces"][2])
        selection_surface.update(
            {
                "surface_id": "surface:fixture/mcp-selection",
                "kind": "mcp_selection",
                "equipment_identity": "mcp:fixture/context7",
                "locator": copy.deepcopy(selection_target["locator"]),
                "observation": {"present": False},
                "recovery": {"kind": "none", "reason": "absent_noop"},
            }
        )
        selection_document["surfaces"] = [
            selection_document["surfaces"][0],
            selection_surface,
        ]
        self.assertEqual(
            validate_document(selection_document, selection_authority),
            (),
        )

        selection_capture_without_equipment = copy.deepcopy(selection_document)
        del selection_capture_without_equipment["surfaces"][1][
            "equipment_identity"
        ]
        cases.append(
            (
                "CAPTURED_STATE_SCHEMA_INVALID",
                selection_capture_without_equipment,
                selection_authority,
            )
        )

        relabeled_selection = copy.deepcopy(selection_document)
        relabeled_selection["surfaces"][1][
            "equipment_identity"
        ] = "plugin:fixture/example"
        cases.append(
            (
                "PLAN_ACTION_WRITE_TARGET_MISMATCH",
                relabeled_selection,
                selection_authority,
            )
        )

        for expected_code, document, authority in cases:
            with self.subTest(expected_code=expected_code):
                codes = {
                    diagnostic.code
                    for diagnostic in validate_document(document, authority)
                }
                self.assertIn(expected_code, codes)

    def test_native_installation_capture_accepts_only_coherent_route_evidence(
        self,
    ) -> None:
        absent_noop = valid_document()
        absent_noop["provider_routes"][0]["planned_actions"] = []
        absent_noop["provider_routes"][0]["control_owner"] = "operator_owned"
        absent_noop["surfaces"][0]["mutation_policy"] = "operator_owned"
        absent_noop["surfaces"][2]["mutation_policy"] = "operator_owned"
        absent_noop["bindings"][
            "plan_action_set_digest"
        ] = EMPTY_PLAN_ACTION_SET_DIGEST
        absent_noop["surfaces"][0]["recovery"] = {
            "kind": "none",
            "reason": "absent_noop",
        }
        self.assertEqual(
            validate_document(absent_noop, empty_authoritative_plan_action_set()),
            (),
        )

        observed = valid_document()
        observed["provider_routes"][0]["planned_actions"] = []
        observed["provider_routes"][0]["control_owner"] = "operator_owned"
        observed["surfaces"][0]["mutation_policy"] = "operator_owned"
        observed["surfaces"][2]["mutation_policy"] = "operator_owned"
        observed["bindings"][
            "plan_action_set_digest"
        ] = EMPTY_PLAN_ACTION_SET_DIGEST
        observed["provider_routes"][0]["restore_evidence"] = {
            "restore_class": "native_rolling",
            "channel": "official-marketplace",
            "observed_version": {"status": "observed", "value": "1.2.3"},
            "observation_source": "claude plugin list",
            "native_update_control": "unknown",
            "exact_prior_artifact_restore": False,
        }
        observed["surfaces"][0]["observation"] = {
            "installed": True,
            "channel": "official-marketplace",
            "observed_version": "1.2.3",
            "observation_source": "claude plugin list",
        }
        observed["surfaces"][0]["recovery"] = {
            "kind": "none",
            "reason": "operator_owned",
        }
        self.assertEqual(
            validate_document(observed, empty_authoritative_plan_action_set()),
            (),
        )

        cases: list[tuple[str, dict[str, object]]] = []

        absent_but_installed = valid_document()
        absent_but_installed["surfaces"][0]["observation"] = copy.deepcopy(
            observed["surfaces"][0]["observation"]
        )
        cases.append(
            ("NATIVE_INSTALLATION_PRESENCE_MISMATCH", absent_but_installed)
        )

        absent_wrong_recovery = valid_document()
        absent_wrong_recovery["surfaces"][0]["recovery"] = {
            "kind": "none",
            "reason": "already_desired",
        }
        cases.append(
            ("NATIVE_INSTALLATION_RECOVERY_MISMATCH", absent_wrong_recovery)
        )

        unbound_remove = valid_document()
        unbound_remove["provider_routes"][0]["planned_actions"] = []
        cases.append(("NATIVE_REMOVE_INVERSE_UNBOUND", unbound_remove))

        forged_action_identity = valid_document()
        forged_action_identity["provider_routes"][0]["planned_actions"][0][
            "action_identity"
        ] = FORGED_ACTION_IDENTITY
        cases.append(
            ("FORWARD_ACTION_IDENTITY_UNKNOWN", forged_action_identity)
        )

        forged_action_digest = valid_document()
        forged_action_digest["provider_routes"][0]["planned_actions"][0][
            "action_digest"
        ] = "sha256:" + "f" * 64
        cases.append(("FORWARD_ACTION_DIGEST_MISMATCH", forged_action_digest))

        inverse_guard_mismatch = valid_document()
        inverse_guard_mismatch["surfaces"][0]["recovery"][
            "expected_pre_state_digest"
        ] = "sha256:" + "f" * 64
        cases.append(
            ("NATIVE_REMOVE_INVERSE_GUARD_MISMATCH", inverse_guard_mismatch)
        )

        desired_fragment_as_inverse_guard = valid_document()
        desired_fragment_as_inverse_guard["surfaces"][0]["recovery"][
            "expected_pre_state_digest"
        ] = PLAN_ACTION_PAYLOAD["desired_state_digest"]
        cases.append(
            (
                "NATIVE_REMOVE_INVERSE_GUARD_MISMATCH",
                desired_fragment_as_inverse_guard,
            )
        )

        for locator_field, locator_value in (
            ("manager", "other-manager"),
            ("native_identity", "other@fixture"),
            ("scope", "other-scope"),
        ):
            relabeled_locator = valid_document()
            relabeled_locator["surfaces"][0]["locator"][locator_field] = (
                locator_value
            )
            cases.append(
                (
                    "FORWARD_ACTION_INSTALLATION_LOCATOR_MISMATCH",
                    relabeled_locator,
                )
            )

        immutable_remove_inverse = valid_document()
        immutable_remove_inverse["provider_routes"][0]["restore_evidence"] = {
            "restore_class": "immutable",
            "revision": "fixture-revision",
            "artifact_reference": "https://example.invalid/plugin.tgz",
            "content_digest": "sha256:" + "a" * 64,
        }
        cases.append(
            (
                "NATIVE_REMOVE_INVERSE_RESTORE_CLASS_INVALID",
                immutable_remove_inverse,
            )
        )

        immutable_unreferenced_remove = copy.deepcopy(immutable_remove_inverse)
        immutable_unreferenced_remove["provider_routes"][0]["planned_actions"] = []
        immutable_unreferenced_remove["provider_routes"][0][
            "surface_references"
        ]["installation"] = {"status": "not_applicable"}
        cases.append(
            (
                "NATIVE_REMOVE_INVERSE_RESTORE_CLASS_INVALID",
                immutable_unreferenced_remove,
            )
        )

        observed_but_absent = copy.deepcopy(observed)
        observed_but_absent["surfaces"][0]["observation"] = {"installed": False}
        cases.append(
            ("NATIVE_INSTALLATION_PRESENCE_MISMATCH", observed_but_absent)
        )

        observed_wrong_version = copy.deepcopy(observed)
        observed_wrong_version["surfaces"][0]["observation"][
            "observed_version"
        ] = "9.9.9"
        cases.append(
            ("NATIVE_INSTALLATION_VERSION_MISMATCH", observed_wrong_version)
        )

        observed_wrong_channel = copy.deepcopy(observed)
        observed_wrong_channel["surfaces"][0]["observation"][
            "channel"
        ] = "different-channel"
        cases.append(
            ("NATIVE_INSTALLATION_CHANNEL_MISMATCH", observed_wrong_channel)
        )

        observed_wrong_source = copy.deepcopy(observed)
        observed_wrong_source["surfaces"][0]["observation"][
            "observation_source"
        ] = "different source"
        cases.append(
            ("NATIVE_INSTALLATION_SOURCE_MISMATCH", observed_wrong_source)
        )

        observed_absence_recovery = copy.deepcopy(observed)
        observed_absence_recovery["surfaces"][0]["recovery"] = {
            "kind": "none",
            "reason": "absent_noop",
        }
        cases.append(
            ("NATIVE_INSTALLATION_RECOVERY_MISMATCH", observed_absence_recovery)
        )

        observed_remove_inverse = copy.deepcopy(observed)
        observed_remove_inverse["surfaces"][0]["recovery"] = {
            "kind": "native_inverse",
            "inverse_operation": "remove",
            "expected_pre_state_digest": "sha256:" + "9" * 64,
        }
        cases.append(
            ("NATIVE_REMOVE_INVERSE_REQUIRES_ABSENCE", observed_remove_inverse)
        )

        observed_with_forward_install = copy.deepcopy(observed)
        observed_with_forward_install["provider_routes"][0]["planned_actions"] = (
            copy.deepcopy(valid_document()["provider_routes"][0]["planned_actions"])
        )
        observed_with_forward_install["bindings"]["plan_action_set_digest"] = (
            PLAN_ACTION_SET_DIGEST
        )
        observed_with_forward_install["provider_routes"][0][
            "control_owner"
        ] = "reconciler_owned"
        observed_with_forward_install["surfaces"][0][
            "mutation_policy"
        ] = "reconciler_owned"
        observed_with_forward_install["surfaces"][2][
            "mutation_policy"
        ] = "reconciler_owned"
        cases.append(
            (
                "NATIVE_FORWARD_INSTALL_REQUIRES_ABSENCE",
                observed_with_forward_install,
            )
        )

        missing_installation_reference = valid_document()
        missing_installation_reference["provider_routes"][0][
            "surface_references"
        ]["installation"] = {"status": "not_applicable"}
        cases.append(
            (
                "NATIVE_INSTALLATION_REFERENCE_REQUIRED",
                missing_installation_reference,
            )
        )

        split_install_authority = authoritative_plan_action_set()
        install_payload = split_install_authority["actions"][0]["action_payload"]
        install_payload["surface_scope"] = [
            CLAUDE_SKILL_TARGET["write_surface_identity"]
        ]
        install_payload["preconditions"]["surface_scope"] = copy.deepcopy(
            install_payload["surface_scope"]
        )
        install_payload["write_targets"] = [
            copy.deepcopy(CLAUDE_SKILL_TARGET)
        ]
        split_install_authority["actions"][0][
            "action_digest"
        ] = CAPTURED_STATE.plan_action_digest(install_payload)

        configure_payload = copy.deepcopy(PLAN_ACTION_PAYLOAD)
        configure_payload["ordinal"] = 1
        configure_payload["operation"] = "configure"
        configure_payload["surface_scope"] = [
            PLUGIN_INSTALLATION_TARGET["write_surface_identity"]
        ]
        configure_payload["preconditions"]["surface_scope"] = copy.deepcopy(
            configure_payload["surface_scope"]
        )
        configure_payload["write_targets"] = [
            copy.deepcopy(PLUGIN_INSTALLATION_TARGET)
        ]
        configure_payload["verification_dependencies"] = []
        configure_payload["action_identity"] = (
            CAPTURED_STATE.plan_action_identity(configure_payload)
        )
        configure_action = {
            "action_payload": configure_payload,
            "action_digest": CAPTURED_STATE.plan_action_digest(
                configure_payload
            ),
        }
        split_install_authority["actions"].append(configure_action)
        split_install_authority["action_set_digest"] = (
            CAPTURED_STATE.plan_action_set_digest(
                split_install_authority["candidate_identity"],
                split_install_authority["implementation_manifest_digest"],
                split_install_authority["plan_digest"],
                split_install_authority["actions"],
            )
        )

        split_install_document = valid_document()
        install_reference = split_install_document["provider_routes"][0][
            "planned_actions"
        ][0]
        install_reference["action_digest"] = split_install_authority[
            "actions"
        ][0]["action_digest"]
        install_reference["write_bindings"] = [
            {
                "target_identity": CLAUDE_SKILL_TARGET["target_identity"],
                "surface_id": "surface:fixture/claude-skill",
            }
        ]
        split_install_document["provider_routes"][0]["planned_actions"].append(
            {
                "action_identity": configure_payload["action_identity"],
                "action_digest": configure_action["action_digest"],
                "write_bindings": [
                    {
                        "target_identity": PLUGIN_INSTALLATION_TARGET[
                            "target_identity"
                        ],
                        "surface_id": "surface:fixture/plugin-installation",
                    }
                ],
                "verification_dependency_bindings": [],
            }
        )
        split_install_document["bindings"]["plan_action_set_digest"] = (
            split_install_authority["action_set_digest"]
        )
        split_install_codes = {
            diagnostic.code
            for diagnostic in validate_document(
                split_install_document,
                split_install_authority,
            )
        }
        self.assertIn(
            "NATIVE_REMOVE_INVERSE_INSTALL_ACTION_OWNERSHIP_MISMATCH",
            split_install_codes,
        )

        for expected_code, document in cases:
            with self.subTest(expected_code=expected_code):
                codes = {
                    diagnostic.code
                    for diagnostic in validate_document(document)
                }
                self.assertIn(expected_code, codes)

    def test_forward_install_requires_separate_authoritative_plan_membership(
        self,
    ) -> None:
        cases: list[tuple[str, dict[str, object], dict[str, object]]] = []

        wrong_plan_actions = authoritative_plan_action_set()
        wrong_plan_actions["actions"][0]["action_payload"][
            "plan_digest"
        ] = "sha256:" + "f" * 64
        cases.append(
            (
                "FORWARD_ACTION_PLAN_DIGEST_MISMATCH",
                valid_document(),
                wrong_plan_actions,
            )
        )

        forged_evidence_digest = authoritative_plan_action_set()
        forged_evidence_digest["actions"][0]["action_digest"] = (
            "sha256:" + "f" * 64
        )
        cases.append(
            (
                "PLAN_ACTION_DIGEST_MISMATCH",
                valid_document(),
                forged_evidence_digest,
            )
        )

        forged_evidence_identity = authoritative_plan_action_set()
        forged_evidence_identity["actions"][0]["action_payload"][
            "action_identity"
        ] = FORGED_ACTION_IDENTITY
        forged_evidence_identity["actions"][0][
            "action_digest"
        ] = CAPTURED_STATE.plan_action_digest(
            forged_evidence_identity["actions"][0]["action_payload"]
        )
        cases.append(
            (
                "PLAN_ACTION_IDENTITY_MISMATCH",
                valid_document(),
                forged_evidence_identity,
            )
        )

        wrong_action_route = authoritative_plan_action_set()
        wrong_action_route["actions"][0]["action_payload"][
            "route_identity"
        ] = "route:fixture/other"
        wrong_action_route["actions"][0][
            "action_payload"
        ]["action_identity"] = CAPTURED_STATE.plan_action_identity(
            wrong_action_route["actions"][0]["action_payload"]
        )
        wrong_action_route["actions"][0][
            "action_digest"
        ] = CAPTURED_STATE.plan_action_digest(
            wrong_action_route["actions"][0]["action_payload"]
        )
        wrong_route_document = valid_document()
        wrong_route_document["provider_routes"][0]["planned_actions"][0][
            "action_identity"
        ] = wrong_action_route["actions"][0]["action_payload"][
            "action_identity"
        ]
        wrong_route_document["provider_routes"][0]["planned_actions"][0][
            "action_digest"
        ] = wrong_action_route["actions"][0]["action_digest"]
        cases.append(
            (
                "FORWARD_ACTION_ROUTE_MISMATCH",
                wrong_route_document,
                wrong_action_route,
            )
        )

        for expected_code, document, plan_action_set in cases:
            with self.subTest(expected_code=expected_code):
                codes = {
                    diagnostic.code
                    for diagnostic in validate_document(document, plan_action_set)
                }
                self.assertIn(expected_code, codes)

        invented_payload = copy.deepcopy(PLAN_ACTION_PAYLOAD)
        invented_payload["ordinal"] = 999
        invented_payload["action_identity"] = CAPTURED_STATE.plan_action_identity(
            invented_payload
        )
        invented_action = {
            "action_payload": invented_payload,
            "action_digest": CAPTURED_STATE.plan_action_digest(invented_payload),
        }
        invented_document = valid_document()
        invented_document["provider_routes"][0]["planned_actions"][0][
            "action_identity"
        ] = invented_payload["action_identity"]
        invented_document["provider_routes"][0]["planned_actions"][0][
            "action_digest"
        ] = invented_action["action_digest"]
        invented_document["bindings"][
            "plan_action_set_digest"
        ] = CAPTURED_STATE.plan_action_set_digest(
            invented_document["bindings"]["candidate_identity"],
            invented_document["bindings"]["implementation_manifest_digest"],
            invented_document["bindings"]["plan_digest"],
            [invented_action],
        )

        invented_codes = {
            diagnostic.code
            for diagnostic in validate_document(
                invented_document,
                authoritative_plan_action_set(),
            )
        }
        self.assertIn("PLAN_ACTION_SET_DIGEST_MISMATCH", invented_codes)
        self.assertIn("FORWARD_ACTION_IDENTITY_UNKNOWN", invented_codes)

        unreferenced_document = valid_document()
        unreferenced_document["provider_routes"][0]["planned_actions"] = []
        unreferenced_codes = {
            diagnostic.code
            for diagnostic in validate_document(
                unreferenced_document,
                authoritative_plan_action_set(),
            )
        }
        self.assertIn(
            "AUTHORITATIVE_PLAN_ACTION_UNREFERENCED",
            unreferenced_codes,
        )

        duplicate_reference_document = valid_document()
        duplicate_reference_document["provider_routes"].append(
            copy.deepcopy(duplicate_reference_document["provider_routes"][0])
        )
        duplicate_reference_codes = {
            diagnostic.code
            for diagnostic in validate_document(
                duplicate_reference_document,
                authoritative_plan_action_set(),
            )
        }
        self.assertIn(
            "DUPLICATE_FORWARD_ACTION_REFERENCE",
            duplicate_reference_codes,
        )

    def test_manifest_semantics_fail_closed(self) -> None:
        cases = []

        duplicate_route = valid_document()
        duplicate_route["provider_routes"].append(
            copy.deepcopy(duplicate_route["provider_routes"][0])
        )
        cases.append(("DUPLICATE_ROUTE_ID", duplicate_route))

        duplicate_surface = valid_document()
        duplicate_surface["surfaces"].append(
            copy.deepcopy(duplicate_surface["surfaces"][0])
        )
        cases.append(("DUPLICATE_SURFACE_ID", duplicate_surface))

        duplicate_logical_installation = valid_document()
        cloned_installation = copy.deepcopy(
            duplicate_logical_installation["surfaces"][0]
        )
        cloned_installation["surface_id"] = (
            "surface:fixture/duplicate-plugin-installation"
        )
        cloned_installation["observation"] = {
            "installed": True,
            "channel": "official-marketplace",
            "observed_version": "9.9.9",
            "observation_source": "contradictory clone",
        }
        cloned_installation["recovery"] = {
            "kind": "none",
            "reason": "already_desired",
        }
        duplicate_logical_installation["surfaces"].append(cloned_installation)
        cases.append(
            ("DUPLICATE_LOGICAL_SURFACE", duplicate_logical_installation)
        )

        duplicate_logical_enablement = valid_document()
        enablement = copy.deepcopy(duplicate_logical_enablement["surfaces"][0])
        enablement.update(
            {
                "surface_id": "surface:fixture/plugin-enablement",
                "kind": "plugin_enablement",
                "observation": {
                    "applicable": False,
                    "reason": "not_installed",
                },
                "recovery": {"kind": "none", "reason": "absent_noop"},
            }
        )
        duplicate_logical_enablement["provider_routes"][0][
            "surface_references"
        ]["enablement"] = {
            "status": "captured",
            "surface_id": enablement["surface_id"],
        }
        duplicate_logical_enablement["surfaces"].append(enablement)
        cloned_enablement = copy.deepcopy(enablement)
        cloned_enablement["surface_id"] = (
            "surface:fixture/duplicate-plugin-enablement"
        )
        cloned_enablement["observation"] = {"applicable": True, "enabled": True}
        duplicate_logical_enablement["surfaces"].append(cloned_enablement)
        cases.append(
            ("DUPLICATE_LOGICAL_SURFACE", duplicate_logical_enablement)
        )

        orphan_native_installation = valid_document()
        orphan_installation = copy.deepcopy(orphan_native_installation["surfaces"][0])
        orphan_installation["surface_id"] = "surface:fixture/orphan-installation"
        orphan_installation["locator"]["native_identity"] = "orphan@fixture"
        orphan_native_installation["surfaces"].append(orphan_installation)
        cases.append(("ORPHAN_MUTABLE_SURFACE", orphan_native_installation))

        orphan_claude_skill = valid_document()
        orphan_skill = copy.deepcopy(orphan_claude_skill["surfaces"][2])
        orphan_skill["surface_id"] = "surface:fixture/orphan-claude-skill"
        orphan_skill["equipment_identity"] = "skill:fixture/other"
        orphan_skill["locator"]["path"] = "~/.claude/skills/other"
        orphan_claude_skill["provider_routes"][0]["equipment_identities"].append(
            "skill:fixture/other"
        )
        orphan_claude_skill["surfaces"].append(orphan_skill)
        cases.append(("ORPHAN_MUTABLE_SURFACE", orphan_claude_skill))

        missing_canonical_dependency = valid_document()
        missing_canonical_dependency["provider_routes"][0][
            "surface_references"
        ]["canonical_skill_dependencies"] = []
        cases.append(
            ("CANONICAL_SKILL_DEPENDENCY_MISSING", missing_canonical_dependency)
        )

        duplicate_canonical_dependency = valid_document()
        canonical_clone = copy.deepcopy(
            duplicate_canonical_dependency["surfaces"][1]
        )
        canonical_clone["surface_id"] = "surface:fixture/canonical-skill-copy"
        canonical_clone["locator"]["path"] = "~/.agents/skills/example-copy"
        duplicate_canonical_dependency["surfaces"].append(canonical_clone)
        duplicate_canonical_dependency["provider_routes"][0][
            "surface_references"
        ]["canonical_skill_dependencies"].append(
            {
                "status": "captured",
                "surface_id": canonical_clone["surface_id"],
            }
        )
        cases.append(
            (
                "DUPLICATE_CANONICAL_SKILL_DEPENDENCY",
                duplicate_canonical_dependency,
            )
        )

        mismatched_canonical_dependency = valid_document()
        mismatched_canonical_dependency["surfaces"][1][
            "equipment_identity"
        ] = "skill:fixture/other"
        cases.append(
            (
                "CANONICAL_SKILL_DEPENDENCY_EQUIPMENT_MISMATCH",
                mismatched_canonical_dependency,
            )
        )

        duplicate_mutable_physical_skill = valid_document()
        physical_clone = copy.deepcopy(
            duplicate_mutable_physical_skill["surfaces"][2]
        )
        physical_clone["surface_id"] = "surface:fixture/other-claude-skill"
        physical_clone["equipment_identity"] = "skill:fixture/other"
        duplicate_mutable_physical_skill["provider_routes"][0][
            "equipment_identities"
        ].append("skill:fixture/other")
        duplicate_mutable_physical_skill["provider_routes"][0][
            "surface_references"
        ]["skill_entries"].append(
            {
                "status": "captured",
                "surface_id": physical_clone["surface_id"],
            }
        )
        duplicate_mutable_physical_skill["surfaces"].append(physical_clone)
        cases.append(
            (
                "DUPLICATE_MUTABLE_PHYSICAL_SURFACE",
                duplicate_mutable_physical_skill,
            )
        )

        duplicate_reference = valid_document()
        installation_reference = copy.deepcopy(
            duplicate_reference["provider_routes"][0]["surface_references"][
                "installation"
            ]
        )
        duplicate_reference["provider_routes"][0]["surface_references"][
            "plugin_selections"
        ].append(installation_reference)
        cases.append(("DUPLICATE_SURFACE_REFERENCE", duplicate_reference))

        dangling_reference = valid_document()
        dangling_reference["provider_routes"][0]["surface_references"][
            "installation"
        ]["surface_id"] = "surface:fixture/missing"
        cases.append(("DANGLING_SURFACE_REFERENCE", dangling_reference))

        wrong_reference_kind = valid_document()
        wrong_reference_kind["provider_routes"][0]["surface_references"][
            "plugin_selections"
        ].append(
            {
                "status": "captured",
                "surface_id": "surface:fixture/plugin-installation",
            }
        )
        wrong_reference_kind["provider_routes"][0]["surface_references"][
            "installation"
        ] = {"status": "not_applicable"}
        cases.append(("REFERENCE_KIND_MISMATCH", wrong_reference_kind))

        unknown_surface_route = valid_document()
        unknown_surface_route["surfaces"][1]["route_id"] = "route:fixture/missing"
        cases.append(("UNKNOWN_SURFACE_ROUTE", unknown_surface_route))

        wrong_equipment = valid_document()
        wrong_equipment["surfaces"][1]["equipment_identity"] = "skill:fixture/other"
        cases.append(("SURFACE_EQUIPMENT_MISMATCH", wrong_equipment))

        wrong_ownership = valid_document()
        wrong_ownership["surfaces"][0]["mutation_policy"] = "operator_owned"
        cases.append(("SURFACE_OWNERSHIP_MISMATCH", wrong_ownership))

        canonical_mutable = valid_document()
        canonical_mutable["surfaces"][1]["mutation_policy"] = "reconciler_owned"
        cases.append(("CAPTURED_STATE_SCHEMA_INVALID", canonical_mutable))

        canonical_wrong_root = valid_document()
        canonical_wrong_root["surfaces"][1]["locator"][
            "path"
        ] = "~/.claude/skills/example"
        cases.append(("CAPTURED_STATE_SCHEMA_INVALID", canonical_wrong_root))

        canonical_wrong_recovery = valid_document()
        canonical_wrong_recovery["surfaces"][1]["recovery"] = {
            "kind": "none",
            "reason": "absent_noop",
        }
        cases.append(
            ("CAPTURED_STATE_SCHEMA_INVALID", canonical_wrong_recovery)
        )

        claude_wrong_root = valid_document()
        claude_wrong_root["surfaces"][2]["locator"][
            "path"
        ] = "~/.agents/skills/example"
        cases.append(("CAPTURED_STATE_SCHEMA_INVALID", claude_wrong_root))

        claude_forbidden = valid_document()
        claude_forbidden["surfaces"][2]["mutation_policy"] = "forbidden"
        cases.append(("CAPTURED_STATE_SCHEMA_INVALID", claude_forbidden))

        present_claude_without_recovery = valid_document()
        present_claude_without_recovery["surfaces"][2]["observation"] = {
            "entry_type": "regular_file",
            "metadata": {
                "capture_platform": "fixture",
                "mode": "0644",
                "uid": 501,
                "gid": 20,
                "mtime_ns": "1",
                "flags": 0,
                "acl": {"status": "none"},
                "xattrs": {"status": "none"},
            },
            "size_bytes": 1,
            "content_digest": "sha256:" + "a" * 64,
        }
        cases.append(
            (
                "CLAUDE_SKILL_RECOVERY_MISMATCH",
                present_claude_without_recovery,
            )
        )

        wrong_reference_route = valid_document()
        wrong_reference_route["provider_routes"].append(
            {
                **copy.deepcopy(wrong_reference_route["provider_routes"][0]),
                "route_id": "route:fixture/other",
                "surface_references": {
                    "installation": {
                        "status": "captured",
                        "surface_id": "surface:fixture/plugin-installation",
                    },
                    "enablement": {"status": "not_applicable"},
                    "projector": {"status": "not_applicable"},
                    "mcp_selections": [],
                    "plugin_selections": [],
                    "skill_entries": [],
                    "canonical_skill_dependencies": [],
                },
            }
        )
        wrong_reference_route["provider_routes"][0]["surface_references"][
            "installation"
        ] = {"status": "not_applicable"}
        cases.append(("SURFACE_ROUTE_MISMATCH", wrong_reference_route))

        digest_mismatch = valid_document()
        digest_mismatch["bindings"]["capability_set_digest"] = "sha256:" + "9" * 64
        cases.append(("CAPABILITY_SET_DIGEST_MISMATCH", digest_mismatch))

        unsorted_capabilities = valid_document()
        second_binding = {
            "capability_identity": "capability:aaa",
            "capability_digest": "sha256:" + "8" * 64,
            "manager_version_evidence_digest": "sha256:" + "9" * 64,
        }
        unsorted_capabilities["bindings"]["capability_bindings"].append(
            second_binding
        )
        unsorted_capabilities["bindings"][
            "capability_set_digest"
        ] = CAPTURED_STATE.capability_set_digest(
            unsorted_capabilities["bindings"]["capability_bindings"]
        )
        cases.append(("CAPABILITY_BINDINGS_NOT_SORTED", unsorted_capabilities))

        unknown_capability = valid_document()
        unknown_capability["provider_routes"][0]["capability_binding"][
            "capability_identity"
        ] = "capability:missing"
        cases.append(("ROUTE_CAPABILITY_BINDING_UNKNOWN", unknown_capability))

        duplicate_capability = valid_document()
        duplicate_capability["bindings"]["capability_bindings"].append(
            copy.deepcopy(CAPABILITY_BINDING)
        )
        cases.append(("DUPLICATE_CAPABILITY_IDENTITY", duplicate_capability))

        for expected_code, document in cases:
            with self.subTest(expected_code=expected_code):
                codes = {
                    diagnostic.code
                    for diagnostic in validate_document(document)
                }
                self.assertIn(expected_code, codes)

    def test_malformed_manifest_returns_a_diagnostic_instead_of_crashing(self) -> None:
        diagnostics = validate_document(
            {"bindings": {"capability_bindings": "not-an-array"}}
        )

        self.assertEqual(diagnostics[0].code, "CAPTURED_STATE_SCHEMA_INVALID")

        malformed_plan_action_set = authoritative_plan_action_set()
        malformed_plan_action_set["unexpected"] = True
        diagnostics = validate_document(valid_document(), malformed_plan_action_set)
        self.assertEqual(
            diagnostics[0].code,
            "AUTHORITATIVE_PLAN_ACTION_SET_SCHEMA_INVALID",
        )

        secret_canary = "CAPTURED_STATE_SECRET_CANARY_1ccac130"
        secret_bearing_plan_action_set = authoritative_plan_action_set()
        secret_bearing_plan_action_set["actions"][0]["action_payload"][
            "unexpected"
        ] = secret_canary
        diagnostics = validate_document(
            valid_document(),
            secret_bearing_plan_action_set,
        )
        self.assertNotIn(secret_canary, repr(diagnostics))

        with self.assertRaises(TypeError):
            CAPTURED_STATE.validate_captured_state(valid_document())
        with self.assertRaises(TypeError):
            CAPTURED_STATE.validate_captured_state(
                valid_document(),
                authoritative_plan_action_set(),
            )

    def test_public_and_cli_gates_reject_schema_invalid_locators(self) -> None:
        invalid_documents: list[tuple[str, dict[str, object]]] = []
        for surface_index, root in (
            (1, "~/.agents/skills/"),
            (2, "~/.claude/skills/"),
        ):
            for basename in (".", "..", "nested\\name", "nul\0name"):
                schema_invalid = valid_document()
                schema_invalid["surfaces"][surface_index]["locator"]["path"] = (
                    root + basename
                )
                invalid_documents.append((f"{root}{basename!r}", schema_invalid))
        for field in ("manager", "native_identity", "scope"):
            invalid_native = valid_document()
            invalid_native["surfaces"][0]["locator"][field] = ""
            invalid_documents.append((f"native:{field}", invalid_native))

        for label, invalid_document in invalid_documents:
            with self.subTest(public=label):
                self.assertEqual(
                    validate_document(invalid_document)[0].code,
                    "CAPTURED_STATE_SCHEMA_INVALID",
                )

        with tempfile.TemporaryDirectory() as directory:
            plan_actions_path = Path(directory) / "authoritative-plan-actions.json"
            plan_actions_path.write_text(
                json.dumps(authoritative_plan_action_set()),
                encoding="utf-8",
            )
            for index, (label, invalid_document) in enumerate(invalid_documents):
                manifest_path = Path(directory) / f"schema-invalid-{index}.json"
                manifest_path.write_text(
                    json.dumps(invalid_document),
                    encoding="utf-8",
                )
                result = subprocess.run(
                    validation_cli_args(plan_actions_path, manifest_path),
                    cwd=ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                with self.subTest(cli=label):
                    self.assertEqual(1, result.returncode)
                    self.assertIn("CAPTURED_STATE_SCHEMA_INVALID", result.stderr)

    def test_cli_exits_nonzero_for_a_semantic_error(self) -> None:
        document = valid_document()
        document["bindings"]["capability_set_digest"] = "sha256:" + "9" * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid-semantic-state.json"
            plan_actions_path = Path(directory) / "authoritative-plan-actions.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            plan_actions_path.write_text(
                json.dumps(authoritative_plan_action_set()),
                encoding="utf-8",
            )
            result = subprocess.run(
                validation_cli_args(plan_actions_path, path),
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("CAPABILITY_SET_DIGEST_MISMATCH", result.stderr)

    def test_cli_rejects_artifacts_from_a_different_current_candidate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "captured-state.json"
            action_set_path = Path(directory) / "plan-actions.json"
            manifest_path.write_text(
                json.dumps(valid_document()),
                encoding="utf-8",
            )
            action_set_path.write_text(
                json.dumps(authoritative_plan_action_set()),
                encoding="utf-8",
            )
            result = subprocess.run(
                validation_cli_args(
                    action_set_path,
                    manifest_path,
                    candidate_identity="candidate:fixture/controller-v2",
                    implementation_manifest_digest="sha256:" + "b" * 64,
                ),
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            omitted = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/agent_equipment_captured_state.py"),
                    "--authoritative-plan-actions",
                    str(action_set_path),
                    str(manifest_path),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("TRUSTED_CANDIDATE_IDENTITY_MISMATCH", result.stderr)
        self.assertIn(
            "TRUSTED_IMPLEMENTATION_MANIFEST_DIGEST_MISMATCH",
            result.stderr,
        )
        self.assertNotEqual(0, omitted.returncode)
        self.assertIn("--expected-candidate-identity", omitted.stderr)

    def test_diagnostics_never_echo_captured_identifiers(self) -> None:
        secret_canary = "CAPTURED_STATE_SECRET_CANARY_6b22b82a"
        document = valid_document()
        document["surfaces"][0]["surface_id"] = secret_canary
        document["surfaces"][0]["recovery"][
            "expected_pre_state_digest"
        ] = "sha256:" + "f" * 64
        document["provider_routes"][0]["surface_references"]["installation"][
            "surface_id"
        ] = secret_canary
        document["provider_routes"][0]["planned_actions"][0][
            "write_bindings"
        ][0]["surface_id"] = secret_canary

        diagnostics = validate_document(document)
        self.assertIn(
            "NATIVE_REMOVE_INVERSE_GUARD_MISMATCH",
            {diagnostic.code for diagnostic in diagnostics},
        )
        self.assertNotIn(secret_canary, repr(diagnostics))

        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "captured-state.json"
            action_set_path = Path(directory) / "plan-actions.json"
            manifest_path.write_text(json.dumps(document), encoding="utf-8")
            action_set_path.write_text(
                json.dumps(authoritative_plan_action_set()),
                encoding="utf-8",
            )
            result = subprocess.run(
                validation_cli_args(action_set_path, manifest_path),
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("NATIVE_REMOVE_INVERSE_GUARD_MISMATCH", result.stderr)
        self.assertNotIn(secret_canary, result.stderr)

    def test_cli_rejects_ambiguous_or_nonstandard_json(self) -> None:
        document_text = json.dumps(valid_document())
        action_set_text = json.dumps(authoritative_plan_action_set())
        duplicate_document_key = document_text.replace(
            '"migration_id": "fixture-captured-state"',
            (
                '"migration_id": "fixture-captured-state", '
                '"migration_id": "shadow"'
            ),
            1,
        )
        nonstandard_document_constant = document_text.replace(
            '"captured_at": "2026-08-12T00:00:00Z"',
            '"captured_at": NaN',
            1,
        )
        duplicate_action_set_key = action_set_text.replace(
            '"plan_digest": "sha256:' + "2" * 64 + '"',
            (
                '"plan_digest": "sha256:'
                + "2" * 64
                + '", "plan_digest": "sha256:'
                + "f" * 64
                + '"'
            ),
            1,
        )
        nonstandard_action_set_constant = action_set_text.replace(
            '"action_set_digest": "' + PLAN_ACTION_SET_DIGEST + '"',
            '"action_set_digest": Infinity',
            1,
        )
        cases = (
            (
                "captured duplicate",
                duplicate_document_key,
                action_set_text,
                "CAPTURED_STATE_READ_FAILED",
            ),
            (
                "captured constant",
                nonstandard_document_constant,
                action_set_text,
                "CAPTURED_STATE_READ_FAILED",
            ),
            (
                "action-set duplicate",
                document_text,
                duplicate_action_set_key,
                "AUTHORITATIVE_PLAN_ACTION_SET_READ_FAILED",
            ),
            (
                "action-set constant",
                document_text,
                nonstandard_action_set_constant,
                "AUTHORITATIVE_PLAN_ACTION_SET_READ_FAILED",
            ),
        )

        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "captured-state.json"
            action_set_path = Path(directory) / "plan-actions.json"
            for label, manifest_text, actions_text, expected_code in cases:
                manifest_path.write_text(manifest_text, encoding="utf-8")
                action_set_path.write_text(actions_text, encoding="utf-8")
                result = subprocess.run(
                    validation_cli_args(action_set_path, manifest_path),
                    cwd=ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                with self.subTest(label=label):
                    self.assertEqual(1, result.returncode)
                    self.assertIn(expected_code, result.stderr)


if __name__ == "__main__":
    unittest.main()
