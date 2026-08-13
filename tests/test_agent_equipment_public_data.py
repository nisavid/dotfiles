from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.agent_equipment_public_data import (
    contains_literal_credential,
    string_looks_like_credential,
    string_looks_like_private_key,
)

ROOT = Path(__file__).resolve().parent.parent


def write_age_manifest(root: Path, paths: list[str]) -> None:
    document = {
        "version": "privacy-age-envelopes/v1",
        "envelopes": [
            {
                "path": relative,
                "sha256": "sha256:"
                + hashlib.sha256((root / relative).read_bytes()).hexdigest(),
            }
            for relative in sorted(paths)
        ],
    }
    (root / ".privacy-age-envelopes.json").write_bytes(
        (json.dumps(document, ensure_ascii=True, indent=2) + "\n").encode("ascii")
    )


def provider_credentials() -> tuple[str, ...]:
    return (
        *("gh" + prefix + "_" + "A" * 20 for prefix in "pousr"),
        "github" + "_pat_" + "A" * 20,
        "AK" + "IA" + "A" * 16,
        "AS" + "IA" + "A" * 16,
        "s" + "k-" + "A" * 20,
        "p" + "st_" + "A" * 12 + "::" + "B" * 8,
    )


def header_and_query_credentials() -> tuple[str, ...]:
    authorization = "Author" + "ization:"
    proxy_authorization = "Proxy-Author" + "ization"
    bearer_value = " Bear" + "er actual-secret-value"
    x_api_key = "X-Api-" + "Key:"
    credential_query_tail = "client_" + "secret=actual-secret-value"
    return (
        authorization + bearer_value,
        authorization + " Digest actual-secret-value",
        authorization + " actual-secret-value",
        authorization.casefold() + bearer_value.casefold(),
        authorization.casefold() + " opaque-secret-value",
        proxy_authorization + "=" + "Basic Zml4dHVyZTpzZWNyZXQ=",
        proxy_authorization + ": opaque-secret-value",
        x_api_key + " actual-secret-value",
        "api_" + "key=actual-secret-value",
        "api_" + 'key="actual-secret-value"',
        "access-" + "token: actual-secret-value",
        "pass" + "word=actual-secret-value",
        "pass" + "word: 'actual-secret-value'",
        "client_" + "secret: actual-secret-value",
        "Bearer " + "actual-secret-value",
        "https://example.invalid/mcp?" + "token=actual-secret-value",
        "https://example.invalid/mcp?a=1&" + credential_query_tail,
    )


def provider_credential_fields() -> tuple[tuple[str, str], ...]:
    return (
        ("AWS_" + "ACCESS_KEY_ID", "aws-access-key-id-canary"),
        ("AWS_" + "SECRET_ACCESS_KEY", "aws-secret-access-key-canary"),
        ("AWS_" + "SESSION_TOKEN", "aws-session-token-canary"),
        ("CONTEXT7_" + "API_KEY", "context7-api-key-canary"),
        ("FIRECRAWL_" + "API_KEY", "firecrawl-api-key-canary"),
        ("GREPTILE_" + "API_KEY", "greptile-api-key-canary"),
        ("GITHUB_" + "TOKEN", "github-token-canary"),
        ("GH_" + "TOKEN", "gh-token-canary"),
        ("GITHUB_" + "PERSONAL_ACCESS_TOKEN", "github-pat-canary"),
        ("GITHUB_" + "PAT", "github-pat-alias-canary"),
        ("GITHUB_" + "OAUTH_TOKEN", "github-oauth-token-canary"),
        ("GITHUB_" + "ENTERPRISE_TOKEN", "github-enterprise-token-canary"),
        ("GH_" + "ENTERPRISE_TOKEN", "gh-enterprise-token-canary"),
        ("CODEX_" + "GITHUB_PAT", "codex-github-pat-canary"),
        ("FOSSA_" + "API_KEY", "fossa-api-key-canary"),
        ("API_KEY_" + "CONTEXT7", "context7-suffix-canary"),
        ("TOKEN_" + "GITHUB", "github-suffix-canary"),
        ("aws." + "secret_access_key", "aws-dotted-key-canary"),
        ("github." + "personal.access.token", "github-dotted-key-canary"),
        ("AWS." + "SECRET.ACCESS.KEY", "aws-uppercase-dotted-key-canary"),
    )


def private_key_markers() -> tuple[str, ...]:
    return tuple(
        "-----BEGIN " + prefix + "PRIVATE KEY-----"
        for prefix in ("", "ENCRYPTED ", "RSA ", "EC ", "DSA ", "OPENSSH ")
    ) + (
        "-----BEGIN " + "PGP PRIVATE KEY BLOCK-----",
        "-----BEGIN " + "SSH2 ENCRYPTED PRIVATE KEY-----",
        "---- BEGIN " + "SSH2 ENCRYPTED PRIVATE KEY ----",
        "PuTTY-User-" + "Key-File-3: ssh-ed25519",
        "AGE-" + "SECRET-KEY-" + "A" * 32,
    )


