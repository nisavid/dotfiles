from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
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
        relay = protocol["relay_binding"]
        self.assertIn("phase-B envelope digest", relay["selection"])
        coverage = relay["observation_coverage"]
        self.assertEqual("GET", coverage["method"])
        self.assertEqual(100, coverage["per_page"])
        self.assertEqual([], coverage["named_search_filters"])
        self.assertIn("--paginate", coverage["pagination"])
        self.assertNotIn("requested_limit", coverage)
        self.assertNotIn("accepted_maximum", coverage)
        self.assertIn("runAttempt", coverage["projected_run_fields"])
        self.assertEqual(
            ["relay-observation-selection.json", "relay-observation-final.json"],
            relay["retained_observations"],
        )
        self.assertEqual(
            ["relay-observation-selection.json", "relay-observation-final.json"],
            relay["rejected_observations"]["files"],
        )
        self.assertIn(
            "failure-only", relay["rejected_observations"]["retention"]
        )
        self.assertIn(
            "explicit rejected outcome and reason",
            relay["rejected_observations"]["retention"],
        )
        self.assertIn("queued", relay["duplicate_rule"])
        self.assertIn("completed unsuccessful", relay["duplicate_rule"])
        self.assertIn("greater than 1", relay["rerun_rule"])
        self.assertIn("fresh session", protocol["session"]["execution_attempts"])
        self.assertIn("Submissions after the final check", relay["temporal_limit"])
        self.assertIn("not a permanent or global uniqueness", relay["temporal_limit"])

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

    def fake_gh(
        self,
        root: Path,
        pages: list[object],
        *,
        exit_code: int = 0,
        pause_seconds: float = 0,
    ) -> tuple[Path, Path]:
        fixture = root / "gh-pages.json"
        invocation = root / "gh-invocation.json"
        executable = root / "gh"
        _write_json(fixture, pages)
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "import sys\n"
            "import time\n"
            "from pathlib import Path\n"
            f"fixture = Path({str(fixture)!r})\n"
            f"invocation = Path({str(invocation)!r})\n"
            "invocation.write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
            "for page in json.loads(fixture.read_text(encoding='utf-8')):\n"
            "    print(json.dumps(page), flush=True)\n"
            f"time.sleep({pause_seconds!r})\n"
            f"raise SystemExit({exit_code})\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        return executable, invocation

    def relay_arguments(
        self,
        root: Path,
        gh: Path,
        *,
        stage: str = "selection",
        selected_run_id: str | None = None,
        timeout: str = "5",
    ) -> list[str]:
        arguments = [
            "record-relay-observation",
            "--repository",
            "example/project",
            "--gh",
            str(gh),
            "--query-timeout-seconds",
            timeout,
            "--stage",
            stage,
            "--session-id",
            "c" * 64,
            "--qualifier-run-id",
            "987",
            "--phase-b-sha256",
            "d" * 64,
            "--expected-commit",
            "a" * 40,
        ]
        if selected_run_id is not None:
            arguments.extend(("--selected-run-id", selected_run_id))
        arguments.extend(("--output", str(root / f"{stage}.json")))
        return arguments

    def test_repo_local_command_validates_the_frozen_public_surface(self) -> None:
        result = self.run_cli("validate-static", "--root", str(ROOT))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("pq-sequoia-macos static surface: valid\n", result.stdout)

    def test_static_validation_binds_closed_runner_declaration_to_workflow(
        self,
    ) -> None:
        expected_runner = {
            "label": "macos-15",
            "runner_environment": "github-hosted",
            "runner_os": "macOS",
            "runner_arch": "ARM64",
            "hardware_arch": "arm64",
            "macos_major": "15",
        }
        mutations = {
            "label": "macos-14",
            "runner_environment": "self-hosted",
            "runner_os": "Linux",
            "runner_arch": "X64",
            "hardware_arch": "x86_64",
            "macos_major": "14",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                "docs/crypto/pq-sequoia-macos",
                "packaging/homebrew/pq-sequoia-macos/v1",
                ".github/workflows",
            ):
                shutil.copytree(ROOT / relative, root / relative)
            candidate_path = (
                root / "packaging/homebrew/pq-sequoia-macos/v1/candidate.json"
            )
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            self.assertEqual(expected_runner, candidate["runner"])

            aligned = self.run_cli("validate-static", "--root", str(root))
            self.assertEqual(0, aligned.returncode, aligned.stderr)

            for field, value in mutations.items():
                with self.subTest(field=field):
                    changed = json.loads(json.dumps(candidate))
                    changed["runner"][field] = value
                    _write_json(candidate_path, changed)
                    rejected = self.run_cli(
                        "validate-static", "--root", str(root)
                    )
                    self.assertEqual(1, rejected.returncode)
                    self.assertIn(
                        "candidate runner boundary mismatch", rejected.stderr
                    )

            changed = json.loads(json.dumps(candidate))
            changed["runner"]["unexpected"] = "unsupported"
            _write_json(candidate_path, changed)
            rejected = self.run_cli("validate-static", "--root", str(root))
            self.assertEqual(1, rejected.returncode)
            self.assertIn("candidate runner boundary mismatch", rejected.stderr)

    def test_source_signature_requires_one_exact_validsig_identity(self) -> None:
        candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
        statuses = {
            "sq": (
                candidate["applications"]["sq"]["signer_subkey_fingerprint"],
                candidate["applications"]["sq"]["signer_primary_fingerprint"],
            ),
            "sqv": (
                candidate["applications"]["sqv"]["signer_subkey_fingerprint"],
                candidate["applications"]["sqv"]["signer_primary_fingerprint"],
            ),
            "openssl": (
                candidate["openssl"]["signer_subkey_fingerprint"],
                candidate["openssl"]["signer_primary_fingerprint"],
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate_path = root / "candidate.json"
            _write_json(candidate_path, candidate)
            for source, (signing, primary) in statuses.items():
                with self.subTest(source=source):
                    status = root / f"{source}.status"
                    output = root / f"{source}.json"
                    status.write_text(
                        _validsig_status(signing=signing, primary=primary),
                        encoding="utf-8",
                    )
                    accepted = self.run_cli(
                        "verify-gpg-status",
                        "--candidate",
                        str(candidate_path),
                        "--source",
                        source,
                        "--status",
                        str(status),
                        "--output",
                        str(output),
                    )
                    self.assertEqual(0, accepted.returncode, accepted.stderr)
                    record = json.loads(output.read_text(encoding="utf-8"))
                    self.assertEqual(signing, record["signing_fingerprint"])
                    self.assertEqual(primary, record["primary_fingerprint"])

                    changed = json.loads(json.dumps(candidate))
                    owner = (
                        changed["openssl"]
                        if source == "openssl"
                        else changed["applications"][source]
                    )
                    owner["signer_subkey_fingerprint"] = "D" * 40
                    _write_json(candidate_path, changed)
                    output.unlink()
                    rejected = self.run_cli(
                        "verify-gpg-status",
                        "--candidate",
                        str(candidate_path),
                        "--source",
                        source,
                        "--status",
                        str(status),
                        "--output",
                        str(output),
                    )
                    self.assertEqual(1, rejected.returncode)
                    self.assertIn("signing fingerprint mismatch", rejected.stderr)
                    self.assertFalse(output.exists())
                    _write_json(candidate_path, candidate)

            signing, primary = statuses["openssl"]
            status = root / "openssl.status"
            output = root / "openssl.json"
            invalid_cases = {
                "missing": "[GNUPG:] GOODSIG fixture\n",
                "duplicate": _validsig_status(signing=signing, primary=primary) * 2,
                "malformed": (
                    f"[GNUPG:] VALIDSIG {signing} 2026-09-29 1790697600 "
                    "0 4 0 22 8 00\n"
                ),
            }
            for label, content in invalid_cases.items():
                with self.subTest(label=label):
                    status.write_text(content, encoding="utf-8")
                    rejected = self.run_cli(
                        "verify-gpg-status",
                        "--candidate",
                        str(candidate_path),
                        "--source",
                        "openssl",
                        "--status",
                        str(status),
                        "--output",
                        str(output),
                    )
                    self.assertEqual(1, rejected.returncode)
                    self.assertIn("exactly one valid VALIDSIG", rejected.stderr)
                    self.assertFalse(output.exists())

    def test_success_evidence_retains_exact_source_status_preimages(self) -> None:
        candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
        signers = {
            "sq": candidate["applications"]["sq"],
            "sqv": candidate["applications"]["sqv"],
            "openssl": candidate["openssl"],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence"
            evidence.mkdir()
            candidate_path = root / "candidate.json"
            _write_json(candidate_path, candidate)

            for source, signer in signers.items():
                status = root / f"{source}.status"
                receipt = evidence / f"source-{source}-signer.json"
                retained = evidence / f"source-{source}-validsig.status"
                status.write_text(
                    _validsig_status(
                        signing=signer["signer_subkey_fingerprint"],
                        primary=signer["signer_primary_fingerprint"],
                    ),
                    encoding="utf-8",
                )
                accepted = self.run_cli(
                    "verify-gpg-status",
                    "--candidate",
                    str(candidate_path),
                    "--source",
                    source,
                    "--status",
                    str(status),
                    "--output",
                    str(receipt),
                )
                self.assertEqual(0, accepted.returncode, accepted.stderr)
                shutil.copyfile(status, retained)
                self.assertEqual(
                    json.loads(receipt.read_text(encoding="utf-8"))["status_sha256"],
                    _sha256(retained),
                )

            self.assertEqual(
                {
                    "source-openssl-signer.json",
                    "source-openssl-validsig.status",
                    "source-sq-signer.json",
                    "source-sq-validsig.status",
                    "source-sqv-signer.json",
                    "source-sqv-validsig.status",
                },
                {path.name for path in evidence.iterdir()},
            )

        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            'cp "$signer_status" "$PQ_SCRATCH/evidence/source-$component-validsig.status"',
            workflow,
        )
        self.assertIn(
            'cp "$openssl_signer_status" "$PQ_SCRATCH/evidence/source-openssl-validsig.status"',
            workflow,
        )
        qualification_upload = workflow[
            workflow.index("- name: Upload value-free qualification evidence") :
            workflow.index("- name: Upload rejected relay observations")
        ]
        self.assertIn("/evidence", qualification_upload)
        for forbidden in ("/downloads", "/gnupg", "/private", "pubkeys", ".tar"):
            self.assertNotIn(forbidden, qualification_upload)

    def test_prepatch_archive_must_match_the_signed_commit_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "source.git"
            repository.mkdir()
            git_environment = _closed_git_environment()
            subprocess.run(
                ["git", "init", "--quiet", str(repository)],
                check=True,
                env=git_environment,
            )
            (repository / "README.md").write_bytes(b"fixture\n")
            executable = repository / "bin/tool"
            executable.parent.mkdir()
            executable.write_bytes(b"#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            (repository / "README.link").symlink_to("README.md")
            subprocess.run(
                ["git", "-C", str(repository), "add", "--", "."],
                check=True,
                env=git_environment,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "-c",
                    "user.name=PQ source fixture",
                    "-c",
                    "user.email=pq-source.invalid@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "commit",
                    "--quiet",
                    "--no-gpg-sign",
                    "--message",
                    "Create signed-tree fixture",
                ],
                check=True,
                env=git_environment,
            )
            commit = subprocess.run(
                ["git", "-C", str(repository), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
                env=git_environment,
            ).stdout.strip()
            archive = root / "archive"
            shutil.copytree(
                repository,
                archive,
                symlinks=True,
                ignore=shutil.ignore_patterns(".git"),
            )
            output = root / "tree-verification.json"
            accepted = self.run_cli(
                "verify-archive-tree",
                "--repository",
                str(repository),
                "--commit",
                commit,
                "--archive-root",
                str(archive),
                "--output",
                str(output),
            )
            self.assertEqual(0, accepted.returncode, accepted.stderr)
            record = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(commit, record["commit"])
            self.assertEqual(3, record["entry_count"])
            self.assertEqual(
                record["commit_normalized_tree_sha256"],
                record["archive_normalized_tree_sha256"],
            )
            self.assertTrue(record["tree_match"])

            (archive / "README.md").write_bytes(b"different but digest-pinned\n")
            output.unlink()
            rejected = self.run_cli(
                "verify-archive-tree",
                "--repository",
                str(repository),
                "--commit",
                commit,
                "--archive-root",
                str(archive),
                "--output",
                str(output),
            )
            self.assertEqual(1, rejected.returncode)
            self.assertIn("archive tree does not match", rejected.stderr)
            self.assertFalse(output.exists())

    def test_active_homebrew_formula_must_match_frozen_core_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            core = root / "homebrew-core"
            openssl_formula = "openssl@3.5.rb"
            formula_relative_path = f"Formula/o/{openssl_formula}"
            formula = core / formula_relative_path
            formula.parent.mkdir(parents=True)
            formula.write_bytes(b"class OpensslAT35 < Formula\nend\n")
            git_environment = _closed_git_environment()
            subprocess.run(
                ["git", "init", "--quiet", str(core)],
                check=True,
                env=git_environment,
            )
            subprocess.run(
                ["git", "-C", str(core), "add", "--", formula_relative_path],
                check=True,
                env=git_environment,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(core),
                    "-c",
                    "user.name=PQ formula fixture",
                    "-c",
                    "user.email=pq-formula.invalid@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "commit",
                    "--quiet",
                    "--no-gpg-sign",
                    "--message",
                    "Create formula fixture",
                ],
                check=True,
                env=git_environment,
            )
            commit = subprocess.run(
                ["git", "-C", str(core), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
                env=git_environment,
            ).stdout.strip()
            candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
            candidate["openssl"]["homebrew_core_commit"] = commit
            candidate["openssl"]["homebrew_core_formula_path"] = formula_relative_path
            candidate["openssl"]["formula_sha256"] = _sha256(formula)
            candidate_path = root / "candidate.json"
            _write_json(candidate_path, candidate)
            downloaded = root / f"downloaded-{openssl_formula}"
            shutil.copyfile(formula, downloaded)
            output = root / "formula-verification.json"

            accepted = self.run_cli(
                "verify-homebrew-formula",
                "--candidate",
                str(candidate_path),
                "--core-root",
                str(core),
                "--active-formula",
                str(formula),
                "--output",
                str(output),
            )
            self.assertEqual(0, accepted.returncode, accepted.stderr)
            record = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(commit, record["homebrew_core_revision"])
            self.assertEqual(_sha256(formula), record["formula_sha256"])

            formula.write_bytes(b"class DifferentFormula < Formula\nend\n")
            self.assertEqual(
                candidate["openssl"]["formula_sha256"], _sha256(downloaded)
            )
            output.unlink()
            changed_formula = self.run_cli(
                "verify-homebrew-formula",
                "--candidate",
                str(candidate_path),
                "--core-root",
                str(core),
                "--active-formula",
                str(formula),
                "--output",
                str(output),
            )
            self.assertEqual(1, changed_formula.returncode)
            self.assertIn(
                "active OpenSSL formula digest mismatch", changed_formula.stderr
            )
            self.assertFalse(output.exists())

            shutil.copyfile(downloaded, formula)
            (core / "unrelated.txt").write_text("new revision\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(core), "add", "--", "unrelated.txt"],
                check=True,
                env=git_environment,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(core),
                    "-c",
                    "user.name=PQ formula fixture",
                    "-c",
                    "user.email=pq-formula.invalid@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "commit",
                    "--quiet",
                    "--no-gpg-sign",
                    "--message",
                    "Advance core fixture",
                ],
                check=True,
                env=git_environment,
            )
            changed_revision = self.run_cli(
                "verify-homebrew-formula",
                "--candidate",
                str(candidate_path),
                "--core-root",
                str(core),
                "--active-formula",
                str(formula),
                "--output",
                str(output),
            )
            self.assertEqual(1, changed_revision.returncode)
            self.assertIn("Homebrew core revision mismatch", changed_revision.stderr)
            self.assertFalse(output.exists())

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

    def test_openssl_preflight_consumes_output_and_preserves_failures(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        start = workflow.index("          openssl_prefix=$(brew --prefix openssl@3.5)")
        end = workflow.index("          printf 'PQ_OPENSSL_PREFIX=", start)
        preflight = "\n".join(line[10:] for line in workflow[start:end].splitlines())
        with tempfile.TemporaryDirectory(prefix="pq-openssl-preflight-") as temporary:
            root = Path(temporary)
            tools = root / "bin"
            tools.mkdir()
            brew = tools / "brew"
            brew.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$FAKE_OPENSSL_PREFIX"\n',
                encoding="utf-8",
            )
            brew.chmod(0o755)
            openssl = tools / "openssl"
            openssl.write_text(
                "#!/usr/bin/env python3\n"
                "import os, signal, sys\n"
                "signal.signal(signal.SIGPIPE, signal.SIG_DFL)\n"
                "if sys.argv[1:] == ['version']:\n"
                "    print('OpenSSL 3.5.8 fixture')\n"
                "    raise SystemExit(0)\n"
                "algorithms = {'-signature-algorithms': 'ML-DSA-65', "
                "'-kem-algorithms': 'ML-KEM-768'}\n"
                "argument = sys.argv[2]\n"
                "mode = os.environ['FAKE_MODE'] if argument == "
                "os.environ['FAKE_ARGUMENT'] else 'present'\n"
                "print('unrelated' if mode == 'absent' else algorithms[argument], "
                "flush=True)\n"
                "if mode == 'continued-output':\n"
                "    for _ in range(1024):\n"
                "        os.write(1, b'continued output\\n' * 256)\n"
                "if mode == 'producer-failure':\n"
                "    raise SystemExit(23)\n",
                encoding="utf-8",
            )
            openssl.chmod(0o755)
            for argument in ("-signature-algorithms", "-kem-algorithms"):
                for mode, expected in (
                    ("continued-output", 0),
                    ("absent", 1),
                    ("producer-failure", 23),
                ):
                    with self.subTest(argument=argument, mode=mode):
                        environment = {
                            **os.environ,
                            "PATH": str(tools) + os.pathsep + os.environ["PATH"],
                            "FAKE_OPENSSL_PREFIX": str(root),
                            "FAKE_ARGUMENT": argument,
                            "FAKE_MODE": mode,
                        }
                        result = subprocess.run(
                            [
                                "bash", "--noprofile", "--norc", "-euo",
                                "pipefail", "-c", preflight,
                            ],
                            cwd=root,
                            env=environment,
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=10,
                        )
                        self.assertEqual(expected, result.returncode, result.stderr)

    def test_manual_workflow_binds_revision_runner_and_live_relay(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("\n  push:", workflow)
        self.assertIn("runs-on: macos-15", workflow)
        self.assertIn("RUNNER_ENVIRONMENT", workflow)
        self.assertIn("GITHUB_WORKFLOW_SHA", workflow)
        self.assertIn("validate-relay", workflow)
        self.assertEqual(2, workflow.count("record-relay-observation"))
        self.assertEqual(2, workflow.count('--repository "$GITHUB_REPOSITORY"'))
        self.assertNotIn("gh run list", workflow)
        self.assertNotIn("--event workflow_dispatch", workflow)
        self.assertNotIn("--limit 1000", workflow)
        self.assertIn("relay-observation-selection.json", workflow)
        self.assertIn("relay-observation-final.json", workflow)
        self.assertEqual(2, workflow.count('.decision.outcome == "rejected"'))
        self.assertIn(
            "pq-sequoia-macos-rejected-relay-${{ inputs.session_id }}", workflow
        )
        rejected_upload = workflow[
            workflow.index("- name: Upload rejected relay observations") :
            workflow.index("- name: Clean disposable secret material")
        ]
        self.assertIn("if: failure()", rejected_upload)
        self.assertIn(
            "rejected-evidence/relay-observation-selection.json",
            rejected_upload,
        )
        self.assertIn(
            "rejected-evidence/relay-observation-final.json", rejected_upload
        )
        self.assertNotIn("/evidence\n", rejected_upload)
        qualification_upload = workflow[
            workflow.index("- name: Upload value-free qualification evidence") :
            workflow.index("- name: Upload rejected relay observations")
        ]
        self.assertIn("if: success()", qualification_upload)
        self.assertNotIn(
            '.displayTitle == $target and .status == "completed"', workflow
        )
        self.assertLess(
            workflow.index("- name: Close the live interoperability phase"),
            workflow.index("- name: Check relay again before final evidence"),
        )
        self.assertLess(
            workflow.index("- name: Check relay again before final evidence"),
            workflow.index("- name: Finalize value-free evidence"),
        )
        self.assertIn("PQ_PHASE_B_SHA256", workflow)
        self.assertIn("--expected-producer-closure-sha256", workflow)
        self.assertIn("--expected-parent-sha256", workflow)
        self.assertIn("ImageVersion", workflow)
        self.assertIn("interop-open", workflow)
        self.assertIn("publish-peer-response", workflow)
        self.assertIn("interop-close", workflow)
        self.assertIn("if: always()", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertEqual(2, workflow.count('[[ "$GITHUB_WORKFLOW_SHA" =='))
        self.assertEqual(2, workflow.count('[[ "${GITHUB_RUN_ATTEMPT:?}" == 1 ]]'))
        self.assertNotIn("home/", workflow)
        self.assertNotIn("actions/cache", workflow)
        self.assertEqual(2, workflow.count("base64 --decode"))
        self.assertIn("verify-gpg-status", workflow)
        self.assertIn("verify-archive-tree", workflow)
        self.assertIn("verify-homebrew-formula", workflow)
        self.assertIn("HOMEBREW_NO_INSTALL_FROM_API=1", workflow)
        self.assertLess(
            workflow.index("verify-homebrew-formula"),
            workflow.index("brew install capnp gnupg pkgconf"),
        )
        self.assertLess(
            workflow.index("verify-archive-tree"), workflow.index('patch -d "$sources')
        )

        procedure = PROCEDURE.read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("scripts/pq-sequoia-macos validate-static", procedure)
        self.assertIn("pq-sequoia-macos/PROCEDURE.md", readme)
        self.assertIn("dotfiles #148", procedure)
        self.assertIn("record-relay-observation", procedure)
        self.assertIn("relay-observation-selection.json", procedure)
        self.assertIn("relay-observation-final.json", procedure)
        self.assertIn("failure-only relay artifact", procedure)
        self.assertIn("explicit rejected", procedure)
        self.assertIn("outcome and reason", procedure)
        self.assertIn("Submissions after the final check", procedure)
        self.assertIn("not a permanent or global uniqueness", procedure)
        self.assertIn("source-sq-validsig.status", procedure)
        self.assertIn("source-sqv-validsig.status", procedure)
        self.assertIn("source-openssl-validsig.status", procedure)
        self.assertIn("fresh session identifier and new workflow runs", procedure)
        normalized_procedure = " ".join(procedure.split())
        self.assertIn("same locally merged artifact", normalized_procedure)
        self.assertIn(
            "creates and verifies a fresh detached signature", normalized_procedure
        )
        self.assertIn("decrypts byte-for-byte", normalized_procedure)
        self.assertIn("leave no output path", normalized_procedure)

    def test_workflow_rejects_reruns_before_exchange_input_use(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        qualify_guard = "- name: Reject a qualification rerun before exchange input use"
        response_guard = "- name: Reject a response rerun before exchange input use"

        self.assertLess(
            workflow.index(qualify_guard),
            workflow.index("- name: Check out the reviewed qualification revision"),
        )
        self.assertLess(
            workflow.index(response_guard),
            workflow.index("- name: Check out the reviewed relay revision"),
        )

        for guard in (qualify_guard, response_guard):
            with self.subTest(guard=guard):
                step = workflow[workflow.index(guard) :]
                step = step[: step.index("\n      - name:")]
                run_lines = step[step.index("        run: |\n") + len("        run: |\n") :]
                run_script = "\n".join(
                    line.removeprefix("          ")
                    for line in run_lines.splitlines()
                )
                first_attempt = subprocess.run(
                    ["bash", "-c", run_script],
                    cwd=ROOT,
                    env={**os.environ, "GITHUB_RUN_ATTEMPT": "1"},
                    capture_output=True,
                    text=True,
                    check=False,
                )
                rerun = subprocess.run(
                    ["bash", "-c", run_script],
                    cwd=ROOT,
                    env={**os.environ, "GITHUB_RUN_ATTEMPT": "2"},
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(0, first_attempt.returncode, first_attempt.stderr)
                self.assertNotEqual(0, rerun.returncode)

    def test_final_duplicate_failure_retains_both_observation_preimages(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        step = workflow[
            workflow.index("- name: Check relay again before final evidence") :
            workflow.index("- name: Finalize value-free evidence")
        ]
        failure_branch = step[step.index("            relay_status=$?") :]
        failure_script = "false\n" + textwrap.dedent(failure_branch)

        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            for name in ("public", "evidence", "rejected-evidence"):
                (scratch / name).mkdir()
            selection = scratch / "evidence/relay-observation-selection.json"
            final = scratch / "public/relay-observation-final.json"
            selection_bytes = b'{"schema_version":"pq-sequoia-relay-observation/v1","stage":"selection"}\n'
            final_bytes = (
                b'{"schema_version":"pq-sequoia-relay-observation/v1",'
                b'"stage":"final","decision":{"outcome":"rejected",'
                b'"reason":"matching relay duplicate observed"},'
                b'"exchange_binding":{"selected_run_id":null},'
                b'"coverage":{"pagination_complete":true},'
                b'"matching_runs":[{"databaseId":1},{"databaseId":2}]}\n'
            )
            selection.write_bytes(selection_bytes)
            final.write_bytes(final_bytes)

            retained = subprocess.run(
                ["bash", "-c", failure_script],
                cwd=ROOT,
                env={**os.environ, "PQ_SCRATCH": str(scratch)},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(1, retained.returncode, retained.stderr)
            rejected = scratch / "rejected-evidence"
            self.assertEqual(
                {
                    "relay-observation-final.json",
                    "relay-observation-selection.json",
                },
                {path.name for path in rejected.iterdir()},
            )
            self.assertEqual(
                selection_bytes,
                (rejected / "relay-observation-selection.json").read_bytes(),
            )
            self.assertEqual(
                final_bytes,
                (rejected / "relay-observation-final.json").read_bytes(),
            )

        rejected_upload = workflow[
            workflow.index("- name: Upload rejected relay observations") :
            workflow.index("- name: Clean disposable secret material")
        ]
        upload_files = {
            line.rsplit("/", 1)[-1]
            for line in rejected_upload.splitlines()
            if "/rejected-evidence/" in line
        }
        self.assertEqual(
            {
                "relay-observation-final.json",
                "relay-observation-selection.json",
            },
            upload_files,
        )

    def test_rerun_failures_retain_the_allowlisted_observation_preimages(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        rerun_bytes = (
            b'{"schema_version":"pq-sequoia-relay-observation/v1",'
            b'"decision":{"outcome":"rejected",'
            b'"reason":"matching relay rerun observed"},'
            b'"exchange_binding":{"selected_run_id":null},'
            b'"coverage":{"pagination_complete":true},'
            b'"matching_runs":[{"databaseId":1,"runAttempt":2}],'
            b'"stage":"STAGE"}\n'
        )
        selection_bytes = b'{"schema_version":"pq-sequoia-relay-observation/v1","stage":"selection"}\n'

        for stage, step_start, step_end in (
            (
                "selection",
                "- name: Wait for the matching public peer response",
                "- name: Close the live interoperability phase",
            ),
            (
                "final",
                "- name: Check relay again before final evidence",
                "- name: Finalize value-free evidence",
            ),
        ):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                step = workflow[
                    workflow.index(step_start) : workflow.index(step_end)
                ]
                failure_branch = step[step.index("            relay_status=$?") :]
                if stage == "selection":
                    failure_branch = failure_branch[
                        : failure_branch.index("            if [[")
                    ]
                failure_script = "false\n" + textwrap.dedent(failure_branch)

                scratch = Path(directory)
                for name in ("public", "evidence", "rejected-evidence"):
                    (scratch / name).mkdir()
                observation = scratch / f"public/relay-observation-{stage}.json"
                observation_bytes = rerun_bytes.replace(b"STAGE", stage.encode())
                observation.write_bytes(observation_bytes)
                if stage == "final":
                    (scratch / "evidence/relay-observation-selection.json").write_bytes(
                        selection_bytes
                    )

                retained = subprocess.run(
                    ["bash", "-c", failure_script],
                    cwd=ROOT,
                    env={**os.environ, "PQ_SCRATCH": str(scratch)},
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertEqual(1, retained.returncode, retained.stderr)
                rejected = scratch / "rejected-evidence"
                self.assertEqual(
                    observation_bytes,
                    (rejected / f"relay-observation-{stage}.json").read_bytes(),
                )
                if stage == "final":
                    self.assertEqual(
                        selection_bytes,
                        (rejected / "relay-observation-selection.json").read_bytes(),
                    )

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

    def test_protocol_positive_sizes_reject_booleans_and_accept_integer_boundaries(
        self,
    ) -> None:
        module = _load_cli()
        one_byte = _payload(b"x")
        maximum = _payload(b"x" * module.MAX_PAYLOAD_BYTES)
        self.assertEqual(b"x", module.decode_payload("fixture", one_byte))
        self.assertEqual(
            module.MAX_PAYLOAD_BYTES,
            len(module.decode_payload("fixture", maximum)),
        )

        revocations = _revocations()
        module.validate_revocations(revocations)
        artifacts = {
            name: {"sha256": hashlib.sha256(name.encode()).hexdigest(), "size": 1}
            for name in module.EXCHANGE_ARTIFACTS
        }
        module.validate_artifact_map(artifacts)

        for boolean in (True, False):
            with self.subTest(seam="payload", value=boolean):
                changed_payload = dict(one_byte)
                changed_payload["size"] = boolean
                with self.assertRaisesRegex(
                    module.ProcedureError, "payload size is invalid"
                ):
                    module.decode_payload("fixture", changed_payload)

            with self.subTest(seam="revocation", value=boolean):
                changed_revocations = json.loads(json.dumps(revocations))
                changed_revocations["emergency_certificate"]["size"] = boolean
                with self.assertRaisesRegex(
                    module.ProcedureError, "revocation size is invalid"
                ):
                    module.validate_revocations(changed_revocations)

            with self.subTest(seam="artifact-map", value=boolean):
                changed_artifacts = json.loads(json.dumps(artifacts))
                changed_artifacts["message.bin"]["size"] = boolean
                with self.assertRaisesRegex(
                    module.ProcedureError, "artifact size is invalid"
                ):
                    module.validate_artifact_map(changed_artifacts)

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

    def test_certificate_versions_come_from_packet_dump(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            certificate = root / "certificate.pgp"
            certificate.write_bytes(b"public certificate fixture")
            output = root / "inspection.json"

            version_four = _write_sq_inspection_fixture(root / "sq-v4", 4)
            rejected = self.run_cli(
                "inspect-certificate",
                "--sq",
                str(version_four),
                "--certificate",
                str(certificate),
                "--output",
                str(output),
            )
            self.assertEqual(1, rejected.returncode)
            self.assertIn("key packet version mismatch", rejected.stderr)
            self.assertFalse(output.exists())

            version_six = _write_sq_inspection_fixture(root / "sq-v6", 6)
            accepted = self.run_cli(
                "inspect-certificate",
                "--sq",
                str(version_six),
                "--certificate",
                str(certificate),
                "--output",
                str(output),
            )
            self.assertEqual(0, accepted.returncode, accepted.stderr)
            shape = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(6, shape["primary_version"])
            self.assertEqual(6, shape["signing_version"])
            self.assertEqual(6, shape["encryption_version"])

    def test_certificate_key_fields_stay_with_their_packet_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            certificate = root / "certificate.pgp"
            certificate.write_bytes(b"public certificate fixture")
            output = root / "inspection.json"

            # New evidence recreated from the pinned sq 1.4.0 packet-dump
            # interface and RFC 9980's transferable-public-key structure.
            sq = _write_sq_inspection_fixture(root / "sq", 6)
            accepted = self.run_cli(
                "inspect-certificate",
                "--sq",
                str(sq),
                "--certificate",
                str(certificate),
                "--output",
                str(output),
            )

            self.assertEqual(0, accepted.returncode, accepted.stderr)
            shape = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("ML-DSA-65+Ed25519", shape["primary_algorithm"])
            self.assertEqual("ML-DSA-65+Ed25519", shape["signing_algorithm"])
            self.assertEqual("ML-KEM-768+X25519", shape["encryption_algorithm"])

    def test_certificate_rejects_malformed_key_packet_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            certificate = root / "certificate.pgp"
            certificate.write_bytes(b"public certificate fixture")
            output = root / "inspection.json"

            sq = _write_sq_inspection_fixture(
                root / "sq-malformed", 6, omit_encryption_fingerprint=True
            )
            rejected = self.run_cli(
                "inspect-certificate",
                "--sq",
                str(sq),
                "--certificate",
                str(certificate),
                "--output",
                str(output),
            )

            self.assertEqual(1, rejected.returncode)
            self.assertIn("key packet observation mismatch", rejected.stderr)
            self.assertFalse(output.exists())

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
            "runAttempt": 1,
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

    def test_phase_b_binds_exact_runtime_closure_through_public_cli(self) -> None:
        module = _load_cli()
        session = "a" * 64
        peer_closure = "b" * 64
        candidate_digest = _sha256(CANDIDATE)
        phase_a = _envelope(
            module,
            phase="hatchery-phase-a",
            session=session,
            closure=peer_closure,
            parent="0" * 64,
            payloads={
                "hatchery-cert.pgp": _payload(b"public certificate fixture"),
                "hatchery-message.sig": _payload(b"public signature fixture"),
            },
            results={
                "local_revocation_results": _revocations(),
                "local_cleanup_pending": True,
            },
        )
        phase_a["control_signature"] = _payload(b"public control signature fixture")
        local_result = {
            "schema_version": "pq-sequoia-local-result/v1",
            "candidate_identity": "sha256:" + candidate_digest,
            "message_sha256": module.MESSAGE_SHA256,
            "local_cleanup_complete": True,
            "local_revocation_results": _revocations(),
        }
        runtime_closure = {
            "schema_version": "pq-sequoia-runtime-closure/v1",
            "candidate_identity": "sha256:" + candidate_digest,
            "workflow": {"workflow_sha": "c" * 40},
            "runner": {"image_version": "fixture-a"},
            "build_tools": {},
            "versions": {},
            "source_verification": {},
            "tap": {"commit": "d" * 40},
            "shared_cache_observation": {"listing_sha256": "e" * 64},
            "closures": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sq, sqv = _write_interop_tool_fixtures(root)
            phase_a_path = root / "phase-a.json"
            local_result_path = root / "local-result.json"
            runtime_closure_path = root / "runtime-closure.json"
            phase_b_path = root / "phase-b.json"
            state = root / "state"
            _write_json(phase_a_path, phase_a)
            _write_json(local_result_path, local_result)
            _write_json(runtime_closure_path, runtime_closure)

            opened = self.run_cli(
                "interop-open",
                "--root",
                str(ROOT),
                "--sq",
                str(sq),
                "--sqv",
                str(sqv),
                "--candidate-identity",
                "sha256:" + candidate_digest,
                "--producer-closure",
                str(runtime_closure_path),
                "--expected-peer-closure-sha256",
                peer_closure,
                "--session-id",
                session,
                "--peer-envelope",
                str(phase_a_path),
                "--local-result",
                str(local_result_path),
                "--state-dir",
                str(state),
                "--output",
                str(phase_b_path),
            )
            self.assertEqual(0, opened.returncode, opened.stderr)
            phase_b = json.loads(phase_b_path.read_text(encoding="utf-8"))
            self.assertEqual(
                _sha256(runtime_closure_path), phase_b["producer_closure_sha256"]
            )
            self.assertNotEqual(
                candidate_digest, phase_b["producer_closure_sha256"]
            )

            cleaned = self.run_cli("cleanup", "--state-dir", str(state))
            self.assertEqual(0, cleaned.returncode, cleaned.stderr)
            self.assertFalse(state.exists())

    def test_open_and_close_execute_authenticated_reconciled_exchange(self) -> None:
        module = _load_cli()
        session = "a" * 64
        peer_closure = "b" * 64
        candidate_digest = _sha256(CANDIDATE)
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
            "candidate_identity": "sha256:" + candidate_digest,
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
            runtime_closure_path = root / "runtime-closure.json"
            state = root / "state"
            phase_b_path = root / "phase-b.json"
            _write_json(phase_a_path, phase_a)
            _write_json(local_result_path, local_result)
            _write_json(
                runtime_closure_path,
                {
                    "schema_version": "pq-sequoia-runtime-closure/v1",
                    "candidate_identity": "sha256:" + candidate_digest,
                    "workflow": {},
                    "runner": {},
                    "build_tools": {},
                    "versions": {},
                    "source_verification": {},
                    "tap": {},
                    "shared_cache_observation": {},
                    "closures": {},
                },
            )
            local_closure = _sha256(runtime_closure_path)

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
                        candidate_identity="sha256:" + candidate_digest,
                        producer_closure=runtime_closure_path,
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
                self.assertEqual(local_closure, phase_b["producer_closure_sha256"])
                self.assertNotEqual(candidate_digest, phase_b["producer_closure_sha256"])
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
                    "runAttempt": 1,
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

    def test_subkey_retirement_pairs_same_artifact_before_and_after(self) -> None:
        module = _load_cli()
        harness = _RevocationSubprocessHarness()
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            _write_revocation_workspace(workspace)
            original_run = module.subprocess.run
            module.subprocess.run = harness
            try:
                results = module.exercise_revocations(
                    Path("/fixture/sq"),
                    Path("/fixture/sqv"),
                    workspace,
                    {"LC_ALL": "C", "SEQUOIA_HOME": str(workspace / "store")},
                )
            finally:
                module.subprocess.run = original_run

            self.assertEqual(set(module.REVOCATION_CASES), set(results))
            self.assertTrue(all(record["passed"] is True for record in results.values()))

            signer_calls = [
                command
                for command in harness.commands
                if "sign" in command and "--signer-file" in command
            ]
            self.assertEqual(2, len(signer_calls))
            self.assertEqual(
                {str(workspace / "signing-subkey-retired-key.pgp")},
                {
                    command[command.index("--signer-file") + 1]
                    for command in signer_calls
                },
            )
            verifier_calls = [
                command for command in harness.commands if command[0] == "/fixture/sqv"
            ]
            self.assertEqual(1, len(verifier_calls))
            self.assertEqual(
                str(workspace / "pre-retirement.sig"),
                verifier_calls[0][verifier_calls[0].index("--signature-file") + 1],
            )

            encryption_calls = [
                command
                for command in harness.commands
                if "encrypt" in command and "--for-file" in command
            ]
            self.assertEqual(2, len(encryption_calls))
            self.assertEqual(
                {str(workspace / "encryption-subkey-retired-key.pgp")},
                {
                    command[command.index("--for-file") + 1]
                    for command in encryption_calls
                },
            )
            self.assertEqual(
                MESSAGE.read_bytes(),
                (workspace / "pre-retirement-decrypted.bin").read_bytes(),
            )
            self.assertFalse((workspace / "post-retirement.sig").exists())
            self.assertFalse((workspace / "post-retirement.pgp").exists())

    def test_subkey_retirement_rejects_nondiscriminating_evidence(self) -> None:
        cases = (
            (
                "signing artifact fails before retirement",
                _RevocationSubprocessHarness(fail_before="sign"),
                "expected success",
            ),
            (
                "encryption artifact fails before retirement",
                _RevocationSubprocessHarness(fail_before="encrypt"),
                "expected success",
            ),
            (
                "baseline decryption changes bytes",
                _RevocationSubprocessHarness(decrypted=b"wrong plaintext"),
                "pre-retirement decryption mismatch",
            ),
            (
                "rejected signing leaves output",
                _RevocationSubprocessHarness(leak_after="sign"),
                "rejected operation produced output",
            ),
            (
                "rejected encryption leaves output",
                _RevocationSubprocessHarness(leak_after="encrypt"),
                "rejected operation produced output",
            ),
        )
        for label, harness, error in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as directory:
                module = _load_cli()
                workspace = Path(directory)
                _write_revocation_workspace(workspace)
                original_run = module.subprocess.run
                module.subprocess.run = harness
                try:
                    with self.assertRaisesRegex(module.ProcedureError, error):
                        module.exercise_revocations(
                            Path("/fixture/sq"),
                            Path("/fixture/sqv"),
                            workspace,
                            {
                                "LC_ALL": "C",
                                "SEQUOIA_HOME": str(workspace / "store"),
                            },
                        )
                finally:
                    module.subprocess.run = original_run

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

    def test_record_runtime_binds_tap_and_shared_cache_observations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tap = root / "tap"
            (tap / "Formula").mkdir(parents=True)
            subprocess.run(["git", "init", "--quiet", str(tap)], check=True)
            tap_record = root / "tap.json"
            prepared = self.run_cli(
                "prepare-tap",
                "--root",
                str(ROOT),
                "--tap-root",
                str(tap),
                "--output",
                str(tap_record),
            )
            self.assertEqual(0, prepared.returncode, prepared.stderr)

            bin_dir = root / "bin"
            bin_dir.mkdir()
            for name in ("sw_vers", "xcodebuild", "brew", "gpg", "rustc", "cargo", "capnp"):
                _write_any_output_tool(bin_dir / name, f"{name} fixture\n")
            sq = _write_any_output_tool(bin_dir / "sq", "sq fixture\n")
            sqv = _write_any_output_tool(bin_dir / "sqv", "sqv fixture\n")
            openssl = _write_any_output_tool(bin_dir / "openssl", "openssl fixture\n")
            otool = _write_otool_fixture(
                bin_dir / "otool", sq, "/usr/lib/libSystem.B.dylib"
            )
            cache_tool = _write_output_tool(
                bin_dir / "dyld_shared_cache_util",
                "/usr/lib/libSystem.B.dylib\n",
            )
            source_verification, active_formula = _source_verification_fixtures(root)
            output = root / "runtime.json"
            environment = os.environ.copy()
            environment["PATH"] = str(bin_dir) + os.pathsep + environment["PATH"]
            result = subprocess.run(
                [
                    str(CLI),
                    "record-runtime",
                    "--root",
                    str(ROOT),
                    "--tap-root",
                    str(tap),
                    "--otool",
                    str(otool),
                    "--dyld-shared-cache-util",
                    str(cache_tool),
                    "--sq",
                    str(sq),
                    "--sqv",
                    str(sqv),
                    "--openssl",
                    str(openssl),
                    "--source-verification",
                    str(source_verification),
                    "--active-formula-verification",
                    str(active_formula),
                    "--candidate-identity",
                    "sha256:" + _sha256(CANDIDATE),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            record = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("pq-sequoia-runtime-closure/v1", record["schema_version"])
            self.assertRegex(record["tap"]["commit"], r"^[0-9a-f]{40}$")
            self.assertEqual(
                _sha256(source_verification),
                record["source_verification"]["receipt_sha256"],
            )
            self.assertEqual(
                "87ec0fe343645ff3e4865da62205a7844c99f144",
                record["source_verification"]["active_formula_runtime"][
                    "homebrew_core_revision"
                ],
            )
            self.assertEqual(
                1, record["shared_cache_observation"]["listed_name_count"]
            )
            for closure in record["closures"].values():
                self.assertEqual(
                    ["/usr/lib/libSystem.B.dylib"], closure["apple_shared_cache"]
                )
            self.assertNotIn("shared_cache_or_unresolved", json.dumps(record))

    def test_validate_relay_command_writes_only_exact_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = {
                "databaseId": 321,
                "runAttempt": 1,
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

            metadata["headSha"] = "a" * 40
            metadata["runAttempt"] = 2
            _write_json(source, metadata)
            rejected_attempt = self.run_cli(
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
            self.assertEqual(1, rejected_attempt.returncode)
            self.assertIn("relay run attempt mismatch", rejected_attempt.stderr)
            self.assertFalse(output.exists())

    def test_relay_selection_finds_a_match_after_page_ten(self) -> None:
        title = (
            "pq-sequoia-publish-peer-response-"
            f"{'c' * 64}-987-{'d' * 64}"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pages = []
            for page_number in range(11):
                pages.append(
                    [
                        {
                            "databaseId": page_number * 100 + offset + 1,
                            "runAttempt": 1,
                            "displayTitle": "unrelated",
                            "event": "push",
                            "headSha": "b" * 40,
                            "status": "completed",
                            "conclusion": "success",
                        }
                        for offset in range(100)
                    ]
                )
            pages[-1][-1] = {
                "databaseId": 1100,
                "runAttempt": 1,
                "displayTitle": title,
                "event": "workflow_dispatch",
                "headSha": "a" * 40,
                "status": "completed",
                "conclusion": "success",
            }
            gh, invocation = self.fake_gh(root, pages)

            result = self.run_cli(*self.relay_arguments(root, gh))

            self.assertEqual(0, result.returncode, result.stderr)
            record = json.loads((root / "selection.json").read_text())
            self.assertTrue(record["selection_ready"])
            self.assertEqual([1100], [run["databaseId"] for run in record["matching_runs"]])
            self.assertEqual(
                {
                    "endpoint": "/repos/example/project/actions/workflows/pq-sequoia-macos.yml/runs",
                    "method": "GET",
                    "named_search_filters": [],
                    "page_count": 11,
                    "pagination_complete": True,
                    "per_page": 100,
                    "raw_record_count": 1100,
                    "repeated_record_count": 0,
                    "unique_run_count": 1100,
                },
                record["coverage"],
            )
            self.assertEqual(
                [
                    "api",
                    "--method",
                    "GET",
                    "--paginate",
                    "--raw-field",
                    "per_page=100",
                    "--jq",
                    ".workflow_runs | map({databaseId: .id, runAttempt: .run_attempt, displayTitle: .display_title, event: .event, headSha: .head_sha, status: .status, conclusion: .conclusion})",
                    "/repos/example/project/actions/workflows/pq-sequoia-macos.yml/runs",
                ],
                json.loads(invocation.read_text()),
            )

    def test_relay_checks_retain_every_observed_matching_duplicate_before_rejecting(
        self,
    ) -> None:
        title = f"pq-sequoia-publish-peer-response-{'c' * 64}-987-{'d' * 64}"
        selected = {
            "databaseId": 321,
            "runAttempt": 1,
            "displayTitle": title,
            "event": "workflow_dispatch",
            "headSha": "a" * 40,
            "status": "completed",
            "conclusion": "success",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for stage in ("selection", "final"):
                for status, conclusion in (
                    ("queued", None),
                    ("completed", "failure"),
                ):
                    with self.subTest(stage=stage, status=status):
                        duplicate = {
                            **selected,
                            "databaseId": 654,
                            "status": status,
                            "conclusion": conclusion,
                        }
                        gh, _ = self.fake_gh(root, [[selected], [duplicate]])
                        rejected = self.run_cli(
                            *self.relay_arguments(
                                root,
                                gh,
                                stage=stage,
                                selected_run_id=(
                                    "321" if stage == "final" else None
                                ),
                            )
                        )

                        self.assertEqual(1, rejected.returncode)
                        self.assertIn(
                            "matching relay duplicate observed", rejected.stderr
                        )
                        record = json.loads(
                            (root / f"{stage}.json").read_text(encoding="utf-8")
                        )
                        self.assertEqual(stage, record["stage"])
                        self.assertEqual(
                            {
                                "outcome": "rejected",
                                "reason": "matching relay duplicate observed",
                            },
                            record["decision"],
                        )
                        self.assertFalse(record["selection_ready"])
                        self.assertIsNone(
                            record["exchange_binding"]["selected_run_id"]
                        )
                        self.assertEqual(
                            [selected, duplicate], record["matching_runs"]
                        )
                        self.assertEqual(
                            {
                                "endpoint": "/repos/example/project/actions/workflows/pq-sequoia-macos.yml/runs",
                                "method": "GET",
                                "named_search_filters": [],
                                "page_count": 2,
                                "pagination_complete": True,
                                "per_page": 100,
                                "raw_record_count": 2,
                                "repeated_record_count": 0,
                                "unique_run_count": 2,
                            },
                            record["coverage"],
                        )

    def test_relay_checks_reject_and_retain_an_observed_response_rerun(
        self,
    ) -> None:
        title = f"pq-sequoia-publish-peer-response-{'c' * 64}-987-{'d' * 64}"
        rerun = {
            "databaseId": 321,
            "runAttempt": 2,
            "displayTitle": title,
            "event": "workflow_dispatch",
            "headSha": "a" * 40,
            "status": "completed",
            "conclusion": "success",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for stage in ("selection", "final"):
                with self.subTest(stage=stage):
                    gh, _ = self.fake_gh(root, [[rerun]])
                    rejected = self.run_cli(
                        *self.relay_arguments(
                            root,
                            gh,
                            stage=stage,
                            selected_run_id="321" if stage == "final" else None,
                        )
                    )

                    self.assertEqual(1, rejected.returncode)
                    self.assertIn("matching relay rerun observed", rejected.stderr)
                    record = json.loads(
                        (root / f"{stage}.json").read_text(encoding="utf-8")
                    )
                    self.assertEqual(stage, record["stage"])
                    self.assertEqual(
                        {
                            "outcome": "rejected",
                            "reason": "matching relay rerun observed",
                        },
                        record["decision"],
                    )
                    self.assertFalse(record["selection_ready"])
                    self.assertIsNone(record["exchange_binding"]["selected_run_id"])
                    self.assertEqual([rerun], record["matching_runs"])

    def test_relay_observation_normalizes_identical_overlap(self) -> None:
        title = f"pq-sequoia-publish-peer-response-{'c' * 64}-987-{'d' * 64}"
        selected = {
            "databaseId": 321,
            "runAttempt": 1,
            "displayTitle": title,
            "event": "workflow_dispatch",
            "headSha": "a" * 40,
            "status": "completed",
            "conclusion": "success",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gh, _ = self.fake_gh(root, [[selected], [selected]])

            result = self.run_cli(*self.relay_arguments(root, gh))

            self.assertEqual(0, result.returncode, result.stderr)
            record = json.loads((root / "selection.json").read_text())
            self.assertEqual([selected], record["matching_runs"])
            self.assertEqual(2, record["coverage"]["raw_record_count"])
            self.assertEqual(1, record["coverage"]["unique_run_count"])
            self.assertEqual(1, record["coverage"]["repeated_record_count"])

    def test_relay_observation_rejects_conflicting_run_identity(self) -> None:
        title = f"pq-sequoia-publish-peer-response-{'c' * 64}-987-{'d' * 64}"
        queued = {
            "databaseId": 321,
            "runAttempt": 1,
            "displayTitle": title,
            "event": "workflow_dispatch",
            "headSha": "a" * 40,
            "status": "queued",
            "conclusion": None,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gh, _ = self.fake_gh(
                root,
                [[queued], [{**queued, "status": "completed", "conclusion": "success"}]],
            )

            result = self.run_cli(*self.relay_arguments(root, gh))

            self.assertEqual(1, result.returncode)
            self.assertIn("conflicting relay observations", result.stderr)
            self.assertFalse((root / "selection.json").exists())

    def test_relay_observation_rejects_wrong_event_or_commit(self) -> None:
        title = f"pq-sequoia-publish-peer-response-{'c' * 64}-987-{'d' * 64}"
        selected = {
            "databaseId": 321,
            "runAttempt": 1,
            "displayTitle": title,
            "event": "workflow_dispatch",
            "headSha": "a" * 40,
            "status": "completed",
            "conclusion": "success",
        }
        for name, changed in (
            ("event", {**selected, "event": "push"}),
            ("commit", {**selected, "headSha": "b" * 40}),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                gh, _ = self.fake_gh(root, [[changed]])

                result = self.run_cli(*self.relay_arguments(root, gh))

                self.assertEqual(1, result.returncode)
                self.assertIn("matching relay binding mismatch", result.stderr)
                self.assertFalse((root / "selection.json").exists())

    def test_relay_observation_rejects_malformed_page_and_run(self) -> None:
        malformed_cases = (
            ("page", {"workflow_runs": []}, "page must be an array"),
            ("run", [{"databaseId": 1}], "fields mismatch"),
        )
        for name, page, message in malformed_cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                gh, _ = self.fake_gh(root, [page])

                result = self.run_cli(*self.relay_arguments(root, gh))

                self.assertEqual(1, result.returncode)
                self.assertIn(message, result.stderr)
                self.assertFalse((root / "selection.json").exists())

    def test_relay_empty_traversal_is_not_ready_and_cannot_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gh, _ = self.fake_gh(root, [[]])

            selection = self.run_cli(*self.relay_arguments(root, gh))

            self.assertEqual(0, selection.returncode, selection.stderr)
            record = json.loads((root / "selection.json").read_text())
            self.assertFalse(record["selection_ready"])
            self.assertEqual([], record["matching_runs"])

            gh, _ = self.fake_gh(root, [[]])
            final = self.run_cli(
                *self.relay_arguments(
                    root, gh, stage="final", selected_run_id="321"
                )
            )

            self.assertEqual(1, final.returncode)
            self.assertIn("selected relay run absent", final.stderr)
            self.assertFalse((root / "final.json").exists())

    def test_relay_provider_failure_and_timeout_leave_no_observation(self) -> None:
        title = f"pq-sequoia-publish-peer-response-{'c' * 64}-987-{'d' * 64}"
        selected = {
            "databaseId": 321,
            "runAttempt": 1,
            "displayTitle": title,
            "event": "workflow_dispatch",
            "headSha": "a" * 40,
            "status": "completed",
            "conclusion": "success",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gh, _ = self.fake_gh(root, [[selected]], exit_code=1)
            failed = self.run_cli(*self.relay_arguments(root, gh))
            self.assertEqual(1, failed.returncode)
            self.assertIn("provider traversal failed", failed.stderr)
            self.assertFalse((root / "selection.json").exists())

            gh, _ = self.fake_gh(root, [[]], pause_seconds=0.5)
            timed_out = self.run_cli(
                *self.relay_arguments(root, gh, timeout="0.05")
            )
            self.assertEqual(1, timed_out.returncode)
            self.assertIn("provider traversal timed out", timed_out.stderr)
            self.assertFalse((root / "selection.json").exists())

    def test_relay_unsuccessful_match_is_retained_but_not_ready(self) -> None:
        title = f"pq-sequoia-publish-peer-response-{'c' * 64}-987-{'d' * 64}"
        unsuccessful = {
            "databaseId": 321,
            "runAttempt": 1,
            "displayTitle": title,
            "event": "workflow_dispatch",
            "headSha": "a" * 40,
            "status": "completed",
            "conclusion": "failure",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gh, _ = self.fake_gh(root, [[unsuccessful]])

            result = self.run_cli(*self.relay_arguments(root, gh))

            self.assertEqual(0, result.returncode, result.stderr)
            record = json.loads((root / "selection.json").read_text())
            self.assertFalse(record["selection_ready"])
            self.assertEqual([unsuccessful], record["matching_runs"])

    def test_relay_final_observation_requires_selected_id_continuity(self) -> None:
        title = f"pq-sequoia-publish-peer-response-{'c' * 64}-987-{'d' * 64}"
        selected = {
            "databaseId": 321,
            "runAttempt": 1,
            "displayTitle": title,
            "event": "workflow_dispatch",
            "headSha": "a" * 40,
            "status": "completed",
            "conclusion": "success",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gh, _ = self.fake_gh(root, [[selected]])
            final = self.run_cli(
                *self.relay_arguments(
                    root, gh, stage="final", selected_run_id="321"
                )
            )
            self.assertEqual(0, final.returncode, final.stderr)
            record = json.loads((root / "final.json").read_text())
            self.assertEqual("final", record["stage"])
            self.assertEqual("321", record["exchange_binding"]["selected_run_id"])

            (root / "final.json").unlink()
            gh, _ = self.fake_gh(root, [[selected]])
            changed = self.run_cli(
                *self.relay_arguments(
                    root, gh, stage="final", selected_run_id="654"
                )
            )
            self.assertEqual(1, changed.returncode)
            self.assertIn("selected relay run changed", changed.stderr)
            self.assertFalse((root / "final.json").exists())

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
                    module.ProcedureError, "unresolved Mach-O dependency"
                ):
                    module.record_macho_closure(
                        executable,
                        Path("otool"),
                        {"/usr/lib/libSystem.B.dylib"},
                    )
            finally:
                module.tool_output = original

    def test_apple_shared_cache_requires_exact_live_membership(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "candidate-bin"
            executable.write_bytes(b"fake Mach-O fixture")
            otool = _write_otool_fixture(
                root / "otool",
                executable,
                "/usr/lib/lib-not-in-any-shared-cache.dylib",
            )
            cache_tool = _write_output_tool(
                root / "dyld_shared_cache_util",
                "/usr/lib/libSystem.B.dylib\n",
            )
            output = root / "macho-closure.json"
            rejected = self.run_cli(
                "record-macho-closure",
                "--executable",
                str(executable),
                "--otool",
                str(otool),
                "--dyld-shared-cache-util",
                str(cache_tool),
                "--output",
                str(output),
            )
            self.assertEqual(1, rejected.returncode)
            self.assertIn("unresolved Mach-O dependency", rejected.stderr)
            self.assertFalse(output.exists())

            _write_otool_fixture(
                otool,
                executable,
                "/usr/lib/libSystem.B.dylib",
            )
            accepted = self.run_cli(
                "record-macho-closure",
                "--executable",
                str(executable),
                "--otool",
                str(otool),
                "--dyld-shared-cache-util",
                str(cache_tool),
                "--output",
                str(output),
            )
            self.assertEqual(0, accepted.returncode, accepted.stderr)
            record = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                ["/usr/lib/libSystem.B.dylib"],
                record["closure"]["apple_shared_cache"],
            )
            self.assertEqual(
                hashlib.sha256(b"/usr/lib/libSystem.B.dylib\n").hexdigest(),
                record["shared_cache_observation"]["listing_sha256"],
            )
            self.assertEqual(1, record["shared_cache_observation"]["listed_name_count"])

    def test_ephemeral_tap_requires_an_exact_committed_formula_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tap = root / "tap"
            formula_dir = tap / "Formula"
            formula_dir.mkdir(parents=True)
            subprocess.run(["git", "init", "--quiet", str(tap)], check=True)
            formula_sources = sorted((PACKAGE_ROOT / "Formula").glob("*.rb"))
            for source in formula_sources:
                shutil.copyfile(source, formula_dir / source.name)

            output = root / "tap-closure.json"
            uncommitted = self.run_cli(
                "record-tap",
                "--root",
                str(ROOT),
                "--tap-root",
                str(tap),
                "--output",
                str(output),
            )
            self.assertEqual(1, uncommitted.returncode)
            self.assertIn("tap worktree must be clean", uncommitted.stderr)
            self.assertFalse(output.exists())

            for formula in formula_dir.iterdir():
                formula.unlink()
            prepared = self.run_cli(
                "prepare-tap",
                "--root",
                str(ROOT),
                "--tap-root",
                str(tap),
                "--output",
                str(output),
            )
            self.assertEqual(0, prepared.returncode, prepared.stderr)
            record = json.loads(output.read_text(encoding="utf-8"))
            commit = record["commit"]
            self.assertRegex(commit, r"^[0-9a-f]{40}$")
            self.assertEqual(
                {source.name for source in formula_sources}, set(record["formulae"])
            )
            for source in formula_sources:
                self.assertEqual(
                    _sha256(source), record["formulae"][source.name]["sha256"]
                )
                committed = subprocess.run(
                    ["git", "-C", str(tap), "show", f"{commit}:Formula/{source.name}"],
                    check=True,
                    capture_output=True,
                ).stdout
                self.assertEqual(source.read_bytes(), committed)

            changed_formula = formula_dir / formula_sources[0].name
            changed_formula.write_bytes(b"different formula\n")
            closed_git_environment = os.environ.copy()
            closed_git_environment["GIT_CONFIG_NOSYSTEM"] = "1"
            closed_git_environment["GIT_CONFIG_GLOBAL"] = os.devnull
            subprocess.run(
                ["git", "-C", str(tap), "add", "--", f"Formula/{changed_formula.name}"],
                check=True,
                env=closed_git_environment,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(tap),
                    "-c",
                    "user.name=PQ qualification test",
                    "-c",
                    "user.email=pq-test.invalid@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "commit",
                    "--quiet",
                    "--no-gpg-sign",
                    "--message",
                    "Commit different formula bytes",
                ],
                check=True,
                env=closed_git_environment,
            )
            output.unlink()
            wrong_commit = self.run_cli(
                "record-tap",
                "--root",
                str(ROOT),
                "--tap-root",
                str(tap),
                "--output",
                str(output),
            )
            self.assertEqual(1, wrong_commit.returncode)
            self.assertIn("tap formula identity mismatch", wrong_commit.stderr)
            self.assertFalse(output.exists())


def _payload(content: bytes) -> dict[str, object]:
    return {
        "encoding": "base64",
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "data": base64.b64encode(content).decode("ascii"),
    }


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _validsig_status(*, signing: str, primary: str) -> str:
    return (
        f"[GNUPG:] VALIDSIG {signing} 2026-09-29 1790697600 0 "
        f"4 0 22 8 00 {primary}\n"
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _closed_git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    return environment


def _source_verification_fixtures(root: Path) -> tuple[Path, Path]:
    openssl_formula = "openssl@3.5.rb"
    formula_relative_path = f"Formula/o/{openssl_formula}"
    formula = {
        "schema_version": "pq-sequoia-homebrew-formula-verification/v1",
        "formula": "openssl@3.5",
        "formula_path": str(root / "core" / formula_relative_path),
        "formula_relative_path": formula_relative_path,
        "formula_sha256": "3265208aa3bf71299a48b3a2c7d3b734f88b2b65831488ae9e514dbc93c6db05",
        "homebrew_core_revision": "87ec0fe343645ff3e4865da62205a7844c99f144",
    }
    source = {
        "schema_version": "pq-sequoia-source-verification/v1",
        "candidate_sha256": _sha256(CANDIDATE),
        "verified": {"openssl": {"active_formula": formula}},
    }
    source_path = root / "source-verification.json"
    formula_path = root / "active-formula-verification.json"
    _write_json(source_path, source)
    _write_json(formula_path, formula)
    return source_path, formula_path


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


def _write_revocation_workspace(workspace: Path) -> None:
    (workspace / "key.pgp").write_bytes(b"private fixture key")
    (workspace / "cert.pgp").write_bytes(b"public fixture certificate")
    (workspace / "message.bin").write_bytes(MESSAGE.read_bytes())
    (workspace / "message.sig").write_bytes(b"baseline fixture signature")
    (workspace / "message.pgp").write_bytes(b"baseline fixture ciphertext")
    (workspace / "emergency-revocation.pgp").write_bytes(
        b"emergency fixture revocation"
    )


class _RevocationSubprocessHarness:
    def __init__(
        self,
        *,
        fail_before: str | None = None,
        decrypted: bytes | None = None,
        leak_after: str | None = None,
    ) -> None:
        self.fail_before = fail_before
        self.decrypted = MESSAGE.read_bytes() if decrypted is None else decrypted
        self.leak_after = leak_after
        self.commands: list[list[str]] = []
        self.revoked_stores: set[str] = set()

    def __call__(
        self,
        command,
        *,
        check,
        capture_output,
        env,
        timeout,
    ) -> subprocess.CompletedProcess[bytes]:
        arguments = [str(value) for value in command]
        self.commands.append(arguments)
        returncode = 0
        stdout = b""

        if len(arguments) > 1 and arguments[1] == "inspect":
            stdout = (
                b"OpenPGP Certificate.\n"
                b"  Fingerprint : AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n"
                b"  Subkey : BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB\n"
                b"  Key flags : signing\n"
                b"  Subkey : CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC\n"
                b"  Key flags : transport encryption\n"
            )
        elif "revoke" in arguments and "--output" in arguments:
            output = Path(arguments[arguments.index("--output") + 1])
            output.write_bytes(f"fixture revocation for {output.name}".encode())
        elif "keyring" in arguments and "merge" in arguments:
            output = Path(arguments[arguments.index("--output") + 1])
            output.write_bytes(b"merged private fixture artifact")
        elif "sign" in arguments and "--signer-file" in arguments:
            output = Path(arguments[arguments.index("--signature-file") + 1])
            if output.name == "pre-retirement.sig":
                if self.fail_before == "sign":
                    returncode = 1
                else:
                    output.write_bytes(b"pre-retirement fixture signature")
            elif output.name == "post-retirement.sig":
                returncode = 1
                if self.leak_after == "sign":
                    output.write_bytes(b"")
        elif arguments[0] == "/fixture/sqv":
            signature = Path(arguments[arguments.index("--signature-file") + 1])
            returncode = 0 if signature.exists() else 1
        elif "encrypt" in arguments and "--for-file" in arguments:
            output = Path(arguments[arguments.index("--output") + 1])
            if output.name == "pre-retirement.pgp":
                if self.fail_before == "encrypt":
                    returncode = 1
                else:
                    output.write_bytes(b"pre-retirement fixture ciphertext")
            elif output.name == "post-retirement.pgp":
                returncode = 1
                if self.leak_after == "encrypt":
                    output.write_bytes(b"")
        elif "decrypt" in arguments and "--output" in arguments:
            output = Path(arguments[arguments.index("--output") + 1])
            output.write_bytes(self.decrypted)
        elif "cert" in arguments and "import" in arguments:
            imported = Path(arguments[-1])
            if "revocation" in imported.name or imported.name == "retired-certificate.pgp":
                self.revoked_stores.add(env["SEQUOIA_HOME"])
        elif (
            "cert" in arguments
            and "list" in arguments
            and "--gossip" not in arguments
            and env["SEQUOIA_HOME"] in self.revoked_stores
        ):
            returncode = 1

        return subprocess.CompletedProcess(command, returncode, stdout, b"")


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


def _write_sq_inspection_fixture(
    path: Path, version: int, *, omit_encryption_fingerprint: bool = False
) -> Path:
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
    encryption_fingerprint = (
        "" if omit_encryption_fingerprint else f"  Fingerprint: {encryption}\n"
    )
    packet_dump = f"""Public-Key Packet, new CTB
  Version: {version}
  Pk algo: ML-DSA-65+Ed25519
  Fingerprint: {primary}
Signature Packet, new CTB
  Version: {version}
  Type: DirectKey
  Pk algo: ML-DSA-65+Ed25519
  Issuer Fingerprint: {primary}
User ID Packet, new CTB
  Value: PQ qualification fixture
Signature Packet, new CTB
  Version: {version}
  Type: PositiveCertification
  Pk algo: ML-DSA-65+Ed25519
  Issuer Fingerprint: {primary}
Public-Subkey Packet, new CTB
  Version: {version}
  Pk algo: ML-DSA-65+Ed25519
  Fingerprint: {signing}
Signature Packet, new CTB
  Version: {version}
  Type: SubkeyBinding
  Pk algo: ML-DSA-65+Ed25519
  Issuer Fingerprint: {primary}
Public-Subkey Packet, new CTB
  Version: {version}
  Pk algo: ML-KEM-768+X25519
{encryption_fingerprint}Signature Packet, new CTB
  Version: {version}
  Type: SubkeyBinding
  Pk algo: ML-DSA-65+Ed25519
  Issuer Fingerprint: {primary}
"""
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"inspection = {inspection!r}\n"
        f"packet_dump = {packet_dump!r}\n"
        "if sys.argv[1] == 'inspect':\n"
        "    print(inspection, end='')\n"
        "elif sys.argv[1:3] == ['packet', 'dump']:\n"
        "    print(packet_dump, end='')\n"
        "else:\n"
        "    raise SystemExit(2)\n",
        encoding="utf-8",
    )
    path.chmod(0o700)
    return path


def _write_output_tool(path: Path, output: str) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "if sys.argv[1:] != ['-list']:\n"
        "    raise SystemExit(2)\n"
        f"print({output!r}, end='')\n",
        encoding="utf-8",
    )
    path.chmod(0o700)
    return path


def _write_any_output_tool(path: Path, output: str) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        f"print({output!r}, end='')\n",
        encoding="utf-8",
    )
    path.chmod(0o700)
    return path


def _write_interop_tool_fixtures(root: Path) -> tuple[Path, Path]:
    sq = root / "sq"
    sqv = root / "sqv"
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
    packet_dump = f"""Public-Key Packet, new CTB
  Version: 6
  Pk algo: ML-DSA-65+Ed25519
  Fingerprint: {primary}
Public-Subkey Packet, new CTB
  Version: 6
  Pk algo: ML-DSA-65+Ed25519
  Fingerprint: {signing}
Public-Subkey Packet, new CTB
  Version: 6
  Pk algo: ML-KEM-768+X25519
  Fingerprint: {encryption}
"""
    signature_dump = f"""Signature Packet
  Version: 6
  Pk algo: ML-DSA-65+Ed25519
  Issuer Fingerprint: {signing}
"""
    message = base64.b64encode(MESSAGE.read_bytes()).decode("ascii")
    sq.write_text(
        "#!/usr/bin/env python3\n"
        "import base64\n"
        "import pathlib\n"
        "import sys\n"
        f"inspection = {inspection!r}\n"
        f"packet_dump = {packet_dump!r}\n"
        f"signature_dump = {signature_dump!r}\n"
        f"message = base64.b64decode({message!r})\n"
        "args = sys.argv[1:]\n"
        "if args[0] == 'inspect':\n"
        "    print(inspection, end='')\n"
        "elif args[:2] == ['packet', 'dump']:\n"
        "    print(signature_dump if args[-1].endswith('.sig') else packet_dump, end='')\n"
        "elif args[:2] == ['key', 'generate']:\n"
        "    pathlib.Path(args[args.index('--output') + 1]).write_bytes(b'public test key placeholder')\n"
        "    pathlib.Path(args[args.index('--rev-cert') + 1]).write_bytes(b'public test revocation placeholder')\n"
        "elif args[:2] == ['key', 'delete']:\n"
        "    pathlib.Path(args[args.index('--output') + 1]).write_bytes(b'public test certificate placeholder')\n"
        "elif args[0] == 'sign':\n"
        "    pathlib.Path(args[args.index('--signature-file') + 1]).write_bytes(b'public test signature placeholder')\n"
        "elif args[0] == 'encrypt':\n"
        "    pathlib.Path(args[args.index('--output') + 1]).write_bytes(b'public test ciphertext placeholder')\n"
        "elif args[0] == 'decrypt':\n"
        "    if 'tampered' in args[-1]:\n"
        "        raise SystemExit(1)\n"
        "    pathlib.Path(args[args.index('--output') + 1]).write_bytes(message)\n"
        "else:\n"
        "    raise SystemExit(2)\n",
        encoding="utf-8",
    )
    sqv.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "raise SystemExit(1 if 'altered-message.bin' in sys.argv[-1] else 0)\n",
        encoding="utf-8",
    )
    sq.chmod(0o700)
    sqv.chmod(0o700)
    return sq, sqv


def _write_otool_fixture(path: Path, executable: Path, dependency: str) -> Path:
    listing = (
        f"{executable}:\n"
        f"\t{dependency} (compatibility version 1.0.0, current version 1.0.0)\n"
    )
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"listing = {listing!r}\n"
        "if sys.argv[1] == '-l':\n"
        "    pass\n"
        "elif sys.argv[1] == '-L':\n"
        "    print(listing, end='')\n"
        "else:\n"
        "    raise SystemExit(2)\n",
        encoding="utf-8",
    )
    path.chmod(0o700)
    return path


if __name__ == "__main__":
    unittest.main()
