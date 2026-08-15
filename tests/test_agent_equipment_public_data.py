from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.agent_equipment_public_data import (
    _javascript_lexical_index,
    _javascript_mappings_contain_literal_credential,
    _lex_javascript,
    contains_literal_credential,
    serialized_syntax,
    string_looks_like_credential,
    string_looks_like_private_key,
)
from tests.age_tooling_test_support import require_age_tooling_or_skip

ROOT = Path(__file__).resolve().parent.parent
PRIVACY_SCAN_TIMEOUT_SECONDS = 10


def run_privacy_scan(
    root: Path,
    *arguments: str,
    environment: dict[str, str] | None = None,
    input_text: str | None = None,
    timeout: float = PRIVACY_SCAN_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/privacy-scan"),
            "--root",
            str(root),
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        input=input_text,
        timeout=timeout,
    )


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
            "valid_checkpoint_record(authorization=apply_authorization,)",
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

            result = run_privacy_scan(root)

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

            result = run_privacy_scan(root)

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

            result = run_privacy_scan(root)

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

            result = run_privacy_scan(root)

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

            result = run_privacy_scan(root)

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

            result = run_privacy_scan(root)

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

            result = run_privacy_scan(root)

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

    def test_nested_serialized_mapping_pairs_preserve_credential_policy(
        self,
    ) -> None:
        field = "api" + "_key"
        literal = "production-value-" + "73918462"
        literal_documents = (
            'const config = {"' + field + '": "' + literal + '"};\n',
            "send({" + field + ': "' + literal + '"});\n',
            "config: {" + field + ": " + literal + "}\n",
            "items:\n  - " + field + ": " + literal + "\n",
            "items: [{" + field + ": " + literal + "}]\n",
            'const config = {"' + field + '":\n "' + literal + '"};\n',
            ("const config = {" + field + ': {literal: "' + literal + '"}};\n'),
            "const config = {" + field + ': ["' + literal + '"]};\n',
            ("config: {" + field + ": {literal: " + literal + "}}\n"),
            'const config = {"api\\x5fkey": "' + literal + '"};\n',
            'const config = {["api_" + "key"]: "' + literal + '"};\n',
            "const config = {" + field + ": ${TOKEN}-" + literal + "};\n",
            ("const config = {" + field + ': "${API_KEY}" + "-' + literal + '"};\n'),
            (
                "const config = {"
                + field
                + ': {"secret_profile_reference":"context7"} && "'
                + literal
                + '"};\n'
            ),
            "const config = {" + field + ": `" + literal + "`};\n",
            (
                "const config = `${JSON.stringify({"
                + field
                + ': "'
                + literal
                + '"})}`;\n'
            ),
            "const config = {/* c */ " + field + ': "' + literal + '"};\n',
            "const config = {" + field + ' /* c */: "' + literal + '"};\n',
            'const config = {_api_key: "' + literal + '"};\n',
            'const config = {$api_key: "' + literal + '"};\n',
            'const config = {[`api_key`]: "' + literal + '"};\n',
            'const config = {[("api_" + "key")]: "' + literal + '"};\n',
            'const config = {api\\u{5f}key: "' + literal + '"};\n',
            ('const quote=/"/; const config={' + field + ':"' + literal + '"};\n'),
            "const config = {" + field + ': String("' + literal + '")};\n',
            "const config = {" + field + ': lookup("' + literal + '")};\n',
            "config: {? " + field + " : " + literal + "}\n",
            "const config = {" + field + ": config.api_key};\n",
            "send({" + field + ": lookup()});\n",
            "const config = {" + field + ": lookup()};\n",
        )
        public_documents = (
            "const config = {" + field + ": ${API_KEY}};\n",
            "const config = {" + field + ": ${{ secrets.API_KEY }}};\n",
            "const config = {" + field + ": secret_profile:context7};\n",
            "const config = {" + field + ": secret_reference:TOKEN};\n",
            ("const config = {" + field + ": pass://fixture-vault/item/password};\n"),
            "const config = {" + field + ": __API_KEY__};\n",
            "const config = {token: str};\n",
            "const config = {token: false, password: null};\n",
            ('{"' + field + '": {"secret_profile_reference": "context7"}}\n'),
            (
                '{"' + field + '": {"secret_reference": "API_KEY", '
                '"template": "{reference}"}}\n'
            ),
            (
                "const config = {"
                + field
                + ': {secret_profile_reference: "context7"}};\n'
            ),
            (
                "config: {"
                + field
                + ': {secret_reference: API_KEY, template: "{reference}"}}\n'
            ),
            "const config = {" + field + ": process.env.API_KEY ?? fallback};\n",
            "const config = {" + field + ': process.env.API_KEY || ""};\n',
            "type Credentials = {" + field + ": string | undefined};\n",
            "type Credentials = {" + field + ": Option<string>};\n",
        )

        for document in literal_documents:
            with self.subTest(literal=document.splitlines()[0]):
                syntax = (
                    "yaml"
                    if document.startswith(("config:", "items:"))
                    else "javascript"
                )
                self.assertTrue(string_looks_like_credential(document, syntax=syntax))
        for document in public_documents:
            with self.subTest(public=document.splitlines()[0]):
                syntax = "yaml" if document.startswith("config:") else "javascript"
                self.assertFalse(string_looks_like_credential(document, syntax=syntax))

    def test_privacy_scan_rejects_nested_serialized_mapping_credentials(
        self,
    ) -> None:
        field = "api" + "_key"
        literal = "production-value-" + "73918462"
        documents = {
            "credential.js": ('const config = {"' + field + '": "' + literal + '"};\n'),
            "call.js": "send({" + field + ': "' + literal + '"});\n',
            "credential.yaml": "config: {" + field + ": " + literal + "}\n",
            "sequence.yaml": "items:\n  - " + field + ": " + literal + "\n",
            "flow-sequence.yaml": ("items: [{" + field + ": " + literal + "}]\n"),
            "cross-line.js": (
                'const config = {"' + field + '":\n "' + literal + '"};\n'
            ),
            "object.js": (
                "const config = {" + field + ': {literal: "' + literal + '"}};\n'
            ),
            "array.js": ("const config = {" + field + ': ["' + literal + '"]};\n'),
            "escaped-key.js": ('const config = {"api\\x5fkey": "' + literal + '"};\n'),
            "computed-key.js": (
                'const config = {["api_" + "key"]: "' + literal + '"};\n'
            ),
            "template.js": ("const config = {" + field + ": `" + literal + "`};\n"),
            "comment.js": (
                "const config = {/* c */ " + field + ': "' + literal + '"};\n'
            ),
            "literal-call.js": (
                "const config = {" + field + ': lookup("' + literal + '")};\n'
            ),
            "explicit-key.yaml": ("config: {? " + field + " : " + literal + "}\n"),
            "config.json.tmpl": (
                '{\n "config": {{ if .enabled }}{"'
                + field
                + '":"'
                + literal
                + '"}{{ end }}\n}\n'
            ),
            "settings.yaml.tmpl": (
                "config: {{ if .enabled }}{" + field + ": " + literal + "}{{ end }}\n"
            ),
            "settings.js.tmpl": (
                "const config = {{ if .enabled }}{"
                + field
                + ':"'
                + literal
                + '"}{{ end }};\n'
            ),
            "key-gap.js.tmpl": (
                "const config = {"
                + field
                + '{{/* public comment */}}:"'
                + literal
                + '"};\n'
            ),
            "key-gap.json.tmpl": (
                '{"' + field + '"{{- /* public comment */ -}}:"' + literal + '"}\n'
            ),
            "key-gap.yaml.tmpl": (
                "config: {" + field + "{{/* public comment */}}: " + literal + "}\n"
            ),
            "key-gap.toml.tmpl": (
                field + '{{/* public comment */}} = "' + literal + '"\n'
            ),
            "key-gap.js.j2": (
                "const config = {"
                + field
                + '{# public comment #}:"'
                + literal
                + '"};\n'
            ),
            "key-control.json.j2": (
                '{"'
                + field
                + '"{% if enabled %}:{% else %}:{% endif %}"'
                + literal
                + '"}\n'
            ),
            "generated-key.json.tmpl": ('{"{{ "api_key" }}":"' + literal + '"}\n'),
            "split-key.json.tmpl": ('{"api_{{ "key" }}":"' + literal + '"}\n'),
            "dynamic-key.json.tmpl": ('{"{{ .credentialKey }}":"' + literal + '"}\n'),
            "helper-key.json.tmpl": (
                '{"api_{{ printf "%s" "key" }}":"' + literal + '"}\n'
            ),
            "helper-key.yaml.tmpl": (
                'config: {api_{{ printf "%s" "key" }}: ' + literal + "}\n"
            ),
            "helper-key.toml.tmpl": (
                'api_{{ printf "%s" "key" }} = "' + literal + '"\n'
            ),
            "helper-key.js.tmpl": (
                'const config = {"api_{{ printf "%s" "key" }}":"' + literal + '"};\n'
            ),
            "wrapped.tmpl.json": (
                '{{ if .enabled }}{"' + field + '":"' + literal + '"}{{ end }}\n'
            ),
            "authorization.yaml": (
                "headers:\n  authorization: Token " + literal + "\n"
            ),
            "authorization.conf": "authorization = Token " + literal + "\n",
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, document in documents.items():
                (root / relative).write_text(document, encoding="utf-8")

            result = run_privacy_scan(root)

        self.assertEqual(result.returncode, 1)
        finding_paths = {line.split(":", 1)[0] for line in result.stdout.splitlines()}
        self.assertEqual(finding_paths, set(documents))
        self.assertTrue(
            all(
                "[provider-token] review required" in line
                for line in result.stdout.splitlines()
            )
        )
        self.assertNotIn(literal, result.stdout + result.stderr)

    def test_javascript_unresolved_computed_keys_fail_closed_for_credential_literals(
        self,
    ) -> None:
        literal = "production-value-" + "73918462"
        suspicious_documents = (
            ('const key = "api_key";\nconst config = {[key]: "' + literal + '"};\n'),
            (
                'const parts = ["api", "key"];\n'
                'const config = {[parts.join("_")]: "' + literal + '"};\n'
            ),
        )
        public_documents = (
            "const config = {[key]: process.env.API_KEY};\n",
            'const config = {[key]: "public"};\n',
            'const config = {["public_label"]: "' + literal + '"};\n',
        )

        for document in suspicious_documents:
            with self.subTest(suspicious=document.splitlines()[0]):
                self.assertTrue(
                    string_looks_like_credential(document, syntax="javascript")
                )
        for document in public_documents:
            with self.subTest(public=document):
                self.assertFalse(
                    string_looks_like_credential(document, syntax="javascript")
                )

    def test_path_specific_mapping_rules_fail_closed_without_rejecting_sources(
        self,
    ) -> None:
        field = "api" + "_key"
        authorization_field = "author" + "ization"
        literal = "production-value-" + "73918462"
        literal_javascript = (
            (
                "const config = {"
                + field
                + ': process.env.API_KEY\n + "-'
                + literal
                + '"};\n'
            ),
            "/* {" + field + ': "' + literal + '"} */\n',
            "// {" + field + ': "' + literal + '"}\n',
            ('const config = {["api_".concat("key")]: "' + literal + '"};\n'),
            "const config = {[String.raw`api_key`]: `" + literal + "`};\n",
            ('const config = {[`${"api_"}key`]: "' + literal + '"};\n'),
            ('const config = {[("api_" + // ]\n "key")]: "' + literal + '"};\n'),
            (
                'const config = {["a" + "p" + "i" + "_" + "k" + "e" + "y"]: "'
                + literal
                + '"};\n'
            ),
            (
                'const quote = () => /"/; const config = {'
                + field
                + ': "'
                + literal
                + '"};\n'
            ),
            (
                'function quote() { return /"/; } const config = {'
                + field
                + ': "'
                + literal
                + '"};\n'
            ),
            "const config = {" + field + ": Number(73918462)};\n",
            "const config = {" + field + ": lookup(productionValue)};\n",
            "const config = {" + field + ": (productionValue)};\n",
            "const config = {" + field + ": await lookup()};\n",
            "const config = {" + field + ": (lookup())};\n",
            (
                "const config = {"
                + field
                + ": process.env.API_KEY + productionValue};\n"
            ),
            (
                "const config = {"
                + field
                + ': process.env.API_KEY ?? "'
                + literal
                + '"};\n'
            ),
            (
                "const config = {"
                + field
                + ': `${process.env.API_KEY || "'
                + literal
                + '"}`};\n'
            ),
            (
                "let x=1,y=2; x++ / y; const config = {"
                + field
                + ':"'
                + literal
                + '"}; /z/.test("z");\n'
            ),
            'const config = {"\\141pi_key": "' + literal + '"};\n',
            "const config = {'\\141pi_key': '" + literal + "'};\n",
            "const config = {" + field + ': `${"' + literal + '"}`};\n',
            "const config = {" + field + ': `${String("' + literal + '")}`};\n',
            "const config = {" + field + ": `${73918462}`};\n",
            ("const config = {" + field + ' // comment\n : "' + literal + '"};\n'),
            (
                "const config = {"
                + field
                + ': pass://fixture-vault/item/password + "-'
                + literal
                + '"};\n'
            ),
            (
                "const config = {"
                + field
                + ': secret-service:// + "'
                + literal
                + '"};\n'
            ),
            (
                'const config = {["api_key" + '
                + " " * 5_000
                + ']: "'
                + literal
                + '"};\n'
            ),
            (
                'const production_value = "'
                + literal
                + '";\nconst config = {'
                + field
                + ": production_value};\n"
            ),
            (
                'const lookup = () => "'
                + literal
                + '";\nconst config = {'
                + field
                + ": lookup()};\n"
            ),
            ('const config = {[api > key ? "public" : "other"]: "' + literal + '"};\n'),
            "const config = {[api + key]: `" + literal + "`};\n",
        )
        public_javascript = (
            "const config = {" + field + ": (process.env.API_KEY)};\n",
            "const config = {" + field + ': process.env["API_KEY"]};\n',
            "const config = {" + field + ": process?.env?.API_KEY};\n",
            "const config = {" + field + ': getenv("API_KEY")};\n',
            "const config = {" + field + ": `${process.env.API_KEY}`};\n",
            "type Credentials = {" + field + "?: string};\n",
            "const config = {" + field + ': process.env["CONTEXT7_API_KEY"]};\n',
            "const config = {" + field + ': getenv("CONTEXT7_API_KEY")};\n',
            'const config = {token: process.env["GITHUB_TOKEN"]};\n',
            'const config = {password: Deno.env.get("DATABASE_PASSWORD")};\n',
            "const {" + field + ": key} = config;\n",
            "function use({" + field + ": credential}) {}\n",
            "const {config:{" + field + ":key}}=source;\n",
            "const {" + field + ": localKey}: Credentials = config;\n",
            "type C={" + field + ":string|null};\n",
            "type C={" + field + ":string[]};\n",
            "type C={" + field + ":Record<string,string>};\n",
            "type C={" + field + ":()=>string};\n",
            "type C={" + field + ':"public"|undefined};\n',
            "interface C {" + field + ": string}\n",
            (
                "const config = {"
                + field
                + ':{secret_profile_reference:"context7" // comment\n}};\n'
            ),
            'const source = "]:";\n',
            "const regex = /]:/;\n",
            '// ]: public\nconst source = "public";\n',
            'const header = "Authorization:Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}";\n',
            'const description = "api_key: supplied by the runtime";\n',
            (
                "const "
                + authorization_field
                + " = request.headers."
                + authorization_field
                + ";\n"
            ),
            (
                "const config = {"
                + authorization_field
                + ": request.headers."
                + authorization_field
                + "};\n"
            ),
            (
                "const config = {"
                + authorization_field
                + ": process.env.AUTHORIZATION};\n"
            ),
            (
                'const docs = "'
                + authorization_field
                + ": request.headers."
                + authorization_field
                + '";\n'
            ),
        )
        literal_yaml = (
            "config: {api key: " + literal + "}\n",
            "config: {api/key: " + literal + "}\n",
            "config: {npm token: " + literal + "}\n",
            "config: {" + field + ": lookup(" + literal + ")}\n",
            "config: {\n  " + field + ": " + literal + "\n}\n",
            "!!str " + field + ": " + literal + "\n",
            "&name " + field + ": " + literal + "\n",
            "config: {!!str " + field + ": " + literal + "}\n",
            "config: {&name " + field + ": " + literal + "}\n",
            "config: {" + field + ": $TOKEN\n  " + literal + "}\n",
            "config: {" + field + ": __API_KEY__\n  " + literal + "}\n",
        )
        public_yaml = (
            "config: {" + field + ": ${API_KEY}}\n",
            "config: {" + field + ": ~}\n",
            ("config: {" + field + ": {secret_profile_reference: context7}}\n"),
            ("config: {" + field + ': {"secret_profile_reference": context7}}\n'),
            (
                "config: {"
                + field
                + ': {"secret_reference": API_KEY, '
                + '"template": "{reference}"}}\n'
            ),
            (
                "config: {"
                + field
                + ": {\n secret_profile_reference: context7 # comment\n}}\n"
            ),
        )

        for document in literal_javascript:
            with self.subTest(literal_javascript=document.splitlines()[0]):
                self.assertTrue(
                    string_looks_like_credential(document, syntax="javascript")
                )
        for document in public_javascript:
            with self.subTest(public_javascript=document.splitlines()[0]):
                self.assertFalse(
                    string_looks_like_credential(document, syntax="javascript")
                )
        for document in literal_yaml:
            with self.subTest(literal_yaml=document.splitlines()[0]):
                self.assertTrue(string_looks_like_credential(document, syntax="yaml"))
        for document in public_yaml:
            with self.subTest(public_yaml=document.splitlines()[0]):
                self.assertFalse(string_looks_like_credential(document, syntax="yaml"))

    def test_path_specific_mapping_rules_have_bounded_nesting(self) -> None:
        javascript = "/* public */\n" * 1_200 + "[" * 4_000 + "]" * 4_000
        template = "`x${" * 1_100 + "source" + "}`" * 1_100
        wrapped_source = (
            "const config = {api_key: "
            + "(" * 4_000
            + "process.env.API_KEY"
            + ")" * 4_000
            + "};\n"
        )

        self.assertFalse(string_looks_like_credential(javascript, syntax="javascript"))
        self.assertFalse(string_looks_like_credential(template, syntax="javascript"))
        self.assertFalse(
            string_looks_like_credential(wrapped_source, syntax="javascript")
        )

    def test_javascript_source_symbols_require_whole_file_certificates(self) -> None:
        public_documents = (
            (
                'const description = "const process = fixture";\n'
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            ("// const Bun = fixture\nconst config = {api_key: Bun.env.API_KEY};\n"),
            (
                "const pattern = /function\\s+getenv\\(/;\n"
                'const config = {api_key: getenv("API_KEY")};\n'
            ),
            (
                "const fixture = {process: source};\n"
                "const config = {api_key: process.env.API_KEY};\n"
            ),
        )
        suspicious_documents = (
            (
                "function inspect() { process = fixture; }\n"
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            ("const config = {api_key: process.env.API_KEY};\nprocess = fixture;\n"),
            (
                "{ const process = fixture; use(process); }\n"
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            (
                "try { inspect(); } catch (process) { inspect(process); }\n"
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            (
                "for (const process of runtimes) { inspect(process); }\n"
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            (
                "const tools = { inspect(process) { return process; } };\n"
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            (
                "function inspect(process) { return process; }\n"
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            (
                "const process = fixture;\n"
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            ("function use(process) {\n  return {api_key: process.env.API_KEY};\n}\n"),
            ("process = fixture;\nconst config = {api_key: process.env.API_KEY};\n"),
            (
                "{\n"
                "  const process = fixture;\n"
                "  const config = {api_key: process.env.API_KEY};\n"
                "}\n"
            ),
            (
                "try { inspect(); } catch (process) {\n"
                "  const config = {api_key: process.env.API_KEY};\n"
                "}\n"
            ),
            (
                "for (const process of runtimes) {\n"
                "  const config = {api_key: process.env.API_KEY};\n"
                "}\n"
            ),
            (
                "const tools = {\n"
                "  inspect(process) {\n"
                "    return {api_key: process.env.API_KEY};\n"
                "  },\n"
                "};\n"
            ),
        )

        for document in public_documents:
            with self.subTest(public=document.splitlines()[0]):
                self.assertFalse(
                    string_looks_like_credential(document, syntax="javascript")
                )
        for document in suspicious_documents:
            with self.subTest(suspicious=document.splitlines()[0]):
                self.assertTrue(
                    string_looks_like_credential(document, syntax="javascript")
                )

    def test_javascript_binding_patterns_shadow_only_bound_names(self) -> None:
        public_documents = (
            (
                "const {process: localProcess} = runtime;\n"
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            (
                "const {getenv: localGetenv} = runtime;\n"
                'const config = {api_key: getenv("API_KEY")};\n'
            ),
            (
                'import type {process} from "./types.js";\n'
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            (
                'import {process as localProcess} from "./runtime.js";\n'
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            (
                "({process: localProcess} = runtime);\n"
                "const config = {api_key: process.env.API_KEY};\n"
            ),
        )
        suspicious_documents = (
            (
                "function inspect({process}) { return process; }\n"
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            (
                "const {process} = runtime;\n"
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            (
                "const {runtime: Bun} = source;\n"
                "const config = {api_key: Bun.env.API_KEY};\n"
            ),
            (
                "const [Deno] = runtimes;\n"
                'const config = {password: Deno.env.get("DATABASE_PASSWORD")};\n'
            ),
            (
                "const {...os} = runtime;\n"
                'const config = {password: os.env.get("DATABASE_PASSWORD")};\n'
            ),
            (
                "const {environment: getenv} = runtime;\n"
                'const config = {api_key: getenv("API_KEY")};\n'
            ),
            (
                "function use({process}) {\n"
                "  return {api_key: process.env.API_KEY};\n"
                "}\n"
            ),
            ("const use = ({Bun}) => ({api_key: Bun.env.API_KEY});\n"),
            (
                'import {runtime as getenv} from "./runtime.js";\n'
                'const config = {api_key: getenv("API_KEY")};\n'
            ),
            (
                "({runtime: process} = source);\n"
                "const config = {api_key: process.env.API_KEY};\n"
            ),
        )

        for document in public_documents:
            with self.subTest(public=document.splitlines()[0]):
                self.assertFalse(
                    string_looks_like_credential(document, syntax="javascript")
                )
        for document in suspicious_documents:
            with self.subTest(suspicious=document.splitlines()[0]):
                self.assertTrue(
                    string_looks_like_credential(document, syntax="javascript")
                )

    def test_javascript_nonvalue_colons_do_not_hide_runtime_mappings(self) -> None:
        literal = "production-value-" + "73918462"
        public_documents = (
            "const api_key: string = process.env.API_KEY;\n",
            "function use(api_key: CredentialSource) { return api_key; }\n",
            'const selected = ready ? api_key : "public";\n',
            "class Credentials { api_key: string; }\n",
            "type Credentials = {api_key: string};\n",
            "interface Credentials { api_key: string }\n",
            "const {api_key: localKey} = source;\n",
            (
                "function use({api_key: localKey}: "
                "{api_key: string}) { return localKey; }\n"
            ),
            'type Credentials = {["api_key"]: string};\n',
        )
        suspicious_documents = (
            'const config: Credentials = {api_key: "' + literal + '"};\n',
            ('const {fallback = {api_key: "' + literal + '"}} = source;\n'),
            (
                'function use({fallback = {api_key: "'
                + literal
                + '"}}) { return fallback; }\n'
            ),
            (
                "class Credentials {\n"
                '  load() { return {api_key: "' + literal + '"}; }\n'
                "}\n"
            ),
            'const config = {["api_key"]: "' + literal + '"};\n',
        )

        for document in public_documents:
            with self.subTest(public=document.splitlines()[0]):
                self.assertFalse(
                    string_looks_like_credential(document, syntax="javascript")
                )
        for document in suspicious_documents:
            with self.subTest(suspicious=document.splitlines()[0]):
                self.assertTrue(
                    string_looks_like_credential(document, syntax="javascript")
                )

    def test_javascript_source_certificates_fail_closed_on_ambiguous_code(
        self,
    ) -> None:
        literal = "production-value-" + "73918462"
        authorization_field = "author" + "ization"
        public_documents = (
            (
                "if (ready) /const process = fixture/.test(source)\n"
                "const config = {api_key: process.env.API_KEY}\n"
            ),
            (
                "while (ready) /let Bun = fixture/.test(source)\n"
                "const config = {api_key: Bun.env.API_KEY}\n"
            ),
            (
                "for (; ready;) /getenv = fixture/.test(source)\n"
                'const config = {api_key: getenv("API_KEY")}\n'
            ),
            (
                "let x = 1, y = 2; x++ / y;\n"
                "const config = {api_key: process.env.API_KEY}\n"
            ),
            (
                'import {process as localProcess} from "./runtime.js"\n'
                "const config = {api_key: process.env.API_KEY}\n"
            ),
            (
                "type Source = {api_key: string; nested: {password: string}}\n"
                "const config = {api_key: process.env.API_KEY}\n"
            ),
            (
                "const fixture = {process: source}; type Source = process;\n"
                'import {process as localProcess} from "./runtime.js";\n'
                "runtime.process;\n"
                "const config = {api_key: process.env.API_KEY}\n"
            ),
            ("runtime.eval(source);\nconst config = {api_key: process.env.API_KEY}\n"),
            "const config = {api_key: process.env.API_KEY ?? fallback}\n",
            (
                "const config = {"
                + authorization_field
                + ": request.headers."
                + authorization_field
                + "}\n"
            ),
        )
        suspicious_documents = (
            ("function use(process, options = {api_key: process.env.API_KEY}) {}\n"),
            (
                "function use(...process) {\n"
                "  return {api_key: process.env.API_KEY};\n"
                "}\n"
            ),
            (
                "const process: Runtime = fixture;\n"
                "const config = {api_key: process.env.API_KEY}\n"
            ),
            (
                "function use(process: Runtime) {}\n"
                "const config = {api_key: process.env.API_KEY}\n"
            ),
            (
                "type Source = {value: string}\n"
                'const config = {api_key: lookup("' + literal + '")}\n'
            ),
            (
                "const task = async function process() {};\n"
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            (
                'import {runtime as process} from "./runtime.js"\n'
                "const config = {api_key: process.env.API_KEY}\n"
            ),
            (
                "const fallback = source;\n"
                "const config = {api_key: process.env.API_KEY ?? fallback}\n"
            ),
            ('const config = {api_key: process.env.API_KEY ?? "' + literal + '"}\n'),
            ("use(process);\nconst config = {api_key: process.env.API_KEY}\n"),
            (
                "const selected = ready ? process : runtime;\n"
                "const config = {api_key: process.env.API_KEY}\n"
            ),
            ("process++;\nconst config = {api_key: process.env.API_KEY}\n"),
            ("function process() {}\nconst config = {api_key: process.env.API_KEY}\n"),
            ("class process {}\nconst config = {api_key: process.env.API_KEY}\n"),
            ("eval(source);\nconst config = {api_key: process.env.API_KEY}\n"),
            ("with (runtime) {}\nconst config = {api_key: process.env.API_KEY}\n"),
            ("Function(source);\nconst config = {api_key: process.env.API_KEY}\n"),
            "( const config = {api_key: process.env.API_KEY};\n",
            "const config = {api_key: process.env.API_KEY}; (\n",
            "} const config = {api_key: process.env.API_KEY};\n",
            (
                "const pro"
                "\\u0063"
                "ess = fixture;\n"
                "const config = {api_key: process.env.API_KEY}\n"
            ),
            (
                "const request = fixture;\n"
                "const config = {"
                + authorization_field
                + ": request.headers."
                + authorization_field
                + "}\n"
            ),
        )

        for document in public_documents:
            with self.subTest(public=document.splitlines()[0]):
                self.assertFalse(
                    string_looks_like_credential(document, syntax="javascript")
                )
        for document in suspicious_documents:
            with self.subTest(suspicious=document.splitlines()[0]):
                self.assertTrue(
                    string_looks_like_credential(document, syntax="javascript")
                )

    def test_javascript_typed_initializers_are_runtime_credential_sites(
        self,
    ) -> None:
        literal = "production-value-" + "73918462"
        suspicious_documents = (
            'const api_key: string = "' + literal + '";\n',
            'function use(api_key: string = "' + literal + '") {}\n',
            'class Source { api_key: string = "' + literal + '"; }\n',
            'class Source { api_key?: string = "' + literal + '"; }\n',
            'class Source { api_key!: string = "' + literal + '"; }\n',
            ('const {api_key: local = "' + literal + '"} = source;\n'),
            (
                "class Source {\n"
                "  field: string\n"
                '  load() { return {api_key: "' + literal + '"}; }\n'
                "}\n"
            ),
            ('type Source = string const config = {api_key: "' + literal + '"};\n'),
        )
        public_documents = (
            "const api_key: string = process.env.API_KEY;\n",
            "function use(api_key: string = process.env.API_KEY) {}\n",
            "class Source { api_key?: string = process.env.API_KEY; }\n",
            ('type Source = {api_key: "public"; nested: {password: string}}\n'),
        )

        for document in suspicious_documents:
            with self.subTest(suspicious=document.splitlines()[0]):
                self.assertTrue(
                    string_looks_like_credential(document, syntax="javascript")
                )
        for document in public_documents:
            with self.subTest(public=document.splitlines()[0]):
                self.assertFalse(
                    string_looks_like_credential(document, syntax="javascript")
                )

    def test_javascript_ambiguous_type_ranges_do_not_swallow_runtime_blocks(
        self,
    ) -> None:
        literal = "production-value-" + "73918462"
        runtime_mapping = '{api_key: "' + literal + '"}'
        suspicious_documents = (
            (
                "class Source { field: string [load]() { return "
                + runtime_mapping
                + "; } }\n"
            ),
            (
                "class Source { field: string static [load]() { return "
                + runtime_mapping
                + "; } }\n"
            ),
            (
                "class Source { field: string static load() { return "
                + runtime_mapping
                + "; } }\n"
            ),
            (
                "class Source { field: string static { const config = "
                + runtime_mapping
                + "; } }\n"
            ),
            *(
                "type Source = string "
                + boundary
                + " N { const config = "
                + runtime_mapping
                + "; }\n"
                for boundary in ("namespace", "enum", "module", "using", "xyz")
            ),
            ("type Source = string xyz { const config = " + runtime_mapping + "; }\n"),
            (
                "type Source = string namespace N { export const config = "
                + runtime_mapping
                + "; }\n"
            ),
            (
                "type Source = string module M { export const config = "
                + runtime_mapping
                + "; }\n"
            ),
            ('type Source = string enum E { api_key = "' + literal + '" }\n'),
            ("type Source = string using c = " + runtime_mapping + ";\n"),
        )
        public_documents = (
            "type Source = string & {nested: {password: string}};\n",
            (
                "type Source = string; namespace N { export const config = "
                "{api_key: process.env.API_KEY}; }\n"
            ),
            (
                "type Source = string; module M { export const config = "
                "{api_key: process.env.API_KEY}; }\n"
            ),
            "type Source = string; enum E { api_key = 0 }\n",
            ("type Source = string; using c = {api_key: process.env.API_KEY};\n"),
            (
                "type Factory = <T = string>() => T; "
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            (
                "class Source { field: string; static [load]() { return "
                "{api_key: process.env.API_KEY}; } }\n"
            ),
        )

        for document in suspicious_documents:
            with self.subTest(suspicious=document.splitlines()[0]):
                self.assertTrue(
                    string_looks_like_credential(document, syntax="javascript")
                )
        for document in public_documents:
            with self.subTest(public=document):
                self.assertFalse(
                    string_looks_like_credential(document, syntax="javascript")
                )

    def test_javascript_direct_assignment_members_use_bounded_literal_fallback(
        self,
    ) -> None:
        literal = "production-value-" + "73918462"
        suspicious_documents = (
            'type Source = string enum E { api_key = "' + literal + '" }\n',
            'enum E { api_key = "' + literal + '" }\n',
            'class E { api_key = "' + literal + '" }\n',
        )
        public_documents = (
            'enum E { api_key = "public" }\n',
            'class E { api_key = "short" }\n',
            "class E { static api_key = process.env.API_KEY }\n",
            "enum E { api_key = API_KEY }\n",
            ('type E<api_key = "production-value-73918462"> = api_key;\n'),
        )

        for document in suspicious_documents:
            with self.subTest(suspicious=document.splitlines()[0]):
                self.assertTrue(
                    string_looks_like_credential(document, syntax="javascript")
                )
        for document in public_documents:
            with self.subTest(public=document.splitlines()[0]):
                self.assertFalse(
                    string_looks_like_credential(document, syntax="javascript")
                )

    def test_javascript_bindable_source_shorthands_require_certificates(
        self,
    ) -> None:
        literal = "production-value-" + "73918462"
        names = (
            "str",
            "string",
            "object",
            "unknown",
            "int",
            "bool",
            "bytes",
            "list",
            "tuple",
            "any",
            "never",
            "float",
            "$API_KEY",
            "__API_KEY__",
            "undefined",
            "FALSE",
            "True",
            "NULL",
            "Undefined",
        )

        for name in names:
            with self.subTest(unbound=name):
                self.assertFalse(
                    string_looks_like_credential(
                        "const config = {api_key: " + name + "};\n",
                        syntax="javascript",
                    )
                )
            with self.subTest(bound=name):
                self.assertTrue(
                    string_looks_like_credential(
                        "const "
                        + name
                        + ' = "'
                        + literal
                        + '";\nconst config = {api_key: '
                        + name
                        + "};\n",
                        syntax="javascript",
                    )
                )
            with self.subTest(template_bound=name):
                self.assertTrue(
                    string_looks_like_credential(
                        "const "
                        + name
                        + ' = "'
                        + literal
                        + '";\nconst config = {api_key: `${'
                        + name
                        + "}`};\n",
                        syntax="javascript",
                    )
                )

        for literal_name in ("false", "null", "true"):
            with self.subTest(literal=literal_name):
                self.assertFalse(
                    string_looks_like_credential(
                        "const config = {api_key: " + literal_name + "};\n",
                        syntax="javascript",
                    )
                )

        self.assertTrue(
            string_looks_like_credential(
                'const undefined = "' + literal + '";\nconst config = {'
                "api_key: process.env.API_KEY ?? undefined};\n",
                syntax="javascript",
            )
        )

    def test_javascript_dynamic_intrinsics_invalidate_source_certificates(
        self,
    ) -> None:
        suspicious_prefixes = (
            "(0, eval)(source);\n",
            "(eval)(source);\n",
            "eval?.(source);\n",
            "globalThis.eval(source);\n",
            "const indirect = eval;\n",
            "Function.call(null, source);\n",
            "globalThis.Function(source);\n",
            "globalThis.process = makeRuntime(source);\n",
            "global.process = makeRuntime(source);\n",
            "window.process = makeRuntime(source);\n",
            "self.process = makeRuntime(source);\n",
            "this.process = makeRuntime(source);\n",
            "top.process = makeRuntime(source);\n",
            "parent.process = makeRuntime(source);\n",
            "frames.process = makeRuntime(source);\n",
            'this.eval("process = makeRuntime(source)");\n',
            'top.eval("process = makeRuntime(source)");\n',
            'setTimeout("process = makeRuntime(source)", 0);\n',
            'setTimeout(("process = makeRuntime(source)"), 0);\n',
            "setInterval(`process = makeRuntime(source)`, 1);\n",
            "setTimeout(`process = ${makeRuntime(source)}`, 0);\n",
            "setInterval(String.raw`process = ${makeRuntime(source)}`, 1);\n",
            "setTimeout((String.raw)`process = ${makeRuntime(source)}`, 0);\n",
            'setInterval(String["raw"]`process = ${makeRuntime(source)}`, 1);\n',
            "(setTimeout)(`process = ${makeRuntime(source)}`, 0);\n",
            "(0, setInterval)(String.raw`process = ${makeRuntime(source)}`, 1);\n",
            'setTimeout.call(null, "process = makeRuntime(source)", 0);\n',
            'setTimeout?.call(null, "process = makeRuntime(source)", 0);\n',
            'setInterval.apply(null, ["process = makeRuntime(source)", 1]);\n',
            '[].filter.constructor("process = makeRuntime(source)")();\n',
            '(async () => {}).constructor("process = makeRuntime(source)")();\n',
            '(runtime.constructor)("process = makeRuntime(source)")();\n',
            '(0, runtime.constructor)("process = makeRuntime(source)")();\n',
            'runtime.constructor.call(null, "process = makeRuntime(source)")();\n',
            'runtime.constructor?.call(null, "process = makeRuntime(source)")();\n',
            'Reflect.set(globalThis, "process", source);\n',
        )
        suffix = "const config = {api_key: process.env.API_KEY};\n"

        for prefix in suspicious_prefixes:
            with self.subTest(prefix=prefix.strip()):
                self.assertTrue(
                    string_looks_like_credential(
                        prefix + suffix,
                        syntax="javascript",
                    )
                )

        self.assertFalse(
            string_looks_like_credential(
                "runtime.eval(source);\n" + suffix,
                syntax="javascript",
            )
        )
        self.assertFalse(
            string_looks_like_credential(
                "setTimeout(callback, 0);\n"
                "setInterval?.(callback, 0);\n"
                "const descriptor = runtime.constructor;\n" + suffix,
                syntax="javascript",
            )
        )

    def test_javascript_dynamic_callable_references_normalize_static_members_and_aliases(
        self,
    ) -> None:
        suffix = "const config = {api_key: process.env.API_KEY};\n"
        suspicious_prefixes = (
            'setTimeout["call"](null, "process = makeRuntime(source)", 0);\n',
            'setInterval[`apply`](null, ["process = makeRuntime(source)", 1]);\n',
            'runtime["constructor"]("process = makeRuntime(source)")();\n',
            (
                'runtime["con" + "structor"]["call"]'
                '(null, "process = makeRuntime(source)")();\n'
            ),
            (
                'const C = [].filter["constructor"];\n'
                'C("process = makeRuntime(source)")();\n'
            ),
            (
                "const {constructor: C} = [].filter;\n"
                'C("process = makeRuntime(source)")();\n'
            ),
            (
                'const {["con" + "structor"]: C} = [].filter;\n'
                'C("process = makeRuntime(source)")();\n'
            ),
            '[setTimeout][0]("process = makeRuntime(source)", 0);\n',
            '[setTimeout, callback][0]("process = makeRuntime(source)", 0);\n',
            '([setInterval])[0]("process = makeRuntime(source)", 1);\n',
            (
                '[callback, runtime["constructor"]][1]'
                '("process = makeRuntime(source)")();\n'
            ),
            ('const timer = setTimeout;\ntimer("process = makeRuntime(source)", 0);\n'),
        )

        for prefix in suspicious_prefixes:
            with self.subTest(prefix=prefix.splitlines()[0]):
                self.assertTrue(
                    string_looks_like_credential(prefix + suffix, syntax="javascript")
                )

        public_prefixes = (
            'const descriptor = runtime["constructor"];\n',
            "const timer = setTimeout;\ntimer(callback, 0);\n",
            "[setTimeout][0](callback, 0);\n",
            '[setTimeout][1]("process = makeRuntime(source)", 0);\n',
            '[setTimeout]["00"]("process = makeRuntime(source)", 0);\n',
            '[callback, setTimeout][0]("process = makeRuntime(source)", 0);\n',
            "[runtime.constructor][0];\n",
        )
        for prefix in public_prefixes:
            with self.subTest(public=prefix.splitlines()[0]):
                self.assertFalse(
                    string_looks_like_credential(prefix + suffix, syntax="javascript")
                )

    def test_javascript_ambiguous_runtime_candidates_fail_closed(self) -> None:
        literal = "production-value-" + "73918462"
        documents = (
            (
                'const config = {api_key: /[)]/.test(value) ? "'
                + literal
                + '" : process.env.API_KEY};\n'
            ),
            (
                'const config = {api_key: /[}]/.test(value) ? "'
                + literal
                + '" : process.env.API_KEY};\n'
            ),
            (
                'const config = {api_key: /[(]/.test(value) ? "'
                + literal
                + '" : process.env.API_KEY};\n'
            ),
            ('const config = {broken ? marker, api_key: "' + literal + '"};\n'),
            ('const config = {broken ? api_key: "' + literal + '"};\n'),
            (
                'const config = {broken ? /* unresolved */ api_key: "'
                + literal
                + '"};\n'
            ),
        )

        for document in documents:
            with self.subTest(document=document.splitlines()[0]):
                self.assertTrue(
                    string_looks_like_credential(document, syntax="javascript")
                )

    def test_malformed_javascript_declaration_work_is_linear(self) -> None:
        small = _javascript_lexical_index("const value " * 512).work_units
        large = _javascript_lexical_index("const value " * 1024).work_units

        self.assertLessEqual(large, small * 3)

        small_types = _javascript_lexical_index("type T = string " * 512)
        large_types = _javascript_lexical_index("type T = string " * 1024)

        self.assertFalse(small_types.analysis_exhausted)
        self.assertFalse(large_types.analysis_exhausted)
        self.assertLessEqual(large_types.work_units, small_types.work_units * 3)

        exhausted = _javascript_lexical_index(
            "type T = string;",
            work_budget=0,
        )
        self.assertTrue(exhausted.analysis_exhausted)
        self.assertTrue(
            _javascript_mappings_contain_literal_credential(
                "const config = {api_key: process.env.API_KEY};",
                work_budget=0,
            )
        )

        callable_small = _javascript_lexical_index("x(): T " * 256)
        callable_large = _javascript_lexical_index("x(): T " * 512)
        self.assertTrue(callable_small.analysis_exhausted)
        self.assertTrue(callable_large.analysis_exhausted)
        self.assertLessEqual(callable_large.work_units, callable_small.work_units * 3)
        self.assertTrue(
            _javascript_mappings_contain_literal_credential(
                "x(): T " * 512 + "const config = {api_key: process.env.API_KEY};\n"
            )
        )

        for fragment in ("function f ", "class C ", "interface I ", "import x "):
            with self.subTest(fragment=fragment.strip()):
                family_small = _javascript_lexical_index(fragment * 256)
                family_large = _javascript_lexical_index(fragment * 512)
                self.assertLessEqual(
                    family_large.work_units,
                    family_small.work_units * 3,
                )

    def test_unterminated_template_opaque_spans_remain_ordered(self) -> None:
        _, opaque_spans, _ = _lex_javascript(
            '`outer ${ `inner ${ "production-value-73918462"'
        )

        self.assertEqual(
            opaque_spans,
            tuple(sorted(opaque_spans, key=lambda span: (span[0], span[1]))),
        )

    def test_template_output_actions_fail_closed_in_credential_context(self) -> None:
        literal = "production-value-" + "73918462"
        documents = (
            (
                'const config = {api_key: {{ printf "%q" "' + literal + '" }}};\n',
                "javascript-template",
            ),
            (
                '{"api_key": {{ printf "%q" "' + literal + '" }}}\n',
                "template",
            ),
        )
        public_documents = (
            ("{{/* public comment */}}\n", "template"),
            ("{{ if .enabled }}public{{ end }}\n", "template"),
            (
                "const config = {api_key: {{ .CredentialReference }}};\n",
                "javascript-template",
            ),
        )

        for document, syntax in documents:
            with self.subTest(syntax=syntax):
                self.assertTrue(string_looks_like_credential(document, syntax=syntax))
        for document, syntax in public_documents:
            with self.subTest(public=syntax):
                self.assertFalse(string_looks_like_credential(document, syntax=syntax))

    def test_template_local_binding_outputs_do_not_receive_source_certificates(
        self,
    ) -> None:
        literal = "production-value-" + "73918462"
        documents = (
            (
                '{{ $secret := "' + literal + '" }}\n{"api_key":"{{ $secret }}"}\n',
                "template",
            ),
            (
                '{{ $secret = "' + literal + '" }}\n'
                "const config = {api_key: {{ $secret }}};\n",
                "javascript-template",
            ),
            (
                '{% set secret = "' + literal + '" %}\n'
                "config: {api_key: {{ secret }}}\n",
                "yaml-template",
            ),
            (
                '{% set secret = "' + literal + '" %}\napi_key = "{{ secret }}"\n',
                "toml-template",
            ),
        )
        public_documents = (
            '{"api_key":"{{ .CredentialReference }}"}\n',
            '{"api_key":"{{ $CredentialReference }}"}\n',
            '{"api_key":"{{ credential_reference }}"}\n',
            (
                "{{ $class := .dataClass }}\n"
                '{"{{ $class }}_memory_enabled": {{ $class }}}\n'
            ),
        )

        for document, syntax in documents:
            with self.subTest(syntax=syntax):
                self.assertTrue(string_looks_like_credential(document, syntax=syntax))
        for document in public_documents:
            with self.subTest(public=document):
                self.assertFalse(
                    string_looks_like_credential(document, syntax="template")
                )

    def test_template_output_actions_fail_closed_in_credential_keys(self) -> None:
        literal = "production-value-" + "73918462"
        documents = (
            (
                '{"api_{{ printf "%s" "key" }}":"' + literal + '"}\n',
                "template",
            ),
            (
                'const config = {"api_{{ printf "%s" "key" }}":"' + literal + '"};\n',
                "javascript-template",
            ),
            (
                'config: {api_{{ printf "%s" "key" }}: ' + literal + "}\n",
                "yaml-template",
            ),
            (
                'api_{{ printf "%s" "key" }} = "' + literal + '"\n',
                "toml-template",
            ),
        )

        for document, syntax in documents:
            with self.subTest(syntax=syntax):
                self.assertTrue(string_looks_like_credential(document, syntax=syntax))

    def test_template_control_flow_cannot_concatenate_credential_key_branches(
        self,
    ) -> None:
        literal = "production-value-" + "73918462"
        documents = (
            (
                '{"api_{{ if .key }}key{{ else }}secret{{ end }}":"' + literal + '"}\n',
                "template",
            ),
            (
                'const config = {"{{if .key}}api_key{{else}}password{{end}}":"'
                + literal
                + '"};\n',
                "javascript-template",
            ),
            (
                'config: {"'
                '{{if .key}}api_key{{else}}password{{end}}": ' + literal + "}\n",
                "yaml-template",
            ),
            (
                'api_{{ if .key }}key{{ else }}secret{{ end }} = "' + literal + '"\n',
                "toml-template",
            ),
        )

        for document, syntax in documents:
            with self.subTest(syntax=syntax):
                self.assertTrue(string_looks_like_credential(document, syntax=syntax))

        self.assertFalse(
            string_looks_like_credential(
                "label: {{ if .enabled }}public{{ else }}reference{{ end }}\n",
                syntax="yaml-template",
            )
        )

    def test_privacy_scan_serialized_syntax_table_is_explicit(self) -> None:
        cases = {
            "source.js": "javascript",
            "source.json": None,
            "source.jsx": "javascript-conservative",
            "source.ts": "javascript",
            "source.tsx": "javascript-conservative",
            "source.js.tmpl": "javascript-template",
            "source.tsx.tmpl": "javascript-conservative-template",
            "source.yaml": "yaml",
            "source.yaml.j2": "yaml-template",
            "source.toml": None,
            "source.toml.tpl": "toml-template",
            "source.tmpl": "template",
            "source.txt": None,
        }
        for relative, expected in cases.items():
            with self.subTest(relative=relative):
                self.assertEqual(serialized_syntax(relative), expected)

        literal = "production-value-" + "73918462"
        self.assertTrue(
            string_looks_like_credential(
                'const node = <Box></Box>;\nconst config = {api_key: "'
                + literal
                + '"};\n',
                syntax="javascript-conservative",
            )
        )
        self.assertTrue(
            string_looks_like_credential(
                'const config = {api_key: {{ printf "%q" "' + literal + '" }}};\n',
                syntax="javascript-conservative-template",
            )
        )

    def test_privacy_scan_routes_syntax_aware_files_fail_closed(self) -> None:
        literal = "production-value-" + "73918462"
        documents = {
            "closing.tsx": (
                '<Box></Box>;\nconst config = {api_key: "' + literal + '"};\n'
            ),
            "closing.jsx": (
                '<Box></Box>;\nconst config = {api_key: "' + literal + '"};\n'
            ),
            "helper.js.tmpl": (
                'const config = {api_key: {{ printf "%q" "' + literal + '" }}};\n'
            ),
            "helper.json.tmpl": ('{"api_key": {{ printf "%q" "' + literal + '" }}}\n'),
            "helper.tmpl": ('{"api_key": {{ printf "%q" "' + literal + '" }}}\n'),
            "bound-helper.json.tmpl": (
                '{{ $secret := "' + literal + '" }}\n{"api_key":"{{ $secret }}"}\n'
            ),
            "branch-key.json.tmpl": (
                '{"api_{{ if .key }}key{{ else }}secret{{ end }}":"' + literal + '"}\n'
            ),
            "regex.ts": (
                'const config = {api_key: /[)]/.test(value) ? "'
                + literal
                + '" : process.env.API_KEY};\n'
            ),
            "literal.ts": 'const config = {api_key: "' + literal + '"};\n',
            "class-field.ts": (
                "class Source {\n"
                "  field: string\n"
                '  load() { return {api_key: "' + literal + '"}; }\n'
                "}\n"
            ),
            "same-line-computed-method.ts": (
                'class Source { field: string [load]() { return {api_key: "'
                + literal
                + '"}; } }\n'
            ),
            "malformed-type.ts": (
                'type Source = string const config = {api_key: "' + literal + '"};\n'
            ),
            "unknown-type-block.ts": (
                'type Source = string namespace N { const config = {api_key: "'
                + literal
                + '"}; }\n'
            ),
            "unterminated-using.ts": (
                'type Source = string using c = {api_key: "' + literal + '"};\n'
            ),
            "direct-assignment-class.ts": ('class E { api_key = "' + literal + '" }\n'),
            "direct-assignment-enum.ts": ('enum E { api_key = "' + literal + '" }\n'),
            "malformed-ternary.ts": (
                'const config = {broken ? api_key: "' + literal + '"};\n'
            ),
            "dynamic-global.ts": (
                "this.process = makeRuntime(source);\n"
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            "string-code.ts": (
                "(setTimeout)(`process = ${makeRuntime(source)}`, 0);\n"
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            "string-raw-code.ts": (
                'setInterval(String["raw"]`process = ${makeRuntime(source)}`, 1);\n'
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            "string-wrapped-raw-code.ts": (
                "setTimeout((String.raw)`process = ${makeRuntime(source)}`, 0);\n"
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            "constructor-code.ts": (
                '(0, [].filter.constructor)("process = makeRuntime(source)")();\n'
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            "computed-constructor-code.ts": (
                'runtime["constructor"]["call"]'
                '(null, "process = makeRuntime(source)")();\n'
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            "container-call.ts": (
                '[setTimeout][0]("process = makeRuntime(source)", 0);\n'
                "const config = {api_key: process.env.API_KEY};\n"
            ),
            "computed-local-key.ts": (
                'const key = "api_key";\nconst config = {[key]: "' + literal + '"};\n'
            ),
            "types.ts": "interface Credentials {\n  api_key: CredentialSource\n}\n",
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, document in documents.items():
                (root / relative).write_text(document, encoding="utf-8")
            result = run_privacy_scan(root)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            set(result.stdout.splitlines()),
            {
                f"{relative}:0: [provider-token] review required"
                for relative in documents
                if relative != "types.ts"
            },
        )
        self.assertNotIn(literal, result.stdout + result.stderr)

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

            result = run_privacy_scan(root)

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

            result = run_privacy_scan(root)

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

            result = run_privacy_scan(
                root,
                "--denylist",
                "-",
                input_text="private-user\n",
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

        invalid_pointer = "gitdir: /Users/" + "private-user/not-a-worktree\n"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").write_text(invalid_pointer, encoding="utf-8")

            result = run_privacy_scan(root)

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
                    result = run_privacy_scan(root)
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
                file_result = run_privacy_scan(unreadable_file_root)
            finally:
                unreadable_file.chmod(0o600)

            unreadable_tree_root = base / "tree-root"
            unreadable_tree_root.mkdir()
            unreadable_directory = unreadable_tree_root / "unreadable"
            unreadable_directory.mkdir()
            try:
                unreadable_directory.chmod(0)
                tree_result = run_privacy_scan(unreadable_tree_root)
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

            result = run_privacy_scan(root, timeout=2)

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

            result = run_privacy_scan(root)

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

            result = run_privacy_scan(root)

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
        if shutil.which("age-inspect") is None:
            require_age_tooling_or_skip("age-inspect is unavailable")
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

            result = run_privacy_scan(root)

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

            result = run_privacy_scan(root, environment=environment)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout,
            "ciphertext.age:0: [age-parser-unavailable] review required\n",
        )

    def test_privacy_scan_prefers_the_configured_age_tooling_directory(self) -> None:
        native_age = (ROOT / "home/.private-prd-01.toml.age").read_bytes()
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repository"
            root.mkdir()
            (root / "ciphertext.age").write_bytes(native_age)
            write_age_manifest(root, ["ciphertext.age"])
            tooling = base / "trusted-age-bin"
            tooling.mkdir()
            parser = tooling / "age-inspect"
            parser.write_text(
                "#!/bin/sh\n"
                'if [ "$1" = --version ]; then\n'
                "  printf '%s\\n' v1.3.1\n"
                "  exit 0\n"
                "fi\n"
                "/bin/cat >/dev/null\n"
                "printf '%s\\n' "
                '\'{"version":"age-encryption.org/v1",'
                '"postquantum":"yes","armor":false,'
                '"stanza_types":["mlkem768x25519"],'
                '"sizes":{"header":1,"armor":0,"overhead":1,'
                '"min_payload":1,"max_payload":1,"min_padding":0,'
                '"max_padding":0}}\'\n',
                encoding="utf-8",
            )
            parser.chmod(0o755)
            ambient = base / "ambient-bin"
            ambient.mkdir()
            ambient_parser = ambient / "age-inspect"
            ambient_parser.write_text(
                "#!/bin/sh\nprintf '%s\\n' v9.9.9\n",
                encoding="utf-8",
            )
            ambient_parser.chmod(0o755)
            environment = os.environ.copy()
            environment["AGE_TOOLING_DIRECTORY"] = os.fspath(tooling)
            environment["PATH"] = os.fspath(ambient)

            result = run_privacy_scan(root, environment=environment)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_privacy_scan_checks_the_age_parser_version_once_per_scan(self) -> None:
        native_age = (ROOT / "home/.private-prd-01.toml.age").read_bytes()
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repository"
            root.mkdir()
            for relative in ("first.age", "second.age"):
                (root / relative).write_bytes(native_age)
            write_age_manifest(root, ["first.age", "second.age"])
            fake_bin = base / "bin"
            fake_bin.mkdir()
            parser_log = base / "age-inspect.log"
            parser = fake_bin / "age-inspect"
            parser.write_text(
                "#!/bin/sh\n"
                'printf \'%s\\n\' "$1" >> "$AGE_INSPECT_LOG"\n'
                'if [ "$1" = --version ]; then\n'
                "  printf '%s\\n' v1.3.1\n"
                "  exit 0\n"
                "fi\n"
                "/bin/cat >/dev/null\n"
                "printf '%s\\n' "
                '\'{"version":"age-encryption.org/v1",'
                '"postquantum":"yes","armor":false,'
                '"stanza_types":["mlkem768x25519"],'
                '"sizes":{"header":1,"armor":0,"overhead":1,'
                '"min_payload":1,"max_payload":1,"min_padding":0,'
                '"max_padding":0}}\'\n',
                encoding="utf-8",
            )
            parser.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = os.fspath(fake_bin)
            environment["AGE_INSPECT_LOG"] = os.fspath(parser_log)

            result = run_privacy_scan(root, environment=environment)
            parser_invocations = parser_log.read_text(encoding="utf-8").splitlines()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            parser_invocations,
            ["--version", "--json", "--json"],
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

            result = run_privacy_scan(root, environment=environment)

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

            result = run_privacy_scan(root, environment=environment)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout,
            "ciphertext.age:0: [age-parser-unavailable] review required\n",
        )

    def test_privacy_scan_rejects_oversized_age_input_before_parsing(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "oversized.age").write_bytes(b"x" * (4 * 1024 * 1024 + 1))

            result = run_privacy_scan(root)

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

            result = run_privacy_scan(
                root,
                "--denylist",
                str(denylist),
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

    def test_privacy_scan_scales_large_casefolded_exact_denylist_matching(
        self,
    ) -> None:
        matching_term = "private-machine-label"
        unrelated_terms = [
            f"unrelated-private-term-{index:05d}-" + "x" * 32 for index in range(9_999)
        ]
        public_lines = [f"public content line {index:06d}" for index in range(100_000)]
        with TemporaryDirectory() as directory, TemporaryDirectory() as private:
            root = Path(directory)
            denylist = Path(private) / "denylist"
            denylist.write_text(
                "\n".join((*unrelated_terms, matching_term)) + "\n",
                encoding="utf-8",
            )
            (root / "public.txt").write_text(
                "\n".join((*public_lines, f"prefix {matching_term.upper()} suffix"))
                + "\n",
                encoding="utf-8",
            )

            result = run_privacy_scan(
                root,
                "--denylist",
                str(denylist),
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout,
            "public.txt:100001: [exact-denylist] review required\n",
        )

    def test_privacy_scan_does_not_follow_file_symlinks_outside_the_root(self) -> None:
        credential = provider_credentials()[0]
        with TemporaryDirectory() as root_directory, TemporaryDirectory() as outside:
            root = Path(root_directory)
            target = Path(outside) / "outside.txt"
            target.write_text(credential + "\n", encoding="utf-8")
            (root / "public-link").symlink_to(target)

            result = run_privacy_scan(root)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_privacy_scan_scans_symlink_target_text_without_following_it(self) -> None:
        credential = provider_credentials()[0]
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "public-link").symlink_to("../" + credential)

            result = run_privacy_scan(root)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout,
            "public-link:0: [provider-token-symlink-target] review required\n",
        )
        self.assertNotIn(credential, result.stdout)


if __name__ == "__main__":
    unittest.main()
