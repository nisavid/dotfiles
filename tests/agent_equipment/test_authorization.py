from __future__ import annotations

import os
import stat
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_equipment import authorization
from agent_equipment.authorization import (
    AuthorizationLedgerClaim,
    AuthorizationLedgerClaimStatus,
    FileAuthorizationLedger,
    authorization_ledger_claim_identity,
)
from agent_equipment.canonical import strict_load_json_bytes
from agent_equipment.model import thaw_json


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _claim(nonce_character: str = "3") -> AuthorizationLedgerClaim:
    return AuthorizationLedgerClaim(
        apply_authorization_identity="apply-authorization:sha256:" + "1" * 64,
        apply_authorization_digest=_digest("2"),
        execution_domain_identity="execution-domain:fixture/global-ledger-v1",
        execution_nonce="execution-nonce:sha256:" + nonce_character * 64,
        run_identity="run:sha256:" + "4" * 64,
    )


class FileAuthorizationLedgerTest(unittest.TestCase):
    def _file_ledger(self, root: Path) -> FileAuthorizationLedger:
        ledger = FileAuthorizationLedger(root)
        self.addCleanup(ledger.close)
        return ledger

    def test_module_has_no_direct_apply_start_api(self) -> None:
        for name in (
            "ApplyAuthorizationGate",
            "ApplyAuthorizationTrust",
            "ClaimedApplyAuthorization",
            "AuthorizationRejection",
            "authorize_apply_start",
            "_authorize_apply_start",
        ):
            with self.subTest(name=name):
                self.assertFalse(hasattr(authorization, name))

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

    def test_claim_rejects_invalid_bindings_before_the_ledger(self) -> None:
        with self.assertRaisesRegex(ValueError, "claim bindings"):
            AuthorizationLedgerClaim(
                apply_authorization_identity="apply-authorization:sha256:" + "1" * 64,
                apply_authorization_digest="not-a-digest",
                execution_domain_identity="execution-domain:fixture/global-ledger-v1",
                execution_nonce="execution-nonce:sha256:" + "3" * 64,
                run_identity="run:sha256:" + "4" * 64,
            )

    def test_file_ledger_durably_claims_once_and_preserves_replay_evidence(
        self,
    ) -> None:
        claim = _claim()
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "authorization-ledger"
            root.mkdir(mode=0o700)
            ledger = self._file_ledger(root)

            self.assertIs(
                ledger.claim(claim),
                AuthorizationLedgerClaimStatus.DURABLE,
            )
            self.assertIs(
                ledger.claim(claim),
                AuthorizationLedgerClaimStatus.REPLAY,
            )

            [claim_path] = list(root.iterdir())
            self.assertEqual(
                claim_path.name,
                claim.claim_identity.removeprefix("authorization-ledger-claim:sha256:")
                + ".json",
            )
            self.assertEqual(stat.S_IMODE(claim_path.stat().st_mode), 0o600)
            persisted = thaw_json(strict_load_json_bytes(claim_path.read_bytes()))
            self.assertEqual(persisted, thaw_json(claim.as_json()))

    def test_file_ledger_fsyncs_the_claim_before_its_parent_directory(
        self,
    ) -> None:
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
                status = ledger.claim(_claim())

        self.assertIs(status, AuthorizationLedgerClaimStatus.DURABLE)
        self.assertEqual(fsync_kinds, ["file", "directory"])

    def test_post_create_persistence_failure_consumes_the_nonce(self) -> None:
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
                        raise OSError("fsync failed")
                    original_fsync(descriptor)

                with patch(
                    "agent_equipment.authorization.os.fsync",
                    side_effect=fail_selected_fsync,
                ):
                    failed = ledger.claim(_claim())
                replay = ledger.claim(_claim())

                self.assertIs(
                    failed,
                    AuthorizationLedgerClaimStatus.DURABILITY_UNCERTAIN,
                )
                self.assertIs(replay, AuthorizationLedgerClaimStatus.REPLAY)
                self.assertEqual(len(list(root.iterdir())), 1)

    def test_file_ledger_completes_short_writes(self) -> None:
        original_write = os.write

        def short_write(descriptor: int, payload: bytes) -> int:
            return original_write(descriptor, payload[:7])

        claim = _claim()
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "authorization-ledger"
            root.mkdir(mode=0o700)
            ledger = self._file_ledger(root)
            with patch(
                "agent_equipment.authorization.os.write",
                side_effect=short_write,
            ):
                status = ledger.claim(claim)

            self.assertIs(status, AuthorizationLedgerClaimStatus.DURABLE)
            [claim_path] = list(root.iterdir())
            persisted = thaw_json(strict_load_json_bytes(claim_path.read_bytes()))
            self.assertEqual(
                persisted["apply_authorization_digest"],
                claim.apply_authorization_digest,
            )

    def test_failed_write_permanently_consumes_the_nonce(self) -> None:
        claim = _claim()
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "authorization-ledger"
            root.mkdir(mode=0o700)
            ledger = self._file_ledger(root)
            with patch("agent_equipment.authorization.os.write", return_value=0):
                failed = ledger.claim(claim)
            replay = ledger.claim(claim)

            self.assertIs(
                failed,
                AuthorizationLedgerClaimStatus.DURABILITY_UNCERTAIN,
            )
            self.assertIs(replay, AuthorizationLedgerClaimStatus.REPLAY)
            self.assertEqual(len(list(root.iterdir())), 1)

    def test_file_ledger_rejects_symlink_roots_and_consumes_existing_names(
        self,
    ) -> None:
        claim = _claim()
        claim_name = (
            claim.claim_identity.removeprefix("authorization-ledger-claim:sha256:")
            + ".json"
        )

        with TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            target_root = temporary_root / "target-ledger"
            target_root.mkdir(mode=0o700)
            symlink_root = temporary_root / "symlink-ledger"
            symlink_root.symlink_to(target_root, target_is_directory=True)
            symlink_ledger = self._file_ledger(symlink_root)

            self.assertIs(
                symlink_ledger.claim(claim),
                AuthorizationLedgerClaimStatus.UNAVAILABLE,
            )
            self.assertEqual(list(target_root.iterdir()), [])

            sentinel = temporary_root / "sentinel"
            sentinel.write_bytes(b"unchanged\n")
            (target_root / claim_name).symlink_to(sentinel)
            ledger = self._file_ledger(target_root)

            self.assertIs(
                ledger.claim(claim),
                AuthorizationLedgerClaimStatus.REPLAY,
            )
            self.assertEqual(sentinel.read_bytes(), b"unchanged\n")

    def test_file_ledger_revalidates_claims_and_fails_closed_after_close(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "authorization-ledger"
            root.mkdir(mode=0o700)
            ledger = self._file_ledger(root)
            claim = _claim()
            object.__setattr__(claim, "run_identity", "run:invalid")

            malformed = ledger.claim(claim)
            ledger.close()
            closed = ledger.claim(_claim())

            self.assertIs(malformed, AuthorizationLedgerClaimStatus.UNAVAILABLE)
            self.assertIs(closed, AuthorizationLedgerClaimStatus.UNAVAILABLE)
            self.assertEqual(list(root.iterdir()), [])

    def test_file_ledger_keeps_one_cas_target_after_path_replacement(
        self,
    ) -> None:
        claim = _claim()
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "authorization-ledger"
            displaced_root = Path(temporary) / "displaced-ledger"
            root.mkdir(mode=0o700)
            ledger = self._file_ledger(root)

            first = ledger.claim(claim)
            root.rename(displaced_root)
            root.mkdir(mode=0o700)
            second = ledger.claim(claim)

            self.assertIs(first, AuthorizationLedgerClaimStatus.DURABLE)
            self.assertIs(second, AuthorizationLedgerClaimStatus.REPLAY)
            self.assertEqual(len(list(displaced_root.iterdir())), 1)
            self.assertEqual(list(root.iterdir()), [])

    def test_concurrent_claims_have_exactly_one_durable_winner(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "authorization-ledger"
            root.mkdir(mode=0o700)
            ledger = self._file_ledger(root)

            with ThreadPoolExecutor(max_workers=8) as executor:
                results = tuple(
                    executor.map(
                        lambda _: ledger.claim(_claim()),
                        range(8),
                    )
                )

            self.assertEqual(
                results.count(AuthorizationLedgerClaimStatus.DURABLE),
                1,
            )
            self.assertEqual(
                results.count(AuthorizationLedgerClaimStatus.REPLAY),
                7,
            )
            self.assertEqual(len(list(root.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