class AgentEquipmentPublicDataTest(unittest.TestCase):
    def test_provider_token_families_are_literal_credentials(self) -> None:
        for credential in provider_credentials():
            with self.subTest(family=credential[:4]):
                self.assertTrue(string_looks_like_credential(credential))

    def test_private_key_markers_are_shared_literal_credentials(self) -> None:
        for marker in private_key_markers():
            with self.subTest(marker=marker.split(" ")[1:2]):
                self.assertTrue(string_looks_like_private_key(marker))
                self.assertTrue(string_looks_like_credential(marker))

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
            '"pass' + 'word": password',
            (
                "git+https://example.invalid/public.git@"
                "0123456789abcdef0123456789abcdef01234567"
            ),
            (
                '{"Access' + 'KeyId":"\'${AWS_ACCESS_KEY_ID}\'",'
                '"SecretAccess' + 'Key":"\'${AWS_SECRET_ACCESS_KEY}\'"}'
            ),
        )

        for credential in credentials:
            with self.subTest(credential=credential.split(":", 1)[0]):
                self.assertTrue(string_looks_like_credential(credential))
        for public_value in public_values:
            with self.subTest(public_value=public_value):
                self.assertFalse(string_looks_like_credential(public_value))

    def test_bearer_prose_is_public_but_credential_context_is_not(self) -> None:
        authorization = "Author" + "ization"
        proxy_authorization = "Proxy-Author" + "ization"
        bearer = "Bear" + "er "
        public_prose = (
            "Use Bearer authentication for requests.",
            "The bearer token is supplied by the runtime.",
            "Bearer authentication is required by this endpoint.",
        )
        credential_values = (
            authorization + ": " + bearer + "actual-secret-value",
            proxy_authorization + "=" + bearer + "actual-secret-value",
            bearer + "gh" + "p_" + "A" * 20,
            bearer + "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signature",
            bearer + "abcdefghijklmnopqrstuvwxyz",
            bearer + "A" * 32,
        )

        for prose in public_prose:
            with self.subTest(prose=prose):
                self.assertFalse(string_looks_like_credential(prose))
        for credential in credential_values:
            with self.subTest(credential=credential[:24]):
                self.assertTrue(string_looks_like_credential(credential))

    def test_github_expression_literals_are_scanned_before_references_are_removed(
        self,
    ) -> None:
        credential = "gh" + "p_" + "A" * 20
        literal_expression = "${{" + repr(credential) + "}}"

        self.assertTrue(string_looks_like_credential(literal_expression))
        self.assertFalse(string_looks_like_credential("${{ secrets.GITHUB_TOKEN }}"))

    def test_recursive_documents_include_keys_and_do_not_follow_cycles(self) -> None:
        credential = "gh" + "p_" + "A" * 20
        nested = {"public": [{"nested": credential}]}
        credential_key = {credential: "redacted"}
        cycle: list[object] = []
        cycle.append(cycle)

        self.assertTrue(contains_literal_credential(nested))
        self.assertTrue(contains_literal_credential(credential_key))
        self.assertFalse(contains_literal_credential(cycle))

    def test_recursive_documents_preserve_credential_field_value_context(
        self,
    ) -> None:
        credential_fields = (
            {"api_" + "key": "actual-secret-value"},
            {"pass" + "word": "actual-secret-value"},
            {"to" + "ken": "actual-secret-value"},
            {"author" + "ization": "opaque-secret-value"},
        )

        for document in credential_fields:
            with self.subTest(field=next(iter(document))):
                self.assertTrue(contains_literal_credential(document))
        self.assertFalse(
            contains_literal_credential(
                {"secret_reference": "GITHUB_PERSONAL_ACCESS_TOKEN"}
            )
        )
        public_reference_fields = (
            {"to" + "ken": "$TOKEN"},
            {"api_" + "key": "${API_KEY}"},
            {"pass" + "word": "${{ secrets.PASSWORD }}"},
            {"client_" + "secret": "secret_profile:context7"},
            {
                "to" + "ken": {
                    "secret_profile_reference": "context7",
                }
            },
            {
                "api_" + "key": {
                    "secret_reference": "API_KEY",
                    "template": "{reference}",
                }
            },
        )
        for document in public_reference_fields:
            with self.subTest(public_reference=next(iter(document))):
                self.assertFalse(contains_literal_credential(document))

    def test_serialized_credential_assignments_match_mapping_policy(self) -> None:
        literal = "actual-" + "secret value"
        credential_fields = (
            "api_" + "key",
            "access_" + "token",
            "pass" + "word",
            "client_" + "secret",
            "to" + "ken",
            "sec" + "ret",
            "author" + "ization",
            "proxy-author" + "ization",
            "x-api-" + "key",
        )

        for field in credential_fields:
            document = {field: literal}
            serialized_documents = (
                json.dumps(document, separators=(",", ":")),
                f"{field}: '{literal}'",
                f'{field} = "{literal}"',
            )
            with self.subTest(field=field):
                self.assertTrue(contains_literal_credential(document))
                for serialized in serialized_documents:
                    self.assertTrue(string_looks_like_credential(serialized))

        parity_documents = (
            ("TO" + "KEN=abcdefg", {"TO" + "KEN": "abcdefg"}),
            ("FOSSA_API_" + "KEY=abc1234", {"FOSSA_API_" + "KEY": "abc1234"}),
            ('"TO' + 'KEN": actualsecretvalue', {"TO" + "KEN": "actualsecretvalue"}),
            (
                '"FOSSA_API_' + 'KEY" = fossaactualsecret',
                {"FOSSA_API_" + "KEY": "fossaactualsecret"},
            ),
        )
        for serialized, document in parity_documents:
            with self.subTest(serialized=serialized):
                self.assertTrue(contains_literal_credential(document))
                self.assertTrue(string_looks_like_credential(serialized))

    def test_provider_credential_fields_match_mapping_and_serialized_policy(
        self,
    ) -> None:
        for field, literal in provider_credential_fields():
            with self.subTest(field=field):
                self.assertTrue(contains_literal_credential({field: literal}))
                self.assertTrue(
                    string_looks_like_credential(
                        json.dumps({field: literal}, separators=(",", ":"))
                    )
                )

        public_fields = ("compat", "compatibility", "secret_profile_reference")
        for field in public_fields:
            with self.subTest(public_field=field):
                self.assertFalse(contains_literal_credential({field: "public"}))
                self.assertFalse(
                    string_looks_like_credential(
                        json.dumps({field: "public"}, separators=(",", ":"))
                    )
                )
        self.assertFalse(contains_literal_credential({"compare_token": "absent"}))

    def test_common_provider_environment_fields_are_credentials_but_controls_are_not(
        self,
    ) -> None:
        literal_fields = (
            "NPM_TOKEN",
            "HF_TOKEN",
            "HF_ACCESS_TOKEN",
            "HUGGINGFACE_TOKEN",
            "SENTRY_AUTH_TOKEN",
            "CLOUDFLARE_API_TOKEN",
            "VERCEL_TOKEN",
            "SLACK_BOT_TOKEN",
            "SUPABASE_PASSWORD",
            "SUPABASE_ACCESS_TOKEN",
            "DB_PASSWORD",
            "POSTGRES_PASSWORD",
            "REDIS_PASSWORD",
            "DOCKER_PASSWORD",
            "STRIPE_SECRET_KEY",
            "WEBHOOK_SECRET",
            "JWT_SECRET",
            "COOKIE_SECRET",
        )
        public_fields = (
            "compare_token",
            "compat",
            "compatibility_token",
            "authorization_identity",
            "secret_reference",
            "secret_profile_reference",
        )

        for field in literal_fields:
            with self.subTest(literal_field=field):
                document = {field: "actual-secret-value"}
                self.assertTrue(contains_literal_credential(document))
                self.assertTrue(
                    string_looks_like_credential(
                        json.dumps(document, separators=(",", ":"))
                    )
                )
        for field in public_fields:
            with self.subTest(public_field=field):
                document = {field: "public-control-value"}
                self.assertFalse(contains_literal_credential(document))
                self.assertFalse(
                    string_looks_like_credential(
                        json.dumps(document, separators=(",", ":"))
                    )
                )

    def test_credential_field_context_rejects_unrecognized_composites(self) -> None:
        literal_documents = (
            {"to" + "ken": {"value": "actual-secret"}},
            {"api_" + "key": {"literal": "actual-secret-value"}},
            {"pass" + "word": ["actual-secret"]},
            {
                "client_" + "secret": {
                    "name": "public",
                    "value": "actual-secret-value",
                }
            },
            {
                "pass" + "word": {
                    "secret_reference": "TOKEN",
                    "extra": "public",
                }
            },
        )
        public_documents = (
            {
                "to" + "ken": {
                    "secret_reference": "TOKEN",
                    "template": "Authorization:Bearer ${{reference}}",
                }
            },
            {"to" + "ken": {"secret_profile_reference": "github"}},
        )

        for document in literal_documents:
            with self.subTest(literal=document):
                self.assertTrue(contains_literal_credential(document))
        for document in public_documents:
            with self.subTest(public=document):
                self.assertFalse(contains_literal_credential(document))

    def test_python_literal_mappings_preserve_nested_credential_context(self) -> None:
        document = "config = " + repr({"DB_" + "PASSWORD": "actual-" + "secret"})

        self.assertTrue(string_looks_like_credential(document))

    def test_reference_values_must_be_the_complete_credential_value(self) -> None:
        mixed_values = (
            "${TOKEN}actual-secret",
            "actual-secret${TOKEN}",
            "Bearer ${TOKEN} actual-secret",
            "Bearer ${TOKEN}-actual-secret",
            "Basic {reference}:actual-secret",
            "Basic ${TOKEN}-actual-secret",
            "pass://fixture-vault/item/password actual-secret",
            "secret_reference:TOKEN/actual-secret",
        )
        exact_references = (
            "${TOKEN}",
            "${{ secrets.TOKEN }}",
            "{reference}",
            "pass://fixture-vault/item/password",
            "secret_reference:TOKEN",
        )

        for value in mixed_values:
            with self.subTest(mixed=value):
                self.assertTrue(contains_literal_credential({"token": value}))
                self.assertTrue(
                    string_looks_like_credential(
                        json.dumps({"token": value}, separators=(",", ":"))
                    )
                )
        for value in exact_references:
            with self.subTest(reference=value):
                self.assertFalse(contains_literal_credential({"token": value}))

    def test_provider_and_private_key_signatures_are_checked_before_parsing(
        self,
    ) -> None:
        provider_token = "gh" + "p_" + "A" * 24
        private_key = "-----BEGIN " + "PGP PRIVATE KEY BLOCK-----"
        documents = (
            '{"token":"${TOKEN}","note":"' + provider_token + '"}',
            "token = '${TOKEN}'\nnote = '" + private_key + "'\n",
        )

        for document in documents:
            with self.subTest(document=document[:16]):
                self.assertTrue(string_looks_like_credential(document))

    def test_serialized_credential_fields_accept_common_statement_terminators(
        self,
    ) -> None:
        field = "FIRECRAWL_" + "API_KEY"
        literal = "quoted secret value"
        padded_literal = "AaBbCcDdEeFf00112233445566778899+/="
        documents = (
            f'{field}="{literal}";',
            f'{field}="{literal}" # runtime comment',
            f'{field}="{literal}" // runtime comment',
            f'const {field} = "{literal}"; // runtime comment',
            f'{field}="{literal}");',
            f'call({field}="{literal}")',
            f"{field}={padded_literal};",
            f'{{"{field}":"{literal}"}},',
            f'[{field}="{literal}"]',
            f'{field}="{literal}"\nnext = public',
            f'{field}="{literal}"',
        )

        for document in documents:
            with self.subTest(document=document):
                self.assertTrue(string_looks_like_credential(document))

    def test_serialized_credential_assignments_preserve_reference_exceptions(
        self,
    ) -> None:
        credential_fields = (
            "to" + "ken",
            "sec" + "ret",
            "author" + "ization",
            "proxy-author" + "ization",
        )
        references = (
            "$TOKEN",
            "${TOKEN}",
            "${{ secrets.TOKEN }}",
            "secret_profile:context7",
            "secret_reference:API_KEY",
            "reference:context7",
            "pass://fixture-vault/item/password",
            "secret-service://",
        )

        for field in credential_fields:
            for reference in references:
                document = {field: reference}
                serialized = json.dumps(document, separators=(",", ":"))
                shell_fixture_source = f"print -r -- '{field}={reference}'"
                with self.subTest(field=field, reference=reference):
                    self.assertFalse(contains_literal_credential(document))
                    self.assertFalse(string_looks_like_credential(serialized))
                    self.assertFalse(string_looks_like_credential(shell_fixture_source))

    def test_provider_references_do_not_mask_adjacent_literal_credentials(
        self,
    ) -> None:
        api_key = "api_" + "key"
        context7_api_key = "context7_" + "api_key"
        credential_field = "to" + "ken"
        literal = "actual-" + "secret-value"
        documents = (
            (
                f"{api_key}=pass://fixture-vault/item/password;"
                f"{credential_field}={literal}"
            ),
            json.dumps(
                {
                    context7_api_key: "pass://fixture-vault/item/password",
                    credential_field: literal,
                },
                separators=(",", ":"),
            ),
        )

        for document in documents:
            with self.subTest(document=document):
                self.assertTrue(string_looks_like_credential(document))

    def test_reference_wrappers_do_not_mask_provider_credentials(self) -> None:
        github_token = "gh" + "p_" + "A" * 36
        aws_access_key = "AK" + "IA" + "A" * 16
        aws_session_token = "AS" + "IA" + "A" * 16
        openai_key = "s" + "k-" + "A" * 24
        wrapped_literals = (
            "$" + github_token,
            "${" + github_token + "}",
            "${{ " + github_token + " }}",
            "${{ secrets." + github_token + " }}",
            "reference:" + github_token,
            "secret_reference:" + aws_access_key,
            "secret_profile:" + aws_session_token,
            "reference:" + openai_key,
            "pass://" + github_token + "/item/password",
        )

        for wrapped in wrapped_literals:
            with self.subTest(wrapper=wrapped.split(":", 1)[0]):
                self.assertTrue(string_looks_like_credential(wrapped))
                self.assertTrue(contains_literal_credential({"to" + "ken": wrapped}))

    def test_malformed_reference_prefixes_are_literal_credential_values(self) -> None:
        field = "to" + "ken"
        literal = "actual-" + "secret"
        documents = (
            f"{field}=pass://vault/item/password{field.upper()}={literal}",
            f"{field}=pass://vault/item/password-{field.upper()}={literal}",
            f"{field}=reference:context7/{field.upper()}={literal}",
        )

        for document in documents:
            with self.subTest(document=document):
                self.assertTrue(string_looks_like_credential(document))

    def test_mixed_reference_and_literal_values_are_credentials(self) -> None:
        token_field = "to" + "ken"
        fossa_field = "FOSSA_API_" + "KEY"
        documents = (
            token_field + "=actual-secret-${SUFFIX}",
            token_field + "=${PREFIX}-actual-secret",
            fossa_field + "=${PREFIX}actualsecret${SUFFIX}",
            token_field + r"=\$PREFIX-actual-secret",
        )

        for document in documents:
            with self.subTest(document=document):
                self.assertTrue(string_looks_like_credential(document))

        authorization = "Author" + "ization"
        authorization_values = (
            authorization + ": Bear" + "er ${TOKEN}-actual-secret",
            authorization + ": Bas" + "ic ${TOKEN}-actual-secret",
        )
        for value in authorization_values:
            with self.subTest(authorization=value.split(":", 1)[1]):
                self.assertTrue(string_looks_like_credential(value))

    def test_reviewer_punctuation_and_provider_bypass_corpus_is_rejected(self) -> None:
        documents = (
            "TOKEN=actual!secret",
            "FOSSA_API_KEY=actual%secret",
            "TOKEN: actual secret value",
            "TOKEN: actual[secret]",
            "TOKEN=actual-secret?x=1",
            "TOKEN=actual&secret",
            "TOKEN=actual(secret)",
            "TOKEN=-actualsecret",
            "NPM_TOKEN=actual-secret-value",
            "HF_TOKEN=actual-secret-value",
            "HUGGINGFACE_TOKEN=actual-secret-value",
            "SENTRY_AUTH_TOKEN=actual-secret-value",
            "CLOUDFLARE_API_TOKEN=actual-secret-value",
            "VERCEL_TOKEN=actual-secret-value",
            "SLACK_BOT_TOKEN=actual-secret-value",
            "SUPABASE_ACCESS_TOKEN=actual-secret-value",
            "DB_PASSWORD=actual-secret-value",
            "POSTGRES_PASSWORD=actual-secret-value",
            "REDIS_PASSWORD=actual-secret-value",
            "DOCKER_PASSWORD=actual-secret-value",
            "STRIPE_SECRET_KEY=actual-secret-value",
            "WEBHOOK_SECRET=actual-secret-value",
            "JWT_SECRET=actual-secret-value",
            "COOKIE_SECRET=actual-secret-value",
        )

        for document in documents:
            with self.subTest(document=document.split("=", 1)[0]):
                self.assertTrue(string_looks_like_credential(document))

    def test_json_unicode_escaped_credential_keys_do_not_evade_policy(self) -> None:
        escaped_key = "Authoriz" + "\\u0061" + "tion"
        serialized = '{"' + escaped_key + '":"actual-secret-value"}'

        self.assertTrue(string_looks_like_credential(serialized))

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

    def test_privacy_scan_rejects_credentials_in_python_comments_and_docstrings(
        self,
    ) -> None:
        credential = "Bear" + "er " + "A" * 32
        sources = {
            "comment.py": "# Author" + "ization: " + credential + "\n",
            "docstring.py": '"""Author' + "ization: " + credential + '"""\n',
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, source in sources.items():
                (root / relative).write_text(source, encoding="utf-8")

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
            set(result.stdout.splitlines()),
            {
                "comment.py:1: [provider-token] review required",
                "docstring.py:1: [provider-token] review required",
            },
        )
        self.assertNotIn(credential, result.stdout + result.stderr)

    def test_privacy_scan_rejects_a_credential_hidden_by_a_duplicate_json_member(
        self,
    ) -> None:
        field = "to" + "ken"
        credential = "actual-" + "secret-value"
        document = '{"' + field + '":"' + credential + '","' + field + '":"${TOKEN}"}\n'
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "duplicate.json").write_text(document, encoding="utf-8")

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
            "duplicate.json:1: [provider-token] review required\n",
        )
        self.assertNotIn(credential, result.stdout + result.stderr)

    def test_privacy_scan_rejects_a_numeric_credential_field(self) -> None:
        field = "pass" + "word"
        token_field = "to" + "ken"
        credential = "123456"
        document = '{"' + field + '":' + credential + "}\n"
        absent_document = '{"' + field + '":null,"' + token_field + '":false}\n'
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "numeric.json").write_text(document, encoding="utf-8")
            (root / "absent.json").write_text(
                absent_document,
                encoding="utf-8",
            )

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
        self.assertIn(
            "numeric.json:0: [provider-token] review required",
            result.stdout,
        )
        self.assertNotIn("absent.json", result.stdout)
        self.assertNotIn(credential, result.stdout + result.stderr)

    def test_privacy_scan_rejects_each_provider_credential_field_without_echoing_values(
        self,
    ) -> None:
        assignments = tuple(
            f'{field}="{literal}"' for field, literal in provider_credential_fields()
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "provider-fields.env").write_text(
                "\n".join(assignments) + "\n",
                encoding="utf-8",
            )

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
                f"provider-fields.env:{line_number}: [provider-token] review required"
                for line_number in range(1, len(assignments) + 1)
            ],
        )
        self.assertTrue(
            all(
                literal not in result.stdout
                for _, literal in provider_credential_fields()
            )
        )

    def test_privacy_scan_rejects_cross_line_assignments_without_echoing_values(
        self,
    ) -> None:
        aws_field = "AWS_SECRET_ACCESS_" + "KEY"
        firecrawl_field = "FIRECRAWL_API_" + "KEY"
        aws_literal = "AwsSecretLiteral123+/="
        firecrawl_literal = "firecrawl-literal-canary"
        documents = {
            "credential.json": ('{"' + aws_field + '":\n "' + aws_literal + '"}\n'),
            "credential.yaml": firecrawl_field + ":\n " + firecrawl_literal + "\n",
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, document in documents.items():
                (root / relative).write_text(document, encoding="utf-8")

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
            set(result.stdout.splitlines()),
            {
                "credential.json:0: [provider-token] review required",
                "credential.yaml:0: [provider-token] review required",
            },
        )
        self.assertNotIn(aws_literal, result.stdout + result.stderr)
        self.assertNotIn(firecrawl_literal, result.stdout + result.stderr)

    def test_privacy_scan_preserves_serialized_mapping_parity(self) -> None:
        documents = (
            "TO" + "KEN=abcdefg\n",
            "FOSSA_API_" + "KEY=abc1234\n",
            '"TO' + 'KEN": actualsecretvalue\n',
            '"FOSSA_API_' + 'KEY" = fossaactualsecret\n',
            "TO" + "KEN:\n  abcdefghij\n",
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for index, document in enumerate(documents):
                (root / f"credential-{index}.txt").write_text(
                    document,
                    encoding="utf-8",
                )

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
            len(
                [
                    line
                    for line in result.stdout.splitlines()
                    if "[provider-token]" in line
                ]
            ),
            len(documents),
        )
        self.assertTrue(
            all(document.strip() not in result.stdout for document in documents)
        )

    def test_cross_line_yaml_alphanumeric_literals_are_credentials(self) -> None:
        firecrawl_field = "FIRECRAWL_API_" + "KEY"
        token_field = "TO" + "KEN"
        documents = (
            firecrawl_field + ":\n  actual" + "secret123\n",
            token_field + ":\n  abcdefghijklmnopqrstuvwxyz\n",
            token_field + ":\n  abcdefghij\n",
        )

        for document in documents:
            with self.subTest(field=document.split(":", 1)[0]):
                self.assertTrue(string_looks_like_credential(document))

    def test_structured_serializers_do_not_wrap_literal_credentials(self) -> None:
        token_field = "TO" + "KEN"
        fossa_field = "FOSSA_API_" + "KEY"
        documents = (
            token_field + ": >-\n  actual-secret-value\n",
            fossa_field + ": |\n  fossa-actual-secret-value\n",
            token_field + ": &credential actual-secret-value\n",
            token_field + ": !!str actual-secret-value\n",
            token_field + ' = """actual-secret-value"""\n',
            token_field + " = '''actual-secret-value'''\n",
        )

        for document in documents:
            with self.subTest(document=document.splitlines()[0]):
                self.assertTrue(string_looks_like_credential(document))

    def test_json_and_toml_parsers_preserve_mapping_policy(self) -> None:
        literal_documents = (
            '{"npm token":"punctuation !@#$%^&*() value"}',
            '{"token":{"value":"actual-secret-value"}}',
            '{"sentry/auth/token":{"value":"actual secret"}}',
            '{"api key":"actual-secret-value"}',
            '{"api/key":"actual-secret-value"}',
            '{"api_key":{"literal":"actual-secret-value"}}',
            '{"password":["actual-secret-value"]}',
            '"npm token" = "punctuation !@#$%^&*() value"\n',
            '"sentry/auth/token" = "actual secret"\n',
            'TOKEN = """${TOKEN}\nactual secret on a later line"""\n',
            "JWT_SECRET = '''public first line\nactual secret later'''\n",
        )
        public_documents = (
            '{"compare token":"public-control"}',
            'authorization_identity = "public-control"\n',
            'TOKEN = """${TOKEN}"""\n',
        )

        for document in literal_documents:
            with self.subTest(literal=document.splitlines()[0]):
                self.assertTrue(string_looks_like_credential(document))
        for document in public_documents:
            with self.subTest(public=document.splitlines()[0]):
                self.assertFalse(string_looks_like_credential(document))

    def test_yaml_scalar_forms_preserve_mapping_policy(self) -> None:
        literal_documents = (
            '"npm token": "punctuation !@#$%^&*() value"\n',
            '"api key": actual-secret-value\n',
            "api key: actual-secret-value\n",
            "'sentry/auth/token': 'it''s an actual secret'\n",
            "NPM_TOKEN: &credential punctuation !@#$%^&*() value\n",
            "JWT_SECRET: !!str punctuation !@#$%^&*() value\n",
            "WEBHOOK_SECRET: !<tag:yaml.org,2002:str> actual secret\n",
            '? "npm token"\n: "punctuation !@#$%^&*() value"\n',
            "TOKEN: *credential\n",
            "TOKEN: actual secret value\n",
            "TOKEN: actual[secret]\n",
            "TOKEN: 'actual''secret'\n",
            "? TOKEN\n: actual-secret\n",
        )
        public_documents = (
            "compare_token: public-control\n",
            "authorization_identity: public-control\n",
            "TOKEN: ${TOKEN}\n",
        )

        for document in literal_documents:
            with self.subTest(literal=document.splitlines()[0]):
                self.assertTrue(string_looks_like_credential(document))
        for document in public_documents:
            with self.subTest(public=document.splitlines()[0]):
                self.assertFalse(string_looks_like_credential(document))

    def test_yaml_block_scalars_scan_complete_content_and_header_variants(
        self,
    ) -> None:
        literal_documents = (
            "TOKEN: |-\n  ${TOKEN}\n  actual secret on a later line\n",
            "JWT_SECRET: >2+\n    public first line\n    actual secret later\n",
            "WEBHOOK_SECRET: |+2 # keep\n    first\n    second secret\n",
            '? "npm token"\n: >-\n  public first line\n  actual secret later\n',
            "TOKEN: |\n\n  actual-secret-value\n",
            "TOKEN: |2-\n    actual-secret-value\n",
            "TOKEN: | # comment\n  actual-secret-value\n",
            "TOKEN: &anchor |\n  actual-secret-value\n",
            "TOKEN: !!str |\n  actual-secret-value\n",
            "TOKEN: |\n  ${PREFIX}\n  actual-secret-value\n",
            "TOKEN: >-\n  ${PREFIX}\n  actual-secret-value\n",
        )
        public_documents = (
            "TOKEN: |\n  ${TOKEN}\n",
            "compare_token: >-\n  public control\n",
        )

        for document in literal_documents:
            with self.subTest(literal=document.splitlines()[0]):
                self.assertTrue(string_looks_like_credential(document))
        for document in public_documents:
            with self.subTest(public=document.splitlines()[0]):
                self.assertFalse(string_looks_like_credential(document))

    def test_source_annotations_are_not_cross_line_credential_assignments(self) -> None:
        public_sources = (
            "token: str\noption = None\n",
            "token:\n    option = parser.add_argument('--token')\n",
            "authorization:\n    identity = request.identity\n",
            "def configure(\n    token:\n        Option[str] = None,\n): ...\n",
            (
                "token = arguments[index]\n"
                'if "=" in token:\n'
                '    option, value = token.split("=", 1)\n'
            ),
            'os.environ, {"CONTEXT7_API_KEY": secret_value}, clear=False\n',
        )

        for source in public_sources:
            with self.subTest(source=source.splitlines()[0]):
                self.assertFalse(string_looks_like_credential(source))

    def test_cross_line_empty_assignments_do_not_consume_following_source_tokens(
        self,
    ) -> None:
        credential_field = "CONTEXT7_API_" + "KEY"
        aws_access_field = "AWS_ACCESS_KEY_" + "ID"
        aws_secret_field = "AWS_SECRET_ACCESS_" + "KEY"
        public_sources = (
            credential_field + "=\nEOF",
            "token=\n  shift",
            aws_access_field + "=\n" + aws_secret_field + "=\n",
        )

        for source in public_sources:
            with self.subTest(source=source):
                self.assertFalse(string_looks_like_credential(source))

    def test_privacy_scan_fails_closed_for_oversized_and_nul_files(self) -> None:
        credential = "gh" + "p_" + "A" * 36
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "oversized.txt").write_bytes(
                credential.encode("ascii") + b"x" * (4 * 1024 * 1024)
            )
            (root / "nul.txt").write_bytes(credential.encode("ascii") + b"\0public\n")

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
        self.assertIn(
            "oversized.txt:0: [oversized-public-file] review required",
            result.stdout,
        )
        self.assertIn("nul.txt:1: [provider-token] review required", result.stdout)
        self.assertNotIn(credential, result.stdout + result.stderr)

    def test_privacy_scan_scans_a_dot_git_file_but_prunes_dot_git_directories(
        self,
    ) -> None:
        credential = "gh" + "p_" + "A" * 36
        hidden_credential = "s" + "k-" + "B" * 24
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").write_text(credential + "\n", encoding="utf-8")
            metadata = root / "nested/.git"
            metadata.mkdir(parents=True)
            (metadata / "hidden.txt").write_text(
                hidden_credential + "\n",
                encoding="utf-8",
            )

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
            ".git:1: [provider-token] review required\n",
        )
        self.assertNotIn(credential, result.stdout + result.stderr)
        self.assertNotIn(hidden_credential, result.stdout + result.stderr)

    def test_privacy_scan_treats_an_exact_gitdir_pointer_as_git_metadata(self) -> None:
        gitdir_pointer = (
            "gitdir: /Users/" + "private-user/repository/.git/worktrees/fixture\n"
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").write_text(
                gitdir_pointer,
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/privacy-scan"),
                    "--root",
                    str(root),
                    "--denylist",
                    "-",
                ],
                check=False,
                capture_output=True,
                text=True,
                input="private-user\n",
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

        invalid_pointer = "gitdir: /Users/" + "private-user/not-a-worktree\n"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").write_text(invalid_pointer, encoding="utf-8")

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
        self.assertEqual(result.stdout, ".git:1: [user-home] review required\n")
        self.assertNotIn("private-user", result.stdout + result.stderr)

    def test_privacy_scan_rejects_a_missing_or_non_directory_root(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            roots = (base / "missing", base / "regular-file")
            roots[1].write_text("public\n", encoding="utf-8")

            for root in roots:
                with self.subTest(root=root.name):
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
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(result.stderr, "privacy scan failed\n")

    @unittest.skipIf(
        getattr(os, "geteuid", lambda: -1)() == 0,
        "root can read mode-zero paths",
    )
    def test_privacy_scan_fails_closed_for_unreadable_paths(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            unreadable_file_root = base / "file-root"
            unreadable_file_root.mkdir()
            unreadable_file = unreadable_file_root / "unreadable.txt"
            unreadable_file.write_text("public\n", encoding="utf-8")
            unreadable_file.chmod(0)
            try:
                file_result = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "scripts/privacy-scan"),
                        "--root",
                        str(unreadable_file_root),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            finally:
                unreadable_file.chmod(0o600)

            unreadable_tree_root = base / "tree-root"
            unreadable_tree_root.mkdir()
            unreadable_directory = unreadable_tree_root / "unreadable"
            unreadable_directory.mkdir()
            try:
                unreadable_directory.chmod(0)
                tree_result = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "scripts/privacy-scan"),
                        "--root",
                        str(unreadable_tree_root),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            finally:
                unreadable_directory.chmod(0o700)

        self.assertEqual(file_result.returncode, 1)
        self.assertEqual(
            file_result.stdout,
            "unreadable.txt:0: [unreadable-public-file] review required\n",
        )
        self.assertEqual(file_result.stderr, "")
        self.assertEqual(tree_result.returncode, 1)
        self.assertEqual(tree_result.stdout, "")
        self.assertEqual(tree_result.stderr, "privacy scan failed\n")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFOs require POSIX")
    def test_privacy_scan_rejects_a_fifo_without_blocking(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            os.mkfifo(root / "public.fifo")

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
                timeout=2,
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout,
            "public.fifo:0: [unreadable-public-file] review required\n",
        )
        self.assertEqual(result.stderr, "")

    def test_privacy_scan_uses_shared_private_key_markers_without_echoing_them(
        self,
    ) -> None:
        markers = private_key_markers()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "unsafe.pem").write_text(
                "\n".join(markers) + "\n",
                encoding="utf-8",
            )

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
                f"unsafe.pem:{line_number}: [private-key] review required"
                for line_number in range(1, len(markers) + 1)
            ],
        )
        self.assertTrue(all(marker not in result.stdout for marker in markers))

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
            set(result.stdout.splitlines()),
            {
                (
                    ".privacy-age-envelopes.json:0: "
                    "[invalid-age-envelope-manifest] review required"
                ),
                f"{redacted_path}:0: [invalid-age-envelope] review required",
                f"{redacted_path}:0: [provider-token-filename] review required",
            },
        )
        self.assertNotIn(credential, result.stdout)

    def test_privacy_scan_scans_mislabeled_age_files_and_accepts_age_envelopes(
        self,
    ) -> None:
        credential = provider_credentials()[0]
        native_age = (ROOT / "home/.private-prd-01.toml.age").read_bytes()
        armored_age = (ROOT / "home/.private-agents.md.age").read_bytes()
        header_only_spoof = (
            b"-----BEGIN AGE ENCRYPTED FILE-----\n"
            + base64.b64encode(b"age-encryption.org/v1\n")
            + b"\n-----END AGE ENCRYPTED FILE-----\n"
        )
        plausible_spoof = (
            b"age-encryption.org/v1\n"
            b"-> fixture recipient\n"
            b"--- fixture-tag\n" + credential.encode("utf-8") + b"\n"
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "mislabeled.age").write_text(credential + "\n", encoding="utf-8")
            (root / "native.age").write_bytes(native_age)
            (root / "armored.age").write_bytes(armored_age)
            (root / "spoof.age").write_bytes(header_only_spoof)
            (root / "plausible-spoof.age").write_bytes(plausible_spoof)
            write_age_manifest(
                root,
                [
                    "armored.age",
                    "mislabeled.age",
                    "native.age",
                    "plausible-spoof.age",
                    "spoof.age",
                ],
            )

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
                "mislabeled.age:0: [invalid-age-envelope] review required",
                "mislabeled.age:1: [provider-token] review required",
                "plausible-spoof.age:0: [invalid-age-envelope] review required",
                "plausible-spoof.age:4: [provider-token] review required",
                "spoof.age:0: [invalid-age-envelope] review required",
            ],
        )
        self.assertNotIn(credential, result.stdout)

    def test_privacy_scan_fails_closed_when_age_parser_is_unavailable(self) -> None:
        native_age = (ROOT / "home/.private-prd-01.toml.age").read_bytes()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ciphertext.age").write_bytes(native_age)
            write_age_manifest(root, ["ciphertext.age"])
            environment = os.environ.copy()
            environment["PATH"] = ""

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
                env=environment,
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout,
            "ciphertext.age:0: [age-parser-unavailable] review required\n",
        )

    def test_privacy_scan_fails_closed_when_age_parser_version_is_untrusted(
        self,
    ) -> None:
        native_age = (ROOT / "home/.private-prd-01.toml.age").read_bytes()
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repository"
            root.mkdir()
            (root / "ciphertext.age").write_bytes(native_age)
            write_age_manifest(root, ["ciphertext.age"])
            fake_bin = base / "bin"
            fake_bin.mkdir()
            parser = fake_bin / "age-inspect"
            parser.write_text(
                "#!/bin/sh\nprintf '%s\\n' v9.9.9\n",
                encoding="utf-8",
            )
            parser.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = os.fspath(fake_bin)

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
                env=environment,
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout,
            "ciphertext.age:0: [age-parser-unavailable] review required\n",
        )

    def test_privacy_scan_fails_closed_when_age_parser_times_out(self) -> None:
        native_age = (ROOT / "home/.private-prd-01.toml.age").read_bytes()
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repository"
            root.mkdir()
            (root / "ciphertext.age").write_bytes(native_age)
            write_age_manifest(root, ["ciphertext.age"])
            fake_bin = base / "bin"
            fake_bin.mkdir()
            parser = fake_bin / "age-inspect"
            parser.write_text(
                "#!/bin/sh\n"
                'if [ "$1" = --version ]; then\n'
                "  printf '%s\\n' v1.3.1\n"
                "  exit 0\n"
                "fi\n"
                "exec /bin/sleep 30\n",
                encoding="utf-8",
            )
            parser.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = os.fspath(fake_bin)

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
                env=environment,
                timeout=10,
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout,
            "ciphertext.age:0: [age-parser-unavailable] review required\n",
        )

    def test_privacy_scan_rejects_oversized_age_input_before_parsing(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "oversized.age").write_bytes(b"x" * (4 * 1024 * 1024 + 1))

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
            ".privacy-age-envelopes.json:0: "
            "[invalid-age-envelope-manifest] review required\n"
            "oversized.age:0: [invalid-age-envelope] review required\n",
        )

    def test_privacy_scan_redacts_other_sensitive_filename_families(self) -> None:
        private_email = "operator@" + "private.invalid.txt"
        private_mac = "aa:bb:cc:" + "dd:ee:ff.txt"
        sensitive_paths = {
            "private-machine-label.txt": "exact-denylist-filename",
            private_email: "email-filename",
            private_mac: "mac-address-filename",
            "x/home/private-user/artifact.txt": "user-home-filename",
        }
        with TemporaryDirectory() as directory, TemporaryDirectory() as private:
            root = Path(directory)
            denylist = Path(private) / "denylist"
            denylist.write_text("private-machine-label\n", encoding="utf-8")
            for relative in sensitive_paths:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("public contents\n", encoding="utf-8")

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

    def test_privacy_scan_scans_symlink_target_text_without_following_it(self) -> None:
        credential = provider_credentials()[0]
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "public-link").symlink_to("../" + credential)

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
            "public-link:0: [provider-token-symlink-target] review required\n",
        )
        self.assertNotIn(credential, result.stdout)


if __name__ == "__main__":
    unittest.main()
