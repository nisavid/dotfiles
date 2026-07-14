import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import stat
import subprocess
import threading
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "home/private_dot_local/lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from hindsight_memory_control_plane.adapters import AdapterError, FakeAdapter
from hindsight_memory_control_plane.canonical import digest
from hindsight_memory_control_plane.migration import (
    MigrationError,
    discover_migration_state,
    verify_shadow_plan,
)
from hindsight_memory_control_plane.model import BankRef


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SOURCE = BankRef("example", "engineering")
CANDIDATE = BankRef("example", "historical-candidate")
CONTENT_SENTINEL = "payload-sentinel-that-must-never-enter-the-shadow-plan"
CLI = ROOT / "home/private_dot_local/bin/executable_hindsight-memory"


def bank_surface(bank: BankRef, document_id: str, content_digest: str, *, invalidated=False):
    return {
        "bank_ref": bank.to_dict(),
        "config": {"mission": f"mission-{bank.bank_id}"},
        "stats": {"documents": 1, "memories": 2},
        "scopes": ["repo:dotfiles"],
        "tags": ["agent:codex", "repo:dotfiles", "scope:active"],
        "documents": [{
            "document_id": document_id,
            "updated_at": "2026-07-12T12:00:00Z",
            "content_digest": content_digest,
            "content": CONTENT_SENTINEL if bank == SOURCE else "candidate-payload",
        }],
        "models": [{"model_id": f"model-{bank.bank_id}", "prompt": "content-bearing prompt"}],
        "directives": [{"directive_id": f"directive-{bank.bank_id}", "mission": "content-bearing directive"}],
        "invalidated_memories": ([{
            "item_id": f"invalid-{document_id}",
            "source_document_id": document_id,
            "reason_digest": SHA_C,
            "content_digest": content_digest,
        }] if invalidated else []),
    }


def migration_inventory():
    return {
        "schema_version": 1,
        "endpoint": {
            "profile_id": "example",
            "scheme": "http",
            "host": "127.0.0.1",
            "port": 7979,
            "tenant": "default",
        },
        "provider_identity": {
            "llm": "claude-code",
            "embedding": "local-default",
            "reranking": "jina-mlx",
        },
        "versions": {
            "hindsight": "0.8.4",
            "adapter": "1",
            "providers": {"llm": "current", "embedding": "current", "reranking": "current"},
        },
        "banks": {
            "source": bank_surface(SOURCE, "source-1", SHA_A, invalidated=True),
            "candidate": bank_surface(CANDIDATE, "candidate-1", SHA_B, invalidated=True),
        },
        "operations": {"idle": True, "active": []},
        "hooks": [{"harness": "codex", "active": True}],
        "schedules": [{"kind": "refresh", "enabled": False}],
    }


def package_manifest():
    value = {
        "schema_version": 1,
        "artifact_digest": SHA_E,
        "projection_digest": SHA_D,
        "tag_mapping_digest": SHA_C,
        "candidate_provenance_digest": SHA_A,
        "candidate_curation_digest": SHA_B,
        "source_coverage": [{
            "item_id": "source-1",
            "content_digest": SHA_A,
            "disposition": "retain",
            "reason": "authoritative-source",
            "semantic_scope": "repo:dotfiles",
        }],
        "candidate_coverage": [{
            "item_id": "candidate-1",
            "content_digest": SHA_B,
            "disposition": "retain",
            "reason": "accepted-candidate",
            "semantic_scope": "repo:dotfiles",
        }],
        "invalidation_dispositions": [
            {
                "item_id": "invalid-source-1",
                "disposition": "exclude",
                "reason": "source-invalidated",
                "reapply_content_digest": None,
            },
            {
                "item_id": "invalid-candidate-1",
                "disposition": "reapply",
                "reason": "candidate-curation-preserved",
                "reapply_content_digest": SHA_B,
            },
        ],
    }
    return value


def write_gate_files(root: Path):
    marker = root / "distillation-complete.marker"
    proposal = root / "proposal-log.md"
    marker.write_text("run=offline\nartifact=" + SHA_E + "\n", encoding="utf-8")
    proposal.write_text("## Migration pending\n", encoding="utf-8")
    return {
        "artifact_dir": str(root / "artifacts"),
        "completion_marker": str(marker),
        "proposal_log": str(proposal),
    }


