from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "home/private_dot_local/lib/agent-equipment"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

import agent_equipment

PUBLIC_NAMES = (
    "Catalog",
    "CatalogLockValidation",
    "CoverageRecord",
    "Diagnostic",
    "FrozenJsonObject",
    "InstalledFile",
    "InstalledImplementationManifest",
    "ResolvedLock",
    "ValidatedCatalogLock",
    "build_installed_implementation_manifest",
    "byte_sha256",
    "canonical_json_bytes",
    "canonical_json_sha256",
    "freeze_json",
    "load_catalog_lock",
    "main",
    "strict_load_json_bytes",
    "strict_load_json_path",
    "thaw_json",
    "validate_catalog_lock",
)


class PublicApiTests(unittest.TestCase):
    def test_package_exports_only_the_no_plan_production_api(self) -> None:
        self.assertEqual(agent_equipment.__all__, PUBLIC_NAMES)
        for name in PUBLIC_NAMES:
            with self.subTest(public_name=name):
                self.assertTrue(hasattr(agent_equipment, name))
        for legacy_name in (
            "CoverageEntry",
            "DesignValidationResult",
            "PlannedOperation",
            "load_and_validate",
            "validate_design",
        ):
            with self.subTest(legacy_name=legacy_name):
                self.assertFalse(hasattr(agent_equipment, legacy_name))

    def test_public_validation_signatures_have_no_schema_path_override(self) -> None:
        self.assertEqual(
            tuple(inspect.signature(agent_equipment.load_catalog_lock).parameters),
            ("catalog_path", "lock_path"),
        )
        self.assertEqual(
            tuple(inspect.signature(agent_equipment.validate_catalog_lock).parameters),
            ("catalog", "lock"),
        )
        self.assertEqual(
            tuple(
                inspect.signature(
                    agent_equipment.build_installed_implementation_manifest
                ).parameters
            ),
            (),
        )

    def test_main_fails_closed_before_runtime_commands_exist(self) -> None:
        with self.assertRaises(TypeError):
            agent_equipment.main()
        with self.assertRaises(TypeError):
            agent_equipment.main(object())


if __name__ == "__main__":
    unittest.main()
