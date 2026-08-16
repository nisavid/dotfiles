from __future__ import annotations

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
            "    assert manifest == 'fixture-manifest'\n"
            f"    assert Path({str(self.manifest_marker)!r}).exists()\n"
            f"    subprocess.run([{str(self.native_fake)!r}], check=True)\n"
            f"    Path({str(self.observation_marker)!r}).touch()\n"
            f"    Path({str(self.checkpoint_marker)!r}).touch()\n"
            "    return 0\n",
            encoding="utf-8",
        )
        for name in PACKAGE_NAMES[1:]:
            (self.package_dir / name).write_text("", encoding="utf-8")
        schema_dir = self.install_root / "lib/agent-equipment/schemas"
        schema_dir.mkdir()
        for name in SCHEMA_NAMES:
            (schema_dir / name).write_text("{}\n", encoding="utf-8")

    def emulated_interpreter(
        self,
        *,
        implementation: str,
        version: tuple[int, int, int],
    ) -> Path:
        fake_bin = self.root / f"fake-{implementation}-{version[0]}{version[1]}"
        fake_bin.mkdir()
        interpreter = fake_bin / "python3"
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
                sys.implementation = types.SimpleNamespace(name={implementation!r})
                sys.version_info = {version!r}
                sys.flags = types.SimpleNamespace(
                    isolated=1,
                    dont_write_bytecode=1,
                    no_site=1,
                )
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

    def test_direct_python_without_isolation_exits_before_candidate_import(
        self,
    ) -> None:
        result = subprocess.run(
            [sys.executable, str(self.launcher)],
            capture_output=True,
            text=True,
            check=False,
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
