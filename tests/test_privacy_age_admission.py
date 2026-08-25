from __future__ import annotations

import hashlib
import json
import os
import runpy
import shlex
import shutil
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from scripts import privacy_age_envelopes
from scripts.privacy_age_admission import (
    ADMISSION_CLOCK_SKEW,
    ADMISSION_MAX_LIFETIME,
    ADMISSION_NAMESPACE,
    ADMISSION_PRINCIPAL,
    ADMISSION_VERSION,
    _validate_executable_path_authority,
    canonical_payload_bytes,
    encode_receipt,
    extract_receipt,
    validate_payload,
    verify_receipt_signature,
)
from scripts.privacy_age_integrity_gate import verify_integrity_boundary
from tests.age_tooling_test_support import (
    require_age_tooling_or_skip,
    shared_age_tooling_directory_or_skip,
)

ROOT = Path(__file__).resolve().parents[1]
ADMITTER = ROOT / "scripts/admit-age-envelopes"
TRUSTED_LAUNCHER = ROOT / "scripts/run-trusted-age-admission"
RECEIPT_CREATOR = ROOT / "scripts/create-age-admission-receipt"


def _run(*command: str, cwd: Path, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        env=environment,
        timeout=20,
        **kwargs,
    )


def _commit(root: Path, message: str) -> str:
    _run("git", "add", "--all", cwd=root)
    _run(
        "git",
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "-c",
        f"core.hooksPath={os.devnull}",
        "commit",
        "-m",
        message,
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return _run("git", "rev-parse", "HEAD", cwd=root, capture_output=True).stdout.decode().strip()


class PrivacyAgeAdmissionCreatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.creator = runpy.run_path(os.fspath(RECEIPT_CREATOR))

    def test_staged_signer_probe_reports_the_failure_domain(self) -> None:
        error_type = self.creator["ReceiptRequestError"]
        scenarios = (
            (
                PermissionError("staging filesystem is mounted noexec"),
                "staged admission signature tool is not executable from its staging directory",
            ),
            (
                subprocess.TimeoutExpired(["/staged/ssh-keygen", "-V"], 1),
                "staged admission signature tool execution probe timed out",
            ),
            (
                OSError("invalid executable format"),
                "staged admission signature tool could not be executed",
            ),
        )
        for cause, message in scenarios:
            with self.subTest(cause=type(cause).__name__):
                with (
                    mock.patch.object(
                        self.creator["subprocess"],
                        "run",
                        side_effect=cause,
                    ),
                    self.assertRaises(error_type) as caught,
                ):
                    self.creator["_probe_staged_signing_tool"](
                        Path("/staged/ssh-keygen")
                    )

                self.assertEqual(str(caught.exception), message)

    def test_signer_validation_accepts_an_authorized_symlink(self) -> None:
        raw_tool = shutil.which("ssh-keygen")
        self.assertIsNotNone(raw_tool)
        canonical_tool = Path(raw_tool).resolve(strict=True)
        with TemporaryDirectory(dir=ROOT.parent) as temporary:
            symlink = Path(temporary) / "ssh-keygen"
            symlink.symlink_to(canonical_tool)

            self.assertEqual(
                _validate_executable_path_authority(os.fspath(symlink)),
                canonical_tool,
            )
            with (
                mock.patch.object(self.creator["sys"], "platform", "linux"),
                mock.patch.object(
                    self.creator["shutil"],
                    "which",
                    return_value=os.fspath(symlink),
                ),
            ):
                validated_tool, tool_data = self.creator["_validated_signing_tool"](
                    forbidden_roots=(ROOT,),
                    envelope_module=privacy_age_envelopes,
                )

        self.assertEqual(validated_tool, canonical_tool)
        self.assertTrue(tool_data)

    def test_verifier_rejects_a_symlink_to_a_writable_target_parent(self) -> None:
        raw_tool = shutil.which("ssh-keygen")
        self.assertIsNotNone(raw_tool)
        with TemporaryDirectory(dir=ROOT.parent) as temporary:
            root = Path(temporary)
            writable_target_parent = root / "writable-tools"
            writable_target_parent.mkdir(mode=0o775)
            writable_target_parent.chmod(0o775)
            target = writable_target_parent / "ssh-keygen"
            shutil.copyfile(raw_tool, target)
            target.chmod(0o755)
            symlink = root / "ssh-keygen"
            symlink.symlink_to(target)

            with self.assertRaisesRegex(
                ValueError,
                "admission signature tooling is unavailable",
            ):
                _validate_executable_path_authority(os.fspath(symlink))


class PrivacyAgeAdmissionReceiptTests(unittest.TestCase):
    def test_receipt_round_trips_only_canonical_signed_bytes(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        payload = {
            "base_commit": "0" * 40,
            "expires_at": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "head_commit": "1" * 40,
            "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "nonce": "a" * 32,
            "paths": [],
            "repository": "nisavid/dotfiles",
            "version": ADMISSION_VERSION,
        }
        signature = b"fixture-signature"

        receipt = encode_receipt(payload, signature)
        parsed = extract_receipt(receipt)

        self.assertIsNotNone(parsed)
        parsed_payload, parsed_bytes, parsed_signature = parsed
        self.assertEqual(parsed_payload, payload)
        self.assertEqual(parsed_signature, signature)
        self.assertEqual(parsed_bytes, canonical_payload_bytes(payload))

    def test_receipt_requires_one_unambiguous_body_marker(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        payload = {
            "base_commit": "0" * 40,
            "expires_at": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "head_commit": "1" * 40,
            "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "nonce": "a" * 32,
            "paths": [],
            "repository": "nisavid/dotfiles",
            "version": ADMISSION_VERSION,
        }
        marker = encode_receipt(payload, b"fixture-signature")

        self.assertIsNone(extract_receipt(b"ordinary body"))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            extract_receipt(marker + b"\n" + marker)

    def test_payload_rejects_invalid_time_window(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        payload = {
            "base_commit": "0" * 40,
            "expires_at": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "head_commit": "1" * 40,
            "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "nonce": "a" * 32,
            "paths": [],
            "repository": "nisavid/dotfiles",
            "version": ADMISSION_VERSION,
        }

        expired = payload | {
            "issued_at": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": (now - ADMISSION_CLOCK_SKEW - timedelta(seconds=1)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }
        with self.assertRaisesRegex(ValueError, "expired"):
            validate_payload(expired, now=now)

        future = payload | {
            "issued_at": (now + ADMISSION_CLOCK_SKEW + timedelta(seconds=1)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "expires_at": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        with self.assertRaisesRegex(ValueError, "future"):
            validate_payload(future, now=now)

        overlong = payload | {
            "expires_at": (now + ADMISSION_MAX_LIFETIME + timedelta(seconds=1)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }
        with self.assertRaisesRegex(ValueError, "lifetime"):
            validate_payload(overlong, now=now)

    def test_payload_accepts_printable_ascii_path_punctuation(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        payload = {
            "base_commit": "0" * 40,
            "expires_at": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "head_commit": "1" * 40,
            "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "nonce": "a" * 32,
            "paths": [
                {
                    "base": None,
                    "head": None,
                    "path": "docs/Release notes+@~=,v1.md",
                }
            ],
            "repository": "nisavid/dotfiles",
            "version": ADMISSION_VERSION,
        }

        self.assertEqual(validate_payload(payload, now=now), payload)
        with self.assertRaisesRegex(ValueError, "canonical"):
            validate_payload(
                payload | {"paths": [payload["paths"][0] | {"path": "docs/bad\tname"}]},
                now=now,
            )

    def test_trusted_wrapper_rejects_every_untrusted_launch_path(self) -> None:
        # /tmp has the sticky-ancestor permissions this wrapper must accept;
        # macOS's per-user TMPDIR would not exercise those scenarios.
        with TemporaryDirectory(dir="/tmp") as temporary:
            root = Path(temporary)
            base = root / "base"
            head = root / "head"
            base.mkdir()
            _run("git", "init", "--quiet", cwd=base)
            launcher = base / "scripts/create-age-admission-receipt"
            launcher.parent.mkdir(parents=True)
            launcher.write_text(
                "#!/usr/bin/env python3\n"
                "import os\n"
                "from pathlib import Path\n"
                "Path(os.environ['ADMISSION_LAUNCHER_MARKER']).write_text('ran')\n"
                "raise SystemExit(0)\n",
                encoding="ascii",
            )
            launcher.chmod(0o755)
            base_commit = _commit(base, "trusted launcher")
            _run("git", "clone", "--quiet", "--no-local", str(base), str(head), cwd=root)
            wrapper = root / "trusted-wrapper"
            shutil.copy2(TRUSTED_LAUNCHER, wrapper)
            wrapper.chmod(0o755)
            marker = root / "launcher-ran"
            environment = os.environ.copy()
            environment["ADMISSION_LAUNCHER_MARKER"] = str(marker)
            creator_arguments = [
                "--base-repository",
                str(base),
                "--base-commit",
                base_commit,
                "--head-repository",
                str(head),
                "--head-commit",
                base_commit,
            ]

            def wrapper_command(candidate: Path) -> list[str]:
                return [
                    sys.executable,
                    "-I",
                    str(candidate),
                    "--base-repository",
                    str(base),
                    "--base-commit",
                    base_commit,
                    "--",
                    *creator_arguments,
                ]

            def launch(command: list[str]) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                    timeout=30,
                )

            command = wrapper_command(wrapper)
            result = launch(command)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(marker.exists())

            marker.unlink()
            writable_wrapper_dir = root / "writable-wrapper-dir"
            writable_wrapper_dir.mkdir()
            writable_wrapper_dir.chmod(0o775)
            writable_wrapper = writable_wrapper_dir / "trusted-wrapper"
            shutil.copy2(wrapper, writable_wrapper)
            writable_wrapper.chmod(0o755)
            result = launch(wrapper_command(writable_wrapper))
            self.assertEqual(result.returncode, 1, "writable wrapper directory")
            self.assertFalse(marker.exists())

            if os.getuid() != 0:
                sticky_wrapper_dir = root / "user-owned-sticky-wrapper-dir"
                sticky_wrapper_dir.mkdir()
                sticky_wrapper_dir.chmod(0o1777)
                sticky_wrapper = sticky_wrapper_dir / "trusted-wrapper"
                shutil.copy2(wrapper, sticky_wrapper)
                sticky_wrapper.chmod(0o755)
                result = launch(wrapper_command(sticky_wrapper))
                self.assertEqual(result.returncode, 1, "user-owned sticky wrapper directory")
                self.assertFalse(marker.exists())

            missing_separator_command = [
                sys.executable,
                "-I",
                str(wrapper),
                "--base-repository",
                str(base),
                "--base-commit",
                base_commit,
                *creator_arguments,
            ]
            result = launch(missing_separator_command)
            self.assertEqual(result.returncode, 2, "missing creator separator")
            self.assertIn("explicit -- separator", result.stderr)
            self.assertFalse(marker.exists())

            symlink_wrapper = root / "symlink-wrapper"
            symlink_wrapper.symlink_to(wrapper)
            result = launch(wrapper_command(symlink_wrapper))
            self.assertEqual(result.returncode, 1, "symlink wrapper")
            self.assertFalse(marker.exists())

            equals_command = [
                sys.executable,
                "-I",
                str(wrapper),
                "--base-repository",
                str(base),
                "--base-commit",
                base_commit,
                "--",
                f"--base-repository={base}",
                "--base-commit",
                base_commit,
                "--head-repository",
                str(head),
                "--head-commit",
                base_commit,
            ]
            result = launch(equals_command)
            self.assertEqual(result.returncode, 1, "equals-form creator option")
            self.assertFalse(marker.exists())

            launcher.write_text(
                "#!/usr/bin/env python3\n"
                "import os\n"
                "from pathlib import Path\n"
                "Path(os.environ['ADMISSION_LAUNCHER_MARKER']).write_text('tampered')\n",
                encoding="ascii",
            )
            _run(
                "git",
                "update-index",
                "--assume-unchanged",
                "scripts/create-age-admission-receipt",
                cwd=base,
            )
            result = launch(command)
            self.assertEqual(result.returncode, 1, "tampered trusted launcher")
            self.assertFalse(marker.exists())

    def test_ssh_signature_verification_is_bound_to_namespace_and_principal(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = root / "admission-key"
            allowed = root / "allowed-signers"
            message = b"canonical admission payload\n"
            subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
                check=True,
                capture_output=True,
                timeout=10,
            )
            public_key = (root / "admission-key.pub").read_text(encoding="ascii").split()
            allowed.write_text(
                f'{ADMISSION_PRINCIPAL} namespaces="{ADMISSION_NAMESPACE}" '
                f"{public_key[0]} {public_key[1]}\n",
                encoding="ascii",
            )
            # The signing command consumes a file, so create the exact signed
            # message through the public seam before verification.
            (root / "message").write_bytes(message)
            subprocess.run(
                [
                    "ssh-keygen",
                    "-Y",
                    "sign",
                    "-f",
                    str(key),
                    "-n",
                    ADMISSION_NAMESPACE,
                    str(root / "message"),
                ],
                check=True,
                capture_output=True,
                timeout=10,
            )

            verify_receipt_signature(
                message,
                (root / "message.sig").read_bytes(),
                allowed_signers=allowed,
            )

            tampered = message + b"tampered"
            with self.assertRaisesRegex(ValueError, "signature"):
                verify_receipt_signature(
                    tampered,
                    (root / "message.sig").read_bytes(),
                    allowed_signers=allowed,
                )

            (root / "other-namespace").write_bytes(message)
            subprocess.run(
                [
                    "ssh-keygen",
                    "-Y",
                    "sign",
                    "-f",
                    str(key),
                    "-n",
                    "other/namespace/v1",
                    str(root / "other-namespace"),
                ],
                check=True,
                capture_output=True,
                timeout=10,
            )
            with self.assertRaisesRegex(ValueError, "signature"):
                verify_receipt_signature(
                    message,
                    (root / "other-namespace.sig").read_bytes(),
                    allowed_signers=allowed,
                )

            other_allowed = root / "other-allowed-signers"
            other_allowed.write_text(
                allowed.read_text(encoding="ascii").replace(
                    ADMISSION_PRINCIPAL,
                    "someone-else",
                    1,
                ),
                encoding="ascii",
            )
            with self.assertRaisesRegex(ValueError, "signature"):
                verify_receipt_signature(
                    message,
                    (root / "message.sig").read_bytes(),
                    allowed_signers=other_allowed,
                )

    def test_creator_validates_ciphertexts_and_gate_accepts_its_receipt(self) -> None:
        # Keep the expensive raw-tree fixture together: each rejection probes
        # the same trusted-launch boundary, and splitting it would duplicate
        # setup while making the scenario matrix easier to drift. Decompose
        # after bootstrap once the boundary has an independent App root.
        age_binaries = [
            shutil.which(name) for name in ("age", "age-keygen", "age-inspect")
        ]
        if any(binary is None for binary in age_binaries):
            require_age_tooling_or_skip("age tooling is unavailable")
        age_tooling_directory = shared_age_tooling_directory_or_skip(
            (binary for binary in age_binaries if binary is not None),
            "age tooling does not share one trusted install directory",
        )
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base"
            head = root / "head"
            base.mkdir()
            _run("git", "init", "--quiet", cwd=base)

            identity = root / "age-identity.txt"
            _run(
                "age-keygen",
                "-pq",
                "-o",
                str(identity),
                cwd=base,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            recipient = _run(
                "age-keygen",
                "-y",
                str(identity),
                cwd=base,
                capture_output=True,
            ).stdout.decode().strip()
            ciphertext = _run(
                "age",
                "--encrypt",
                "--recipient",
                recipient,
                cwd=base,
                input=b"base secret",
                capture_output=True,
            ).stdout
            changed_ciphertext = _run(
                "age",
                "--encrypt",
                "--recipient",
                recipient,
                cwd=base,
                input=b"changed secret",
                capture_output=True,
            ).stdout

            # The trusted fixture is an activated boundary: keep every
            # admission-infrastructure pathname materialized so the creator
            # exercises the same completeness check as the real base tree.
            protected = {
                ".github/age-admission/allowed_signers": b"",
                ".github/age-admission/privacy-scan-reviewed-findings-v1.json": b"record\n",
                ".github/actions/privacy-boundary/action.yml": b"boundary\n",
                ".github/workflows/privacy-age-integrity.yml": (
                    b"# Protected admission activation sentinel: owner-signed-age-v1\n"
                    b"workflow\n"
                ),
                ".privacy-age-envelopes.json": b"",
                "docs/ENCRYPTION.md": b"encryption\n",
                "home/.chezmoi.toml.tmpl": b"recipient\n",
                "home/private_dot_local/lib/agent-equipment/agent_equipment/secrets.py": b"secrets\n",
                "home/private.age": ciphertext,
                "scripts/admit-age-envelopes": b"admit\n",
                "scripts/agent_equipment_public_data.py": b"public\n",
                "scripts/create-age-admission-receipt": b"creator\n",
                "scripts/run-trusted-age-admission": b"wrapper\n",
                "scripts/privacy-scan": b"scan\n",
                "scripts/privacy_scan_review.py": b"review\n",
                "scripts/privacy_age_admission.py": b"receipt\n",
                "scripts/privacy_age_envelopes.py": b"envelopes\n",
                "scripts/privacy_age_integrity_gate.py": b"gate\n",
                "scripts/privacy_age_admission_result.py": b"result\n",
                "scripts/privacy_age_pr_snapshot.py": b"snapshot\n",
                "scripts/privacy_age_admission_publisher.py": b"publisher\n",
            }
            for relative, contents in protected.items():
                path = base / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents)
            (base / ".gitattributes").write_text(
                "home/private.age filter=admission-test\n",
                encoding="ascii",
            )
            (base / "AGENTS.md").write_text("trusted fixture guidance\n", encoding="ascii")
            (base / "CLAUDE.md").symlink_to("AGENTS.md")
            shutil.copy2(ADMITTER, base / "scripts/admit-age-envelopes")
            for script_name in (
                "create-age-admission-receipt",
                "privacy-scan",
                "privacy_scan_review.py",
                "privacy_age_admission.py",
                "privacy_age_envelopes.py",
                "privacy_age_integrity_gate.py",
                "privacy_age_admission_result.py",
                "privacy_age_pr_snapshot.py",
                "privacy_age_admission_publisher.py",
            ):
                shutil.copy2(ROOT / "scripts" / script_name, base / "scripts" / script_name)
            (base / "scripts/admit-age-envelopes").chmod(0o755)
            (base / "scripts/create-age-admission-receipt").chmod(0o755)
            (base / "scripts/privacy-scan").chmod(0o755)
            (base / "scripts/run-trusted-age-admission").chmod(0o755)
            signing_key = root / "signing-key"
            _run(
                "ssh-keygen",
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-f",
                str(signing_key),
                cwd=base,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            public = (root / "signing-key.pub").read_text(encoding="ascii").split()
            (base / ".github/age-admission/allowed_signers").write_text(
                f'{ADMISSION_PRINCIPAL} namespaces="{ADMISSION_NAMESPACE}" '
                f"{public[0]} {public[1]}\n",
                encoding="ascii",
            )
            manifest = {
                "version": "privacy-age-envelopes/v1",
                "envelopes": [
                    {
                        "path": "home/private.age",
                        "sha256": "sha256:" + hashlib.sha256(ciphertext).hexdigest(),
                    }
                ],
            }
            (base / ".privacy-age-envelopes.json").write_text(
                json.dumps(manifest, indent=2) + "\n",
                encoding="ascii",
            )
            base_commit = _commit(base, "base")
            _run("git", "clone", "--quiet", "--no-local", str(base), str(head), cwd=root)
            filter_script = root / "smudge-filter.sh"
            filter_sentinel = root / "smudge-filter-ran"
            filter_script.write_text(
                "#!/bin/sh\n"
                f"printf ran > {str(filter_sentinel)!r}\n"
                "printf 'transformed-by-filter\\n'\n",
                encoding="ascii",
            )
            filter_script.chmod(0o755)
            for checkout in (base, head):
                _run(
                    "git",
                    "config",
                    "filter.admission-test.smudge",
                    f"{filter_script} %f",
                    cwd=checkout,
                )
            (head / "home/private.age").write_bytes(changed_ciphertext)
            manifest["envelopes"][0]["sha256"] = "sha256:" + hashlib.sha256(changed_ciphertext).hexdigest()
            (head / ".privacy-age-envelopes.json").write_text(
                json.dumps(manifest, indent=2) + "\n",
                encoding="ascii",
            )
            head_commit = _commit(head, "candidate")

            clean_filter_script = root / "clean-filter.sh"
            clean_filter_sentinel = root / "clean-filter-ran"
            clean_filter_script.write_text(
                "#!/bin/sh\n"
                f"printf ran > {str(clean_filter_sentinel)!r}\n"
                "cat\n",
                encoding="ascii",
            )
            clean_filter_script.chmod(0o755)
            for checkout in (base, head):
                _run(
                    "git",
                    "config",
                    "filter.admission-test.clean",
                    f"{clean_filter_script} %f",
                    cwd=checkout,
                )

            output = root / "receipt.txt"
            creator = base / "scripts/create-age-admission-receipt"
            environment = os.environ.copy()
            environment["AGE_TOOLING_DIRECTORY"] = os.fspath(age_tooling_directory)
            original_signer_path = environment.get("PATH", "")
            if sys.platform == "darwin":
                path_override = root / "path-override"
                path_override.mkdir()
                fake_signer = path_override / "ssh-keygen"
                fake_signer.write_text("#!/bin/sh\nexit 97\n", encoding="ascii")
                fake_signer.chmod(0o755)
                environment["PATH"] = os.pathsep.join(
                    (os.fspath(path_override), environment.get("PATH", ""))
                )

            def creator_command(identity_path: Path, output_path: Path) -> list[str]:
                return [
                    str(creator),
                    "--base-repository",
                    str(base),
                    "--base-commit",
                    base_commit,
                    "--head-repository",
                    str(head),
                    "--head-commit",
                    head_commit,
                    "--repository",
                    "nisavid/dotfiles",
                    "--identity",
                    str(identity_path),
                    "--signing-key",
                    str(signing_key),
                    "--trusted-admitter",
                    str(base / "scripts/admit-age-envelopes"),
                    "--output",
                    str(output_path),
                ]

            result = subprocess.run(
                creator_command(identity, output),
                check=False,
                capture_output=True,
                text=True,
                env=environment,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            if sys.platform == "darwin":
                environment["PATH"] = original_signer_path
            self.assertFalse(filter_sentinel.exists())
            self.assertFalse(clean_filter_sentinel.exists())
            receipt = output.read_bytes()
            self.assertNotIn(b"base secret", receipt)
            self.assertNotIn(b"changed secret", receipt)
            verify_integrity_boundary(
                base_repository=base,
                base_commit=base_commit,
                head_repository=head,
                head_commit=head_commit,
                admission_body=receipt,
                allowed_signers=base / ".github/age-admission/allowed_signers",
                repository="nisavid/dotfiles",
            )

            identity_in_base = base / ".git/identity-in-base"
            shutil.copy2(identity, identity_in_base)
            identity_in_base.chmod(0o600)
            result = subprocess.run(
                creator_command(identity_in_base, root / "identity-receipt.txt"),
                check=False,
                capture_output=True,
                text=True,
                env=environment,
                timeout=30,
            )
            self.assertEqual(result.returncode, 1, "identity inside trusted checkout")

            tooling_in_base = base / ".git/age-tooling"
            tooling_in_base.mkdir()
            tooling_environment = environment.copy()
            tooling_environment["AGE_TOOLING_DIRECTORY"] = str(tooling_in_base)
            result = subprocess.run(
                creator_command(identity, root / "tooling-receipt.txt"),
                check=False,
                capture_output=True,
                text=True,
                env=tooling_environment,
                timeout=30,
            )
            self.assertEqual(result.returncode, 1, "tooling inside trusted checkout")

            if sys.platform != "darwin":
                real_ssh_keygen = shutil.which("ssh-keygen", path=environment["PATH"])
                self.assertIsNotNone(real_ssh_keygen)
                passthrough = (
                    "#!/bin/sh\n"
                    f"exec {shlex.quote(real_ssh_keygen)} \"$@\"\n"
                )

                def assert_path_signer_rejected(
                    directory: Path,
                    output_path: Path,
                    label: str,
                    *,
                    directory_mode: int = 0o755,
                    tool_mode: int = 0o755,
                ) -> None:
                    directory.mkdir()
                    directory.chmod(directory_mode)
                    tool = directory / "ssh-keygen"
                    tool.write_text(passthrough, encoding="ascii")
                    tool.chmod(tool_mode)
                    signer_environment = environment.copy()
                    signer_environment["PATH"] = (
                        f"{directory}{os.pathsep}{environment['PATH']}"
                    )
                    signer_result = subprocess.run(
                        creator_command(identity, output_path),
                        check=False,
                        capture_output=True,
                        text=True,
                        env=signer_environment,
                        timeout=30,
                    )
                    self.assertEqual(signer_result.returncode, 1, label)

                assert_path_signer_rejected(
                    base / ".git/fake-tools",
                    root / "untrusted-signing-tool-receipt.txt",
                    "signing tool inside trusted checkout",
                )
                assert_path_signer_rejected(
                    root / "fake-tools",
                    root / "writable-signing-tool-receipt.txt",
                    "writable signing tool",
                    tool_mode=0o775,
                )
                assert_path_signer_rejected(
                    root / "writable-parent-tools",
                    root / "writable-parent-receipt.txt",
                    "writable signing-tool parent",
                    directory_mode=0o775,
                )

            output_alias = root / "output-alias"
            output_alias.symlink_to(base, target_is_directory=True)
            result = subprocess.run(
                creator_command(identity, output_alias / "receipt.txt"),
                check=False,
                capture_output=True,
                text=True,
                env=environment,
                timeout=30,
            )
            self.assertEqual(result.returncode, 1, "output symlink")

            import_marker = root / "trusted-module-imported"
            (base / "scripts/privacy_age_admission.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(import_marker)!r}).write_text('imported')\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                creator_command(identity, root / "dirty-base-receipt.txt"),
                check=False,
                capture_output=True,
                text=True,
                env=environment,
                timeout=30,
            )
            self.assertEqual(result.returncode, 1, "dirty trusted base")
            self.assertFalse(import_marker.exists())

            hidden_marker = root / "hidden-module-imported"
            hidden_module = base / "scripts/privacy_age_admission.py"
            hidden_module.write_text(
                "from pathlib import Path\n"
                f"Path({str(hidden_marker)!r}).write_text('imported')\n",
                encoding="utf-8",
            )
            _run(
                "git",
                "update-index",
                "--assume-unchanged",
                "scripts/privacy_age_admission.py",
                cwd=base,
            )
            result = subprocess.run(
                creator_command(identity, root / "hidden-dirt-receipt.txt"),
                check=False,
                capture_output=True,
                text=True,
                env=environment,
                timeout=30,
            )
            # The no-filter worktree comparison rejects hidden tracked dirt;
            # the trusted module must still never execute from the worktree.
            self.assertEqual(result.returncode, 1, "hidden module worktree dirt")
            self.assertFalse(hidden_marker.exists())
            _run(
                "git",
                "update-index",
                "--no-assume-unchanged",
                "scripts/privacy_age_admission.py",
                cwd=base,
            )
            shutil.copy2(ROOT / "scripts/privacy_age_admission.py", hidden_module)

            launcher = base / "scripts/create-age-admission-receipt"
            launcher_bytes = launcher.read_bytes()
            tamper_marker = b"sys.dont_write_bytecode = True"
            self.assertEqual(launcher_bytes.count(tamper_marker), 1)
            tampered_launcher_bytes = launcher_bytes.replace(
                tamper_marker,
                b"sys.dont_write_bytecode = False",
                1,
            )
            self.assertNotEqual(tampered_launcher_bytes, launcher_bytes)
            launcher.write_bytes(tampered_launcher_bytes)
            _run(
                "git",
                "update-index",
                "--assume-unchanged",
                "scripts/create-age-admission-receipt",
                cwd=base,
            )
            result = subprocess.run(
                creator_command(identity, root / "hidden-launcher-receipt.txt"),
                check=False,
                capture_output=True,
                text=True,
                env=environment,
                timeout=30,
            )
            self.assertEqual(result.returncode, 1, "hidden launcher worktree dirt")
            _run(
                "git",
                "update-index",
                "--no-assume-unchanged",
                "scripts/create-age-admission-receipt",
                cwd=base,
            )
            launcher.write_bytes(launcher_bytes)
            (head / "home/private.age").write_bytes(b"dirty candidate ciphertext\n")
            result = subprocess.run(
                creator_command(identity, root / "dirty-head-receipt.txt"),
                check=False,
                capture_output=True,
                text=True,
                env=environment,
                timeout=30,
            )
            self.assertEqual(result.returncode, 1, "dirty candidate worktree")


if __name__ == "__main__":
    unittest.main()
