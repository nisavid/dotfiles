import contextlib
import errno
import hashlib
import io
import json
import os
import pathlib
import runpy
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
PROGRAM = ROOT / "home/private_dot_local/bin/executable_proton-drive-desktop"
XATTR_MISSING_ERRNO = getattr(errno, "ENODATA", getattr(errno, "ENOATTR", 93))


def invoke(arguments, environment, run=None, popen=None, execve=None, opened=None, program=PROGRAM):
    stdout = io.StringIO()
    stderr = io.StringIO()
    patches = [
        mock.patch.dict(os.environ, environment, clear=True),
        mock.patch.object(sys, "argv", [str(program), *arguments]),
        mock.patch("subprocess.run", side_effect=run),
        mock.patch("subprocess.Popen", side_effect=popen),
        mock.patch("os.execve", side_effect=execve),
    ]
    if opened is not None:
        patches.append(mock.patch("builtins.open", side_effect=opened))
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                runpy.run_path(str(program), run_name="__main__")
            except SystemExit as error:
                code = error.code if isinstance(error.code, int) else 1
            else:
                code = 0
    return code, stdout.getvalue(), stderr.getvalue()


def publish_mount_record(mount, runtime, mount_id, created):
    mount.mkdir(parents=True, mode=0o700, exist_ok=True)
    runtime.mkdir(parents=True, mode=0o700, exist_ok=True)
    information = mount.stat()
    nonce = hashlib.sha256(f"{mount}:{mount_id}".encode()).hexdigest()
    os.setxattr(
        mount, "user.proton-drive-desktop.identity", nonce.encode("ascii")
    )
    marker = runtime / "mountpoint.json"
    marker.write_text(json.dumps({
        "mount": str(mount),
        "device": information.st_dev,
        "inode": information.st_ino,
        "created": created,
        "nonce": nonce,
        "mount_id": mount_id,
    }, separators=(",", ":")))
    marker.chmod(0o600)


class SyntheticDirectoryXattrs:
    """Model the Linux-only product's external xattr boundary on macOS."""

    def __init__(self):
        self.values = {}

    @staticmethod
    def key(path, name):
        information = os.lstat(path)
        return (
            information.st_dev,
            information.st_ino,
            information.st_ctime_ns,
            name,
        )

    def get(self, path, name, *args, **kwargs):
        try:
            return self.values[self.key(path, name)]
        except KeyError:
            raise OSError(XATTR_MISSING_ERRNO, "synthetic xattr is absent") from None

    def set(self, path, name, value, *args, **kwargs):
        self.values[self.key(path, name)] = value

    def remove(self, path, name, *args, **kwargs):
        try:
            del self.values[self.key(path, name)]
        except KeyError:
            raise OSError(XATTR_MISSING_ERRNO, "synthetic xattr is absent") from None


class ServiceContractTests(unittest.TestCase):
    def test_service_is_a_plasma_scoped_foreground_notify_service(self):
        unit = (ROOT / "home/dot_config/systemd/user/proton-drive-desktop.service").read_text()

        self.assertIn("Requisite=plasma-workspace.target graphical-session.target", unit)
        self.assertIn("After=plasma-kwallet-pam.service", unit)
        self.assertIn("PartOf=plasma-workspace.target graphical-session.target", unit)
        self.assertIn("Type=notify", unit)
        self.assertIn("ExecStartPre=%h/.local/bin/proton-drive-desktop _prepare", unit)
        self.assertIn("ExecStart=%h/.local/bin/proton-drive-desktop _mount", unit)
        self.assertIn("ExecStartPost=%h/.local/bin/proton-drive-desktop _verify-mount", unit)
        self.assertIn("ExecStopPost=%h/.local/bin/proton-drive-desktop _post-stop", unit)
        self.assertIn("StandardOutput=null", unit)
        self.assertIn("StandardError=null", unit)
        self.assertIn("UMask=0077", unit)
        self.assertIn("LimitCORE=0", unit)
        self.assertIn("Restart=no", unit)
        self.assertIn("SuccessExitStatus=143", unit)
        self.assertIn("WantedBy=plasma-workspace.target", unit)

        forbidden = (
            "PrivateTmp=", "PrivateMounts=", "PrivateDevices=", "ProtectHome=",
            "NoNewPrivileges=", "ExecStartPre=/usr/bin/secret-tool",
            "Before=", "Wants=graphical-session.target", "Wants=plasma-workspace.target",
        )
        for directive in forbidden:
            self.assertNotIn(directive, unit)

    def test_operator_documentation_covers_custom_xdg_setup_and_failed_recovery(self):
        guide = (ROOT / "docs/PROTON_DRIVE.md").read_text()
        heading = "### Persist an already chosen custom XDG layout"
        self.assertIn(heading, guide)
        custom_xdg = guide.split(heading, 1)[1].split("## Install and qualify", 1)[0]
        compact = " ".join(custom_xdg.split())

        required_in_order = (
            "Default-path users do not need this procedure",
            "does not migrate the desktop or credentials",
            "keep `proton-drive-desktop.service` disabled",
            "`proton-drive-desktop stop`",
            "do not force an unmount",
            "`~/.config/environment.d/90-proton-drive-xdg.conf`",
            "already inherited an absolute `XDG_CONFIG_HOME`",
            "does not relocate this bootstrap file",
            "mkdir -p -- \"$HOME/.config/environment.d\"",
            "`KEY=VALUE`",
            "do not use `export`",
            "arrange a reboot",
            "newly launched services",
            "not already-running processes or unrelated shells",
            "printf 'XDG_CONFIG_HOME=%s\\nXDG_DATA_HOME=%s\\n'",
            "systemctl --user show-environment | sed -n",
            "Do not `eval` this output",
            "match the two intended absolute paths",
            "`~/.local/bin/proton-drive-desktop`",
            "`~/.config/systemd/user/proton-drive-desktop.service`",
            "`~/.local/share/applications/proton-drive.desktop`",
            "test -x \"$HOME/.local/bin/proton-drive-desktop\"",
            "test -r \"$HOME/.config/systemd/user/proton-drive-desktop.service\"",
            "test -r \"$HOME/.local/share/applications/proton-drive.desktop\"",
            "systemctl --user cat proton-drive-desktop.service",
            "test -r \"${XDG_DATA_HOME:-$HOME/.local/share}/applications/proton-drive.desktop\"",
            "keep automatic startup disabled and report the gap",
            "start automatically before any `proton-drive-desktop start` or `open`",
            "including paths with spaces",
        )
        positions = []
        for instruction in required_in_order:
            position = compact.find(instruction)
            with self.subTest(instruction=instruction):
                self.assertGreaterEqual(position, 0)
            positions.append(position)
        if all(position >= 0 for position in positions):
            self.assertEqual(sorted(positions), positions)

        normalized_guide = " ".join(guide.split())
        self.assertIn("one XDG binding for the session", normalized_guide)
        self.assertIn(
            "persistent XDG environment also affects other newly launched desktop processes",
            normalized_guide,
        )
        self.assertIn(
            "After that apply and before the first `start` or `enable`",
            normalized_guide,
        )
        self.assertIn(
            "run `systemctl --user daemon-reload` after a unit update",
            normalized_guide,
        )
        self.assertIn("removes only the two exact links", normalized_guide)
        self.assertIn("explicit `start` retries", normalized_guide)
        self.assertIn("explicit `stop` clears", normalized_guide)
        self.assertIn(
            "persistent, reliable `user.*` extended attributes for directories",
            normalized_guide,
        )
        self.assertIn(
            "device and inode numbers alone are never accepted",
            normalized_guide,
        )
        self.assertIn(
            "runtime marker from an older release has no nonce",
            normalized_guide,
        )
        self.assertIn(
            "Only in that stopped-session state, remove the legacy private runtime marker",
            normalized_guide,
        )
        self.assertIn(
            "interrupted mountpoint creation requires stopped recovery",
            normalized_guide,
        )
        self.assertIn(
            "interrupted mountpoint identity publication requires stopped recovery",
            normalized_guide,
        )
        self.assertIn(
            "interrupted preexisting mountpoint cleanup requires stopped recovery",
            normalized_guide,
        )
        self.assertIn("mountpoint-phase.json", normalized_guide)
        self.assertIn("Do not copy or guess the recorded nonce", normalized_guide)
        self.assertIn('rmdir -- "$mountpoint"', normalized_guide)
        self.assertIn('rm -- "$marker" "$phase"', normalized_guide)
        self.assertIn(
            "source cannot infer that the unmarked directory was helper-created",
            normalized_guide,
        )
        self.assertIn("`/usr/bin/secret-tool`", normalized_guide)
        self.assertIn("test -x /usr/bin/secret-tool", normalized_guide)


