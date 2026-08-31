from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "home"
DOCUMENTS = ROOT / "docs/agent-equipment"
HANDOFF = DOCUMENTS / "IMPLEMENTATION_HANDOFF.md"
CONFIG_SOURCES = {
    SOURCE / "dot_config/agent-equipment/catalog-v1.json": (
        DOCUMENTS / "initial-catalog.proposed.json"
    ),
    SOURCE / "dot_config/agent-equipment/lock-v1.json": (
        DOCUMENTS / "initial-lock.proposed.json"
    ),
}
SCHEMA_NAMES = (
    "acceptance-evidence-v1.schema.json",
    "adapter-contract-v1.schema.json",
    "captured-state-v1.schema.json",
    "catalog-v1.schema.json",
    "execution-authority-v1.schema.json",
    "lock-v1.schema.json",
    "plan-action-set-v1.schema.json",
)
SCHEMA_SOURCE_ROOT = SOURCE / "private_dot_local/lib/agent-equipment/schemas"
LAUNCHER_SOURCE = SOURCE / "private_dot_local/bin/executable_agent-equipment"
PACKAGE_SOURCE_ROOT = SOURCE / "private_dot_local/lib/agent-equipment/agent_equipment"
PACKAGE_NAMES = (
    "__init__.py",
    "_json_schema.py",
    "authoring.py",
    "authorization.py",
    "canonical.py",
    "discovery.py",
    "execution_authority.py",
    "inventory.py",
    "model.py",
    "plan_action_set.py",
    "resolver.py",
    "secrets.py",
    "source_resolution.py",
    "updater.py",
    "validator.py",
)
MANIFEST_PATHS = (
    "bin/agent-equipment",
    *(f"lib/agent-equipment/agent_equipment/{name}" for name in PACKAGE_NAMES),
    *(f"lib/agent-equipment/schemas/{name}" for name in SCHEMA_NAMES),
)
SUBPROCESS_TIMEOUT_SECONDS = 30.0


