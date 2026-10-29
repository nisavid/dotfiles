from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Self
from unittest.mock import patch

from agent_equipment.canonical import (
    _build_installed_implementation_manifest,
    _require_closed_directory,
    build_installed_implementation_manifest,
    canonical_json_bytes,
    canonical_json_sha256,
    strict_load_json_bytes,
    strict_load_json_path,
)
from agent_equipment.model import _canonical_json_bytes, thaw_json

ACCEPTANCE_EVIDENCE_SCHEMA_PATH = (
    "lib/agent-equipment/schemas/acceptance-evidence-v1.schema.json"
)
MANIFEST_PATHS = (
    "bin/agent-equipment",
    "lib/agent-equipment/agent_equipment/__init__.py",
    "lib/agent-equipment/agent_equipment/_json_schema.py",
    "lib/agent-equipment/agent_equipment/authoring.py",
    "lib/agent-equipment/agent_equipment/authorization.py",
    "lib/agent-equipment/agent_equipment/canonical.py",
    "lib/agent-equipment/agent_equipment/discovery.py",
    "lib/agent-equipment/agent_equipment/execution_authority.py",
    "lib/agent-equipment/agent_equipment/inventory.py",
    "lib/agent-equipment/agent_equipment/model.py",
    "lib/agent-equipment/agent_equipment/plan_action_set.py",
    "lib/agent-equipment/agent_equipment/resolver.py",
    "lib/agent-equipment/agent_equipment/secrets.py",
    "lib/agent-equipment/agent_equipment/source_resolution.py",
    "lib/agent-equipment/agent_equipment/updater.py",
    "lib/agent-equipment/agent_equipment/validator.py",
    ACCEPTANCE_EVIDENCE_SCHEMA_PATH,
    "lib/agent-equipment/schemas/adapter-contract-v1.schema.json",
    "lib/agent-equipment/schemas/captured-state-v1.schema.json",
    "lib/agent-equipment/schemas/catalog-v1.schema.json",
    "lib/agent-equipment/schemas/execution-authority-v1.schema.json",
    "lib/agent-equipment/schemas/lock-v1.schema.json",
    "lib/agent-equipment/schemas/plan-action-set-v1.schema.json",
)


def write_installed_tree(root: Path) -> None:
    for relative_path in MANIFEST_PATHS:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"{relative_path}\n".encode())


def fixture_manifest(
    *,
    root: Path,
    runtime: Path,
    implementation_name: str = "cpython",
    version: tuple[int, int, int] = (3, 12, 8),
    relative_paths: tuple[str, ...] = MANIFEST_PATHS,
):
    return _build_installed_implementation_manifest(
        implementation_name=implementation_name,
        version=version,
        runtime_executable=runtime,
        installed_root=root,
        relative_paths=relative_paths,
    )