class PublicCommandTests(unittest.TestCase):
    def setUp(self):
        if sys.platform == "darwin":
            xattrs = SyntheticDirectoryXattrs()
            self.enterContext(mock.patch("os.getxattr", side_effect=xattrs.get))
            self.enterContext(mock.patch("os.setxattr", side_effect=xattrs.set))
            self.enterContext(mock.patch("os.removexattr", side_effect=xattrs.remove))

    def test_status_rejects_relative_xdg_paths_without_external_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            external = mock.Mock(side_effect=AssertionError("external command called"))
            code, output, error = invoke(
                ["status"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": "relative/config",
                    "XDG_DATA_HOME": str(pathlib.Path(temporary) / "data"),
                    "XDG_RUNTIME_DIR": str(pathlib.Path(temporary) / "run"),
                },
                run=external,
            )

        self.assertEqual(2, code)
        self.assertEqual("", output)
        self.assertEqual("invalid XDG_CONFIG_HOME: absolute path required\n", error)
        external.assert_not_called()

    def test_empty_config_and_data_xdg_values_use_standard_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / ".local/share/proton-drive-desktop/files"
            encoded_mount = str(mount).replace(" ", "\\040")

            def external(command, **kwargs):
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="ActiveState=inactive\nSubState=dead\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": "",
                "XDG_DATA_HOME": "",
                "XDG_RUNTIME_DIR": str(root / "run"),
            }
            self.assertEqual(
                (0, "stopped\n", ""),
                invoke(["status"], environment, run=external, opened=opened),
            )

            environment["XDG_DATA_HOME"] = str(root / "data")
            self.assertEqual(
                (0, "stopped\n", ""),
                invoke(["status"], environment, run=external, opened=opened),
            )

            environment["XDG_CONFIG_HOME"] = str(root / "config")
            environment["XDG_DATA_HOME"] = ""
            self.assertEqual(
                (0, "stopped\n", ""),
                invoke(["status"], environment, run=external, opened=opened),
            )

    def test_status_reports_service_and_exact_mount_states_without_authentication(self):
        with tempfile.TemporaryDirectory(prefix="proton drive ") as temporary:
            root = pathlib.Path(temporary)
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_RUNTIME_DIR": str(root / "run"),
            }
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            mount.mkdir(parents=True, mode=0o700)
            runtime.mkdir(parents=True, mode=0o700)
            information = mount.stat()
            (runtime / "mountpoint.json").write_text(json.dumps({
                "mount": str(mount), "device": information.st_dev,
                "inode": information.st_ino, "created": False,
                "nonce": "41" * 32,
                "mount_id": "41",
            }))
            encoded_mount = str(mount).replace(" ", "\\040")
            valid = (
                f"41 30 0:42 / {encoded_mount} ro,nosuid,nodev - "
                "fuse.rclone proton-dolphin{FfUSA}: ro\n"
            )
            foreign = (
                f"41 30 0:42 / {encoded_mount} rw,nosuid,nodev - "
                "fuse.rclone somebody-else: rw\n"
            )
            malformed_disambiguator = (
                f"41 30 0:42 / {encoded_mount} ro,nosuid,nodev - "
                "fuse.rclone proton-dolphin{too-long}: ro\n"
            )
            rw_mount_options = (
                f"41 30 0:42 / {encoded_mount} ro,rw,nosuid,nodev - "
                "fuse.rclone proton-dolphin: ro\n"
            )
            rw_super_options = (
                f"41 30 0:42 / {encoded_mount} ro,nosuid,nodev - "
                "fuse.rclone proton-dolphin: ro,rw\n"
            )
            cases = (
                ("active", "running", valid, 0, "ready\n"),
                ("activating", "start-post", valid, 3, "starting\n"),
                ("deactivating", "stop-sigterm", valid, 3, "stopping\n"),
                ("inactive", "dead", "", 0, "stopped\n"),
                ("failed", "failed", "", 1, "failed\n"),
                ("active", "running", foreign, 1, "inconsistent/foreign state\n"),
                ("active", "running", malformed_disambiguator, 1, "inconsistent/foreign state\n"),
                ("active", "running", rw_mount_options, 1, "inconsistent/foreign state\n"),
                ("active", "running", rw_super_options, 1, "inconsistent/foreign state\n"),
                ("active", "running", valid + valid, 1, "inconsistent/foreign state\n"),
            )

            for active, sub, mountinfo, wanted_code, wanted_output in cases:
                calls = []

                def external(command, **kwargs):
                    calls.append(command)
                    self.assertEqual("/usr/bin/systemctl", command[0])
                    self.assertEqual("show", command[2])
                    return subprocess.CompletedProcess(
                        command, 0,
                        stdout=f"ActiveState={active}\nSubState={sub}\nResult=success\n",
                    )

                def opened(name, *args, **kwargs):
                    if name == "/proc/self/mountinfo":
                        return io.StringIO(mountinfo)
                    return io.open(name, *args, **kwargs)

                with self.subTest(active=active, sub=sub, mountinfo=mountinfo):
                    code, output, error = invoke(
                        ["status"], environment, run=external, opened=opened
                    )
                    self.assertEqual(wanted_code, code)
                    self.assertEqual(wanted_output, output)
                    self.assertEqual("", error)
                    expected_observations = (
                        2 if wanted_output == "inconsistent/foreign state\n" else 1
                    )
                    self.assertEqual(expected_observations, len(calls))
                    self.assertNotIn("secret-tool", repr(calls))

    def test_ready_status_and_reuse_require_the_recorded_mount_instance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            mount.mkdir(parents=True, mode=0o700)
            runtime.mkdir(parents=True, mode=0o700)
            information = mount.stat()
            (runtime / "mountpoint.json").write_text(json.dumps({
                "mount": str(mount), "device": information.st_dev,
                "inode": information.st_ino, "created": False,
                "nonce": "45" * 32,
                "mount_id": "45",
            }))
            encoded_mount = str(mount).replace(" ", "\\040")
            mount_id = "45"
            calls = []

            def external(command, **kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="ActiveState=active\nSubState=running\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO(
                        f"{mount_id} 30 0:45 / {encoded_mount} ro,nosuid,nodev - "
                        "fuse.rclone proton-dolphin: ro\n"
                    )
                return io.open(name, *args, **kwargs)

            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_RUNTIME_DIR": str(root / "run"),
            }
            self.assertEqual(
                (0, "ready\n", ""),
                invoke(["status"], environment, run=external, opened=opened),
            )
            self.assertEqual(
                (0, "ready\n", ""),
                invoke(["start"], environment, run=external, opened=opened),
            )

            mount_id = "46"
            self.assertEqual(
                (1, "inconsistent/foreign state\n", ""),
                invoke(["status"], environment, run=external, opened=opened),
            )
            self.assertEqual(
                (1, "", "inconsistent/foreign state\n"),
                invoke(["start"], environment, run=external, opened=opened),
            )
            self.assertFalse(any(command[2] == "start" for command in calls))

    def test_nonce_less_record_cannot_authorize_an_active_mount(self):
        cases = (
            ("status", (1, "inconsistent/foreign state\n", "")),
            ("start", (1, "", "inconsistent/foreign state\n")),
            ("open", (1, "", "inconsistent/foreign state\n")),
            ("stop", (1, "", "mount is not owned by this session\n")),
            ("_verify-mount", (1, "", "mountpoint ownership record is invalid\n")),
        )
        for command, expected in cases:
            with self.subTest(command=command), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                mount = root / "data/proton-drive-desktop/files"
                runtime = root / "run/proton-drive-desktop"
                mount.mkdir(parents=True, mode=0o700)
                runtime.mkdir(parents=True, mode=0o700)
                information = mount.stat()
                ownership = {
                    "mount": str(mount),
                    "device": information.st_dev,
                    "inode": information.st_ino,
                    "created": False,
                }
                if command != "_verify-mount":
                    ownership["mount_id"] = "44"
                marker = runtime / "mountpoint.json"
                marker.write_text(json.dumps(ownership, separators=(",", ":")))
                marker_before = marker.read_bytes()
                encoded_mount = str(mount).replace(" ", "\\040")
                mountinfo = (
                    f"44 30 0:44 / {encoded_mount} ro,nosuid,nodev - "
                    "fuse.rclone proton-dolphin: ro\n"
                )
                actions = []

                def external(arguments, **kwargs):
                    actions.append(arguments)
                    if arguments[0] == "/usr/bin/systemctl" and arguments[2] == "show":
                        return subprocess.CompletedProcess(
                            arguments,
                            0,
                            stdout=(
                                "ActiveState=active\nSubState=running\n"
                                "Result=success\n"
                            ),
                        )
                    return subprocess.CompletedProcess(arguments, 0)

                def opened(name, *args, **kwargs):
                    if name == "/proc/self/mountinfo":
                        return io.StringIO(mountinfo)
                    return io.open(name, *args, **kwargs)

                def launch(arguments, **kwargs):
                    actions.append(arguments)
                    return mock.Mock()

                environment = {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                }
                with mock.patch(
                    "os.getxattr",
                    side_effect=AssertionError("read xattr through active mount"),
                ):
                    result = invoke(
                        [command],
                        environment,
                        run=external,
                        popen=launch,
                        opened=opened,
                    )

                self.assertEqual(expected, result)
                self.assertTrue(mount.is_dir())
                self.assertEqual(marker_before, marker.read_bytes())
                self.assertFalse(
                    any(action[0] == "/usr/bin/fusermount3" for action in actions)
                )
                self.assertFalse(
                    any(
                        action[0] == "/usr/bin/systemctl" and action[2] == "stop"
                        for action in actions
                    )
                )
                self.assertFalse(
                    any(action[0] == "/usr/bin/dolphin" for action in actions)
                )

    def test_status_rechecks_active_absent_before_reporting_stopped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            publish_mount_record(mount, runtime, "46", True)
            marker = runtime / "mountpoint.json"
            recorded = marker.read_bytes()
            observations = []
            services = iter(("active", "inactive"))

            def external(command, **kwargs):
                state = next(services)
                observations.append(f"service-{state}")
                sub = "running" if state == "active" else "dead"
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=(
                        f"ActiveState={state}\nSubState={sub}\n"
                        "Result=success\n"
                    ),
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    observations.append("mount-absent")
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["status"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                },
                run=external,
                opened=opened,
            )

            self.assertEqual((0, "stopped\n", ""), result)
            self.assertEqual(
                [
                    "service-active", "mount-absent",
                    "service-inactive", "mount-absent",
                ],
                observations,
            )
            self.assertTrue(mount.is_dir())
            self.assertEqual(recorded, marker.read_bytes())

    def test_status_rechecks_each_unsafe_classification_from_scratch(self):
        cases = (
            (
                "failed-ready", ("failed", "failed"), ("ready", "absent"),
                None, (1, "failed\n", ""),
            ),
            (
                "foreign", ("active", "active"), ("foreign", "ready"),
                None, (0, "ready\n", ""),
            ),
            (
                "duplicate", ("active", "active"), ("duplicate", "ready"),
                None, (0, "ready\n", ""),
            ),
            (
                "ownership", ("active", "active"), ("ready", "ready"),
                "repair-on-second-observation", (0, "ready\n", ""),
            ),
        )
        for name, states, mounts, marker_change, expected in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                mount = root / "data/proton-drive-desktop/files"
                runtime = root / "run/proton-drive-desktop"
                publish_mount_record(mount, runtime, "47", False)
                marker = runtime / "mountpoint.json"
                if marker_change:
                    ownership = json.loads(marker.read_text())
                    ownership["mount_id"] = "999"
                    marker.write_text(json.dumps(ownership, separators=(",", ":")))
                encoded_mount = str(mount).replace(" ", "\\040")
                ready = (
                    f"47 30 0:47 / {encoded_mount} ro,nosuid,nodev - "
                    "fuse.rclone proton-dolphin: ro\n"
                )
                foreign = (
                    f"48 30 0:48 / {encoded_mount} rw,nosuid,nodev - "
                    "fuse.other local: rw\n"
                )
                observations = []
                service_observation = 0
                mount_observation = 0

                def external(command, **kwargs):
                    nonlocal service_observation
                    if marker_change and service_observation == 1:
                        ownership = json.loads(marker.read_text())
                        ownership["mount_id"] = "47"
                        marker.write_text(json.dumps(ownership, separators=(",", ":")))
                    state = states[service_observation]
                    service_observation += 1
                    observations.append(f"service-{state}")
                    sub = "running" if state == "active" else state
                    return subprocess.CompletedProcess(
                        command, 0,
                        stdout=(
                            f"ActiveState={state}\nSubState={sub}\n"
                            "Result=success\n"
                        ),
                    )

                def opened(path, *args, **kwargs):
                    nonlocal mount_observation
                    if path == "/proc/self/mountinfo":
                        state = mounts[mount_observation]
                        mount_observation += 1
                        observations.append(f"mount-{state}")
                        content = {
                            "absent": "",
                            "ready": ready,
                            "foreign": foreign,
                            "duplicate": ready + ready.replace("47 30", "49 30", 1),
                        }[state]
                        return io.StringIO(content)
                    return io.open(path, *args, **kwargs)

                result = invoke(
                    ["status"],
                    {
                        "HOME": temporary,
                        "XDG_CONFIG_HOME": str(root / "config"),
                        "XDG_DATA_HOME": str(root / "data"),
                        "XDG_RUNTIME_DIR": str(root / "run"),
                    },
                    run=external,
                    opened=opened,
                )

                self.assertEqual(expected, result)
                self.assertEqual(2, service_observation)
                self.assertEqual(2, mount_observation)

    def test_status_bounds_persistent_active_absent_without_changing_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            publish_mount_record(mount, runtime, "50", True)
            marker = runtime / "mountpoint.json"
            recorded = marker.read_bytes()
            observations = []

            def external(command, **kwargs):
                observations.append("service-active")
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="ActiveState=active\nSubState=running\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    observations.append("mount-absent")
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["status"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                },
                run=external,
                opened=opened,
            )

            self.assertEqual((1, "inconsistent/foreign state\n", ""), result)
            self.assertEqual(
                [
                    "service-active", "mount-absent",
                    "service-active", "mount-absent",
                ],
                observations,
            )
            self.assertTrue(mount.is_dir())
            self.assertEqual(recorded, marker.read_bytes())

    def test_start_does_not_recover_persistent_active_absent_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            publish_mount_record(mount, runtime, "51", True)
            marker = runtime / "mountpoint.json"
            recorded = marker.read_bytes()
            observations = []

            def external(command, **kwargs):
                if command[2] != "show":
                    raise AssertionError("persistent unsafe state authorized an action")
                observations.append("service-active")
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="ActiveState=active\nSubState=running\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    observations.append("mount-absent")
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["start"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                },
                run=external,
                opened=opened,
            )

            self.assertEqual((1, "", "inconsistent/foreign state\n"), result)
            self.assertEqual(
                [
                    "service-active", "mount-absent",
                    "service-active", "mount-absent",
                ],
                observations,
            )
            self.assertTrue(mount.is_dir())
            self.assertEqual(recorded, marker.read_bytes())

    def test_non_root_mount_is_foreign_for_status_open_and_service_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            mount.mkdir(parents=True, mode=0o700)
            runtime.mkdir(parents=True, mode=0o700)
            information = mount.stat()
            marker = runtime / "mountpoint.json"
            marker.write_text(json.dumps({
                "mount": str(mount), "device": information.st_dev,
                "inode": information.st_ino, "created": False,
                "nonce": "47" * 32,
                "mount_id": "47",
            }))
            encoded_mount = str(mount).replace(" ", "\\040")
            non_root = (
                f"47 30 0:47 /subtree {encoded_mount} ro,nosuid,nodev - "
                "fuse.rclone proton-dolphin: ro\n"
            )
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_RUNTIME_DIR": str(root / "run"),
            }

            def external(command, **kwargs):
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="ActiveState=active\nSubState=running\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO(non_root)
                return io.open(name, *args, **kwargs)

            for command, expected in (
                (["status"], (1, "inconsistent/foreign state\n", "")),
                (["open"], (1, "", "inconsistent/foreign state\n")),
                (["_verify-mount"], (
                    1, "", "expected read-only Proton Drive mount not found\n",
                )),
            ):
                dolphin = mock.Mock()
                with self.subTest(command=command[0]):
                    self.assertEqual(
                        expected,
                        invoke(
                            command, environment, run=external, popen=dolphin,
                            opened=opened,
                        ),
                    )
                    dolphin.assert_not_called()

    def test_start_preserves_unexpected_local_contents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_home = root / "config"
            data_home = root / "data"
            runtime = root / "run"
            config_parent = config_home / "rclone"
            mount = data_home / "proton-drive-desktop/files"
            config_parent.mkdir(parents=True, mode=0o700)
            data_home.mkdir(mode=0o700)
            runtime.mkdir(mode=0o700)
            mount.mkdir(parents=True, mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            unexpected = mount / "keep-me.txt"
            unexpected.write_text("local data")
            calls = []

            def external(command, **kwargs):
                calls.append(command)
                if command[2] == "start":
                    return subprocess.CompletedProcess(command, 1)
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="ActiveState=inactive\nSubState=dead\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            code, output, error = invoke(
                ["start"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(config_home),
                    "XDG_DATA_HOME": str(data_home),
                    "XDG_RUNTIME_DIR": str(runtime),
                },
                run=external,
                opened=opened,
            )

            self.assertEqual(1, code)
            self.assertEqual("", output)
            self.assertEqual("mountpoint contains unexpected local contents\n", error)
            self.assertEqual("local data", unexpected.read_text())
            self.assertEqual(1, sum(command[2] == "start" for command in calls))

    def test_failed_service_start_relies_on_ordered_unit_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            data_home = root / "data"
            runtime = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            data_home.mkdir(mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            mount = data_home / "proton-drive-desktop/files"
            module = runpy.run_path(str(PROGRAM), run_name="proton_drive_test_module")
            resolved = {
                "config": config,
                "mount": mount,
                "runtime": runtime / "proton-drive-desktop",
            }
            cleanup_owners = []
            cleanup_owner = "public"
            original_cleanup = module["cleanup_mountpoint"]

            def watched_cleanup(paths):
                cleanup_owners.append(cleanup_owner)
                return original_cleanup(paths)

            class FakeSubprocess:
                PIPE = subprocess.PIPE
                DEVNULL = subprocess.DEVNULL

                @staticmethod
                def run(command, **kwargs):
                    nonlocal cleanup_owner
                    if command[2] == "start":
                        cleanup_owner = "unit"
                        try:
                            module["service_prepare"](resolved)
                            module["service_post_stop"](resolved)
                        finally:
                            cleanup_owner = "public"
                        return subprocess.CompletedProcess(command, 1)
                    return subprocess.CompletedProcess(
                        command, 0,
                        stdout="ActiveState=inactive\nSubState=dead\nResult=success\n",
                    )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            module["service_state"].__globals__["subprocess"] = FakeSubprocess
            module["cleanup_mountpoint"].__globals__["cleanup_mountpoint"] = watched_cleanup
            error = None
            with mock.patch("builtins.open", side_effect=opened):
                try:
                    module["start"](resolved)
                except module["OperationError"] as failure:
                    error = str(failure)

            self.assertEqual("service startup failed", error)
            self.assertEqual(["unit"], cleanup_owners)
            self.assertFalse(mount.exists())
            self.assertFalse((resolved["runtime"] / "mountpoint.json").exists())
            self.assertTrue(config.exists())

    def test_failed_systemctl_start_without_unit_metadata_reports_fixed_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            runtime = root / "run"
            runtime.mkdir(mode=0o700)

            def external(command, **kwargs):
                if command[2] == "start":
                    return subprocess.CompletedProcess(command, 1)
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="ActiveState=inactive\nSubState=dead\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["start"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(runtime),
                },
                run=external,
                opened=opened,
            )

            self.assertEqual((1, "", "service startup failed\n"), result)

    def test_open_starts_once_rechecks_readiness_then_invokes_dolphin(self):
        with tempfile.TemporaryDirectory(prefix="proton drive ") as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            data_home = root / "data"
            runtime = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            data_home.mkdir(mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            mount = data_home / "proton-drive-desktop/files"
            encoded_mount = str(mount).replace(" ", "\\040")
            ready_mount = (
                f"52 30 0:52 / {encoded_mount} ro,nosuid,nodev - "
                "fuse.rclone proton-dolphin: ro\n"
            )
            events = []
            ready = False

            def external(command, **kwargs):
                nonlocal ready
                if command[2] == "start":
                    events.append("start-service")
                    publish_mount_record(
                        mount, runtime / "proton-drive-desktop", "52", True
                    )
                    ready = True
                    return subprocess.CompletedProcess(command, 0)
                events.append("show-ready" if ready else "show-stopped")
                state = "active" if ready else "inactive"
                sub = "running" if ready else "dead"
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=f"ActiveState={state}\nSubState={sub}\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO(ready_mount if ready else "")
                return io.open(name, *args, **kwargs)

            def launch(command, **kwargs):
                events.append(("dolphin", command))
                return mock.Mock()

            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(data_home),
                "XDG_RUNTIME_DIR": str(runtime),
            }
            code, output, error = invoke(
                ["open"], environment, run=external, popen=launch, opened=opened
            )
            self.assertEqual((0, "ready\n", ""), (code, output, error))
            self.assertEqual(
                [
                    "show-stopped", "start-service", "show-ready", "show-ready",
                    ("dolphin", ["/usr/bin/dolphin", str(mount)]),
                ],
                events,
            )

            events.clear()
            code, output, error = invoke(
                ["start"], environment, run=external, popen=launch, opened=opened
            )
            self.assertEqual((0, "ready\n", ""), (code, output, error))
            self.assertEqual(["show-ready"], events)

    def test_open_does_not_report_ready_if_the_final_recheck_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            mount.mkdir(parents=True, mode=0o700)
            runtime = root / "run/proton-drive-desktop"
            runtime.mkdir(parents=True, mode=0o700)
            information = mount.stat()
            (runtime / "mountpoint.json").write_text(json.dumps({
                "mount": str(mount), "device": information.st_dev,
                "inode": information.st_ino, "created": False,
                "nonce": "51" * 32,
                "mount_id": "51",
            }))
            encoded_mount = str(mount).replace(" ", "\\040")
            mount_reads = 0

            def external(command, **kwargs):
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="ActiveState=active\nSubState=running\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                nonlocal mount_reads
                if name == "/proc/self/mountinfo":
                    mount_reads += 1
                    line = (
                        f"51 30 0:51 / {encoded_mount} ro,nosuid,nodev - "
                        "fuse.rclone proton-dolphin: ro\n"
                    )
                    return io.StringIO(line if mount_reads == 1 else "")
                return io.open(name, *args, **kwargs)

            dolphin = mock.Mock(side_effect=AssertionError("Dolphin was opened"))
            result = invoke(
                ["open"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                },
                run=external,
                popen=dolphin,
                opened=opened,
            )

            self.assertEqual(
                (1, "", "mount is not ready for Dolphin: inconsistent/foreign state\n"),
                result,
            )
            dolphin.assert_not_called()

    def test_open_rejects_mount_replacement_between_readiness_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            mount.mkdir(parents=True, mode=0o700)
            runtime.mkdir(parents=True, mode=0o700)
            information = mount.stat()
            (runtime / "mountpoint.json").write_text(json.dumps({
                "mount": str(mount), "device": information.st_dev,
                "inode": information.st_ino, "created": False,
                "nonce": "53" * 32,
                "mount_id": "53",
            }))
            encoded_mount = str(mount).replace(" ", "\\040")
            mount_reads = 0

            def external(command, **kwargs):
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="ActiveState=active\nSubState=running\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                nonlocal mount_reads
                if name == "/proc/self/mountinfo":
                    mount_reads += 1
                    mount_id = "53" if mount_reads == 1 else "54"
                    return io.StringIO(
                        f"{mount_id} 30 0:53 / {encoded_mount} ro,nosuid,nodev - "
                        "fuse.rclone proton-dolphin: ro\n"
                    )
                return io.open(name, *args, **kwargs)

            dolphin = mock.Mock()
            result = invoke(
                ["open"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                },
                run=external,
                popen=dolphin,
                opened=opened,
            )

            self.assertEqual(
                (1, "", "mount is not ready for Dolphin: inconsistent/foreign state\n"),
                result,
            )
            dolphin.assert_not_called()

    def test_open_rejects_missing_or_malformed_mount_ownership(self):
        for record in (None, "[]", "{broken"):
            with self.subTest(record=record), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                mount = root / "data/proton-drive-desktop/files"
                runtime = root / "run/proton-drive-desktop"
                mount.mkdir(parents=True, mode=0o700)
                runtime.mkdir(parents=True, mode=0o700)
                if record is not None:
                    (runtime / "mountpoint.json").write_text(record)
                encoded_mount = str(mount).replace(" ", "\\040")

                def external(command, **kwargs):
                    return subprocess.CompletedProcess(
                        command, 0,
                        stdout="ActiveState=active\nSubState=running\nResult=success\n",
                    )

                def opened(name, *args, **kwargs):
                    if name == "/proc/self/mountinfo":
                        return io.StringIO(
                            f"55 30 0:55 / {encoded_mount} ro,nosuid,nodev - "
                            "fuse.rclone proton-dolphin: ro\n"
                        )
                    return io.open(name, *args, **kwargs)

                dolphin = mock.Mock()
                result = invoke(
                    ["open"],
                    {
                        "HOME": temporary,
                        "XDG_CONFIG_HOME": str(root / "config"),
                        "XDG_DATA_HOME": str(root / "data"),
                        "XDG_RUNTIME_DIR": str(root / "run"),
                    },
                    run=external,
                    popen=dolphin,
                    opened=opened,
                )

                self.assertEqual((1, "", "inconsistent/foreign state\n"), result)
                dolphin.assert_not_called()

    def test_mount_exec_uses_fixed_read_only_arguments_and_scrubbed_environment(self):
        with tempfile.TemporaryDirectory(prefix="proton drive ") as temporary:
            root = pathlib.Path(temporary)
            copied_program = root / "bin with spaces/proton-drive-desktop"
            copied_program.parent.mkdir()
            copied_program.write_bytes(PROGRAM.read_bytes())
            config_parent = root / "config with spaces/rclone"
            mount = root / "data with spaces/proton-drive-desktop/files"
            config_parent.mkdir(parents=True, mode=0o700)
            mount.mkdir(parents=True, mode=0o700)
            (root / "run").mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            captured = {}

            def execute(path, arguments, environment):
                captured.update(path=path, arguments=arguments, environment=environment)

            no_lookup = mock.Mock(side_effect=AssertionError("credential preflight called"))
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config with spaces"),
                "XDG_DATA_HOME": str(root / "data with spaces"),
                "XDG_RUNTIME_DIR": str(root / "run"),
                "NOTIFY_SOCKET": "/run/notify socket",
                "RCLONE_CONFIG_PASS": "strip-this",
                "_RCLONE_INTERNAL": "strip-this-too",
                "Rclone_mixed_case": "keep-this",
            }

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            self.assertEqual(
                (0, "", ""),
                invoke(
                    ["_prepare"], environment, run=no_lookup, opened=opened,
                    program=copied_program,
                ),
            )
            marker = root / "run/proton-drive-desktop/mountpoint.json"
            prepared_marker = marker.read_bytes()
            code, output, error = invoke(
                ["_mount"],
                environment,
                run=no_lookup,
                execve=execute,
                opened=opened,
                program=copied_program,
            )

            self.assertEqual(1, code)
            self.assertEqual("", output)
            self.assertEqual("unable to execute rclone\n", error)
            self.assertEqual("/usr/bin/rclone", captured["path"])
            self.assertEqual(
                [
                    "/usr/bin/rclone", "mount", "proton-dolphin:", str(mount),
                    "--config", str(config),
                    "--password-command", f'"{copied_program}" _credential',
                    "--ask-password=false", "--read-only",
                    "--protondrive-enable-caching=false", "--vfs-cache-mode=off",
                    "--dir-cache-time=2s", "--attr-timeout=1s", "--log-level=ERROR",
                ],
                captured["arguments"],
            )
            self.assertEqual("/run/notify socket", captured["environment"]["NOTIFY_SOCKET"])
            self.assertNotIn("RCLONE_CONFIG_PASS", captured["environment"])
            self.assertNotIn("_RCLONE_INTERNAL", captured["environment"])
            self.assertEqual("keep-this", captured["environment"]["Rclone_mixed_case"])
            self.assertEqual(prepared_marker, marker.read_bytes())
            no_lookup.assert_not_called()

    def test_credential_helper_qualifies_kwallet_and_looks_up_exact_config_id(self):
        with tempfile.TemporaryDirectory(prefix="proton config ") as temporary:
            root = pathlib.Path(temporary)
            actual_config = root / "actual config"
            config_home = root / "config link spelling"
            actual_config.mkdir()
            config_home.symlink_to(actual_config, target_is_directory=True)
            config_parent = config_home / "rclone"
            config_parent.mkdir(parents=True, mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            calls = []

            def external(command, **kwargs):
                calls.append((command, kwargs))
                if command[0] == "/usr/bin/busctl":
                    return subprocess.CompletedProcess(
                        command, 0, stdout='{"type":"s","data":[":1.42"]}\n'
                    )
                return subprocess.CompletedProcess(command, 0, stdout=b"bounded-secret\n")

            code, output, error = invoke(
                ["_credential"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(config_home),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                },
                run=external,
            )

            wanted_id = hashlib.sha256(str(config.absolute()).encode()).hexdigest()
            self.assertEqual((0, "bounded-secret\n", ""), (code, output, error))
            self.assertEqual(
                [
                    "/usr/bin/busctl", "--user", "--json=short", "--auto-start=no",
                    "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
                    "org.freedesktop.DBus", "GetNameOwner", "s",
                    "org.freedesktop.secrets",
                ],
                calls[0][0],
            )
            self.assertEqual("org.kde.ksecretd", calls[1][0][-1])
            self.assertEqual(
                [
                    "/usr/bin/secret-tool", "lookup",
                    "application", "rclone",
                    "purpose", "proton-drive-config",
                    "config-id", wanted_id,
                ],
                calls[2][0],
            )
            self.assertIs(subprocess.DEVNULL, calls[2][1]["stderr"])
            self.assertNotIn("bounded-secret", repr(calls[2][0]))

    def test_credential_failures_are_fixed_and_never_emit_external_canaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            config_parent.mkdir(parents=True, mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_RUNTIME_DIR": str(root / "run"),
            }
            canary = "SHOULD-NOT-LEAK-93cc"

            def mismatch(command, **kwargs):
                owner = ":1.1" if command[-1] == "org.freedesktop.secrets" else ":1.2"
                return subprocess.CompletedProcess(
                    command, 0, stdout=json.dumps({"type": "s", "data": [owner]})
                )

            code, output, error = invoke(["_credential"], environment, run=mismatch)
            self.assertEqual((1, "", "credential service unavailable\n"), (code, output, error))

            def oversized(command, **kwargs):
                if command[0] == "/usr/bin/busctl":
                    return subprocess.CompletedProcess(
                        command, 0, stdout='{"type":"s","data":[":1.8"]}\n'
                    )
                return subprocess.CompletedProcess(
                    command, 1, stdout=(canary.encode() + b"x" * 5000)
                )

            code, output, error = invoke(["_credential"], environment, run=oversized)
            self.assertEqual((1, "", "credential unavailable\n"), (code, output, error))
            self.assertNotIn(canary, output + error)

            malformed_responses = (
                "not-json", "[]", '{"type":"u","data":[1]}',
                '{"type":"s","data":[]}', '{"type":"s","data":["org.kde.ksecretd"]}',
            )
            for response in malformed_responses:
                def malformed(command, **kwargs):
                    return subprocess.CompletedProcess(command, 0, stdout=response)

                with self.subTest(response=response):
                    self.assertEqual(
                        (1, "", "credential service unavailable\n"),
                        invoke(["_credential"], environment, run=malformed),
                    )

    def test_credential_bus_process_failures_are_fixed_and_skip_secret_lookup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            config_parent.mkdir(parents=True, mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_RUNTIME_DIR": str(root / "run"),
            }
            canary = "BUS-DIAGNOSTIC-SHOULD-NOT-LEAK-c927"

            for failure in ("nonzero", "oserror", "timeout"):
                calls = []

                def external(command, **kwargs):
                    calls.append(command)
                    if failure == "nonzero":
                        return subprocess.CompletedProcess(command, 1, stdout=canary)
                    if failure == "oserror":
                        raise OSError(canary)
                    raise subprocess.TimeoutExpired(
                        command, kwargs["timeout"], output=canary, stderr=canary
                    )

                with self.subTest(failure=failure):
                    result = invoke(["_credential"], environment, run=external)
                    self.assertEqual(
                        (1, "", "credential service unavailable\n"), result
                    )
                    self.assertNotIn(canary, result[1] + result[2])
                    self.assertFalse(any(
                        command[0] == "/usr/bin/secret-tool" for command in calls
                    ))

    def test_bus_owner_uses_supported_call_on_a_disposable_private_bus(self):
        tools = tuple(pathlib.Path("/usr/bin") / name for name in (
            "busctl", "dbus-run-session", "dbus-test-tool", "python3",
        ))
        missing = [str(tool) for tool in tools if not os.access(tool, os.X_OK)]
        if missing:
            self.skipTest("required private-bus tools are missing: " + ", ".join(missing))

        production_bytes = PROGRAM.read_bytes()
        obsolete = b'"call", "org.freedesktop.DBus",'
        self.assertEqual(1, production_bytes.count(obsolete))
        mutated_bytes = production_bytes.replace(
            obsolete, b'"get-name-owner", "org.freedesktop.DBus",'
        )
        inner = textwrap.dedent(r"""
            import importlib.machinery
            import importlib.util
            import subprocess
            import sys
            import time

            def load(name, path):
                loader = importlib.machinery.SourceFileLoader(name, path)
                module = importlib.util.module_from_spec(
                    importlib.util.spec_from_loader(loader.name, loader)
                )
                loader.exec_module(module)
                return module

            production = load("proton_desktop_private_bus", sys.argv[1])
            mutated = load("proton_desktop_obsolete_busctl", sys.argv[2])
            service = subprocess.Popen(
                [
                    "/usr/bin/dbus-test-tool", "echo", "--session",
                    "--name=org.kde.ksecretd",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                owner = None
                for _ in range(50):
                    try:
                        owner = production.bus_owner("org.kde.ksecretd")
                    except production.OperationError:
                        time.sleep(0.02)
                    else:
                        break
                assert owner is not None and owner.startswith(":"), owner
                try:
                    mutated.bus_owner("org.kde.ksecretd")
                except mutated.OperationError:
                    pass
                else:
                    raise AssertionError("obsolete busctl verb unexpectedly succeeded")
                print("private bus helper and mutation passed")
            finally:
                service.terminate()
                service.wait(timeout=5)
        """)

        with tempfile.TemporaryDirectory(prefix="proton private bus ") as temporary:
            root = pathlib.Path(temporary)
            mutated = root / "proton-drive-desktop-obsolete"
            mutated.write_bytes(mutated_bytes)
            mutated.chmod(0o700)
            for name in ("runtime", "config", "data", "cache"):
                (root / name).mkdir(mode=0o700)
            environment = {
                "PATH": "/usr/bin:/bin",
                "HOME": str(root),
                "LANG": "C.UTF-8",
                "XDG_RUNTIME_DIR": str(root / "runtime"),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "XDG_DATA_DIRS": str(root / "data"),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            result = subprocess.run(
                [
                    "/usr/bin/dbus-run-session", "--", "/usr/bin/python3", "-c",
                    inner, str(PROGRAM), str(mutated),
                ],
                env=environment,
                cwd=root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                check=False,
            )

        self.assertEqual(production_bytes, PROGRAM.read_bytes())
        self.assertEqual(
            0, result.returncode,
            f"private bus fixture failed\nstdout:\n{result.stdout}stderr:\n{result.stderr}",
        )
        self.assertEqual("private bus helper and mutation passed\n", result.stdout)

    def test_stop_unmounts_before_stopping_cleans_owned_leaf_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            data_home = root / "data"
            runtime = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            data_home.mkdir(mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            mount = data_home / "proton-drive-desktop/files"
            encoded_mount = str(mount).replace(" ", "\\040")
            events = []
            service = False
            mounted = False

            def external(command, **kwargs):
                nonlocal service, mounted
                if command[0] == "/usr/bin/fusermount3":
                    events.append("unmount")
                    mounted = False
                    return subprocess.CompletedProcess(command, 0)
                action = command[2]
                if action == "start":
                    events.append("start")
                    publish_mount_record(
                        mount, runtime / "proton-drive-desktop", "61", True
                    )
                    service = mounted = True
                    return subprocess.CompletedProcess(command, 0)
                if action == "stop":
                    events.append("stop")
                    service = False
                    return subprocess.CompletedProcess(command, 0)
                events.append("show")
                active = "active" if service else "inactive"
                sub = "running" if service else "dead"
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=f"ActiveState={active}\nSubState={sub}\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    entry = (
                        f"61 30 0:61 / {encoded_mount} ro,nosuid,nodev - "
                        "fuse.rclone proton-dolphin: ro\n"
                    )
                    return io.StringIO(entry if mounted else "")
                return io.open(name, *args, **kwargs)

            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(data_home),
                "XDG_RUNTIME_DIR": str(runtime),
            }
            self.assertEqual(0, invoke(["start"], environment, run=external, opened=opened)[0])
            events.clear()

            first = invoke(["stop"], environment, run=external, opened=opened)
            second = invoke(["stop"], environment, run=external, opened=opened)

            self.assertEqual((0, "stopped\n", ""), first)
            self.assertEqual((0, "stopped\n", ""), second)
            self.assertLess(events.index("unmount"), events.index("stop"))
            self.assertEqual(1, events.count("unmount"))
            self.assertEqual(2, events.count("stop"))
            self.assertFalse(mount.exists())
            self.assertTrue(config.exists())

    def test_stop_orders_activating_unmounted_unit_before_final_observation_and_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            publish_mount_record(mount, runtime, "60", True)
            service = "activating"
            events = []

            def external(command, **kwargs):
                nonlocal service
                action = command[2]
                if action == "stop":
                    events.append("stop")
                    self.assertTrue(mount.is_dir())
                    self.assertTrue((runtime / "mountpoint.json").is_file())
                    service = "inactive"
                    return subprocess.CompletedProcess(command, 0)
                events.append(f"show-{service}")
                sub = "start" if service == "activating" else "dead"
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=f"ActiveState={service}\nSubState={sub}\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    events.append("mount-absent")
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["stop"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                },
                run=external,
                opened=opened,
            )

            self.assertEqual((0, "stopped\n", ""), result)
            self.assertEqual(
                [
                    "show-activating", "mount-absent", "mount-absent", "stop",
                    "show-inactive", "mount-absent", "mount-absent",
                ],
                events,
            )
            self.assertFalse(mount.exists())
            self.assertFalse((runtime / "mountpoint.json").exists())

    def test_stop_uses_owned_unmount_path_for_activating_mounted_unit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            publish_mount_record(mount, runtime, "601", True)
            encoded_mount = str(mount).replace(" ", "\\040")
            service = "activating"
            mounted = True
            events = []

            def external(command, **kwargs):
                nonlocal service, mounted
                if command[0] == "/usr/bin/fusermount3":
                    events.append("unmount")
                    mounted = False
                    return subprocess.CompletedProcess(command, 0)
                action = command[2]
                if action == "stop":
                    events.append("stop")
                    service = "inactive"
                    return subprocess.CompletedProcess(command, 0)
                events.append(f"show-{service}")
                sub = "start" if service == "activating" else "dead"
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=f"ActiveState={service}\nSubState={sub}\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    entry = (
                        f"601 30 0:601 / {encoded_mount} ro,nosuid,nodev - "
                        "fuse.rclone proton-dolphin: ro\n"
                    )
                    return io.StringIO(entry if mounted else "")
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["stop"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                },
                run=external,
                opened=opened,
            )

            self.assertEqual((0, "stopped\n", ""), result)
            self.assertLess(events.index("unmount"), events.index("stop"))
            self.assertFalse(mount.exists())
            self.assertFalse((runtime / "mountpoint.json").exists())

    def test_stop_uses_owned_unmount_after_torn_inactive_ready_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            publish_mount_record(mount, runtime, "602", True)
            encoded_mount = str(mount).replace(" ", "\\040")
            service = "inactive"
            mounted = True
            first_show = True
            events = []

            def external(command, **kwargs):
                nonlocal service, mounted, first_show
                if command[0] == "/usr/bin/fusermount3":
                    events.append("unmount")
                    mounted = False
                    return subprocess.CompletedProcess(command, 0)
                action = command[2]
                if action == "stop":
                    events.append("stop")
                    service = "inactive"
                    return subprocess.CompletedProcess(command, 0)
                observed = service
                events.append(f"show-{observed}")
                if first_show:
                    service = "active"
                    first_show = False
                sub = "running" if observed == "active" else "dead"
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=(
                        f"ActiveState={observed}\nSubState={sub}\n"
                        "Result=success\n"
                    ),
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    entry = (
                        f"602 30 0:602 / {encoded_mount} ro,nosuid,nodev - "
                        "fuse.rclone proton-dolphin: ro\n"
                    )
                    return io.StringIO(entry if mounted else "")
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["stop"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                },
                run=external,
                opened=opened,
            )

            self.assertEqual((0, "stopped\n", ""), result)
            self.assertEqual(["show-inactive", "show-active"], events[:2])
            self.assertLess(events.index("unmount"), events.index("stop"))
            self.assertFalse(mount.exists())
            self.assertFalse((runtime / "mountpoint.json").exists())

    def test_stop_cancels_queued_start_after_inactive_observation_before_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            data_home = root / "data"
            runtime = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            data_home.mkdir(mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            mount = data_home / "proton-drive-desktop/files"
            private_runtime = runtime / "proton-drive-desktop"
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(data_home),
                "XDG_RUNTIME_DIR": str(runtime),
            }
            queued_start = "queued"
            initial_mount_snapshot = True
            preparing = False

            def external(command, **kwargs):
                nonlocal queued_start
                if command[2] == "stop":
                    self.assertEqual("prepared", queued_start)
                    self.assertTrue(mount.is_dir())
                    self.assertTrue((private_runtime / "mountpoint.json").is_file())
                    queued_start = "canceled"
                    return subprocess.CompletedProcess(command, 0)
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="ActiveState=inactive\nSubState=dead\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                nonlocal initial_mount_snapshot, preparing, queued_start
                if name == "/proc/self/mountinfo":
                    if initial_mount_snapshot and not preparing:
                        initial_mount_snapshot = False
                        preparing = True
                        prepared = invoke(
                            ["_prepare"], environment, run=external, opened=opened
                        )
                        preparing = False
                        self.assertEqual((0, "", ""), prepared)
                        queued_start = "prepared"
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["stop"], environment, run=external, opened=opened
            )

            self.assertEqual((0, "stopped\n", ""), result)
            self.assertEqual("canceled", queued_start)
            self.assertFalse(mount.exists())
            self.assertFalse((private_runtime / "mountpoint.json").exists())

    def test_inactive_stop_failure_preserves_prepared_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            publish_mount_record(mount, runtime, "62", True)
            marker = runtime / "mountpoint.json"
            recorded = marker.read_bytes()

            def external(command, **kwargs):
                if command[2] == "stop":
                    return subprocess.CompletedProcess(command, 1)
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="ActiveState=inactive\nSubState=dead\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["stop"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                },
                run=external,
                opened=opened,
            )

            self.assertEqual((1, "", "service stop failed\n"), result)
            self.assertTrue(mount.is_dir())
            self.assertEqual(recorded, marker.read_bytes())

    def test_inactive_stop_preserves_mount_found_by_final_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            publish_mount_record(mount, runtime, "63", True)
            marker = runtime / "mountpoint.json"
            recorded = marker.read_bytes()
            encoded_mount = str(mount).replace(" ", "\\040")
            stop_completed = False

            def external(command, **kwargs):
                nonlocal stop_completed
                if command[2] == "stop":
                    stop_completed = True
                    return subprocess.CompletedProcess(command, 0)
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="ActiveState=inactive\nSubState=dead\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    entry = (
                        f"63 30 0:63 / {encoded_mount} ro,nosuid,nodev - "
                        "fuse.rclone proton-dolphin: ro\n"
                    )
                    return io.StringIO(entry if stop_completed else "")
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["stop"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                },
                run=external,
                opened=opened,
            )

            self.assertEqual(
                (1, "", "service stop incomplete: inconsistent/foreign state\n"),
                result,
            )
            self.assertTrue(mount.is_dir())
            self.assertEqual(recorded, marker.read_bytes())

    def test_busy_stop_preserves_the_running_service_and_mountpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            mount.mkdir(parents=True, mode=0o700)
            runtime.mkdir(parents=True, mode=0o700)
            information = mount.stat()
            (runtime / "mountpoint.json").write_text(
                '{"mount":' + repr(str(mount)).replace("'", '"')
                + f',"device":{information.st_dev},"inode":{information.st_ino},'
                '"created":true,"nonce":"' + "71" * 32
                + '","mount_id":"71"}'
            )
            encoded_mount = str(mount).replace(" ", "\\040")
            mountinfo = (
                f"71 30 0:71 / {encoded_mount} ro,nosuid,nodev - "
                "fuse.rclone proton-dolphin: ro\n"
            )
            events = []

            def external(command, **kwargs):
                if command[0] == "/usr/bin/fusermount3":
                    events.append("unmount-busy")
                    return subprocess.CompletedProcess(command, 1)
                if command[2] == "stop":
                    events.append("stop")
                    return subprocess.CompletedProcess(command, 0)
                events.append("show")
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="ActiveState=active\nSubState=running\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO(mountinfo)
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["stop"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                },
                run=external,
                opened=opened,
            )

            self.assertEqual(
                (1, "", "mount is busy; close open files and try again\n"), result
            )
            self.assertEqual(["show", "unmount-busy"], events)
            self.assertTrue(mount.is_dir())
            self.assertTrue((runtime / "mountpoint.json").exists())

    def test_service_entrypoints_prepare_verify_and_cleanup_without_querying_itself(self):
        with tempfile.TemporaryDirectory(prefix="proton service ") as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            data_home = root / "data"
            runtime = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            data_home.mkdir(mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            mount = data_home / "proton-drive-desktop/files"
            encoded_mount = str(mount).replace(" ", "\\040")
            mounted = False

            def no_process(*args, **kwargs):
                raise AssertionError("service entrypoint queried a process boundary")

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    line = (
                        f"81 30 0:81 / {encoded_mount} ro,nosuid,nodev - "
                        "fuse.rclone proton-dolphin{abc12}: ro\n"
                    )
                    return io.StringIO(line if mounted else "")
                return io.open(name, *args, **kwargs)

            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(data_home),
                "XDG_RUNTIME_DIR": str(runtime),
            }
            prepared = invoke(["_prepare"], environment, run=no_process, opened=opened)
            self.assertEqual((0, "", ""), prepared)
            self.assertTrue(mount.is_dir())

            mounted = True
            verified = invoke(["_verify-mount"], environment, run=no_process, opened=opened)
            self.assertEqual((0, "", ""), verified)

            mounted = False
            cleaned = invoke(["_post-stop"], environment, run=no_process, opened=opened)
            self.assertEqual((0, "", ""), cleaned)
            self.assertFalse(mount.exists())

    def test_service_prepare_rejects_mounted_targets_before_target_traversal(self):
        for mounted_case in ("matching", "wrong-source", "duplicate"):
            with self.subTest(mounted_case=mounted_case), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                config_parent = root / "config/rclone"
                data_home = root / "data"
                runtime = root / "run"
                mount = data_home / "proton-drive-desktop/files"
                config_parent.mkdir(parents=True, mode=0o700)
                data_home.mkdir(mode=0o700)
                runtime.mkdir(mode=0o700)
                mount.mkdir(parents=True, mode=0o700)
                config = config_parent / "proton-drive.conf"
                config.write_text("encrypted-placeholder")
                config.chmod(0o600)
                encoded_mount = str(mount).replace(" ", "\\040")
                matching = (
                    f"181 30 0:181 / {encoded_mount} ro,nosuid,nodev - "
                    "fuse.rclone proton-dolphin: ro\n"
                )
                mountinfo = {
                    "matching": matching,
                    "wrong-source": (
                        f"182 30 0:182 / {encoded_mount} rw,nosuid,nodev - "
                        "fuse.other local: rw\n"
                    ),
                    "duplicate": matching + matching.replace("181", "183"),
                }[mounted_case]
                target_accesses = []
                original_lstat = pathlib.Path.lstat
                original_scandir = os.scandir

                def watched_lstat(path, *args, **kwargs):
                    if path == mount:
                        target_accesses.append("lstat")
                    return original_lstat(path, *args, **kwargs)

                def watched_scandir(path, *args, **kwargs):
                    if pathlib.Path(path) == mount:
                        target_accesses.append("scandir")
                    return original_scandir(path, *args, **kwargs)

                def opened(name, *args, **kwargs):
                    if name == "/proc/self/mountinfo":
                        return io.StringIO(mountinfo)
                    return io.open(name, *args, **kwargs)

                process = mock.Mock(side_effect=AssertionError("process boundary reached"))
                launch = mock.Mock(side_effect=AssertionError("rclone launch reached"))
                with mock.patch.object(
                    pathlib.Path, "lstat", autospec=True, side_effect=watched_lstat
                ), mock.patch("os.scandir", side_effect=watched_scandir):
                    result = invoke(
                        ["_prepare"],
                        {
                            "HOME": temporary,
                            "XDG_CONFIG_HOME": str(root / "config"),
                            "XDG_DATA_HOME": str(data_home),
                            "XDG_RUNTIME_DIR": str(runtime),
                        },
                        run=process,
                        execve=launch,
                        opened=opened,
                    )

                self.assertEqual(
                    (1, "", "mountpoint is already mounted; preserving it\n"),
                    result,
                )
                self.assertEqual([], target_accesses)
                self.assertFalse((runtime / "proton-drive-desktop/mountpoint.json").exists())
                process.assert_not_called()
                launch.assert_not_called()

    def test_mount_entrypoint_rejects_mounted_targets_before_target_traversal(self):
        for mounted_case in ("matching", "wrong-source", "duplicate"):
            with self.subTest(mounted_case=mounted_case), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                config_parent = root / "config/rclone"
                mount = root / "data/proton-drive-desktop/files"
                config_parent.mkdir(parents=True, mode=0o700)
                mount.mkdir(parents=True, mode=0o700)
                config = config_parent / "proton-drive.conf"
                config.write_text("encrypted-placeholder")
                config.chmod(0o600)
                encoded_mount = str(mount).replace(" ", "\\040")
                matching = (
                    f"184 30 0:184 / {encoded_mount} ro,nosuid,nodev - "
                    "fuse.rclone proton-dolphin: ro\n"
                )
                mountinfo = {
                    "matching": matching,
                    "wrong-source": (
                        f"185 30 0:185 / {encoded_mount} rw,nosuid,nodev - "
                        "fuse.other local: rw\n"
                    ),
                    "duplicate": matching + matching.replace("184", "186"),
                }[mounted_case]
                target_accesses = []
                original_lstat = pathlib.Path.lstat
                original_scandir = os.scandir

                def watched_lstat(path, *args, **kwargs):
                    if path == mount:
                        target_accesses.append("lstat")
                    return original_lstat(path, *args, **kwargs)

                def watched_scandir(path, *args, **kwargs):
                    if pathlib.Path(path) == mount:
                        target_accesses.append("scandir")
                    return original_scandir(path, *args, **kwargs)

                def opened(name, *args, **kwargs):
                    if name == "/proc/self/mountinfo":
                        return io.StringIO(mountinfo)
                    return io.open(name, *args, **kwargs)

                process = mock.Mock()
                launch = mock.Mock()
                with mock.patch.object(
                    pathlib.Path, "lstat", autospec=True, side_effect=watched_lstat
                ), mock.patch("os.scandir", side_effect=watched_scandir):
                    result = invoke(
                        ["_mount"],
                        {
                            "HOME": temporary,
                            "XDG_CONFIG_HOME": str(root / "config"),
                            "XDG_DATA_HOME": str(root / "data"),
                            "XDG_RUNTIME_DIR": str(root / "run"),
                        },
                        run=process,
                        execve=launch,
                        opened=opened,
                    )

                self.assertEqual(
                    (1, "", "mountpoint is already mounted; preserving it\n"),
                    result,
                )
                self.assertEqual([], target_accesses)
                process.assert_not_called()
                launch.assert_not_called()

    def test_mount_entrypoint_revalidates_the_prepared_empty_directory(self):
        for mutation, wanted_error in (
            ("replacement", "mountpoint was replaced; preserving it\n"),
            ("contents", "mountpoint contains unexpected local contents\n"),
            ("missing-record", "mountpoint ownership record is invalid\n"),
            ("malformed-record", "mountpoint ownership record is invalid\n"),
            ("wrong-path-record", "mountpoint ownership record is invalid\n"),
            ("wrong-identity-record", "mountpoint was replaced; preserving it\n"),
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                config_parent = root / "config/rclone"
                data_home = root / "data"
                runtime = root / "run"
                config_parent.mkdir(parents=True, mode=0o700)
                data_home.mkdir(mode=0o700)
                runtime.mkdir(mode=0o700)
                config = config_parent / "proton-drive.conf"
                config.write_text("encrypted-placeholder")
                config.chmod(0o600)
                mount = data_home / "proton-drive-desktop/files"
                environment = {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(data_home),
                    "XDG_RUNTIME_DIR": str(runtime),
                }

                def opened(name, *args, **kwargs):
                    if name == "/proc/self/mountinfo":
                        return io.StringIO("")
                    return io.open(name, *args, **kwargs)

                self.assertEqual(
                    (0, "", ""), invoke(["_prepare"], environment, opened=opened)
                )
                marker = runtime / "proton-drive-desktop/mountpoint.json"
                prepared_marker = marker.read_bytes()
                if mutation == "replacement":
                    mount.rmdir()
                    mount.mkdir(mode=0o700)
                elif mutation == "contents":
                    (mount / "unexpected.txt").write_text("preserve me\n")
                elif mutation == "missing-record":
                    marker.unlink()
                elif mutation == "malformed-record":
                    marker.write_text("[]")
                elif mutation == "wrong-path-record":
                    ownership = json.loads(marker.read_text())
                    ownership["mount"] = str(root / "other mount")
                    marker.write_text(json.dumps(ownership))
                elif mutation == "wrong-identity-record":
                    ownership = json.loads(marker.read_text())
                    ownership["inode"] += 1
                    marker.write_text(json.dumps(ownership))
                marker_after_mutation = marker.read_bytes() if marker.exists() else None

                launch = mock.Mock()
                result = invoke(
                    ["_mount"], environment, execve=launch, opened=opened
                )

                self.assertEqual((1, "", wanted_error), result)
                launch.assert_not_called()
                self.assertEqual(
                    marker_after_mutation,
                    marker.read_bytes() if marker.exists() else None,
                )
                if mutation in {"replacement", "contents"}:
                    self.assertEqual(prepared_marker, marker.read_bytes())

    def test_stop_preserves_a_matching_mount_without_session_ownership(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            mount.mkdir(parents=True, mode=0o700)
            (root / "run").mkdir(mode=0o700)
            encoded_mount = str(mount).replace(" ", "\\040")
            entry = (
                f"91 30 0:91 / {encoded_mount} ro,nosuid,nodev - "
                "fuse.rclone proton-dolphin: ro\n"
            )
            calls = []

            def external(command, **kwargs):
                calls.append(command)
                if command[0] != "/usr/bin/systemctl" or command[2] != "show":
                    raise AssertionError("foreign mount was modified")
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="ActiveState=active\nSubState=running\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO(entry)
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["stop"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                },
                run=external,
                opened=opened,
            )

            self.assertEqual((1, "", "mount is not owned by this session\n"), result)
            self.assertEqual(1, len(calls))
            self.assertTrue(mount.is_dir())

    def test_startup_mount_mismatch_never_opens_dolphin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            data_home = root / "data"
            runtime = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            data_home.mkdir(mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            mount = data_home / "proton-drive-desktop/files"
            encoded_mount = str(mount).replace(" ", "\\040")
            started = False

            def external(command, **kwargs):
                nonlocal started
                if command[2] == "start":
                    started = True
                    return subprocess.CompletedProcess(command, 0)
                state = "active" if started else "inactive"
                sub = "running" if started else "dead"
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=f"ActiveState={state}\nSubState={sub}\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    wrong = (
                        f"101 30 0:101 / {encoded_mount} rw,nosuid,nodev - "
                        "fuse.rclone wrong-remote: rw\n"
                    )
                    return io.StringIO(wrong if started else "")
                return io.open(name, *args, **kwargs)

            dolphin = mock.Mock(side_effect=AssertionError("Dolphin was opened"))
            result = invoke(
                ["open"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(data_home),
                    "XDG_RUNTIME_DIR": str(runtime),
                },
                run=external,
                popen=dolphin,
                opened=opened,
            )

            self.assertEqual(
                (1, "", "service startup did not become ready: inconsistent/foreign state\n"),
                result,
            )
            dolphin.assert_not_called()

    def test_repeated_start_waits_for_an_existing_start_job(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            mount.mkdir(parents=True, mode=0o700)
            runtime = root / "run/proton-drive-desktop"
            runtime.mkdir(parents=True, mode=0o700)
            information = mount.stat()
            (runtime / "mountpoint.json").write_text(json.dumps({
                "mount": str(mount), "device": information.st_dev,
                "inode": information.st_ino, "created": False,
            }))
            encoded_mount = str(mount).replace(" ", "\\040")
            active = False
            events = []

            def external(command, **kwargs):
                nonlocal active
                if command[2] == "start":
                    events.append("wait-start-job")
                    publish_mount_record(mount, runtime, "106", False)
                    active = True
                    return subprocess.CompletedProcess(command, 0)
                events.append("show-active" if active else "show-starting")
                state = "active" if active else "activating"
                sub = "running" if active else "start-post"
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=f"ActiveState={state}\nSubState={sub}\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    line = (
                        f"106 30 0:106 / {encoded_mount} ro,nosuid,nodev - "
                        "fuse.rclone proton-dolphin: ro\n"
                    )
                    return io.StringIO(line)
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["start"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                },
                run=external,
                opened=opened,
            )

            self.assertEqual((0, "ready\n", ""), result)
            self.assertEqual(["show-starting", "wait-start-job", "show-active"], events)

    def test_start_reuses_owned_mount_after_torn_inactive_ready_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            publish_mount_record(mount, runtime, "123", False)
            encoded_mount = str(mount).replace(" ", "\\040")
            active = False
            events = []

            def external(command, **kwargs):
                nonlocal active
                action = command[2]
                if action == "start":
                    raise AssertionError("stable owned mount was restarted")
                observed = "active" if active else "inactive"
                events.append(f"show-{observed}")
                active = True
                sub = "running" if observed == "active" else "dead"
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=(
                        f"ActiveState={observed}\nSubState={sub}\n"
                        "Result=success\n"
                    ),
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    events.append("mount-ready")
                    return io.StringIO(
                        f"123 30 0:123 / {encoded_mount} ro,nosuid,nodev - "
                        "fuse.rclone proton-dolphin: ro\n"
                    )
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["start"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                },
                run=external,
                opened=opened,
            )

            self.assertEqual((0, "ready\n", ""), result)
            self.assertEqual(
                ["show-inactive", "mount-ready", "show-active", "mount-ready"],
                events,
            )

    def test_open_reuses_owned_mount_after_torn_inactive_ready_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            publish_mount_record(mount, runtime, "124", False)
            encoded_mount = str(mount).replace(" ", "\\040")
            active = False
            events = []

            def external(command, **kwargs):
                nonlocal active
                if command[2] == "start":
                    raise AssertionError("stable owned mount was restarted")
                observed = "active" if active else "inactive"
                events.append(f"show-{observed}")
                active = True
                sub = "running" if observed == "active" else "dead"
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=(
                        f"ActiveState={observed}\nSubState={sub}\n"
                        "Result=success\n"
                    ),
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    events.append("mount-ready")
                    return io.StringIO(
                        f"124 30 0:124 / {encoded_mount} ro,nosuid,nodev - "
                        "fuse.rclone proton-dolphin: ro\n"
                    )
                return io.open(name, *args, **kwargs)

            def launch(command, **kwargs):
                events.append(("dolphin", command))
                return mock.Mock()

            result = invoke(
                ["open"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                },
                run=external,
                popen=launch,
                opened=opened,
            )

            self.assertEqual((0, "ready\n", ""), result)
            self.assertEqual(
                [
                    "show-inactive", "mount-ready", "show-active", "mount-ready",
                    "show-active", "mount-ready",
                    ("dolphin", ["/usr/bin/dolphin", str(mount)]),
                ],
                events,
            )

    def test_start_bounds_persistently_torn_inactive_ready_observations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            publish_mount_record(mount, runtime, "125", False)
            encoded_mount = str(mount).replace(" ", "\\040")
            observations = []

            def external(command, **kwargs):
                if command[2] == "start":
                    raise AssertionError("persistently inconsistent mount was restarted")
                observations.append("service")
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="ActiveState=inactive\nSubState=dead\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    observations.append("mount")
                    return io.StringIO(
                        f"125 30 0:125 / {encoded_mount} ro,nosuid,nodev - "
                        "fuse.rclone proton-dolphin: ro\n"
                    )
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["start"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                },
                run=external,
                opened=opened,
            )

            self.assertEqual((1, "", "inconsistent/foreign state\n"), result)
            self.assertEqual(["service", "mount", "service", "mount"], observations)

    def test_concurrent_starts_share_one_locked_service_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            data_home = root / "data"
            runtime = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            data_home.mkdir(mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            mount = data_home / "proton-drive-desktop/files"
            encoded_mount = str(mount).replace(" ", "\\040")
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(data_home),
                "XDG_RUNTIME_DIR": str(runtime),
            }
            module = runpy.run_path(str(PROGRAM), run_name="proton_drive_test_module")
            entered_start = threading.Event()
            release_start = threading.Event()
            ready = threading.Event()
            starts = 0
            fake_lock = threading.Lock()

            class FakeSubprocess:
                PIPE = subprocess.PIPE
                DEVNULL = subprocess.DEVNULL

                @staticmethod
                def run(command, **kwargs):
                    nonlocal starts
                    if command[2] == "start":
                        with fake_lock:
                            starts += 1
                        entered_start.set()
                        release_start.wait(2)
                        publish_mount_record(
                            mount, runtime / "proton-drive-desktop", "111", True
                        )
                        ready.set()
                        return subprocess.CompletedProcess(command, 0)
                    active = "active" if ready.is_set() else "inactive"
                    sub = "running" if ready.is_set() else "dead"
                    return subprocess.CompletedProcess(
                        command, 0,
                        stdout=f"ActiveState={active}\nSubState={sub}\nResult=success\n",
                    )

            module["main"].__globals__["subprocess"] = FakeSubprocess

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    line = (
                        f"111 30 0:111 / {encoded_mount} ro,nosuid,nodev - "
                        "fuse.rclone proton-dolphin: ro\n"
                    )
                    return io.StringIO(line if ready.is_set() else "")
                return io.open(name, *args, **kwargs)

            results = []

            def worker():
                results.append(module["main"](["start"]))

            with mock.patch.dict(os.environ, environment, clear=True), mock.patch(
                "builtins.open", side_effect=opened
            ), contextlib.redirect_stdout(io.StringIO()):
                first = threading.Thread(target=worker)
                second = threading.Thread(target=worker)
                first.start()
                self.assertTrue(entered_start.wait(1))
                second.start()
                time.sleep(0.05)
                self.assertEqual(1, starts)
                release_start.set()
                first.join(2)
                second.join(2)

            self.assertEqual([0, 0], sorted(results))
            self.assertEqual(1, starts)

    def test_start_reuses_service_first_preparation_after_stale_stopped_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            data_home = root / "data"
            runtime_base = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            data_home.mkdir(mode=0o700)
            runtime_base.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            module = runpy.run_path(str(PROGRAM), run_name="proton_drive_test_module")
            resolved = {
                "config": config,
                "mount": data_home / "proton-drive-desktop/files",
                "runtime": runtime_base / "proton-drive-desktop",
            }
            service_paths = {
                "config": root / "service config/rclone/proton-drive.conf",
                "mount": root / "service data/proton-drive-desktop/files",
                "runtime": resolved["runtime"],
            }
            encoded_mount = str(resolved["mount"]).replace(" ", "\\040")
            stale_mount_read = threading.Event()
            service_ready = threading.Event()
            mounted = False
            service_outcome = []

            class StaleMountinfo(io.StringIO):
                def __exit__(self, *args):
                    stale_mount_read.set()
                    if not service_ready.wait(2):
                        raise AssertionError("synthetic service did not become ready")
                    return super().__exit__(*args)

            class FakeSubprocess:
                PIPE = subprocess.PIPE
                DEVNULL = subprocess.DEVNULL

                @staticmethod
                def run(command, **kwargs):
                    if command[2] == "start":
                        self.assertTrue(service_ready.is_set())
                        return subprocess.CompletedProcess(command, 0)
                    active = "active" if service_ready.is_set() else "inactive"
                    sub = "running" if service_ready.is_set() else "dead"
                    return subprocess.CompletedProcess(
                        command, 0,
                        stdout=f"ActiveState={active}\nSubState={sub}\nResult=success\n",
                    )

            public_mount_reads = 0

            def opened(name, *args, **kwargs):
                nonlocal public_mount_reads
                if name == "/proc/self/mountinfo":
                    line = (
                        f"211 30 0:211 / {encoded_mount} ro,nosuid,nodev - "
                        "fuse.rclone proton-dolphin: ro\n"
                    )
                    if threading.current_thread().name == "public-start":
                        public_mount_reads += 1
                        if public_mount_reads == 1:
                            return StaleMountinfo("")
                    return io.StringIO(line if mounted else "")
                return io.open(name, *args, **kwargs)

            module["service_state"].__globals__["subprocess"] = FakeSubprocess

            def run_service():
                nonlocal mounted
                try:
                    self.assertTrue(stale_mount_read.wait(1))
                    service_outcome.append(module["service_prepare"](service_paths))
                    authoritative = module["authoritative_paths"](service_paths)
                    mounted = True
                    service_outcome.append(module["service_verify_mount"](authoritative))
                finally:
                    service_ready.set()

            result = []

            def run_public():
                try:
                    result.append(("return", module["start"](resolved)))
                except Exception as error:
                    result.append(("error", type(error).__name__, str(error)))

            with mock.patch("builtins.open", side_effect=opened), \
                    contextlib.redirect_stdout(io.StringIO()):
                service_thread = threading.Thread(target=run_service, name="service-prepare")
                public_thread = threading.Thread(target=run_public, name="public-start")
                service_thread.start()
                public_thread.start()
                public_thread.join(3)
                service_thread.join(3)

            self.assertFalse(public_thread.is_alive())
            self.assertFalse(service_thread.is_alive())
            self.assertEqual([0, 0], service_outcome)
            self.assertEqual([("return", 0)], result)
            binding = json.loads((resolved["runtime"] / "binding.json").read_text())
            self.assertEqual(str(resolved["config"]), binding["config"])
            self.assertEqual(str(resolved["mount"]), binding["mount"])
            marker = json.loads((resolved["runtime"] / "mountpoint.json").read_text())
            self.assertEqual(str(resolved["mount"]), marker["mount"])
            self.assertTrue(marker["created"])
            self.assertEqual("211", marker["mount_id"])

    def test_concurrent_public_and_service_first_binding_have_one_winner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            runtime = root / "run"
            runtime.mkdir(mode=0o700)
            module = runpy.run_path(str(PROGRAM), run_name="proton_drive_test_module")
            public = {
                "config": root / "public config/rclone/proton-drive.conf",
                "mount": root / "public data/proton-drive-desktop/files",
                "runtime": runtime / "proton-drive-desktop",
            }
            service = {
                "config": root / "service config/rclone/proton-drive.conf",
                "mount": root / "service data/proton-drive-desktop/files",
                "runtime": runtime / "proton-drive-desktop",
            }
            read_barrier = threading.Barrier(2)
            replace_barrier = threading.Barrier(2)
            service_replaced = threading.Event()
            original_read = module["read_binding"]
            original_os = module["establish_binding"].__globals__["os"]
            prepared = []
            outcomes = []

            def coordinated_read(resolved):
                binding = original_read(resolved)
                if binding is None:
                    try:
                        read_barrier.wait(0.25)
                    except threading.BrokenBarrierError:
                        pass
                return binding

            class CoordinatedOS:
                def __getattr__(self, name):
                    return getattr(original_os, name)

                @staticmethod
                def replace(source, destination):
                    try:
                        replace_barrier.wait(0.25)
                    except threading.BrokenBarrierError:
                        original_os.replace(source, destination)
                        return
                    if threading.current_thread().name == "service-prepare":
                        original_os.replace(source, destination)
                        service_replaced.set()
                        return
                    service_replaced.wait(1)
                    original_os.replace(source, destination)

            def prepared_path(resolved, announce=True):
                prepared.append((resolved["config"], resolved["mount"]))
                return 0

            def service_prepared_path(resolved):
                prepared.append((resolved["config"], resolved["mount"]))

            module["establish_binding"].__globals__["os"] = CoordinatedOS()
            module["establish_binding"].__globals__["read_binding"] = coordinated_read
            module["start"].__globals__["start_locked"] = prepared_path
            module["service_prepare"].__globals__["prepare_mountpoint"] = service_prepared_path

            def worker(name, operation, resolved):
                try:
                    outcomes.append((name, operation(resolved)))
                except Exception as error:
                    outcomes.append((name, type(error).__name__))

            public_thread = threading.Thread(
                target=worker, name="public-start", args=("public", module["start"], public),
            )
            service_thread = threading.Thread(
                target=worker, name="service-prepare",
                args=("service", module["service_prepare"], service),
            )
            public_thread.start()
            service_thread.start()
            public_thread.join(2)
            service_thread.join(2)

            self.assertFalse(public_thread.is_alive())
            self.assertFalse(service_thread.is_alive())
            self.assertEqual([("public", 0), ("service", 0)], sorted(outcomes))
            binding = json.loads((public["runtime"] / "binding.json").read_text())
            authoritative = (pathlib.Path(binding["config"]), pathlib.Path(binding["mount"]))
            self.assertEqual([authoritative, authoritative], sorted(prepared))

    def test_start_does_not_traverse_or_republish_during_unit_transition(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            data_home = root / "data"
            runtime_base = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            data_home.mkdir(mode=0o700)
            runtime_base.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            module = runpy.run_path(str(PROGRAM), run_name="proton_drive_test_module")
            resolved = {
                "config": config,
                "mount": data_home / "proton-drive-desktop/files",
                "runtime": runtime_base / "proton-drive-desktop",
            }
            service_paths = {
                "config": root / "service config/rclone/proton-drive.conf",
                "mount": root / "service data/proton-drive-desktop/files",
                "runtime": resolved["runtime"],
            }
            encoded_mount = str(resolved["mount"]).replace(" ", "\\040")
            stale_mount_read = threading.Event()
            service_prepared = threading.Event()
            advance_service = threading.Event()
            service_verified = threading.Event()
            mounted = False
            public_mount_reads = 0
            mounted_target_accesses = []
            public_marker_writes = []
            service_outcome = []

            class InitialMountinfo(io.StringIO):
                def __exit__(self, *args):
                    stale_mount_read.set()
                    if not service_prepared.wait(2):
                        raise AssertionError("synthetic service did not prepare")
                    return super().__exit__(*args)

            class TransitionMountinfo(io.StringIO):
                def __exit__(self, *args):
                    advance_service.set()
                    if not service_verified.wait(2):
                        raise AssertionError("synthetic service did not verify")
                    return super().__exit__(*args)

            class FakeSubprocess:
                PIPE = subprocess.PIPE
                DEVNULL = subprocess.DEVNULL

                @staticmethod
                def run(command, **kwargs):
                    if command[2] == "start":
                        advance_service.set()
                        self.assertTrue(service_verified.wait(2))
                        return subprocess.CompletedProcess(command, 0)
                    active = "active" if service_verified.is_set() else "inactive"
                    sub = "running" if service_verified.is_set() else "dead"
                    return subprocess.CompletedProcess(
                        command, 0,
                        stdout=f"ActiveState={active}\nSubState={sub}\nResult=success\n",
                    )

            def opened(name, *args, **kwargs):
                nonlocal public_mount_reads
                if name == "/proc/self/mountinfo":
                    line = (
                        f"212 30 0:212 / {encoded_mount} ro,nosuid,nodev - "
                        "fuse.rclone proton-dolphin: ro\n"
                    )
                    if threading.current_thread().name == "public-start":
                        public_mount_reads += 1
                        if public_mount_reads == 1:
                            return InitialMountinfo("")
                        if not mounted:
                            return TransitionMountinfo("")
                    return io.StringIO(line if mounted else "")
                return io.open(name, *args, **kwargs)

            original_scandir = os.scandir
            original_write_marker = module["write_marker"]

            def watched_scandir(path, *args, **kwargs):
                if pathlib.Path(path) == resolved["mount"] and mounted:
                    mounted_target_accesses.append(threading.current_thread().name)
                return original_scandir(path, *args, **kwargs)

            def watched_write_marker(paths, ownership):
                if threading.current_thread().name == "public-start":
                    public_marker_writes.append(dict(ownership))
                return original_write_marker(paths, ownership)

            module["service_state"].__globals__["subprocess"] = FakeSubprocess
            module["write_marker"].__globals__["write_marker"] = watched_write_marker

            def run_service():
                nonlocal mounted
                try:
                    self.assertTrue(stale_mount_read.wait(1))
                    service_outcome.append(module["service_prepare"](service_paths))
                    authoritative = module["authoritative_paths"](service_paths)
                    service_prepared.set()
                    self.assertTrue(advance_service.wait(2))
                    mounted = True
                    service_outcome.append(module["service_verify_mount"](authoritative))
                finally:
                    service_verified.set()

            public_outcome = []

            def run_public():
                try:
                    public_outcome.append(("return", module["start"](resolved)))
                except Exception as error:
                    public_outcome.append(("error", type(error).__name__, str(error)))

            with mock.patch("builtins.open", side_effect=opened), \
                    mock.patch("os.scandir", side_effect=watched_scandir), \
                    contextlib.redirect_stdout(io.StringIO()):
                service_thread = threading.Thread(target=run_service, name="service-prepare")
                public_thread = threading.Thread(target=run_public, name="public-start")
                service_thread.start()
                public_thread.start()
                public_thread.join(3)
                service_thread.join(3)

            self.assertFalse(public_thread.is_alive())
            self.assertFalse(service_thread.is_alive())
            self.assertEqual([0, 0], service_outcome)
            self.assertEqual([("return", 0)], public_outcome)
            self.assertEqual([], mounted_target_accesses)
            self.assertEqual([], public_marker_writes)
            binding = json.loads((resolved["runtime"] / "binding.json").read_text())
            self.assertEqual(str(resolved["config"]), binding["config"])
            self.assertEqual(str(resolved["mount"]), binding["mount"])
            marker = json.loads((resolved["runtime"] / "mountpoint.json").read_text())
            self.assertEqual(str(resolved["mount"]), marker["mount"])
            self.assertTrue(marker["created"])
            self.assertEqual("212", marker["mount_id"])

    def test_public_start_does_not_hold_binding_lock_while_service_prepares(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            runtime = root / "run"
            runtime.mkdir(mode=0o700)
            module = runpy.run_path(str(PROGRAM), run_name="proton_drive_test_module")
            public = {
                "config": root / "public config/rclone/proton-drive.conf",
                "mount": root / "public data/proton-drive-desktop/files",
                "runtime": runtime / "proton-drive-desktop",
            }
            service = {
                "config": root / "service config/rclone/proton-drive.conf",
                "mount": root / "service data/proton-drive-desktop/files",
                "runtime": runtime / "proton-drive-desktop",
            }
            prepared = []
            service_outcome = []
            service_thread = None

            def prepare_mountpoint(resolved):
                prepared.append((resolved["config"], resolved["mount"]))

            def wait_for_service(resolved, announce=True):
                nonlocal service_thread

                def prepare_service():
                    service_outcome.append(module["service_prepare"](service))

                service_thread = threading.Thread(target=prepare_service)
                service_thread.start()
                service_thread.join(1)
                if service_thread.is_alive():
                    raise module["OperationError"]("service preparation deadlocked")
                prepared.append((resolved["config"], resolved["mount"]))
                return 0

            module["service_prepare"].__globals__["prepare_mountpoint"] = prepare_mountpoint
            module["start"].__globals__["start_locked"] = wait_for_service

            self.assertEqual(0, module["start"](public))
            service_thread.join(1)
            self.assertFalse(service_thread.is_alive())
            self.assertEqual([0], service_outcome)
            self.assertEqual([prepared[0], prepared[0]], prepared)

    def test_cleanup_finishes_before_overlapping_preparation_publishes_new_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            data_home = root / "data"
            runtime_base = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            data_home.mkdir(mode=0o700)
            runtime_base.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            module = runpy.run_path(str(PROGRAM), run_name="proton_drive_test_module")
            resolved = {
                "config": config,
                "mount": data_home / "proton-drive-desktop/files",
                "runtime": runtime_base / "proton-drive-desktop",
            }
            service = "inactive"
            public_mount_reads = 0
            preparation_finished = threading.Event()
            preparation_outcome = []
            preparation_thread = None

            class FinalPublicMountinfo(io.StringIO):
                def __exit__(self, *args):
                    nonlocal preparation_thread
                    preparation_thread = threading.Thread(
                        target=prepare_again, name="overlapping-prepare"
                    )
                    preparation_thread.start()
                    preparation_finished.wait(0.5)
                    return super().__exit__(*args)

            def external(command, **kwargs):
                nonlocal service
                if command[2] == "stop":
                    service = "inactive"
                    return subprocess.CompletedProcess(command, 0)
                sub = "start-pre" if service == "activating" else "dead"
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=(
                        f"ActiveState={service}\nSubState={sub}\n"
                        "Result=success\n"
                    ),
                )

            def opened(name, *args, **kwargs):
                nonlocal public_mount_reads
                if name == "/proc/self/mountinfo":
                    if threading.current_thread().name == "public-stop":
                        public_mount_reads += 1
                        if public_mount_reads == 2:
                            return FinalPublicMountinfo("")
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            def prepare_again():
                nonlocal service
                try:
                    preparation_outcome.append(module["service_prepare"](resolved))
                    service = "activating"
                except Exception as error:
                    preparation_outcome.append((type(error).__name__, str(error)))
                finally:
                    preparation_finished.set()

            module["service_state"].__globals__["subprocess"] = subprocess
            with mock.patch("subprocess.run", side_effect=external), mock.patch(
                "builtins.open", side_effect=opened
            ):
                self.assertEqual(0, module["service_prepare"](resolved))
                self.assertTrue(json.loads(
                    module["marker_path"](resolved).read_text()
                )["created"])
                stop_outcome = []

                def stop_publicly():
                    try:
                        stop_outcome.append(("return", module["stop"](resolved)))
                    except Exception as error:
                        stop_outcome.append(("error", type(error).__name__, str(error)))

                with contextlib.redirect_stdout(io.StringIO()):
                    public_thread = threading.Thread(
                        target=stop_publicly, name="public-stop"
                    )
                    public_thread.start()
                    public_thread.join(3)
                    if preparation_thread is not None:
                        preparation_thread.join(3)

                self.assertFalse(public_thread.is_alive())
                self.assertIsNotNone(preparation_thread)
                self.assertFalse(preparation_thread.is_alive())
                self.assertEqual([("return", 0)], stop_outcome)
                self.assertEqual([0], preparation_outcome)
                marker = module["marker_path"](resolved)
                self.assertTrue(resolved["mount"].is_dir())
                self.assertTrue(marker.is_file())
                self.assertEqual(
                    str(resolved["mount"]), json.loads(marker.read_text())["mount"]
                )

                launch = mock.Mock(side_effect=SystemExit(0))
                with mock.patch("os.execve", side_effect=launch):
                    with self.assertRaisesRegex(SystemExit, "0"):
                        module["mount_exec"](resolved)
                launch.assert_called_once()

                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(0, module["stop"](resolved))
                    self.assertEqual(0, module["stop"](resolved))
                self.assertFalse(resolved["mount"].exists())
                self.assertFalse(marker.exists())

    def test_preparation_finishes_before_public_cleanup_and_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            mount = root / "data/proton-drive-desktop/files"
            runtime_base = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            mount.mkdir(parents=True, mode=0o700)
            runtime_base.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            module = runpy.run_path(str(PROGRAM), run_name="proton_drive_test_module")
            resolved = {
                "config": config,
                "mount": mount,
                "runtime": runtime_base / "proton-drive-desktop",
            }
            service = "inactive"
            preparation_inside = threading.Event()
            release_preparation = threading.Event()
            preparation_finished = threading.Event()
            preparation_outcome = []
            preparation_thread = None

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    if threading.current_thread().name == "new-service-prepare":
                        preparation_inside.set()
                        if not release_preparation.wait(2):
                            raise AssertionError("preparation was not released")
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            def prepare_again():
                try:
                    preparation_outcome.append(module["service_prepare"](resolved))
                except Exception as error:
                    preparation_outcome.append((type(error).__name__, str(error)))
                finally:
                    preparation_finished.set()

            def external(command, **kwargs):
                nonlocal preparation_thread, service
                if command[2] == "stop":
                    preparation_thread = threading.Thread(
                        target=prepare_again, name="new-service-prepare"
                    )
                    preparation_thread.start()
                    if not preparation_inside.wait(2):
                        raise AssertionError("preparation did not acquire metadata lock")
                    service = "activating"
                    release_preparation.set()
                    if not preparation_finished.wait(2):
                        raise AssertionError("preparation did not finish")
                    return subprocess.CompletedProcess(command, 0)
                sub = "start-pre" if service == "activating" else "dead"
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=(
                        f"ActiveState={service}\nSubState={sub}\n"
                        "Result=success\n"
                    ),
                )

            with mock.patch("builtins.open", side_effect=opened):
                self.assertEqual(0, module["service_prepare"](resolved))
                marker = module["marker_path"](resolved)
                ownership = json.loads(marker.read_text())
                self.assertFalse(ownership["created"])
                ownership["mount_id"] = "777"
                marker.write_text(json.dumps(ownership, separators=(",", ":")))

                stop_outcome = []
                with mock.patch("subprocess.run", side_effect=external), \
                        contextlib.redirect_stdout(io.StringIO()):
                    try:
                        module["stop"](resolved)
                    except Exception as error:
                        stop_outcome.append((type(error).__name__, str(error)))
                preparation_thread.join(2)

                self.assertFalse(preparation_thread.is_alive())
                self.assertEqual([0], preparation_outcome)
                self.assertEqual(
                    [("OperationError", "service stop incomplete: starting")],
                    stop_outcome,
                )
                self.assertTrue(mount.is_dir())
                prepared = json.loads(marker.read_text())
                self.assertFalse(prepared["created"])
                self.assertNotIn("mount_id", prepared)

                launch = mock.Mock(side_effect=SystemExit(0))
                with mock.patch("os.execve", side_effect=launch):
                    with self.assertRaisesRegex(SystemExit, "0"):
                        module["mount_exec"](resolved)
                launch.assert_called_once()

                process = mock.Mock(
                    side_effect=AssertionError("unit post-stop queried systemd")
                )
                service = "deactivating"
                with mock.patch("subprocess.run", side_effect=process):
                    self.assertEqual(0, module["service_post_stop"](resolved))
                    self.assertEqual(0, module["service_post_stop"](resolved))
                process.assert_not_called()
                self.assertTrue(mount.is_dir())
                self.assertFalse(marker.exists())

    def test_stop_rereads_a_concurrent_session_binding_under_the_control_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            runtime_base = root / "run"
            runtime_base.mkdir(mode=0o700)
            module = runpy.run_path(str(PROGRAM), run_name="proton_drive_test_module")

            def resolved_for(config_home, data_home):
                with mock.patch.dict(os.environ, {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(config_home),
                    "XDG_DATA_HOME": str(data_home),
                    "XDG_RUNTIME_DIR": str(runtime_base),
                }, clear=True):
                    return module["paths"]()

            stale = resolved_for(root / "stale config", root / "stale data")
            bound = resolved_for(root / "bound config", root / "bound data")
            mount = bound["mount"]
            mount.mkdir(parents=True, mode=0o700)
            initial_read = threading.Event()
            outcome = []
            original_authoritative = module["authoritative_paths"]

            def coordinated_authoritative(resolved):
                authoritative = original_authoritative(resolved)
                if threading.current_thread().name == "serialized-stop":
                    initial_read.set()
                return authoritative

            module["main"].__globals__["paths"] = lambda: stale
            module["main"].__globals__["authoritative_paths"] = coordinated_authoritative

            def external(command, **kwargs):
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="ActiveState=inactive\nSubState=dead\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            def worker():
                try:
                    outcome.append(module["main"](["stop"]))
                except module["OperationError"] as error:
                    outcome.append(str(error))

            with mock.patch("subprocess.run", side_effect=external), mock.patch(
                "builtins.open", side_effect=opened
            ), contextlib.redirect_stdout(io.StringIO()):
                with module["control_lock"](bound):
                    publish_mount_record(mount, bound["runtime"], "1", True)
                    marker = module["marker_path"](bound)
                    thread = threading.Thread(target=worker, name="serialized-stop")
                    thread.start()
                    self.assertTrue(initial_read.wait(1))
                    module["establish_binding"](bound)
                thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual([0], outcome)
            self.assertFalse(mount.exists())
            self.assertFalse(marker.exists())

    def test_post_stop_preserves_a_replacement_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            data_home = root / "data"
            runtime = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            data_home.mkdir(mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            mount = data_home / "proton-drive-desktop/files"
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(data_home),
                "XDG_RUNTIME_DIR": str(runtime),
            }

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            self.assertEqual(
                0, invoke(["_prepare"], environment, opened=opened)[0]
            )
            mount.rmdir()
            replacement = root / "replacement"
            replacement.mkdir()
            protected = replacement / "keep.txt"
            protected.write_text("keep")
            mount.symlink_to(replacement, target_is_directory=True)

            result = invoke(["_post-stop"], environment, opened=opened)

            self.assertEqual(
                (1, "", "mountpoint was replaced; preserving it\n"), result
            )
            self.assertTrue(mount.is_symlink())
            self.assertEqual("keep", protected.read_text())

    def test_interrupted_created_leaf_is_not_silently_reclassified(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            data_home = root / "data"
            runtime = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            data_home.mkdir(mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            mount = data_home / "proton-drive-desktop/files"
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(data_home),
                "XDG_RUNTIME_DIR": str(runtime),
            }

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            real_mkdir = os.mkdir

            def terminate_after_leaf_creation(path, mode=0o777, *args, **kwargs):
                real_mkdir(path, mode, *args, **kwargs)
                if pathlib.Path(path) == mount:
                    raise SystemExit(91)

            with mock.patch("os.mkdir", side_effect=terminate_after_leaf_creation):
                interrupted = invoke(["_prepare"], environment, opened=opened)

            self.assertEqual(91, interrupted[0])
            self.assertTrue(mount.is_dir())
            diagnostic = (
                "interrupted mountpoint creation requires stopped recovery\n"
            )
            self.assertEqual(
                (1, "", diagnostic),
                invoke(["_prepare"], environment, opened=opened),
            )
            launch = mock.Mock()
            self.assertEqual(
                (1, "", diagnostic),
                invoke(
                    ["_mount"], environment, execve=launch, opened=opened
                ),
            )
            launch.assert_not_called()

            def external(command, **kwargs):
                returncode = 1 if command[2] == "start" else 0
                return subprocess.CompletedProcess(
                    command, returncode,
                    stdout=(
                        "ActiveState=inactive\nSubState=dead\n"
                        "Result=success\n"
                    ),
                )

            for command in ("start", "stop"):
                with self.subTest(command=command):
                    self.assertEqual(
                        (1, "", diagnostic),
                        invoke(
                            [command], environment,
                            run=external, opened=opened,
                        ),
                    )
            self.assertEqual(
                (1, "", diagnostic),
                invoke(["_post-stop"], environment, opened=opened),
            )

            mount.rmdir()
            self.assertEqual(
                (0, "", ""), invoke(["_prepare"], environment, opened=opened)
            )
            marker = runtime / "proton-drive-desktop/mountpoint.json"
            self.assertTrue(json.loads(marker.read_text())["created"])
            self.assertEqual(
                (0, "", ""),
                invoke(["_post-stop"], environment, opened=opened),
            )
            self.assertFalse(mount.exists())

    def test_interrupted_identity_publication_reconciles_before_mounting(self):
        for preexisting in (False, True):
            for boundary in ("nonce", "before-marker", "after-marker"):
                with self.subTest(
                    preexisting=preexisting, boundary=boundary
                ), tempfile.TemporaryDirectory() as temporary:
                    root = pathlib.Path(temporary)
                    config_parent = root / "config/rclone"
                    data_home = root / "data"
                    runtime = root / "run"
                    config_parent.mkdir(parents=True, mode=0o700)
                    data_home.mkdir(mode=0o700)
                    runtime.mkdir(mode=0o700)
                    config = config_parent / "proton-drive.conf"
                    config.write_text("encrypted-placeholder")
                    config.chmod(0o600)
                    mount = data_home / "proton-drive-desktop/files"
                    if preexisting:
                        mount.mkdir(parents=True, mode=0o700)
                    private_runtime = runtime / "proton-drive-desktop"
                    marker = private_runtime / "mountpoint.json"
                    environment = {
                        "HOME": temporary,
                        "XDG_CONFIG_HOME": str(root / "config"),
                        "XDG_DATA_HOME": str(data_home),
                        "XDG_RUNTIME_DIR": str(runtime),
                    }

                    def opened(name, *args, **kwargs):
                        if name == "/proc/self/mountinfo":
                            return io.StringIO("")
                        return io.open(name, *args, **kwargs)

                    if boundary == "nonce":
                        real_setxattr = os.setxattr

                        def terminate(*args, **kwargs):
                            real_setxattr(*args, **kwargs)
                            raise SystemExit(92)

                        interruption = mock.patch(
                            "os.setxattr", side_effect=terminate
                        )
                    else:
                        real_replace = os.replace

                        def terminate(source, destination, *args, **kwargs):
                            if pathlib.Path(destination) == marker:
                                if boundary == "after-marker":
                                    real_replace(
                                        source, destination, *args, **kwargs
                                    )
                                raise SystemExit(92)
                            return real_replace(
                                source, destination, *args, **kwargs
                            )

                        interruption = mock.patch(
                            "os.replace", side_effect=terminate
                        )

                    with interruption:
                        interrupted = invoke(
                            ["_prepare"], environment, opened=opened
                        )

                    self.assertEqual(92, interrupted[0])
                    diagnostic = (
                        "interrupted mountpoint identity publication requires "
                        "stopped recovery\n"
                    )
                    launch = mock.Mock()
                    self.assertEqual(
                        (1, "", diagnostic),
                        invoke(
                            ["_mount"], environment,
                            execve=launch, opened=opened,
                        ),
                    )
                    launch.assert_not_called()

                    def external(command, **kwargs):
                        if command[2] == "start":
                            return subprocess.CompletedProcess(command, 1)
                        return subprocess.CompletedProcess(
                            command, 0,
                            stdout=(
                                "ActiveState=inactive\nSubState=dead\n"
                                "Result=success\n"
                            ),
                        )

                    self.assertEqual(
                        (1, "", diagnostic),
                        invoke(
                            ["start"], environment,
                            run=external, opened=opened,
                        ),
                    )
                    self.assertEqual(
                        (1, "", diagnostic),
                        invoke(
                            ["stop"], environment,
                            run=external, opened=opened,
                        ),
                    )
                    self.assertEqual(
                        (1, "", diagnostic),
                        invoke(["_post-stop"], environment, opened=opened),
                    )

                    self.assertEqual(
                        (0, "", ""),
                        invoke(["_prepare"], environment, opened=opened),
                    )
                    ownership = json.loads(marker.read_text())
                    self.assertEqual(not preexisting, ownership["created"])
                    self.assertEqual(
                        ownership["nonce"].encode("ascii"),
                        os.getxattr(
                            mount, "user.proton-drive-desktop.identity"
                        ),
                    )

                    launched = mock.Mock(side_effect=SystemExit(0))
                    self.assertEqual(
                        (0, "", ""),
                        invoke(
                            ["_mount"], environment,
                            execve=launched, opened=opened,
                        ),
                    )
                    launched.assert_called_once()
                    self.assertEqual(
                        (0, "", ""),
                        invoke(["_post-stop"], environment, opened=opened),
                    )
                    self.assertEqual(preexisting, mount.exists())

    def test_interrupted_preexisting_cleanup_requires_bounded_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            mount.mkdir(parents=True, mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            unknown_name = "user.proton-drive-desktop.keep"
            unknown_value = b"preserve-unknown-identity"
            os.setxattr(mount, unknown_name, unknown_value)
            private_runtime = runtime / "proton-drive-desktop"
            marker = private_runtime / "mountpoint.json"
            phase = private_runtime / "mountpoint-phase.json"
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_RUNTIME_DIR": str(runtime),
            }

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            self.assertEqual(
                (0, "", ""), invoke(["_prepare"], environment, opened=opened)
            )
            real_removexattr = os.removexattr

            def terminate_after_nonce_removal(path, name, *args, **kwargs):
                real_removexattr(path, name, *args, **kwargs)
                if name == "user.proton-drive-desktop.identity":
                    raise SystemExit(93)

            with mock.patch(
                "os.removexattr", side_effect=terminate_after_nonce_removal
            ):
                interrupted = invoke(
                    ["_post-stop"], environment, opened=opened
                )

            self.assertEqual(93, interrupted[0])
            diagnostic = (
                "interrupted preexisting mountpoint cleanup requires stopped "
                "recovery\n"
            )
            launch = mock.Mock()
            for command in ("_prepare", "_mount", "_post-stop"):
                with self.subTest(command=command):
                    self.assertEqual(
                        (1, "", diagnostic),
                        invoke(
                            [command], environment,
                            execve=launch, opened=opened,
                        ),
                    )
            launch.assert_not_called()

            def external(command, **kwargs):
                returncode = 1 if command[2] == "start" else 0
                return subprocess.CompletedProcess(
                    command, returncode,
                    stdout=(
                        "ActiveState=inactive\nSubState=dead\n"
                        "Result=success\n"
                    ),
                )

            for command in ("start", "stop"):
                with self.subTest(command=command):
                    self.assertEqual(
                        (1, "", diagnostic),
                        invoke(
                            [command], environment,
                            run=external, opened=opened,
                        ),
                    )

            self.assertTrue(mount.is_dir())
            self.assertTrue(marker.is_file())
            self.assertTrue(phase.is_file())
            with self.assertRaises(OSError) as missing:
                os.getxattr(mount, "user.proton-drive-desktop.identity")
            self.assertEqual(XATTR_MISSING_ERRNO, missing.exception.errno)
            self.assertEqual(unknown_value, os.getxattr(mount, unknown_name))

            marker.unlink()
            phase.unlink()
            self.assertEqual(
                (0, "", ""), invoke(["_prepare"], environment, opened=opened)
            )
            self.assertFalse(json.loads(marker.read_text())["created"])
            self.assertEqual(unknown_value, os.getxattr(mount, unknown_name))
            self.assertEqual(
                (0, "", ""),
                invoke(["_post-stop"], environment, opened=opened),
            )
            self.assertTrue(mount.is_dir())
            self.assertEqual(unknown_value, os.getxattr(mount, unknown_name))

    def test_interrupted_publication_preserves_an_unknown_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            mount.mkdir(parents=True, mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_RUNTIME_DIR": str(runtime),
            }

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            real_setxattr = os.setxattr

            def terminate_after_nonce_creation(*args, **kwargs):
                real_setxattr(*args, **kwargs)
                raise SystemExit(94)

            with mock.patch(
                "os.setxattr", side_effect=terminate_after_nonce_creation
            ):
                self.assertEqual(
                    94, invoke(["_prepare"], environment, opened=opened)[0]
                )

            unknown_identity = b"ab" * 32
            os.setxattr(
                mount,
                "user.proton-drive-desktop.identity",
                unknown_identity,
            )
            phase = runtime / "proton-drive-desktop/mountpoint-phase.json"
            phase_before = phase.read_bytes()
            diagnostic = (
                "interrupted mountpoint identity publication requires "
                "stopped recovery\n"
            )
            launch = mock.Mock()

            for command in ("_prepare", "_mount", "_post-stop"):
                with self.subTest(command=command):
                    self.assertEqual(
                        (1, "", diagnostic),
                        invoke(
                            [command], environment,
                            execve=launch, opened=opened,
                        ),
                    )

            launch.assert_not_called()
            self.assertTrue(mount.is_dir())
            self.assertEqual(phase_before, phase.read_bytes())
            self.assertEqual(
                unknown_identity,
                os.getxattr(mount, "user.proton-drive-desktop.identity"),
            )

    def test_prepare_preserves_an_empty_replacement_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            data_home = root / "data"
            runtime = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            data_home.mkdir(mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            mount = data_home / "proton-drive-desktop/files"
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(data_home),
                "XDG_RUNTIME_DIR": str(runtime),
            }

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            self.assertEqual(0, invoke(["_prepare"], environment, opened=opened)[0])
            original_marker = (runtime / "proton-drive-desktop/mountpoint.json").read_bytes()
            mount.rmdir()
            mount.mkdir(mode=0o700)

            result = invoke(["_prepare"], environment, opened=opened)

            self.assertEqual(
                (1, "", "mountpoint was replaced; preserving it\n"), result
            )
            self.assertTrue(mount.is_dir())
            self.assertEqual(
                original_marker,
                (runtime / "proton-drive-desktop/mountpoint.json").read_bytes(),
            )

    def test_prepare_rejects_a_replacement_with_colliding_device_and_inode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            data_home = root / "data"
            runtime = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            data_home.mkdir(mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            mount = data_home / "proton-drive-desktop/files"
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(data_home),
                "XDG_RUNTIME_DIR": str(runtime),
            }

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            self.assertEqual(0, invoke(["_prepare"], environment, opened=opened)[0])
            marker = runtime / "proton-drive-desktop/mountpoint.json"
            ownership = json.loads(marker.read_text())
            ownership["nonce"] = "11" * 32
            mount.rmdir()
            mount.mkdir(mode=0o700)
            replacement_nonce = b"22" * 32
            os.setxattr(mount, "user.proton-drive-desktop.identity", replacement_nonce)
            replacement = mount.stat()
            ownership["device"] = replacement.st_dev
            ownership["inode"] = replacement.st_ino
            marker.write_text(json.dumps(ownership, separators=(",", ":")))
            marker_before = marker.read_bytes()

            result = invoke(["_prepare"], environment, opened=opened)

            self.assertEqual(
                (1, "", "mountpoint was replaced; preserving it\n"), result
            )
            self.assertEqual(marker_before, marker.read_bytes())
            self.assertEqual(
                replacement_nonce,
                os.getxattr(mount, "user.proton-drive-desktop.identity"),
            )

    def test_mount_and_cleanup_reject_replacements_with_colliding_stat_identity(self):
        for command in ("_mount", "_post-stop"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                config_parent = root / "config/rclone"
                data_home = root / "data"
                runtime = root / "run"
                config_parent.mkdir(parents=True, mode=0o700)
                data_home.mkdir(mode=0o700)
                runtime.mkdir(mode=0o700)
                config = config_parent / "proton-drive.conf"
                config.write_text("encrypted-placeholder")
                config.chmod(0o600)
                mount = data_home / "proton-drive-desktop/files"
                environment = {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(data_home),
                    "XDG_RUNTIME_DIR": str(runtime),
                }

                def opened(name, *args, **kwargs):
                    if name == "/proc/self/mountinfo":
                        return io.StringIO("")
                    return io.open(name, *args, **kwargs)

                self.assertEqual(
                    0, invoke(["_prepare"], environment, opened=opened)[0]
                )
                marker = runtime / "proton-drive-desktop/mountpoint.json"
                ownership = json.loads(marker.read_text())
                mount.rmdir()
                mount.mkdir(mode=0o700)
                replacement_nonce = b"33" * 32
                os.setxattr(
                    mount,
                    "user.proton-drive-desktop.identity",
                    replacement_nonce,
                )
                replacement = mount.stat()
                ownership["device"] = replacement.st_dev
                ownership["inode"] = replacement.st_ino
                marker.write_text(json.dumps(ownership, separators=(",", ":")))
                marker_before = marker.read_bytes()
                launch = mock.Mock()

                result = invoke(
                    [command], environment, execve=launch, opened=opened
                )

                self.assertEqual(
                    (1, "", "mountpoint was replaced; preserving it\n"), result
                )
                launch.assert_not_called()
                self.assertTrue(mount.is_dir())
                self.assertEqual(marker_before, marker.read_bytes())
                self.assertEqual(
                    replacement_nonce,
                    os.getxattr(mount, "user.proton-drive-desktop.identity"),
                )

    def test_cleanup_removes_created_leaf_or_only_preexisting_leaf_identity(self):
        for preexisting in (False, True):
            with self.subTest(preexisting=preexisting), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                config_parent = root / "config/rclone"
                data_home = root / "data"
                runtime = root / "run"
                config_parent.mkdir(parents=True, mode=0o700)
                data_home.mkdir(mode=0o700)
                runtime.mkdir(mode=0o700)
                config = config_parent / "proton-drive.conf"
                config.write_text("encrypted-placeholder")
                config.chmod(0o600)
                mount = data_home / "proton-drive-desktop/files"
                if preexisting:
                    mount.mkdir(parents=True, mode=0o700)
                environment = {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(data_home),
                    "XDG_RUNTIME_DIR": str(runtime),
                }

                def opened(name, *args, **kwargs):
                    if name == "/proc/self/mountinfo":
                        return io.StringIO("")
                    return io.open(name, *args, **kwargs)

                self.assertEqual(
                    (0, "", ""), invoke(["_prepare"], environment, opened=opened)
                )
                marker = runtime / "proton-drive-desktop/mountpoint.json"
                ownership = json.loads(marker.read_text())
                self.assertEqual(not preexisting, ownership["created"])
                self.assertRegex(ownership["nonce"], r"\A[0-9a-f]{64}\Z")
                self.assertEqual(
                    ownership["nonce"].encode("ascii"),
                    os.getxattr(mount, "user.proton-drive-desktop.identity"),
                )

                self.assertEqual(
                    (0, "", ""),
                    invoke(["_post-stop"], environment, opened=opened),
                )
                self.assertFalse(marker.exists())
                self.assertEqual(preexisting, mount.exists())
                if preexisting:
                    with self.assertRaises(OSError) as missing:
                        os.getxattr(mount, "user.proton-drive-desktop.identity")
                    self.assertEqual(XATTR_MISSING_ERRNO, missing.exception.errno)

    def test_prepare_preserves_replacement_of_a_recorded_preexisting_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            mount.mkdir(parents=True, mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_RUNTIME_DIR": str(runtime),
            }

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            self.assertEqual(0, invoke(["_prepare"], environment, opened=opened)[0])
            marker = runtime / "proton-drive-desktop/mountpoint.json"
            original_marker = marker.read_bytes()
            self.assertFalse(json.loads(original_marker)["created"])
            mount.rmdir()
            mount.mkdir(mode=0o700)

            result = invoke(["_prepare"], environment, opened=opened)

            self.assertEqual(
                (1, "", "mountpoint was replaced; preserving it\n"), result
            )
            self.assertTrue(mount.is_dir())
            self.assertEqual(original_marker, marker.read_bytes())

    def test_prepare_recovers_its_recorded_leaf_when_the_leaf_is_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            data_home = root / "data"
            runtime = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            data_home.mkdir(mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            mount = data_home / "proton-drive-desktop/files"
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(data_home),
                "XDG_RUNTIME_DIR": str(runtime),
            }

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            self.assertEqual(0, invoke(["_prepare"], environment, opened=opened)[0])
            marker = runtime / "proton-drive-desktop/mountpoint.json"
            previous = json.loads(marker.read_text())
            mount.rmdir()

            self.assertEqual(
                (0, "", ""), invoke(["_prepare"], environment, opened=opened)
            )
            recovered = json.loads(marker.read_text())
            self.assertTrue(mount.is_dir())
            self.assertTrue(recovered["created"])
            self.assertNotEqual(
                previous["nonce"], recovered["nonce"]
            )
            self.assertEqual(
                recovered["nonce"].encode("ascii"),
                os.getxattr(mount, "user.proton-drive-desktop.identity"),
            )

    def test_legacy_record_requires_a_stopped_session_transition_for_existing_leaf(self):
        for command in ("_prepare", "_mount", "_post-stop"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                config_parent = root / "config/rclone"
                mount = root / "data/proton-drive-desktop/files"
                runtime = root / "run/proton-drive-desktop"
                config_parent.mkdir(parents=True, mode=0o700)
                mount.mkdir(parents=True, mode=0o700)
                runtime.mkdir(parents=True, mode=0o700)
                config = config_parent / "proton-drive.conf"
                config.write_text("encrypted-placeholder")
                config.chmod(0o600)
                information = mount.stat()
                marker = runtime / "mountpoint.json"
                marker.write_text(json.dumps({
                    "mount": str(mount),
                    "device": information.st_dev,
                    "inode": information.st_ino,
                    "created": True,
                }, separators=(",", ":")))
                marker_before = marker.read_bytes()
                environment = {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                }

                def opened(name, *args, **kwargs):
                    if name == "/proc/self/mountinfo":
                        return io.StringIO("")
                    return io.open(name, *args, **kwargs)

                launch = mock.Mock()
                result = invoke(
                    [command], environment, execve=launch, opened=opened
                )

                self.assertEqual(
                    (1, "", "mountpoint ownership record is invalid\n"), result
                )
                launch.assert_not_called()
                self.assertTrue(mount.is_dir())
                self.assertEqual(marker_before, marker.read_bytes())

    def test_prepare_recovers_a_legacy_record_only_when_the_leaf_is_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            data_home = root / "data"
            managed_parent = data_home / "proton-drive-desktop"
            runtime = root / "run/proton-drive-desktop"
            config_parent.mkdir(parents=True, mode=0o700)
            managed_parent.mkdir(parents=True, mode=0o700)
            runtime.mkdir(parents=True, mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            mount = managed_parent / "files"
            marker = runtime / "mountpoint.json"
            legacy = json.dumps({
                "mount": str(mount),
                "device": 1,
                "inode": 2,
                "created": False,
            }, separators=(",", ":"))
            marker.write_text(legacy)
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(data_home),
                "XDG_RUNTIME_DIR": str(root / "run"),
            }

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            self.assertEqual(
                (0, "", ""), invoke(["_prepare"], environment, opened=opened)
            )
            recovered = json.loads(marker.read_text())
            self.assertTrue(recovered["created"])
            self.assertRegex(recovered["nonce"], r"\A[0-9a-f]{64}\Z")
            self.assertEqual(
                recovered["nonce"].encode("ascii"),
                os.getxattr(mount, "user.proton-drive-desktop.identity"),
            )

    def test_prepare_fails_closed_when_directory_xattrs_cannot_be_created(self):
        for preexisting in (False, True):
            with self.subTest(preexisting=preexisting), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                config_parent = root / "config/rclone"
                data_home = root / "data"
                runtime = root / "run"
                config_parent.mkdir(parents=True, mode=0o700)
                data_home.mkdir(mode=0o700)
                runtime.mkdir(mode=0o700)
                config = config_parent / "proton-drive.conf"
                config.write_text("encrypted-placeholder")
                config.chmod(0o600)
                mount = data_home / "proton-drive-desktop/files"
                if preexisting:
                    mount.mkdir(parents=True, mode=0o700)
                environment = {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(data_home),
                    "XDG_RUNTIME_DIR": str(runtime),
                }

                def opened(name, *args, **kwargs):
                    if name == "/proc/self/mountinfo":
                        return io.StringIO("")
                    return io.open(name, *args, **kwargs)

                unavailable = OSError(errno.EOPNOTSUPP, "synthetic unsupported xattr")
                with mock.patch("os.setxattr", side_effect=unavailable):
                    result = invoke(["_prepare"], environment, opened=opened)

                self.assertEqual(
                    (1, "", "mountpoint identity is unavailable\n"), result
                )
                self.assertEqual(preexisting, mount.exists())
                self.assertFalse(
                    (runtime / "proton-drive-desktop/mountpoint.json").exists()
                )

    def test_xattr_read_failures_preserve_state_and_never_reach_exec(self):
        for command in ("_prepare", "_mount", "_post-stop"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                config_parent = root / "config/rclone"
                data_home = root / "data"
                runtime = root / "run"
                config_parent.mkdir(parents=True, mode=0o700)
                data_home.mkdir(mode=0o700)
                runtime.mkdir(mode=0o700)
                config = config_parent / "proton-drive.conf"
                config.write_text("encrypted-placeholder")
                config.chmod(0o600)
                mount = data_home / "proton-drive-desktop/files"
                environment = {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(data_home),
                    "XDG_RUNTIME_DIR": str(runtime),
                }

                def opened(name, *args, **kwargs):
                    if name == "/proc/self/mountinfo":
                        return io.StringIO("")
                    return io.open(name, *args, **kwargs)

                self.assertEqual(
                    0, invoke(["_prepare"], environment, opened=opened)[0]
                )
                marker = runtime / "proton-drive-desktop/mountpoint.json"
                marker_before = marker.read_bytes()
                launch = mock.Mock()
                unavailable = OSError(errno.EOPNOTSUPP, "synthetic unsupported xattr")
                with mock.patch("os.getxattr", side_effect=unavailable):
                    result = invoke(
                        [command], environment, execve=launch, opened=opened
                    )

                self.assertEqual(
                    (1, "", "mountpoint identity is unavailable\n"), result
                )
                launch.assert_not_called()
                self.assertTrue(mount.is_dir())
                self.assertEqual(marker_before, marker.read_bytes())

    def test_preexisting_leaf_cleanup_preserves_state_when_xattr_removal_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            mount.mkdir(parents=True, mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_RUNTIME_DIR": str(runtime),
            }

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            self.assertEqual(
                (0, "", ""), invoke(["_prepare"], environment, opened=opened)
            )
            marker = runtime / "proton-drive-desktop/mountpoint.json"
            marker_before = marker.read_bytes()
            nonce_before = os.getxattr(
                mount, "user.proton-drive-desktop.identity"
            )
            unavailable = OSError(errno.EOPNOTSUPP, "synthetic unsupported xattr")

            with mock.patch("os.removexattr", side_effect=unavailable):
                result = invoke(["_post-stop"], environment, opened=opened)

            self.assertEqual(
                (1, "", "mountpoint identity is unavailable\n"), result
            )
            self.assertTrue(mount.is_dir())
            self.assertEqual(marker_before, marker.read_bytes())
            self.assertEqual(
                nonce_before,
                os.getxattr(mount, "user.proton-drive-desktop.identity"),
            )

    def test_wrong_shaped_ownership_records_use_fixed_errors_and_preserve_mountpoint(self):
        for record in ("{broken", "[]", '"scalar"'):
            for command, mounted, wanted_error in (
                ("_prepare", False, "mountpoint ownership record is invalid\n"),
                ("_post-stop", False, "mountpoint ownership record is invalid\n"),
                ("stop", True, "mount is not owned by this session\n"),
            ):
                with self.subTest(record=record, command=command), tempfile.TemporaryDirectory() as temporary:
                    root = pathlib.Path(temporary)
                    config_parent = root / "config/rclone"
                    mount = root / "data/proton-drive-desktop/files"
                    runtime = root / "run/proton-drive-desktop"
                    config_parent.mkdir(parents=True, mode=0o700)
                    mount.mkdir(parents=True, mode=0o700)
                    runtime.mkdir(parents=True, mode=0o700)
                    config = config_parent / "proton-drive.conf"
                    config.write_text("encrypted-placeholder")
                    config.chmod(0o600)
                    marker = runtime / "mountpoint.json"
                    marker.write_text(record)
                    encoded_mount = str(mount).replace(" ", "\\040")

                    def external(arguments, **kwargs):
                        return subprocess.CompletedProcess(
                            arguments, 0,
                            stdout="ActiveState=active\nSubState=running\nResult=success\n",
                        )

                    def opened(name, *args, **kwargs):
                        if name == "/proc/self/mountinfo":
                            entry = (
                                f"121 30 0:121 / {encoded_mount} ro,nosuid,nodev - "
                                "fuse.rclone proton-dolphin: ro\n"
                            )
                            return io.StringIO(entry if mounted else "")
                        return io.open(name, *args, **kwargs)

                    result = invoke(
                        [command],
                        {
                            "HOME": temporary,
                            "XDG_CONFIG_HOME": str(root / "config"),
                            "XDG_DATA_HOME": str(root / "data"),
                            "XDG_RUNTIME_DIR": str(root / "run"),
                        },
                        run=external,
                        opened=opened,
                    )
                    self.assertEqual((1, "", wanted_error), result)
                    self.assertTrue(mount.is_dir())
                    self.assertEqual(record, marker.read_text())

    def test_verify_records_mount_instance_and_stop_rejects_a_different_instance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            config_parent.mkdir(parents=True, mode=0o700)
            (root / "data").mkdir(mode=0o700)
            (root / "run").mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_RUNTIME_DIR": str(root / "run"),
            }
            encoded_mount = str(mount).replace(" ", "\\040")
            mount_id = "131"
            mounted = False

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    entry = (
                        f"{mount_id} 30 0:131 / {encoded_mount} ro,nosuid,nodev - "
                        "fuse.rclone proton-dolphin: ro\n"
                    )
                    return io.StringIO(entry if mounted else "")
                return io.open(name, *args, **kwargs)

            self.assertEqual(0, invoke(["_prepare"], environment, opened=opened)[0])
            mounted = True
            self.assertEqual(0, invoke(["_verify-mount"], environment, opened=opened)[0])
            marker = runtime / "mountpoint.json"
            ownership = json.loads(marker.read_text())
            self.assertEqual("131", ownership["mount_id"])
            underlying_identity = (ownership["device"], ownership["inode"])

            mount_id = "132"
            calls = []

            def external(arguments, **kwargs):
                calls.append(arguments)
                return subprocess.CompletedProcess(
                    arguments, 0,
                    stdout="ActiveState=active\nSubState=running\nResult=success\n",
                )

            result = invoke(
                ["stop"], environment, run=external, opened=opened
            )

            self.assertEqual(
                (1, "", "mounted instance changed; preserving it\n"), result
            )
            self.assertFalse(any(call[0] == "/usr/bin/fusermount3" for call in calls))
            preserved = json.loads(marker.read_text())
            self.assertEqual(underlying_identity, (preserved["device"], preserved["inode"]))
            self.assertEqual("131", preserved["mount_id"])

    def test_stop_observes_detach_independently_of_unmount_helper_exit(self):
        for helper_exit in (0, 1):
            for after, wanted_code, wanted_error, stops in (
                ("absent", 0, "", 1),
                ("same", 1, "mount is busy; close open files and try again\n", 0),
                ("different", 1, "mounted instance changed; preserving it\n", 0),
                ("foreign", 1, "mount changed; preserving it\n", 0),
            ):
                with self.subTest(helper_exit=helper_exit, after=after), tempfile.TemporaryDirectory() as temporary:
                    root = pathlib.Path(temporary)
                    mount = root / "data/proton-drive-desktop/files"
                    runtime = root / "run/proton-drive-desktop"
                    mount.mkdir(parents=True, mode=0o700)
                    runtime.mkdir(parents=True, mode=0o700)
                    publish_mount_record(mount, runtime, "141", True)
                    encoded_mount = str(mount).replace(" ", "\\040")
                    service = True
                    detached = False
                    events = []

                    def external(arguments, **kwargs):
                        nonlocal service, detached
                        if arguments[0] == "/usr/bin/fusermount3":
                            events.append("unmount")
                            detached = True
                            return subprocess.CompletedProcess(arguments, helper_exit)
                        if arguments[2] == "stop":
                            events.append("stop")
                            service = False
                            return subprocess.CompletedProcess(arguments, 0)
                        events.append("show")
                        state = "active" if service else "inactive"
                        sub = "running" if service else "dead"
                        return subprocess.CompletedProcess(
                            arguments, 0,
                            stdout=f"ActiveState={state}\nSubState={sub}\nResult=success\n",
                        )

                    def opened(name, *args, **kwargs):
                        if name == "/proc/self/mountinfo":
                            if not detached:
                                mountinfo = (
                                    f"141 30 0:141 / {encoded_mount} ro,nosuid,nodev - "
                                    "fuse.rclone proton-dolphin: ro\n"
                                )
                            elif after == "absent":
                                mountinfo = ""
                            elif after == "same":
                                mountinfo = (
                                    f"141 30 0:141 / {encoded_mount} ro,nosuid,nodev - "
                                    "fuse.rclone proton-dolphin: ro\n"
                                )
                            elif after == "different":
                                mountinfo = (
                                    f"142 30 0:142 / {encoded_mount} ro,nosuid,nodev - "
                                    "fuse.rclone proton-dolphin: ro\n"
                                )
                            else:
                                mountinfo = (
                                    f"143 30 0:143 / {encoded_mount} rw,nosuid,nodev - "
                                    "fuse.other foreign: rw\n"
                                )
                            return io.StringIO(mountinfo)
                        return io.open(name, *args, **kwargs)

                    result = invoke(
                        ["stop"],
                        {
                            "HOME": temporary,
                            "XDG_CONFIG_HOME": str(root / "config"),
                            "XDG_DATA_HOME": str(root / "data"),
                            "XDG_RUNTIME_DIR": str(root / "run"),
                        },
                        run=external,
                        opened=opened,
                    )
                    self.assertEqual(wanted_code, result[0])
                    self.assertEqual(wanted_error, result[2])
                    self.assertEqual(stops, events.count("stop"))

    def test_explicit_start_and_stop_recover_a_failed_unmounted_unit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            data_home = root / "data"
            runtime = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            data_home.mkdir(mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            mount = data_home / "proton-drive-desktop/files"
            encoded_mount = str(mount).replace(" ", "\\040")
            service = "failed"
            mounted = False
            events = []

            def external(arguments, **kwargs):
                nonlocal service, mounted
                action = arguments[2]
                if action == "start":
                    events.append("explicit-start")
                    publish_mount_record(
                        mount, runtime / "proton-drive-desktop", "151", True
                    )
                    service = "active"
                    mounted = True
                    return subprocess.CompletedProcess(arguments, 0)
                if action == "stop":
                    events.append("explicit-stop")
                    service = "inactive"
                    return subprocess.CompletedProcess(arguments, 0)
                events.append(f"show-{service}")
                sub = {"failed": "failed", "active": "running", "inactive": "dead"}[service]
                return subprocess.CompletedProcess(
                    arguments, 0,
                    stdout=f"ActiveState={service}\nSubState={sub}\nResult=exit-code\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    entry = (
                        f"151 30 0:151 / {encoded_mount} ro,nosuid,nodev - "
                        "fuse.rclone proton-dolphin: ro\n"
                    )
                    return io.StringIO(entry if mounted else "")
                return io.open(name, *args, **kwargs)

            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(data_home),
                "XDG_RUNTIME_DIR": str(runtime),
            }
            self.assertEqual(
                (0, "ready\n", ""),
                invoke(["start"], environment, run=external, opened=opened),
            )
            self.assertIn("explicit-start", events)

            mounted = False
            service = "failed"
            self.assertEqual(
                (0, "stopped\n", ""),
                invoke(["stop"], environment, run=external, opened=opened),
            )
            self.assertIn("explicit-stop", events)
            self.assertFalse(mount.exists())

    def test_service_consumes_the_session_binding_created_by_public_start(self):
        with tempfile.TemporaryDirectory(prefix="proton binding ") as temporary:
            root = pathlib.Path(temporary)
            caller_config = root / "caller config/rclone"
            caller_data = root / "caller data"
            runtime = root / "run"
            caller_config.mkdir(parents=True, mode=0o700)
            caller_data.mkdir(mode=0o700)
            runtime.mkdir(mode=0o700)
            config = caller_config / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            caller_mount = caller_data / "proton-drive-desktop/files"
            manager_data = root / "manager data"
            manager_data.mkdir(mode=0o700)
            canary = "UNRELATED-MANAGER-VALUE-5ec8"

            def failed_start(arguments, **kwargs):
                if arguments[2] == "start":
                    return subprocess.CompletedProcess(arguments, 1)
                return subprocess.CompletedProcess(
                    arguments, 0,
                    stdout="ActiveState=inactive\nSubState=dead\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            caller_environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "caller config"),
                "XDG_DATA_HOME": str(caller_data),
                "XDG_RUNTIME_DIR": str(runtime),
            }
            self.assertEqual(
                (1, "", "service startup failed\n"),
                invoke(["start"], caller_environment, run=failed_start, opened=opened),
            )

            binding = runtime / "proton-drive-desktop/binding.json"
            self.assertTrue(binding.is_file())
            binding_text = binding.read_text()
            self.assertNotIn(canary, binding_text)
            self.assertEqual(
                {
                    "config": str(config),
                    "mount": str(caller_mount),
                },
                json.loads(binding_text),
            )

            manager_environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "manager config"),
                "XDG_DATA_HOME": str(manager_data),
                "XDG_RUNTIME_DIR": str(runtime),
                "UNRELATED_MANAGER_VALUE": canary,
            }
            self.assertEqual(
                (0, "", ""),
                invoke(["_prepare"], manager_environment, opened=opened),
            )
            self.assertTrue(caller_mount.is_dir())
            self.assertFalse((manager_data / "proton-drive-desktop/files").exists())


if __name__ == "__main__":
    unittest.main()
