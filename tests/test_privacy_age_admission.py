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
            (base / ".gitattributes").write_text(
                "home/private.age filter=admission-test\n",
                encoding="ascii",
            )
            (base / "AGENTS.md").write_text("trusted fixture guidance\n", encoding="ascii")
            (base / "CLAUDE.md").symlink_to("AGENTS.md")
            shutil.copy2(ADMITTER, base / "scripts/admit-age-envelopes")
            for script_name in (
                "create-age-admission-receipt",
                "privacy_age_admission.py",
                "privacy_age_envelopes.py",
                "privacy_age_integrity_gate.py",
            ):
                shutil.copy2(ROOT / "scripts" / script_name, base / "scripts" / script_name)
            (base / "scripts/admit-age-envelopes").chmod(0o755)
            (base / "scripts/create-age-admission-receipt").chmod(0o755)
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
            environment["AGE_TOOLING_DIRECTORY"] = str(
                Path(os.environ.get("AGE_TOOLING_DIRECTORY", "/opt/homebrew/bin"))
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
            self.assertEqual(result.returncode, 1)

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
            self.assertEqual(result.returncode, 1)

            fake_tool_dir = base / ".git/fake-tools"
            fake_tool_dir.mkdir()
            fake_tool = fake_tool_dir / "ssh-keygen"
            fake_tool.write_text("#!/bin/sh\nexit 99\n", encoding="ascii")
            fake_tool.chmod(0o755)
            untrusted_tool_environment = environment.copy()
            untrusted_tool_environment["PATH"] = (
                f"{fake_tool_dir}{os.pathsep}{environment['PATH']}"
            )
            result = subprocess.run(
                creator_command(identity, root / "untrusted-signing-tool-receipt.txt"),
                check=False,
                capture_output=True,
                text=True,
                env=untrusted_tool_environment,
                timeout=30,
            )
            self.assertEqual(result.returncode, 1)

            external_fake_tool_dir = root / "fake-tools"
            external_fake_tool_dir.mkdir()
            external_fake_tool = external_fake_tool_dir / "ssh-keygen"
            external_fake_tool.write_text("#!/bin/sh\nexit 99\n", encoding="ascii")
            external_fake_tool.chmod(0o775)
            writable_tool_environment = environment.copy()
            writable_tool_environment["PATH"] = (
                f"{external_fake_tool_dir}{os.pathsep}{environment['PATH']}"
            )
            result = subprocess.run(
                creator_command(identity, root / "writable-signing-tool-receipt.txt"),
                check=False,
                capture_output=True,
                text=True,
                env=writable_tool_environment,
                timeout=30,
            )
            self.assertEqual(result.returncode, 1)

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
            self.assertEqual(result.returncode, 1)

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
            self.assertEqual(result.returncode, 1)
            self.assertFalse(import_marker.exists())

            (base / "scripts/privacy_age_admission.py").unlink()
            shutil.copy2(
                ROOT / "scripts/privacy_age_admission.py",
                base / "scripts/privacy_age_admission.py",
            )
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
            self.assertEqual(result.returncode, 1)
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
            launcher.write_bytes(
                launcher_bytes.replace(
                    b"sys.dont_write_bytecode = True",
                    b"sys.dont_write_bytecode = False",
                    1,
                )
            )
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
            self.assertEqual(result.returncode, 1)
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
            self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