class CanonicalJsonTest(unittest.TestCase):
    def test_canonical_json_is_compact_utf8_key_sorted_and_digest_stable(self) -> None:
        document = {"b": 1, "a": "é"}

        self.assertEqual(canonical_json_bytes(document), b'{"a":"\xc3\xa9","b":1}')
        self.assertEqual(
            canonical_json_sha256(document),
            "sha256:aa58fba8483623bed37c1b02edfccbdd9a53123837c20bfa4cb4049993a2872e",
        )

    def test_model_and_public_canonical_serializers_remain_byte_identical(
        self,
    ) -> None:
        corpus = (
            None,
            True,
            0,
            -17,
            1.25,
            "é/雪",
            [],
            {},
            {"z": [3, {"b": False, "a": None}], "a": "ordered"},
        )

        for document in corpus:
            with self.subTest(document=document):
                self.assertEqual(
                    _canonical_json_bytes(document),
                    canonical_json_bytes(document),
                )

    def test_strict_load_rejects_ambiguous_or_non_json_input(self) -> None:
        loaded = strict_load_json_bytes(b'{"items":[true,null,1.25]}')
        self.assertEqual(thaw_json(loaded), {"items": [True, None, 1.25]})

        for payload in (
            b'{"duplicate":1,"duplicate":2}',
            b'{"nonfinite":NaN}',
            b'{"surrogate":"\\ud800"}',
            b"\xff",
        ):
            with (
                self.subTest(payload=payload),
                self.assertRaises((UnicodeError, ValueError)),
            ):
                strict_load_json_bytes(payload)

        with TemporaryDirectory() as directory:
            path = Path(directory) / "document.json"
            path.write_bytes(b'{"source":"path"}')
            self.assertEqual(
                thaw_json(strict_load_json_path(path)),
                {"source": "path"},
            )

    def test_proposed_catalog_and_lock_are_stable_canonical_vectors(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        documents = repository / "docs/agent-equipment"

        self.assertEqual(
            canonical_json_sha256(
                strict_load_json_path(documents / "initial-catalog.proposed.json")
            ),
            "sha256:b580775ec1ea54029d8eda747dd98e49824de952ba326d344c6186e56cfee05d",
        )
        self.assertEqual(
            canonical_json_sha256(
                strict_load_json_path(documents / "initial-lock.proposed.json")
            ),
            "sha256:1f493d7f74f249e65242fa45f340a23cf2ff8a26949b524ef269d78b76851a0a",
        )

    def test_public_manifest_builder_accepts_no_caller_trust_inputs(self) -> None:
        self.assertEqual(
            tuple(
                inspect.signature(build_installed_implementation_manifest).parameters
            ),
            (),
        )

    def test_installed_manifest_hashes_actual_runtime_and_closed_inventory(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            runtime = base / "python3.12-real"
            runtime.write_bytes(b"runtime\n")
            selected_runtime = base / "python3.12"
            selected_runtime.symlink_to(runtime.name)
            installed_root = base / "installed"
            write_installed_tree(installed_root)

            manifest = fixture_manifest(
                root=installed_root,
                runtime=selected_runtime,
            )

        self.assertEqual(manifest.runtime_identity, "cpython:3.12.8")
        self.assertEqual(
            manifest.runtime_executable_digest,
            "sha256:fae9d8f386d67956867dedef7c89476199a4a25ee9ffe13560a6bfae7ae6c407",
        )
        self.assertEqual(
            tuple(item.path for item in manifest.files),
            MANIFEST_PATHS,
        )
        self.assertEqual(
            manifest.files[0].digest,
            "sha256:70590403b684cc601172740a8415e1c4d77aa505136ca72c91b9df6e7908bf04",
        )

    def test_installed_manifest_rejects_invalid_runtime(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            runtime = base / "python"
            runtime.write_bytes(b"runtime")
            root = base / "installed"
            write_installed_tree(root)

            for implementation_name, version in (
                ("", (3, 12, 8)),
                ("pypy", (3, 12, 8)),
                ("cpython", (3, 11, 9)),
            ):
                with (
                    self.subTest(
                        implementation_name=implementation_name,
                        version=version,
                    ),
                    self.assertRaises(ValueError),
                ):
                    fixture_manifest(
                        root=root,
                        runtime=runtime,
                        implementation_name=implementation_name,
                        version=version,
                    )

    def test_installed_manifest_rejects_invalid_runtime_path(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "installed"
            write_installed_tree(root)

            with self.assertRaises(ValueError):
                fixture_manifest(root=root, runtime=Path())

    def test_installed_manifest_rejects_empty_inventory(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            runtime = base / "python"
            runtime.write_bytes(b"runtime")
            root = base / "installed"
            write_installed_tree(root)

            with self.assertRaises(ValueError):
                fixture_manifest(root=root, runtime=runtime, relative_paths=())

    def test_installed_manifest_rejects_entries_over_role_bounds(self) -> None:
        cases = (
            (MANIFEST_PATHS[0], (256 * 1024) + 1),
            (MANIFEST_PATHS[1], (1024 * 1024) + 1),
            (ACCEPTANCE_EVIDENCE_SCHEMA_PATH, (512 * 1024) + 1),
        )
        for relative_path, oversized_bytes in cases:
            with (
                self.subTest(relative_path=relative_path),
                TemporaryDirectory() as directory,
            ):
                base = Path(directory)
                runtime = base / "python"
                runtime.write_bytes(b"runtime")
                root = base / "installed"
                write_installed_tree(root)
                with (root / relative_path).open("wb") as stream:
                    stream.truncate(oversized_bytes)

                with self.assertRaises(ValueError):
                    fixture_manifest(root=root, runtime=runtime)

    def test_installed_manifest_rejects_runtime_over_256_mebibytes(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            runtime = base / "python"
            with runtime.open("wb") as stream:
                stream.truncate((256 * 1024 * 1024) + 1)
            root = base / "installed"
            write_installed_tree(root)

            with self.assertRaises(ValueError):
                fixture_manifest(root=root, runtime=runtime)

    def test_installed_manifest_rejects_aggregate_over_eight_mebibytes(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            runtime = base / "python"
            runtime.write_bytes(b"runtime")
            root = base / "installed"
            write_installed_tree(root)
            for relative_path in MANIFEST_PATHS:
                if relative_path.startswith("lib/agent-equipment/agent_equipment/"):
                    target_size = 900 * 1024
                elif relative_path.startswith("lib/agent-equipment/schemas/"):
                    target_size = 400 * 1024
                else:
                    continue
                with (root / relative_path).open("wb") as stream:
                    stream.truncate(target_size)

            aggregate_size = sum(
                (root / relative_path).stat().st_size
                for relative_path in MANIFEST_PATHS
            )
            self.assertGreater(aggregate_size, 8 * 1024 * 1024)

            with self.assertRaises(ValueError):
                fixture_manifest(root=root, runtime=runtime)

    def test_installed_manifest_rejects_missing_symlinked_or_hardlinked_files(
        self,
    ) -> None:
        for case in ("missing", "symlink", "hardlink"):
            with self.subTest(case=case), TemporaryDirectory() as directory:
                base = Path(directory)
                runtime = base / "python"
                runtime.write_bytes(b"runtime")
                root = base / "installed"
                write_installed_tree(root)
                first = root / MANIFEST_PATHS[0]
                second = root / MANIFEST_PATHS[1]
                first.unlink()
                if case == "symlink":
                    first.symlink_to(second)
                elif case == "hardlink":
                    first.hardlink_to(second)

                with self.assertRaises(ValueError):
                    fixture_manifest(root=root, runtime=runtime)

    def test_installed_manifest_rejects_out_of_inventory_hardlink_alias(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            runtime = base / "python"
            runtime.write_bytes(b"runtime")
            root = base / "installed"
            write_installed_tree(root)
            alias = root / "unmanaged-alias"
            alias.hardlink_to(root / MANIFEST_PATHS[0])

            with self.assertRaises(ValueError):
                fixture_manifest(root=root, runtime=runtime)

    def test_installed_manifest_rejects_extra_owned_tree_entries(self) -> None:
        extras = (
            "lib/agent-equipment/agent_equipment/extra.py",
            "lib/agent-equipment/agent_equipment/__pycache__/cached.pyc",
            "lib/agent-equipment/schemas/extra.schema.json",
            "lib/agent-equipment/unexpected/entry",
        )
        for extra_path in extras:
            with self.subTest(extra_path=extra_path), TemporaryDirectory() as directory:
                base = Path(directory)
                runtime = base / "python"
                runtime.write_bytes(b"runtime")
                root = base / "installed"
                write_installed_tree(root)
                extra = root / extra_path
                extra.parent.mkdir(parents=True, exist_ok=True)
                extra.write_bytes(b"unexpected")

                with self.assertRaises(ValueError):
                    fixture_manifest(root=root, runtime=runtime)

    def test_closed_inventory_stops_at_the_first_excess_entry(self) -> None:
        class Entry:
            def __init__(self, name: str) -> None:
                self.name = name

        class Scanner:
            def __init__(self) -> None:
                self._names = ("first", "second", "extra", "must-not-be-read")
                self.yielded = 0

            def __enter__(self) -> Self:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def __iter__(self) -> Scanner:
                return self

            def __next__(self) -> Entry:
                if self.yielded >= 3:
                    raise AssertionError("closed inventory enumeration continued")
                entry = Entry(self._names[self.yielded])
                self.yielded += 1
                return entry

        scanner = Scanner()
        with (
            patch("agent_equipment.canonical.os.scandir", return_value=scanner),
            self.assertRaises(ValueError),
        ):
            _require_closed_directory(-1, ("first", "second"))

        self.assertEqual(scanner.yielded, 3)

    def test_installed_manifest_fails_if_a_file_is_swapped_during_hash(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            runtime = base / "python"
            runtime.write_bytes(b"runtime")
            root = base / "installed"
            write_installed_tree(root)
            installed = root / MANIFEST_PATHS[0]
            outside = base / "outside"
            outside.write_bytes(b"outside")

            def swap_file(role: str, relative_path: str) -> None:
                if role == "installed" and relative_path == MANIFEST_PATHS[0]:
                    installed.rename(root / "original-launcher")
                    installed.symlink_to(outside)

            with (
                patch(
                    "agent_equipment.canonical._before_descriptor_hash",
                    side_effect=swap_file,
                ),
                self.assertRaises(ValueError),
            ):
                fixture_manifest(root=root, runtime=runtime)

    def test_installed_manifest_fails_if_opened_content_changes(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            runtime = base / "python"
            runtime.write_bytes(b"runtime")
            root = base / "installed"
            write_installed_tree(root)
            installed = root / MANIFEST_PATHS[0]

            def change_file(role: str, relative_path: str) -> None:
                if role == "installed" and relative_path == MANIFEST_PATHS[0]:
                    installed.write_bytes(b"changed-during-hash")

            with (
                patch(
                    "agent_equipment.canonical._before_descriptor_hash",
                    side_effect=change_file,
                ),
                self.assertRaises(ValueError),
            ):
                fixture_manifest(root=root, runtime=runtime)

    def test_installed_manifest_fails_if_a_parent_is_swapped_during_hash(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            runtime = base / "python"
            runtime.write_bytes(b"runtime")
            root = base / "installed"
            write_installed_tree(root)
            parent = root / "lib/agent-equipment/schemas"
            target = ACCEPTANCE_EVIDENCE_SCHEMA_PATH

            def swap_parent(role: str, relative_path: str) -> None:
                if role == "installed" and relative_path == target:
                    parent.rename(root / "original-schemas")
                    parent.mkdir()
                    (parent / Path(target).name).write_bytes(b"replacement")

            with (
                patch(
                    "agent_equipment.canonical._before_descriptor_hash",
                    side_effect=swap_parent,
                ),
                self.assertRaises(ValueError),
            ):
                fixture_manifest(root=root, runtime=runtime)

    def test_installed_manifest_rechecks_earlier_file_after_later_hash(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            runtime = base / "python"
            runtime.write_bytes(b"runtime")
            root = base / "installed"
            write_installed_tree(root)
            earlier = root / MANIFEST_PATHS[0]

            def change_earlier_file(role: str, relative_path: str) -> None:
                if role == "installed" and relative_path == MANIFEST_PATHS[-1]:
                    earlier.write_bytes(b"changed after its digest")

            with (
                patch(
                    "agent_equipment.canonical._before_descriptor_hash",
                    side_effect=change_earlier_file,
                ),
                self.assertRaises(ValueError),
            ):
                fixture_manifest(root=root, runtime=runtime)

    def test_installed_manifest_rechecks_runtime_after_later_hash(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            runtime = base / "python"
            runtime.write_bytes(b"runtime")
            root = base / "installed"
            write_installed_tree(root)

            def change_runtime_later(role: str, relative_path: str) -> None:
                if role == "installed" and relative_path == MANIFEST_PATHS[-1]:
                    runtime.write_bytes(b"changed after its digest")

            with (
                patch(
                    "agent_equipment.canonical._before_descriptor_hash",
                    side_effect=change_runtime_later,
                ),
                self.assertRaises(ValueError),
            ):
                fixture_manifest(root=root, runtime=runtime)

    def test_installed_manifest_fails_if_resolved_runtime_is_swapped(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            actual_runtime = base / "python-real"
            actual_runtime.write_bytes(b"runtime")
            selected_runtime = base / "python"
            selected_runtime.symlink_to(actual_runtime.name)
            root = base / "installed"
            write_installed_tree(root)

            def swap_runtime(role: str, relative_path: str) -> None:
                if role == "runtime":
                    actual_runtime.rename(base / "original-runtime")
                    actual_runtime.write_bytes(b"replacement")

            with (
                patch(
                    "agent_equipment.canonical._before_descriptor_hash",
                    side_effect=swap_runtime,
                ),
                self.assertRaises(ValueError),
            ):
                fixture_manifest(root=root, runtime=selected_runtime)


if __name__ == "__main__":
    unittest.main()
