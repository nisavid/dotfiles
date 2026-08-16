from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "home/private_dot_local/lib/agent-equipment"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from agent_equipment import validator
from agent_equipment.validator import EXPECTED_SCHEMA_SHA256

DOCUMENTS = ROOT / "docs/agent-equipment"
CATALOG = DOCUMENTS / "initial-catalog.proposed.json"
LOCK = DOCUMENTS / "initial-lock.proposed.json"


class SchemaManifestTests(unittest.TestCase):
    def copy_schema_set(self, destination: Path) -> None:
        for name in EXPECTED_SCHEMA_SHA256:
            shutil.copyfile(DOCUMENTS / name, destination / name)

    def test_missing_changed_and_malformed_schema_sets_fail_before_semantics(
        self,
    ) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        cases = ("missing", "changed", "malformed")
        for case in cases:
            with self.subTest(case=case), TemporaryDirectory() as directory:
                schema_directory = Path(directory)
                self.copy_schema_set(schema_directory)
                target = schema_directory / "catalog-v1.schema.json"
                if case == "missing":
                    target.unlink()
                elif case == "changed":
                    target.write_bytes(target.read_bytes() + b"\n")
                else:
                    target.write_bytes(b"{")

                results = (
                    validator._load_catalog_lock_for_tests(
                        CATALOG,
                        LOCK,
                        schema_directory=schema_directory,
                    ),
                    validator._validate_catalog_lock_for_tests(
                        catalog,
                        lock,
                        schema_directory=schema_directory,
                    ),
                )

                for result in results:
                    self.assertIsNone(result.model)
                    self.assertEqual(
                        tuple(diagnostic.code for diagnostic in result.diagnostics),
                        ("SCHEMA_MANIFEST_INVALID",),
                    )
                    rendered = " ".join(
                        diagnostic.message for diagnostic in result.diagnostics
                    )
                    self.assertNotIn("catalog-v1.schema.json", rendered)
                    self.assertNotIn(str(schema_directory), rendered)

    def test_compiled_schema_digest_manifest_cannot_be_rewritten(self) -> None:
        with self.assertRaises(TypeError):
            EXPECTED_SCHEMA_SHA256["catalog-v1.schema.json"] = "0" * 64  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
