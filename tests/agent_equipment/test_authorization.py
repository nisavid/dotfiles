from __future__ import annotations

import copy
import os
import stat
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_equipment.authorization import (
    MAX_APPLY_AUTHORIZATION_BYTES,
    ApplyAuthorizationGate,
    ApplyAuthorizationTrust,
    AuthorizationLedger,
    AuthorizationLedgerClaim,
    AuthorizationLedgerClaimStatus,
    AuthorizationRejection,
    ClaimedApplyAuthorization,
    FileAuthorizationLedger,
    TrustedExecutionDomain,
    authorization_ledger_claim_identity,
)
from agent_equipment.canonical import (
    canonical_json_bytes,
    canonical_json_sha256,
    strict_load_json_bytes,
)
from agent_equipment.model import FrozenJsonObject, freeze_json, thaw_json


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _valid_authorization() -> tuple[dict[str, object], str]:
    bindings = {
        "candidate_identity": "candidate:fixture/controller-v1",
        "implementation_manifest_digest": _digest("1"),
        "catalog_digest": _digest("2"),
        "lock_digest": _digest("3"),
        "plan_digest": _digest("4"),
        "plan_action_set_digest": _digest("5"),
        "prepared_action_authority_set_identity": (
            "prepared-action-authority-set:sha256:" + "6" * 64
        ),
        "prepared_action_authority_set_digest": _digest("7"),
        "capability_set_digest": _digest("8"),
        "captured_state_identity": "capture:fixture/run-v1",
        "captured_state_digest": _digest("9"),
        "capture_observation_authority_set_identity": (
            "capture-observation-authority-set:sha256:" + "a" * 64
        ),
        "capture_observation_authority_set_digest": _digest("b"),
        "expected_case_manifest_digest": _digest("c"),
        "operator_review_package_digest": _digest("d"),
    }
    document: dict[str, object] = {
        "schema_version": "agent-equipment-apply-authorization/v1",
        "authorization_identity": "",
        "issuer_identity": "authority:fixture/operator",
        "issued_at": "2026-08-13T07:00:00Z",
        "not_before": "2026-08-13T07:00:00Z",
        "expires_at": "2026-08-13T08:00:00Z",
        "execution_nonce": "execution-nonce:sha256:" + "e" * 64,
        "run_identity": "run:sha256:" + "f" * 64,
        "execution_domain_identity": ("execution-domain:fixture/global-ledger-v1"),
        "command": "apply",
        "bindings": bindings,
    }
    return document, _seal(document)


def _seal(document: dict[str, object]) -> str:
    identity_payload = copy.deepcopy(document)
    identity_payload.pop("authorization_identity")
    document["authorization_identity"] = "apply-authorization:" + canonical_json_sha256(
        identity_payload
    )
    return canonical_json_sha256(document)


def _trust(
    document: dict[str, object], authorization_digest: str
) -> ApplyAuthorizationTrust:
    bindings = freeze_json(document["bindings"])
    assert isinstance(bindings, FrozenJsonObject)
    return ApplyAuthorizationTrust(
        expected_candidate_identity=str(bindings["candidate_identity"]),
        expected_implementation_manifest_digest=str(
            bindings["implementation_manifest_digest"]
        ),
        expected_authorization_identity=str(document["authorization_identity"]),
        expected_authorization_digest=authorization_digest,
        expected_execution_domain_identity=str(document["execution_domain_identity"]),
        expected_execution_nonce=str(document["execution_nonce"]),
        expected_run_identity=str(document["run_identity"]),
        expected_operator_review_package_digest=str(
            bindings["operator_review_package_digest"]
        ),
        expected_issuer_identity=str(document["issuer_identity"]),
        trusted_now=datetime(2026, 8, 13, 7, 30, tzinfo=timezone.utc),
        expected_bindings=bindings,
    )


