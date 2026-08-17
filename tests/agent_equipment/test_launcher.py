from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_SOURCE = ROOT / "home/private_dot_local/bin/executable_agent-equipment"
PACKAGE_SOURCE_ROOT = (
    ROOT / "home/private_dot_local/lib/agent-equipment/agent_equipment"
)
SCHEMA_SOURCE_ROOT = ROOT / "home/private_dot_local/lib/agent-equipment/schemas"
PACKAGE_NAMES = (
    "__init__.py",
    "_json_schema.py",
    "canonical.py",
    "model.py",
    "secrets.py",
    "validator.py",
)
SCHEMA_NAMES = (
    "acceptance-evidence-v1.schema.json",
    "adapter-contract-v1.schema.json",
    "captured-state-v1.schema.json",
    "catalog-v1.schema.json",
    "execution-authority-v1.schema.json",
    "lock-v1.schema.json",
    "plan-action-set-v1.schema.json",
)
MANIFEST_PATHS = (
    "bin/agent-equipment",
    *(f"lib/agent-equipment/agent_equipment/{name}" for name in PACKAGE_NAMES),
    *(f"lib/agent-equipment/schemas/{name}" for name in SCHEMA_NAMES),
)
SUBPROCESS_TIMEOUT_SECONDS = 30.0


class LauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.install_root = self.root / "installed path with spaces"
        self.bin_dir = self.install_root / "bin"
        self.package_dir = self.install_root / "lib/agent-equipment/agent_equipment"
        self.bin_dir.mkdir(parents=True)
        self.package_dir.mkdir(parents=True)
        self.launcher = self.bin_dir / "agent-equipment"
        self.launcher.write_bytes(LAUNCHER_SOURCE.read_bytes())
        self.launcher.chmod(0o700)
        self.import_marker = self.root / "candidate-imported"
        self.manifest_marker = self.root / "manifest-built"
        self.native_marker = self.root / "native-fake-called"
        self.observation_marker = self.root / "observation-written"
        self.checkpoint_marker = self.root / "checkpoint-written"
        self.native_fake = self.root / "native-fake"
        self.native_fake.write_text(
            f"#!/bin/sh\n: > {str(self.native_marker)!r}\n",
            encoding="utf-8",
        )
        self.native_fake.chmod(0o700)
        (self.package_dir / "__init__.py").write_text(
            "import subprocess\n"
            "from pathlib import Path\n"
            f"Path({str(self.import_marker)!r}).touch()\n"
            "def build_installed_implementation_manifest():\n"
            f"    Path({str(self.manifest_marker)!r}).touch()\n"
            "    return 'fixture-manifest'\n"
            "def main(manifest):\n"
            "    assert manifest.schema_version == "
            "'agent-equipment-installed-implementation/v1'\n"
            f"    assert Path({str(self.manifest_marker)!r}).exists()\n"
            f"    subprocess.run([{str(self.native_fake)!r}], check=True)\n"
            f"    Path({str(self.observation_marker)!r}).touch()\n"
            f"    Path({str(self.checkpoint_marker)!r}).touch()\n"
            "    return 0\n",
            encoding="utf-8",
        )
        for name in PACKAGE_NAMES[1:]:
            (self.package_dir / name).write_text("", encoding="utf-8")
        (self.package_dir / "model.py").write_text(
            "from pathlib import Path\n"
            "class InstalledFile:\n"
            "    def __init__(self, path, digest):\n"
            "        self.path = path\n"
            "        self.digest = digest\n"
            "class InstalledImplementationManifest:\n"
            "    def __init__(self, schema_version, runtime_identity, "
            "runtime_executable_digest, files, digest):\n"
            "        self.schema_version = schema_version\n"
            "        self.runtime_identity = runtime_identity\n"
            "        self.runtime_executable_digest = runtime_executable_digest\n"
            "        self.files = files\n"
            "        self.digest = digest\n"
            f"        Path({str(self.manifest_marker)!r}).touch()\n",
            encoding="utf-8",
        )
        schema_dir = self.install_root / "lib/agent-equipment/schemas"
        schema_dir.mkdir()
        for name in SCHEMA_NAMES:
            (schema_dir / name).write_text("{}\n", encoding="utf-8")

    def emulated_interpreter(
        self,
        *,
        implementation: str,
        runtime_executable: Path | None = None,
        version: tuple[int, int, int],
    ) -> Path:
        fake_bin = self.root / f"fake-{implementation}-{version[0]}{version[1]}"
        fake_bin.mkdir()
        interpreter = fake_bin / "python3"
        selected_executable = str(runtime_executable or Path(sys.executable))
        interpreter.write_text(
            f"#!{sys.executable}\n"
            + textwrap.dedent(
                f"""\
                import pathlib
                import sys
                import types

                if sys.argv[1:4] != ["-I", "-B", "-S"]:
                    raise SystemExit("launcher did not request -I -B -S")
                launcher = sys.argv[4]
                sys.argv = [launcher, *sys.argv[5:]]
                implementation_values = {{
                    name: getattr(sys.implementation, name)
                    for name in dir(sys.implementation)
                    if not name.startswith("_")
                }}
                implementation_values["name"] = {implementation!r}
                sys.implementation = types.SimpleNamespace(**implementation_values)
                class EmulatedVersionInfo(tuple):
                    major = property(lambda value: value[0])
                    minor = property(lambda value: value[1])
                    micro = property(lambda value: value[2])

                sys.version_info = EmulatedVersionInfo({version!r})
                flag_values = {{
                    name: getattr(sys.flags, name)
                    for name in dir(sys.flags)
                    if not name.startswith("_")
                }}
                flag_values.update(
                    isolated=1,
                    dont_write_bytecode=1,
                    no_site=1,
                )
                sys.flags = types.SimpleNamespace(**flag_values)
                sys.executable = {selected_executable!r}
                namespace = {{"__file__": launcher, "__name__": "__main__"}}
                source = pathlib.Path(launcher).read_bytes()
                exec(compile(source, launcher, "exec"), namespace)
                """
            ),
            encoding="utf-8",
        )
        interpreter.chmod(0o700)
        return fake_bin

    def run_launcher(
        self,
        *,
        fake_bin: Path | None = None,
        cwd: Path | None = None,
        environment: dict[str, str] | None = None,
        launcher: Path | None = None,
        timeout: float = SUBPROCESS_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess[str]:
        path = os.environ.get("PATH", "")
        if fake_bin is not None:
            path = f"{fake_bin}{os.pathsep}{path}"
        return subprocess.run(
            [str(launcher or self.launcher)],
            cwd=cwd,
            env=(os.environ | {"PATH": path} | (environment or {})),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

    def test_old_cpython_exits_before_candidate_import(self) -> None:
        fake_bin = self.emulated_interpreter(
            implementation="cpython",
            version=(3, 11, 9),
        )

        result = self.run_launcher(fake_bin=fake_bin)

        self.assertNotEqual(result.returncode, 0)
        self.assert_no_candidate_effects()

    def test_absent_python_exits_before_candidate_import(self) -> None:
        empty_path = self.root / "empty-path"
        empty_path.mkdir()

        result = self.run_launcher(environment={"PATH": str(empty_path)})

        self.assertNotEqual(result.returncode, 0)
        self.assert_no_candidate_effects()

    def assert_no_candidate_effects(self) -> None:
        for marker in (
            self.import_marker,
            self.manifest_marker,
            self.native_marker,
            self.observation_marker,
            self.checkpoint_marker,
        ):
            with self.subTest(marker=marker.name):
                self.assertFalse(marker.exists())

    def test_non_cpython_exits_before_candidate_import(self) -> None:
        fake_bin = self.emulated_interpreter(
            implementation="pypy",
            version=(3, 12, 4),
        )

        result = self.run_launcher(fake_bin=fake_bin)

        self.assertNotEqual(result.returncode, 0)
        self.assert_no_candidate_effects()

    def test_runtime_over_256_mebibytes_fails_redacted_before_import(self) -> None:
        oversized_runtime = self.root / "oversized-python-runtime"
        with oversized_runtime.open("wb") as stream:
            stream.truncate((256 * 1024 * 1024) + 1)
        fake_bin = self.emulated_interpreter(
            implementation="cpython",
            runtime_executable=oversized_runtime,
            version=(3, 12, 4),
        )

        result = self.run_launcher(fake_bin=fake_bin)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            "agent-equipment: installed implementation manifest is invalid\n",
        )
        self.assert_no_candidate_effects()

    def test_extra_import_root_entry_fails_before_candidate_import(self) -> None:
        shadow_marker = self.root / "shadow-imported"
        shadow = self.install_root / "lib/agent-equipment/subprocess.py"
        shadow.write_text(
            f"from pathlib import Path\nPath({str(shadow_marker)!r}).touch()\n",
            encoding="utf-8",
        )

        result = self.run_launcher()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            "agent-equipment: installed implementation manifest is invalid\n",
        )
        self.assertFalse(shadow_marker.exists())
        self.assert_no_candidate_effects()

    def test_malformed_closed_package_import_fails_redacted_before_main(
        self,
    ) -> None:
        (self.package_dir / "__init__.py").write_text(
            "this is not valid Python !!!\n",
            encoding="utf-8",
        )

        result = self.run_launcher()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            "agent-equipment: installed implementation manifest is invalid\n",
        )
        self.assert_no_candidate_effects()

    def test_missing_package_precheck_fails_with_redacted_bootstrap_error(
        self,
    ) -> None:
        (self.package_dir / "__init__.py").unlink()

        result = self.run_launcher()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            "agent-equipment: installed implementation manifest is invalid\n",
        )
        self.assert_no_candidate_effects()

    def test_package_fifo_fails_promptly_and_redacted_before_import(self) -> None:
        fifo_source = self.package_dir / "secrets.py"
        fifo_source.unlink()
        os.mkfifo(fifo_source)

        result = self.run_launcher(timeout=2.0)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            "agent-equipment: installed implementation manifest is invalid\n",
        )
        self.assert_no_candidate_effects()

    def test_launcher_resolution_failure_uses_redacted_bootstrap_error(self) -> None:
        cycle_a = self.root / "launcher-cycle-a"
        cycle_b = self.root / "launcher-cycle-b"
        cycle_a.symlink_to(cycle_b)
        cycle_b.symlink_to(cycle_a)
        bootstrap = (
            "from pathlib import Path\n"
            f"source = Path({str(self.launcher)!r}).read_bytes()\n"
            f"reported_path = {str(cycle_a)!r}\n"
            "namespace = {'__file__': reported_path, '__name__': '__main__'}\n"
            "exec(compile(source, reported_path, 'exec'), namespace)\n"
        )

        result = subprocess.run(
            [sys.executable, "-I", "-B", "-S", "-c", bootstrap],
            capture_output=True,
            text=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            "agent-equipment: installed implementation manifest is invalid\n",
        )
        self.assert_no_candidate_effects()

    def test_package_source_over_one_mebibyte_fails_redacted_before_import(
        self,
    ) -> None:
        oversized_source = self.package_dir / "secrets.py"
        with oversized_source.open("wb") as stream:
            stream.truncate((1024 * 1024) + 1)

        result = self.run_launcher()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            "agent-equipment: installed implementation manifest is invalid\n",
        )
        self.assert_no_candidate_effects()

    def test_schema_over_512_kibibytes_fails_redacted_before_import(self) -> None:
        oversized_schema = (
            self.install_root / "lib/agent-equipment/schemas/catalog-v1.schema.json"
        )
        with oversized_schema.open("wb") as stream:
            stream.truncate((512 * 1024) + 1)

        result = self.run_launcher()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            "agent-equipment: installed implementation manifest is invalid\n",
        )
        self.assert_no_candidate_effects()

    def test_launcher_over_256_kibibytes_fails_redacted_before_import(self) -> None:
        target_size = (256 * 1024) + 1
        padding_size = target_size - self.launcher.stat().st_size
        self.assertGreater(padding_size, 2)
        with self.launcher.open("ab") as stream:
            stream.write(b"\n#" + (b"x" * (padding_size - 2)))

        result = self.run_launcher()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            "agent-equipment: installed implementation manifest is invalid\n",
        )
        self.assert_no_candidate_effects()

    def test_aggregate_capture_over_eight_mebibytes_fails_before_import(
        self,
    ) -> None:
        package_target = 900 * 1024
        for name in PACKAGE_NAMES:
            path = self.package_dir / name
            padding_size = package_target - path.stat().st_size
            self.assertGreater(padding_size, 2)
            with path.open("ab") as stream:
                stream.write(b"\n#" + (b"x" * (padding_size - 2)))

        schema_target = 400 * 1024
        schema_dir = self.install_root / "lib/agent-equipment/schemas"
        for name in SCHEMA_NAMES:
            path = schema_dir / name
            padding_size = schema_target - path.stat().st_size
            self.assertGreater(padding_size, 0)
            with path.open("ab") as stream:
                stream.write(b" " * padding_size)

        aggregate_size = sum(
            (self.install_root / relative_path).stat().st_size
            for relative_path in MANIFEST_PATHS
        )
        self.assertGreater(aggregate_size, 8 * 1024 * 1024)

        result = self.run_launcher()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            "agent-equipment: installed implementation manifest is invalid\n",
        )
        self.assert_no_candidate_effects()

    def test_candidate_import_cannot_reseal_changed_installed_bytes(self) -> None:
        (self.package_dir / "__init__.py").write_text(
            "from pathlib import Path\n"
            f"Path({str(self.import_marker)!r}).touch()\n"
            "Path(__file__).with_name('secrets.py').write_text('changed\\n')\n"
            "def build_installed_implementation_manifest():\n"
            f"    Path({str(self.manifest_marker)!r}).touch()\n"
            "    return 'coordinated-reseal'\n"
            "def main(manifest):\n"
            f"    Path({str(self.native_marker)!r}).touch()\n"
            f"    Path({str(self.observation_marker)!r}).touch()\n"
            f"    Path({str(self.checkpoint_marker)!r}).touch()\n"
            "    return 0\n",
            encoding="utf-8",
        )

        result = self.run_launcher()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            "agent-equipment: installed implementation manifest is invalid\n",
        )
        self.assertTrue(self.import_marker.exists())
        for marker in (
            self.manifest_marker,
            self.native_marker,
            self.observation_marker,
            self.checkpoint_marker,
        ):
            with self.subTest(marker=marker.name):
                self.assertFalse(marker.exists())

    def test_main_receives_launcher_owned_prebound_manifest(self) -> None:
        manifest_output = self.root / "received-manifest.json"
        (self.package_dir / "model.py").write_text(
            "class InstalledFile:\n"
            "    def __init__(self, path, digest):\n"
            "        self.path = path\n"
            "        self.digest = digest\n"
            "class InstalledImplementationManifest:\n"
            "    def __init__(self, schema_version, runtime_identity, "
            "runtime_executable_digest, files, digest):\n"
            "        self.schema_version = schema_version\n"
            "        self.runtime_identity = runtime_identity\n"
            "        self.runtime_executable_digest = runtime_executable_digest\n"
            "        self.files = files\n"
            "        self.digest = digest\n",
            encoding="utf-8",
        )
        (self.package_dir / "__init__.py").write_text(
            "import json\n"
            "from pathlib import Path\n"
            f"Path({str(self.import_marker)!r}).touch()\n"
            "def build_installed_implementation_manifest():\n"
            f"    Path({str(self.manifest_marker)!r}).touch()\n"
            "    raise AssertionError('candidate builder must not run')\n"
            "def main(manifest):\n"
            f"    Path({str(manifest_output)!r}).write_text(json.dumps({{\n"
            "        'schema_version': manifest.schema_version,\n"
            "        'runtime_identity': manifest.runtime_identity,\n"
            "        'runtime_executable_digest': "
            "manifest.runtime_executable_digest,\n"
            "        'files': [\n"
            "            {'path': item.path, 'digest': item.digest}\n"
            "            for item in manifest.files\n"
            "        ],\n"
            "        'digest': manifest.digest,\n"
            "    }))\n"
            "    return 0\n",
            encoding="utf-8",
        )
        expected_files = [
            {
                "path": relative,
                "digest": "sha256:"
                + hashlib.sha256(
                    (self.install_root / relative).read_bytes()
                ).hexdigest(),
            }
            for relative in MANIFEST_PATHS
        ]
        expected_payload = {
            "schema_version": "agent-equipment-installed-implementation/v1",
            "runtime_identity": (
                f"cpython:{sys.version_info.major}.{sys.version_info.minor}."
                f"{sys.version_info.micro}"
            ),
            "runtime_executable_digest": "sha256:"
            + hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest(),
            "files": expected_files,
        }
        expected_manifest = expected_payload | {
            "digest": "sha256:"
            + hashlib.sha256(
                json.dumps(
                    expected_payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
        }

        result = self.run_launcher()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.manifest_marker.exists())
        self.assertEqual(json.loads(manifest_output.read_text()), expected_manifest)

    def test_import_executes_captured_bytes_before_rejecting_path_replacement(
        self,
    ) -> None:
        captured_source = self.root / "captured-validator-source"
        replacement_imported = self.root / "replacement-validator-imported"
        replacement_source = (
            "from pathlib import Path\n"
            f"Path({str(replacement_imported)!r}).touch()\n"
            "SOURCE = 'path'\n"
        )
        (self.package_dir / "validator.py").write_text(
            "SOURCE = 'captured'\n",
            encoding="utf-8",
        )
        (self.package_dir / "__init__.py").write_text(
            "import os\n"
            "from pathlib import Path\n"
            f"Path({str(self.import_marker)!r}).touch()\n"
            "validator_path = Path(__file__).with_name('validator.py')\n"
            "replacement = validator_path.with_name('.validator-replacement')\n"
            f"replacement.write_text({replacement_source!r})\n"
            "os.replace(replacement, validator_path)\n"
            "from . import validator\n"
            f"Path({str(captured_source)!r}).write_text(validator.SOURCE)\n"
            "def build_installed_implementation_manifest():\n"
            f"    Path({str(self.manifest_marker)!r}).touch()\n"
            "    return 'coordinated-reseal'\n"
            "def main(manifest):\n"
            f"    Path({str(self.native_marker)!r}).touch()\n"
            "    return 0\n",
            encoding="utf-8",
        )

        result = self.run_launcher()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            "agent-equipment: installed implementation manifest is invalid\n",
        )
        self.assertEqual(captured_source.read_text(), "captured")
        self.assertFalse(replacement_imported.exists())
        self.assertFalse(self.manifest_marker.exists())
        self.assertFalse(self.native_marker.exists())

    def test_direct_python_without_isolation_exits_before_candidate_import(
        self,
    ) -> None:
        result = subprocess.run(
            [sys.executable, str(self.launcher)],
            capture_output=True,
            text=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assert_no_candidate_effects()

    @unittest.skipUnless(
        sys.implementation.name == "cpython" and sys.version_info >= (3, 12),
        "requires an external CPython 3.12+ interpreter",
    )
    def test_candidate_package_import_runs_with_site_disabled(self) -> None:
        package_source = (self.package_dir / "__init__.py").read_text(encoding="utf-8")
        (self.package_dir / "__init__.py").write_text(
            "import sys\nassert sys.flags.no_site\n" + package_source,
            encoding="utf-8",
        )

        result = self.run_launcher()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.import_marker.exists())

    @unittest.skipUnless(
        sys.implementation.name == "cpython" and sys.version_info >= (3, 12),
        "requires an external CPython 3.12+ interpreter",
    )
    def test_current_cpython_uses_only_installed_package_without_bytecode(
        self,
    ) -> None:
        poison_root = self.root / "poison"
        poison_package = poison_root / "agent_equipment"
        poison_package.mkdir(parents=True)
        cwd = self.root / "poison-cwd"
        cwd_package = cwd / "agent_equipment"
        cwd_package.mkdir(parents=True)
        pythonpath_marker = self.root / "pythonpath-imported"
        cwd_marker = self.root / "cwd-imported"
        sitecustomize_marker = self.root / "sitecustomize-imported"
        (poison_package / "__init__.py").write_text(
            f"from pathlib import Path\nPath({str(pythonpath_marker)!r}).touch()\n",
            encoding="utf-8",
        )
        (cwd_package / "__init__.py").write_text(
            f"from pathlib import Path\nPath({str(cwd_marker)!r}).touch()\n",
            encoding="utf-8",
        )
        (poison_root / "sitecustomize.py").write_text(
            f"from pathlib import Path\nPath({str(sitecustomize_marker)!r}).touch()\n",
            encoding="utf-8",
        )

        result = self.run_launcher(
            cwd=cwd,
            environment={"PYTHONPATH": str(poison_root)},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        for marker in (
            self.import_marker,
            self.manifest_marker,
            self.native_marker,
            self.observation_marker,
            self.checkpoint_marker,
        ):
            with self.subTest(installed_marker=marker.name):
                self.assertTrue(marker.exists())
        for marker in (pythonpath_marker, cwd_marker, sitecustomize_marker):
            with self.subTest(poison_marker=marker.name):
                self.assertFalse(marker.exists())
        self.assertEqual(list(self.root.rglob("__pycache__")), [])

    @unittest.skipUnless(
        sys.implementation.name == "cpython" and sys.version_info >= (3, 12),
        "requires an external CPython 3.12+ interpreter",
    )
    def test_venv_sitecustomize_cannot_run_before_launcher_gate(self) -> None:
        virtual_environment = self.root / "venv"
        venv.EnvBuilder(with_pip=False).create(virtual_environment)
        site_packages = next(
            (virtual_environment / "lib").glob("python*/site-packages")
        )
        sitecustomize_marker = self.root / "venv-sitecustomize-imported"
        (site_packages / "sitecustomize.py").write_text(
            f"from pathlib import Path\nPath({str(sitecustomize_marker)!r}).touch()\n",
            encoding="utf-8",
        )

        result = self.run_launcher(fake_bin=virtual_environment / "bin")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(sitecustomize_marker.exists())

    @unittest.skipUnless(
        sys.implementation.name == "cpython" and sys.version_info >= (3, 12),
        "requires an external CPython 3.12+ interpreter",
    )
    def test_symlinked_launcher_resolves_its_installed_package(self) -> None:
        launcher_link = self.root / "agent-equipment-link"
        launcher_link.symlink_to(self.launcher)

        result = self.run_launcher(launcher=launcher_link)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.import_marker.exists())

    @unittest.skipUnless(
        sys.implementation.name == "cpython" and sys.version_info >= (3, 12),
        "requires an external CPython 3.12+ interpreter",
    )
    def test_current_cpython_runs_only_installed_real_package_fail_closed(
        self,
    ) -> None:
        self.install_real_package()
        poison_root = self.root / "real-package-poison"
        poison_package = poison_root / "agent_equipment"
        poison_package.mkdir(parents=True)
        cwd = self.root / "real-package-cwd"
        (cwd / "agent_equipment").mkdir(parents=True)
        pythonpath_marker = self.root / "real-pythonpath-imported"
        cwd_marker = self.root / "real-cwd-imported"
        sitecustomize_marker = self.root / "real-sitecustomize-imported"
        (poison_package / "__init__.py").write_text(
            f"from pathlib import Path\nPath({str(pythonpath_marker)!r}).touch()\n",
            encoding="utf-8",
        )
        (cwd / "agent_equipment/__init__.py").write_text(
            f"from pathlib import Path\nPath({str(cwd_marker)!r}).touch()\n",
            encoding="utf-8",
        )
        (poison_root / "sitecustomize.py").write_text(
            f"from pathlib import Path\nPath({str(sitecustomize_marker)!r}).touch()\n",
            encoding="utf-8",
        )
        runtime_home = self.root / "runtime-home"
        runtime_home.mkdir()
        native_bin = self.root / "native-bin"
        native_bin.mkdir()
        native_marker = self.root / "real-native-called"
        for command in ("claude", "codex", "cursor"):
            executable = native_bin / command
            executable.write_text(
                f"#!/bin/sh\n: > {str(native_marker)!r}\n",
                encoding="utf-8",
            )
            executable.chmod(0o700)

        result = self.run_launcher(
            fake_bin=native_bin,
            cwd=cwd,
            environment={
                "HOME": str(runtime_home),
                "PYTHONPATH": str(poison_root),
            },
        )

        self.assertEqual(result.returncode, 64, result.stderr)
        self.assertEqual(
            result.stderr,
            "agent-equipment: no runtime commands are available\n",
        )
        for marker in (pythonpath_marker, cwd_marker, sitecustomize_marker):
            with self.subTest(poison_marker=marker.name):
                self.assertFalse(marker.exists())
        self.assertFalse(native_marker.exists())
        self.assertEqual(list(runtime_home.iterdir()), [])
        self.assertEqual(list(self.root.rglob("__pycache__")), [])

    @unittest.skipUnless(
        sys.implementation.name == "cpython" and sys.version_info >= (3, 12),
        "requires an external CPython 3.12+ interpreter",
    )
    def test_runtime_validation_uses_prebound_schema_bytes(self) -> None:
        self.install_real_package()
        validation_marker = self.root / "schema-validation-result"
        catalog = ROOT / "docs/agent-equipment/initial-catalog.proposed.json"
        lock = ROOT / "docs/agent-equipment/initial-lock.proposed.json"
        schema = (
            self.install_root / "lib/agent-equipment/schemas/catalog-v1.schema.json"
        )
        package_source = (self.package_dir / "__init__.py").read_text(encoding="utf-8")
        (self.package_dir / "__init__.py").write_text(
            package_source
            + "\nimport json\n"
            + "def main(installed_implementation_manifest):\n"
            + "    Path = __import__('pathlib').Path\n"
            + f"    Path({str(schema)!r}).write_text('{{}}\\n')\n"
            + "    result = validate_catalog_lock(\n"
            + f"        json.loads(Path({str(catalog)!r}).read_text()),\n"
            + f"        json.loads(Path({str(lock)!r}).read_text()),\n"
            + "    )\n"
            + f"    Path({str(validation_marker)!r}).write_text(\n"
            + "        'valid' if result.model is not None else 'invalid'\n"
            + "    )\n"
            + "    return 0 if result.model is not None else 1\n",
            encoding="utf-8",
        )

        result = self.run_launcher()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(validation_marker.read_text(), "valid")

    def install_real_package(self) -> None:
        shutil.rmtree(self.package_dir)
        shutil.copytree(
            PACKAGE_SOURCE_ROOT,
            self.package_dir,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        shutil.copytree(
            SCHEMA_SOURCE_ROOT,
            self.install_root / "lib/agent-equipment/schemas",
            dirs_exist_ok=True,
        )

    @unittest.skipUnless(
        sys.implementation.name == "cpython" and sys.version_info >= (3, 12),
        "requires an external CPython 3.12+ interpreter",
    )
    def test_missing_manifest_entry_fails_closed_before_main(self) -> None:
        self.install_real_package()
        missing = (
            self.install_root
            / "lib/agent-equipment/schemas/plan-action-set-v1.schema.json"
        )
        missing.unlink()

        result = self.run_launcher()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            "agent-equipment: installed implementation manifest is invalid\n",
        )
        for marker in (
            self.native_marker,
            self.observation_marker,
            self.checkpoint_marker,
        ):
            with self.subTest(marker=marker.name):
                self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
