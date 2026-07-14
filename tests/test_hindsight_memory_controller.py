import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import runpy
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "home/private_dot_local/bin/executable_hindsight-memory"
LIB = ROOT / "home/private_dot_local/lib"
if str(LIB) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(LIB))

from hindsight_memory_control_plane import (
    OperationSnapshot,
    PlanError,
    build_plan,
    build_mutation_plan,
    canonical_bytes,
    load_inventory,
    verify_plan,
)
from hindsight_memory_control_plane.canonical import digest
from hindsight_memory_control_plane.adapters import FakeAdapter
from hindsight_memory_control_plane.ledger import LedgerError, append_record


def inventory():
    return {
        "schema_version": 1,
        "machine": {"id": "test-mac", "base_port": 7979},
        "archetype": {"id": "trusted-workstation"},
        "profiles": [
            {
                "id": "core",
                "slot": 0,
                "enabled": True,
                "host": "127.0.0.1",
                "roles": {
                    "llm": "local-llm",
                    "embedding": "local-embedding",
                    "reranking": "local-reranker",
                },
                "data_classes": ["engineering", "personal"],
            }
        ],
        "providers": [
            {
                "id": "local-llm",
                "role": "llm",
                "placement": "local",
                "data_classes": ["engineering", "personal"],
            },
            {
                "id": "local-embedding",
                "role": "embedding",
                "placement": "local",
                "data_classes": ["engineering", "personal"],
            },
            {
                "id": "local-reranker",
                "role": "reranking",
                "placement": "local",
                "data_classes": ["engineering", "personal"],
            },
        ],
        "banks": [
            {
                "id": "engineering",
                "profile_id": "core",
                "data_class": "engineering",
                "authority": "authoritative",
                "writable": True,
            }
        ],
        "harnesses": [
            {
                "id": "codex",
                "profile_id": "core",
                "home_bank": {"profile_id": "core", "bank_id": "engineering"},
            }
        ],
        "migration": {
            "artifact_dir": "/tmp/hindsight-artifacts",
            "proposal_log": "/tmp/hindsight-proposals.md",
        },
        "policy": {
            "engineering_memory_enabled": True,
            "allowed_placements": {
                "engineering": ["local", "private-remote"],
                "personal": ["local", "private-remote"],
            },
        },
    }


