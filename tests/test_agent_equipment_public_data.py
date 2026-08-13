from __future__ import annotations

import hashlib
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.agent_equipment_public_data import (
    contains_literal_credential,
    string_looks_like_credential,
)

ROOT = Path(__file__).resolve().parent.parent


def provider_credentials() -> tuple[str, ...]:
    return (
        *("gh" + prefix + "_" + "A" * 20 for prefix in "pousr"),
        "github" + "_pat_" + "A" * 20,
        "AK" + "IA" + "A" * 16,
        "s" + "k-" + "A" * 20,
        "p" + "st_" + "A" * 12 + "::" + "B" * 8,
    )


def header_and_query_credentials() -> tuple[str, ...]:
    authorization = "Author" + "ization:"
    proxy_authorization = "Proxy-Author" + "ization"
    bearer_value = " Bear" + "er actual-secret-value"
    x_api_key = "X-Api-" + "Key:"
    client_secret = "client_" + "secret=actual-secret-value"
    return (
        authorization + bearer_value,
        authorization + " Digest actual-secret-value",
        authorization + " actual-secret-value",
        authorization.casefold() + bearer_value.casefold(),
        proxy_authorization + "=" + "Basic Zml4dHVyZTpzZWNyZXQ=",
        proxy_authorization + ": opaque-secret-value",
        x_api_key + " actual-secret-value",
        "api_" + "key=actual-secret-value",
        "access-" + "token: actual-secret-value",
        "pass" + "word=actual-secret-value",
        "client_" + "secret: actual-secret-value",
        "Bearer " + "actual-secret-value",
        "https://example.invalid/mcp?" + "token=actual-secret-value",
        "https://example.invalid/mcp?a=1&" + client_secret,
    )


class AgentEquipmentPublicDataTest(unittest.TestCase):
    def test_provider_token_families_are_literal_credentials(self) -> None:
        for credential in provider_credentials():
            with self.subTest(family=credential[:4]):
                self.assertTrue(string_looks_like_credential(credential))

    def test_header_and_query_values_are_credentials_but_references_are_public(
        self,
    ) -> None:
        credentials = header_and_query_credentials()
        public_values = (
            "Authorization:Bearer {reference}",
            "Authorization:Bearer ${{reference}}",
            "Authorization:Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}",
            "Authorization:Bearer $GREPTILE_API_KEY",
            "https://example.invalid/mcp?token={reference}",
            "apply-authorization:sha256:" + "a" * 64,
            "authorization:fixture/apply",
            "authorization = validated_record",
            "https://token.example.com/mcp",
            "sk-version-public",
            "activation:example/canary-label",
            "GITHUB_PERSONAL_ACCESS_TOKEN",
            "secret_profile:context7",
            (
                "git+https://example.invalid/public.git@"
                "0123456789abcdef0123456789abcdef01234567"
            ),
        )

        for credential in credentials:
            with self.subTest(credential=credential.split(":", 1)[0]):
                self.assertTrue(string_looks_like_credential(credential))
        for public_value in public_values:
            with self.subTest(public_value=public_value):
                self.assertFalse(string_looks_like_credential(public_value))

    def test_recursive_documents_include_keys_and_do_not_follow_cycles(self) -> None:
        credential = "gh" + "p_" + "A" * 20
        nested = {"public": [{"nested": credential}]}
        credential_key = {credential: "redacted"}
        cycle: list[object] = []
        cycle.append(cycle)

        self.assertTrue(contains_literal_credential(nested))
        self.assertTrue(contains_literal_credential(credential_key))
        self.assertFalse(contains_literal_credential(cycle))

    def test_privacy_scan_uses_the_shared_policy_without_echoing_values(self) -> None:
        credentials = (
            provider_credentials()
            + header_and_query_credentials()
            + ("fixture context " + provider_credentials()[0],)
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            unsafe = root / "unsafe.txt"
            unsafe.write_text("\n".join(credentials) + "\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/privacy-scan"),
                    "--root",
                    str(root),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                f"unsafe.txt:{line_number}: [provider-token] review required"
                for line_number in range(1, len(credentials) + 1)
            ],
        )
        self.assertTrue(all(value not in result.stdout for value in credentials))

    def test_privacy_scan_redacts_and_reports_a_credential_shaped_filename(
        self,
    ) -> None:
        credential = "github" + "_pat_" + "A" * 20
        relative = f"artifact-{credential}.age"
        redacted_path = (
            "redacted-path:sha256:"
            + hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / relative).write_bytes(b"\0binary contents")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/privacy-scan"),
                    "--root",
                    str(root),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout,
            f"{redacted_path}:0: [provider-token-filename] review required\n",
        )
        self.assertNotIn(credential, result.stdout)

    def test_privacy_scan_redacts_other_sensitive_filename_families(self) -> None:
        private_email = "operator@" + "private.invalid.txt"
        private_mac = "aa:bb:cc:" + "dd:ee:ff.txt"
        sensitive_paths = {
            "private-machine-label.txt": "exact-denylist-filename",
            private_email: "email-filename",
            private_mac: "mac-address-filename",
        }
        with TemporaryDirectory() as directory, TemporaryDirectory() as private:
            root = Path(directory)
            denylist = Path(private) / "denylist"
            denylist.write_text("private-machine-label\n", encoding="utf-8")
            for relative in sensitive_paths:
                (root / relative).write_text("public contents\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/privacy-scan"),
                    "--root",
                    str(root),
                    "--denylist",
                    str(denylist),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        expected = {
            "redacted-path:sha256:"
            + hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]
            + f":0: [{rule}] review required"
            for relative, rule in sensitive_paths.items()
        }
        self.assertEqual(result.returncode, 1)
        self.assertEqual(set(result.stdout.splitlines()), expected)
        self.assertTrue(
            all(relative not in result.stdout for relative in sensitive_paths)
        )

    def test_privacy_scan_does_not_follow_file_symlinks_outside_the_root(self) -> None:
        credential = provider_credentials()[0]
        with TemporaryDirectory() as root_directory, TemporaryDirectory() as outside:
            root = Path(root_directory)
            target = Path(outside) / "outside.txt"
            target.write_text(credential + "\n", encoding="utf-8")
            (root / "public-link").symlink_to(target)

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/privacy-scan"),
                    "--root",
                    str(root),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