class InstallationTests(unittest.TestCase):
    def environment(
        self,
        root: Path,
        destination: Path,
    ) -> tuple[dict[str, str], list[str]]:
        runtime = root / "runtime"
        runtime.mkdir()
        config = runtime / "chezmoi.toml"
        environment = os.environ | {
            "HOME": str(destination),
            "XDG_CACHE_HOME": str(runtime / "cache"),
            "XDG_CONFIG_HOME": str(destination / ".config"),
            "XDG_DATA_HOME": str(destination / ".local/share"),
            "XDG_STATE_HOME": str(destination / ".local/state"),
            "CHEZMOI_CONFIG_FILE": str(config),
        }
        arguments = [
            "-D",
            str(destination),
            "-c",
            str(config),
            "--cache",
            str(runtime / "cache"),
            "--persistent-state",
            str(runtime / "state.boltdb"),
            "--no-tty",
        ]
        return environment, arguments

    def test_authored_config_is_exactly_the_reviewed_proposal(self) -> None:
        for installed_source, proposal in CONFIG_SOURCES.items():
            with self.subTest(source=installed_source.name):
                self.assertEqual(installed_source.read_bytes(), proposal.read_bytes())

    def test_installed_schema_sources_equal_authoritative_schemas(self) -> None:
        for name in SCHEMA_NAMES:
            with self.subTest(schema=name):
                self.assertEqual(
                    (SCHEMA_SOURCE_ROOT / name).read_bytes(),
                    (DOCUMENTS / name).read_bytes(),
                )

    def test_package_source_inventory_is_closed(self) -> None:
        self.assertEqual(
            tuple(path.name for path in sorted(PACKAGE_SOURCE_ROOT.glob("*.py"))),
            PACKAGE_NAMES,
        )
        handoff = HANDOFF.read_text(encoding="utf-8")
        for name in PACKAGE_NAMES:
            with self.subTest(handoff_source=name):
                self.assertIn(
                    "home/private_dot_local/lib/agent-equipment/"
                    f"agent_equipment/{name}",
                    handoff,
                )

    def test_chezmoi_installs_exact_files_and_leaves_runtime_state_unmanaged(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "home with spaces"
            destination.mkdir()
            environment, arguments = self.environment(root, destination)

            initialized = subprocess.run(
                ["chezmoi", "-S", str(SOURCE), *arguments, "init"],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            self.assertNotIn("inconsistent state", initialized.stderr)

            source_to_target = {
                **{
                    source: destination / ".config/agent-equipment" / source.name
                    for source in CONFIG_SOURCES
                },
                LAUNCHER_SOURCE: destination / ".local/bin/agent-equipment",
                **{
                    PACKAGE_SOURCE_ROOT / name: destination
                    / ".local/lib/agent-equipment/agent_equipment"
                    / name
                    for name in PACKAGE_NAMES
                },
                **{
                    SCHEMA_SOURCE_ROOT / name: destination
                    / ".local/lib/agent-equipment/schemas"
                    / name
                    for name in SCHEMA_NAMES
                },
            }
            applied = subprocess.run(
                [
                    "chezmoi",
                    "-S",
                    str(SOURCE),
                    *arguments,
                    "--source-path",
                    "--refresh-externals=never",
                    "apply",
                    "--parent-dirs",
                    *map(str, source_to_target),
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertNotIn("inconsistent state", applied.stderr)

            for source, target in source_to_target.items():
                with self.subTest(source=source.relative_to(SOURCE)):
                    resolved_target = subprocess.run(
                        [
                            "chezmoi",
                            "-S",
                            str(SOURCE),
                            *arguments,
                            "target-path",
                            "--source-path",
                            str(source),
                        ],
                        env=environment,
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=SUBPROCESS_TIMEOUT_SECONDS,
                    ).stdout.strip()
                    self.assertEqual(Path(resolved_target), target)
                    self.assertEqual(target.read_bytes(), source.read_bytes())
                    expected_mode = 0o755 if source == LAUNCHER_SOURCE else 0o644
                    self.assertEqual(stat.S_IMODE(target.stat().st_mode), expected_mode)

            self.assertEqual(
                stat.S_IMODE((destination / ".local").stat().st_mode),
                0o700,
            )
            for directory in (
                destination / ".local/bin",
                destination / ".local/lib",
                destination / ".local/lib/agent-equipment",
                destination / ".local/lib/agent-equipment/agent_equipment",
                destination / ".local/lib/agent-equipment/schemas",
            ):
                with self.subTest(directory=directory.relative_to(destination)):
                    self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o755)

            package_root = destination / ".local/lib/agent-equipment"
            manifest_result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    "-c",
                    (
                        "import json, sys; "
                        f"sys.path.insert(0, {str(package_root)!r}); "
                        "from agent_equipment import "
                        "build_installed_implementation_manifest; "
                        "manifest = build_installed_implementation_manifest(); "
                        "print(json.dumps({"
                        "'runtime_identity': manifest.runtime_identity, "
                        "'paths': [entry.path for entry in manifest.files]}))"
                    ),
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )
            self.assertEqual(manifest_result.returncode, 0, manifest_result.stderr)
            installed_manifest = json.loads(manifest_result.stdout)
            self.assertEqual(
                installed_manifest["runtime_identity"],
                "cpython:"
                f"{sys.version_info.major}.{sys.version_info.minor}."
                f"{sys.version_info.micro}",
            )
            self.assertEqual(tuple(installed_manifest["paths"]), MANIFEST_PATHS)

            managed = subprocess.run(
                ["chezmoi", "-S", str(SOURCE), *arguments, "managed"],
                env=environment,
                capture_output=True,
                text=True,
                check=True,
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            ).stdout.splitlines()
            self.assertIn(".config/agent-equipment/catalog-v1.json", managed)
            for runtime_path in (
                ".config/agent-equipment/inventory.json",
                ".local/state/agent-equipment/inventory.json",
                ".local/state/agent-equipment/checkpoints",
            ):
                with self.subTest(unmanaged=runtime_path):
                    self.assertNotIn(runtime_path, managed)


if __name__ == "__main__":
    unittest.main()