class SequenceAdapter(FakeAdapter):
    def __init__(self, inventories):
        super().__init__(
            endpoint=migration_inventory()["endpoint"],
            state={"migration_inventory": copy.deepcopy(inventories[0])},
        )
        self.inventories = [copy.deepcopy(value) for value in inventories]

    def read_migration_inventory(self, source_bank, candidate_bank):
        self._record(
            "read_migration_inventory",
            {"source_bank": source_bank.to_dict(), "candidate_bank": candidate_bank.to_dict()},
        )
        if not self.inventories:
            raise AdapterError("migration inventory is unavailable")
        return copy.deepcopy(self.inventories.pop(0))


class MigrationDiscoveryContractTest(unittest.TestCase):
    def discover(
        self,
        root: Path,
        *,
        inventories=None,
        package=None,
        approved_digest=None,
        catalog=None,
        watermarks=None,
    ):
        manifest = copy.deepcopy(package or package_manifest())
        normalized_manifest = copy.deepcopy(manifest)
        for key in ("source_coverage", "candidate_coverage", "invalidation_dispositions"):
            if isinstance(normalized_manifest.get(key), list):
                normalized_manifest[key].sort(key=lambda item: json.dumps(item, sort_keys=True))
        adapter = SequenceAdapter(inventories or [migration_inventory(), migration_inventory()])
        watermark_values = iter(
            copy.deepcopy(
                watermarks
                or [
                    {"codex": {"document_id": "source-1", "epoch": 4, "checkpoint": 9}},
                    {"codex": {"document_id": "source-1", "epoch": 4, "checkpoint": 9}},
                ]
            )
        )
        result = discover_migration_state(
            adapter,
            source_bank=SOURCE,
            candidate_bank=CANDIDATE,
            offline_package_manifest=manifest,
            approved_offline_package_digest=approved_digest or digest(normalized_manifest),
            migration_paths=write_gate_files(root),
            retain_watermark_reader=lambda: next(watermark_values),
            private_catalog_digests=catalog or {
                "catalog": SHA_A,
                "bank_archetypes": SHA_B,
                "tag_aliases": SHA_C,
            },
            timestamp="20260713T120000Z",
        )
        return adapter, result

    def test_complete_discovery_writes_private_content_inventory_and_redacted_unapproved_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter, result = self.discover(Path(directory))
            self.assertTrue(result.complete)
            self.assertEqual(result.blockers, ())
            self.assertEqual(
                [call["method"] for call in adapter.calls],
                ["read_migration_inventory", "read_migration_inventory"],
            )
            run_dir = Path(result.run_dir)
            inventory_path = run_dir / "inventory.json"
            plan_path = run_dir / "shadow-plan.json"
            self.assertEqual(stat.S_IMODE(run_dir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(inventory_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(plan_path.stat().st_mode), 0o600)
            inventory_text = inventory_path.read_text(encoding="utf-8")
            plan_text = plan_path.read_text(encoding="utf-8")
            self.assertIn(CONTENT_SENTINEL, inventory_text)
            self.assertNotIn(CONTENT_SENTINEL, plan_text)
            plan = json.loads(plan_text)
            self.assertFalse(plan["approved"])
            self.assertEqual(plan["mutation_authority"], "none")
            self.assertTrue(plan["complete"])
            self.assertFalse(plan["legacy_observations_imported"])
            verify_shadow_plan(plan)

    def test_discovery_records_high_water_invalidations_and_every_required_surface(self):
        with tempfile.TemporaryDirectory() as directory:
            _, result = self.discover(Path(directory))
            inventory = json.loads((Path(result.run_dir) / "inventory.json").read_text())
            self.assertEqual(
                inventory["high_water_manifest"],
                [
                    {"bank_role": "candidate", "content_digest": SHA_B, "document_id": "candidate-1", "updated_at": "2026-07-12T12:00:00Z"},
                    {"bank_role": "source", "content_digest": SHA_A, "document_id": "source-1", "updated_at": "2026-07-12T12:00:00Z"},
                ],
            )
            self.assertEqual(
                {item["item_id"] for item in inventory["invalidation_manifest"]},
                {"invalid-source-1", "invalid-candidate-1"},
            )
            for key in ("endpoint", "provider_identity", "versions", "banks", "operations", "hooks", "schedules", "retain_watermarks"):
                self.assertIn(key, inventory["snapshot"])

    def test_each_missing_required_surface_returns_explicit_incomplete_result_without_artifacts(self):
        required = ("endpoint", "provider_identity", "versions", "banks", "operations", "hooks", "schedules")
        for key in required:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                broken = migration_inventory()
                del broken[key]
                _, result = self.discover(Path(directory), inventories=[broken, broken])
                self.assertFalse(result.complete)
                self.assertIn(f"missing:{key}", result.blockers)
                self.assertIsNone(result.run_dir)
                self.assertFalse((Path(directory) / "artifacts").exists())

    def test_retain_watermarks_are_separate_and_drift_blocks_planning(self):
        before = {"codex": {"document_id": "source-1", "epoch": 4, "checkpoint": 9}}
        after = {"codex": {"document_id": "source-1", "epoch": 4, "checkpoint": 10}}
        with tempfile.TemporaryDirectory() as directory:
            _, result = self.discover(Path(directory), watermarks=[before, after])
            self.assertFalse(result.complete)
            self.assertIn("drift:retain_watermarks", result.blockers)
            self.assertIsNone(result.run_dir)

        broken = migration_inventory()
        broken["retain_watermarks"] = before
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(MigrationError, "must not contain retain watermarks"):
                self.discover(Path(directory), inventories=[broken, broken])

    def test_explicit_empty_collections_are_complete_but_missing_record_fields_are_not(self):
        empty = migration_inventory()
        for bank in empty["banks"].values():
            bank["documents"] = []
            bank["invalidated_memories"] = []
        empty["hooks"] = []
        empty["schedules"] = []
        manifest = package_manifest()
        manifest["source_coverage"] = []
        manifest["candidate_coverage"] = []
        manifest["invalidation_dispositions"] = []
        with tempfile.TemporaryDirectory() as directory:
            _, result = self.discover(Path(directory), inventories=[empty, empty], package=manifest)
            self.assertTrue(result.complete)

        for field in ("document_id", "updated_at", "content_digest"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                broken = migration_inventory()
                del broken["banks"]["source"]["documents"][0][field]
                _, result = self.discover(Path(directory), inventories=[broken, broken])
                self.assertFalse(result.complete)
                self.assertIn(f"missing:source.documents.{field}", result.blockers)

    def test_shadow_plan_binds_exact_coverage_scope_curation_and_cutover_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            _, result = self.discover(Path(directory))
            plan = result.plan.to_dict()
            self.assertEqual(
                {item["item_id"] for item in plan["coverage"]["source"]},
                {"source-1"},
            )
            self.assertEqual(
                {item["item_id"] for item in plan["coverage"]["candidate"]},
                {"candidate-1"},
            )
            self.assertEqual(
                [item["semantic_scope"] for role in ("source", "candidate") for item in plan["coverage"][role]],
                ["repo:dotfiles", "repo:dotfiles"],
            )
            self.assertEqual(
                {item["item_id"] for item in plan["invalidation_dispositions"]},
                {"invalid-source-1", "invalid-candidate-1"},
            )
            self.assertEqual(plan["bindings"]["candidate_provenance_digest"], SHA_A)
            self.assertEqual(plan["bindings"]["candidate_curation_digest"], SHA_B)
            self.assertTrue(plan["operations"]["idle"])
            self.assertIn("full_schema_backup", plan["rollback_requirements"])
            self.assertEqual(plan["cutover"]["on_drift"], "restart_verification")
            self.assertTrue(plan["cutover"]["freeze_retain_paths"])
            self.assertTrue(plan["cutover"]["final_catch_up"])
            self.assertEqual(plan["closeout"]["authority"], "separate_digest_bound_approval")
            self.assertEqual(plan["archive_retirement"]["authority"], "separate_digest_bound_approval")
            self.assertNotEqual(plan["closeout"]["kind"], plan["archive_retirement"]["kind"])

    def test_shadow_plan_verifier_rejects_rehashed_semantic_weakening(self):
        with tempfile.TemporaryDirectory() as directory:
            _, result = self.discover(Path(directory))
            original = result.plan.to_dict()

        mutations = (
            lambda plan: plan["rollback_requirements"].remove("full_schema_backup"),
            lambda plan: plan["cutover"].update({"freeze_retain_paths": False}),
            lambda plan: plan["operations"].update({"idle": False}),
            lambda plan: plan["closeout"].update({"archive_deletion_authority": True}),
            lambda plan: plan["archive_retirement"].update({"authority": "implicit"}),
            lambda plan: plan["bindings"].update({"inventory_digest": "invalid"}),
            lambda plan: plan["semantic_diff"].update({"proposed_retains": 0}),
            lambda plan: plan.update({"schema_version": True}),
            lambda plan: plan["semantic_diff"].update({"source_items": True}),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                plan = copy.deepcopy(original)
                mutate(plan)
                body = {key: value for key, value in plan.items() if key != "plan_digest"}
                plan["plan_digest"] = digest(body)
                with self.assertRaises(MigrationError):
                    verify_shadow_plan(plan)

    def test_missing_extra_duplicate_coverage_and_non_scalar_scope_fail_closed(self):
        mutations = []
        missing = package_manifest()
        missing["source_coverage"] = []
        mutations.append(missing)
        extra = package_manifest()
        extra["candidate_coverage"].append({**extra["candidate_coverage"][0], "item_id": "extra"})
        mutations.append(extra)
        duplicate = package_manifest()
        duplicate["source_coverage"].append(copy.deepcopy(duplicate["source_coverage"][0]))
        mutations.append(duplicate)
        multiple_scope = package_manifest()
        multiple_scope["source_coverage"][0]["semantic_scope"] = ["repo:dotfiles", "scope:active"]
        mutations.append(multiple_scope)
        for manifest in mutations:
            with self.subTest(manifest=manifest), tempfile.TemporaryDirectory() as directory:
                _, result = self.discover(Path(directory), package=manifest)
                self.assertFalse(result.complete)
                self.assertTrue(result.blockers)
                self.assertIsNone(result.run_dir)

    def test_busy_operations_package_digest_mismatch_and_drift_block(self):
        busy = migration_inventory()
        busy["operations"] = {"idle": False, "active": [{"operation_id": "retain-1"}]}
        with tempfile.TemporaryDirectory() as directory:
            _, result = self.discover(Path(directory), inventories=[busy, busy])
            self.assertFalse(result.complete)
            self.assertIn("operations:not_idle", result.blockers)

        with tempfile.TemporaryDirectory() as directory:
            _, result = self.discover(Path(directory), approved_digest="0" * 64)
            self.assertFalse(result.complete)
            self.assertIn("offline_package:digest_mismatch", result.blockers)

        before = migration_inventory()
        after = migration_inventory()
        after["banks"]["source"]["stats"]["documents"] = 2
        with tempfile.TemporaryDirectory() as directory:
            _, result = self.discover(Path(directory), inventories=[before, after])
            self.assertFalse(result.complete)
            self.assertIn("drift:bank_stats", result.blockers)

    def test_equivalent_reordering_produces_the_same_semantic_digests(self):
        first = migration_inventory()
        second = copy.deepcopy(first)
        second["hooks"] = list(reversed(second["hooks"]))
        manifest = package_manifest()
        with tempfile.TemporaryDirectory() as left, tempfile.TemporaryDirectory() as right:
            _, left_result = self.discover(Path(left), inventories=[first, first], package=manifest)
            reordered = copy.deepcopy(manifest)
            reordered["invalidation_dispositions"].reverse()
            _, right_result = self.discover(Path(right), inventories=[second, second], package=reordered)
            self.assertEqual(left_result.inventory_digest, right_result.inventory_digest)
            self.assertEqual(left_result.shadow_plan_digest, right_result.shadow_plan_digest)

    def test_artifact_directory_symlink_and_existing_run_are_refused_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            real.mkdir()
            link = root / "artifacts"
            link.symlink_to(real, target_is_directory=True)
            manifest = package_manifest()
            paths = write_gate_files(root)
            paths["artifact_dir"] = str(link)
            adapter = SequenceAdapter([migration_inventory(), migration_inventory()])
            with self.assertRaises(MigrationError):
                discover_migration_state(
                    adapter,
                    source_bank=SOURCE,
                    candidate_bank=CANDIDATE,
                    offline_package_manifest=manifest,
                    approved_offline_package_digest=digest(manifest),
                    migration_paths=paths,
                    retain_watermark_reader=lambda: {"codex": {"epoch": 1}},
                    private_catalog_digests={"catalog": SHA_A},
                    timestamp="20260713T120000Z",
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = write_gate_files(root)
            run = Path(paths["artifact_dir"]) / "controller-discovery-20260713T120000Z"
            run.mkdir(parents=True)
            sentinel = run / "inventory.json"
            sentinel.write_text("do-not-overwrite", encoding="utf-8")
            manifest = package_manifest()
            adapter = SequenceAdapter([migration_inventory(), migration_inventory()])
            with self.assertRaises(MigrationError):
                discover_migration_state(
                    adapter,
                    source_bank=SOURCE,
                    candidate_bank=CANDIDATE,
                    offline_package_manifest=manifest,
                    approved_offline_package_digest=digest(manifest),
                    migration_paths=paths,
                    retain_watermark_reader=lambda: {"codex": {"epoch": 1}},
                    private_catalog_digests={"catalog": SHA_A},
                    timestamp="20260713T120000Z",
                )
            self.assertEqual(sentinel.read_text(), "do-not-overwrite")


class MigrationCliContractTest(unittest.TestCase):
    def run_cli(self, *args, env=None):
        return subprocess.run(
            [sys.executable, str(CLI), "--state-dir", "/tmp/hindsight-state", *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            env=env,
        )

    def test_migration_discover_requires_explicit_profile_and_read_only_flag(self):
        missing_profile = self.run_cli("migration", "discover", "--read-only")
        self.assertNotEqual(missing_profile.returncode, 0)
        self.assertIn("--profile", missing_profile.stderr)

        missing_read_only = self.run_cli("migration", "discover", "--profile", "example")
        self.assertNotEqual(missing_read_only.returncode, 0)
        self.assertIn("--read-only", missing_read_only.stderr)

    def test_migration_discover_uses_get_only_and_reports_unapproved_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seen = []
            handler_errors = []
            surfaces = {
                "engineering": bank_surface(BankRef("core", "engineering"), "source-1", SHA_A, invalidated=True),
                "historical-candidate": bank_surface(
                    BankRef("core", "historical-candidate"),
                    "candidate-1",
                    SHA_B,
                    invalidated=True,
                ),
            }

            def response_for(raw_path):
                parsed = urlparse(raw_path)
                if parsed.path == "/version":
                    return {"api_version": "0.8.4", "features": {"observations": True}}
                parts = parsed.path.split("/")
                bank_id = parts[4]
                suffix = "/" + "/".join(parts[5:])
                surface = surfaces[bank_id]
                query = parse_qs(parsed.query)
                if suffix == "/config":
                    return {"bank_id": bank_id, "config": surface["config"], "overrides": {}}
                if suffix == "/stats":
                    return surface["stats"]
                if suffix == "/observations/scopes":
                    return {"scopes": surface["scopes"]}
                if suffix == "/tags":
                    return {"items": surface["tags"], "total": len(surface["tags"]), "limit": 1000, "offset": 0}
                if suffix == "/documents":
                    items = [
                        {
                            "id": item["document_id"],
                            "updated_at": item["updated_at"],
                            "content_hash": item["content_digest"],
                            "created_at": item["updated_at"],
                            "text_length": len(item.get("content", "")),
                            "memory_unit_count": 1,
                            "tags": [],
                            "document_metadata": {},
                            "retain_params": {},
                        }
                        for item in surface["documents"]
                    ]
                    return {"items": items, "total": len(items), "limit": 1000, "offset": 0}
                if suffix == "/mental-models":
                    return {
                        "items": [
                            {"id": item["model_id"], "content": item["prompt"], "trigger": None}
                            for item in surface["models"]
                        ]
                    }
                if suffix == "/directives":
                    return {"items": surface["directives"]}
                if suffix == "/webhooks":
                    return {"items": []}
                if suffix == "/memories/list":
                    items = [
                        {
                            "id": item["item_id"],
                            "document_id": item["source_document_id"],
                            "text": "invalidated-content",
                            "invalidation_reason": "test-curation",
                        }
                        for item in surface["invalidated_memories"]
                    ]
                    return {"items": items, "total": len(items), "limit": 1000, "offset": 0}
                if suffix == "/operations" and query.get("status") in (["pending"], ["processing"]):
                    return {"bank_id": bank_id, "operations": [], "total": 0, "limit": 1000, "offset": 0}
                raise AssertionError(f"unexpected read path: {raw_path}")

            class Handler(BaseHTTPRequestHandler):
                def do_GET(handler):
                    seen.append((handler.command, handler.path, handler.headers.get("Authorization")))
                    try:
                        raw = json.dumps(response_for(handler.path)).encode()
                    except Exception as error:
                        handler_errors.append(repr(error))
                        handler.send_response(500)
                        handler.send_header("Content-Length", "0")
                        handler.end_headers()
                    else:
                        handler.send_response(200)
                        handler.send_header("Content-Length", str(len(raw)))
                        handler.end_headers()
                        handler.wfile.write(raw)

                def log_message(self, *_args):
                    pass

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(thread.join, 2)
            self.addCleanup(server.shutdown)

            paths = write_gate_files(root)
            inventory_path = root / "controller-inventory.json"
            inventory_path.write_text(json.dumps({
                "schema_version": 1,
                "machine": {"base_port": server.server_port},
                "archetype": {},
                "profiles": [{
                    "id": "core",
                    "enabled": True,
                    "host": "127.0.0.1",
                    "port": server.server_port,
                    "tenant": "default",
                    "roles": {},
                    "data_classes": [],
                }],
                "providers": [],
                "banks": [
                    {"id": "engineering", "profile_id": "core", "data_class": "engineering", "authority": "none", "writable": False},
                    {"id": "historical-candidate", "profile_id": "core", "data_class": "engineering", "authority": "none", "writable": False},
                ],
                "harnesses": [],
                "migration": {"artifact_dir": paths["artifact_dir"], "proposal_log": paths["proposal_log"]},
                "policy": {"engineering_memory_enabled": False},
            }), encoding="utf-8")
            manifest = package_manifest()
            manifest_path = root / "offline-package.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            catalog_path = root / "catalog-digests.json"
            catalog_path.write_text(json.dumps({"catalog": SHA_A}), encoding="utf-8")
            watermark_path = root / "retain-watermarks.json"
            watermark_path.write_text(
                json.dumps({"codex": {"document_id": "source-1", "epoch": 4, "checkpoint": 9}}),
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["TEST_HINDSIGHT_TOKEN"] = "read-only-test-token"
            result = self.run_cli(
                "migration", "discover", "--read-only",
                "--inventory", str(inventory_path),
                "--profile", "core",
                "--source-bank", "engineering",
                "--candidate-bank", "historical-candidate",
                "--offline-package-manifest", str(manifest_path),
                "--approved-offline-package-digest", digest(manifest),
                "--private-catalog-digests", str(catalog_path),
                "--retain-watermarks", str(watermark_path),
                "--completion-marker", paths["completion_marker"],
                "--token-env", "TEST_HINDSIGHT_TOKEN",
                "--timestamp", "20260713T120000Z",
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout + repr(handler_errors) + repr(seen))
            output = json.loads(result.stdout)
            self.assertTrue(output["complete"])
            self.assertFalse(output["approved"])
            self.assertRegex(output["inventory_digest"], r"^[0-9a-f]{64}$")
            self.assertRegex(output["shadow_plan_digest"], r"^[0-9a-f]{64}$")
            self.assertGreater(len(seen), 2)
            self.assertTrue(all(method == "GET" for method, _path, _auth in seen))
            self.assertFalse(any(path.startswith("/v1/migrations/") for _method, path, _auth in seen))
            self.assertTrue(all(auth == "Bearer read-only-test-token" for _method, _path, auth in seen))


if __name__ == "__main__":
    unittest.main()
