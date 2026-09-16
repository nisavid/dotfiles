from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SURFACE = ROOT / "docs/crypto/pq-sequoia-macos"
PROTOCOL = SURFACE / "interop-v1.json"
MESSAGE = SURFACE / "fixtures/v1/message.bin"
PACKAGE_ROOT = ROOT / "packaging/homebrew/pq-sequoia-macos/v1"
CANDIDATE = PACKAGE_ROOT / "candidate.json"
CLI = ROOT / "scripts/pq-sequoia-macos"
WORKFLOW = ROOT / ".github/workflows/pq-sequoia-macos.yml"
PROCEDURE = SURFACE / "PROCEDURE.md"
PROTOCOL_SHA256 = hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()


def _load_cli():
    loader = SourceFileLoader("pq_sequoia_macos", str(CLI))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load pq-sequoia-macos")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InteroperabilityProtocolTests(unittest.TestCase):
    def test_frozen_protocol_preserves_bidirectional_live_secret_lifetimes(
        self,
    ) -> None:
        message = MESSAGE.read_bytes()
        protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))

        self.assertEqual(
            b"dotfiles #147 RFC 9980 interoperability fixture v1\n", message
        )
        self.assertEqual(51, len(message))
        self.assertEqual(
            "6be8c2fe3154649151aacd41f35dd6a212881e627acca131fe3f0101b14f4337",
            hashlib.sha256(message).hexdigest(),
        )
        self.assertEqual("pq-sequoia-interop/v1", protocol["schema_version"])
        self.assertEqual("review-candidate", protocol["status"])
        self.assertEqual(51, protocol["message"]["size"])
        self.assertEqual(
            hashlib.sha256(message).hexdigest(), protocol["message"]["sha256"]
        )

        phases = protocol["phases"]
        self.assertEqual(
            ["hatchery-open", "macos-ci-live", "hatchery-return", "macos-ci-close"],
            [phase["id"] for phase in phases],
        )
        self.assertTrue(
            phases[0]["secret_lifetime"]["retain_through"] == "hatchery-return"
        )
        self.assertTrue(
            phases[1]["secret_lifetime"]["retain_through"] == "macos-ci-close"
        )
        self.assertTrue(phases[1]["requires_same_live_job_as"] == "macos-ci-close")

        transferred = set(protocol["artifact_policy"]["transferred"])
        self.assertIn("ciphertext-to-hatchery.pgp", transferred)
        self.assertIn("ciphertext-to-macos-ci.pgp", transferred)
        self.assertNotIn("revocation.pgp", transferred)
        self.assertIn("revocation packets", protocol["artifact_policy"]["local_only"])
        self.assertIn("secret keys", protocol["artifact_policy"]["local_only"])
        self.assertEqual(
            {
                "message.bin",
                "hatchery-cert.pgp",
                "hatchery-message.sig",
                "macos-ci-cert.pgp",
                "macos-ci-message.sig",
                "ciphertext-to-hatchery.pgp",
                "ciphertext-to-macos-ci.pgp",
            },
            set(protocol["reciprocal_artifact_map"]["artifacts"]),
        )
        self.assertIn(
            "control_signature", protocol["envelopes"]["required_envelope_fields"]
        )
        self.assertIn("phase-B envelope digest", protocol["relay_binding"]["selection"])

        required = set(protocol["acceptance"]["required_observations"])
        self.assertIn("hatchery decrypts macos-ci ciphertext byte-for-byte", required)
        self.assertIn("macos-ci decrypts hatchery ciphertext byte-for-byte", required)
        self.assertIn("both peers reject altered messages", required)
        self.assertIn(
            "both peers reject tampered ciphertext with no recovered output", required
        )
        self.assertIn(
            "both peers exercise certificate and subkey revocation locally", required
        )


