from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.privacy_age_admission import (
    ADMISSION_NAMESPACE,
    ADMISSION_PRINCIPAL,
    ADMISSION_VERSION,
    encode_receipt,
    extract_receipt,
    verify_receipt_signature,
)
from scripts.privacy_age_integrity_gate import verify_integrity_boundary

ROOT = Path(__file__).resolve().parents[1]
CREATOR = ROOT / "scripts/create-age-admission-receipt"
ADMITTER = ROOT / "scripts/admit-age-envelopes"


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
        self.assertEqual(
            json.loads(parsed_bytes),
            payload,
        )

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
            )
            public_key = (root / "admission-key.pub").read_text(encoding="ascii")
            allowed.write_text(
                f"{ADMISSION_PRINCIPAL} {public_key.split(maxsplit=2)[0]} "
                f"{public_key.split(maxsplit=2)[1]}\n",
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

    def test_creator_validates_ciphertexts_and_gate_accepts_its_receipt(self) -> None:
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

            protected = {
                ".github/age-admission/allowed_signers": b"",
                ".github/actions/privacy-boundary/action.yml": b"boundary\n",
                ".github/workflows/privacy-age-integrity.yml": b"workflow\n",
                ".privacy-age-envelopes.json": b"",
                "docs/ENCRYPTION.md": b"encryption\n",
                "home/.chezmoi.toml.tmpl": b"recipient\n",
                "home/private_dot_local/lib/agent-equipment/agent_equipment/secrets.py": b"secrets\n",
                "home/private.age": ciphertext,
                "scripts/admit-age-envelopes": b"admit\n",
                "scripts/agent_equipment_public_data.py": b"public\n",
                "scripts/create-age-admission-receipt": b"creator\n",
                "scripts/privacy-scan": b"scan\n",
                "scripts/privacy_age_admission.py": b"receipt\n",
                "scripts/privacy_age_envelopes.py": b"envelopes\n",
                "scripts/privacy_age_integrity_gate.py": b"gate\n",
            }
            for relative, contents in protected.items():
                path = base / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents)
            shutil.copy2(ADMITTER, base / "scripts/admit-age-envelopes")
            shutil.copy2(
                ROOT / "scripts/privacy_age_envelopes.py",
                base / "scripts/privacy_age_envelopes.py",
            )
            (base / "scripts/admit-age-envelopes").chmod(0o755)
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
                f"repository-owner {public[0]} {public[1]}\n",
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
            (head / "home/private.age").write_bytes(changed_ciphertext)
            manifest["envelopes"][0]["sha256"] = "sha256:" + hashlib.sha256(changed_ciphertext).hexdigest()
            (head / ".privacy-age-envelopes.json").write_text(
                json.dumps(manifest, indent=2) + "\n",
                encoding="ascii",
            )
            head_commit = _commit(head, "candidate")

            output = root / "receipt.txt"
            environment = os.environ.copy()
            environment["AGE_TOOLING_DIRECTORY"] = str(
                Path(os.environ.get("AGE_TOOLING_DIRECTORY", "/opt/homebrew/bin"))
            )
            def creator_command(identity_path: Path, output_path: Path) -> list[str]:
                return [
                    str(CREATOR),
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

            identity_in_base = base / "identity-in-base"
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
            self.assertEqual(result.returncode, 1)

            tooling_in_base = base / "age-tooling"
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
            self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