class ControllerCliTest(unittest.TestCase):
    def run_cli(self, state_dir, *args):
        return subprocess.run(
            ["python3", str(CLI), "--state-dir", str(state_dir), *map(str, args)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def write_json(self, path, value, *, pretty=False):
        path.write_text(
            json.dumps(value, indent=2 if pretty else None, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_canonical_json_rejects_non_finite_numbers(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_bytes({"value": value})

    def test_rollback_archive_overlap_detects_path_and_inode_aliases(self):
        module = runpy.run_path(str(CLI))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            incoming = root / "incoming.zip"
            incoming.write_bytes(b"archive")
            hardlink = root / "hardlink.zip"
            os.link(incoming, hardlink)
            self.assertTrue(module["_paths_overlap"](incoming, [incoming]))
            self.assertTrue(module["_paths_overlap"](hardlink, [incoming]))
            self.assertFalse(module["_paths_overlap"](root / "rollback.tar", [incoming]))

    def test_apply_cli_uses_selected_inventory_plan_and_fresh_rollback(self):
        module = runpy.run_path(str(CLI))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory_path = root / "inventory.json"
            plan_path = root / "plan.json"
            self.write_json(inventory_path, inventory())
            desired = load_inventory(inventory_path)
            endpoint = {
                "profile_id": "core", "scheme": "http", "host": "127.0.0.1",
                "port": 7979, "tenant": "default",
            }
            state = {"banks": []}
            plan = build_plan(
                desired,
                {"profile_id": "core", "endpoint": endpoint, "state": state, "compatibility": []},
                {"idle": True, "active": []},
            )
            self.write_json(plan_path, plan.to_dict())
            adapter = FakeAdapter(endpoint=endpoint, state=state)
            args = module["argparse"].Namespace(
                inventory=str(inventory_path),
                profile="core",
                plan=str(plan_path),
                approval_digest=plan.plan_digest,
                token_env="HINDSIGHT_TEST_TOKEN",
                completion_marker=None,
            )
            output = StringIO()
            with (
                patch.dict(os.environ, {"HINDSIGHT_TEST_TOKEN": "local-test-token"}),
                patch.dict(module["apply_command"].__globals__, {"HttpAdapter": lambda **_kwargs: adapter}),
                redirect_stdout(output),
            ):
                self.assertEqual(module["apply_command"](args), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["status"], "applied")
            self.assertEqual(
                result["applied_action_ids"],
                ["01-create-bank-engineering", "02-configure-bank-engineering"],
            )
            self.assertIn("create_rollback_bundle", [call["method"] for call in adapter.calls])
            methods = [call["method"] for call in adapter.calls]
            self.assertLess(methods.index("create_rollback_bundle"), methods.index("create_bank"))

    def test_apply_cli_routes_mutation_through_digest_selected_admin_archive(self):
        module = runpy.run_path(str(CLI))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory_path = root / "inventory.json"
            plan_path = root / "plan.json"
            marker = root / "artifacts" / "distillation-complete.marker"
            proposal = root / "proposal.md"
            value = inventory()
            value["migration"] = {"artifact_dir": str(marker.parent), "proposal_log": str(proposal)}
            self.write_json(inventory_path, value)
            desired = load_inventory(inventory_path)
            endpoint = {"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"}
            state = {"banks": []}
            base = build_plan(
                desired, {"profile_id": "core", "endpoint": endpoint, "state": state, "compatibility": []},
                {"idle": True, "active": []},
            )
            archive = root / "approved-bank.zip"
            archive.write_bytes(b"approved migration archive")
            archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            rollback_payload = b"verified pre-state rollback archive"
            rollback_digest = hashlib.sha256(rollback_payload).hexdigest()
            rollback_archive = root / "pre-state-backup.tar"
            migration_digest = "3" * 64
            plan = build_mutation_plan(
                base, migration_run_id="run-1", migration_artifact_digest=migration_digest,
                rollback_archive_digest=rollback_digest,
                actions=[{
                    "id": "migrate-1", "kind": "migrate_bank",
                    "artifact_digest": migration_digest, "archive_digest": archive_digest,
                }],
            )
            self.write_json(plan_path, plan.to_dict())
            marker.parent.mkdir()
            marker.write_text(f"run=run-1\nartifact={migration_digest}\n", encoding="utf-8")
            proposal.write_text(
                f"## Migration complete\nrun=run-1\nartifact={migration_digest}\n", encoding="utf-8",
            )
            evidence_path = root / "restore-evidence.json"
            self.write_json(evidence_path, {archive_digest: {
                "disposable": True, "restore_verified": True, "artifact_digest": archive_digest,
            }, rollback_digest: {
                "disposable": True, "restore_verified": True, "artifact_digest": rollback_digest,
            }})
            adapter = FakeAdapter(endpoint=endpoint, state=state)
            args = module["argparse"].Namespace(
                inventory=str(inventory_path), profile="core", plan=str(plan_path),
                approval_digest=plan.plan_digest, token_env="HINDSIGHT_TEST_TOKEN",
                completion_marker=str(marker), migration_archive=[str(archive)],
                restore_evidence=str(evidence_path), admin_version="1",
                rollback_archive=str(rollback_archive),
            )
            admin_calls = []

            def run_admin(argv, **_kwargs):
                admin_calls.append(argv)
                if argv[1] == "backup":
                    rollback_archive.write_bytes(rollback_payload)
                return subprocess.CompletedProcess(argv, 0, "{}", "")

            with (
                patch.dict(os.environ, {"HINDSIGHT_TEST_TOKEN": "local-test-token"}),
                patch.dict(module["apply_command"].__globals__, {"HttpAdapter": lambda **_kwargs: adapter}),
                patch.object(module["subprocess"], "run", side_effect=run_admin),
                redirect_stdout(StringIO()),
            ):
                self.assertEqual(module["apply_command"](args), 0)
            self.assertEqual(admin_calls[0][0:2], ["hindsight-admin", "backup"])
            self.assertEqual(admin_calls[1][0:2], ["hindsight-admin", "import-bank"])
            self.assertIn(str(archive), admin_calls[1])
            self.assertIn(archive_digest, admin_calls[1])

    def test_broker_pid_read_is_bounded_and_disappearance_is_invalid(self):
        module = runpy.run_path(str(CLI))
        read_broker_pid = module["_read_broker_pid"]
        broker_error = module["BrokerError"]
        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory) / "broker.pid"
            pid_path.write_bytes(b"9" * (1024 * 1024))
            os.chmod(pid_path, 0o600)
            with patch.object(module["os"], "read", wraps=os.read) as read:
                with self.assertRaisesRegex(broker_error, "BROKER_PID_INVALID"):
                    read_broker_pid(pid_path)
            self.assertFalse(read.called)
            pid_path.write_bytes(b"not-a-pid")
            with patch.object(module["os"], "read", wraps=os.read) as read:
                with self.assertRaisesRegex(broker_error, "BROKER_PID_INVALID"):
                    read_broker_pid(pid_path)
            self.assertTrue(read.called)
            self.assertTrue(all(call.args[1] <= 257 for call in read.call_args_list))

        class DisappearingPath:
            def __fspath__(self):
                return "/definitely/missing/broker.pid"

            def lstat(self):
                return type("Metadata", (), {"st_mode": stat.S_IFREG | 0o600, "st_size": 3})()

        with self.assertRaisesRegex(broker_error, "BROKER_PID_INVALID"):
            read_broker_pid(DisappearingPath())

    def test_failed_broker_pid_write_removes_the_partial_file(self):
        module = runpy.run_path(str(CLI))
        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory) / "broker.pid"
            with patch.object(module["os"], "write", return_value=0):
                with self.assertRaises(OSError):
                    module["_write_broker_pid"](pid_path)
            self.assertFalse(pid_path.exists())

            def replace_pid(_descriptor, _body):
                pid_path.unlink()
                pid_path.write_text("replacement", encoding="utf-8")
                return 0

            with patch.object(module["os"], "write", side_effect=replace_pid):
                with self.assertRaises(OSError):
                    module["_write_broker_pid"](pid_path)
            self.assertEqual(pid_path.read_text(encoding="utf-8"), "replacement")

    def test_failed_private_artifact_write_removes_only_its_partial_file(self):
        module = runpy.run_path(str(CLI))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "plan.json"
            with patch.object(module["os"], "write", return_value=0):
                with self.assertRaises(OSError):
                    module["write_private"](target, {"schema_version": 1})
            self.assertFalse(target.exists())

            target.write_text("previous", encoding="utf-8")
            with patch.object(module["os"], "write", return_value=0):
                with self.assertRaises(OSError):
                    module["write_private"](target, {"schema_version": 1})
            self.assertEqual(target.read_text(encoding="utf-8"), "previous")

            def replace_target(_descriptor, _body):
                target.unlink()
                target.write_text("replacement", encoding="utf-8")
                return 0

            with patch.object(module["os"], "write", side_effect=replace_target):
                with self.assertRaises(OSError):
                    module["write_private"](target, {"schema_version": 1})
            self.assertEqual(target.read_text(encoding="utf-8"), "replacement")

    def test_broker_serve_refuses_a_live_pid_when_the_probe_is_unhealthy(self):
        module = runpy.run_path(str(CLI))
        broker_error = module["BrokerError"]
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            state.mkdir(mode=0o700)
            pid_path = state / "broker.pid"
            pid_path.write_text(
                json.dumps({"pid": 12345, "start_time": "process-start"}),
                encoding="ascii",
            )
            os.chmod(pid_path, 0o600)
            args = module["argparse"].Namespace(
                state_dir=str(state),
                socket=str(state / "broker.sock"),
                profile=["example"],
                shutdown_timeout=1.0,
            )
            with patch.dict(
                module["broker_serve_command"].__globals__,
                {
                    "_process_running": lambda _pid: True,
                    "_process_start_time": lambda _pid: "process-start",
                    "_broker_probe": lambda _path, timeout=1.0: False,
                },
            ):
                with self.assertRaisesRegex(broker_error, "BROKER_ALREADY_RUNNING"):
                    module["broker_serve_command"](args)
            self.assertIn("process-start", pid_path.read_text(encoding="ascii"))

    def test_broker_stop_rejects_a_reused_pid_without_signaling(self):
        module = runpy.run_path(str(CLI))
        broker_error = module["BrokerError"]
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            state.mkdir(mode=0o700)
            pid_path = state / "broker.pid"
            pid_path.write_text(
                json.dumps({"pid": 12345, "start_time": "original-start"}),
                encoding="ascii",
            )
            os.chmod(pid_path, 0o600)
            args = module["argparse"].Namespace(
                state_dir=str(state),
                socket=str(state / "broker.sock"),
                timeout=0.0,
            )
            with (
                patch.dict(
                    module["broker_stop_command"].__globals__,
                    {
                        "_process_running": lambda _pid: True,
                        "_process_start_time": lambda _pid: "replacement-start",
                    },
                ),
                patch.object(module["os"], "kill") as kill,
            ):
                with self.assertRaisesRegex(broker_error, "BROKER_PID_IDENTITY_INVALID"):
                    module["broker_stop_command"](args)
            kill.assert_not_called()
            self.assertTrue(pid_path.exists())

    def test_broker_stop_removes_a_stale_pid_file(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            state.mkdir(mode=0o700)
            pid_path = state / "broker.pid"
            pid_path.write_text("999999999", encoding="ascii")
            os.chmod(pid_path, 0o600)
            result = self.run_cli(
                state,
                "broker", "stop",
                "--socket", state / "broker.sock",
                "--timeout", "0.1",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(pid_path.exists())

    def test_broker_stop_normalizes_a_late_signal_permission_failure(self):
        module = runpy.run_path(str(CLI))
        broker_error = module["BrokerError"]
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            state.mkdir(mode=0o700)
            pid_path = state / "broker.pid"
            pid_path.write_text(
                json.dumps({"pid": 12345, "start_time": "process-start"}),
                encoding="ascii",
            )
            os.chmod(pid_path, 0o600)

            def kill(_pid, signal_number):
                if signal_number == 0:
                    return None
                raise PermissionError("signal denied")

            args = module["argparse"].Namespace(
                state_dir=str(state),
                socket=str(state / "broker.sock"),
                timeout=0.0,
            )
            with (
                patch.dict(
                    module["broker_stop_command"].__globals__,
                    {"_process_start_time": lambda _pid: "process-start"},
                ),
                patch.object(module["os"], "kill", side_effect=kill),
            ):
                with self.assertRaisesRegex(broker_error, "BROKER_STOP_TIMEOUT"):
                    module["broker_stop_command"](args)

    def test_broker_stop_refuses_state_outside_a_private_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            state.mkdir(mode=0o755)
            socket_path = state / "broker.sock"
            socket_path.write_text("preserve", encoding="utf-8")
            result = self.run_cli(
                state,
                "broker", "stop",
                "--socket", socket_path,
                "--timeout", "0.1",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(socket_path.read_text(encoding="utf-8"), "preserve")

    def test_broker_stop_refuses_non_socket_cleanup_paths(self):
        for path_kind in ("regular", "symlink"):
            with self.subTest(path_kind=path_kind), tempfile.TemporaryDirectory() as directory:
                state = Path(directory) / "state"
                state.mkdir(mode=0o700)
                socket_path = state / "broker.sock"
                protected = state / "protected"
                if path_kind == "regular":
                    socket_path.write_text("preserve", encoding="utf-8")
                else:
                    protected.write_text("preserve", encoding="utf-8")
                    socket_path.symlink_to(protected)
                result = self.run_cli(
                    state,
                    "broker", "stop",
                    "--socket", socket_path,
                    "--timeout", "0.1",
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("BROKER_PATH_INVALID", result.stderr)
                if path_kind == "regular":
                    self.assertEqual(socket_path.read_text(encoding="utf-8"), "preserve")
                else:
                    self.assertTrue(socket_path.is_symlink())
                    self.assertEqual(protected.read_text(encoding="utf-8"), "preserve")

    def test_private_artifact_writes_refuse_symlink_destinations(self):
        module = runpy.run_path(str(CLI))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protected = root / "protected.json"
            protected.write_text("preserve", encoding="utf-8")
            destination = root / "plan.json"
            destination.symlink_to(protected)
            with self.assertRaises(OSError):
                module["write_private"](destination, {"schema_version": 1})
            self.assertEqual(protected.read_text(encoding="utf-8"), "preserve")

            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaises(OSError):
                module["write_private"](
                    linked_parent / "plan.json",
                    {"schema_version": 1},
                )
            self.assertFalse((real_parent / "plan.json").exists())

    def test_validate_is_closed_and_reports_a_known_canonical_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            compact = tmp / "compact.json"
            pretty = tmp / "pretty.json"
            self.write_json(compact, inventory())
            self.write_json(pretty, inventory(), pretty=True)

            expected = "e240cb5a96a1ea63de338e695798b4e190414ead42db0ac107a2858bbf83fad7"
            for fixture in (compact, pretty):
                result = self.run_cli(tmp, "validate", "--inventory", fixture)
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)
                self.assertEqual(output["inventory_digest"], expected)
                self.assertRegex(output["artifact_digest"], r"^[0-9a-f]{64}$")

            for key in ("policy",):
                invalid = inventory()
                del invalid[key]
                fixture = tmp / f"missing-{key}.json"
                self.write_json(fixture, invalid)
                result = self.run_cli(tmp, "validate", "--inventory", fixture)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("root keys", result.stderr)

            invalid = inventory()
            invalid["surprise"] = True
            fixture = tmp / "unknown.json"
            self.write_json(fixture, invalid)
            result = self.run_cli(tmp, "validate", "--inventory", fixture)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("root keys", result.stderr)

            invalid = inventory()
            invalid["banks"].append(dict(invalid["banks"][0]))
            fixture = tmp / "duplicate.json"
            self.write_json(fixture, invalid)
            result = self.run_cli(tmp, "validate", "--inventory", fixture)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate banks id", result.stderr)

    def test_validate_rejects_references_authority_ports_placement_and_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            invalid_cases = []

            disabled_reference = inventory()
            disabled_reference["profiles"][0]["enabled"] = False
            disabled_reference["profiles"][0]["roles"]["llm"] = "missing-provider"
            invalid_cases.append((disabled_reference, "unknown provider"))

            split_brain = inventory()
            split_brain["banks"].append({"id": "engineering-2", "profile_id": "core", "data_class": "engineering", "authority": "authoritative", "writable": True})
            invalid_cases.append((split_brain, "exactly one authoritative write bank"))

            collision = inventory()
            collision["profiles"].append({**collision["profiles"][0], "id": "other", "slot": 1, "port": 7979})
            invalid_cases.append((collision, "endpoint collision"))

            forbidden = inventory()
            forbidden["providers"][0]["placement"] = "third-party-hosted"
            invalid_cases.append((forbidden, "placement is forbidden"))

            relative_path = inventory()
            relative_path["migration"]["artifact_dir"] = "artifacts"
            invalid_cases.append((relative_path, "path must be absolute"))

            for index, (value, message) in enumerate(invalid_cases):
                fixture = tmp / f"invalid-{index}.json"
                self.write_json(fixture, value)
                result = self.run_cli(tmp, "validate", "--inventory", fixture)
                self.assertNotEqual(result.returncode, 0, f"case {index} unexpectedly passed")
                self.assertIn(message, result.stderr)

    def test_validate_rejects_invalid_unreferenced_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            invalid_providers = [
                {"id": "unused", "role": "secret", "placement": "local", "data_classes": ["engineering"]},
                {"id": "unused", "role": "llm", "placement": "elsewhere", "data_classes": ["engineering"]},
                {"id": "unused", "role": "llm", "placement": "local", "data_classes": "engineering"},
                {"id": "unused", "role": "llm", "placement": "local", "data_classes": ["engineering", 7]},
            ]
            for index, provider in enumerate(invalid_providers):
                value = inventory()
                value["providers"].append(provider)
                fixture = tmp / f"provider-{index}.json"
                self.write_json(fixture, value)
                result = self.run_cli(tmp, "validate", "--inventory", fixture)
                self.assertNotEqual(result.returncode, 0, f"unreferenced provider case {index} unexpectedly passed")
                self.assertIn("provider unused", result.stderr)

    def test_validate_requires_boolean_bank_writable(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            for index, writable in enumerate(("false", 1, 0, None, [], {})):
                value = inventory()
                value["banks"][0]["writable"] = writable
                fixture = tmp / f"writable-{index}.json"
                self.write_json(fixture, value)
                result = self.run_cli(tmp, "validate", "--inventory", fixture)
                self.assertNotEqual(result.returncode, 0, f"non-boolean writable case {index} unexpectedly passed")
                self.assertIn("writable must be boolean", result.stderr)

    def test_plan_is_digest_bound_canonical_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            fixture = tmp / "inventory.json"
            live = tmp / "live.json"
            operations = tmp / "operations.json"
            output = tmp / "plan.json"
            self.write_json(fixture, inventory())
            self.write_json(
                live,
                {
                    "profile_id": "core",
                    "endpoint": {
                        "profile_id": "core",
                        "scheme": "http",
                        "host": "127.0.0.1",
                        "port": 7979,
                        "tenant": "default",
                    },
                    "state": {"banks": []},
                    "compatibility": [{"check": "provider-contract", "compatible": True}],
                },
            )
            self.write_json(operations, {"idle": True, "active": []})

            result = self.run_cli(
                tmp,
                "plan",
                "--inventory", fixture,
                "--live-state", live,
                "--operations", operations,
                "--output", output,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                set(value),
                {
                    "schema_version", "inventory_digest", "artifact_digest",
                    "target_profile", "target_endpoint", "live_state_digest",
                    "operations", "compatibility", "actions", "destructive",
                    "plan_digest",
                },
            )
            self.assertEqual(value["target_endpoint"]["port"], 7979)
            self.assertEqual(value["operations"], {"active": [], "idle": True})
            self.assertEqual(
                [a["id"] for a in value["actions"]],
                ["01-create-bank-engineering", "02-configure-bank-engineering"],
            )
            self.assertEqual(
                value["actions"][1]["artifact_digest"],
                hashlib.sha256(
                    json.dumps(
                        inventory()["banks"][0],
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
            )
            self.assertFalse(value["destructive"])
            body = dict(value)
            plan_digest = body.pop("plan_digest")
            canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            self.assertEqual(plan_digest, hashlib.sha256(canonical).hexdigest())
            self.assertEqual(output.read_bytes(), json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n")
            self.assertEqual(os.stat(output).st_mode & 0o777, 0o600)

            status = self.run_cli(
                tmp,
                "status",
                "--inventory", fixture,
                "--live-state", live,
                "--plan", output,
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertEqual(
                {key: json.loads(status.stdout)[key] for key in ("desired_agrees", "live_agrees", "plan_agrees")},
                {"desired_agrees": True, "live_agrees": True, "plan_agrees": True},
            )

    def test_plan_rejects_caller_supplied_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            fixture = tmp / "inventory.json"
            operations = tmp / "operations.json"
            self.write_json(fixture, inventory())
            self.write_json(operations, {"idle": True, "active": []})
            for suffix in ({}, {"destructive": False}):
                live = tmp / f"live-{len(suffix)}.json"
                self.write_json(
                    live,
                    {
                        "profile_id": "core",
                        "endpoint": {"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"},
                        "state": {},
                        "compatibility": [],
                        "actions": [{"id": "delete-1", "kind": "delete_bank", "bank": {"profile_id": "core", "bank_id": "engineering"}, **suffix}],
                    },
                )
                result = self.run_cli(tmp, "plan", "--inventory", fixture, "--live-state", live, "--operations", operations)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("cannot supply proposed actions", result.stderr)

    def test_plan_derives_semantic_actions_from_desired_and_observed_state(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            fixture = tmp / "inventory.json"
            value = inventory()
            value["banks"][0].update(
                {
                    "enable_auto_consolidation": False,
                    "memory_defense": True,
                    "models": [{"id": "summary", "revision": "v2"}],
                    "directives": [{"id": "grounded", "text": "Use live truth."}],
                }
            )
            self.write_json(fixture, value)
            desired = load_inventory(fixture)
            live = {
                "profile_id": "core",
                "endpoint": {
                    "profile_id": "core", "scheme": "http",
                    "host": "127.0.0.1", "port": 7979, "tenant": "default",
                },
                "state": {
                    "banks": [
                        {
                            "id": "engineering",
                            "artifact_digest": "0" * 64,
                            "enable_auto_consolidation": True,
                            "memory_defense": False,
                            "models": [{"id": "summary", "revision": "v1", "artifact_digest": "1" * 64}],
                            "directives": [],
                        },
                        {"id": "unmanaged"},
                    ]
                },
                "compatibility": [],
            }
            plan = build_plan(desired, live, {"idle": True, "active": []})
            self.assertEqual(
                [action.kind for action in plan.actions],
                [
                    "configure_bank", "set_auto_consolidation",
                    "set_memory_defense", "upsert_model",
                    "upsert_directive", "report_unmanaged",
                ],
            )
            for action in plan.actions:
                if "bank" in action.details:
                    self.assertEqual(action.details["bank"]["profile_id"], "core")
                else:
                    self.assertEqual(action.details["profile_id"], "core")

            bank = value["banks"][0]
            matching = {
                **live,
                "state": {
                    "banks": [
                        {
                            "id": "engineering",
                            "artifact_digest": digest(bank.get("config", bank)),
                            "enable_auto_consolidation": False,
                            "memory_defense": True,
                            "models": [
                                {
                                    "id": "summary", "revision": "v2",
                                    "artifact_digest": digest(bank["models"][0]),
                                }
                            ],
                            "directives": [
                                {
                                    "id": "grounded",
                                    "artifact_digest": digest(bank["directives"][0]),
                                }
                            ],
                        }
                    ]
                },
            }
            self.assertEqual(
                build_plan(desired, matching, {"idle": True, "active": []}).actions,
                (),
            )

    def test_plan_artifacts_reject_private_and_payload_carriers(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            fixture = tmp / "inventory.json"
            live = tmp / "live.json"
            operations = tmp / "operations.json"
            self.write_json(fixture, inventory())
            base_live = {
                "profile_id": "core",
                "endpoint": {"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"},
                "state": {"banks": []},
                "compatibility": [{"check": "provider-contract", "compatible": True}],
            }
            adversarial = [
                ({"idle": False, "active": [{"id": "op-1", "kind": "retain", "status": "running", "token": "private"}]}, base_live, "operations"),
                ({"idle": True, "active": []}, {**base_live, "compatibility": [{"check": "provider-contract", "compatible": True, "api_key": "private"}]}, "compatibility"),
                ({"idle": True, "active": []}, {**base_live, "actions": [{"id": "create-1", "kind": "create_bank", "control_key": "private"}]}, "cannot supply proposed actions"),
                ({"idle": True, "active": []}, {**base_live, "actions": [{"id": "create-1", "kind": "create_bank", "metadata": {"note": "innocuous nested payload"}}]}, "cannot supply proposed actions"),
            ]
            for index, (operation_value, live_value, message) in enumerate(adversarial):
                self.write_json(operations, operation_value)
                self.write_json(live, live_value)
                result = self.run_cli(tmp, "plan", "--inventory", fixture, "--live-state", live, "--operations", operations)
                self.assertNotEqual(result.returncode, 0, f"adversarial case {index} unexpectedly passed")
                self.assertIn(message, result.stderr)

            desired = load_inventory(fixture)
            with self.assertRaisesRegex(PlanError, "operations entry"):
                build_plan(
                    desired,
                    base_live,
                    OperationSnapshot(False, ({"id": "op-1", "kind": "retain", "status": "running", "signing_key": "private"},)),
                )

    def test_plan_owns_immutable_copies_of_all_nested_values(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            fixture = tmp / "inventory.json"
            self.write_json(fixture, inventory())
            desired = load_inventory(fixture)
            live = {
                "profile_id": "core",
                "endpoint": {"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"},
                "state": {"banks": []},
                "compatibility": [{"check": "provider-contract", "compatible": True}],
            }
            operations = {"idle": False, "active": [{"id": "op-1", "kind": "retain", "status": "running", "profile_id": "core"}]}
            plan = build_plan(desired, live, operations)
            before = canonical_bytes(plan.to_dict())

            live["compatibility"][0]["compatible"] = False
            live["state"]["banks"].append({"id": "personal"})
            operations["active"][0]["status"] = "failed"
            with self.assertRaises(TypeError):
                plan.compatibility[0]["compatible"] = False
            with self.assertRaises(TypeError):
                plan.actions[0].details["bank"] = {"bank_id": "personal"}
            with self.assertRaises(TypeError):
                plan.operations.active[0]["status"] = "failed"
            with self.assertRaises(TypeError):
                desired.profiles[0]["id"] = "changed"

            self.assertEqual(canonical_bytes(plan.to_dict()), before)
            verify_plan(plan)

    def test_plan_rejects_live_endpoint_drift_from_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            fixture = tmp / "inventory.json"
            live = tmp / "live.json"
            operations = tmp / "operations.json"
            self.write_json(fixture, inventory())
            self.write_json(operations, {"idle": True, "active": []})
            self.write_json(live, {"profile_id": "core", "endpoint": {"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7980, "tenant": "default"}, "state": {"banks": []}, "compatibility": []})
            result = self.run_cli(tmp, "plan", "--inventory", fixture, "--live-state", live, "--operations", operations)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("endpoint identity does not match inventory", result.stderr)

    def test_status_rejects_unknown_and_malformed_plan_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            fixture = tmp / "inventory.json"
            live = tmp / "live.json"
            operations = tmp / "operations.json"
            plan = tmp / "plan.json"
            self.write_json(fixture, inventory())
            self.write_json(operations, {"idle": True, "active": []})
            self.write_json(live, {"profile_id": "core", "endpoint": {"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"}, "state": {"banks": []}, "compatibility": []})
            self.assertEqual(self.run_cli(tmp, "plan", "--inventory", fixture, "--live-state", live, "--operations", operations, "--output", plan).returncode, 0)

            value = json.loads(plan.read_text())
            value["secret"] = "private"
            self.write_json(plan, value)
            unknown = self.run_cli(tmp, "status", "--inventory", fixture, "--live-state", live, "--plan", plan)
            self.assertNotEqual(unknown.returncode, 0)
            self.assertIn("plan keys", unknown.stderr)

            del value["secret"]
            value["plan_digest"] = "not-a-digest"
            self.write_json(plan, value)
            malformed = self.run_cli(tmp, "status", "--inventory", fixture, "--live-state", live, "--plan", plan)
            self.assertNotEqual(malformed.returncode, 0)
            self.assertIn("plan_digest", malformed.stderr)

            value["plan_digest"] = "0" * 64
            self.write_json(plan, value)
            tampered = self.run_cli(tmp, "status", "--inventory", fixture, "--live-state", live, "--plan", plan)
            self.assertNotEqual(tampered.returncode, 0)
            self.assertIn("plan digest does not match plan body", tampered.stderr)

    def test_ledger_is_canonical_private_and_payload_free(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "controller.jsonl"
            record = {
                "schema_version": 1,
                "action_id": "retain-1",
                "correlation_id": "session-1",
                "source_bank": {"profile_id": "core", "bank_id": "engineering", "endpoint": {"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"}},
                "target_bank": {"profile_id": "core", "bank_id": "personal", "endpoint": {"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"}},
                "policy_digest": "1" * 64,
                "artifact_digest": "2" * 64,
                "decision": "deny",
                "reason_code": "CROSS_BANK_POLICY_DENY",
                "timestamp": "2026-07-12T17:00:00Z",
                "reversible_record_id": None,
            }
            append_record(ledger, record)
            self.assertEqual(ledger.read_bytes(), json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n")
            self.assertEqual(os.stat(ledger).st_mode & 0o777, 0o600)

            before = ledger.read_bytes()
            real_write = os.write
            writes = 0

            def partial_then_fail(descriptor, body):
                nonlocal writes
                writes += 1
                if writes == 1:
                    chunk = body[:max(1, len(body) // 2)]
                    return real_write(descriptor, chunk)
                raise OSError("append failed")

            with patch(
                "hindsight_memory_control_plane.ledger.os.write",
                side_effect=partial_then_fail,
            ):
                with self.assertRaisesRegex(OSError, "append failed"):
                    append_record(ledger, record)
            self.assertEqual(ledger.read_bytes(), before)

            protected = Path(directory) / "protected.jsonl"
            protected.write_text("preserve", encoding="utf-8")
            linked_ledger = Path(directory) / "linked.jsonl"
            linked_ledger.symlink_to(protected)
            with self.assertRaises(OSError):
                append_record(linked_ledger, record)
            self.assertEqual(protected.read_text(encoding="utf-8"), "preserve")

            real_parent = Path(directory) / "real-ledger-parent"
            nested_parent = real_parent / "nested"
            nested_parent.mkdir(parents=True)
            linked_parent = Path(directory) / "linked-ledger-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaises(OSError):
                append_record(linked_parent / "nested" / "controller.jsonl", record)
            self.assertFalse((nested_parent / "controller.jsonl").exists())

            fifo = Path(directory) / "ledger.fifo"
            os.mkfifo(fifo, 0o600)
            with self.assertRaises(OSError):
                append_record(fifo, record)

            hardlink_source = Path(directory) / "hardlink-source.jsonl"
            hardlink_source.write_text("preserve", encoding="utf-8")
            hardlink_ledger = Path(directory) / "hardlink-ledger.jsonl"
            os.link(hardlink_source, hardlink_ledger)
            with self.assertRaises(OSError):
                append_record(hardlink_ledger, record)
            self.assertEqual(hardlink_source.read_text(encoding="utf-8"), "preserve")

            for key in ("token", "api_key", "control_key", "signing_key", "secret"):
                contaminated = dict(record)
                contaminated["source_bank"] = {**record["source_bank"], key: "private"}
                with self.assertRaisesRegex(LedgerError, "bank reference keys"):
                    append_record(ledger, contaminated)

            contaminated = dict(record)
            contaminated["source_bank"] = {**record["source_bank"], "metadata": {"note": "innocuous nested payload"}}
            with self.assertRaisesRegex(LedgerError, "bank reference keys"):
                append_record(ledger, contaminated)

            for missing in ("source_bank", "target_bank", "reversible_record_id"):
                incomplete = dict(record)
                del incomplete[missing]
                with self.assertRaisesRegex(LedgerError, "missing keys"):
                    append_record(ledger, incomplete)


if __name__ == "__main__":
    unittest.main()