class CandidatePackagingTests(unittest.TestCase):
    def test_candidate_manifest_freezes_supported_sources_and_locks(self) -> None:
        candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))

        self.assertEqual("pq-sequoia-macos-candidate/v1", candidate["schema_version"])
        self.assertEqual("macos-15", candidate["runner"]["label"])
        self.assertEqual("ARM64", candidate["runner"]["runner_arch"])
        self.assertEqual("15", candidate["runner"]["macos_major"])

        self.assertEqual("3.5.8", candidate["openssl"]["version"])
        self.assertEqual("LTS", candidate["openssl"]["support_line"])
        self.assertEqual("2030-04-08", candidate["openssl"]["supported_until"])
        self.assertEqual(
            "87ec0fe343645ff3e4865da62205a7844c99f144",
            candidate["openssl"]["homebrew_core_commit"],
        )
        self.assertEqual(
            "3265208aa3bf71299a48b3a2c7d3b734f88b2b65831488ae9e514dbc93c6db05",
            candidate["openssl"]["formula_sha256"],
        )
        self.assertEqual(
            "a8f84a39918ec6415ce765d9b429d313ba97b8143169c172e734b9514464f5b2",
            candidate["openssl"]["source_sha256"],
        )
        self.assertEqual(
            "1a4c97d1ab594a16b200f258fe208afc38d799e5584aebb143b51e54ab9e68db",
            candidate["openssl"]["arm64_sequoia_bottle_sha256"],
        )

        expected = {
            "sq": {
                "version": "1.4.0",
                "commit": "558e1461d4f277924b0710f17a5bb56469f74ff2",
                "source_sha256": "c856bfb0f0c94a1b8f4b72a04a6eff1e1d3d24c377cb0b1e495688e9aad8467a",
                "patch_sha256": "efddbf6ac7c76b2ec0677f881e607af03281648238ffd390266ddb50973cda64",
                "lock_sha256": "b8d698b3a0556cb0115aec4091a46dbf6ba909b2941a74ba61c99e69e01f5efa",
            },
            "sqv": {
                "version": "1.5.0",
                "commit": "e0dbf9133a1bf605eb2ead3869d9722d8dfc8252",
                "source_sha256": "695749c7b8dc006c0d5ade1830bf6263453eff8211d1e18402f6686327124800",
                "patch_sha256": "3a85149ff2c9ab3d91b8354b50052fe60344338e397332fb218bd14eb786c96b",
                "lock_sha256": "6509c7b5ecde46470e9c4cf7d67048ab5f06fc74ba207905361d6f760abb8b8f",
            },
        }
        for name, values in expected.items():
            with self.subTest(name=name):
                component = candidate["applications"][name]
                for field, value in values.items():
                    self.assertEqual(value, component[field])
                self.assertEqual("2.4.1", component["sequoia_openpgp_version"])
                self.assertEqual(
                    "0fbc8f9818a6fad141d85993777ba298ee52c80a09bd23d45dda461a6b7c83cb",
                    component["sequoia_openpgp_checksum"],
                )
                patch_path = ROOT / component["patch_path"]
                formula_path = ROOT / component["formula_path"]
                self.assertEqual(component["patch_sha256"], _sha256(patch_path))
                self.assertEqual(component["formula_sha256"], _sha256(formula_path))

                formula = formula_path.read_text(encoding="utf-8")
                self.assertIn('depends_on "openssl@3.5"', formula)
                self.assertIn("keg_only", formula)
                self.assertNotIn('openssl@3"', formula)
                self.assertNotIn("head ", formula.lower())
                embedded_patch = formula.split("\n__END__\n", 1)[1].encode()
                self.assertEqual(patch_path.read_bytes(), embedded_patch)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class QualificationProcedureTests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(CLI), *arguments],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_repo_local_command_validates_the_frozen_public_surface(self) -> None:
        result = self.run_cli("validate-static", "--root", str(ROOT))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("pq-sequoia-macos static surface: valid\n", result.stdout)

    def test_public_envelope_validator_accepts_only_bound_payloads(self) -> None:
        session_id = "a" * 64
        cert = b"public disposable certificate"
        signature = b"public detached signature"
        envelope = {
            "schema_version": "pq-sequoia-interop-envelope/v1",
            "phase": "hatchery-phase-a",
            "session_id": session_id,
            "protocol_sha256": PROTOCOL_SHA256,
            "producer_closure_sha256": "b" * 64,
            "parent_envelope_sha256": "0" * 64,
            "message_sha256": "6be8c2fe3154649151aacd41f35dd6a212881e627acca131fe3f0101b14f4337",
            "payloads": {
                "hatchery-cert.pgp": _payload(cert),
                "hatchery-message.sig": _payload(signature),
            },
            "results": {
                "local_revocation_results": {
                    name: {"passed": True, "sha256": "c" * 64, "size": 1}
                    for name in (
                        "emergency_certificate",
                        "retired_certificate",
                        "retired_signing_subkey",
                        "retired_encryption_subkey",
                    )
                },
                "local_cleanup_pending": True,
            },
            "control_signature": _payload(b"public control signature"),
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "envelope.json"
            path.write_text(json.dumps(envelope), encoding="utf-8")
            result = self.run_cli(
                "validate-envelope",
                "--phase",
                "hatchery-phase-a",
                "--session-id",
                session_id,
                str(path),
            )
            self.assertEqual(0, result.returncode, result.stderr)

            envelope["payloads"]["hatchery-cert.pgp"]["sha256"] = "d" * 64
            path.write_text(json.dumps(envelope), encoding="utf-8")
            rejected = self.run_cli(
                "validate-envelope",
                "--phase",
                "hatchery-phase-a",
                "--session-id",
                session_id,
                str(path),
            )
            self.assertEqual(1, rejected.returncode)
            self.assertIn("payload digest mismatch", rejected.stderr)
            self.assertNotIn(base64.b64encode(cert).decode(), rejected.stderr)

            envelope["payloads"]["hatchery-cert.pgp"]["sha256"] = _sha256_bytes(cert)
            envelope["protected_material"] = "forbidden"
            path.write_text(json.dumps(envelope), encoding="utf-8")
            closed_schema = self.run_cli(
                "validate-envelope",
                "--phase",
                "hatchery-phase-a",
                "--session-id",
                session_id,
                str(path),
            )
            self.assertEqual(1, closed_schema.returncode)
            self.assertIn("envelope fields mismatch", closed_schema.stderr)

            envelope.pop("protected_material")
            duplicate = json.dumps(envelope).replace(
                '"phase": "hatchery-phase-a",',
                '"phase": "hatchery-phase-a", "phase": "hatchery-phase-c",',
            )
            path.write_text(duplicate, encoding="utf-8")
            ambiguous = self.run_cli(
                "validate-envelope",
                "--phase",
                "hatchery-phase-a",
                "--session-id",
                session_id,
                str(path),
            )
            self.assertEqual(1, ambiguous.returncode)
            self.assertIn("duplicate JSON field", ambiguous.stderr)

            oversized = json.dumps(envelope) + (" " * 46000)
            path.write_text(oversized, encoding="utf-8")
            bounded = self.run_cli(
                "validate-envelope",
                "--phase",
                "hatchery-phase-a",
                "--session-id",
                session_id,
                str(path),
            )
            self.assertEqual(1, bounded.returncode)
            self.assertIn("protocol size limit", bounded.stderr)

    def test_manual_workflow_binds_revision_runner_and_live_relay(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("\n  push:", workflow)
        self.assertIn("runs-on: macos-15", workflow)
        self.assertIn("RUNNER_ENVIRONMENT", workflow)
        self.assertIn("GITHUB_WORKFLOW_SHA", workflow)
        self.assertIn("databaseId,displayTitle,event,headSha,status,conclusion", workflow)
        self.assertIn("validate-relay", workflow)
        self.assertIn("PQ_PHASE_B_SHA256", workflow)
        self.assertIn("--expected-producer-closure-sha256", workflow)
        self.assertIn("--expected-parent-sha256", workflow)
        self.assertIn("ImageVersion", workflow)
        self.assertIn("interop-open", workflow)
        self.assertIn("publish-peer-response", workflow)
        self.assertIn("interop-close", workflow)
        self.assertIn("if: always()", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertNotIn("home/", workflow)

        procedure = PROCEDURE.read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("scripts/pq-sequoia-macos validate-static", procedure)
        self.assertIn("pq-sequoia-macos/PROCEDURE.md", readme)
        self.assertIn("dotfiles #148", procedure)

    def test_cleanup_refuses_an_unmarked_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "not-procedure-state"
            state.mkdir()
            sentinel = state / "keep"
            sentinel.write_text("preserve\n", encoding="utf-8")
            result = self.run_cli("cleanup", "--state-dir", str(state))
            self.assertEqual(1, result.returncode)
            self.assertIn("unmarked state directory", result.stderr)
            self.assertEqual("preserve\n", sentinel.read_text(encoding="utf-8"))

    def test_protocol_bytes_are_part_of_static_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                "docs/crypto/pq-sequoia-macos",
                "packaging/homebrew/pq-sequoia-macos/v1",
            ):
                shutil.copytree(ROOT / relative, root / relative)
            protocol_path = root / "docs/crypto/pq-sequoia-macos/interop-v1.json"
            protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
            protocol["session"]["relay_wait_minutes"] = 1
            protocol_path.write_text(
                json.dumps(protocol, indent=2) + "\n", encoding="utf-8"
            )
            result = self.run_cli("validate-static", "--root", str(root))
            self.assertEqual(1, result.returncode)
            self.assertIn("protocol identity mismatch", result.stderr)

    def test_canonical_transcript_binds_session_protocol_closure_and_parent(self) -> None:
        module = _load_cli()
        base = {
            "schema_version": "pq-sequoia-interop-envelope/v1",
            "phase": "hatchery-phase-a",
            "session_id": "a" * 64,
            "protocol_sha256": module.PROTOCOL_SHA256,
            "producer_closure_sha256": "c" * 64,
            "parent_envelope_sha256": "0" * 64,
            "message_sha256": module.MESSAGE_SHA256,
            "payloads": {},
            "results": {},
            "control_signature": _payload(b"signature"),
        }
        original = module.canonical_transcript(base)
        for field, value in (
            ("session_id", "d" * 64),
            ("protocol_sha256", "e" * 64),
            ("producer_closure_sha256", "f" * 64),
            ("parent_envelope_sha256", "1" * 64),
        ):
            changed = dict(base)
            changed[field] = value
            self.assertNotEqual(original, module.canonical_transcript(changed), field)

    def test_composite_certificate_and_signature_shape_is_enforced(self) -> None:
        module = _load_cli()
        primary = "A" * 64
        signing = "B" * 64
        encryption = "C" * 64
        inspection = f"""OpenPGP Certificate.

      Fingerprint: {primary}
  Public-key algo: ML-DSA-65+Ed25519
         Key flags: certification

           Subkey: {signing}
  Public-key algo: ML-DSA-65+Ed25519
         Key flags: signing

           Subkey: {encryption}
  Public-key algo: ML-KEM-768+X25519
         Key flags: transport encryption, data-at-rest encryption
"""
        shape = module.parse_certificate_inspection(inspection)
        self.assertEqual(signing, shape["signing_fingerprint"])
        self.assertEqual(encryption, shape["encryption_fingerprint"])

        classical = inspection.replace("ML-DSA-65+Ed25519", "Ed25519")
        with self.assertRaisesRegex(module.ProcedureError, "composite key shape"):
            module.parse_certificate_inspection(classical)

        signature_dump = f"""Signature Packet
  Version: 6
  Type: Binary
  Pk algo: ML-DSA-65+Ed25519
    Issuer Fingerprint: {signing}
"""
        module.validate_signature_inspection(signature_dump, signing)
        with self.assertRaisesRegex(module.ProcedureError, "signature algorithm"):
            module.validate_signature_inspection(
                signature_dump.replace("ML-DSA-65+Ed25519", "Ed25519"), signing
            )

    def test_phase_c_requires_signed_parent_and_hatchery_result(self) -> None:
        module = _load_cli()
        envelope = {
            "schema_version": "pq-sequoia-interop-envelope/v1",
            "phase": "hatchery-phase-c",
            "session_id": "a" * 64,
            "candidate_identity": "sha256:" + "b" * 64,
            "message_sha256": module.MESSAGE_SHA256,
            "payloads": {"ciphertext-to-macos-ci.pgp": _payload(b"ciphertext")},
            "results": {
                "peer_signature_verified": True,
                "altered_message_rejected": True,
                "ciphertext_decrypted_byte_identical": True,
                "tampered_ciphertext_rejected_without_output": True,
                "local_cleanup_complete": True,
            },
        }
        with self.assertRaisesRegex(module.ProcedureError, "envelope fields mismatch"):
            module.validate_envelope(envelope, "hatchery-phase-c", "a" * 64)

    def test_reciprocal_artifact_map_must_match_receiver_observations(self) -> None:
        module = _load_cli()
        observed = {
            name: {"sha256": hashlib.sha256(name.encode()).hexdigest(), "size": len(name)}
            for name in module.EXCHANGE_ARTIFACTS
        }
        result = {
            "schema_version": "pq-sequoia-peer-result/v1",
            "producer": "hatchery",
            "session_id": "a" * 64,
            "protocol_sha256": module.PROTOCOL_SHA256,
            "producer_closure_sha256": "c" * 64,
            "peer_closure_sha256": "d" * 64,
            "message_sha256": module.MESSAGE_SHA256,
            "artifact_map": observed,
            "peer_signature_verified": True,
            "altered_message_rejected": True,
            "ciphertext_decrypted_byte_identical": True,
            "tampered_ciphertext_rejected_without_output": True,
            "local_cleanup_complete": True,
        }
        module.validate_peer_result(
            result,
            expected_session="a" * 64,
            expected_producer_closure="c" * 64,
            expected_peer_closure="d" * 64,
            observed_artifacts=observed,
        )
        changed = json.loads(json.dumps(result))
        changed["artifact_map"][next(iter(module.EXCHANGE_ARTIFACTS))]["size"] += 1
        with self.assertRaisesRegex(module.ProcedureError, "artifact map mismatch"):
            module.validate_peer_result(
                changed,
                expected_session="a" * 64,
                expected_producer_closure="c" * 64,
                expected_peer_closure="d" * 64,
                observed_artifacts=observed,
            )

    def test_relay_metadata_binds_exact_run_and_reviewed_commit(self) -> None:
        module = _load_cli()
        metadata = {
            "databaseId": 12345,
            "displayTitle": "expected-title",
            "event": "workflow_dispatch",
            "headSha": "a" * 40,
            "status": "completed",
            "conclusion": "success",
        }
        module.validate_relay_metadata(
            metadata,
            expected_run_id="12345",
            expected_title="expected-title",
            expected_commit="a" * 40,
        )
        with self.assertRaisesRegex(module.ProcedureError, "relay revision mismatch"):
            module.validate_relay_metadata(
                {**metadata, "headSha": "b" * 40},
                expected_run_id="12345",
                expected_title="expected-title",
                expected_commit="a" * 40,
            )

    def test_control_signature_rejects_cross_session_replay(self) -> None:
        module = _load_cli()
        envelope = _envelope(
            module,
            phase="hatchery-phase-a",
            session="a" * 64,
            closure="b" * 64,
            parent="0" * 64,
            payloads={
                "hatchery-cert.pgp": _payload(b"certificate"),
                "hatchery-message.sig": _payload(b"message signature"),
            },
            results={
                "local_revocation_results": _revocations(),
                "local_cleanup_pending": True,
            },
        )
        signature = hashlib.sha256(module.canonical_transcript(envelope)).hexdigest()
        envelope["control_signature"] = _payload(signature.encode())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cert = root / "cert.pgp"
            sig = root / "control.sig"
            transcript = root / "transcript.json"
            cert.write_bytes(b"public certificate")
            sig.write_bytes(signature.encode())
            original = module.run_command

            def checking_run(command, *, environment, expected_success=True):
                supplied = Path(command[-2]).read_text(encoding="ascii")
                observed = hashlib.sha256(Path(command[-1]).read_bytes()).hexdigest()
                if supplied != observed:
                    raise module.ProcedureError("control transcript signature rejected")
                return subprocess.CompletedProcess(command, 0, b"", b"")

            module.run_command = checking_run
            try:
                module.verify_control_signature(
                    Path("sqv"), envelope, cert, sig, transcript, {}
                )
                replayed = dict(envelope)
                replayed["session_id"] = "c" * 64
                with self.assertRaisesRegex(
                    module.ProcedureError, "control transcript signature rejected"
                ):
                    module.verify_control_signature(
                        Path("sqv"), replayed, cert, sig, transcript, {}
                    )
            finally:
                module.run_command = original

    def test_select_kegs_executes_exact_identity_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sq = root / "sq"
            sqv = root / "sqv"
            sq.write_text(
                "#!/bin/sh\nprintf '%s\\n' 'sq 1.4.0 sequoia-openpgp 2.4.1 OpenSSL 3.5.8'\n",
                encoding="utf-8",
            )
            sqv.write_text(
                "#!/bin/sh\nprintf '%s\\n' 'sqv 1.5.0 sequoia-openpgp 2.4.1 OpenSSL 3.5.8'\n",
                encoding="utf-8",
            )
            sq.chmod(0o700)
            sqv.chmod(0o700)
            output = root / "selected.env"
            accepted = self.run_cli(
                "select-kegs",
                "--sq",
                str(sq),
                "--sqv",
                str(sqv),
                "--expected-sq-sha256",
                _sha256(sq),
                "--expected-sqv-sha256",
                _sha256(sqv),
                "--output",
                str(output),
            )
            self.assertEqual(0, accepted.returncode, accepted.stderr)
            self.assertEqual(f"SQ={sq}\nSQV={sqv}\n", output.read_text())
            output.unlink()
            rejected = self.run_cli(
                "select-kegs",
                "--sq",
                str(sq),
                "--sqv",
                str(sqv),
                "--expected-sq-sha256",
                "0" * 64,
                "--expected-sqv-sha256",
                _sha256(sqv),
                "--output",
                str(output),
            )
            self.assertEqual(1, rejected.returncode)
            self.assertFalse(output.exists())

    def test_open_and_close_execute_authenticated_reconciled_exchange(self) -> None:
        module = _load_cli()
        session = "a" * 64
        peer_closure = "b" * 64
        local_closure = _sha256(CANDIDATE)
        phase_a = _envelope(
            module,
            phase="hatchery-phase-a",
            session=session,
            closure=peer_closure,
            parent="0" * 64,
            payloads={
                "hatchery-cert.pgp": _payload(b"hatchery certificate"),
                "hatchery-message.sig": _payload(b"hatchery message signature"),
            },
            results={
                "local_revocation_results": _revocations(),
                "local_cleanup_pending": True,
            },
        )
        phase_a["control_signature"] = _payload(b"hatchery control signature")
        local_result = {
            "schema_version": "pq-sequoia-local-result/v1",
            "candidate_identity": "sha256:" + local_closure,
            "message_sha256": module.MESSAGE_SHA256,
            "local_cleanup_complete": True,
            "local_revocation_results": _revocations(),
        }
        shape = _certificate_shape()
        signature_shape = {
            "version": 6,
            "algorithm": "ML-DSA-65+Ed25519",
            "issuer_fingerprint": shape["signing_fingerprint"],
        }
        verified_controls: list[tuple[str, str]] = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            phase_a_path = root / "phase-a.json"
            local_result_path = root / "local-result.json"
            state = root / "state"
            phase_b_path = root / "phase-b.json"
            _write_json(phase_a_path, phase_a)
            _write_json(local_result_path, local_result)

            originals = (
                module.generate_key,
                module.inspect_certificate,
                module.inspect_signature,
                module.verify_control_signature,
                module.run_command,
            )

            def fake_generate_key(sq, workspace, environment):
                (workspace / "key.pgp").write_bytes(b"local secret placeholder")
                (workspace / "cert.pgp").write_bytes(b"macos certificate")

            def fake_run(command, *, environment, expected_success=True):
                if "--signature-file" in command and "sign" in command:
                    target = Path(command[command.index("--signature-file") + 1])
                    target.write_bytes(b"macos signature")
                if "encrypt" in command:
                    target = Path(command[command.index("--output") + 1])
                    target.write_bytes(b"ciphertext to hatchery")
                if "decrypt" in command and expected_success:
                    target = Path(command[command.index("--output") + 1])
                    target.write_bytes(MESSAGE.read_bytes())
                return subprocess.CompletedProcess(command, 0, b"", b"")

            def fake_verify_control(sqv, envelope, certificate, *args):
                verified_controls.append((envelope["phase"], certificate.name))

            module.generate_key = fake_generate_key
            module.inspect_certificate = lambda *args: shape
            module.inspect_signature = lambda *args: signature_shape
            module.verify_control_signature = fake_verify_control
            module.run_command = fake_run
            try:
                module.interop_open(
                    SimpleNamespace(
                        root=ROOT,
                        sq=Path("/bin/true"),
                        sqv=Path("/bin/true"),
                        candidate_identity="sha256:" + local_closure,
                        expected_peer_closure_sha256=peer_closure,
                        session_id=session,
                        peer_envelope=phase_a_path,
                        local_result=local_result_path,
                        state_dir=state,
                        output=phase_b_path,
                    )
                )
                phase_b = json.loads(phase_b_path.read_text(encoding="utf-8"))
                self.assertEqual(_sha256(phase_a_path), phase_b["parent_envelope_sha256"])
                self.assertIn("control_signature", phase_b)

                state_record = json.loads((state / "state.json").read_text())
                ciphertext = b"ciphertext to macos"
                artifacts = state_record["artifact_map"]
                artifacts["ciphertext-to-macos-ci.pgp"] = {
                    "sha256": hashlib.sha256(ciphertext).hexdigest(),
                    "size": len(ciphertext),
                }
                hatchery_result = {
                    "schema_version": "pq-sequoia-peer-result/v1",
                    "producer": "hatchery",
                    "session_id": session,
                    "protocol_sha256": module.PROTOCOL_SHA256,
                    "producer_closure_sha256": peer_closure,
                    "peer_closure_sha256": local_closure,
                    "message_sha256": module.MESSAGE_SHA256,
                    "artifact_map": artifacts,
                    "peer_signature_verified": True,
                    "altered_message_rejected": True,
                    "ciphertext_decrypted_byte_identical": True,
                    "tampered_ciphertext_rejected_without_output": True,
                    "local_cleanup_complete": True,
                }
                phase_c = _envelope(
                    module,
                    phase="hatchery-phase-c",
                    session=session,
                    closure=peer_closure,
                    parent=_sha256(phase_b_path),
                    payloads={
                        "ciphertext-to-macos-ci.pgp": _payload(ciphertext),
                        "results/hatchery.json": _payload(
                            (json.dumps(hatchery_result, sort_keys=True) + "\n").encode()
                        ),
                    },
                    results={"local_cleanup_complete": True},
                )
                phase_c["control_signature"] = _payload(b"return control signature")
                phase_c_path = root / "phase-c.json"
                _write_json(phase_c_path, phase_c)
                title = f"pq-sequoia-publish-peer-response-{session}-777-{_sha256(phase_b_path)}"
                relay = {
                    "databaseId": 888,
                    "displayTitle": title,
                    "event": "workflow_dispatch",
                    "headSha": "c" * 40,
                    "status": "completed",
                    "conclusion": "success",
                }
                relay_path = root / "relay.json"
                _write_json(relay_path, relay)
                result_path = root / "results/macos-ci.json"
                module.interop_close(
                    SimpleNamespace(
                        root=ROOT,
                        sq=Path("/bin/true"),
                        sqv=Path("/bin/true"),
                        session_id=session,
                        peer_envelope=phase_c_path,
                        state_dir=state,
                        relay_metadata=relay_path,
                        expected_relay_run_id="888",
                        expected_relay_title=title,
                        candidate_commit="c" * 40,
                        output=result_path,
                    )
                )
                result = json.loads(result_path.read_text())
                self.assertEqual(artifacts, result["artifact_map"])
                self.assertEqual(888, result["relay_run"]["databaseId"])
                self.assertEqual(
                    hatchery_result,
                    json.loads(result_path.with_name("hatchery.json").read_text()),
                )
                self.assertTrue(result["local_cleanup_complete"])
                self.assertFalse(state.exists())
                self.assertEqual(
                    [
                        ("hatchery-phase-a", "peer-cert.pgp"),
                        ("hatchery-phase-c", "peer-cert.pgp"),
                    ],
                    verified_controls,
                )
            finally:
                (
                    module.generate_key,
                    module.inspect_certificate,
                    module.inspect_signature,
                    module.verify_control_signature,
                    module.run_command,
                ) = originals

    def test_marked_cleanup_removes_only_the_owned_state(self) -> None:
        module = _load_cli()
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            state.mkdir()
            (state / module.STATE_MARKER).write_text(
                module.STATE_MARKER_CONTENT, encoding="utf-8"
            )
            (state / "secret-placeholder").write_bytes(b"unread disposable bytes")
            result = self.run_cli("cleanup", "--state-dir", str(state))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(state.exists())

    def test_qualify_local_executes_matrix_and_cleans_workspace(self) -> None:
        module = _load_cli()
        shape = _certificate_shape()
        signature_shape = {
            "version": 6,
            "algorithm": "ML-DSA-65+Ed25519",
            "issuer_fingerprint": shape["signing_fingerprint"],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work_root = root / "work"
            output = root / "local-result.json"
            originals = (
                module.generate_key,
                module.inspect_certificate,
                module.inspect_signature,
                module.exercise_revocations,
                module.run_command,
            )

            def fake_generate_key(sq, workspace, environment):
                (workspace / "key.pgp").write_bytes(b"key placeholder")
                (workspace / "cert.pgp").write_bytes(b"certificate")
                (workspace / "emergency-revocation.pgp").write_bytes(b"revocation")

            def fake_run(command, *, environment, expected_success=True):
                if "sign" in command and "--signature-file" in command:
                    Path(command[command.index("--signature-file") + 1]).write_bytes(
                        b"signature"
                    )
                if "encrypt" in command and expected_success:
                    Path(command[command.index("--output") + 1]).write_bytes(
                        b"ciphertext payload"
                    )
                if "decrypt" in command and expected_success:
                    Path(command[command.index("--output") + 1]).write_bytes(
                        MESSAGE.read_bytes()
                    )
                return subprocess.CompletedProcess(command, 0, b"", b"")

            module.generate_key = fake_generate_key
            module.inspect_certificate = lambda *args: shape
            module.inspect_signature = lambda *args: signature_shape
            module.exercise_revocations = lambda *args: _revocations()
            module.run_command = fake_run
            try:
                module.qualify_local(
                    SimpleNamespace(
                        root=ROOT,
                        sq=Path("/bin/true"),
                        sqv=Path("/bin/true"),
                        candidate_identity="sha256:" + _sha256(CANDIDATE),
                        work_root=work_root,
                        output=output,
                    )
                )
            finally:
                (
                    module.generate_key,
                    module.inspect_certificate,
                    module.inspect_signature,
                    module.exercise_revocations,
                    module.run_command,
                ) = originals
            result = json.loads(output.read_text())
            self.assertEqual(shape, result["certificate_shape"])
            self.assertEqual(200, result["sequential_lifecycles"]["sq"])
            self.assertTrue(result["local_cleanup_complete"])
            self.assertEqual([], list(work_root.iterdir()))

    def test_record_runtime_retains_only_closed_macho_observations(self) -> None:
        module = _load_cli()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "runtime.json"
            closure = {
                "root": "/candidate/bin",
                "objects": [
                    {"path": "/candidate/bin", "realpath": "/candidate/bin", "size": 1, "sha256": "a" * 64}
                ],
                "apple_shared_cache": ["/usr/lib/libSystem.B.dylib"],
            }
            original_output = module.tool_output
            original_closure = module.record_macho_closure
            module.tool_output = lambda command: "public tool identity"
            module.record_macho_closure = lambda executable: closure
            try:
                module.record_runtime(
                    SimpleNamespace(
                        sq=Path("/bin/true"),
                        sqv=Path("/bin/true"),
                        openssl=Path("/bin/true"),
                        candidate_identity="sha256:" + _sha256(CANDIDATE),
                        output=output,
                    )
                )
            finally:
                module.tool_output = original_output
                module.record_macho_closure = original_closure
            result = json.loads(output.read_text())
            self.assertEqual("pq-sequoia-runtime-closure/v1", result["schema_version"])
            self.assertEqual(closure, result["closures"]["sq"])
            self.assertNotIn("shared_cache_or_unresolved", json.dumps(result))

    def test_validate_relay_command_writes_only_exact_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = {
                "databaseId": 321,
                "displayTitle": "bound-title",
                "event": "workflow_dispatch",
                "headSha": "a" * 40,
                "status": "completed",
                "conclusion": "success",
            }
            source = root / "source.json"
            output = root / "validated.json"
            _write_json(source, metadata)
            result = self.run_cli(
                "validate-relay",
                "--metadata",
                str(source),
                "--expected-run-id",
                "321",
                "--expected-title",
                "bound-title",
                "--expected-commit",
                "a" * 40,
                "--output",
                str(output),
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(metadata, json.loads(output.read_text()))

            metadata["headSha"] = "b" * 40
            _write_json(source, metadata)
            output.unlink()
            rejected = self.run_cli(
                "validate-relay",
                "--metadata",
                str(source),
                "--expected-run-id",
                "321",
                "--expected-title",
                "bound-title",
                "--expected-commit",
                "a" * 40,
                "--output",
                str(output),
            )
            self.assertEqual(1, rejected.returncode)
            self.assertFalse(output.exists())

    def test_non_system_unresolved_macho_dependency_fails_closed(self) -> None:
        module = _load_cli()
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "candidate-bin"
            executable.write_bytes(b"fake Mach-O")
            original = module.tool_output

            def fake_tool_output(command: list[str]) -> str:
                if command[1] == "-l":
                    return ""
                return (
                    f"{executable}:\n"
                    "\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n"
                    "\t@rpath/libunqualified.dylib (compatibility version 1.0.0)"
                )

            module.tool_output = fake_tool_output
            try:
                with self.assertRaisesRegex(
                    module.ProcedureError, "unresolved non-system Mach-O dependency"
                ):
                    module.record_macho_closure(executable)
            finally:
                module.tool_output = original


def _payload(content: bytes) -> dict[str, object]:
    return {
        "encoding": "base64",
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "data": base64.b64encode(content).decode("ascii"),
    }


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _revocations() -> dict[str, object]:
    return {
        name: {"passed": True, "sha256": hashlib.sha256(name.encode()).hexdigest(), "size": 1}
        for name in (
            "emergency_certificate",
            "retired_certificate",
            "retired_signing_subkey",
            "retired_encryption_subkey",
        )
    }


def _envelope(module, *, phase, session, closure, parent, payloads, results):
    return {
        "schema_version": "pq-sequoia-interop-envelope/v1",
        "phase": phase,
        "session_id": session,
        "protocol_sha256": module.PROTOCOL_SHA256,
        "producer_closure_sha256": closure,
        "parent_envelope_sha256": parent,
        "message_sha256": module.MESSAGE_SHA256,
        "payloads": payloads,
        "results": results,
    }


def _certificate_shape() -> dict[str, object]:
    return {
        "primary_fingerprint": "A" * 64,
        "primary_version": 6,
        "primary_algorithm": "ML-DSA-65+Ed25519",
        "primary_capabilities": ["certification"],
        "signing_fingerprint": "B" * 64,
        "signing_version": 6,
        "signing_algorithm": "ML-DSA-65+Ed25519",
        "signing_capabilities": ["signing"],
        "encryption_fingerprint": "C" * 64,
        "encryption_version": 6,
        "encryption_algorithm": "ML-KEM-768+X25519",
        "encryption_capabilities": ["transport encryption", "data-at-rest encryption"],
        "authentication_capable": False,
    }


if __name__ == "__main__":
    unittest.main()