class _RecordingLedger:
    def __init__(
        self,
        status: AuthorizationLedgerClaimStatus = (
            AuthorizationLedgerClaimStatus.DURABLE
        ),
    ) -> None:
        self.status = status
        self.claims: list[AuthorizationLedgerClaim] = []

    def claim(self, claim: AuthorizationLedgerClaim) -> AuthorizationLedgerClaimStatus:
        self.claims.append(claim)
        return self.status


def _authorize(
    raw_authorization: bytes,
    trust: ApplyAuthorizationTrust,
    ledger: AuthorizationLedger,
) -> object:
    gate = ApplyAuthorizationGate(
        TrustedExecutionDomain(
            identity=trust.expected_execution_domain_identity,
            authorization_ledger=ledger,
        )
    )
    return gate.authorize_apply_start(raw_authorization, trust)


class ApplyAuthorizationTest(unittest.TestCase):
    def _file_ledger(self, root: Path) -> FileAuthorizationLedger:
        ledger = FileAuthorizationLedger(root)
        self.addCleanup(ledger.close)
        return ledger

    def test_ledger_claim_identity_matches_the_independent_design_golden(
        self,
    ) -> None:
        self.assertEqual(
            authorization_ledger_claim_identity(
                "execution-domain:fixture/global-ledger-v1",
                "execution-nonce:sha256:" + "2" * 64,
            ),
            "authorization-ledger-claim:sha256:"
            "9e9791ab1c9634b4c9740924bf7370ce1418ab20e1a9666656e8c43ad2c36ebd",
        )

    def test_valid_authorization_is_claimed_once_after_complete_validation(
        self,
    ) -> None:
        document, authorization_digest = _valid_authorization()
        ledger = _RecordingLedger()
        gate = ApplyAuthorizationGate(
            TrustedExecutionDomain(
                identity=str(document["execution_domain_identity"]),
                authorization_ledger=ledger,
            )
        )

        result = gate.authorize_apply_start(
            canonical_json_bytes(document),
            _trust(document, authorization_digest),
        )

        self.assertIsInstance(result, ClaimedApplyAuthorization)
        assert isinstance(result, ClaimedApplyAuthorization)
        self.assertEqual(result.authorization, freeze_json(document))
        self.assertEqual(result.authorization_digest, authorization_digest)
        self.assertEqual(len(ledger.claims), 1)
        self.assertEqual(result.claim_identity, ledger.claims[0].claim_identity)
        self.assertEqual(
            ledger.claims[0].as_json(),
            freeze_json(
                {
                    "schema_version": ("agent-equipment-authorization-ledger-claim/v1"),
                    "claim_identity": result.claim_identity,
                    "apply_authorization_identity": document["authorization_identity"],
                    "apply_authorization_digest": authorization_digest,
                    "execution_domain_identity": document["execution_domain_identity"],
                    "execution_nonce": document["execution_nonce"],
                    "run_identity": document["run_identity"],
                }
            ),
        )

    def test_oversized_raw_input_is_rejected_before_all_other_work(
        self,
    ) -> None:
        document, authorization_digest = _valid_authorization()
        ledger = _RecordingLedger()

        with (
            patch("agent_equipment.authorization.strict_load_json_bytes") as parse_json,
            patch("agent_equipment.authorization.validate_document") as validate_schema,
            patch(
                "agent_equipment.authorization.contains_literal_credential"
            ) as scan_secrets,
            patch(
                "agent_equipment.authorization.canonical_json_sha256"
            ) as hash_document,
        ):
            result = _authorize(
                b"x" * (MAX_APPLY_AUTHORIZATION_BYTES + 1),
                _trust(document, authorization_digest),
                ledger,
            )

        self.assertIsInstance(result, AuthorizationRejection)
        assert isinstance(result, AuthorizationRejection)
        self.assertEqual(
            [diagnostic.code for diagnostic in result.diagnostics],
            ["EXECUTION_AUTHORITY_BYTES_INVALID"],
        )
        parse_json.assert_not_called()
        validate_schema.assert_not_called()
        scan_secrets.assert_not_called()
        hash_document.assert_not_called()
        self.assertEqual(ledger.claims, [])

    def test_only_exact_bytes_cross_the_raw_authorization_boundary(
        self,
    ) -> None:
        class BytesSubclass(bytes):
            pass

        document, authorization_digest = _valid_authorization()
        ledger = _RecordingLedger()
        for raw in (
            "{}",
            bytearray(b"{}"),
            memoryview(b"{}"),
            BytesSubclass(b"{}"),
        ):
            with self.subTest(raw_type=type(raw).__name__):
                result = _authorize(  # type: ignore[arg-type]
                    raw,
                    _trust(document, authorization_digest),
                    ledger,
                )
                self.assertEqual(
                    _diagnostic_codes(result),
                    ["EXECUTION_AUTHORITY_BYTES_INVALID"],
                )
        self.assertEqual(ledger.claims, [])

    def test_file_ledger_durably_claims_once_and_preserves_replay_evidence(
        self,
    ) -> None:
        document, authorization_digest = _valid_authorization()
        raw_authorization = canonical_json_bytes(document)
        trust = _trust(document, authorization_digest)
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "authorization-ledger"
            root.mkdir(mode=0o700)
            ledger = self._file_ledger(root)

            first = _authorize(raw_authorization, trust, ledger)
            second = _authorize(raw_authorization, trust, ledger)

            self.assertIsInstance(first, ClaimedApplyAuthorization)
            self.assertIsInstance(second, AuthorizationRejection)
            assert isinstance(first, ClaimedApplyAuthorization)
            assert isinstance(second, AuthorizationRejection)
            self.assertEqual(
                [diagnostic.code for diagnostic in second.diagnostics],
                ["APPLY_AUTHORIZATION_REPLAYED"],
            )
            claim_paths = list(root.iterdir())
            self.assertEqual(len(claim_paths), 1)
            claim_path = claim_paths[0]
            self.assertEqual(
                claim_path.name,
                first.claim_identity.removeprefix("authorization-ledger-claim:sha256:")
                + ".json",
            )
            self.assertEqual(stat.S_IMODE(claim_path.stat().st_mode), 0o600)
            claim = thaw_json(strict_load_json_bytes(claim_path.read_bytes()))
            self.assertEqual(claim["claim_identity"], first.claim_identity)
            self.assertEqual(claim["apply_authorization_digest"], authorization_digest)

    def test_file_ledger_keeps_one_cas_target_after_path_replacement(
        self,
    ) -> None:
        document, authorization_digest = _valid_authorization()
        raw_authorization = canonical_json_bytes(document)
        trust = _trust(document, authorization_digest)
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "authorization-ledger"
            displaced_root = Path(temporary) / "displaced-ledger"
            root.mkdir(mode=0o700)
            ledger = self._file_ledger(root)
            gate = ApplyAuthorizationGate(
                TrustedExecutionDomain(
                    identity=trust.expected_execution_domain_identity,
                    authorization_ledger=ledger,
                )
            )

            first = gate.authorize_apply_start(raw_authorization, trust)
            root.rename(displaced_root)
            root.mkdir(mode=0o700)
            second = gate.authorize_apply_start(raw_authorization, trust)

            self.assertIsInstance(first, ClaimedApplyAuthorization)
            self.assertEqual(
                _diagnostic_codes(second),
                ["APPLY_AUTHORIZATION_REPLAYED"],
            )
            self.assertEqual(len(list(displaced_root.iterdir())), 1)
            self.assertEqual(list(root.iterdir()), [])

    def test_ambiguous_or_canonically_oversized_json_never_reaches_schema(
        self,
    ) -> None:
        document, authorization_digest = _valid_authorization()
        ledger = _RecordingLedger()
        canonically_oversized = b"[" + b",".join([b"1e9"] * 50_000) + b"]"
        self.assertLessEqual(len(canonically_oversized), MAX_APPLY_AUTHORIZATION_BYTES)

        for label, raw in (
            ("invalid UTF-8", b"\xff"),
            ("duplicate members", b'{"a":1,"a":2}'),
            ("nonfinite number", b"NaN"),
            ("canonical oversize", canonically_oversized),
        ):
            with (
                self.subTest(label=label),
                patch(
                    "agent_equipment.authorization.validate_document"
                ) as validate_schema,
            ):
                result = _authorize(
                    raw,
                    _trust(document, authorization_digest),
                    ledger,
                )

                self.assertIsInstance(result, AuthorizationRejection)
                assert isinstance(result, AuthorizationRejection)
                self.assertEqual(
                    [diagnostic.code for diagnostic in result.diagnostics],
                    ["EXECUTION_AUTHORITY_JSON_INVALID"],
                )
                validate_schema.assert_not_called()
        self.assertEqual(ledger.claims, [])

    def test_closed_schema_secret_and_complete_trust_mismatches_do_not_claim(
        self,
    ) -> None:
        document, authorization_digest = _valid_authorization()
        trusted = _trust(document, authorization_digest)
        ledger = _RecordingLedger()

        extra_member = copy.deepcopy(document)
        extra_member["approval"] = True
        schema_result = _authorize(canonical_json_bytes(extra_member), trusted, ledger)
        self.assertEqual(
            _diagnostic_codes(schema_result),
            ["APPLY_AUTHORIZATION_SCHEMA_INVALID"],
        )

        secret = copy.deepcopy(document)
        secret["issuer_identity"] = "authority:sk-" + "A" * 48
        secret_digest = _seal(secret)
        secret_result = _authorize(
            canonical_json_bytes(secret),
            replace(
                trusted,
                expected_authorization_identity=str(secret["authorization_identity"]),
                expected_authorization_digest=secret_digest,
                expected_issuer_identity=str(secret["issuer_identity"]),
            ),
            ledger,
        )
        self.assertEqual(
            _diagnostic_codes(secret_result),
            ["APPLY_AUTHORIZATION_LITERAL_SECRET"],
        )

        alternate_bindings = {
            "candidate_identity": "candidate:fixture/other-controller",
            "implementation_manifest_digest": _digest("0"),
            "catalog_digest": _digest("0"),
            "lock_digest": _digest("0"),
            "plan_digest": _digest("0"),
            "plan_action_set_digest": _digest("0"),
            "prepared_action_authority_set_identity": (
                "prepared-action-authority-set:sha256:" + "0" * 64
            ),
            "prepared_action_authority_set_digest": _digest("0"),
            "capability_set_digest": _digest("0"),
            "captured_state_identity": "capture:fixture/other-run",
            "captured_state_digest": _digest("0"),
            "capture_observation_authority_set_identity": (
                "capture-observation-authority-set:sha256:" + "0" * 64
            ),
            "capture_observation_authority_set_digest": _digest("0"),
            "expected_case_manifest_digest": _digest("0"),
            "operator_review_package_digest": _digest("0"),
        }
        for field, alternate in alternate_bindings.items():
            with self.subTest(misbound_field=field):
                misbound = copy.deepcopy(document)
                assert isinstance(misbound["bindings"], dict)
                misbound["bindings"][field] = alternate
                misbound_digest = _seal(misbound)
                misbound_result = _authorize(
                    canonical_json_bytes(misbound),
                    replace(
                        trusted,
                        expected_authorization_identity=str(
                            misbound["authorization_identity"]
                        ),
                        expected_authorization_digest=misbound_digest,
                    ),
                    ledger,
                )
                self.assertIn(
                    "APPLY_AUTHORIZATION_BINDING_MISMATCH",
                    _diagnostic_codes(misbound_result),
                )
        self.assertEqual(ledger.claims, [])

    def test_trusted_time_window_is_ordered_exact_and_expiry_is_exclusive(
        self,
    ) -> None:
        document, authorization_digest = _valid_authorization()
        ledger = _RecordingLedger()
        trusted = _trust(document, authorization_digest)

        for label, trusted_now in (
            ("before", datetime(2026, 8, 13, 6, 59, 59, tzinfo=timezone.utc)),
            ("expired", datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)),
            (
                "naive",
                datetime(
                    2026,
                    8,
                    13,
                    7,
                    30,
                    tzinfo=timezone.utc,
                ).replace(tzinfo=None),
            ),
        ):
            with self.subTest(label=label):
                result = _authorize(
                    canonical_json_bytes(document),
                    replace(trusted, trusted_now=trusted_now),
                    ledger,
                )
                self.assertIn(
                    (
                        "TRUSTED_CLOCK_INVALID"
                        if label == "naive"
                        else "APPLY_AUTHORIZATION_TIME_INVALID"
                    ),
                    _diagnostic_codes(result),
                )

        nanosecond_document = copy.deepcopy(document)
        nanosecond_document["not_before"] = "2026-08-13T07:30:00.000000001Z"
        nanosecond_digest = _seal(nanosecond_document)
        nanosecond_result = _authorize(
            canonical_json_bytes(nanosecond_document),
            replace(
                trusted,
                expected_authorization_identity=str(
                    nanosecond_document["authorization_identity"]
                ),
                expected_authorization_digest=nanosecond_digest,
                trusted_now=datetime(2026, 8, 13, 7, 30, tzinfo=timezone.utc),
            ),
            ledger,
        )
        self.assertIn(
            "APPLY_AUTHORIZATION_TIME_INVALID",
            _diagnostic_codes(nanosecond_result),
        )

        invalid_calendar = copy.deepcopy(document)
        invalid_calendar["issued_at"] = "2026-02-30T07:00:00Z"
        invalid_calendar_digest = _seal(invalid_calendar)
        invalid_calendar_result = _authorize(
            canonical_json_bytes(invalid_calendar),
            replace(
                trusted,
                expected_authorization_identity=str(
                    invalid_calendar["authorization_identity"]
                ),
                expected_authorization_digest=invalid_calendar_digest,
            ),
            ledger,
        )
        self.assertEqual(
            _diagnostic_codes(invalid_calendar_result),
            ["APPLY_AUTHORIZATION_SCHEMA_INVALID"],
        )
        self.assertEqual(ledger.claims, [])

    def test_identity_digest_issuer_domain_nonce_and_run_are_independent_trust(
        self,
    ) -> None:
        document, authorization_digest = _valid_authorization()
        trusted = _trust(document, authorization_digest)
        ledger = _RecordingLedger()

        forged_identity = copy.deepcopy(document)
        forged_identity["authorization_identity"] = (
            "apply-authorization:sha256:" + "0" * 64
        )
        self.assertIn(
            "APPLY_AUTHORIZATION_IDENTITY_INVALID",
            _diagnostic_codes(
                _authorize(canonical_json_bytes(forged_identity), trusted, ledger)
            ),
        )

        self.assertIn(
            "APPLY_AUTHORIZATION_DIGEST_MISMATCH",
            _diagnostic_codes(
                _authorize(
                    canonical_json_bytes(document),
                    replace(trusted, expected_authorization_digest=_digest("0")),
                    ledger,
                )
            ),
        )

        mutations = {
            "issuer_identity": (
                "authority:fixture/other",
                "APPLY_AUTHORIZATION_BINDING_MISMATCH",
            ),
            "execution_domain_identity": (
                "execution-domain:fixture/other-ledger-v1",
                "EXECUTION_DOMAIN_MISMATCH",
            ),
            "execution_nonce": (
                "execution-nonce:sha256:" + "0" * 64,
                "EXECUTION_BINDING_MISMATCH",
            ),
            "run_identity": (
                "run:sha256:" + "0" * 64,
                "EXECUTION_BINDING_MISMATCH",
            ),
        }
        for field, (alternate, expected_code) in mutations.items():
            with self.subTest(field=field):
                candidate = copy.deepcopy(document)
                candidate[field] = alternate
                candidate_digest = _seal(candidate)
                result = _authorize(
                    canonical_json_bytes(candidate),
                    replace(
                        trusted,
                        expected_authorization_identity=str(
                            candidate["authorization_identity"]
                        ),
                        expected_authorization_digest=candidate_digest,
                    ),
                    ledger,
                )
                self.assertIn(expected_code, _diagnostic_codes(result))
        self.assertEqual(ledger.claims, [])

    def test_file_ledger_fsyncs_the_claim_before_its_parent_directory(
        self,
    ) -> None:
        document, authorization_digest = _valid_authorization()
        trust = _trust(document, authorization_digest)
        original_fsync = os.fsync
        fsync_kinds: list[str] = []

        def record_fsync(descriptor: int) -> None:
            metadata = os.fstat(descriptor)
            fsync_kinds.append(
                "directory" if stat.S_ISDIR(metadata.st_mode) else "file"
            )
            original_fsync(descriptor)

        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "authorization-ledger"
            root.mkdir(mode=0o700)
            ledger = self._file_ledger(root)
            with patch(
                "agent_equipment.authorization.os.fsync",
                side_effect=record_fsync,
            ):
                result = _authorize(canonical_json_bytes(document), trust, ledger)

        self.assertIsInstance(result, ClaimedApplyAuthorization)
        self.assertEqual(fsync_kinds, ["file", "directory"])

    def test_post_create_persistence_failures_consume_the_nonce(self) -> None:
        document, authorization_digest = _valid_authorization()
        trust = _trust(document, authorization_digest)
        original_fsync = os.fsync

        for failing_kind in ("file", "directory"):
            with (
                self.subTest(failing_kind=failing_kind),
                TemporaryDirectory() as temporary,
            ):
                root = Path(temporary) / "authorization-ledger"
                root.mkdir(mode=0o700)
                ledger = self._file_ledger(root)

                def fail_selected_fsync(
                    descriptor: int,
                    selected_kind: str = failing_kind,
                ) -> None:
                    metadata = os.fstat(descriptor)
                    observed_kind = (
                        "directory" if stat.S_ISDIR(metadata.st_mode) else "file"
                    )
                    if observed_kind == selected_kind:
                        raise OSError("private fsync detail")
                    original_fsync(descriptor)

                with patch(
                    "agent_equipment.authorization.os.fsync",
                    side_effect=fail_selected_fsync,
                ):
                    failed = _authorize(canonical_json_bytes(document), trust, ledger)
                replay = _authorize(canonical_json_bytes(document), trust, ledger)

                self.assertEqual(
                    _diagnostic_codes(failed),
                    ["AUTHORIZATION_LEDGER_DURABILITY_UNCERTAIN"],
                )
                self.assertEqual(
                    _diagnostic_codes(replay),
                    ["APPLY_AUTHORIZATION_REPLAYED"],
                )
                self.assertEqual(len(list(root.iterdir())), 1)

    def test_file_ledger_completes_short_writes(self) -> None:
        document, authorization_digest = _valid_authorization()
        original_write = os.write

        def short_write(descriptor: int, payload: bytes) -> int:
            return original_write(descriptor, payload[:7])

        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "authorization-ledger"
            root.mkdir(mode=0o700)
            ledger = self._file_ledger(root)
            with patch(
                "agent_equipment.authorization.os.write",
                side_effect=short_write,
            ):
                result = _authorize(
                    canonical_json_bytes(document),
                    _trust(document, authorization_digest),
                    ledger,
                )

            self.assertIsInstance(result, ClaimedApplyAuthorization)
            [claim_path] = list(root.iterdir())
            claim = thaw_json(strict_load_json_bytes(claim_path.read_bytes()))
            self.assertEqual(claim["apply_authorization_digest"], authorization_digest)

    def test_failed_write_is_redacted_and_permanently_consumes_the_nonce(
        self,
    ) -> None:
        document, authorization_digest = _valid_authorization()
        raw_authorization = canonical_json_bytes(document)
        trust = _trust(document, authorization_digest)
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "authorization-ledger"
            root.mkdir(mode=0o700)
            ledger = self._file_ledger(root)
            with patch("agent_equipment.authorization.os.write", return_value=0):
                failed = _authorize(raw_authorization, trust, ledger)
            replay = _authorize(raw_authorization, trust, ledger)

            self.assertEqual(
                _diagnostic_codes(failed),
                ["AUTHORIZATION_LEDGER_DURABILITY_UNCERTAIN"],
            )
            assert isinstance(failed, AuthorizationRejection)
            self.assertNotIn(
                str(root),
                " ".join(diagnostic.message for diagnostic in failed.diagnostics),
            )
            self.assertEqual(
                _diagnostic_codes(replay),
                ["APPLY_AUTHORIZATION_REPLAYED"],
            )
            self.assertEqual(len(list(root.iterdir())), 1)

    def test_file_ledger_rejects_symlink_roots_and_consumes_existing_names(
        self,
    ) -> None:
        document, authorization_digest = _valid_authorization()
        trust = _trust(document, authorization_digest)
        domain = str(document["execution_domain_identity"])
        nonce = str(document["execution_nonce"])
        claim_name = (
            authorization_ledger_claim_identity(domain, nonce).removeprefix(
                "authorization-ledger-claim:sha256:"
            )
            + ".json"
        )

        with TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            target_root = temporary_root / "target-ledger"
            target_root.mkdir(mode=0o700)
            symlink_root = temporary_root / "symlink-ledger"
            symlink_root.symlink_to(target_root, target_is_directory=True)
            symlink_ledger = self._file_ledger(symlink_root)

            unsafe_root = _authorize(
                canonical_json_bytes(document), trust, symlink_ledger
            )

            self.assertEqual(
                _diagnostic_codes(unsafe_root),
                ["AUTHORIZATION_LEDGER_UNAVAILABLE"],
            )
            self.assertEqual(list(target_root.iterdir()), [])

            sentinel = temporary_root / "sentinel"
            sentinel.write_bytes(b"unchanged\n")
            (target_root / claim_name).symlink_to(sentinel)
            ledger = self._file_ledger(target_root)

            existing_name = _authorize(canonical_json_bytes(document), trust, ledger)

            self.assertEqual(
                _diagnostic_codes(existing_name),
                ["APPLY_AUTHORIZATION_REPLAYED"],
            )
            self.assertEqual(sentinel.read_bytes(), b"unchanged\n")

    def test_file_ledger_revalidates_typed_claims_and_fails_closed_after_close(
        self,
    ) -> None:
        document, authorization_digest = _valid_authorization()
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "authorization-ledger"
            root.mkdir(mode=0o700)
            ledger = self._file_ledger(root)
            claim = AuthorizationLedgerClaim(
                apply_authorization_identity=str(document["authorization_identity"]),
                apply_authorization_digest=authorization_digest,
                execution_domain_identity=str(document["execution_domain_identity"]),
                execution_nonce=str(document["execution_nonce"]),
                run_identity=str(document["run_identity"]),
            )
            object.__setattr__(claim, "run_identity", "run:invalid")

            malformed = ledger.claim(claim)
            ledger.close()
            closed = _authorize(
                canonical_json_bytes(document),
                _trust(document, authorization_digest),
                ledger,
            )

            self.assertIs(
                malformed,
                AuthorizationLedgerClaimStatus.UNAVAILABLE,
            )
            self.assertEqual(
                _diagnostic_codes(closed),
                ["AUTHORIZATION_LEDGER_UNAVAILABLE"],
            )
            self.assertEqual(list(root.iterdir()), [])

    def test_concurrent_claims_have_exactly_one_durable_winner(self) -> None:
        document, authorization_digest = _valid_authorization()
        raw_authorization = canonical_json_bytes(document)
        trust = _trust(document, authorization_digest)
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "authorization-ledger"
            root.mkdir(mode=0o700)
            ledger = self._file_ledger(root)

            with ThreadPoolExecutor(max_workers=8) as executor:
                results = tuple(
                    executor.map(
                        lambda _: _authorize(raw_authorization, trust, ledger),
                        range(8),
                    )
                )

            self.assertEqual(
                sum(
                    isinstance(result, ClaimedApplyAuthorization) for result in results
                ),
                1,
            )
            self.assertEqual(
                sum(
                    _diagnostic_codes(result) == ["APPLY_AUTHORIZATION_REPLAYED"]
                    for result in results
                ),
                7,
            )
            self.assertEqual(len(list(root.iterdir())), 1)

    def test_gate_prebinds_one_authoritative_domain_and_cas_target(
        self,
    ) -> None:
        document, authorization_digest = _valid_authorization()
        authoritative_ledger = _RecordingLedger()
        foreign_ledger = _RecordingLedger()
        gate = ApplyAuthorizationGate(
            TrustedExecutionDomain(
                identity=str(document["execution_domain_identity"]),
                authorization_ledger=authoritative_ledger,
            )
        )
        raw_authorization = canonical_json_bytes(document)
        trust = _trust(document, authorization_digest)

        with self.assertRaises(FrozenInstanceError):
            gate._execution_domain = TrustedExecutionDomain(  # type: ignore[misc]
                identity=str(document["execution_domain_identity"]),
                authorization_ledger=foreign_ledger,
            )

        with self.assertRaises(TypeError):
            gate.authorize_apply_start(  # type: ignore[call-arg]
                raw_authorization,
                trust,
                foreign_ledger,
            )

        admitted = gate.authorize_apply_start(
            raw_authorization,
            trust,
        )

        foreign = copy.deepcopy(document)
        foreign["execution_domain_identity"] = (
            "execution-domain:fixture/other-ledger-v1"
        )
        foreign_digest = _seal(foreign)

        rejected = gate.authorize_apply_start(
            canonical_json_bytes(foreign),
            _trust(foreign, foreign_digest),
        )

        self.assertIsInstance(admitted, ClaimedApplyAuthorization)
        self.assertEqual(
            _diagnostic_codes(rejected),
            ["EXECUTION_DOMAIN_MISMATCH"],
        )
        self.assertEqual(len(authoritative_ledger.claims), 1)
        self.assertEqual(foreign_ledger.claims, [])

    def test_only_a_durable_ledger_outcome_grants_claimed_authority(
        self,
    ) -> None:
        document, authorization_digest = _valid_authorization()
        trust = _trust(document, authorization_digest)
        expected = {
            AuthorizationLedgerClaimStatus.REPLAY: ("APPLY_AUTHORIZATION_REPLAYED"),
            AuthorizationLedgerClaimStatus.UNAVAILABLE: (
                "AUTHORIZATION_LEDGER_UNAVAILABLE"
            ),
            AuthorizationLedgerClaimStatus.DURABILITY_UNCERTAIN: (
                "AUTHORIZATION_LEDGER_DURABILITY_UNCERTAIN"
            ),
        }

        for status, expected_code in expected.items():
            with self.subTest(status=status):
                ledger = _RecordingLedger(status)
                result = _authorize(canonical_json_bytes(document), trust, ledger)

                self.assertEqual(_diagnostic_codes(result), [expected_code])
                self.assertEqual(len(ledger.claims), 1)

        invalid_status_ledger = _RecordingLedger()
        invalid_status_ledger.status = object()  # type: ignore[assignment]
        invalid_status_result = _authorize(
            canonical_json_bytes(document), trust, invalid_status_ledger
        )
        self.assertEqual(
            _diagnostic_codes(invalid_status_result),
            ["AUTHORIZATION_LEDGER_DURABILITY_UNCERTAIN"],
        )

        raising_ledger = _RecordingLedger()
        with patch.object(
            raising_ledger,
            "claim",
            side_effect=RuntimeError("private ledger failure"),
        ):
            raised_result = _authorize(
                canonical_json_bytes(document), trust, raising_ledger
            )
        self.assertEqual(
            _diagnostic_codes(raised_result),
            ["AUTHORIZATION_LEDGER_DURABILITY_UNCERTAIN"],
        )


def _diagnostic_codes(result: object) -> list[str]:
    if not isinstance(result, AuthorizationRejection):
        return []
    return [diagnostic.code for diagnostic in result.diagnostics]


if __name__ == "__main__":
    unittest.main()
