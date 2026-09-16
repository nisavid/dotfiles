from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SURFACE = ROOT / "docs/crypto/pq-sequoia-macos"
PROTOCOL = SURFACE / "interop-v1.json"
MESSAGE = SURFACE / "fixtures/v1/message.bin"
PACKAGE_ROOT = ROOT / "packaging/homebrew/pq-sequoia-macos/v1"
CANDIDATE = PACKAGE_ROOT / "candidate.json"
CLI = ROOT / "scripts/pq-sequoia-macos"
WORKFLOW = ROOT / ".github/workflows/pq-sequoia-macos.yml"
PROCEDURE = SURFACE / "PROCEDURE.md"


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
            "candidate_identity": "sha256:" + "b" * 64,
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


def _payload(content: bytes) -> dict[str, object]:
    return {
        "encoding": "base64",
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "data": base64.b64encode(content).decode("ascii"),
    }


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


if __name__ == "__main__":
    unittest.main()
