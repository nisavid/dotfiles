"""Render desktop bindings in a disposable home without account or service access."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = {
    "private_dot_local/bin/executable_proton-drive-desktop": ".local/bin/proton-drive-desktop",
    "dot_config/systemd/user/proton-drive-desktop.service": ".config/systemd/user/proton-drive-desktop.service",
    "private_dot_local/private_share/applications/proton-drive.desktop.tmpl": ".local/share/applications/proton-drive.desktop",
}


class DesktopDeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("chezmoi"):
            raise RuntimeError("chezmoi is required for desktop deployment qualification")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"
        self.home = self.root / "home with spaces 'quote\" $cash` \\path"
        self.source.mkdir()
        self.home.mkdir()
        for name in (*PAYLOAD, ".chezmoiignore"):
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "home" / name, target)
        self.config = self.root / "chezmoi.toml"
        self.config.write_text("")
        self.env = {
            "HOME": str(self.home), "PATH": os.environ["PATH"],
            "LANG": "C.UTF-8", "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local/share"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
        }

    def chezmoi(self, *args):
        return subprocess.run([
            shutil.which("chezmoi"), "--source", str(self.source),
            "--destination", str(self.home), "--config", str(self.config),
            "--cache", str(self.root / "cache"), "--persistent-state",
            str(self.root / "state.boltdb"), "--no-tty", *args,
        ], env=self.env, cwd=self.root, text=True, capture_output=True)

    def platform(self, name):
        ignore = self.source / ".chezmoiignore"
        result = self.chezmoi("execute-template", "--override-data",
                              '{"chezmoi":{"os":"' + name + '"}}',
                              ignore.read_text())
        self.assertEqual(result.returncode, 0, result.stderr)
        ignore.write_text(result.stdout)

    def documented_wiring(self, action):
        guide = (ROOT / "docs/PROTON_DRIVE.md").read_text()
        marker = f"# proton-drive-custom-xdg-links: {action}"
        lines = guide.splitlines()
        start = next(
            index for index, line in enumerate(lines) if line.strip() == marker
        )
        self.assertEqual("```sh", lines[start - 1].strip())
        end = next(
            index for index in range(start + 1, len(lines))
            if lines[index].strip() == "```"
        )
        return textwrap.dedent("\n".join(lines[start:end])) + "\n"

    def documented_effective_unit_qualification(self):
        guide = (ROOT / "docs/PROTON_DRIVE.md").read_text()
        marker = "# proton-drive-effective-unit: qualify"
        lines = guide.splitlines()
        start = next(
            index for index, line in enumerate(lines) if line.strip() == marker
        )
        self.assertEqual("```sh", lines[start - 1].strip())
        end = next(
            index for index in range(start + 1, len(lines))
            if lines[index].strip() == "```"
        )
        return textwrap.dedent("\n".join(lines[start:end])) + "\n"

    def documented_baloo_setup(self):
        guide = (ROOT / "docs/PROTON_DRIVE.md").read_text()
        marker = "# proton-drive-baloo: setup"
        lines = guide.splitlines()
        start = next(
            index for index, line in enumerate(lines) if line.strip() == marker
        )
        self.assertEqual("```sh", lines[start - 1].strip())
        end = next(
            index for index in range(start + 1, len(lines))
            if lines[index].strip() == "```"
        )
        return textwrap.dedent("\n".join(lines[start:end])) + "\n"

    def documented_recovery_evidence_inspector(self):
        guide = (ROOT / "docs/PROTON_DRIVE.md").read_text()
        marker = "# proton-drive-recovery-evidence: inspect"
        lines = guide.splitlines()
        marker_index = next(
            index for index, line in enumerate(lines) if line.strip() == marker
        )
        self.assertIn("<<'PY'", lines[marker_index + 1])
        start = marker_index + 2
        end = next(
            index for index in range(start, len(lines))
            if lines[index].strip() == "PY"
        )
        return textwrap.dedent("\n".join(lines[start:end])) + "\n"

    def run_wiring(self, action, environment):
        return subprocess.run(
            ["/bin/sh"], input=self.documented_wiring(action), env=environment,
            cwd=self.root, text=True, capture_output=True,
        )

    def run_documented_root_selection(self, action, selected_root):
        wiring = self.documented_wiring(action)
        function_start = wiring.index("normalize_discovery_root() {")
        selection_end = wiring.index("\n\nfor discovery_destination", function_start)
        script = wiring[function_start:selection_end]
        script += '\nprintf \'%s\\n%s\\n\' "$unit_link" "$launcher_link"\n'
        environment = {
            **self.env,
            "XDG_CONFIG_HOME": selected_root,
            "XDG_DATA_HOME": selected_root,
        }
        return subprocess.run(
            ["/bin/sh"], input=script, env=environment, cwd=self.root,
            text=True, capture_output=True,
        )

    def run_effective_unit_qualification(self, environment):
        return subprocess.run(
            ["/bin/sh"], input=self.documented_effective_unit_qualification(),
            env=environment, cwd=ROOT, text=True, capture_output=True,
        )

    def run_baloo_setup(self, environment):
        return subprocess.run(
            ["/bin/sh"], input=self.documented_baloo_setup(),
            env=environment, cwd=self.root, text=True, capture_output=True,
        )

    def baloo_fixture(self):
        fake_bin = self.root / "fake-baloo-bin"
        fake_bin.mkdir(exist_ok=True)
        balooctl = fake_bin / "balooctl6"
        balooctl.write_text(textwrap.dedent("""\
            #!/bin/sh
            printf '%s\\n' "$*" >> "$SYNTHETIC_BALOO_CALLS"
            case "$1 $2 $3" in
              'config add excludeFolders')
                grep -F -x -q -- "$4" "$SYNTHETIC_BALOO_STATE" 2>/dev/null ||
                  printf '%s\\n' "$4" >> "$SYNTHETIC_BALOO_STATE"
                ;;
              'config list excludeFolders')
                cat "$SYNTHETIC_BALOO_STATE"
                ;;
              *) exit 64 ;;
            esac
        """))
        balooctl.chmod(0o700)
        state = self.root / "baloo-state"
        calls = self.root / "baloo-calls"
        state.write_text("/existing/unrelated-exclusion\n")
        calls.unlink(missing_ok=True)
        return {
            **self.env,
            "PATH": f"{fake_bin}:{self.env['PATH']}",
            "SYNTHETIC_BALOO_STATE": str(state),
            "SYNTHETIC_BALOO_CALLS": str(calls),
        }, state, calls

    def test_documented_baloo_setup_creates_once_and_preserves_exclusions(self):
        environment, state, calls = self.baloo_fixture()
        data_home = self.root / "XDG data with spaces"
        data_home.mkdir(mode=0o700)
        environment["XDG_DATA_HOME"] = str(data_home)
        managed_parent = data_home / "proton-drive-desktop"

        for _ in range(2):
            result = self.run_baloo_setup(environment)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual("", result.stderr)

        self.assertTrue(managed_parent.is_dir())
        self.assertEqual(0o700, managed_parent.stat().st_mode & 0o777)
        self.assertEqual(
            ["/existing/unrelated-exclusion", str(managed_parent)],
            state.read_text().splitlines(),
        )
        self.assertEqual(4, len(calls.read_text().splitlines()))

    def test_documented_baloo_setup_accepts_a_valid_existing_parent(self):
        environment, state, calls = self.baloo_fixture()
        data_home = self.root / "existing data"
        managed_parent = data_home / "proton-drive-desktop"
        managed_parent.mkdir(parents=True, mode=0o700)
        existing = managed_parent / "existing-evidence"
        existing.write_text("preserve me\n")
        environment["XDG_DATA_HOME"] = str(data_home)

        result = self.run_baloo_setup(environment)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual("preserve me\n", existing.read_text())
        self.assertEqual(
            ["/existing/unrelated-exclusion", str(managed_parent)],
            state.read_text().splitlines(),
        )
        self.assertEqual(2, len(calls.read_text().splitlines()))

    def test_documented_baloo_setup_rejects_unsafe_paths_before_baloo(self):
        cases = ("symlink", "file", "unsafe-mode", "relative")
        for case in cases:
            with self.subTest(case=case):
                environment, state, calls = self.baloo_fixture()
                data_home = self.root / f"{case} data"
                if case == "relative":
                    environment["XDG_DATA_HOME"] = "relative/data"
                else:
                    data_home.mkdir(mode=0o700)
                    managed_parent = data_home / "proton-drive-desktop"
                    if case == "symlink":
                        target = self.root / "symlink target"
                        target.mkdir(exist_ok=True)
                        managed_parent.symlink_to(target, target_is_directory=True)
                    elif case == "file":
                        managed_parent.write_text("preserve file\n")
                    else:
                        managed_parent.mkdir(mode=0o755)
                    environment["XDG_DATA_HOME"] = str(data_home)

                result = self.run_baloo_setup(environment)

                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(calls.exists())
                self.assertEqual(
                    "/existing/unrelated-exclusion\n", state.read_text()
                )
                if case == "symlink":
                    self.assertTrue(managed_parent.is_symlink())
                elif case == "file":
                    self.assertEqual("preserve file\n", managed_parent.read_text())
                elif case == "unsafe-mode":
                    self.assertEqual(0o755, managed_parent.stat().st_mode & 0o777)

    def test_documented_baloo_setup_rejects_synthetic_identity_failures(self):
        cases = {
            "owner-mismatch": f"{os.getuid() + 1} 700\n",
            "malformed-identity": "unexpected stat output\n",
        }
        for case, stat_output in cases.items():
            with self.subTest(case=case):
                environment, state, calls = self.baloo_fixture()
                data_home = self.root / f"{case} data"
                managed_parent = data_home / "proton-drive-desktop"
                managed_parent.mkdir(parents=True, mode=0o700)
                evidence = managed_parent / "existing-evidence"
                evidence.write_text("preserve me\n")
                environment["XDG_DATA_HOME"] = str(data_home)
                fake_bin = Path(environment["PATH"].split(":", 1)[0])
                fake_stat = fake_bin / "stat"
                fake_stat.write_text(
                    f"#!/bin/sh\nprintf '%s\\n' '{stat_output.rstrip()}'\n"
                )
                fake_stat.chmod(0o700)

                result = self.run_baloo_setup(environment)

                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(calls.exists())
                self.assertEqual(
                    "/existing/unrelated-exclusion\n", state.read_text()
                )
                self.assertEqual("preserve me\n", evidence.read_text())

    def test_documented_baloo_setup_does_not_reuse_after_mkdir_failure(self):
        environment, state, calls = self.baloo_fixture()
        data_home = self.root / "mkdir failure data"
        data_home.mkdir(mode=0o700)
        environment["XDG_DATA_HOME"] = str(data_home)
        fake_bin = Path(environment["PATH"].split(":", 1)[0])
        fake_mkdir = fake_bin / "mkdir"
        fake_mkdir.write_text("#!/bin/sh\nexit 73\n")
        fake_mkdir.chmod(0o700)

        result = self.run_baloo_setup(environment)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(calls.exists())
        self.assertFalse((data_home / "proton-drive-desktop").exists())
        self.assertEqual("/existing/unrelated-exclusion\n", state.read_text())

    def test_linux_apply_installs_controls_without_activating_or_enrolling(self):
        self.platform("linux")
        marker = self.home / "existing-user-data"
        marker.write_text("preserve me\n")
        for _ in range(2):
            result = self.chezmoi("apply", "--force")
            self.assertEqual(result.returncode, 0, result.stderr)
        for source, target in PAYLOAD.items():
            if not source.endswith(".tmpl"):
                self.assertEqual((self.home / target).read_bytes(),
                                 (ROOT / "home" / source).read_bytes())
        self.assertTrue(os.access(self.home / ".local/bin/proton-drive-desktop", os.X_OK))
        self.assertEqual(marker.read_text(), "preserve me\n")
        self.assertEqual(sorted(str(p.relative_to(self.home)) for p in self.home.rglob("*")
                                if p.is_file() or p.is_symlink()),
                         sorted([*PAYLOAD.values(), "existing-user-data"]))

    def test_effective_unit_qualification_rejects_shadow_drop_ins_and_byte_drift(self):
        self.platform("linux")
        applied = self.chezmoi("apply", "--force")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        installed = self.home / ".config/systemd/user/proton-drive-desktop.service"
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        systemctl = fake_bin / "systemctl"
        systemctl.write_text(textwrap.dedent("""\
            #!/bin/sh
            case "$*" in
              *--property=FragmentPath*) printf '%s\n' "$SYNTHETIC_FRAGMENT" ;;
              *--property=DropInPaths*) printf '%s\n' "${SYNTHETIC_DROP_INS-}" ;;
              *) exit 64 ;;
            esac
        """))
        systemctl.chmod(0o700)
        environment = {
            **self.env,
            "PATH": f"{fake_bin}:{self.env['PATH']}",
            "SYNTHETIC_FRAGMENT": str(installed),
            "SYNTHETIC_DROP_INS": "",
        }

        clean = self.run_effective_unit_qualification(environment)
        self.assertEqual(clean.returncode, 0, clean.stderr)

        custom_root = self.root / "custom config"
        custom_fragment = custom_root / "systemd/user/proton-drive-desktop.service"
        custom_fragment.parent.mkdir(parents=True)
        custom_fragment.symlink_to(installed)
        custom = self.run_effective_unit_qualification({
            **environment,
            "SYNTHETIC_FRAGMENT": str(custom_fragment),
        })
        self.assertEqual(custom.returncode, 0, custom.stderr)

        shadow = self.root / "shadow/proton-drive-desktop.service"
        shadow.parent.mkdir()
        shadow.write_bytes(installed.read_bytes())
        shadowed = self.run_effective_unit_qualification({
            **environment,
            "SYNTHETIC_FRAGMENT": str(shadow),
        })
        self.assertNotEqual(shadowed.returncode, 0)

        overridden = self.run_effective_unit_qualification({
            **environment,
            "SYNTHETIC_DROP_INS": str(self.root / "override.conf"),
        })
        self.assertNotEqual(overridden.returncode, 0)

        installed.write_bytes(installed.read_bytes() + b"# drift\n")
        drifted = self.run_effective_unit_qualification(environment)
        self.assertNotEqual(drifted.returncode, 0)

    @unittest.skipUnless(os.uname().sysname == "Linux", "Linux desktop launcher")
    def test_launcher_finds_installed_command_without_local_bin_on_path(self):
        self.platform("linux")
        result = self.chezmoi("apply", "--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        executable = self.home / ".local/bin/proton-drive-desktop"
        executable.write_text(
            '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$PROTON_LAUNCH_TEST_RESULT"\n'
        )
        marker = self.root / "launcher-arguments"
        launcher = self.home / ".local/share/applications/proton-drive.desktop"
        result = subprocess.run(
            ["/usr/bin/gio", "launch", str(launcher)],
            env={**self.env, "PATH": "/usr/bin:/bin",
                 "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent-synthetic-bus",
                 "PROTON_LAUNCH_TEST_RESULT": str(marker)},
            cwd=self.root, text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if marker.exists() and marker.read_text() == "open\n":
                break
            time.sleep(0.01)
        self.assertTrue(marker.exists(), "launcher did not execute the installed command")
        self.assertEqual(marker.read_text(), "open\n")

    def test_documented_custom_xdg_links_are_conflict_safe_and_reversible(self):
        self.platform("linux")
        applied = self.chezmoi("apply", "--force")
        self.assertEqual(applied.returncode, 0, applied.stderr)

        custom_config = self.root / "custom config"
        custom_data = self.root / "custom data"
        unit_source = self.home / ".config/systemd/user/proton-drive-desktop.service"
        launcher_source = self.home / ".local/share/applications/proton-drive.desktop"
        unit_link = custom_config / "systemd/user/proton-drive-desktop.service"
        launcher_link = custom_data / "applications/proton-drive.desktop"

        unrelated = custom_data / "applications/keep.txt"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("preserve me\n")

        layouts = (
            ("both-custom", custom_config, custom_data),
            ("config-only", custom_config, None),
            ("data-only", None, custom_data),
            ("all-default", None, None),
        )
        for name, config_home, data_home in layouts:
            with self.subTest(layout=name):
                environment = {**self.env}
                environment.pop("XDG_CONFIG_HOME")
                environment.pop("XDG_DATA_HOME")
                if config_home is not None:
                    environment["XDG_CONFIG_HOME"] = str(config_home)
                if data_home is not None:
                    environment["XDG_DATA_HOME"] = str(data_home)
                destinations = (
                    (unit_source, unit_source if config_home is None else unit_link),
                    (launcher_source,
                     launcher_source if data_home is None else launcher_link),
                )

                for _ in range(2):
                    result = self.run_wiring("setup", environment)
                    self.assertEqual(result.returncode, 0, result.stderr)
                for source, destination in destinations:
                    self.assertTrue(source.is_file())
                    self.assertFalse(source.is_symlink())
                    if destination != source:
                        self.assertTrue(destination.is_symlink())
                        self.assertEqual(source, destination.resolve(strict=True))
                    self.assertEqual(source.read_bytes(), destination.read_bytes())

                for source_name in PAYLOAD:
                    source = self.source / source_name
                    source.write_bytes(source.read_bytes() + b"\n# disposable update\n")
                updated = self.chezmoi("apply", "--force")
                self.assertEqual(updated.returncode, 0, updated.stderr)
                for source, destination in destinations:
                    self.assertEqual(source.read_bytes(), destination.read_bytes())

                source_payloads = {
                    source: source.read_bytes()
                    for source in (unit_source, launcher_source)
                }
                for _ in range(2):
                    removed = self.run_wiring("remove", environment)
                    self.assertEqual(removed.returncode, 0, removed.stderr)
                for source, destination in destinations:
                    self.assertTrue(source.is_file())
                    self.assertFalse(source.is_symlink())
                    self.assertEqual(source_payloads[source], source.read_bytes())
                    if destination != source:
                        self.assertFalse(destination.exists() or destination.is_symlink())
                self.assertEqual("preserve me\n", unrelated.read_text())

        environment = {
            **self.env,
            "XDG_CONFIG_HOME": str(custom_config),
            "XDG_DATA_HOME": str(custom_data),
        }

        unit_link.write_text("conflicting unit\n")
        conflict = self.run_wiring("setup", environment)
        self.assertNotEqual(conflict.returncode, 0)
        self.assertEqual("conflicting unit\n", unit_link.read_text())
        self.assertFalse(launcher_link.exists() or launcher_link.is_symlink())
        unit_link.unlink()

        other = self.root / "other launcher"
        other.write_text("other\n")
        launcher_link.symlink_to(other)
        conflict = self.run_wiring("setup", environment)
        self.assertNotEqual(conflict.returncode, 0)
        self.assertEqual(other, launcher_link.resolve(strict=True))
        self.assertFalse(unit_link.exists() or unit_link.is_symlink())
        removal_conflict = self.run_wiring("remove", environment)
        self.assertNotEqual(removal_conflict.returncode, 0)
        self.assertEqual(other, launcher_link.resolve(strict=True))
        self.assertFalse(unit_link.exists() or unit_link.is_symlink())

    def test_documented_wiring_normalizes_trailing_separators(self):
        self.platform("linux")
        applied = self.chezmoi("apply", "--force")
        self.assertEqual(applied.returncode, 0, applied.stderr)

        default_config = self.home / ".config"
        default_data = self.home / ".local/share"
        custom_config = self.root / "custom config"
        custom_data = self.root / "custom data"
        unit_source = default_config / "systemd/user/proton-drive-desktop.service"
        launcher_source = default_data / "applications/proton-drive.desktop"
        unit_link = custom_config / "systemd/user/proton-drive-desktop.service"
        launcher_link = custom_data / "applications/proton-drive.desktop"

        layouts = (
            ("default-one", f"{default_config}/", f"{default_data}/",
             unit_source, launcher_source),
            ("default-repeated", f"{default_config}///", f"{default_data}////",
             unit_source, launcher_source),
            ("mixed-one", f"{custom_config}/", f"{default_data}/",
             unit_link, launcher_source),
            ("mixed-repeated", f"{default_config}///", f"{custom_data}////",
             unit_source, launcher_link),
        )
        for name, config_home, data_home, unit_destination, launcher_destination in layouts:
            with self.subTest(layout=name):
                environment = {
                    **self.env,
                    "XDG_CONFIG_HOME": config_home,
                    "XDG_DATA_HOME": data_home,
                }
                destinations = (
                    (unit_source, unit_destination),
                    (launcher_source, launcher_destination),
                )

                for _ in range(2):
                    result = self.run_wiring("setup", environment)
                    self.assertEqual(result.returncode, 0, result.stderr)
                for source, destination in destinations:
                    self.assertEqual(source.read_bytes(), destination.read_bytes())
                    if destination != source:
                        self.assertTrue(destination.is_symlink())
                        self.assertEqual(str(source), os.readlink(destination))

                for _ in range(2):
                    removed = self.run_wiring("remove", environment)
                    self.assertEqual(removed.returncode, 0, removed.stderr)
                for source, destination in destinations:
                    self.assertTrue(source.is_file())
                    self.assertFalse(source.is_symlink())
                    if destination != source:
                        self.assertFalse(destination.exists() or destination.is_symlink())

    @unittest.skipUnless(os.uname().sysname == "Linux", "Linux xattr recovery")
    def test_documented_recovery_inspector_covers_every_phase_branch(self):
        inspector = self.documented_recovery_evidence_inspector()
        identity_name = "user.proton-drive-desktop.identity"
        unknown_name = "user.proton-drive-desktop.keep"
        nonce = "12" * 32
        mount_tag = "proton-drive-desktop-" + "34" * 32

        for phase_name, identity, marker_present, expected_code in (
            ("prepare-create", None, False, 1),
            ("prepare-publish", None, False, 0),
            ("prepare-publish", nonce, True, 0),
            ("cleanup-retained", nonce, True, 0),
            ("cleanup-retained", None, False, 0),
        ):
            with self.subTest(
                phase=phase_name,
                identity=identity,
                marker_present=marker_present,
            ), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                mount = root / "files"
                mount.mkdir(mode=0o700)
                os.setxattr(mount, unknown_name, b"preserve-unknown")
                information = mount.stat()
                common = {
                    "mount": str(mount),
                    "created": True,
                    "nonce": nonce,
                    "mount_tag": mount_tag,
                }
                phase = {"phase": phase_name, **common}
                if phase_name != "prepare-create":
                    phase.update(
                        device=information.st_dev, inode=information.st_ino
                    )
                phase_path = root / "mountpoint-phase.json"
                marker_path = root / "mountpoint.json"
                phase_path.write_text(json.dumps(phase, separators=(",", ":")))
                if marker_present:
                    marker_path.write_text(json.dumps({
                        **common,
                        "device": information.st_dev,
                        "inode": information.st_ino,
                    }, separators=(",", ":")))
                if identity is not None:
                    os.setxattr(mount, identity_name, identity.encode("ascii"))
                phase_before = phase_path.read_bytes()
                marker_before = (
                    marker_path.read_bytes() if marker_path.exists() else None
                )

                result = subprocess.run(
                    [
                        "/usr/bin/python3", "-", str(phase_path),
                        str(marker_path), str(mount),
                    ],
                    input=inspector,
                    text=True,
                    capture_output=True,
                )

                self.assertEqual(expected_code, result.returncode, result.stderr)
                if phase_name == "prepare-create":
                    self.assertIn("cannot authorize", result.stderr)
                else:
                    self.assertIn(
                        f"evidence matched: {phase_name}", result.stdout
                    )
                self.assertEqual(phase_before, phase_path.read_bytes())
                if marker_before is None:
                    self.assertFalse(marker_path.exists())
                else:
                    self.assertEqual(marker_before, marker_path.read_bytes())
                self.assertEqual(
                    b"preserve-unknown", os.getxattr(mount, unknown_name)
                )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mount = root / "files"
            replacement = root / "replacement"
            mount.mkdir(mode=0o700)
            replacement.mkdir(mode=0o700)
            information = mount.stat()
            common = {
                "mount": str(mount), "device": information.st_dev,
                "inode": information.st_ino, "created": True,
                "nonce": nonce, "mount_tag": mount_tag,
            }
            phase_path = root / "mountpoint-phase.json"
            marker_path = root / "mountpoint.json"
            phase_path.write_text(json.dumps({
                "phase": "cleanup-retained", **common,
            }, separators=(",", ":")))
            marker_path.write_text(json.dumps(common, separators=(",", ":")))
            mount.rmdir()
            replacement.rename(mount)
            os.setxattr(mount, unknown_name, b"preserve-replacement")
            phase_before = phase_path.read_bytes()
            marker_before = marker_path.read_bytes()

            result = subprocess.run(
                [
                    "/usr/bin/python3", "-", str(phase_path),
                    str(marker_path), str(mount),
                ],
                input=inspector,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("directory identity mismatch", result.stderr)
            self.assertEqual(phase_before, phase_path.read_bytes())
            self.assertEqual(marker_before, marker_path.read_bytes())
            self.assertEqual(
                b"preserve-replacement", os.getxattr(mount, unknown_name)
            )

        for action in ("setup", "remove"):
            for selected_root in ("/", "////"):
                with self.subTest(action=action, selected_root=selected_root):
                    normalized = self.run_documented_root_selection(
                        action, selected_root
                    )
                    self.assertEqual(normalized.returncode, 0, normalized.stderr)
                    self.assertEqual(
                        normalized.stdout,
                        "/systemd/user/proton-drive-desktop.service\n"
                        "/applications/proton-drive.desktop\n",
                    )

    def test_non_linux_apply_omits_all_desktop_bindings(self):
        self.platform("darwin")
        result = self.chezmoi("apply", "--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        for target in PAYLOAD.values():
            self.assertFalse((self.home / target).exists(), target)

    def test_dry_run_does_not_install_bindings(self):
        self.platform("linux")
        result = self.chezmoi("apply", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        for target in PAYLOAD.values():
            self.assertFalse((self.home / target).exists(), target)


if __name__ == "__main__":
    unittest.main()
