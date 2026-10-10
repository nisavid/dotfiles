import contextlib
import ctypes
import errno
import hashlib
import io
import json
import os
import pathlib
import re
import resource
import runpy
import shlex
import shutil
import signal
import socket
import stat
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
TEST_MOUNT_TAG = "proton-drive-desktop-" + "ab" * 32
REAL_FSTAT = os.fstat
REAL_POPEN = subprocess.Popen
RCLONE_VERSION_COMMAND = ["/usr/bin/rclone", "version"]
RCLONE_VERSION_OUTPUT = b"rclone v1.75.2\n- os/version: synthetic\n"
INTERRUPTED_CLEANUP_DIAGNOSTIC = (
    "interrupted retained mountpoint cleanup requires stopped recovery"
)
PRIVATE_BUS_SANDBOX_MESSAGES = {
    "Failed to turn off SO_PASSRIGHTS on user lookup socket, ignoring: "
    "Operation not permitted",
    "Failed to enable SO_PASSCRED on handoff timestamp socket: "
    "Operation not permitted",
}
PRIVATE_BUS_FD_LIMIT_WARNING = re.compile(
    r"dbus-daemon\[[1-9][0-9]*\]: Failed to set fd limit to 65536: "
    r"Operation not permitted"
)


def private_bus_diagnostics(output):
    return [
        line for line in output.splitlines()
        if line not in PRIVATE_BUS_SANDBOX_MESSAGES
        and PRIVATE_BUS_FD_LIMIT_WARNING.fullmatch(line) is None
    ]


def with_mode(information, mode):
    values = list(information)
    values[0] = stat.S_IFMT(information.st_mode) | mode
    return os.stat_result(values)


def with_uid(information, uid):
    values = list(information)
    values[4] = uid
    return os.stat_result(values)


class DescriptorCapture(io.StringIO):
    def __init__(self, descriptor):
        super().__init__()
        self.descriptor = descriptor

    def fileno(self):
        return self.descriptor


class SyntheticVersionProcess:
    def __init__(self, completed):
        read_descriptor, write_descriptor = os.pipe()
        try:
            os.write(write_descriptor, completed.stdout[:4097])
        finally:
            os.close(write_descriptor)
        self.stdout = os.fdopen(read_descriptor, "rb", buffering=0)
        self.returncode = completed.returncode
        self.pid = os.getpid()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


def synthetic_version_popen(command, *args, **kwargs):
    if command != RCLONE_VERSION_COMMAND:
        raise AssertionError(f"unexpected synthetic process command: {command!r}")
    return SyntheticVersionProcess(subprocess.CompletedProcess(
        command, 0, stdout=RCLONE_VERSION_OUTPUT
    ))


def invoke(
    arguments, environment, run=None, popen=None, execve=None, opened=None,
    program=PROGRAM, stdout_descriptor=None, rclone_version=None,
):
    stdout = (
        io.StringIO()
        if stdout_descriptor is None
        else DescriptorCapture(stdout_descriptor)
    )
    stderr = io.StringIO()
    version_outcome = rclone_version
    if version_outcome is None:
        version_outcome = subprocess.CompletedProcess(
            RCLONE_VERSION_COMMAND, 0, stdout=RCLONE_VERSION_OUTPUT
        )

    def popen_dispatch(command, *args, **kwargs):
        if command == RCLONE_VERSION_COMMAND:
            outcome = (
                version_outcome(command, *args, **kwargs)
                if callable(version_outcome)
                else version_outcome
            )
            if isinstance(outcome, BaseException):
                raise outcome
            if isinstance(outcome, subprocess.CompletedProcess):
                return SyntheticVersionProcess(outcome)
            return outcome
        if popen is None:
            return mock.DEFAULT
        return popen(command, *args, **kwargs)

    patches = [
        mock.patch.dict(os.environ, environment, clear=True),
        mock.patch.object(sys, "argv", [str(program), *arguments]),
        mock.patch("subprocess.run", side_effect=run),
        mock.patch("subprocess.Popen", side_effect=popen_dispatch),
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
        "mount_tag": TEST_MOUNT_TAG,
        "mount_id": mount_id,
    }, separators=(",", ":")))
    marker.chmod(0o600)


def invoke_credential(
    environment, launch_tag=TEST_MOUNT_TAG, **kwargs
):
    read_descriptor, write_descriptor = os.pipe()
    pipe_output = bytearray()
    collector_errors = []

    def collect():
        try:
            while True:
                chunk = os.read(read_descriptor, 8192)
                if not chunk:
                    break
                pipe_output.extend(chunk)
        except BaseException as error:
            collector_errors.append(error)
        finally:
            try:
                os.close(read_descriptor)
            except OSError as error:
                collector_errors.append(error)

    collector = threading.Thread(target=collect, name="credential-output-collector")
    collector_started = False
    invocation_error = None
    try:
        collector.start()
        collector_started = True
        try:
            result = invoke(
                ["_credential", launch_tag],
                environment,
                stdout_descriptor=write_descriptor,
                **kwargs,
            )
        except BaseException as error:
            invocation_error = error
    finally:
        try:
            os.close(write_descriptor)
        finally:
            if collector_started:
                collector.join()
            else:
                os.close(read_descriptor)
    if invocation_error is not None:
        if collector_errors:
            raise invocation_error from collector_errors[0]
        raise invocation_error
    if collector_errors:
        raise collector_errors[0]
    code, redirected_output, error = result
    if pipe_output and redirected_output:
        raise AssertionError("credential output used two stdout paths")
    output = bytes(pipe_output) or redirected_output.encode("utf-8")
    return code, output.decode("utf-8"), error


@contextlib.contextmanager
def synthetic_credential_subprocess(secret):
    with tempfile.TemporaryDirectory(
        prefix="proton-credential-subprocess-",
        dir=pathlib.Path.home(),
    ) as temporary:
        root = pathlib.Path(temporary)
        config_parent = root / "config/rclone"
        mount = root / "data/proton-drive-desktop/files"
        runtime = root / "run/proton-drive-desktop"
        config_parent.mkdir(parents=True, mode=0o700)
        config = config_parent / "proton-drive.conf"
        config.write_text("encrypted-placeholder")
        config.chmod(0o600)
        publish_mount_record(mount, runtime, "720", False)

        busctl = root / "busctl"
        busctl.write_text(
            "#!/usr/bin/python3\n"
            "print('{\"type\":\"s\",\"data\":[\":1.27\"]}')\n"
        )
        busctl.chmod(0o700)
        secret_tool = root / "secret-tool"
        secret_hex = (secret + bytes([10])).hex()
        secret_tool.write_text(
            "#!/usr/bin/python3\n"
            "import os\n"
            f"os.write(1, bytes.fromhex({secret_hex!r}))\n"
        )
        secret_tool.chmod(0o700)

        helper_source = PROGRAM.read_bytes()
        for original, replacement in (
            (b"/usr/bin/busctl", os.fsencode(busctl)),
            (b"/usr/bin/secret-tool", os.fsencode(secret_tool)),
        ):
            if helper_source.count(original) != 1:
                raise AssertionError(
                    f"synthetic command seam is not unique: {original!r}"
                )
            helper_source = helper_source.replace(original, replacement)
        helper = root / "proton-drive-desktop"
        helper.write_bytes(helper_source)
        helper.chmod(0o700)
        environment = {
            "HOME": str(root),
            "LANG": "C.UTF-8",
            "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_RUNTIME_DIR": str(root / "run"),
        }
        yield helper, environment


class SyntheticDirectoryXattrs:
    """Model the Linux-only product's external xattr boundary on macOS."""

    def __init__(self):
        self.values = {}
        self.descriptors = {}

    @staticmethod
    def key(path, name):
        information = os.lstat(path)
        return (
            information.st_dev,
            information.st_ino,
            name,
        )

    def get(self, path, name, *args, **kwargs):
        try:
            return self.values[self.key(path, name)]
        except KeyError:
            raise OSError(XATTR_MISSING_ERRNO, "synthetic xattr is absent") from None

    def set(self, path, name, value, *args, **kwargs):
        key = self.key(path, name)
        identity = key[:2]
        if identity not in self.descriptors:
            flags = os.O_RDONLY
            flags |= getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_DIRECTORY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            information = os.fstat(descriptor)
            if (information.st_dev, information.st_ino) != identity:
                os.close(descriptor)
                raise OSError(errno.ESTALE, "synthetic xattr target changed")
            self.descriptors[identity] = descriptor
        self.values[key] = value

    def remove(self, path, name, *args, **kwargs):
        try:
            del self.values[self.key(path, name)]
        except KeyError:
            raise OSError(XATTR_MISSING_ERRNO, "synthetic xattr is absent") from None

    def close(self):
        for descriptor in self.descriptors.values():
            os.close(descriptor)
        self.descriptors.clear()


def retained_publication_snapshot(mount, marker, phase):
    def xattrs(path):
        return tuple(
            (name, os.getxattr(path, name, follow_symlinks=False))
            for name in sorted(os.listxattr(path, follow_symlinks=False))
        )

    def tree(path):
        information = path.lstat()
        common = (
            information.st_dev,
            information.st_ino,
            information.st_uid,
            stat.S_IMODE(information.st_mode),
            xattrs(path),
        )
        if stat.S_ISDIR(information.st_mode):
            return (
                "directory",
                common,
                tuple((child.name, tree(child)) for child in sorted(path.iterdir())),
            )
        if stat.S_ISREG(information.st_mode):
            return "file", common, path.read_bytes()
        return "other", common, os.readlink(path) if path.is_symlink() else None

    def record(path):
        return tree(path) if path.exists() else None

    return record(marker), record(phase), tree(mount)


@contextlib.contextmanager
def interrupted_publication_fixture():
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

        with mock.patch("os.setxattr", side_effect=SystemExit(96)):
            interrupted = invoke(["_prepare"], environment, opened=opened)
        if interrupted[0] != 96:
            raise AssertionError(f"publication was not interrupted: {interrupted!r}")

        private_runtime = runtime / "proton-drive-desktop"
        marker = private_runtime / "mountpoint.json"
        phase = private_runtime / "mountpoint-phase.json"
        if marker.exists() or not phase.is_file():
            raise AssertionError("fixture did not retain only the publication phase")
        yield mount, marker, phase, environment, opened


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
        self.assertIn("TimeoutStartSec=45s", unit)
        self.assertIn("WantedBy=plasma-workspace.target", unit)

        forbidden = (
            "PrivateTmp=", "PrivateMounts=", "PrivateDevices=", "ProtectHome=",
            "NoNewPrivileges=", "ExecStartPre=/usr/bin/secret-tool",
            "Before=", "Wants=graphical-session.target", "Wants=plasma-workspace.target",
        )
        for directive in forbidden:
            self.assertNotIn(directive, unit)

    @unittest.skipUnless(sys.platform == "linux", "Linux pathname validation")
    def test_production_ancestor_check_does_not_exempt_sticky_tmp(self):
        self.assertTrue(pathlib.Path("/tmp").stat().st_mode & 0o022)
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
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

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["_prepare"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(data_home),
                    "XDG_RUNTIME_DIR": str(runtime),
                },
                opened=opened,
            )

            self.assertEqual(
                (1, "", "unsafe rclone config ancestor\n"), result
            )
            self.assertFalse((data_home / "proton-drive-desktop").exists())

    @unittest.skipUnless(sys.platform == "linux", "Linux systemd lifecycle")
    def test_systemd_accepts_disposable_user_lifecycle_fixture(self):
        analyzer = shutil.which("systemd-analyze")
        self.assertIsNotNone(analyzer, "systemd-analyze is required on Linux")
        bus_runner = shutil.which("dbus-run-session")
        self.assertIsNotNone(bus_runner, "dbus-run-session is required on Linux")
        source_unit = (
            ROOT / "home/dot_config/systemd/user/proton-drive-desktop.service"
        ).read_text()

        def verify(unit_text):
            with tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                unit_dir = root / "config/systemd/user"
                runtime = root / "run"
                unit_dir.mkdir(parents=True)
                runtime.mkdir()
                unit_text = re.sub(
                    r"%h/\.local/bin/proton-drive-desktop _[a-z-]+",
                    "/usr/bin/true",
                    unit_text,
                )
                (unit_dir / "proton-drive-desktop.service").write_text(unit_text)
                (unit_dir / "plasma-workspace.target").write_text(textwrap.dedent("""\
                    [Unit]
                    Description=Synthetic Plasma lifecycle target
                """))
                (unit_dir / "graphical-session.target").write_text(textwrap.dedent("""\
                    [Unit]
                    Description=Synthetic graphical session target
                """))
                (unit_dir / "plasma-kwallet-pam.service").write_text(textwrap.dedent("""\
                    [Service]
                    Type=oneshot
                    ExecStart=/usr/bin/true
                """))
                wants = unit_dir / "plasma-workspace.target.wants"
                wants.mkdir()
                (wants / "proton-drive-desktop.service").symlink_to(
                    unit_dir / "proton-drive-desktop.service"
                )
                def constrain_open_files():
                    _, hard_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
                    low_limit = (
                        1024
                        if hard_limit == resource.RLIM_INFINITY
                        else min(hard_limit, 1024)
                    )
                    resource.setrlimit(
                        resource.RLIMIT_NOFILE, (low_limit, low_limit)
                    )

                return subprocess.run(
                    [
                        bus_runner, "--", "/bin/sh", "-c",
                        'DBUS_SYSTEM_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" exec "$@"',
                        "verify-user-unit",
                        analyzer, "--user", "--generators=no", "verify",
                        str(unit_dir / "proton-drive-desktop.service"),
                        str(unit_dir / "plasma-workspace.target"),
                    ],
                    cwd=root,
                    env={
                        "HOME": str(root / "home"),
                        "PATH": os.environ["PATH"],
                        "LANG": "C.UTF-8",
                        "XDG_CONFIG_HOME": str(root / "config"),
                        "XDG_RUNTIME_DIR": str(runtime),
                    },
                    text=True,
                    capture_output=True,
                    preexec_fn=constrain_open_files,
                )

        clean = verify(source_unit)
        clean_diagnostics = private_bus_diagnostics(clean.stdout + clean.stderr)
        self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)
        self.assertEqual([], clean_diagnostics)

    def test_private_bus_diagnostic_filter_is_exact(self):
        warning = (
            "dbus-daemon[4172]: Failed to set fd limit to 65536: "
            "Operation not permitted"
        )
        self.assertEqual([], private_bus_diagnostics(warning))

        for diagnostic in (
            "dbus-daemon: Failed to set fd limit to 65536: Operation not permitted",
            "dbus-daemon[0]: Failed to set fd limit to 65536: Operation not permitted",
            "dbus-daemon[4172]: Failed to set fd limit to 65535: Operation not permitted",
            "dbus-daemon[4172]: Failed to set fd limit to 65536: Permission denied",
            warning + ": verifier failed",
            "proton-drive-desktop.service: Failed to verify unit",
        ):
            with self.subTest(diagnostic=diagnostic):
                self.assertEqual(
                    [diagnostic], private_bus_diagnostics(diagnostic)
                )

    def test_lifecycle_dependency_contract_detects_removed_target_ordering(self):
        source_unit = (
            ROOT / "home/dot_config/systemd/user/proton-drive-desktop.service"
        ).read_text()
        targets = {"plasma-workspace.target", "graphical-session.target"}

        def dependencies(unit_text):
            section = None
            result = {}
            for raw_line in unit_text.splitlines():
                line = raw_line.strip()
                if line.startswith("[") and line.endswith("]"):
                    section = line[1:-1]
                elif section == "Unit" and "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    result.setdefault(key, set()).update(value.split())
            return result

        def satisfies_lifecycle_contract(unit_text):
            relationships = dependencies(unit_text)
            return all(
                targets.issubset(relationships.get(key, set()))
                for key in ("Requisite", "After", "PartOf")
            )

        self.assertTrue(satisfies_lifecycle_contract(source_unit))
        mutated = source_unit.replace(
            "After=plasma-workspace.target graphical-session.target\n", "", 1
        )
        self.assertFalse(satisfies_lifecycle_contract(mutated))

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
            "test -r \"${XDG_DATA_HOME:-$HOME/.local/share}/applications/proton-drive.desktop\"",
            "keep automatic startup disabled and report the gap",
            "start automatically before any `proton-drive-desktop start` or `open`",
            "including paths with spaces",
            "Qualify the effective loaded unit",
            "--property=FragmentPath --value",
            "--property=DropInPaths --value",
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
            "retains that empty underlying directory", normalized_guide
        )
        self.assertIn("supported ordinary-user pathname", normalized_guide)
        self.assertIn(
            "final descriptor-backed inspection in `_mount`", normalized_guide
        )
        self.assertIn(
            "throughout startup, the mounted session, and completed shutdown",
            normalized_guide,
        )
        self.assertIn(
            "must not rename or replace either directory, mount over the managed path, or independently unmount it during that interval",
            normalized_guide,
        )
        self.assertIn(
            "This contract also applies at logout and direct service shutdown",
            normalized_guide,
        )
        self.assertIn(
            "do not enforce this reservation or prove unconditional pathname identity",
            normalized_guide,
        )
        self.assertNotIn("`/proc/<rclone-pid>/fd/<descriptor>`", normalized_guide)
        self.assertIn("`cleanup-retained`", normalized_guide)
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
            "interrupted retained mountpoint cleanup requires stopped recovery",
            normalized_guide,
        )
        self.assertIn("mountpoint-phase.json", normalized_guide)
        self.assertIn("Do not copy or guess the recorded nonce", normalized_guide)
        self.assertIn(
            "A `prepare-create` intention does not identify an existing leaf",
            normalized_guide,
        )
        self.assertIn(
            "compares the current device and inode with the phase before recovery",
            normalized_guide,
        )
        self.assertIn(
            "retry `proton-drive-desktop start`", normalized_guide
        )
        self.assertIn(
            "retry `proton-drive-desktop stop`", normalized_guide
        )
        self.assertNotIn('rmdir -- "$mountpoint"', normalized_guide)
        self.assertNotIn('rm -- "$marker" "$phase"', normalized_guide)
        self.assertIn(
            "source cannot infer that the unmarked directory was helper-created",
            normalized_guide,
        )
        self.assertIn("`/usr/bin/secret-tool`", normalized_guide)
        self.assertIn("test -x /usr/bin/secret-tool", normalized_guide)
        self.assertIn("There is no sticky-directory exception", normalized_guide)
        self.assertIn(
            "do not close an owner-change-and-return race between samples",
            normalized_guide,
        )
        self.assertIn(
            "current launch's nonsecret source tag", normalized_guide
        )
        self.assertIn(
            "standard output is a pipe before any Secret Service lookup",
            normalized_guide,
        )
        self.assertIn(
            "4,096-byte key plus its permitted line ending and one overflow byte",
            normalized_guide,
        )
        self.assertIn(
            "stable active service with an absent target mount",
            normalized_guide,
        )
        self.assertIn(
            "`start` and `open` still reject that state", normalized_guide
        )
        self.assertIn(
            "hostile same-UID forgery or power-loss durability",
            normalized_guide,
        )
        self.assertIn("--property=FragmentPath --value", normalized_guide)
        self.assertIn("--property=DropInPaths --value", normalized_guide)


@unittest.skipUnless(sys.platform == "linux", "Linux runtime behavior")
class PublicCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        required = (pathlib.Path("/usr/bin/python3"), pathlib.Path("/usr/bin/rclone"))
        missing = [
            str(path) for path in required
            if not path.is_file() or not os.access(path, os.X_OK)
        ]
        if missing:
            raise RuntimeError(
                "Linux runtime tests require executable " + ", ".join(missing)
            )

    def setUp(self):
        def synthetic_ancestor_fstat(descriptor):
            information = REAL_FSTAT(descriptor)
            try:
                path = pathlib.Path(os.readlink(f"/proc/self/fd/{descriptor}"))
            except OSError:
                return information
            if path == pathlib.Path(tempfile.gettempdir()).resolve():
                # Synthetic fixtures explicitly model a safe temporary root.
                # Production observes the real mode and has no /tmp exception.
                return with_mode(information, 0o755)
            return information

        self.enterContext(mock.patch("os.fstat", side_effect=synthetic_ancestor_fstat))
        if sys.platform == "darwin":
            xattrs = SyntheticDirectoryXattrs()
            self.addCleanup(xattrs.close)
            self.enterContext(mock.patch(
                "os.getxattr", side_effect=xattrs.get, create=True
            ))
            self.enterContext(mock.patch(
                "os.setxattr", side_effect=xattrs.set, create=True
            ))
            self.enterContext(mock.patch(
                "os.removexattr", side_effect=xattrs.remove, create=True
            ))

    @contextlib.contextmanager
    def retained_recovery_fixture(
        self, phase_name, marker_kind="absent", mode=0o700,
        identity="matching",
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            data_home = root / "data"
            runtime_base = root / "run"
            runtime = runtime_base / "proton-drive-desktop"
            config_parent.mkdir(parents=True, mode=0o700)
            data_home.mkdir(mode=0o700)
            runtime.mkdir(parents=True, mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            mount = data_home / "proton-drive-desktop/files"
            mount.mkdir(parents=True, mode=mode)
            mount.chmod(mode)
            information = mount.stat()
            nonce = "12" * 32
            common = {
                "mount": str(mount),
                "device": information.st_dev,
                "inode": information.st_ino,
                "created": True,
                "nonce": nonce,
                "mount_tag": "proton-drive-desktop-" + "34" * 32,
            }
            marker_record = None
            if marker_kind == "predecessor":
                marker_record = {
                    **common,
                    "created": False,
                    "nonce": "56" * 32,
                    "mount_tag": "proton-drive-desktop-" + "78" * 32,
                    "mount_id": "90",
                }
                encoded = json.dumps(
                    marker_record, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
                commitment = hashlib.sha256(
                    b"proton-drive-desktop predecessor\0"
                    + nonce.encode("ascii")
                    + b"\0"
                    + encoded
                ).hexdigest()
                common["mount_tag"] = f"proton-drive-desktop-{commitment}"
            elif marker_kind == "prepared":
                marker_record = dict(common)
            elif marker_kind == "verified":
                marker_record = {**common, "mount_id": "91"}
            elif marker_kind != "absent":
                raise AssertionError(f"unknown marker fixture: {marker_kind}")
            phase = runtime / "mountpoint-phase.json"
            marker = runtime / "mountpoint.json"
            phase.write_text(json.dumps({
                "phase": phase_name, **common,
            }, separators=(",", ":")))
            if marker_record is not None:
                marker.write_text(json.dumps(
                    marker_record, separators=(",", ":")
                ))
            if identity == "matching":
                os.setxattr(
                    mount,
                    "user.proton-drive-desktop.identity",
                    nonce.encode("ascii"),
                )
            elif identity == "wrong":
                os.setxattr(
                    mount,
                    "user.proton-drive-desktop.identity",
                    b"9a" * 32,
                )
            elif identity != "absent":
                raise AssertionError(f"unknown identity fixture: {identity}")
            os.setxattr(mount, "user.keep", b"preserve this xattr")
            binding = runtime / "binding.json"
            binding.write_text(json.dumps({
                "config": str(config), "mount": str(mount),
            }, separators=(",", ":")))
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(data_home),
                "XDG_RUNTIME_DIR": str(runtime_base),
            }
            external_calls = []

            def external(arguments, **kwargs):
                external_calls.append(arguments)
                if arguments[0] == "/usr/bin/systemctl" and arguments[2] == "show":
                    main_pid = (
                        "MainPID=0\n"
                        if "--property=MainPID" in arguments else ""
                    )
                    return subprocess.CompletedProcess(
                        arguments,
                        0,
                        stdout=(
                            "ActiveState=inactive\nSubState=dead\n"
                            f"Result=success\n{main_pid}"
                        ),
                    )
                return subprocess.CompletedProcess(arguments, 0)

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            yield {
                "root": root,
                "mount": mount,
                "runtime": runtime,
                "phase": phase,
                "marker": marker,
                "environment": environment,
                "external": external,
                "external_calls": external_calls,
                "opened": opened,
            }

    @contextlib.contextmanager
    def prepare_create_recovery_fixture(self, predecessor=True):
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
            mount = data_home / "proton-drive-desktop/files"
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(data_home),
                "XDG_RUNTIME_DIR": str(runtime_base),
            }

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            if predecessor:
                self.assertEqual(
                    (0, "", ""),
                    invoke(["_prepare"], environment, opened=opened),
                )
                mount.rmdir()

            real_mkdir = os.mkdir

            def interrupt_leaf_creation(path, mode=0o777, *args, **kwargs):
                descriptor = kwargs.get("dir_fd")
                if descriptor is not None:
                    parent = pathlib.Path(
                        os.readlink(f"/proc/self/fd/{descriptor}")
                    )
                    if parent / path == mount:
                        raise SystemExit(95)
                return real_mkdir(path, mode, *args, **kwargs)

            with mock.patch("os.mkdir", side_effect=interrupt_leaf_creation):
                self.assertEqual(
                    95,
                    invoke(["_prepare"], environment, opened=opened)[0],
                )

            runtime = runtime_base / "proton-drive-desktop"
            phase = runtime / "mountpoint-phase.json"
            marker = runtime / "mountpoint.json"
            self.assertFalse(mount.exists())
            self.assertTrue(phase.is_file())
            self.assertEqual(predecessor, marker.is_file())

            def external(arguments, **kwargs):
                return subprocess.CompletedProcess(
                    arguments,
                    0,
                    stdout=(
                        "ActiveState=inactive\nSubState=dead\n"
                        "Result=success\nMainPID=0\n"
                    ),
                )

            yield {
                "mount": mount,
                "phase": phase,
                "marker": marker,
                "environment": environment,
                "external": external,
                "opened": opened,
            }

    def assert_interrupted_publication_rejected(
        self, mount, marker, phase, environment, opened, expected_error,
        fstat=None,
    ):
        before = retained_publication_snapshot(mount, marker, phase)
        fstat_patch = (
            mock.patch("os.fstat", side_effect=fstat)
            if fstat is not None
            else contextlib.nullcontext()
        )
        with fstat_patch:
            result = invoke(["_prepare"], environment, opened=opened)

        self.assertEqual((1, "", expected_error), result)
        self.assertEqual(
            before, retained_publication_snapshot(mount, marker, phase)
        )
        launch = mock.Mock()
        self.assertEqual(
            (
                1,
                "",
                "interrupted mountpoint identity publication requires "
                "stopped recovery\n",
            ),
            invoke(["_mount"], environment, execve=launch, opened=opened),
        )
        launch.assert_not_called()
        self.assertEqual(
            before, retained_publication_snapshot(mount, marker, phase)
        )

    def test_inspect_recovery_accepts_admitted_prepare_publication_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            mount.mkdir(parents=True, mode=0o755)
            mount.chmod(0o755)
            runtime.mkdir(parents=True, mode=0o700)
            information = mount.stat()
            nonce = "12" * 32
            phase = runtime / "mountpoint-phase.json"
            phase.write_text(json.dumps({
                "phase": "prepare-publish",
                "mount": str(mount),
                "device": information.st_dev,
                "inode": information.st_ino,
                "created": True,
                "nonce": nonce,
                "mount_tag": "proton-drive-desktop-" + "34" * 32,
            }, separators=(",", ":")))
            os.setxattr(mount, "user.keep", b"preserve this xattr")
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_RUNTIME_DIR": str(root / "run"),
            }
            before = retained_publication_snapshot(
                mount, runtime / "mountpoint.json", phase
            )
            external_calls = []

            def external(arguments, **kwargs):
                external_calls.append(arguments)
                return subprocess.CompletedProcess(
                    arguments,
                    0,
                    stdout=(
                        "ActiveState=inactive\nSubState=dead\n"
                        "Result=success\nMainPID=0\n"
                    ),
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["inspect-recovery"], environment,
                run=external, opened=opened,
            )

            self.assertEqual(
                (
                    0,
                    "recovery eligible: prepare-publish\n"
                    "next action: proton-drive-desktop start\n",
                    "",
                ),
                result,
            )
            self.assertEqual(
                before,
                retained_publication_snapshot(
                    mount, runtime / "mountpoint.json", phase
                ),
            )
            self.assertEqual(0o755, stat.S_IMODE(mount.stat().st_mode))
            self.assertEqual(
                [[
                    "/usr/bin/systemctl", "--user", "show",
                    "proton-drive-desktop.service", "--property=ActiveState",
                    "--property=SubState", "--property=Result",
                    "--property=MainPID",
                ]],
                external_calls,
            )

    def test_inspect_recovery_accepts_verified_cleanup_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            mount.mkdir(parents=True, mode=0o750)
            mount.chmod(0o750)
            runtime.mkdir(parents=True, mode=0o700)
            information = mount.stat()
            nonce = "56" * 32
            mount_tag = "proton-drive-desktop-" + "78" * 32
            common = {
                "mount": str(mount),
                "device": information.st_dev,
                "inode": information.st_ino,
                "created": False,
                "nonce": nonce,
                "mount_tag": mount_tag,
            }
            phase = runtime / "mountpoint-phase.json"
            marker = runtime / "mountpoint.json"
            phase.write_text(json.dumps({
                "phase": "cleanup-retained", **common,
            }, separators=(",", ":")))
            marker.write_text(json.dumps({
                **common, "mount_id": "91",
            }, separators=(",", ":")))
            os.setxattr(
                mount,
                "user.proton-drive-desktop.identity",
                nonce.encode("ascii"),
            )
            os.setxattr(mount, "user.keep", b"preserve this xattr")
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_RUNTIME_DIR": str(root / "run"),
            }
            before = retained_publication_snapshot(mount, marker, phase)
            external_calls = []

            def external(arguments, **kwargs):
                external_calls.append(arguments)
                main_pid = (
                    "MainPID=0\n"
                    if "--property=MainPID" in arguments else ""
                )
                return subprocess.CompletedProcess(
                    arguments,
                    0,
                    stdout=(
                        "ActiveState=inactive\nSubState=dead\n"
                        f"Result=success\n{main_pid}"
                    ),
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            inspected = invoke(
                ["inspect-recovery"], environment,
                run=external, opened=opened,
            )

            self.assertEqual(
                (
                    0,
                    "recovery eligible: cleanup-retained\n"
                    "next action: proton-drive-desktop stop\n",
                    "",
                ),
                inspected,
            )
            self.assertEqual(
                before, retained_publication_snapshot(mount, marker, phase)
            )
            self.assertEqual(0o750, stat.S_IMODE(mount.stat().st_mode))
            self.assertEqual(1, len(external_calls))

            self.assertEqual(
                (0, "", ""),
                invoke(["_post-stop"], environment, opened=opened),
            )
            self.assertEqual(
                before, retained_publication_snapshot(mount, marker, phase)
            )
            self.assertEqual(
                (0, "stopped\n", ""),
                invoke(
                    ["stop"], environment, run=external, opened=opened
                ),
            )
            self.assertFalse(marker.exists())
            self.assertFalse(phase.exists())
            self.assertEqual(0o750, stat.S_IMODE(mount.stat().st_mode))
            self.assertEqual(b"preserve this xattr", os.getxattr(mount, "user.keep"))

    def test_inspect_recovery_accepts_only_absent_prepare_create_leaf(self):
        for leaf_exists in (False, True):
            with self.subTest(leaf_exists=leaf_exists), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                config_parent = root / "config/rclone"
                data_home = root / "data"
                runtime = root / "run/proton-drive-desktop"
                config_parent.mkdir(parents=True, mode=0o700)
                data_home.mkdir(mode=0o700)
                runtime.mkdir(parents=True, mode=0o700)
                config = config_parent / "proton-drive.conf"
                config.write_text("encrypted-placeholder")
                config.chmod(0o600)
                mount = data_home / "proton-drive-desktop/files"
                mount.parent.mkdir(mode=0o700)
                if leaf_exists:
                    mount.mkdir(mode=0o755)
                    os.setxattr(mount, "user.keep", b"preserve this xattr")
                phase = runtime / "mountpoint-phase.json"
                phase.write_text(json.dumps({
                    "phase": "prepare-create",
                    "mount": str(mount),
                    "created": True,
                    "nonce": "9a" * 32,
                    "mount_tag": "proton-drive-desktop-" + "bc" * 32,
                }, separators=(",", ":")))
                (runtime / "binding.json").write_text(json.dumps({
                    "config": str(config), "mount": str(mount),
                }, separators=(",", ":")))
                environment = {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(data_home),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                }
                phase_before = phase.read_bytes()
                leaf_before = (
                    retained_publication_snapshot(
                        mount, runtime / "mountpoint.json", phase
                    )
                    if leaf_exists else None
                )

                def external(arguments, **kwargs):
                    return subprocess.CompletedProcess(
                        arguments,
                        0,
                        stdout=(
                            "ActiveState=inactive\nSubState=dead\n"
                            "Result=success\nMainPID=0\n"
                        ),
                    )

                def opened(name, *args, **kwargs):
                    if name == "/proc/self/mountinfo":
                        return io.StringIO("")
                    return io.open(name, *args, **kwargs)

                inspected = invoke(
                    ["inspect-recovery"], environment,
                    run=external, opened=opened,
                )

                if leaf_exists:
                    self.assertEqual(
                        (
                            1,
                            "",
                            "prepare-create cannot authorize an existing leaf; "
                            "preserve everything\n",
                        ),
                        inspected,
                    )
                    self.assertEqual(
                        leaf_before,
                        retained_publication_snapshot(
                            mount, runtime / "mountpoint.json", phase
                        ),
                    )
                    self.assertEqual(
                        (
                            1,
                            "",
                            "interrupted mountpoint creation requires stopped "
                            "recovery\n",
                        ),
                        invoke(["_prepare"], environment, opened=opened),
                    )
                else:
                    self.assertEqual(
                        (
                            0,
                            "recovery eligible: prepare-create\n"
                            "next action: proton-drive-desktop start\n",
                            "",
                        ),
                        inspected,
                    )
                    self.assertFalse(mount.exists())
                    self.assertEqual(phase_before, phase.read_bytes())
                    self.assertEqual(
                        (0, "", ""),
                        invoke(["_prepare"], environment, opened=opened),
                    )
                    self.assertTrue(mount.is_dir())
                    self.assertFalse(phase.exists())

    def test_prepare_create_accepts_absence_and_committed_predecessor(self):
        for predecessor in (False, True):
            with self.subTest(
                predecessor=predecessor
            ), self.prepare_create_recovery_fixture(predecessor) as fixture:
                phase_before = fixture["phase"].read_bytes()
                marker_before = (
                    fixture["marker"].read_bytes() if predecessor else None
                )

                inspected = invoke(
                    ["inspect-recovery"], fixture["environment"],
                    run=fixture["external"], opened=fixture["opened"],
                )

                self.assertEqual(
                    (
                        0,
                        "recovery eligible: prepare-create\n"
                        "next action: proton-drive-desktop start\n",
                        "",
                    ),
                    inspected,
                )
                self.assertEqual(phase_before, fixture["phase"].read_bytes())
                if predecessor:
                    self.assertEqual(
                        marker_before, fixture["marker"].read_bytes()
                    )
                else:
                    self.assertFalse(fixture["marker"].exists())
                self.assertFalse(fixture["mount"].exists())

                self.assertEqual(
                    (0, "", ""),
                    invoke(
                        ["_prepare"], fixture["environment"],
                        opened=fixture["opened"],
                    ),
                )
                self.assertTrue(fixture["mount"].is_dir())
                self.assertTrue(fixture["marker"].is_file())
                self.assertFalse(fixture["phase"].exists())

    def test_prepare_create_rejects_invalid_markers_without_losing_evidence(self):
        cases = (
            "null",
            "scalar",
            "array",
            "malformed",
            "extra-field",
            "wrong-path",
            "wrong-tag",
            "unrelated-valid",
        )
        for marker_case in cases:
            with self.subTest(
                marker=marker_case
            ), self.prepare_create_recovery_fixture() as fixture:
                if marker_case == "null":
                    marker_bytes = b"null"
                elif marker_case == "scalar":
                    marker_bytes = b'"marker"'
                elif marker_case == "array":
                    marker_bytes = b"[]"
                elif marker_case == "malformed":
                    marker_bytes = b'{"mount":'
                else:
                    ownership = json.loads(fixture["marker"].read_bytes())
                    if marker_case == "extra-field":
                        ownership["version"] = 2
                    elif marker_case == "wrong-path":
                        ownership["mount"] += "-other"
                    elif marker_case == "wrong-tag":
                        ownership["mount_tag"] = (
                            "proton-drive-desktop-" + "cd" * 32
                        )
                    elif marker_case == "unrelated-valid":
                        ownership["device"] += 1
                        ownership["inode"] += 1
                        ownership["nonce"] = "ef" * 32
                    else:
                        raise AssertionError(marker_case)
                    marker_bytes = json.dumps(
                        ownership, separators=(",", ":")
                    ).encode()
                fixture["marker"].write_bytes(marker_bytes)
                marker_before = fixture["marker"].read_bytes()
                phase_before = fixture["phase"].read_bytes()

                inspected = invoke(
                    ["inspect-recovery"], fixture["environment"],
                    run=fixture["external"], opened=fixture["opened"],
                )

                self.assertEqual(
                    (
                        1,
                        "",
                        "marker does not match phase; preserve everything\n",
                    ),
                    inspected,
                )
                self.assertEqual(
                    marker_before, fixture["marker"].read_bytes()
                )
                self.assertTrue(fixture["phase"].is_file())
                self.assertEqual(phase_before, fixture["phase"].read_bytes())
                self.assertFalse(fixture["mount"].exists())

                recovered = invoke(
                    ["_prepare"], fixture["environment"],
                    opened=fixture["opened"],
                )

                self.assertEqual(
                    (
                        1,
                        "",
                        "interrupted mountpoint creation requires stopped "
                        "recovery\n",
                    ),
                    recovered,
                )
                self.assertEqual(
                    marker_before, fixture["marker"].read_bytes()
                )
                self.assertTrue(fixture["phase"].is_file())
                self.assertEqual(phase_before, fixture["phase"].read_bytes())
                self.assertFalse(fixture["mount"].exists())

    def test_inspection_and_recovery_share_phase_specific_marker_rules(self):
        cases = (
            ("prepare-publish", "absent", "absent"),
            ("prepare-publish", "prepared", "matching"),
            ("prepare-publish", "predecessor", "absent"),
            ("cleanup-retained", "absent", "absent"),
            ("cleanup-retained", "prepared", "matching"),
            ("cleanup-retained", "verified", "matching"),
        )
        for phase_name, marker_kind, identity in cases:
            with self.subTest(
                phase=phase_name, marker=marker_kind, identity=identity
            ), self.retained_recovery_fixture(
                phase_name, marker_kind=marker_kind, identity=identity
            ) as fixture:
                before = retained_publication_snapshot(
                    fixture["mount"], fixture["marker"], fixture["phase"]
                )

                inspected = invoke(
                    ["inspect-recovery"], fixture["environment"],
                    run=fixture["external"], opened=fixture["opened"],
                )

                action = "start" if phase_name == "prepare-publish" else "stop"
                self.assertEqual(
                    (
                        0,
                        f"recovery eligible: {phase_name}\n"
                        f"next action: proton-drive-desktop {action}\n",
                        "",
                    ),
                    inspected,
                )
                self.assertEqual(
                    before,
                    retained_publication_snapshot(
                        fixture["mount"], fixture["marker"], fixture["phase"]
                    ),
                )
                self.assertEqual(1, len(fixture["external_calls"]))

                if phase_name == "prepare-publish":
                    recovered = invoke(
                        ["_prepare"], fixture["environment"],
                        opened=fixture["opened"],
                    )
                    self.assertEqual((0, "", ""), recovered)
                else:
                    recovered = invoke(
                        ["stop"], fixture["environment"],
                        run=fixture["external"], opened=fixture["opened"],
                    )
                    self.assertEqual((0, "stopped\n", ""), recovered)
                self.assertFalse(fixture["phase"].exists())
                self.assertEqual(
                    b"preserve this xattr",
                    os.getxattr(fixture["mount"], "user.keep"),
                )

    def test_committed_publication_predecessor_must_name_the_same_mount(self):
        for same_path in (False, True):
            with self.subTest(
                same_path=same_path
            ), self.retained_recovery_fixture(
                "prepare-publish",
                marker_kind="predecessor",
                identity="absent",
            ) as fixture:
                marker = json.loads(fixture["marker"].read_bytes())
                operation = json.loads(fixture["phase"].read_bytes())
                if not same_path:
                    marker["mount"] = str(
                        fixture["root"] / "different-mount/files"
                    )
                    marker_bytes = json.dumps(
                        marker, separators=(",", ":")
                    ).encode("utf-8")
                    fixture["marker"].write_bytes(marker_bytes)
                    encoded = json.dumps(
                        marker, sort_keys=True, separators=(",", ":")
                    ).encode("utf-8")
                    commitment = hashlib.sha256(
                        b"proton-drive-desktop predecessor\0"
                        + operation["nonce"].encode("ascii")
                        + b"\0"
                        + encoded
                    ).hexdigest()
                    operation["mount_tag"] = (
                        f"proton-drive-desktop-{commitment}"
                    )
                    fixture["phase"].write_text(json.dumps(
                        operation, separators=(",", ":")
                    ))
                before = retained_publication_snapshot(
                    fixture["mount"], fixture["marker"], fixture["phase"]
                )

                inspected = invoke(
                    ["inspect-recovery"], fixture["environment"],
                    run=fixture["external"], opened=fixture["opened"],
                )
                if same_path:
                    self.assertEqual(
                        (
                            0,
                            "recovery eligible: prepare-publish\n"
                            "next action: proton-drive-desktop start\n",
                            "",
                        ),
                        inspected,
                    )
                else:
                    self.assertEqual(
                        (
                            1,
                            "",
                            "marker does not match phase; preserve "
                            "everything\n",
                        ),
                        inspected,
                    )
                self.assertEqual(
                    before,
                    retained_publication_snapshot(
                        fixture["mount"], fixture["marker"], fixture["phase"]
                    ),
                )

                recovered = invoke(
                    ["_prepare"], fixture["environment"],
                    opened=fixture["opened"],
                )
                if same_path:
                    self.assertEqual((0, "", ""), recovered)
                    self.assertFalse(fixture["phase"].exists())
                    ownership = json.loads(fixture["marker"].read_bytes())
                    self.assertEqual(
                        operation["mount"], ownership["mount"]
                    )
                    self.assertEqual(
                        operation["nonce"].encode("ascii"),
                        os.getxattr(
                            fixture["mount"],
                            "user.proton-drive-desktop.identity",
                        ),
                    )
                    self.assertEqual(
                        b"preserve this xattr",
                        os.getxattr(fixture["mount"], "user.keep"),
                    )
                else:
                    self.assertEqual(
                        (
                            1,
                            "",
                            "interrupted mountpoint identity publication "
                            "requires stopped recovery\n",
                        ),
                        recovered,
                    )
                    self.assertEqual(
                        before,
                        retained_publication_snapshot(
                            fixture["mount"], fixture["marker"],
                            fixture["phase"],
                        ),
                    )

    def test_inspection_and_recovery_reject_every_present_invalid_marker(self):
        invalid_markers = {
            "null": b"null",
            "scalar": b'"marker"',
            "array": b"[]",
            "malformed": b'{"mount":',
            "extra-field": None,
        }
        for phase_name in ("prepare-publish", "cleanup-retained"):
            for marker_case, marker_bytes in invalid_markers.items():
                with self.subTest(
                    phase=phase_name, marker=marker_case
                ), self.retained_recovery_fixture(
                    phase_name, identity="matching"
                ) as fixture:
                    if marker_bytes is None:
                        operation = json.loads(fixture["phase"].read_text())
                        marker_bytes = json.dumps({
                            key: operation[key]
                            for key in (
                                "mount", "device", "inode", "created",
                                "nonce", "mount_tag",
                            )
                        } | {"version": 2}, separators=(",", ":")).encode()
                    fixture["marker"].write_bytes(marker_bytes)
                    before = retained_publication_snapshot(
                        fixture["mount"], fixture["marker"], fixture["phase"]
                    )

                    inspected = invoke(
                        ["inspect-recovery"], fixture["environment"],
                        run=fixture["external"], opened=fixture["opened"],
                    )

                    self.assertEqual(
                        (
                            1,
                            "",
                            "marker does not match phase; preserve everything\n",
                        ),
                        inspected,
                    )
                    self.assertEqual(
                        before,
                        retained_publication_snapshot(
                            fixture["mount"], fixture["marker"], fixture["phase"]
                        ),
                    )

                    if phase_name == "prepare-publish":
                        rejected = invoke(
                            ["_prepare"], fixture["environment"],
                            opened=fixture["opened"],
                        )
                        self.assertEqual(
                            (
                                1,
                                "",
                                "interrupted mountpoint identity publication "
                                "requires stopped recovery\n",
                            ),
                            rejected,
                        )
                    else:
                        rejected = invoke(
                            ["stop"], fixture["environment"],
                            run=fixture["external"], opened=fixture["opened"],
                        )
                        self.assertEqual(1, rejected[0])
                    self.assertEqual(
                        before,
                        retained_publication_snapshot(
                            fixture["mount"], fixture["marker"], fixture["phase"]
                        ),
                    )

    def test_cleanup_inspection_does_not_accept_publication_predecessor(self):
        with self.retained_recovery_fixture(
            "cleanup-retained", marker_kind="predecessor", identity="matching"
        ) as fixture:
            before = retained_publication_snapshot(
                fixture["mount"], fixture["marker"], fixture["phase"]
            )

            inspected = invoke(
                ["inspect-recovery"], fixture["environment"],
                run=fixture["external"], opened=fixture["opened"],
            )

            self.assertEqual(
                (
                    1,
                    "",
                    "marker does not match phase; preserve everything\n",
                ),
                inspected,
            )
            self.assertEqual(
                before,
                retained_publication_snapshot(
                    fixture["mount"], fixture["marker"], fixture["phase"]
                ),
            )
            stopped = invoke(
                ["stop"], fixture["environment"],
                run=fixture["external"], opened=fixture["opened"],
            )
            self.assertEqual(1, stopped[0])
            self.assertEqual(
                before,
                retained_publication_snapshot(
                    fixture["mount"], fixture["marker"], fixture["phase"]
                ),
            )

    def test_cleanup_retained_survives_startup_hooks_until_explicit_stop(self):
        diagnostic = (
            "interrupted retained mountpoint cleanup requires stopped "
            "recovery\n"
        )
        for entrypoint in ("start", "open", "automatic"):
            with self.subTest(
                entrypoint=entrypoint
            ), self.retained_recovery_fixture(
                "cleanup-retained",
                marker_kind="verified",
                mode=0o750,
                identity="matching",
            ) as fixture:
                mount = fixture["mount"]
                marker = fixture["marker"]
                phase = fixture["phase"]
                before = retained_publication_snapshot(mount, marker, phase)
                information = mount.stat()
                directory_identity = (
                    information.st_dev,
                    information.st_ino,
                    stat.S_IMODE(information.st_mode),
                )
                hook_results = []
                dolphin = mock.Mock()

                def external(arguments, **kwargs):
                    if arguments[2] == "show":
                        main_pid = (
                            "MainPID=0\n"
                            if "--property=MainPID" in arguments else ""
                        )
                        return subprocess.CompletedProcess(
                            arguments,
                            0,
                            stdout=(
                                "ActiveState=inactive\nSubState=dead\n"
                                f"Result=success\n{main_pid}"
                            ),
                        )
                    if arguments[2] == "start":
                        hook_results.extend((
                            invoke(
                                ["_prepare"], fixture["environment"],
                                opened=fixture["opened"],
                            ),
                            invoke(
                                ["_post-stop"], fixture["environment"],
                                opened=fixture["opened"],
                            ),
                        ))
                        return subprocess.CompletedProcess(arguments, 1)
                    return subprocess.CompletedProcess(arguments, 0)

                if entrypoint == "automatic":
                    hook_results.extend((
                        invoke(
                            ["_prepare"], fixture["environment"],
                            opened=fixture["opened"],
                        ),
                        invoke(
                            ["_post-stop"], fixture["environment"],
                            opened=fixture["opened"],
                        ),
                    ))
                else:
                    refused = invoke(
                        [entrypoint], fixture["environment"],
                        run=external, popen=dolphin,
                        opened=fixture["opened"],
                    )
                    self.assertEqual((1, "", diagnostic), refused)
                    dolphin.assert_not_called()

                self.assertEqual(
                    [(1, "", diagnostic), (0, "", "")], hook_results
                )
                self.assertEqual(
                    before,
                    retained_publication_snapshot(mount, marker, phase),
                )

                inspected = invoke(
                    ["inspect-recovery"], fixture["environment"],
                    run=external, opened=fixture["opened"],
                )
                self.assertEqual(
                    (
                        0,
                        "recovery eligible: cleanup-retained\n"
                        "next action: proton-drive-desktop stop\n",
                        "",
                    ),
                    inspected,
                )
                self.assertEqual(
                    before,
                    retained_publication_snapshot(mount, marker, phase),
                )

                stopped = invoke(
                    ["stop"], fixture["environment"],
                    run=external, opened=fixture["opened"],
                )
                self.assertEqual((0, "stopped\n", ""), stopped)
                self.assertFalse(marker.exists())
                self.assertFalse(phase.exists())
                after = mount.stat()
                self.assertEqual(
                    directory_identity,
                    (
                        after.st_dev,
                        after.st_ino,
                        stat.S_IMODE(after.st_mode),
                    ),
                )
                self.assertEqual([], list(mount.iterdir()))
                self.assertEqual(
                    ["user.keep"],
                    sorted(os.listxattr(mount, follow_symlinks=False)),
                )
                self.assertEqual(
                    b"preserve this xattr", os.getxattr(mount, "user.keep")
                )

    def test_inspection_and_prepare_share_directory_evidence_refusals(self):
        cases = {
            "unsafe-mode": "unsafe mountpoint; preserve everything\n",
            "foreign-owner": "unsafe mountpoint; preserve everything\n",
            "contents": "mountpoint is not empty; preserve everything\n",
            "replacement": "directory identity mismatch; preserve everything\n",
            "wrong-nonce": "directory identity mismatch; preserve everything\n",
            "wrong-tag": "marker does not match phase; preserve everything\n",
            "wrong-path": (
                "phase names a different mountpoint; preserve everything\n"
            ),
            "wrong-device": "directory identity mismatch; preserve everything\n",
            "wrong-inode": "directory identity mismatch; preserve everything\n",
        }
        for evidence, expected_error in cases.items():
            with self.subTest(evidence=evidence), self.retained_recovery_fixture(
                "prepare-publish", marker_kind="prepared", identity="matching"
            ) as fixture:
                mount = fixture["mount"]
                fstat_patch = contextlib.nullcontext()
                if evidence == "unsafe-mode":
                    mount.chmod(0o770)
                elif evidence == "foreign-owner":
                    def foreign_owner_fstat(descriptor):
                        information = REAL_FSTAT(descriptor)
                        try:
                            path = pathlib.Path(
                                os.readlink(f"/proc/self/fd/{descriptor}")
                            )
                        except OSError:
                            return information
                        if path == pathlib.Path(tempfile.gettempdir()).resolve():
                            return with_mode(information, 0o755)
                        if path == mount:
                            return with_uid(information, os.getuid() + 1)
                        return information

                    fstat_patch = mock.patch(
                        "os.fstat", side_effect=foreign_owner_fstat
                    )
                elif evidence == "contents":
                    (mount / "keep.txt").write_text("preserve this file")
                elif evidence == "replacement":
                    retained = mount.parent / "retained-original"
                    mount.rename(retained)
                    mount.mkdir(mode=0o700)
                    os.setxattr(mount, "user.keep", b"preserve replacement")
                elif evidence == "wrong-nonce":
                    os.setxattr(
                        mount,
                        "user.proton-drive-desktop.identity",
                        b"9a" * 32,
                    )
                elif evidence == "wrong-tag":
                    ownership = json.loads(fixture["marker"].read_text())
                    ownership["mount_tag"] = (
                        "proton-drive-desktop-" + "ab" * 32
                    )
                    fixture["marker"].write_text(json.dumps(
                        ownership, separators=(",", ":")
                    ))
                elif evidence in {"wrong-path", "wrong-device", "wrong-inode"}:
                    operation = json.loads(fixture["phase"].read_text())
                    if evidence == "wrong-path":
                        operation["mount"] += "-other"
                    elif evidence == "wrong-device":
                        operation["device"] += 1
                    else:
                        operation["inode"] += 1
                    fixture["phase"].write_text(json.dumps(
                        operation, separators=(",", ":")
                    ))
                else:
                    raise AssertionError(evidence)
                before = retained_publication_snapshot(
                    mount, fixture["marker"], fixture["phase"]
                )

                with fstat_patch:
                    inspected = invoke(
                        ["inspect-recovery"], fixture["environment"],
                        run=fixture["external"], opened=fixture["opened"],
                    )
                    rejected = invoke(
                        ["_prepare"], fixture["environment"],
                        opened=fixture["opened"],
                    )

                self.assertEqual((1, "", expected_error), inspected)
                self.assertEqual(1, rejected[0])
                self.assertEqual(
                    before,
                    retained_publication_snapshot(
                        mount, fixture["marker"], fixture["phase"]
                    ),
                )

    def test_inspection_and_public_commands_reject_manager_and_mount_uncertainty(self):
        manager_cases = {
            "unavailable": subprocess.CompletedProcess([], 1, stdout=""),
            "malformed": subprocess.CompletedProcess(
                [], 0, stdout="ActiveState=inactive\n"
            ),
            "active": subprocess.CompletedProcess(
                [],
                0,
                stdout=(
                    "ActiveState=active\nSubState=running\nResult=success\n"
                ),
            ),
        }
        for manager_state, response in manager_cases.items():
            with self.subTest(
                manager=manager_state
            ), self.retained_recovery_fixture(
                "prepare-publish", identity="absent"
            ) as fixture:
                calls = []

                def external(arguments, **kwargs):
                    calls.append(arguments)
                    stdout = response.stdout
                    if (
                        response.returncode == 0
                        and "--property=MainPID" in arguments
                    ):
                        stdout += "MainPID=0\n"
                    return subprocess.CompletedProcess(
                        arguments, response.returncode, stdout=stdout
                    )

                before = retained_publication_snapshot(
                    fixture["mount"], fixture["marker"], fixture["phase"]
                )
                inspected = invoke(
                    ["inspect-recovery"], fixture["environment"],
                    run=external, opened=fixture["opened"],
                )
                started = invoke(
                    ["start"], fixture["environment"],
                    run=external, opened=fixture["opened"],
                )

                self.assertEqual(1, inspected[0])
                self.assertEqual(1, started[0])
                self.assertFalse(any(
                    call[0] == "/usr/bin/systemctl" and call[2] == "start"
                    for call in calls
                ))
                self.assertEqual(
                    before,
                    retained_publication_snapshot(
                        fixture["mount"], fixture["marker"], fixture["phase"]
                    ),
                )

        with self.retained_recovery_fixture(
            "prepare-publish", identity="absent"
        ) as fixture:
            mount = fixture["mount"]
            encoded_mount = str(mount).replace(" ", "\\040")
            foreign_mount = (
                f"71 30 0:71 / {encoded_mount} rw,nosuid,nodev - "
                "fuse.other local: rw\n"
            )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO(foreign_mount)
                return io.open(name, *args, **kwargs)

            before = retained_publication_snapshot(
                mount, fixture["marker"], fixture["phase"]
            )
            inspected = invoke(
                ["inspect-recovery"], fixture["environment"],
                run=fixture["external"], opened=opened,
            )
            started = invoke(
                ["start"], fixture["environment"],
                run=fixture["external"], opened=opened,
            )

            self.assertEqual(
                (
                    1,
                    "",
                    "recovery target is mounted or foreign; preserving "
                    "recovery evidence\n",
                ),
                inspected,
            )
            self.assertEqual((1, "", "inconsistent/foreign state\n"), started)
            self.assertFalse(any(
                call[0] == "/usr/bin/systemctl" and call[2] == "start"
                for call in fixture["external_calls"]
            ))
            self.assertEqual(
                before,
                retained_publication_snapshot(
                    mount, fixture["marker"], fixture["phase"]
                ),
            )

    def test_inspect_recovery_rejects_a_stopped_manager_with_a_process(self):
        with self.retained_recovery_fixture(
            "prepare-publish", identity="absent"
        ) as fixture:
            def manager_with_process(arguments, **kwargs):
                return subprocess.CompletedProcess(
                    arguments,
                    0,
                    stdout=(
                        "ActiveState=failed\nSubState=failed\n"
                        "Result=exit-code\nMainPID=42\n"
                    ),
                )

            inspected = invoke(
                ["inspect-recovery"], fixture["environment"],
                run=manager_with_process, opened=fixture["opened"],
            )

            self.assertEqual(
                (
                    1,
                    "",
                    "service still has a process; preserving recovery evidence\n",
                ),
                inspected,
            )

    def test_prepare_accepts_only_the_fixed_scrubbed_rclone_version_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "config/rclone").mkdir(parents=True, mode=0o700)
            (root / "data").mkdir(mode=0o700)
            (root / "run").mkdir(mode=0o700)
            config = root / "config/rclone/proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_RUNTIME_DIR": str(root / "run"),
                "RCLONE_CONFIG_PASS": "secret-canary",
                "_RCLONE_INTERNAL": "internal-canary",
                "UNRELATED_VALUE": "preserved",
            }
            observed = {}

            def version_process(command, *args, **kwargs):
                observed.update(command=command, kwargs=kwargs)
                return subprocess.CompletedProcess(
                    command, 0, stdout=RCLONE_VERSION_OUTPUT
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["_prepare"], environment, opened=opened,
                rclone_version=version_process,
            )

            self.assertEqual((0, "", ""), result)
            self.assertEqual(RCLONE_VERSION_COMMAND, observed["command"])
            child_environment = observed["kwargs"]["env"]
            self.assertNotIn("RCLONE_CONFIG_PASS", child_environment)
            self.assertNotIn("_RCLONE_INTERNAL", child_environment)
            self.assertEqual("preserved", child_environment["UNRELATED_VALUE"])
            self.assertEqual(subprocess.DEVNULL, observed["kwargs"]["stdin"])
            self.assertEqual(subprocess.PIPE, observed["kwargs"]["stdout"])
            self.assertEqual(subprocess.DEVNULL, observed["kwargs"]["stderr"])
            self.assertTrue(observed["kwargs"]["start_new_session"])
            self.assertTrue(
                (root / "run/proton-drive-desktop/mountpoint.json").is_file()
            )

    def test_prepare_rejects_unqualified_rclone_before_managed_state_mutation(self):
        outcomes = {
            "wrong": subprocess.CompletedProcess(
                RCLONE_VERSION_COMMAND, 0, stdout=b"rclone v1.76.0\n"
            ),
            "malformed": subprocess.CompletedProcess(
                RCLONE_VERSION_COMMAND, 0, stdout=b"not-rclone\n"
            ),
            "invalid-utf8": subprocess.CompletedProcess(
                RCLONE_VERSION_COMMAND, 0, stdout=b"rclone v1.75.2\xff\n"
            ),
            "oversized": subprocess.CompletedProcess(
                RCLONE_VERSION_COMMAND, 0,
                stdout=b"rclone v1.75.2\n" + b"x" * 8192,
            ),
            "failing": subprocess.CompletedProcess(
                RCLONE_VERSION_COMMAND, 23, stdout=b"secret-canary\n"
            ),
            "absent": FileNotFoundError("secret-canary"),
        }
        for case, outcome in outcomes.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                (root / "config/rclone").mkdir(parents=True, mode=0o700)
                (root / "data").mkdir(mode=0o700)
                (root / "run").mkdir(mode=0o700)
                config = root / "config/rclone/proton-drive.conf"
                config.write_text("encrypted-placeholder")
                config.chmod(0o600)
                environment = {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                }
                launched = mock.Mock(
                    side_effect=AssertionError("mount execution reached")
                )

                result = invoke(
                    ["_prepare"], environment, execve=launched,
                    rclone_version=outcome,
                )

                self.assertEqual(
                    (1, "", "rclone version check failed\n"), result
                )
                self.assertFalse(
                    (root / "data/proton-drive-desktop/files").exists()
                )
                self.assertFalse(
                    (root / "run/proton-drive-desktop").exists()
                )
                launched.assert_not_called()

    def test_prepare_bounds_a_stalled_rclone_version_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "config/rclone").mkdir(parents=True, mode=0o700)
            (root / "data").mkdir(mode=0o700)
            (root / "run").mkdir(mode=0o700)
            config = root / "config/rclone/proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_RUNTIME_DIR": str(root / "run"),
            }

            class ImmediateTimeoutSelector:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def register(self, *args):
                    return None

                def select(self, timeout=None):
                    return []

            def stalled_version(command, *args, **kwargs):
                return REAL_POPEN(
                    ["/usr/bin/python3", "-c", "import time; time.sleep(30)"],
                    *args,
                    **kwargs,
                )

            with mock.patch(
                "selectors.DefaultSelector", ImmediateTimeoutSelector
            ):
                result = invoke(
                    ["_prepare"], environment,
                    rclone_version=stalled_version,
                )

            self.assertEqual(
                (1, "", "rclone version check failed\n"), result
            )
            self.assertFalse((root / "run/proton-drive-desktop").exists())
            self.assertFalse(
                (root / "data/proton-drive-desktop/files").exists()
            )

    def test_next_service_prepare_rejects_version_drift_without_changing_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "config/rclone").mkdir(parents=True, mode=0o700)
            (root / "data").mkdir(mode=0o700)
            (root / "run").mkdir(mode=0o700)
            config = root / "config/rclone/proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
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

            self.assertEqual(
                (0, "", ""),
                invoke(["_prepare"], environment, opened=opened),
            )
            self.assertEqual(
                (0, "", ""),
                invoke(["_post-stop"], environment, opened=opened),
            )
            private_runtime = root / "run/proton-drive-desktop"
            binding = private_runtime / "binding.json"
            binding_before = binding.read_bytes()
            marker = private_runtime / "mountpoint.json"
            self.assertFalse(marker.exists())
            mount = root / "data/proton-drive-desktop/files"
            mount_before = mount.stat()
            drifted = subprocess.CompletedProcess(
                RCLONE_VERSION_COMMAND, 0, stdout=b"rclone v1.76.0\n"
            )

            result = invoke(
                ["_prepare"], environment, opened=opened,
                rclone_version=drifted,
            )

            self.assertEqual(
                (1, "", "rclone version check failed\n"), result
            )
            self.assertEqual(binding_before, binding.read_bytes())
            self.assertFalse(marker.exists())
            mount_after = mount.stat()
            self.assertEqual(
                (mount_before.st_dev, mount_before.st_ino, mount_before.st_mode),
                (mount_after.st_dev, mount_after.st_ino, mount_after.st_mode),
            )

    def test_prepare_rejects_a_mount_boundary_at_the_managed_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            data_home = root / "data"
            managed_parent = data_home / "proton-drive-desktop"
            config_parent = root / "config/rclone"
            runtime = root / "run"
            managed_parent.mkdir(parents=True, mode=0o700)
            config_parent.mkdir(parents=True, mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            mount = managed_parent / "files"

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                if str(name).startswith("/proc/self/fdinfo/"):
                    descriptor = int(str(name).rsplit("/", 1)[1])
                    target = pathlib.Path(
                        os.readlink(f"/proc/self/fd/{descriptor}")
                    )
                    mount_id = "801" if target == data_home else "802"
                    return io.StringIO(f"mnt_id:\t{mount_id}\n")
                return io.open(name, *args, **kwargs)

            getxattr = mock.Mock(
                side_effect=AssertionError("mountpoint xattr read")
            )
            setxattr = mock.Mock(
                side_effect=AssertionError("mountpoint xattr write")
            )
            removexattr = mock.Mock(
                side_effect=AssertionError("mountpoint xattr removal")
            )
            with mock.patch("os.getxattr", getxattr), mock.patch(
                "os.setxattr", setxattr
            ), mock.patch("os.removexattr", removexattr):
                result = invoke(
                    ["_prepare"],
                    {
                        "HOME": temporary,
                        "XDG_CONFIG_HOME": str(root / "config"),
                        "XDG_DATA_HOME": str(data_home),
                        "XDG_RUNTIME_DIR": str(runtime),
                    },
                    opened=opened,
                )

            self.assertEqual(
                (
                    1,
                    "",
                    "managed mountpoint directory crosses a mount boundary\n",
                ),
                result,
            )
            self.assertFalse(mount.exists())
            self.assertFalse(
                (runtime / "proton-drive-desktop/mountpoint.json").exists()
            )
            getxattr.assert_not_called()
            setxattr.assert_not_called()
            removexattr.assert_not_called()

    def test_status_rejects_a_mount_boundary_at_the_managed_parent(self):
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
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(data_home),
                "XDG_RUNTIME_DIR": str(runtime),
            }

            def unmounted_open(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                if str(name).startswith("/proc/self/fdinfo/"):
                    return io.StringIO("mnt_id:\t811\n")
                return io.open(name, *args, **kwargs)

            self.assertEqual(
                (0, "", ""),
                invoke(["_prepare"], environment, opened=unmounted_open),
            )
            mount = data_home / "proton-drive-desktop/files"
            marker = runtime / "proton-drive-desktop/mountpoint.json"
            ownership = json.loads(marker.read_text())
            ownership["mount_id"] = "812"
            marker.write_text(json.dumps(ownership, separators=(",", ":")))
            encoded_mount = str(mount).replace(" ", "\\040")
            mountinfo = (
                f"812 30 0:812 / {encoded_mount} ro,nosuid,nodev - "
                f"fuse.rclone {ownership['mount_tag']} ro\n"
            )

            def active(arguments, **kwargs):
                return subprocess.CompletedProcess(
                    arguments,
                    0,
                    stdout=(
                        "ActiveState=active\nSubState=running\nResult=success\n"
                    ),
                )

            def boundary_open(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO(mountinfo)
                if str(name).startswith("/proc/self/fdinfo/"):
                    descriptor = int(str(name).rsplit("/", 1)[1])
                    target = pathlib.Path(
                        os.readlink(f"/proc/self/fd/{descriptor}")
                    )
                    mount_id = "811" if target == data_home else "813"
                    return io.StringIO(f"mnt_id:\t{mount_id}\n")
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["status"], environment, run=active, opened=boundary_open
            )

            self.assertEqual((1, "inconsistent/foreign state\n", ""), result)
            self.assertEqual(ownership, json.loads(marker.read_text()))

    def test_mount_and_cleanup_preserve_state_across_a_parent_mount_boundary(self):
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
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(data_home),
                "XDG_RUNTIME_DIR": str(runtime),
            }

            def unmounted_open(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                if str(name).startswith("/proc/self/fdinfo/"):
                    return io.StringIO("mnt_id:\t821\n")
                return io.open(name, *args, **kwargs)

            self.assertEqual(
                (0, "", ""),
                invoke(["_prepare"], environment, opened=unmounted_open),
            )
            mount = data_home / "proton-drive-desktop/files"
            marker = runtime / "proton-drive-desktop/mountpoint.json"
            marker_before = marker.read_bytes()
            nonce_before = os.getxattr(
                mount, "user.proton-drive-desktop.identity"
            )

            def boundary_open(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                if str(name).startswith("/proc/self/fdinfo/"):
                    descriptor = int(str(name).rsplit("/", 1)[1])
                    target = pathlib.Path(
                        os.readlink(f"/proc/self/fd/{descriptor}")
                    )
                    mount_id = "821" if target == data_home else "822"
                    return io.StringIO(f"mnt_id:\t{mount_id}\n")
                return io.open(name, *args, **kwargs)

            launch = mock.Mock(
                side_effect=AssertionError("rclone execution reached")
            )
            for command in ("_mount", "_post-stop"):
                with self.subTest(command=command):
                    result = invoke(
                        [command],
                        environment,
                        execve=launch,
                        opened=boundary_open,
                    )
                    self.assertEqual(
                        (
                            1,
                            "",
                            "managed mountpoint directory crosses a mount boundary\n",
                        ),
                        result,
                    )
                    self.assertEqual(marker_before, marker.read_bytes())
                    self.assertEqual(
                        nonce_before,
                        os.getxattr(
                            mount, "user.proton-drive-desktop.identity"
                        ),
                    )
            launch.assert_not_called()

    def test_separate_data_filesystem_is_supported_when_parent_shares_it(self):
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
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(data_home),
                "XDG_RUNTIME_DIR": str(runtime),
            }
            mounted = False

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    if not mounted:
                        return io.StringIO("")
                    marker = json.loads(
                        (
                            runtime
                            / "proton-drive-desktop/mountpoint.json"
                        ).read_text()
                    )
                    encoded_mount = str(
                        data_home / "proton-drive-desktop/files"
                    ).replace(" ", "\\040")
                    return io.StringIO(
                        f"831 30 0:831 / {encoded_mount} ro,nosuid,nodev - "
                        f"fuse.rclone {marker['mount_tag']} ro\n"
                    )
                if str(name).startswith("/proc/self/fdinfo/"):
                    descriptor = int(str(name).rsplit("/", 1)[1])
                    target = pathlib.Path(
                        os.readlink(f"/proc/self/fd/{descriptor}")
                    )
                    mount_id = "830" if data_home in (target, *target.parents) else "700"
                    return io.StringIO(f"mnt_id:\t{mount_id}\n")
                return io.open(name, *args, **kwargs)

            self.assertEqual(
                (0, "", ""),
                invoke(["_prepare"], environment, opened=opened),
            )
            mount = data_home / "proton-drive-desktop/files"
            marker = runtime / "proton-drive-desktop/mountpoint.json"
            launch = mock.Mock(side_effect=SystemExit(0))
            self.assertEqual(
                (0, "", ""),
                invoke(
                    ["_mount"], environment, execve=launch, opened=opened
                ),
            )
            launch.assert_called_once()

            ownership = json.loads(marker.read_text())
            ownership["mount_id"] = "831"
            marker.write_text(json.dumps(ownership, separators=(",", ":")))
            mounted = True

            def active(arguments, **kwargs):
                return subprocess.CompletedProcess(
                    arguments,
                    0,
                    stdout=(
                        "ActiveState=active\nSubState=running\nResult=success\n"
                    ),
                )

            self.assertEqual(
                (0, "ready\n", ""),
                invoke(
                    ["status"], environment, run=active, opened=opened
                ),
            )
            mounted = False
            self.assertEqual(
                (0, "", ""),
                invoke(["_post-stop"], environment, opened=opened),
            )
            self.assertTrue(mount.is_dir())
            self.assertFalse(marker.exists())

    def test_unknown_manager_state_is_reported_and_preserved_by_stop(self):
        responses = {
            "unavailable": subprocess.CompletedProcess(
                ["systemctl"], 1, stdout=""
            ),
            "incomplete": subprocess.CompletedProcess(
                ["systemctl"], 0, stdout="ActiveState=active\n"
            ),
            "malformed": subprocess.CompletedProcess(
                ["systemctl"],
                0,
                stdout=(
                    "ActiveState active\nSubState=running\nResult=success\n"
                ),
            ),
        }
        for case, response in responses.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                data_home = root / "data"
                runtime = root / "run/proton-drive-desktop"
                mount = data_home / "proton-drive-desktop/files"
                mount.mkdir(parents=True, mode=0o700)
                runtime.mkdir(parents=True, mode=0o700)
                publish_mount_record(mount, runtime, "841", True)
                marker = runtime / "mountpoint.json"
                marker_before = marker.read_bytes()
                nonce_before = os.getxattr(
                    mount, "user.proton-drive-desktop.identity"
                )
                encoded_mount = str(mount).replace(" ", "\\040")
                mountinfo = (
                    f"841 30 0:841 / {encoded_mount} ro,nosuid,nodev - "
                    f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
                )
                calls = []

                def external(arguments, **kwargs):
                    calls.append(arguments)
                    if arguments[0] != "/usr/bin/systemctl" or arguments[2] != "show":
                        return subprocess.CompletedProcess(arguments, 0)
                    return subprocess.CompletedProcess(
                        arguments, response.returncode, stdout=response.stdout
                    )

                def opened(name, *args, **kwargs):
                    if name == "/proc/self/mountinfo":
                        return io.StringIO(mountinfo)
                    if str(name).startswith("/proc/self/fdinfo/"):
                        return io.StringIO("mnt_id:\t840\n")
                    return io.open(name, *args, **kwargs)

                environment = {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(data_home),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                }
                self.assertEqual(
                    (1, "unknown\n", ""),
                    invoke(
                        ["status"], environment, run=external, opened=opened
                    ),
                )
                calls.clear()
                self.assertEqual(
                    (1, "", "service state is unknown; preserving it\n"),
                    invoke(
                        ["stop"], environment, run=external, opened=opened
                    ),
                )
                self.assertTrue(calls)
                self.assertTrue(
                    all(
                        call[0] == "/usr/bin/systemctl" and call[2] == "show"
                        for call in calls
                    )
                )
                self.assertEqual(marker_before, marker.read_bytes())
                self.assertEqual(
                    nonce_before,
                    os.getxattr(
                        mount, "user.proton-drive-desktop.identity"
                    ),
                )

    def test_stop_recovers_from_unknown_to_valid_active_and_failed_states(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            data_home = root / "data"
            runtime = root / "run/proton-drive-desktop"
            mount = data_home / "proton-drive-desktop/files"
            mount.mkdir(parents=True, mode=0o700)
            runtime.mkdir(parents=True, mode=0o700)
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(data_home),
                "XDG_RUNTIME_DIR": str(root / "run"),
            }
            encoded_mount = str(mount).replace(" ", "\\040")
            manager_state = "unknown"
            mounted = True
            events = []

            def external(arguments, **kwargs):
                nonlocal manager_state, mounted
                if arguments[0] == "/usr/bin/fusermount3":
                    events.append("unmount")
                    mounted = False
                    return subprocess.CompletedProcess(arguments, 0)
                action = arguments[2]
                if action == "show":
                    events.append(f"show-{manager_state}")
                    if manager_state == "unknown":
                        return subprocess.CompletedProcess(
                            arguments, 0, stdout="ActiveState=active\n"
                        )
                    substate = {
                        "active": "running",
                        "failed": "failed",
                        "inactive": "dead",
                    }[manager_state]
                    return subprocess.CompletedProcess(
                        arguments,
                        0,
                        stdout=(
                            f"ActiveState={manager_state}\n"
                            f"SubState={substate}\nResult=success\n"
                        ),
                    )
                if action == "stop":
                    events.append("stop")
                    if manager_state != "failed":
                        manager_state = "inactive"
                    return subprocess.CompletedProcess(arguments, 0)
                if action == "reset-failed":
                    events.append("reset-failed")
                    manager_state = "inactive"
                    return subprocess.CompletedProcess(arguments, 0)
                raise AssertionError(arguments)

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    if mounted:
                        return io.StringIO(
                            f"851 30 0:851 / {encoded_mount} ro,nosuid,nodev - "
                            f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
                        )
                    return io.StringIO("")
                if str(name).startswith("/proc/self/fdinfo/"):
                    return io.StringIO("mnt_id:\t850\n")
                return io.open(name, *args, **kwargs)

            publish_mount_record(mount, runtime, "851", True)
            self.assertEqual(
                (1, "unknown\n", ""),
                invoke(
                    ["status"], environment, run=external, opened=opened
                ),
            )
            self.assertFalse(any(event in {"unmount", "stop"} for event in events))

            manager_state = "active"
            events.clear()
            self.assertEqual(
                (0, "stopped\n", ""),
                invoke(["stop"], environment, run=external, opened=opened),
            )
            self.assertLess(events.index("unmount"), events.index("stop"))
            self.assertFalse((runtime / "mountpoint.json").exists())

            publish_mount_record(mount, runtime, "852", True)
            manager_state = "unknown"
            mounted = False
            events.clear()
            self.assertEqual(
                (1, "unknown\n", ""),
                invoke(
                    ["status"], environment, run=external, opened=opened
                ),
            )
            self.assertFalse(any(event in {"stop", "reset-failed"} for event in events))

            manager_state = "failed"
            events.clear()
            self.assertEqual(
                (0, "stopped\n", ""),
                invoke(["stop"], environment, run=external, opened=opened),
            )
            self.assertIn("stop", events)
            self.assertIn("reset-failed", events)
            self.assertNotIn("unmount", events)
            self.assertFalse((runtime / "mountpoint.json").exists())

    def test_prepare_rejects_world_writable_transitive_mount_ancestor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            unsafe = root / "unsafe"
            data_home = unsafe / "private/data"
            config_parent = root / "config/rclone"
            runtime = root / "run"
            data_home.mkdir(parents=True, mode=0o700)
            config_parent.mkdir(parents=True, mode=0o700)
            runtime.mkdir(mode=0o700)
            unsafe.chmod(0o777)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["_prepare"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(data_home),
                    "XDG_RUNTIME_DIR": str(runtime),
                },
                opened=opened,
            )

            self.assertEqual(
                (1, "", "unsafe managed mountpoint ancestor\n"), result
            )
            self.assertFalse(
                (runtime / "proton-drive-desktop/mountpoint.json").exists()
            )
            self.assertFalse((data_home / "proton-drive-desktop").exists())

    def test_prepare_rejects_group_writable_transitive_mount_ancestor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            unsafe = root / "unsafe"
            data_home = unsafe / "private/data"
            config_parent = root / "config/rclone"
            runtime = root / "run"
            data_home.mkdir(parents=True, mode=0o700)
            config_parent.mkdir(parents=True, mode=0o700)
            runtime.mkdir(mode=0o700)
            unsafe.chmod(0o770)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["_prepare"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(data_home),
                    "XDG_RUNTIME_DIR": str(runtime),
                },
                opened=opened,
            )

            self.assertEqual(
                (1, "", "unsafe managed mountpoint ancestor\n"), result
            )
            self.assertFalse(
                (runtime / "proton-drive-desktop/mountpoint.json").exists()
            )
            self.assertFalse((data_home / "proton-drive-desktop").exists())

    def test_prepare_rejects_world_writable_transitive_config_ancestor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            unsafe = root / "unsafe"
            config_parent = unsafe / "private/config/rclone"
            data_home = root / "data"
            runtime = root / "run"
            config_parent.mkdir(parents=True, mode=0o700)
            data_home.mkdir(mode=0o700)
            runtime.mkdir(mode=0o700)
            unsafe.chmod(0o777)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["_prepare"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(unsafe / "private/config"),
                    "XDG_DATA_HOME": str(data_home),
                    "XDG_RUNTIME_DIR": str(runtime),
                },
                opened=opened,
            )

            self.assertEqual(
                (1, "", "unsafe rclone config ancestor\n"), result
            )
            self.assertFalse(
                (runtime / "proton-drive-desktop/mountpoint.json").exists()
            )
            self.assertFalse((data_home / "proton-drive-desktop").exists())

    def test_prepare_rejects_symlinked_transitive_config_ancestor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            actual = root / "actual/private/config"
            linked = root / "linked"
            config_parent = linked / "private/config/rclone"
            data_home = root / "data"
            runtime = root / "run"
            actual.mkdir(parents=True, mode=0o700)
            linked.symlink_to(root / "actual", target_is_directory=True)
            (actual / "rclone").mkdir(mode=0o700)
            data_home.mkdir(mode=0o700)
            runtime.mkdir(mode=0o700)
            config = actual / "rclone/proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            result = invoke(
                ["_prepare"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(linked / "private/config"),
                    "XDG_DATA_HOME": str(data_home),
                    "XDG_RUNTIME_DIR": str(runtime),
                },
                opened=opened,
            )

            self.assertEqual(
                (1, "", "unsafe rclone config ancestor\n"), result
            )
            self.assertFalse(
                (runtime / "proton-drive-desktop/mountpoint.json").exists()
            )
            self.assertFalse((data_home / "proton-drive-desktop").exists())

    def test_prepare_rejects_symlinked_transitive_mount_ancestor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            actual = root / "actual/private/data"
            linked = root / "linked"
            data_home = linked / "private/data"
            config_parent = root / "config/rclone"
            runtime = root / "run"
            actual.mkdir(parents=True, mode=0o700)
            linked.symlink_to(root / "actual", target_is_directory=True)
            config_parent.mkdir(parents=True, mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            descriptors_before = len(os.listdir("/proc/self/fd"))
            result = invoke(
                ["_prepare"],
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(data_home),
                    "XDG_RUNTIME_DIR": str(runtime),
                },
                opened=opened,
            )

            self.assertEqual(
                (1, "", "unsafe managed mountpoint ancestor\n"), result
            )
            self.assertEqual(descriptors_before, len(os.listdir("/proc/self/fd")))
            self.assertFalse(
                (runtime / "proton-drive-desktop/mountpoint.json").exists()
            )
            self.assertFalse((actual / "proton-drive-desktop").exists())

    def test_mount_rejects_ancestor_replaced_after_preparation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            data_home = root / "data"
            config_parent = root / "config/rclone"
            runtime = root / "run"
            data_home.mkdir(mode=0o700)
            config_parent.mkdir(parents=True, mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
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
            marker_before = marker.read_bytes()
            original = root / "data-original"
            data_home.rename(original)
            data_home.symlink_to(original, target_is_directory=True)
            launch = mock.Mock()

            result = invoke(
                ["_mount"], environment, execve=launch, opened=opened
            )

            self.assertEqual(
                (1, "", "unsafe managed mountpoint ancestor\n"), result
            )
            launch.assert_not_called()
            self.assertEqual(marker_before, marker.read_bytes())
            self.assertTrue((original / "proton-drive-desktop/files").is_dir())

    def test_mount_anchors_config_parent_across_late_ancestor_replacement(self):
        def exercise_handoff():
            with tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                config_home = root / "config"
                config_parent = config_home / "rclone"
                data_home = root / "data"
                runtime = root / "run"
                config_parent.mkdir(parents=True, mode=0o700)
                data_home.mkdir(mode=0o700)
                runtime.mkdir(mode=0o700)
                config = config_parent / "proton-drive.conf"
                config.write_text("trusted-encrypted-placeholder")
                config.chmod(0o600)
                environment = {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(config_home),
                    "XDG_DATA_HOME": str(data_home),
                    "XDG_RUNTIME_DIR": str(runtime),
                }

                def opened(name, *args, **kwargs):
                    if name == "/proc/self/mountinfo":
                        return io.StringIO("")
                    return io.open(name, *args, **kwargs)

                self.assertEqual(
                    (0, "", ""),
                    invoke(["_prepare"], environment, opened=opened),
                )
                observed = {}

                def replace_before_rclone_opens_config(
                    path, arguments, exec_environment
                ):
                    original = root / "trusted-config"
                    root.chmod(0o777)
                    config_home.rename(original)
                    replacement_parent = config_home / "rclone"
                    replacement_parent.mkdir(parents=True, mode=0o700)
                    replacement = replacement_parent / "proton-drive.conf"
                    replacement.write_text("attacker-controlled-placeholder")
                    replacement.chmod(0o600)
                    config_argument = arguments[arguments.index("--config") + 1]
                    descriptor = int(pathlib.Path(config_argument).parts[-2])
                    observed["argument"] = config_argument
                    observed["inheritable"] = os.get_inheritable(descriptor)
                    observed["contents"] = pathlib.Path(config_argument).read_text()
                    raise SystemExit(0)

                result = invoke(
                    ["_mount"],
                    environment,
                    execve=replace_before_rclone_opens_config,
                    opened=opened,
                )
                return result, observed

        result, observed = exercise_handoff()
        self.assertEqual((0, "", ""), result)
        self.assertRegex(
            observed["argument"],
            r"\A/proc/self/fd/[0-9]+/proton-drive\.conf\Z",
        )
        self.assertEqual(
            "trusted-encrypted-placeholder", observed["contents"]
        )
        self.assertTrue(observed["inheritable"])

        with mock.patch("os.set_inheritable", return_value=None):
            mutated_result, mutated = exercise_handoff()
        self.assertEqual((0, "", ""), mutated_result)
        self.assertFalse(mutated["inheritable"])

    def test_mount_rechecks_data_home_owner_and_preserves_prepared_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            data_home = root / "data with spaces"
            config_parent = root / "config/rclone"
            runtime = root / "run"
            data_home.mkdir(mode=0o700)
            config_parent.mkdir(parents=True, mode=0o700)
            runtime.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
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
            marker_before = marker.read_bytes()
            mount = data_home / "proton-drive-desktop/files"
            nonce_before = os.getxattr(
                mount, "user.proton-drive-desktop.identity"
            )
            unrelated = data_home / "unrelated-existing-state"
            unrelated.write_text("preserve me\n")
            launch = mock.Mock()

            def changed_owner(descriptor):
                information = REAL_FSTAT(descriptor)
                try:
                    descriptor_path = pathlib.Path(
                        os.readlink(f"/proc/self/fd/{descriptor}")
                    )
                except OSError:
                    return information
                if descriptor_path == data_home:
                    return with_uid(information, os.getuid() + 1)
                if descriptor_path == pathlib.Path(tempfile.gettempdir()).resolve():
                    return with_mode(information, 0o755)
                return information

            with mock.patch("os.fstat", side_effect=changed_owner):
                result = invoke(
                    ["_mount"], environment, execve=launch, opened=opened
                )

            self.assertEqual((1, "", "unsafe XDG data directory\n"), result)
            launch.assert_not_called()
            self.assertEqual(marker_before, marker.read_bytes())
            self.assertEqual(
                nonce_before,
                os.getxattr(mount, "user.proton-drive-desktop.identity"),
            )
            self.assertEqual("preserve me\n", unrelated.read_text())

    def test_owned_descriptor_chain_handles_root_and_space_paths(self):
        module = runpy.run_path(str(PROGRAM), run_name="proton_drive_test_module")
        with tempfile.TemporaryDirectory() as temporary:
            space_path = pathlib.Path(temporary) / "owned directory with spaces"
            space_path.mkdir(mode=0o700)

            def synthetic_root_owner(descriptor):
                information = REAL_FSTAT(descriptor)
                try:
                    descriptor_path = pathlib.Path(
                        os.readlink(f"/proc/self/fd/{descriptor}")
                    )
                except OSError:
                    return information
                if descriptor_path == pathlib.Path("/"):
                    return with_uid(information, os.getuid())
                if descriptor_path == pathlib.Path(tempfile.gettempdir()).resolve():
                    return with_mode(information, 0o755)
                return information

            with mock.patch("os.fstat", side_effect=synthetic_root_owner):
                for path in (pathlib.Path("/"), space_path):
                    with self.subTest(path=path):
                        descriptor = module["open_safe_directory_chain"](
                            path,
                            "managed mountpoint ancestor",
                            owned_paths={path: "XDG data directory"},
                        )
                        try:
                            self.assertTrue(stat.S_ISDIR(os.fstat(descriptor).st_mode))
                        finally:
                            os.close(descriptor)

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
                "mount_tag": TEST_MOUNT_TAG,
                "mount_id": "41",
            }))
            encoded_mount = str(mount).replace(" ", "\\040")
            valid = (
                f"41 30 0:42 / {encoded_mount} ro,nosuid,nodev - "
                f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
            )
            foreign = (
                f"41 30 0:42 / {encoded_mount} rw,nosuid,nodev - "
                "fuse.rclone somebody-else: rw\n"
            )
            malformed_tag = (
                f"41 30 0:42 / {encoded_mount} ro,nosuid,nodev - "
                "fuse.rclone proton-drive-desktop-too-short ro\n"
            )
            rw_mount_options = (
                f"41 30 0:42 / {encoded_mount} ro,rw,nosuid,nodev - "
                f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
            )
            rw_super_options = (
                f"41 30 0:42 / {encoded_mount} ro,nosuid,nodev - "
                f"fuse.rclone {TEST_MOUNT_TAG} ro,rw\n"
            )
            cases = (
                ("active", "running", valid, 0, "ready\n"),
                ("activating", "start-post", valid, 3, "starting\n"),
                ("deactivating", "stop-sigterm", valid, 3, "stopping\n"),
                ("inactive", "dead", "", 1, "inconsistent/foreign state\n"),
                ("failed", "failed", "", 1, "failed\n"),
                ("active", "running", foreign, 1, "inconsistent/foreign state\n"),
                ("active", "running", malformed_tag, 1, "inconsistent/foreign state\n"),
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
                        2 if active == "active" and wanted_code != 0 else 1
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
                "mount_tag": TEST_MOUNT_TAG,
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
                        f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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

    def test_reused_mount_id_with_old_source_is_not_owned_by_public_commands(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            mount.mkdir(parents=True, mode=0o700)
            runtime.mkdir(parents=True, mode=0o700)
            information = mount.stat()
            nonce = "46" * 32
            os.setxattr(
                mount,
                "user.proton-drive-desktop.identity",
                nonce.encode("ascii"),
            )
            marker = runtime / "mountpoint.json"
            marker.write_text(json.dumps({
                "mount": str(mount),
                "device": information.st_dev,
                "inode": information.st_ino,
                "created": False,
                "nonce": nonce,
                "mount_tag": "proton-drive-desktop-" + "46" * 32,
                "mount_id": "46",
            }))
            encoded_mount = str(mount).replace(" ", "\\040")
            calls = []

            def external(command, **kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="ActiveState=active\nSubState=running\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO(
                        f"46 30 0:46 / {encoded_mount} ro,nosuid,nodev - "
                        "fuse.rclone proton-dolphin: ro\n"
                    )
                return io.open(name, *args, **kwargs)

            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_RUNTIME_DIR": str(root / "run"),
            }
            cases = (
                ("status", (1, "inconsistent/foreign state\n", "")),
                ("start", (1, "", "inconsistent/foreign state\n")),
                ("stop", (1, "", "mounted instance changed; preserving it\n")),
            )

            for command, expected in cases:
                with self.subTest(command=command):
                    self.assertEqual(
                        expected,
                        invoke([command], environment, run=external, opened=opened),
                    )

            self.assertFalse(any(call[0] == "/usr/bin/fusermount3" for call in calls))
            self.assertFalse(
                any(call[0] == "/usr/bin/systemctl" and call[2] != "show" for call in calls)
            )
            self.assertTrue(mount.is_dir())
            self.assertTrue(marker.is_file())

    def test_old_format_record_preserves_an_active_mount(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            mount.mkdir(parents=True, mode=0o700)
            runtime.mkdir(parents=True, mode=0o700)
            information = mount.stat()
            nonce = "48" * 32
            os.setxattr(
                mount,
                "user.proton-drive-desktop.identity",
                nonce.encode("ascii"),
            )
            marker = runtime / "mountpoint.json"
            marker.write_text(json.dumps({
                "mount": str(mount),
                "device": information.st_dev,
                "inode": information.st_ino,
                "created": False,
                "nonce": nonce,
                "mount_id": "48",
            }))
            marker_before = marker.read_bytes()
            encoded_mount = str(mount).replace(" ", "\\040")
            calls = []

            def external(command, **kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="ActiveState=active\nSubState=running\nResult=success\n",
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO(
                        f"48 30 0:48 / {encoded_mount} ro,nosuid,nodev - "
                        "fuse.rclone proton-dolphin: ro\n"
                    )
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
                (1, "", "mount is not owned by this session\n"), result
            )
            self.assertFalse(any(call[0] == "/usr/bin/fusermount3" for call in calls))
            self.assertTrue(mount.is_dir())
            self.assertEqual(marker_before, marker.read_bytes())

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
                    "mount_tag": TEST_MOUNT_TAG,
                }
                if command != "_verify-mount":
                    ownership["mount_id"] = "44"
                marker = runtime / "mountpoint.json"
                marker.write_text(json.dumps(ownership, separators=(",", ":")))
                marker_before = marker.read_bytes()
                encoded_mount = str(mount).replace(" ", "\\040")
                mountinfo = (
                    f"44 30 0:44 / {encoded_mount} ro,nosuid,nodev - "
                    f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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

    def test_unsupported_records_cannot_authorize_an_active_mount(self):
        command_cases = (
            ("status", (1, "inconsistent/foreign state\n", "")),
            ("start", (1, "", "inconsistent/foreign state\n")),
            ("open", (1, "", "inconsistent/foreign state\n")),
            ("stop", (1, "", "mount is not owned by this session\n")),
            ("_verify-mount", (
                1, "", "mountpoint ownership record is invalid\n",
            )),
        )
        cases = (
            (record_kind, command, expected)
            for record_kind in ("extra-version", "unsupported-known-fields")
            for command, expected in command_cases
        )
        for record_kind, command, expected in cases:
            with self.subTest(
                record_kind=record_kind, command=command
            ), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                mount = root / "data/proton-drive-desktop/files"
                runtime = root / "run/proton-drive-desktop"
                mount.mkdir(parents=True, mode=0o700)
                runtime.mkdir(parents=True, mode=0o700)
                information = mount.stat()
                nonce = "49" * 32
                os.setxattr(
                    mount,
                    "user.proton-drive-desktop.identity",
                    nonce.encode("ascii"),
                )
                os.setxattr(mount, "user.keep", b"preserve this xattr")
                marker = runtime / "mountpoint.json"
                ownership = {
                    "mount": str(mount),
                    "device": information.st_dev,
                    "inode": information.st_ino,
                    "created": False,
                    "nonce": nonce,
                }
                if record_kind == "extra-version":
                    ownership.update({
                        "mount_tag": TEST_MOUNT_TAG,
                        "mount_id": "49",
                        "version": 2,
                    })
                else:
                    ownership["mount_id"] = "49"
                marker.write_text(json.dumps(ownership, separators=(",", ":")))
                marker_before = marker.read_bytes()
                directory_before = mount.stat()
                encoded_mount = str(mount).replace(" ", "\\040")
                mountinfo = (
                    f"49 30 0:49 / {encoded_mount} ro,nosuid,nodev - "
                    f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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
                result = invoke(
                    [command],
                    environment,
                    run=external,
                    popen=launch,
                    opened=opened,
                )

                self.assertEqual(expected, result)
                self.assertEqual(marker_before, marker.read_bytes())
                directory_after = mount.stat()
                self.assertEqual(
                    (directory_before.st_dev, directory_before.st_ino,
                     directory_before.st_mode),
                    (directory_after.st_dev, directory_after.st_ino,
                     directory_after.st_mode),
                )
                self.assertEqual([], list(mount.iterdir()))
                self.assertEqual(
                    nonce.encode("ascii"),
                    os.getxattr(mount, "user.proton-drive-desktop.identity"),
                )
                self.assertEqual(
                    b"preserve this xattr", os.getxattr(mount, "user.keep")
                )
                self.assertFalse(
                    any(action[0] == "/usr/bin/fusermount3" for action in actions)
                )
                self.assertFalse(
                    any(
                        action[0] == "/usr/bin/systemctl" and action[2] != "show"
                        for action in actions
                    )
                )
                self.assertFalse(
                    any(action[0] == "/usr/bin/dolphin" for action in actions)
                )

    def test_unsupported_records_cannot_authorize_unmounted_actions(self):
        commands = (
            "status", "start", "open", "stop",
            "_prepare", "_mount", "_post-stop",
        )
        for record_kind in ("extra-version", "unsupported-known-fields"):
            for command in commands:
                with self.subTest(
                    record_kind=record_kind, command=command
                ), tempfile.TemporaryDirectory() as temporary:
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
                    nonce = "4a" * 32
                    os.setxattr(
                        mount,
                        "user.proton-drive-desktop.identity",
                        nonce.encode("ascii"),
                    )
                    os.setxattr(mount, "user.keep", b"preserve this xattr")
                    ownership = {
                        "mount": str(mount),
                        "device": information.st_dev,
                        "inode": information.st_ino,
                        "created": False,
                        "nonce": nonce,
                    }
                    if record_kind == "extra-version":
                        ownership.update({
                            "mount_tag": TEST_MOUNT_TAG,
                            "version": 2,
                        })
                    else:
                        ownership["mount_id"] = "74"
                    marker = runtime / "mountpoint.json"
                    marker.write_text(json.dumps(ownership, separators=(",", ":")))
                    marker_before = marker.read_bytes()
                    directory_before = mount.stat()
                    actions = []

                    def external(arguments, **kwargs):
                        actions.append(arguments)
                        if (
                            arguments[0] == "/usr/bin/systemctl"
                            and arguments[2] == "show"
                        ):
                            return subprocess.CompletedProcess(
                                arguments,
                                0,
                                stdout=(
                                    "ActiveState=inactive\nSubState=dead\n"
                                    "Result=success\n"
                                ),
                            )
                        return subprocess.CompletedProcess(arguments, 0)

                    def opened(name, *args, **kwargs):
                        if name == "/proc/self/mountinfo":
                            return io.StringIO("")
                        return io.open(name, *args, **kwargs)

                    def launch(arguments, *args, **kwargs):
                        actions.append(arguments)
                        return mock.Mock()

                    environment = {
                        "HOME": temporary,
                        "XDG_CONFIG_HOME": str(root / "config"),
                        "XDG_DATA_HOME": str(root / "data"),
                        "XDG_RUNTIME_DIR": str(root / "run"),
                    }
                    result = invoke(
                        [command],
                        environment,
                        run=external,
                        popen=launch,
                        execve=launch,
                        opened=opened,
                    )

                    self.assertEqual(
                        (1, "inconsistent/foreign state\n", "")
                        if command == "status"
                        else (1, "", "mountpoint ownership record is invalid\n"),
                        result,
                    )
                    self.assertEqual(marker_before, marker.read_bytes())
                    directory_after = mount.stat()
                    self.assertEqual(
                        (directory_before.st_dev, directory_before.st_ino,
                         directory_before.st_mode),
                        (directory_after.st_dev, directory_after.st_ino,
                         directory_after.st_mode),
                    )
                    self.assertEqual([], list(mount.iterdir()))
                    self.assertEqual(
                        nonce.encode("ascii"),
                        os.getxattr(
                            mount, "user.proton-drive-desktop.identity"
                        ),
                    )
                    self.assertEqual(
                        b"preserve this xattr", os.getxattr(mount, "user.keep")
                    )
                    self.assertFalse(
                        any(
                            action[0] == "/usr/bin/systemctl"
                            and action[2] != "show"
                            for action in actions
                        )
                    )
                    self.assertFalse(
                        any(
                            action[0] in {
                                "/usr/bin/dolphin", "/usr/bin/fusermount3",
                                "/usr/bin/rclone",
                            }
                            for action in actions
                        )
                    )

    def test_status_classifies_malformed_retained_records_without_mutation(self):
        malformed = ("{", "null", "42", "[]", '{"unsupported": true}')
        for filename in ("mountpoint.json", "mountpoint-phase.json"):
            for contents in malformed:
                for late_arrival in (False, True):
                    with self.subTest(
                        filename=filename, contents=contents,
                        late_arrival=late_arrival,
                    ), tempfile.TemporaryDirectory() as temporary:
                        root = pathlib.Path(temporary)
                        mount = root / "data/proton-drive-desktop/files"
                        runtime = root / "run/proton-drive-desktop"
                        mount.mkdir(parents=True, mode=0o700)
                        runtime.mkdir(parents=True, mode=0o700)
                        os.setxattr(mount, "user.keep", b"preserve")
                        before = mount.stat()
                        record = runtime / filename
                        if not late_arrival:
                            record.write_text(contents)
                        reads = 0
                        actions = []

                        def external(arguments, **kwargs):
                            actions.append(arguments)
                            self.assertEqual(
                                ["/usr/bin/systemctl", "--user", "show"],
                                arguments[:3],
                            )
                            return subprocess.CompletedProcess(
                                arguments, 0,
                                stdout="ActiveState=inactive\nSubState=dead\n"
                                       "Result=success\n",
                            )

                        def opened(name, *args, **kwargs):
                            nonlocal reads
                            if name == "/proc/self/mountinfo":
                                return io.StringIO("")
                            if pathlib.Path(name) == record:
                                reads += 1
                                if late_arrival and reads == 2:
                                    record.write_text(contents)
                            return io.open(name, *args, **kwargs)

                        def unexpected_process(*args, **kwargs):
                            self.fail("status must not launch a process")

                        result = invoke(
                            ["status"],
                            {
                                "HOME": temporary,
                                "XDG_CONFIG_HOME": str(root / "config"),
                                "XDG_DATA_HOME": str(root / "data"),
                                "XDG_RUNTIME_DIR": str(root / "run"),
                            },
                            run=external, opened=opened,
                            popen=unexpected_process,
                            execve=unexpected_process,
                        )
                        self.assertEqual(
                            (1, "inconsistent/foreign state\n", ""), result
                        )
                        self.assertEqual(contents.encode(), record.read_bytes())
                        self.assertEqual([record], list(runtime.iterdir()))
                        self.assertEqual([], list(mount.iterdir()))
                        after = mount.stat()
                        self.assertEqual(
                            (before.st_dev, before.st_ino, before.st_mode),
                            (after.st_dev, after.st_ino, after.st_mode),
                        )
                        self.assertEqual(
                            ["user.keep"], os.listxattr(mount)
                        )
                        self.assertEqual(b"preserve", os.getxattr(mount, "user.keep"))
                        self.assertTrue(actions)
                        if late_arrival:
                            self.assertEqual(2, reads)

    def test_status_rechecks_detachment_and_reports_unfinished_cleanup(self):
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

            self.assertEqual((1, "inconsistent/foreign state\n", ""), result)
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
                    f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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

    def test_no_record_stopped_state_rejects_unexpected_reserved_targets(self):
        for mutation in ("identity", "contents", "symlink", "regular-file"):
            for command in ("status", "stop", "_post-stop"):
                with self.subTest(
                    mutation=mutation, command=command
                ), tempfile.TemporaryDirectory() as temporary:
                    root = pathlib.Path(temporary)
                    data_home = root / "data"
                    mount = data_home / "proton-drive-desktop/files"
                    runtime = root / "run"
                    mount.parent.mkdir(parents=True, mode=0o700)
                    runtime.mkdir(mode=0o700)
                    if mutation == "symlink":
                        replacement = root / "replacement"
                        replacement.mkdir(mode=0o700)
                        mount.symlink_to(replacement, target_is_directory=True)
                    elif mutation == "regular-file":
                        mount.write_text("preserve me")
                    else:
                        mount.mkdir(mode=0o700)
                        if mutation == "identity":
                            os.setxattr(
                                mount,
                                "user.proton-drive-desktop.identity",
                                b"91" * 32,
                            )
                        else:
                            (mount / "keep.txt").write_text("preserve me")
                    actions = []

                    def external(arguments, **kwargs):
                        actions.append(arguments)
                        return subprocess.CompletedProcess(
                            arguments,
                            0,
                            stdout=(
                                "ActiveState=inactive\nSubState=dead\n"
                                "Result=success\n"
                            ),
                        )

                    def opened(name, *args, **kwargs):
                        if name == "/proc/self/mountinfo":
                            return io.StringIO("")
                        return io.open(name, *args, **kwargs)

                    result = invoke(
                        [command],
                        {
                            "HOME": temporary,
                            "XDG_CONFIG_HOME": str(root / "config"),
                            "XDG_DATA_HOME": str(data_home),
                            "XDG_RUNTIME_DIR": str(runtime),
                        },
                        run=external,
                        opened=opened,
                    )

                    expected = (
                        (1, "inconsistent/foreign state\n", "")
                        if command == "status"
                        else (1, "", "inconsistent/foreign state\n")
                    )
                    self.assertEqual(expected, result)
                    self.assertFalse(
                        any(action[2] == "stop" for action in actions)
                    )
                    self.assertTrue(mount.exists() or mount.is_symlink())

    def test_no_record_stopped_state_allows_an_empty_unmarked_reserved_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            mount.mkdir(parents=True, mode=0o700)

            def external(arguments, **kwargs):
                return subprocess.CompletedProcess(
                    arguments,
                    0,
                    stdout=(
                        "ActiveState=inactive\nSubState=dead\nResult=success\n"
                    ),
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
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

    def test_stop_recovers_a_stable_managed_active_service_without_a_mount(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            publish_mount_record(mount, runtime, "52", True)
            marker = runtime / "mountpoint.json"
            service = "active"
            events = []

            def external(command, **kwargs):
                nonlocal service
                action = command[2]
                if action == "stop":
                    events.append("stop")
                    service = "inactive"
                    return subprocess.CompletedProcess(command, 0)
                events.append(f"show-{service}")
                sub = "running" if service == "active" else "dead"
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=(
                        f"ActiveState={service}\nSubState={sub}\n"
                        "Result=success\n"
                    ),
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
            self.assertGreaterEqual(events.count("show-active"), 2)
            self.assertEqual(1, events.count("stop"))
            self.assertTrue(mount.is_dir())
            self.assertFalse(marker.exists())

    def test_stop_retries_manager_stop_after_an_owned_detach(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            publish_mount_record(mount, runtime, "53", True)
            marker = runtime / "mountpoint.json"
            marker_before = marker.read_bytes()
            encoded_mount = str(mount).replace(" ", "\\040")
            service = "active"
            mounted = True
            stop_attempts = 0

            def external(command, **kwargs):
                nonlocal service, mounted, stop_attempts
                if command[0] == "/usr/bin/fusermount3":
                    mounted = False
                    return subprocess.CompletedProcess(command, 0)
                action = command[2]
                if action == "stop":
                    stop_attempts += 1
                    if stop_attempts == 1:
                        return subprocess.CompletedProcess(command, 1)
                    service = "inactive"
                    return subprocess.CompletedProcess(command, 0)
                sub = "running" if service == "active" else "dead"
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=(
                        f"ActiveState={service}\nSubState={sub}\n"
                        "Result=success\n"
                    ),
                )

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    entry = (
                        f"53 30 0:53 / {encoded_mount} ro,nosuid,nodev - "
                        f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
                    )
                    return io.StringIO(entry if mounted else "")
                return io.open(name, *args, **kwargs)

            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_RUNTIME_DIR": str(root / "run"),
            }
            self.assertEqual(
                (1, "", "service stop failed\n"),
                invoke(["stop"], environment, run=external, opened=opened),
            )
            self.assertEqual(marker_before, marker.read_bytes())

            self.assertEqual(
                (0, "stopped\n", ""),
                invoke(["stop"], environment, run=external, opened=opened),
            )
            self.assertEqual(2, stop_attempts)
            self.assertTrue(mount.is_dir())
            self.assertFalse(marker.exists())

    def test_active_absent_stop_preserves_invalid_or_new_filesystem_state(self):
        for mutation in ("invalid-record", "contents", "ready", "foreign", "duplicate"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                mount = root / "data/proton-drive-desktop/files"
                runtime = root / "run/proton-drive-desktop"
                publish_mount_record(mount, runtime, "54", True)
                marker = runtime / "mountpoint.json"
                marker_before = marker.read_bytes()
                if mutation == "invalid-record":
                    marker.write_text("{invalid")
                    marker_before = marker.read_bytes()
                encoded_mount = str(mount).replace(" ", "\\040")
                mount_observations = 0
                actions = []

                def external(command, **kwargs):
                    actions.append(command)
                    if command[2] == "stop":
                        raise AssertionError("unsafe recovery stopped the service")
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=(
                            "ActiveState=active\nSubState=running\n"
                            "Result=success\n"
                        ),
                    )

                def opened(name, *args, **kwargs):
                    nonlocal mount_observations
                    if name == "/proc/self/mountinfo":
                        mount_observations += 1
                        if mutation == "contents" and mount_observations == 2:
                            (mount / "keep.txt").write_text("preserve me")
                        if mount_observations <= 2 or mutation in {
                            "invalid-record", "contents",
                        }:
                            return io.StringIO("")
                        ready = (
                            f"54 30 0:54 / {encoded_mount} ro,nosuid,nodev - "
                            f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
                        )
                        if mutation == "ready":
                            return io.StringIO(ready)
                        if mutation == "duplicate":
                            return io.StringIO(
                                ready + ready.replace("54 30", "55 30", 1)
                            )
                        return io.StringIO(
                            f"56 30 0:56 / {encoded_mount} rw,nosuid,nodev - "
                            "fuse.other local: rw\n"
                        )
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

                expected_error = {
                    "invalid-record": "mount is not owned by this session\n",
                    "contents": (
                        "mountpoint contains unexpected local contents\n"
                    ),
                    "ready": (
                        "mount appeared during stop recovery; preserving it\n"
                    ),
                    "foreign": (
                        "mount appeared during stop recovery; preserving it\n"
                    ),
                    "duplicate": (
                        "mount appeared during stop recovery; preserving it\n"
                    ),
                }[mutation]
                self.assertEqual((1, "", expected_error), result)
                self.assertEqual(marker_before, marker.read_bytes())
                self.assertFalse(any(action[2] == "stop" for action in actions))
                if mutation == "contents":
                    self.assertEqual(
                        "preserve me", (mount / "keep.txt").read_text()
                    )

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
                "mount_tag": TEST_MOUNT_TAG,
                "mount_id": "47",
            }))
            encoded_mount = str(mount).replace(" ", "\\040")
            non_root = (
                f"47 30 0:47 /subtree {encoded_mount} ro,nosuid,nodev - "
                f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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
            self.assertEqual("inconsistent/foreign state\n", error)
            self.assertEqual("local data", unexpected.read_text())
            self.assertEqual(0, sum(command[2] == "start" for command in calls))

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
                Popen = staticmethod(synthetic_version_popen)
                TimeoutExpired = subprocess.TimeoutExpired

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
            self.assertTrue(mount.is_dir())
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
                f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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
                "mount_tag": TEST_MOUNT_TAG,
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
                        f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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
                "mount_tag": TEST_MOUNT_TAG,
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
                        f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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
                            f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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
            mount_tag = json.loads(prepared_marker)["mount_tag"]
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
            config_argument = captured["arguments"][
                captured["arguments"].index("--config") + 1
            ]
            self.assertRegex(
                config_argument,
                r"\A/proc/self/fd/[0-9]+/proton-drive\.conf\Z",
            )
            self.assertEqual(
                [
                    "/usr/bin/rclone", "mount", "proton-dolphin:",
                    str(mount),
                    "--devname", mount_tag,
                    "--config", config_argument,
                    "--password-command",
                    f'"{copied_program}" _credential {mount_tag}',
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

            parser_result = root / "password command arguments.json"
            copied_program.write_text(textwrap.dedent(f"""\
                #!/usr/bin/python3
                import json
                import pathlib
                import sys
                pathlib.Path({str(parser_result)!r}).write_text(json.dumps(sys.argv[1:]))
                print("synthetic-password")
            """))
            copied_program.chmod(0o700)
            config.write_text("[synthetic]\ntype = local\n")
            parsed = subprocess.run(
                [
                    "/usr/bin/rclone", "config", "encryption", "set",
                    "--config", str(config),
                    "--password-command",
                    captured["arguments"][
                        captured["arguments"].index("--password-command") + 1
                    ],
                    "--ask-password=false", "--auto-confirm",
                ],
                env={
                    "HOME": temporary,
                    "PATH": "/usr/bin:/bin",
                    "XDG_CACHE_HOME": str(root / "cache"),
                },
                cwd=root,
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(0, parsed.returncode, parsed.stderr)
            self.assertEqual(
                ["_credential", mount_tag],
                json.loads(parser_result.read_text()),
            )
            self.assertTrue(
                config.read_text().startswith(
                    "# Encrypted rclone configuration File\n"
                )
            )

    def test_mount_entrypoint_uses_the_reserved_managed_pathname(self):
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
                (0, "", ""), invoke(["_prepare"], environment, opened=opened)
            )
            captured = {}

            def execute(path, arguments, child_environment):
                captured["target"] = arguments[3]

            result = invoke(
                ["_mount"], environment, execve=execute, opened=opened
            )

            self.assertEqual((1, "", "unable to execute rclone\n"), result)
            self.assertEqual(str(mount), captured["target"])
            self.assertNotIn("/proc/", captured["target"])

    def test_interrupted_launch_retry_refreshes_only_the_mount_tag(self):
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
            first = json.loads(marker.read_text())

            self.assertEqual(
                (0, "", ""), invoke(["_prepare"], environment, opened=opened)
            )
            retried = json.loads(marker.read_text())
            self.assertEqual(first["nonce"], retried["nonce"])
            self.assertNotEqual(first["mount_tag"], retried["mount_tag"])
            self.assertRegex(
                retried["mount_tag"],
                r"\Aproton-drive-desktop-[0-9a-f]{64}\Z",
            )

            launched = mock.Mock(side_effect=SystemExit(0))
            self.assertEqual(
                (0, "", ""),
                invoke(
                    ["_mount"], environment, execve=launched, opened=opened
                ),
            )
            arguments = launched.call_args.args[1]
            self.assertEqual(
                retried["mount_tag"], arguments[arguments.index("--devname") + 1]
            )
            self.assertNotIn(first["mount_tag"], arguments)

    def test_credential_rejects_unbound_or_nonpipe_use_before_external_lookup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            config_parent.mkdir(parents=True, mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            publish_mount_record(mount, runtime, "700", False)
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_RUNTIME_DIR": str(root / "run"),
            }
            no_lookup = mock.Mock(
                side_effect=AssertionError("credential lookup was reached")
            )

            read_pipe, write_pipe = os.pipe()
            self.addCleanup(os.close, read_pipe)
            self.addCleanup(os.close, write_pipe)
            regular = tempfile.TemporaryFile()
            self.addCleanup(regular.close)
            terminal_master, terminal_slave = os.openpty()
            self.addCleanup(os.close, terminal_master)
            self.addCleanup(os.close, terminal_slave)

            cases = (
                ("bare", ["_credential"], write_pipe),
                ("wrong-launch", ["_credential", "proton-drive-desktop-" + "cd" * 32], write_pipe),
                ("regular-file", ["_credential", TEST_MOUNT_TAG], regular.fileno()),
                ("terminal", ["_credential", TEST_MOUNT_TAG], terminal_slave),
            )
            for name, arguments, descriptor in cases:
                with self.subTest(name=name):
                    self.assertEqual(
                        (1, "", "credential unavailable\n"),
                        invoke(
                            arguments,
                            environment,
                            run=no_lookup,
                            popen=no_lookup,
                            stdout_descriptor=descriptor,
                        ),
                    )
            no_lookup.assert_not_called()

    def test_credential_bounds_output_acquisition_and_reaps_producers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            config_parent.mkdir(parents=True, mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            publish_mount_record(mount, runtime, "701", False)
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_RUNTIME_DIR": str(root / "run"),
            }

            def bus_only(command, **kwargs):
                self.assertEqual("/usr/bin/busctl", command[0])
                return subprocess.CompletedProcess(
                    command, 0, stdout='{"type":"s","data":[":1.8"]}\n'
                )

            cases = (
                ("empty", "", (1, "", "credential unavailable\n")),
                ("one", "import os; os.write(1, b'x\\n')", (0, "x\n", "")),
                (
                    "maximum-crlf",
                    "import os; os.write(1, b'x' * 4096 + b'\\r\\n')",
                    (0, "x" * 4096 + "\n", ""),
                ),
                (
                    "maximum-plus-one",
                    "import os; os.write(1, b'x' * 4097 + b'\\r\\n')",
                    (1, "", "credential unavailable\n"),
                ),
                (
                    "multiline",
                    "import os; os.write(1, b'first\\nsecond\\n')",
                    (1, "", "credential unavailable\n"),
                ),
                (
                    "failed",
                    "import os, sys; os.write(1, b'failure-canary'); sys.exit(7)",
                    (1, "", "credential unavailable\n"),
                ),
                (
                    "continuous",
                    "import os\nwhile True: os.write(1, b'x' * 4096)",
                    (1, "", "credential unavailable\n"),
                ),
            )
            for name, producer, expected in cases:
                processes = []

                def synthetic_secret_tool(command, **kwargs):
                    self.assertEqual("/usr/bin/secret-tool", command[0])
                    self.assertIs(subprocess.DEVNULL, kwargs["stdin"])
                    self.assertIs(subprocess.PIPE, kwargs["stdout"])
                    self.assertIs(subprocess.DEVNULL, kwargs["stderr"])
                    self.assertTrue(kwargs["start_new_session"])
                    process = REAL_POPEN(
                        [sys.executable, "-c", producer],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    processes.append(process)
                    return process

                with self.subTest(name=name):
                    result = invoke_credential(
                        environment,
                        run=bus_only,
                        popen=synthetic_secret_tool,
                    )
                    self.assertEqual(expected, result)
                    self.assertEqual(1, len(processes))
                    self.assertIsNotNone(
                        processes[0].poll(), "credential producer survived"
                    )

            timeout_program = root / "helper with timeout"
            timeout_source = PROGRAM.read_text()
            self.assertEqual(
                1, timeout_source.count("CREDENTIAL_TIMEOUT_SECONDS = 10")
            )
            timeout_program.write_text(timeout_source.replace(
                "CREDENTIAL_TIMEOUT_SECONDS = 10",
                "CREDENTIAL_TIMEOUT_SECONDS = 0.05",
            ))
            hung_processes = []

            def hung_secret_tool(command, **kwargs):
                process = REAL_POPEN(
                    [sys.executable, "-c", "import time; time.sleep(60)"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                hung_processes.append(process)
                return process

            self.assertEqual(
                (1, "", "credential unavailable\n"),
                invoke_credential(
                    environment,
                    run=bus_only,
                    popen=hung_secret_tool,
                    program=timeout_program,
                ),
            )
            self.assertEqual(1, len(hung_processes))
            self.assertIsNotNone(
                hung_processes[0].poll(), "timed-out producer survived"
            )

    def test_credential_fixture_drains_a_4096_byte_output_pipe(self):
        if os.sysconf("SC_PAGESIZE") != 4096:
            self.skipTest("a 4096-byte pipe requires 4096-byte Linux pages")
        worker_source = textwrap.dedent('''\
            import fcntl
            import json
            import os
            import pathlib
            import runpy
            import signal
            import sys
            import unittest
            from unittest import mock

            namespace = runpy.run_path(sys.argv[1])
            module = namespace["invoke_credential"].__globals__
            original = module["invoke_credential"]
            real_pipe = os.pipe
            real_popen = module["REAL_POPEN"]
            pid_file = pathlib.Path(sys.argv[2])
            processes = []
            process_records = []
            accepted_maximum = False
            launching = False
            termination_pending = False

            def terminate(signum, frame):
                global termination_pending
                if launching:
                    termination_pending = True
                else:
                    raise SystemExit("credential fixture worker terminated")

            signal.signal(signal.SIGTERM, terminate)

            def producer(*args, **kwargs):
                global launching, termination_pending
                launching = True
                try:
                    process = real_popen(*args, **kwargs)
                    processes.append(process)
                    status = pathlib.Path(f"/proc/{process.pid}/stat").read_text()
                    process_records.append([
                        process.pid, status.split(") ", 1)[1].split()[19]
                    ])
                    pid_file.write_text(json.dumps(process_records))
                    return process
                finally:
                    launching = False
                    if termination_pending:
                        termination_pending = False
                        raise SystemExit("credential fixture worker terminated")

            def credential(*args, **kwargs):
                capacities = []

                def output_pipe():
                    read_descriptor, write_descriptor = real_pipe()
                    if not capacities:
                        try:
                            fcntl.fcntl(write_descriptor, fcntl.F_SETPIPE_SZ, 4096)
                            capacity = fcntl.fcntl(
                                write_descriptor, fcntl.F_GETPIPE_SZ
                            )
                            if capacity != 4096:
                                raise AssertionError(
                                    f"fixture output pipe capacity is {capacity}"
                                )
                            capacities.append(capacity)
                        except BaseException:
                            os.close(write_descriptor)
                            os.close(read_descriptor)
                            raise
                    return read_descriptor, write_descriptor

                with mock.patch("os.pipe", side_effect=output_pipe):
                    outcome = original(*args, **kwargs)
                if outcome == (0, "x" * 4096 + "\\n", ""):
                    global accepted_maximum
                    accepted_maximum = True
                return outcome

            try:
                with mock.patch.dict(module, {
                    "invoke_credential": credential,
                    "REAL_POPEN": producer,
                }):
                    case = namespace["PublicCommandTests"](
                        "test_credential_bounds_output_acquisition_and_reaps_producers"
                    )
                    result = unittest.TestResult()
                    case.run(result)
                if not result.wasSuccessful():
                    raise AssertionError(result.errors + result.failures)
                if not accepted_maximum:
                    raise AssertionError("maximum credential was not captured")
                print(json.dumps({"accepted_maximum": accepted_maximum}))
            finally:
                for process in processes:
                    try:
                        if process.poll() is None:
                            try:
                                os.killpg(process.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                        process.wait(timeout=2)
                    finally:
                        process.stdout.close()
        ''')

        with tempfile.TemporaryDirectory() as temporary:
            pid_file = pathlib.Path(temporary) / "producers.json"
            worker = REAL_POPEN(
                [sys.executable, "-c", worker_source, str(pathlib.Path(__file__).resolve()),
                 str(pid_file)],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                try:
                    output, error = worker.communicate(timeout=15)
                except subprocess.TimeoutExpired:
                    self.fail("credential fixture blocked on a measured 4096-byte pipe")
                self.assertEqual(0, worker.returncode, error)
                self.assertEqual("", error)
                self.assertTrue(json.loads(output)["accepted_maximum"])
            finally:
                try:
                    if worker.poll() is None:
                        worker.terminate()
                        try:
                            worker.communicate(timeout=2)
                        except subprocess.TimeoutExpired:
                            worker.kill()
                            worker.communicate()
                    if pid_file.exists():
                        for process_id, start_time in json.loads(pid_file.read_text()):
                            try:
                                status = pathlib.Path(f"/proc/{process_id}/stat").read_text()
                                if status.split(") ", 1)[1].split()[19] == start_time:
                                    os.killpg(process_id, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            except FileNotFoundError:
                                pass
                finally:
                    worker.stdout.close()
                    worker.stderr.close()

    def test_failed_fixed_producers_terminate_forked_pipe_holders(self):
        worker_source = textwrap.dedent('''\
            import io
            import json
            import os
            import pathlib
            import runpy
            import signal
            import stat
            import subprocess
            import sys
            import tempfile
            from unittest import mock

            case, test_file, program_name, root_name, pid_file_name = sys.argv[1:]
            namespace = runpy.run_path(test_file)
            invoke = namespace["invoke"]
            invoke_credential = namespace["invoke_credential"]
            publish_mount_record = namespace["publish_mount_record"]
            real_fstat = os.fstat
            real_popen = subprocess.Popen
            root = pathlib.Path(root_name)
            pid_file = pathlib.Path(pid_file_name)
            program = pathlib.Path(program_name)
            config_parent = root / "config/rclone"
            config_parent.mkdir(parents=True, mode=0o700)
            (root / "data").mkdir(mode=0o700)
            (root / "run").mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            environment = {
                "HOME": str(root),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_RUNTIME_DIR": str(root / "run"),
            }
            leader_source = """
            import json
            import os
            import pathlib
            import signal
            import sys
            import time

            ready_read, ready_write = os.pipe()
            child = os.fork()
            if child == 0:
                os.close(ready_read)
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                os.write(ready_write, b"1")
                os.close(ready_write)
                while True:
                    time.sleep(60)
            os.close(ready_write)
            os.read(ready_read, 1)
            os.close(ready_read)
            pathlib.Path(sys.argv[1]).write_text(json.dumps({
                "leader": os.getpid(),
                "child": child,
                "pgid": os.getpgrp(),
            }))
            os.write(1, b"synthetic-secret-canary")
            os._exit(0)
            """
            processes = []

            def producer(command, *args, **kwargs):
                process = real_popen(
                    [sys.executable, "-c", leader_source, str(pid_file)],
                    *args,
                    **kwargs,
                )
                processes.append(process)
                return process

            def safe_fstat(descriptor):
                information = real_fstat(descriptor)
                try:
                    path = pathlib.Path(os.readlink(f"/proc/self/fd/{descriptor}"))
                except OSError:
                    return information
                if path == pathlib.Path(tempfile.gettempdir()).resolve():
                    values = list(information)
                    values[0] = stat.S_IFMT(information.st_mode) | 0o755
                    return os.stat_result(values)
                return information

            with mock.patch("os.fstat", side_effect=safe_fstat):
                if case == "credential":
                    publish_mount_record(
                        root / "data/proton-drive-desktop/files",
                        root / "run/proton-drive-desktop",
                        "719",
                        False,
                    )

                    def bus_only(command, **kwargs):
                        return subprocess.CompletedProcess(
                            command,
                            0,
                            stdout='{"type":"s","data":[":1.19"]}\\n',
                        )

                    result = invoke_credential(
                        environment,
                        run=bus_only,
                        popen=producer,
                        program=program,
                    )
                else:
                    def opened(name, *args, **kwargs):
                        if name == "/proc/self/mountinfo":
                            return io.StringIO("")
                        return io.open(name, *args, **kwargs)

                    result = invoke(
                        ["_prepare"],
                        environment,
                        opened=opened,
                        program=program,
                        rclone_version=producer,
                    )
            print(json.dumps({
                "result": result,
                "direct_child_reaped": processes[0].returncode is not None,
            }))
        ''')

        def process_is_live(process_id):
            try:
                status = pathlib.Path(f"/proc/{process_id}/stat").read_text()
            except FileNotFoundError:
                return False
            return status.split(") ", 1)[1].split()[0] != "Z"

        for case, timeout_name, terminate_name, expected in (
            (
                "credential",
                "CREDENTIAL_TIMEOUT_SECONDS = 10",
                "CREDENTIAL_TERMINATE_SECONDS = 1",
                [1, "", "credential unavailable\n"],
            ),
            (
                "version",
                "RCLONE_VERSION_TIMEOUT_SECONDS = 5",
                "RCLONE_VERSION_TERMINATE_SECONDS = 1",
                [1, "", "rclone version check failed\n"],
            ),
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory(
                prefix=f"proton {case} process group "
            ) as temporary:
                root = pathlib.Path(temporary)
                program = root / "proton-drive-desktop"
                source = PROGRAM.read_text()
                self.assertEqual(1, source.count(timeout_name))
                self.assertEqual(1, source.count(terminate_name))
                source = source.replace(timeout_name, timeout_name.replace(
                    timeout_name.rsplit(" ", 1)[-1], "0.05"
                ))
                source = source.replace(terminate_name, terminate_name.replace(
                    terminate_name.rsplit(" ", 1)[-1], "0.05"
                ))
                program.write_text(source)
                worker = root / "isolated-worker.py"
                worker.write_text(worker_source)
                pid_file = root / "producer-processes.json"
                process_information = None
                child_was_live = None
                completed = None
                try:
                    completed = subprocess.run(
                        [
                            sys.executable,
                            str(worker),
                            case,
                            str(pathlib.Path(__file__).resolve()),
                            str(program),
                            str(root / "fixture"),
                            str(pid_file),
                        ],
                        cwd=ROOT,
                        text=True,
                        capture_output=True,
                        timeout=5,
                        check=False,
                    )
                    process_information = json.loads(pid_file.read_text())
                    child_was_live = process_is_live(process_information["child"])
                finally:
                    if process_information is None and pid_file.exists():
                        process_information = json.loads(pid_file.read_text())
                    if (
                        process_information is not None
                        and process_is_live(process_information["child"])
                    ):
                        try:
                            os.killpg(process_information["pgid"], signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        cleanup_deadline = time.monotonic() + 1
                        while (
                            process_is_live(process_information["child"])
                            and time.monotonic() < cleanup_deadline
                        ):
                            time.sleep(0.01)

                self.assertEqual("", completed.stderr)
                self.assertNotIn("synthetic-secret-canary", completed.stdout)
                self.assertEqual(0, completed.returncode)
                report = json.loads(completed.stdout)
                self.assertEqual(expected, report["result"])
                self.assertTrue(report["direct_child_reaped"])
                self.assertFalse(
                    child_was_live,
                    "forked pipe holder survived producer cleanup",
                )

    def test_credential_subprocess_preserves_non_ascii_bytes_under_ascii_stdio(self):
        fixture_secret = "credential-clé-雪".encode("utf-8")
        with synthetic_credential_subprocess(fixture_secret) as (helper, environment):
            completed = subprocess.run(
                [str(helper), "_credential", TEST_MOUNT_TAG],
                env={**environment, "PYTHONIOENCODING": "ascii"},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=False,
            )

        self.assertEqual(0, completed.returncode)
        self.assertEqual(fixture_secret + b"\n", completed.stdout)
        self.assertEqual(b"", completed.stderr)

    def test_credential_subprocess_reports_fixed_closed_pipe_failure(self):
        fixture_secret = b"closed-pipe-fixture-canary"
        with synthetic_credential_subprocess(fixture_secret) as (helper, environment):
            read_descriptor, write_descriptor = os.pipe()
            os.close(read_descriptor)
            try:
                process = subprocess.Popen(
                    [str(helper), "_credential", TEST_MOUNT_TAG],
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=write_descriptor,
                    stderr=subprocess.PIPE,
                )
            finally:
                os.close(write_descriptor)
            try:
                _, error = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise

        self.assertEqual(1, process.returncode)
        self.assertEqual(b"credential unavailable\n", error)
        self.assertNotIn(fixture_secret, error)

    def test_credential_helper_qualifies_kwallet_and_looks_up_exact_config_id(self):
        with tempfile.TemporaryDirectory(prefix="proton config ") as temporary:
            root = pathlib.Path(temporary)
            config_home = root / "config path spelling"
            config_parent = config_home / "rclone"
            config_parent.mkdir(parents=True, mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            publish_mount_record(
                root / "data/proton-drive-desktop/files",
                root / "run/proton-drive-desktop",
                "702",
                False,
            )
            calls = []

            def external(command, **kwargs):
                calls.append((command, kwargs))
                self.assertEqual("/usr/bin/busctl", command[0])
                return subprocess.CompletedProcess(
                    command, 0, stdout='{"type":"s","data":[":1.42"]}\n'
                )

            def secret_tool(command, **kwargs):
                calls.append((command, kwargs))
                return REAL_POPEN(
                    [
                        sys.executable,
                        "-c",
                        "import os; os.write(1, b'bounded-secret\\n')",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )

            code, output, error = invoke_credential(
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(config_home),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                },
                run=external,
                popen=secret_tool,
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
            self.assertIs(subprocess.DEVNULL, calls[2][1]["stdin"])
            self.assertIs(subprocess.PIPE, calls[2][1]["stdout"])
            self.assertIs(subprocess.DEVNULL, calls[2][1]["stderr"])
            self.assertTrue(calls[2][1]["start_new_session"])
            self.assertNotIn("bounded-secret", repr(calls[2][0]))

    def test_credential_accepts_the_current_tag_before_mount_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            config_parent.mkdir(parents=True, mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            publish_mount_record(mount, runtime, "706", False)
            marker = runtime / "mountpoint.json"
            ownership = json.loads(marker.read_text())
            del ownership["mount_id"]
            marker.write_text(json.dumps(ownership, separators=(",", ":")))
            encoded_mount = str(mount).replace(" ", "\\040")

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO(
                        f"706 30 0:706 / {encoded_mount} ro,nosuid,nodev - "
                        f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
                    )
                return io.open(name, *args, **kwargs)

            def bus_only(command, **kwargs):
                return subprocess.CompletedProcess(
                    command, 0, stdout='{"type":"s","data":[":1.8"]}\n'
                )

            def secret_tool(command, **kwargs):
                return REAL_POPEN(
                    [
                        sys.executable,
                        "-c",
                        "import os; os.write(1, b'prepared-launch-secret\\n')",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )

            result = invoke_credential(
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                },
                run=bus_only,
                popen=secret_tool,
                opened=opened,
            )

            self.assertEqual((0, "prepared-launch-secret\n", ""), result)
            self.assertNotIn("mount_id", json.loads(marker.read_text()))

    def test_credential_failures_are_fixed_and_never_emit_external_canaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            config_parent.mkdir(parents=True, mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            publish_mount_record(
                root / "data/proton-drive-desktop/files",
                root / "run/proton-drive-desktop",
                "703",
                False,
            )
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

            no_secret = mock.Mock(
                side_effect=AssertionError("secret lookup was reached")
            )
            code, output, error = invoke_credential(
                environment, run=mismatch, popen=no_secret
            )
            self.assertEqual((1, "", "credential service unavailable\n"), (code, output, error))
            no_secret.assert_not_called()

            def oversized(command, **kwargs):
                self.assertEqual("/usr/bin/busctl", command[0])
                return subprocess.CompletedProcess(
                    command, 0, stdout='{"type":"s","data":[":1.8"]}\n'
                )

            oversized_processes = []

            def oversized_secret(command, **kwargs):
                process = REAL_POPEN(
                    [
                        sys.executable,
                        "-c",
                        "import os; os.write(1, b'SHOULD-NOT-LEAK-93cc' + b'x' * 5000)",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                oversized_processes.append(process)
                return process

            code, output, error = invoke_credential(
                environment, run=oversized, popen=oversized_secret
            )
            self.assertEqual((1, "", "credential unavailable\n"), (code, output, error))
            self.assertNotIn(canary, output + error)
            self.assertIsNotNone(oversized_processes[0].poll())

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
                        invoke_credential(
                            environment, run=malformed, popen=no_secret
                        ),
                    )

    def test_credential_rejects_secret_captured_across_provider_turnover(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            config_parent.mkdir(parents=True, mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            publish_mount_record(
                root / "data/proton-drive-desktop/files",
                root / "run/proton-drive-desktop",
                "704",
                False,
            )
            calls = []
            canary = "TURNOVER-SECRET-MUST-NOT-PRINT-61ee"
            owner_calls = 0

            def external(command, **kwargs):
                nonlocal owner_calls
                calls.append(command)
                owner_calls += 1
                owner = ":1.8" if owner_calls <= 2 else ":1.9"
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=json.dumps({"type": "s", "data": [owner]}),
                )

            def secret_tool(command, **kwargs):
                calls.append(command)
                return REAL_POPEN(
                    [
                        sys.executable,
                        "-c",
                        "import os; os.write(1, b'TURNOVER-SECRET-MUST-NOT-PRINT-61ee\\n')",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )

            result = invoke_credential(
                {
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_RUNTIME_DIR": str(root / "run"),
                },
                run=external,
                popen=secret_tool,
            )

            self.assertEqual(
                (1, "", "credential service unavailable\n"), result
            )
            self.assertNotIn(canary, result[1] + result[2])
            self.assertEqual("/usr/bin/secret-tool", calls[2][0])
            self.assertEqual("org.freedesktop.secrets", calls[3][-1])

    def test_credential_bus_process_failures_are_fixed_and_skip_secret_lookup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_parent = root / "config/rclone"
            config_parent.mkdir(parents=True, mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            publish_mount_record(
                root / "data/proton-drive-desktop/files",
                root / "run/proton-drive-desktop",
                "705",
                False,
            )
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
                    no_secret = mock.Mock(
                        side_effect=AssertionError("secret lookup was reached")
                    )
                    result = invoke_credential(
                        environment, run=external, popen=no_secret
                    )
                    self.assertEqual(
                        (1, "", "credential service unavailable\n"), result
                    )
                    self.assertNotIn(canary, result[1] + result[2])
                    no_secret.assert_not_called()

    @unittest.skipUnless(sys.platform == "linux", "Linux private D-Bus integration")
    def test_bus_owner_uses_supported_call_on_a_disposable_private_bus(self):
        tools = tuple(pathlib.Path("/usr/bin") / name for name in (
            "busctl", "dbus-run-session", "dbus-test-tool", "python3",
        ))
        missing = [str(tool) for tool in tools if not os.access(tool, os.X_OK)]
        self.assertFalse(
            missing, "required private-bus tools are missing: " + ", ".join(missing)
        )

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
                        f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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
            self.assertTrue(mount.is_dir())
            self.assertTrue(config.exists())

    def test_public_stop_waits_for_startup_failure_without_mount_before_cleanup(self):
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
                observed = service
                events.append(f"show-{observed}")
                if observed == "activating":
                    service = "failed"
                sub = "start" if observed == "activating" else "failed"
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=(
                        f"ActiveState={observed}\nSubState={sub}\n"
                        f"Result={'exit-code' if observed == 'failed' else 'success'}\n"
                    ),
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
                    "show-activating", "mount-absent", "mount-absent",
                    "show-failed", "show-failed", "mount-absent", "stop",
                    "show-inactive", "mount-absent", "mount-absent",
                ],
                events,
            )
            self.assertTrue(mount.is_dir())
            self.assertFalse((runtime / "mountpoint.json").exists())

    def test_public_stop_waits_for_startup_then_preserves_a_new_busy_mount(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            publish_mount_record(mount, runtime, "604", True)
            marker = runtime / "mountpoint.json"
            prepared = json.loads(marker.read_text())
            del prepared["mount_id"]
            marker.write_text(json.dumps(prepared, separators=(",", ":")))
            encoded_mount = str(mount).replace(" ", "\\040")
            service = "activating"
            mounted = False
            mount_observations = 0
            events = []

            class AbsentThenMounted(io.StringIO):
                def close(self):
                    nonlocal mounted, service
                    mounted = True
                    service = "active"
                    super().close()

            def external(command, **kwargs):
                if command[0] == "/usr/bin/fusermount3":
                    events.append("unmount-busy")
                    return subprocess.CompletedProcess(command, 1)
                action = command[2]
                if action == "stop":
                    events.append("unsafe-stop")
                    return subprocess.CompletedProcess(command, 0)
                events.append(f"show-{service}")
                sub = "start-post" if service == "activating" else "running"
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=(
                        f"ActiveState={service}\nSubState={sub}\n"
                        "Result=success\n"
                    ),
                )

            def opened(name, *args, **kwargs):
                nonlocal mount_observations
                if name == "/proc/self/mountinfo":
                    mount_observations += 1
                    if mount_observations == 2:
                        return AbsentThenMounted("")
                    entry = (
                        f"604 30 0:604 / {encoded_mount} ro,nosuid,nodev - "
                        f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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

            self.assertEqual(
                (1, "", "mount is busy; close open files and try again\n"), result
            )
            self.assertIn("show-active", events)
            self.assertIn("unmount-busy", events)
            self.assertNotIn("unsafe-stop", events)
            self.assertEqual("active", service)
            self.assertTrue(marker.is_file())
            self.assertEqual("604", json.loads(marker.read_text())["mount_id"])

    def test_public_stop_waits_for_startup_then_unmounts_before_stopping(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            publish_mount_record(mount, runtime, "605", True)
            marker = runtime / "mountpoint.json"
            prepared = json.loads(marker.read_text())
            del prepared["mount_id"]
            marker.write_text(json.dumps(prepared, separators=(",", ":")))
            encoded_mount = str(mount).replace(" ", "\\040")
            service = "activating"
            mounted = False
            mount_observations = 0
            events = []

            class AbsentThenMounted(io.StringIO):
                def close(self):
                    nonlocal mounted, service
                    mounted = True
                    service = "active"
                    super().close()

            def external(command, **kwargs):
                nonlocal mounted, service
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
                sub = "start-post" if service == "activating" else "running"
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=(
                        f"ActiveState={service}\nSubState={sub}\n"
                        "Result=success\n"
                    ),
                )

            def opened(name, *args, **kwargs):
                nonlocal mount_observations
                if name == "/proc/self/mountinfo":
                    mount_observations += 1
                    if mount_observations == 2:
                        return AbsentThenMounted("")
                    entry = (
                        f"605 30 0:605 / {encoded_mount} ro,nosuid,nodev - "
                        f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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
            self.assertNotIn("start", events)
            self.assertEqual("inactive", service)
            self.assertFalse(mounted)
            self.assertFalse(marker.exists())

    def test_public_stop_bounds_a_nonsettling_start_without_stopping_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            publish_mount_record(mount, runtime, "606", True)
            marker = runtime / "mountpoint.json"
            recorded = marker.read_bytes()
            source = PROGRAM.read_text()
            self.assertEqual(
                1, source.count("STARTUP_SETTLE_TIMEOUT_SECONDS = 45")
            )
            bounded_program = root / "proton-drive-desktop-bounded-startup"
            bounded_program.write_text(source.replace(
                "STARTUP_SETTLE_TIMEOUT_SECONDS = 45",
                "STARTUP_SETTLE_TIMEOUT_SECONDS = 0",
            ))
            events = []

            def external(command, **kwargs):
                action = command[2]
                events.append(action)
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=(
                        "ActiveState=activating\nSubState=start-post\n"
                        "Result=success\n"
                    ),
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
                program=bounded_program,
            )

            self.assertEqual(
                (1, "", "service startup did not settle before stop\n"), result
            )
            self.assertNotIn("start", events)
            self.assertNotIn("stop", events)
            self.assertEqual(recorded, marker.read_bytes())

    def test_public_stop_preserves_startup_when_settle_observation_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            publish_mount_record(mount, runtime, "607", True)
            marker = runtime / "mountpoint.json"
            recorded = marker.read_bytes()
            show_count = 0
            events = []

            def external(command, **kwargs):
                nonlocal show_count
                action = command[2]
                events.append(action)
                if action != "show":
                    return subprocess.CompletedProcess(command, 0)
                show_count += 1
                if show_count == 1:
                    return subprocess.CompletedProcess(
                        command, 0,
                        stdout=(
                            "ActiveState=activating\nSubState=start-post\n"
                            "Result=success\n"
                        ),
                    )
                return subprocess.CompletedProcess(command, 1, stdout="")

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

            self.assertEqual(
                (1, "", "service startup state unavailable during stop\n"), result
            )
            self.assertNotIn("start", events)
            self.assertNotIn("stop", events)
            self.assertEqual(recorded, marker.read_bytes())

    def test_stop_uses_owned_unmount_path_for_activating_mounted_unit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            mount = root / "data/proton-drive-desktop/files"
            runtime = root / "run/proton-drive-desktop"
            publish_mount_record(mount, runtime, "601", True)
            marker = runtime / "mountpoint.json"
            prepared = json.loads(marker.read_text())
            del prepared["mount_id"]
            marker.write_text(json.dumps(prepared, separators=(",", ":")))
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
                        f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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
            self.assertTrue(mount.is_dir())
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
                        f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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
            self.assertTrue(mount.is_dir())
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
            self.assertTrue(mount.is_dir())
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
                        f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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

    def test_busy_unverified_stop_preserves_the_starting_service_and_mountpoint(self):
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
                + f'","mount_tag":"{TEST_MOUNT_TAG}"}}'
            )
            encoded_mount = str(mount).replace(" ", "\\040")
            mountinfo = (
                f"71 30 0:71 / {encoded_mount} ro,nosuid,nodev - "
                f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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
                    stdout="ActiveState=activating\nSubState=start-post\nResult=success\n",
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
            self.assertEqual(
                "71", json.loads((runtime / "mountpoint.json").read_text())["mount_id"]
            )

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
                    mount_tag = json.loads(
                        (runtime / "proton-drive-desktop/mountpoint.json").read_text()
                    )["mount_tag"] if mounted else TEST_MOUNT_TAG
                    line = (
                        f"81 30 0:81 / {encoded_mount} ro,nosuid,nodev - "
                        f"fuse.rclone {mount_tag} ro\n"
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
            marker = runtime / "proton-drive-desktop/mountpoint.json"
            self.assertEqual(
                {"mount", "device", "inode", "created", "nonce", "mount_tag"},
                set(json.loads(marker.read_text())),
            )

            mounted = True
            verified = invoke(["_verify-mount"], environment, run=no_process, opened=opened)
            self.assertEqual((0, "", ""), verified)
            self.assertEqual(
                {
                    "mount", "device", "inode", "created", "nonce",
                    "mount_tag", "mount_id",
                },
                set(json.loads(marker.read_text())),
            )

            mounted = False
            cleaned = invoke(["_post-stop"], environment, run=no_process, opened=opened)
            self.assertEqual((0, "", ""), cleaned)
            self.assertTrue(mount.is_dir())

    def test_dot_segment_xdg_spelling_survives_the_public_service_lifecycle(self):
        with tempfile.TemporaryDirectory(prefix="proton dot segments ") as temporary:
            root = pathlib.Path(temporary)
            config_root = root / "config with spaces"
            data_root = root / "data with spaces"
            runtime_root = root / "run with spaces"
            for directory in (config_root, data_root, runtime_root):
                directory.mkdir(mode=0o700)
                (directory / "unused segment").mkdir(mode=0o700)
            configured_config_home = config_root / "unused segment/.."
            configured_data_home = data_root / "unused segment/.."
            configured_runtime = runtime_root / "unused segment/.."
            config_parent = configured_config_home / "rclone"
            config_parent.mkdir(mode=0o700)
            config = config_parent / "proton-drive.conf"
            config.write_text("encrypted-placeholder")
            config.chmod(0o600)
            mount = configured_data_home / "proton-drive-desktop/files"
            normalized_mount = pathlib.Path(os.path.normpath(str(mount)))
            encoded_mount = str(normalized_mount).replace(" ", "\\040")
            private_runtime = runtime_root / "proton-drive-desktop"
            environment = {
                "HOME": temporary,
                "XDG_CONFIG_HOME": str(configured_config_home),
                "XDG_DATA_HOME": str(configured_data_home),
                "XDG_RUNTIME_DIR": str(configured_runtime),
            }
            mounted = False
            service_active = False
            process_calls = []

            def external(arguments, **kwargs):
                nonlocal mounted, service_active
                process_calls.append(arguments)
                if arguments[0] == "/usr/bin/busctl":
                    return subprocess.CompletedProcess(
                        arguments, 0, stdout='{"type":"s","data":[":1.72"]}\n'
                    )
                if arguments[0] == "/usr/bin/fusermount3":
                    self.assertEqual(str(mount), arguments[-1])
                    mounted = False
                    return subprocess.CompletedProcess(arguments, 0)
                if arguments[0] == "/usr/bin/systemctl":
                    action = arguments[2]
                    if action == "show":
                        active = "active" if service_active else "inactive"
                        sub = "running" if service_active else "dead"
                        return subprocess.CompletedProcess(
                            arguments,
                            0,
                            stdout=(
                                f"ActiveState={active}\nSubState={sub}\n"
                                "Result=success\n"
                            ),
                        )
                    if action == "stop":
                        service_active = False
                        return subprocess.CompletedProcess(arguments, 0)
                raise AssertionError(f"unexpected process call: {arguments!r}")

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    marker = private_runtime / "mountpoint.json"
                    mount_tag = (
                        json.loads(marker.read_text())["mount_tag"]
                        if marker.exists()
                        else TEST_MOUNT_TAG
                    )
                    entry = (
                        f"172 30 0:172 / {encoded_mount} ro,nosuid,nodev - "
                        f"fuse.rclone {mount_tag} ro\n"
                    )
                    return io.StringIO(entry if mounted else "")
                return io.open(name, *args, **kwargs)

            self.assertEqual(
                (0, "", ""),
                invoke(["_prepare"], environment, opened=opened),
            )
            binding = json.loads((private_runtime / "binding.json").read_text())
            marker = private_runtime / "mountpoint.json"
            ownership = json.loads(marker.read_text())
            self.assertEqual(str(config), binding["config"])
            self.assertEqual(str(mount), binding["mount"])
            self.assertEqual(str(mount), ownership["mount"])
            self.assertIn("..", binding["config"])
            self.assertIn("..", binding["mount"])

            mounted = True
            service_active = True
            self.assertEqual(
                (0, "", ""),
                invoke(["_verify-mount"], environment, opened=opened),
            )
            self.assertEqual(
                (0, "ready\n", ""),
                invoke(["status"], environment, run=external, opened=opened),
            )

            dolphin = mock.Mock()
            self.assertEqual(
                (0, "ready\n", ""),
                invoke(
                    ["open"], environment, run=external, popen=dolphin,
                    opened=opened,
                ),
            )
            dolphin.assert_called_once()
            self.assertEqual(
                ["/usr/bin/dolphin", str(mount)], dolphin.call_args.args[0]
            )

            secret_calls = []

            def secret_tool(arguments, **kwargs):
                secret_calls.append(arguments)
                return REAL_POPEN(
                    [
                        sys.executable,
                        "-c",
                        "import os; os.write(1, b'dot-segment-secret\\n')",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )

            credential_result = invoke_credential(
                environment,
                launch_tag=ownership["mount_tag"],
                run=external,
                popen=secret_tool,
                opened=opened,
            )
            self.assertEqual(
                (0, "dot-segment-secret\n", ""), credential_result
            )
            wanted_config_id = hashlib.sha256(str(config).encode()).hexdigest()
            self.assertEqual(wanted_config_id, secret_calls[0][-1])
            self.assertEqual(
                [
                    "/usr/bin/secret-tool", "lookup",
                    "application", "rclone",
                    "purpose", "proton-drive-config",
                    "config-id", wanted_config_id,
                ],
                secret_calls[0],
            )

            self.assertEqual(
                (0, "stopped\n", ""),
                invoke(["stop"], environment, run=external, opened=opened),
            )
            self.assertFalse(marker.exists())
            self.assertTrue(normalized_mount.is_dir())
            self.assertEqual(binding, json.loads(
                (private_runtime / "binding.json").read_text()
            ))

    def test_post_stop_rejects_mounts_before_traversing_retained_cleanup_target(self):
        for mounted_case in ("matching", "foreign", "duplicate"):
            for marker_present in (True, False):
                with self.subTest(
                    mounted_case=mounted_case, marker_present=marker_present
                ), tempfile.TemporaryDirectory() as temporary:
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
                    unknown_value = b"preserve-foreign-xattr"
                    os.setxattr(mount, unknown_name, unknown_value)
                    environment = {
                        "HOME": temporary,
                        "XDG_CONFIG_HOME": str(root / "config"),
                        "XDG_DATA_HOME": str(root / "data"),
                        "XDG_RUNTIME_DIR": str(runtime),
                    }

                    def unmounted_open(name, *args, **kwargs):
                        if name == "/proc/self/mountinfo":
                            return io.StringIO("")
                        return io.open(name, *args, **kwargs)

                    self.assertEqual(
                        (0, "", ""),
                        invoke(["_prepare"], environment, opened=unmounted_open),
                    )
                    private_runtime = runtime / "proton-drive-desktop"
                    marker = private_runtime / "mountpoint.json"
                    phase = private_runtime / "mountpoint-phase.json"
                    with mock.patch("os.removexattr", side_effect=SystemExit(96)):
                        interrupted = invoke(
                            ["_post-stop"], environment, opened=unmounted_open
                        )
                    self.assertEqual(96, interrupted[0])
                    self.assertTrue(marker.is_file())
                    self.assertTrue(phase.is_file())
                    if not marker_present:
                        marker.unlink()

                    phase_before = phase.read_bytes()
                    marker_before = marker.read_bytes() if marker_present else None
                    information_before = mount.lstat()
                    identity_before = os.getxattr(
                        mount, "user.proton-drive-desktop.identity"
                    )
                    encoded_mount = str(mount).replace(" ", "\\040")
                    matching = (
                        f"187 30 0:187 / {encoded_mount} ro,nosuid,nodev - "
                        "fuse.rclone proton-dolphin: ro\n"
                    )
                    mountinfo = {
                        "matching": matching,
                        "foreign": (
                            f"188 30 0:188 / {encoded_mount} rw,nosuid,nodev - "
                            "fuse.other local: rw\n"
                        ),
                        "duplicate": matching + matching.replace("187", "189"),
                    }[mounted_case]
                    target_accesses = []
                    target_mutations = []
                    original_lstat = pathlib.Path.lstat
                    original_getxattr = os.getxattr
                    original_scandir = os.scandir
                    original_setxattr = os.setxattr
                    original_removexattr = os.removexattr

                    def watched_lstat(path, *args, **kwargs):
                        if path == mount:
                            target_accesses.append("lstat")
                        return original_lstat(path, *args, **kwargs)

                    def watched_getxattr(path, *args, **kwargs):
                        if pathlib.Path(path) == mount:
                            target_accesses.append("getxattr")
                        return original_getxattr(path, *args, **kwargs)

                    def watched_scandir(path, *args, **kwargs):
                        if pathlib.Path(path) == mount:
                            target_accesses.append("scandir")
                        return original_scandir(path, *args, **kwargs)

                    def watched_setxattr(path, *args, **kwargs):
                        if pathlib.Path(path) == mount:
                            target_mutations.append("setxattr")
                        return original_setxattr(path, *args, **kwargs)

                    def watched_removexattr(path, *args, **kwargs):
                        if pathlib.Path(path) == mount:
                            target_mutations.append("removexattr")
                        return original_removexattr(path, *args, **kwargs)

                    def mounted_open(name, *args, **kwargs):
                        if name == "/proc/self/mountinfo":
                            return io.StringIO(mountinfo)
                        return io.open(name, *args, **kwargs)

                    with mock.patch.object(
                        pathlib.Path,
                        "lstat",
                        autospec=True,
                        side_effect=watched_lstat,
                    ), mock.patch(
                        "os.getxattr", side_effect=watched_getxattr
                    ), mock.patch(
                        "os.scandir", side_effect=watched_scandir
                    ), mock.patch(
                        "os.setxattr", side_effect=watched_setxattr
                    ), mock.patch(
                        "os.removexattr", side_effect=watched_removexattr
                    ):
                        result = invoke(
                            ["_post-stop"], environment, opened=mounted_open
                        )

                    self.assertEqual(
                        (1, "", "residual mount remains\n"), result
                    )
                    self.assertEqual([], target_accesses)
                    self.assertEqual([], target_mutations)
                    self.assertEqual(phase_before, phase.read_bytes())
                    self.assertEqual(marker_present, marker.exists())
                    if marker_present:
                        self.assertEqual(marker_before, marker.read_bytes())
                    information_after = mount.lstat()
                    self.assertEqual(
                        (
                            information_before.st_mode,
                            information_before.st_dev,
                            information_before.st_ino,
                        ),
                        (
                            information_after.st_mode,
                            information_after.st_dev,
                            information_after.st_ino,
                        ),
                    )
                    self.assertEqual(
                        identity_before,
                        os.getxattr(
                            mount, "user.proton-drive-desktop.identity"
                        ),
                    )
                    self.assertEqual(
                        unknown_value, os.getxattr(mount, unknown_name)
                    )

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

    def test_service_prepare_qualifies_a_mount_introduced_after_initial_absence(self):
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
            target_mutations = []
            real_getxattr = os.getxattr
            real_setxattr = os.setxattr

            def opened(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                if str(name).startswith("/proc/self/fdinfo/"):
                    descriptor = int(str(name).rsplit("/", 1)[1])
                    target = pathlib.Path(os.readlink(f"/proc/self/fd/{descriptor}"))
                    mount_id = "900" if target == mount else "800"
                    return io.StringIO(f"mnt_id:\t{mount_id}\n")
                return io.open(name, *args, **kwargs)

            def watched_getxattr(path, *args, **kwargs):
                target_mutations.append("getxattr")
                return real_getxattr(path, *args, **kwargs)

            def watched_setxattr(path, *args, **kwargs):
                target_mutations.append("setxattr")
                return real_setxattr(path, *args, **kwargs)

            with mock.patch("os.getxattr", side_effect=watched_getxattr), mock.patch(
                "os.setxattr", side_effect=watched_setxattr
            ):
                result = invoke(["_prepare"], environment, opened=opened)

            self.assertEqual(
                (1, "", "mountpoint is already mounted; preserving it\n"),
                result,
            )
            self.assertEqual([], target_mutations)
            self.assertFalse(
                (runtime / "proton-drive-desktop/mountpoint.json").exists()
            )
            self.assertTrue(mount.is_dir())

    def test_post_stop_qualifies_a_mount_introduced_after_initial_absence(self):
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

            def unmounted_open(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                return io.open(name, *args, **kwargs)

            self.assertEqual(
                (0, "", ""),
                invoke(["_prepare"], environment, opened=unmounted_open),
            )
            marker = runtime / "proton-drive-desktop/mountpoint.json"
            marker_before = marker.read_bytes()
            nonce_before = os.getxattr(
                mount, "user.proton-drive-desktop.identity"
            )

            def raced_open(name, *args, **kwargs):
                if name == "/proc/self/mountinfo":
                    return io.StringIO("")
                if str(name).startswith("/proc/self/fdinfo/"):
                    descriptor = int(str(name).rsplit("/", 1)[1])
                    target = pathlib.Path(os.readlink(f"/proc/self/fd/{descriptor}"))
                    mount_id = "902" if target == mount else "801"
                    return io.StringIO(f"mnt_id:\t{mount_id}\n")
                return io.open(name, *args, **kwargs)

            result = invoke(["_post-stop"], environment, opened=raced_open)

            self.assertEqual(
                (1, "", "mountpoint is already mounted; preserving it\n"),
                result,
            )
            self.assertEqual(marker_before, marker.read_bytes())
            self.assertEqual(
                nonce_before,
                os.getxattr(mount, "user.proton-drive-desktop.identity"),
            )

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
                        f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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
                        f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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
                        f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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
                        f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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
                Popen = staticmethod(synthetic_version_popen)
                TimeoutExpired = subprocess.TimeoutExpired

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
                        f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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
                Popen = staticmethod(synthetic_version_popen)
                TimeoutExpired = subprocess.TimeoutExpired

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
                    marker = resolved["runtime"] / "mountpoint.json"
                    mount_tag = (
                        json.loads(marker.read_text())["mount_tag"]
                        if mounted else TEST_MOUNT_TAG
                    )
                    line = (
                        f"211 30 0:211 / {encoded_mount} ro,nosuid,nodev - "
                        f"fuse.rclone {mount_tag} ro\n"
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
        self.enterContext(mock.patch(
            "subprocess.Popen", side_effect=synthetic_version_popen
        ))
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
                Popen = staticmethod(synthetic_version_popen)
                TimeoutExpired = subprocess.TimeoutExpired

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
                    marker = resolved["runtime"] / "mountpoint.json"
                    mount_tag = (
                        json.loads(marker.read_text())["mount_tag"]
                        if mounted else TEST_MOUNT_TAG
                    )
                    line = (
                        f"212 30 0:212 / {encoded_mount} ro,nosuid,nodev - "
                        f"fuse.rclone {mount_tag} ro\n"
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
                if isinstance(path, int):
                    inspected = pathlib.Path(
                        os.readlink(f"/proc/self/fd/{path}")
                    )
                else:
                    inspected = pathlib.Path(path)
                if inspected == resolved["mount"] and mounted:
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
        self.enterContext(mock.patch(
            "subprocess.Popen", side_effect=synthetic_version_popen
        ))
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
        self.enterContext(mock.patch(
            "subprocess.Popen", side_effect=synthetic_version_popen
        ))
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
                observed = service
                if observed == "activating":
                    service = "failed"
                sub = "start-pre" if observed == "activating" else "dead"
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=(
                        f"ActiveState={observed}\nSubState={sub}\n"
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
                self.assertTrue(resolved["mount"].is_dir())
                self.assertFalse(marker.exists())

    def test_preparation_finishes_before_public_cleanup_and_is_preserved(self):
        self.enterContext(mock.patch(
            "subprocess.Popen", side_effect=synthetic_version_popen
        ))
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
            self.assertTrue(mount.is_dir())
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

    def test_post_stop_preserves_replacement_after_descriptor_cleanup(self):
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
                (0, "", ""), invoke(["_prepare"], environment, opened=opened)
            )
            private_runtime = runtime / "proton-drive-desktop"
            marker = private_runtime / "mountpoint.json"
            phase = private_runtime / "mountpoint-phase.json"
            real_removexattr = os.removexattr
            held = root / "held-cleaned-directory"

            def replace_after_descriptor_cleanup(path, name, *args, **kwargs):
                real_removexattr(path, name, *args, **kwargs)
                mount.rename(held)
                mount.mkdir(mode=0o700)

            with mock.patch(
                "os.removexattr", side_effect=replace_after_descriptor_cleanup
            ):
                result = invoke(["_post-stop"], environment, opened=opened)

            self.assertEqual(
                (1, "", "mountpoint was replaced; preserving it\n"), result
            )
            self.assertTrue(held.is_dir())
            self.assertTrue(mount.is_dir())
            self.assertTrue(marker.is_file())
            self.assertTrue(phase.is_file())

    def test_stop_rejects_same_inode_mutation_after_nonce_removal(self):
        for recovery in (False, True):
            for mutation in ("contents", "mode"):
                with self.subTest(recovery=recovery, mutation=mutation):
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
                        marker = private_runtime / "mountpoint.json"
                        phase = private_runtime / "mountpoint-phase.json"
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

                        def external(command, **kwargs):
                            return subprocess.CompletedProcess(
                                command, 0,
                                stdout=(
                                    "ActiveState=inactive\nSubState=dead\n"
                                    "Result=success\n"
                                ),
                            )

                        self.assertEqual(
                            (0, "", ""),
                            invoke(["_prepare"], environment, opened=opened),
                        )
                        unrelated_name = "user.proton-drive-desktop.keep"
                        unrelated_value = b"preserve-unrelated-xattr"
                        os.setxattr(mount, unrelated_name, unrelated_value)
                        real_removexattr = os.removexattr

                        if recovery:
                            def interrupt_before_nonce_removal(
                                path, name, *args, **kwargs
                            ):
                                if name == "user.proton-drive-desktop.identity":
                                    raise SystemExit(95)
                                return real_removexattr(
                                    path, name, *args, **kwargs
                                )

                            with mock.patch(
                                "os.removexattr",
                                side_effect=interrupt_before_nonce_removal,
                            ):
                                interrupted = invoke(
                                    ["_post-stop"], environment, opened=opened
                                )
                            self.assertEqual(95, interrupted[0])
                            self.assertTrue(phase.is_file())

                        unexpected = mount / "keep.txt"

                        def mutate_after_nonce_removal(
                            path, name, *args, **kwargs
                        ):
                            real_removexattr(path, name, *args, **kwargs)
                            if name == "user.proton-drive-desktop.identity":
                                if mutation == "contents":
                                    unexpected.write_text("preserve this file")
                                else:
                                    mount.chmod(0o770)

                        with mock.patch(
                            "os.removexattr",
                            side_effect=mutate_after_nonce_removal,
                        ):
                            result = invoke(
                                ["stop"], environment,
                                run=external, opened=opened,
                            )

                        self.assertEqual(1, result[0])
                        self.assertEqual("", result[1])
                        self.assertEqual(
                            {
                                "contents": (
                                    "mountpoint is not empty; preserving it\n"
                                ),
                                "mode": "unsafe mountpoint; preserving it\n",
                            }[mutation],
                            result[2],
                        )
                        self.assertTrue(marker.is_file())
                        self.assertTrue(phase.is_file())
                        self.assertEqual(
                            unrelated_value,
                            os.getxattr(mount, unrelated_name),
                        )
                        if mutation == "contents":
                            self.assertEqual(
                                "preserve this file", unexpected.read_text()
                            )
                        else:
                            self.assertEqual(0o770, stat.S_IMODE(mount.stat().st_mode))

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
                dir_fd = kwargs.get("dir_fd")
                if dir_fd is not None:
                    parent = pathlib.Path(os.readlink(f"/proc/self/fd/{dir_fd}"))
                    destination = parent / path
                else:
                    destination = pathlib.Path(path)
                if destination == mount:
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
            self.assertTrue(mount.is_dir())

    def test_prepare_rejects_a_leaf_that_appears_during_creation(self):
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

            def race_mkdir(path, mode=0o777, *args, **kwargs):
                dir_fd = kwargs.get("dir_fd")
                if dir_fd is not None:
                    parent = pathlib.Path(os.readlink(f"/proc/self/fd/{dir_fd}"))
                    destination = parent / path
                else:
                    destination = pathlib.Path(path)
                if destination == mount:
                    real_mkdir(path, mode, *args, **kwargs)
                    raise FileExistsError(errno.EEXIST, "synthetic race", path)
                return real_mkdir(path, mode, *args, **kwargs)

            with mock.patch("os.mkdir", side_effect=race_mkdir):
                result = invoke(["_prepare"], environment, opened=opened)

            self.assertEqual(
                (1, "", "mountpoint appeared during preparation; preserving it\n"),
                result,
            )
            self.assertTrue(mount.is_dir())
            private_runtime = runtime / "proton-drive-desktop"
            self.assertFalse((private_runtime / "mountpoint.json").exists())
            self.assertFalse((private_runtime / "mountpoint-phase.json").exists())

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux xattrs")
    def test_interrupted_publication_rejects_unsafe_mode_without_mutation(self):
        with interrupted_publication_fixture() as (
            mount, marker, phase, environment, opened,
        ):
            mount.chmod(0o770)
            os.setxattr(mount, "user.proton-drive-desktop.keep", b"keep-xattr")
            self.assert_interrupted_publication_rejected(
                mount, marker, phase, environment, opened,
                "unsafe mountpoint\n",
            )

    def test_interrupted_publication_rejects_other_unsafe_directory_evidence(self):
        for evidence in ("owner", "contents", "identity"):
            with self.subTest(evidence=evidence), interrupted_publication_fixture() as (
                mount, marker, phase, environment, opened,
            ):
                os.setxattr(
                    mount,
                    "user.proton-drive-desktop.keep",
                    b"keep-directory-xattr",
                )
                fstat = None
                if evidence == "owner":
                    mount_identity = (mount.stat().st_dev, mount.stat().st_ino)
                    baseline_fstat = os.fstat

                    def changed_owner(descriptor):
                        information = baseline_fstat(descriptor)
                        if (
                            information.st_dev,
                            information.st_ino,
                        ) == mount_identity:
                            return with_uid(information, os.getuid() + 1)
                        return information

                    fstat = changed_owner
                    expected_error = "unsafe mountpoint\n"
                elif evidence == "contents":
                    retained = mount / "retained.bin"
                    retained.write_bytes(b"retained directory contents\x00")
                    retained.chmod(0o640)
                    os.setxattr(retained, "user.keep", b"keep-file-xattr")
                    expected_error = (
                        "mountpoint contains unexpected local contents\n"
                    )
                else:
                    os.setxattr(
                        mount,
                        "user.proton-drive-desktop.identity",
                        b"cd" * 32,
                    )
                    expected_error = (
                        "interrupted mountpoint identity publication requires "
                        "stopped recovery\n"
                    )

                self.assert_interrupted_publication_rejected(
                    mount, marker, phase, environment, opened,
                    expected_error, fstat=fstat,
                )

    def test_interrupted_publication_rejects_nonidentical_markers_without_mutation(self):
        cases = (
            "malformed",
            "missing-field",
            "unexpected-field",
            "mount-id-field",
            "symlink",
            "path",
            "created",
            "nonce",
            "tag",
            "device",
            "inode",
        )
        for evidence in cases:
            with self.subTest(evidence=evidence), interrupted_publication_fixture() as (
                mount, marker, phase, environment, opened,
            ):
                operation = json.loads(phase.read_bytes())
                retained = {
                    "mount": operation["mount"],
                    "device": operation["device"],
                    "inode": operation["inode"],
                    "created": operation["created"],
                    "nonce": operation["nonce"],
                    "mount_tag": operation["mount_tag"],
                }
                if evidence == "malformed":
                    marker_bytes = b'{"mount":'
                else:
                    if evidence == "missing-field":
                        del retained["mount_tag"]
                    elif evidence == "unexpected-field":
                        retained["unexpected"] = "preserve"
                    elif evidence == "mount-id-field":
                        retained["mount_id"] = "17"
                    elif evidence == "path":
                        retained["mount"] = str(mount.parent / "elsewhere")
                    elif evidence == "created":
                        retained["created"] = not retained["created"]
                    elif evidence == "nonce":
                        retained["nonce"] = "cd" * 32
                    elif evidence == "tag":
                        retained["mount_tag"] = (
                            "proton-drive-desktop-" + "cd" * 32
                        )
                    elif evidence == "device":
                        retained["device"] += 1
                    elif evidence == "inode":
                        retained["inode"] += 1
                    marker_bytes = (
                        json.dumps(retained, separators=(",", ":")) + "\n"
                    ).encode()
                target = None
                if evidence == "symlink":
                    target = marker.parent / "retained-marker-target.json"
                    target.write_bytes(marker_bytes)
                    target.chmod(0o600)
                    marker.symlink_to(target)
                else:
                    marker.write_bytes(marker_bytes)
                    marker.chmod(0o600)
                os.setxattr(
                    mount,
                    "user.proton-drive-desktop.keep",
                    b"keep-marker-case-xattr",
                )
                target_before = target.read_bytes() if target is not None else None

                self.assert_interrupted_publication_rejected(
                    mount, marker, phase, environment, opened,
                    "interrupted mountpoint identity publication requires "
                    "stopped recovery\n",
                )
                if target is not None:
                    self.assertEqual(target_before, target.read_bytes())

    def test_interrupted_publication_recovers_absent_and_exact_markers(self):
        for marker_state in ("absent", "exact"):
            with self.subTest(marker_state=marker_state), interrupted_publication_fixture() as (
                mount, marker, phase, environment, opened,
            ):
                operation = json.loads(phase.read_bytes())
                expected_marker = {
                    "mount": operation["mount"],
                    "device": operation["device"],
                    "inode": operation["inode"],
                    "created": operation["created"],
                    "nonce": operation["nonce"],
                    "mount_tag": operation["mount_tag"],
                }
                os.setxattr(
                    mount,
                    "user.proton-drive-desktop.keep",
                    b"keep-through-shutdown",
                )
                if marker_state == "exact":
                    marker_bytes = (
                        json.dumps(expected_marker, indent=2) + "\n"
                    ).encode()
                    marker.write_bytes(marker_bytes)
                    marker.chmod(0o600)
                    os.setxattr(
                        mount,
                        "user.proton-drive-desktop.identity",
                        operation["nonce"].encode("ascii"),
                    )

                self.assertEqual(
                    (0, "", ""),
                    invoke(["_prepare"], environment, opened=opened),
                )
                self.assertFalse(phase.exists())
                recovered_marker = json.loads(marker.read_bytes())
                for key in (
                    "mount", "device", "inode", "created", "nonce",
                ):
                    self.assertEqual(expected_marker[key], recovered_marker[key])
                self.assertRegex(
                    recovered_marker["mount_tag"],
                    r"\Aproton-drive-desktop-[0-9a-f]{64}\Z",
                )
                self.assertEqual(0o700, stat.S_IMODE(mount.stat().st_mode))
                self.assertEqual([], list(mount.iterdir()))
                self.assertEqual(
                    operation["nonce"].encode("ascii"),
                    os.getxattr(
                        mount, "user.proton-drive-desktop.identity"
                    ),
                )
                self.assertEqual(
                    b"keep-through-shutdown",
                    os.getxattr(mount, "user.proton-drive-desktop.keep"),
                )

                launch = mock.Mock(side_effect=SystemExit(0))
                self.assertEqual(
                    (0, "", ""),
                    invoke(
                        ["_mount"], environment,
                        execve=launch, opened=opened,
                    ),
                )
                launch.assert_called_once()
                self.assertEqual(
                    (0, "", ""),
                    invoke(["_post-stop"], environment, opened=opened),
                )
                self.assertTrue(mount.is_dir())
                self.assertEqual(0o700, stat.S_IMODE(mount.stat().st_mode))
                self.assertEqual([], list(mount.iterdir()))
                self.assertFalse(marker.exists())
                self.assertFalse(phase.exists())
                with self.assertRaises(OSError) as missing:
                    os.getxattr(
                        mount, "user.proton-drive-desktop.identity"
                    )
                self.assertEqual(XATTR_MISSING_ERRNO, missing.exception.errno)
                self.assertEqual(
                    b"keep-through-shutdown",
                    os.getxattr(mount, "user.proton-drive-desktop.keep"),
                )

    def test_interrupted_identity_publication_reconciles_before_mounting(self):
        for preexisting in (False, True):
            for boundary in (
                "before-nonce", "nonce", "before-marker", "after-marker",
            ):
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

                    if boundary in {"before-nonce", "nonce"}:
                        real_setxattr = os.setxattr

                        def terminate(*args, **kwargs):
                            if boundary == "nonce":
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
                    self.assertTrue(mount.is_dir())

    def test_interrupted_publication_preserves_phase_when_republication_fails(self):
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

            with mock.patch("os.setxattr", side_effect=SystemExit(97)):
                self.assertEqual(
                    97, invoke(["_prepare"], environment, opened=opened)[0]
                )

            private_runtime = runtime / "proton-drive-desktop"
            marker = private_runtime / "mountpoint.json"
            phase = private_runtime / "mountpoint-phase.json"
            phase_before = phase.read_bytes()
            operation = json.loads(phase_before)
            real_replace = os.replace

            def fail_marker_replace(source, destination, *args, **kwargs):
                if pathlib.Path(destination) == marker:
                    raise OSError(errno.EIO, "synthetic marker failure")
                return real_replace(source, destination, *args, **kwargs)

            with mock.patch("os.replace", side_effect=fail_marker_replace):
                result = invoke(["_prepare"], environment, opened=opened)

            self.assertEqual(
                (1, "", "mountpoint ownership record is unavailable\n"), result
            )
            self.assertFalse(marker.exists())
            self.assertEqual(phase_before, phase.read_bytes())
            self.assertEqual(
                operation["nonce"].encode("ascii"),
                os.getxattr(mount, "user.proton-drive-desktop.identity"),
            )

    def test_interrupted_retained_cleanup_requires_bounded_recovery(self):
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
                "interrupted retained mountpoint cleanup requires stopped "
                "recovery\n"
            )
            launch = mock.Mock()
            for command in ("_prepare", "_mount"):
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

            self.assertEqual(
                (1, "", diagnostic),
                invoke(
                    ["start"], environment,
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

            self.assertEqual(
                (0, "stopped\n", ""),
                invoke(
                    ["stop"], environment,
                    run=external, opened=opened,
                ),
            )
            self.assertFalse(marker.exists())
            self.assertFalse(phase.exists())
            self.assertEqual(unknown_value, os.getxattr(mount, unknown_name))

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

    def test_phase_only_cleanup_requires_the_recorded_directory_identity(self):
        for replaced in (False, True):
            with self.subTest(replaced=replaced), tempfile.TemporaryDirectory() as temporary:
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

                def external(arguments, **kwargs):
                    return subprocess.CompletedProcess(
                        arguments,
                        0,
                        stdout=(
                            "ActiveState=inactive\nSubState=dead\n"
                            "Result=success\n"
                        ),
                    )

                self.assertEqual(
                    (0, "", ""),
                    invoke(["_prepare"], environment, opened=opened),
                )
                real_unlink = pathlib.Path.unlink

                def interrupt_after_marker_removal(path, *args, **kwargs):
                    real_unlink(path, *args, **kwargs)
                    if path == marker:
                        raise SystemExit(96)

                with mock.patch.object(
                    pathlib.Path,
                    "unlink",
                    autospec=True,
                    side_effect=interrupt_after_marker_removal,
                ):
                    interrupted = invoke(
                        ["_post-stop"], environment, opened=opened
                    )

                self.assertEqual(96, interrupted[0])
                self.assertFalse(marker.exists())
                self.assertTrue(phase.is_file())
                phase_before = phase.read_bytes()
                recorded = json.loads(phase_before)
                self.assertEqual(
                    (recorded["device"], recorded["inode"]),
                    (mount.stat().st_dev, mount.stat().st_ino),
                )
                unknown_name = "user.proton-drive-desktop.keep"
                unknown_value = b"preserve-phase-only-unknown-xattr"

                if replaced:
                    replacement = mount.parent / "replacement"
                    replacement.mkdir(mode=0o700)
                    os.setxattr(replacement, unknown_name, unknown_value)
                    mount.rmdir()
                    replacement.rename(mount)
                    self.assertNotEqual(
                        (recorded["device"], recorded["inode"]),
                        (mount.stat().st_dev, mount.stat().st_ino),
                    )
                else:
                    os.setxattr(mount, unknown_name, unknown_value)

                self.assertEqual(
                    (0, "", ""),
                    invoke(["_post-stop"], environment, opened=opened),
                )
                self.assertEqual(phase_before, phase.read_bytes())

                result = invoke(
                    ["stop"], environment,
                    run=external, opened=opened,
                )
                if replaced:
                    self.assertEqual(
                        (
                            1,
                            "",
                            "interrupted retained mountpoint cleanup requires "
                            "stopped recovery\n",
                        ),
                        result,
                    )
                    self.assertEqual(phase_before, phase.read_bytes())
                else:
                    self.assertEqual((0, "stopped\n", ""), result)
                    self.assertFalse(phase.exists())

                self.assertTrue(mount.is_dir())
                self.assertEqual(
                    unknown_value, os.getxattr(mount, unknown_name)
                )

    def test_cleanup_preserves_a_marker_when_the_recorded_directory_is_missing(self):
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
                (0, "", ""),
                invoke(["_prepare"], environment, opened=opened),
            )
            marker = runtime / "proton-drive-desktop/mountpoint.json"
            marker_before = marker.read_bytes()
            mount.rmdir()

            result = invoke(["_post-stop"], environment, opened=opened)

            self.assertEqual(
                (1, "", "mountpoint was replaced; preserving it\n"), result
            )
            self.assertEqual(marker_before, marker.read_bytes())
            self.assertFalse(mount.exists())

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

    def test_cleanup_retains_the_reserved_empty_leaf_and_removes_only_its_identity(self):
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

                with mock.patch(
                    "os.rmdir",
                    side_effect=AssertionError("cleanup attempted path deletion"),
                ):
                    self.assertEqual(
                        (0, "", ""),
                        invoke(["_post-stop"], environment, opened=opened),
                    )
                self.assertFalse(marker.exists())
                self.assertTrue(mount.is_dir())
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

    def test_interrupted_missing_leaf_recreation_recovers_exact_predecessor(self):
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
                (0, "", ""), invoke(["_prepare"], environment, opened=opened)
            )
            private_runtime = runtime / "proton-drive-desktop"
            marker = private_runtime / "mountpoint.json"
            phase = private_runtime / "mountpoint-phase.json"
            predecessor_bytes = marker.read_bytes()
            predecessor = json.loads(predecessor_bytes)
            mount.rmdir()

            with mock.patch("os.setxattr", side_effect=SystemExit(95)):
                interrupted = invoke(["_prepare"], environment, opened=opened)

            self.assertEqual(95, interrupted[0])
            self.assertEqual(predecessor_bytes, marker.read_bytes())
            operation = json.loads(phase.read_text())
            self.assertEqual("prepare-publish", operation["phase"])
            self.assertNotEqual(predecessor["nonce"], operation["nonce"])

            self.assertEqual(
                (0, "", ""), invoke(["_prepare"], environment, opened=opened)
            )
            recovered = json.loads(marker.read_text())
            self.assertFalse(phase.exists())
            self.assertTrue(recovered["created"])
            self.assertNotEqual(predecessor["nonce"], recovered["nonce"])
            self.assertEqual(
                recovered["nonce"].encode("ascii"),
                os.getxattr(mount, "user.proton-drive-desktop.identity"),
            )

    def test_interrupted_missing_leaf_recreation_rejects_unrelated_marker(self):
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
                (0, "", ""), invoke(["_prepare"], environment, opened=opened)
            )
            private_runtime = runtime / "proton-drive-desktop"
            marker = private_runtime / "mountpoint.json"
            phase = private_runtime / "mountpoint-phase.json"
            mount.rmdir()
            with mock.patch("os.setxattr", side_effect=SystemExit(95)):
                self.assertEqual(
                    95, invoke(["_prepare"], environment, opened=opened)[0]
                )

            unrelated = json.loads(marker.read_text())
            unrelated["mount_tag"] = "proton-drive-desktop-" + "cd" * 32
            marker.write_text(json.dumps(unrelated, separators=(",", ":")))
            marker_before = marker.read_bytes()
            phase_before = phase.read_bytes()

            self.assertEqual(
                (
                    1,
                    "",
                    "interrupted mountpoint identity publication requires "
                    "stopped recovery\n",
                ),
                invoke(["_prepare"], environment, opened=opened),
            )
            self.assertEqual(marker_before, marker.read_bytes())
            self.assertEqual(phase_before, phase.read_bytes())
            with self.assertRaises(OSError) as missing:
                os.getxattr(mount, "user.proton-drive-desktop.identity")
            self.assertEqual(XATTR_MISSING_ERRNO, missing.exception.errno)

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
            self.assertEqual(
                {"mount", "device", "inode", "created", "nonce", "mount_tag"},
                set(recovered),
            )
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
                self.assertTrue(mount.is_dir())
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
                    marker = runtime / "mountpoint.json"
                    mount_tag = (
                        json.loads(marker.read_text())["mount_tag"]
                        if mounted else TEST_MOUNT_TAG
                    )
                    entry = (
                        f"{mount_id} 30 0:131 / {encoded_mount} ro,nosuid,nodev - "
                        f"fuse.rclone {mount_tag} ro\n"
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
                ("reused", 1, "mounted instance changed; preserving it\n", 0),
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
                                    f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
                                )
                            elif after == "absent":
                                mountinfo = ""
                            elif after == "same":
                                mountinfo = (
                                    f"141 30 0:141 / {encoded_mount} ro,nosuid,nodev - "
                                    f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
                                )
                            elif after == "different":
                                mountinfo = (
                                    f"142 30 0:142 / {encoded_mount} ro,nosuid,nodev - "
                                    f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
                                )
                            elif after == "reused":
                                replacement_tag = "proton-drive-desktop-" + "cd" * 32
                                mountinfo = (
                                    f"141 30 0:142 / {encoded_mount} ro,nosuid,nodev - "
                                    f"fuse.rclone {replacement_tag} ro\n"
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
            reset_exit = 0
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
                    # systemd retains a stopped unit's failed state until reset.
                    if service != "failed":
                        service = "inactive"
                    return subprocess.CompletedProcess(arguments, 0)
                if action == "reset-failed":
                    if reset_exit == 0:
                        service = "inactive"
                    return subprocess.CompletedProcess(arguments, reset_exit)
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
                        f"fuse.rclone {TEST_MOUNT_TAG} ro\n"
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
            self.assertTrue(mount.is_dir())
            self.assertEqual(
                (0, "stopped\n", ""),
                invoke(["status"], environment, run=external, opened=opened),
            )

            publish_mount_record(
                mount, runtime / "proton-drive-desktop", "152", True
            )
            service = "failed"
            reset_exit = 1
            self.assertEqual(
                (1, "", "service failure reset failed\n"),
                invoke(["stop"], environment, run=external, opened=opened),
            )
            self.assertTrue(mount.exists())
            self.assertEqual(
                (1, "failed\n", ""),
                invoke(["status"], environment, run=external, opened=opened),
            )

            reset_exit = 0
            unexpected = mount / "keep.txt"
            unexpected.write_text("preserve this local file")
            self.assertEqual(
                (1, "", "mountpoint is not empty; preserving it\n"),
                invoke(["stop"], environment, run=external, opened=opened),
            )
            self.assertEqual("preserve this local file", unexpected.read_text())
            self.assertEqual(
                (1, "inconsistent/foreign state\n", ""),
                invoke(["status"], environment, run=external, opened=opened),
            )
            unexpected.unlink()
            self.assertEqual(
                (0, "stopped\n", ""),
                invoke(["stop"], environment, run=external, opened=opened),
            )
            self.assertEqual(
                (0, "stopped\n", ""),
                invoke(["status"], environment, run=external, opened=opened),
            )

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


def real_manager_cleanup_retention_snapshot(mount, marker, phase):
    def record(path):
        if not path.exists():
            return None
        value = path.read_bytes()
        return {
            "mode": stat.S_IMODE(path.lstat().st_mode),
            "size": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
            "bytes_hex": value.hex(),
        }

    information = mount.lstat()
    if not stat.S_ISDIR(information.st_mode) or mount.is_symlink():
        raise RuntimeError("synthetic recovery mountpoint is not a directory")
    contents = []
    for child in sorted(mount.iterdir()):
        child_information = child.lstat()
        contents.append({
            "name": child.name,
            "mode": stat.S_IMODE(child_information.st_mode),
            "type": (
                "directory" if stat.S_ISDIR(child_information.st_mode)
                else "file" if stat.S_ISREG(child_information.st_mode)
                else "symlink" if stat.S_ISLNK(child_information.st_mode)
                else "other"
            ),
        })
    xattrs = {
        name: os.getxattr(mount, name, follow_symlinks=False).hex()
        for name in sorted(os.listxattr(mount, follow_symlinks=False))
    }
    return {
        "marker": record(marker),
        "phase": record(phase),
        "directory": {
            "device": information.st_dev,
            "inode": information.st_ino,
            "uid": information.st_uid,
            "mode": stat.S_IMODE(information.st_mode),
            "contents": contents,
            "xattrs_hex": xattrs,
        },
    }


class PersistentSystemdUnitReference:
    def __init__(self):
        try:
            self.library = ctypes.CDLL("libsystemd.so.0")
        except OSError:
            raise RuntimeError("libsystemd sd-bus is unavailable") from None
        self.library.sd_bus_open_user.argtypes = [
            ctypes.POINTER(ctypes.c_void_p)
        ]
        self.library.sd_bus_open_user.restype = ctypes.c_int
        self.library.sd_bus_call_method.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_char_p,
        ]
        self.library.sd_bus_call_method.restype = ctypes.c_int
        self.library.sd_bus_message_unref.argtypes = [ctypes.c_void_p]
        self.library.sd_bus_message_unref.restype = ctypes.c_void_p
        self.library.sd_bus_flush_close_unref.argtypes = [ctypes.c_void_p]
        self.library.sd_bus_flush_close_unref.restype = ctypes.c_void_p
        self.bus = ctypes.c_void_p()
        opened = self.library.sd_bus_open_user(ctypes.byref(self.bus))
        if opened < 0:
            if self.bus.value:
                self.library.sd_bus_flush_close_unref(self.bus)
            self.bus = ctypes.c_void_p()
            raise RuntimeError("unable to open a persistent user-bus connection")

    def call(self, method, unit_name):
        if not self.bus.value:
            return -errno.ENOTCONN
        reply = ctypes.c_void_p()
        try:
            return self.library.sd_bus_call_method(
                self.bus,
                b"org.freedesktop.systemd1",
                b"/org/freedesktop/systemd1",
                b"org.freedesktop.systemd1.Manager",
                method.encode("ascii"),
                None,
                ctypes.byref(reply),
                b"s",
                ctypes.c_char_p(unit_name.encode("utf-8")),
            )
        finally:
            if reply.value:
                self.library.sd_bus_message_unref(reply)

    def close(self):
        if self.bus.value:
            self.library.sd_bus_flush_close_unref(self.bus)
            self.bus = ctypes.c_void_p()


def run_real_user_manager_cleanup_retention(
    evidence_directory, *, command_runner=None, reference_owner_factory=None,
):
    """Qualify cleanup retention against one isolated real user-manager unit.

    This coordinator-only fixture creates one uniquely named transient unit,
    substitutes only that unit name in a disposable helper copy, and uses
    synthetic config and recovery records. It invokes rclone only for its fixed
    version output. It does not invoke credentials, FUSE, a provider, the
    installed Proton unit, or the network.
    """
    if sys.platform != "linux":
        raise RuntimeError("real user-manager qualification requires Linux")
    if command_runner is None:
        command_runner = subprocess.run
    evidence_directory = pathlib.Path(evidence_directory)
    if not evidence_directory.is_absolute():
        raise RuntimeError("evidence directory must be absolute")

    runtime_value = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime_value:
        raise RuntimeError("XDG_RUNTIME_DIR is required")
    runtime_base = pathlib.Path(runtime_value)
    if not runtime_base.is_absolute():
        raise RuntimeError("XDG_RUNTIME_DIR must be absolute")
    runtime_information = runtime_base.lstat()
    if (
        not stat.S_ISDIR(runtime_information.st_mode)
        or runtime_base.is_symlink()
        or runtime_information.st_uid != os.getuid()
        or runtime_information.st_mode & 0o022
    ):
        raise RuntimeError("XDG_RUNTIME_DIR is not a private user directory")
    manager_directory = runtime_base / "systemd"
    manager_socket = manager_directory / "private"
    try:
        manager_directory_information = manager_directory.lstat()
        manager_socket_information = manager_socket.lstat()
    except OSError:
        raise RuntimeError(
            "real user manager socket is unavailable or unsafe"
        ) from None
    if (
        not stat.S_ISDIR(manager_directory_information.st_mode)
        or manager_directory_information.st_uid != os.getuid()
        or manager_directory_information.st_mode & 0o022
        or not stat.S_ISSOCK(manager_socket_information.st_mode)
        or manager_socket_information.st_uid != os.getuid()
        or manager_socket_information.st_mode & 0o022
    ):
        raise RuntimeError("real user manager socket is unavailable or unsafe")

    for command in (
        pathlib.Path("/usr/bin/systemctl"),
        pathlib.Path("/usr/bin/systemd-run"),
        pathlib.Path("/usr/bin/rclone"),
        pathlib.Path("/usr/bin/true"),
        pathlib.Path("/usr/bin/env"),
        pathlib.Path("/usr/bin/cut"),
        pathlib.Path("/usr/bin/grep"),
        pathlib.Path("/usr/bin/sort"),
        pathlib.Path("/bin/sh"),
    ):
        if not command.is_file() or not os.access(command, os.X_OK):
            raise RuntimeError(f"required executable is unavailable: {command}")

    try:
        rclone_version = command_runner(
            ["/usr/bin/rclone", "version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"LANG": "C.UTF-8", "PATH": "/usr/bin:/bin"},
            timeout=10,
            check=False,
        )
    except OSError:
        raise RuntimeError("rclone 1.75.2 is unavailable") from None
    if (
        rclone_version.returncode != 0
        or not isinstance(rclone_version.stdout, bytes)
        or rclone_version.stdout.splitlines()[:1] != [b"rclone v1.75.2"]
    ):
        raise RuntimeError("rclone 1.75.2 is unavailable")

    bus_address = os.environ.get(
        "DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime_base}/bus"
    )
    if not bus_address or any(character.isspace() for character in bus_address):
        raise RuntimeError("real user bus address is unavailable or unsafe")
    manager_environment = {
        "DBUS_SESSION_BUS_ADDRESS": bus_address,
        "LANG": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "XDG_RUNTIME_DIR": str(runtime_base),
    }
    manager_operations = []

    def manager(*arguments):
        manager_operations.append(list(arguments))
        return command_runner(
            ["/usr/bin/systemctl", "--user", *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=manager_environment,
            timeout=30,
            check=False,
        )

    available = manager("show", "--property=Version", "--value")
    if available.returncode != 0:
        raise RuntimeError("real user manager is unavailable")
    if not available.stdout.strip():
        raise RuntimeError("real user manager returned no version")

    evidence_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not evidence_directory.is_dir() or evidence_directory.is_symlink():
        raise RuntimeError("evidence directory must be a directory")

    def parse_properties(output, required):
        observed = {}
        for line in output.splitlines():
            if line.count("=") < 1:
                raise RuntimeError("manager properties are malformed")
            key, value = line.split("=", 1)
            if key not in required or key in observed:
                raise RuntimeError("manager properties are malformed")
            observed[key] = value
        if set(observed) != set(required):
            raise RuntimeError("manager properties are incomplete")
        return observed

    manager_property_names = (
        "Id", "LoadState", "Transient", "ActiveState", "SubState",
        "Result", "MainPID", "ControlPID", "ExecStartPre", "ExecStopPost",
    )

    def show_fixture_unit(unit_name):
        shown = manager(
            "show", unit_name,
            *(f"--property={name}" for name in manager_property_names),
        )
        if shown.returncode != 0:
            raise RuntimeError("unable to read transient fixture unit state")
        return parse_properties(shown.stdout, manager_property_names)

    def require_unit_identity(properties, unit_name):
        if properties["Id"] != unit_name:
            raise RuntimeError("manager returned properties for the wrong unit")
        if properties["LoadState"] != "loaded":
            raise RuntimeError("transient fixture unit is not loaded")
        if properties["Transient"] != "yes":
            raise RuntimeError("fixture unit is not transient")

    def require_exec_result(properties, property_name, executable, status):
        record = properties[property_name]
        expression = re.compile(
            r"\{[^{}]*path=" + re.escape(str(executable))
            + r"(?:\s|;)[^{}]*code=exited(?:\s|;)[^{}]*status="
            + str(status) + r"(?:/[^\s;}]+)?(?:\s|;|})"
        )
        if expression.search(record) is None:
            raise RuntimeError(
                f"{property_name} manager execution result is not qualifying"
            )

    def read_hook_evidence(hooks, hook_name):
        result = {}
        for suffix in (
            "status", "stdout", "stderr", "sentinel-present",
            "sentinel-absent", "environment-names",
        ):
            path = hooks / f"{hook_name}.{suffix}"
            if not path.is_file() or path.is_symlink():
                raise RuntimeError(f"{hook_name} evidence is incomplete")
            result[suffix.replace("-", "_")] = path.read_text()
        return result

    def checked_teardown(unit_name, reference_owner, referenced):
        try:
            failure = None
            reset_properties = None
            stopped = manager("stop", unit_name)
            if stopped.returncode != 0:
                failure = RuntimeError(
                    f"{unit_name}: transient fixture teardown stop failed"
                )
                stopped_properties = None
                reset = None
            else:
                try:
                    stopped_properties = show_fixture_unit(unit_name)
                    require_unit_identity(stopped_properties, unit_name)
                except RuntimeError as error:
                    failure = error
                    reset = None
                else:
                    if (
                        stopped_properties["ActiveState"] not in ("inactive", "failed")
                        or stopped_properties["MainPID"] != "0"
                        or stopped_properties["ControlPID"] != "0"
                    ):
                        failure = RuntimeError(
                            f"{unit_name}: transient fixture retained a process after stop"
                        )
                        reset = None
                    else:
                        reset = manager("reset-failed", unit_name)
                        if reset.returncode != 0:
                            failure = RuntimeError(
                                f"{unit_name}: transient fixture failure reset failed"
                            )
                        else:
                            reset_properties = show_fixture_unit(unit_name)
                            require_unit_identity(reset_properties, unit_name)
                            if (
                                reset_properties["ActiveState"] != "inactive"
                                or reset_properties["MainPID"] != "0"
                                or reset_properties["ControlPID"] != "0"
                            ):
                                failure = RuntimeError(
                                    f"{unit_name}: transient fixture did not become inactive after reset"
                                )
            release_returncode = None
            if referenced:
                manager_operations.append(["unref-unit", unit_name])
                release_returncode = reference_owner.call("UnrefUnit", unit_name)
                if release_returncode < 0 and failure is None:
                    failure = RuntimeError(
                        f"{unit_name}: transient fixture reference release failed"
                    )
            if failure is not None:
                raise failure
            collected = manager("show", unit_name, "--property=LoadState", "--value")
            if collected.returncode != 0 or collected.stdout.strip() != "not-found":
                raise RuntimeError(f"{unit_name}: transient fixture was not collected")
            return {
                "stop_returncode": stopped.returncode,
                "after_stop": stopped_properties,
                "after_reset": reset_properties,
                "reset_failed_returncode": reset.returncode,
                "release_returncode": release_returncode,
                "collected_load_state": collected.stdout.strip(),
            }
        except Exception as error:
            raise RuntimeError(
                f"{unit_name}: checked teardown failed: {error}; fixture files retained at {root}"
            ) from error

    cleanup_safe = True
    with tempfile.TemporaryDirectory(
        prefix="proton-drive-cleanup-retention-", dir=runtime_base, delete=False,
    ) as temporary:
        manager_socket_alias = None
        try:
            root = pathlib.Path(temporary)
            root.chmod(0o700)
            home = root / "home"
            config_home = root / "config"
            config_parent = config_home / "rclone"
            data_home = root / "data"
            mount = data_home / "proton-drive-desktop/files"
            fixture_runtime = root / "runtime"
            private_runtime = fixture_runtime / "proton-drive-desktop"
            hooks = root / "hooks"
            for directory in (
                home, config_parent, mount, private_runtime, hooks,
            ):
                directory.mkdir(parents=True, mode=0o700, exist_ok=True)
                directory.chmod(0o700)
            mount.chmod(0o750)
            fixture_manager_directory = fixture_runtime / "systemd"
            fixture_manager_directory.mkdir(mode=0o700)
            fixture_manager_directory.chmod(0o700)
            alias_candidate = fixture_manager_directory / "private"
            alias_candidate.symlink_to(manager_socket)
            manager_socket_alias = alias_candidate
            aliased_socket_information = manager_socket_alias.stat()
            if (
                not stat.S_ISSOCK(aliased_socket_information.st_mode)
                or aliased_socket_information.st_dev
                != manager_socket_information.st_dev
                or aliased_socket_information.st_ino
                != manager_socket_information.st_ino
            ):
                raise RuntimeError(
                    "fixture manager socket alias does not name the validated socket"
                )
            config = config_parent / "proton-drive.conf"
            config.write_text("synthetic encrypted config; no credential\n")
            config.chmod(0o600)

            unique = hashlib.sha256(
                f"{os.getpid()}:{root}".encode("utf-8")
            ).hexdigest()[:16]
            unit_name = f"proton-drive-cleanup-retention-{unique}.service"
            service_token = b"proton-drive-desktop.service"
            source_helper = PROGRAM.read_bytes()
            replacement_count = source_helper.count(service_token)
            if replacement_count == 0:
                raise RuntimeError("helper contains no replaceable service binding")
            fixture_helper_bytes = source_helper.replace(
                service_token, unit_name.encode("ascii")
            )
            fixture_helper = root / "proton-drive-desktop-fixture"
            fixture_helper.write_bytes(fixture_helper_bytes)
            fixture_helper.chmod(0o700)

            lifecycle_runner = root / "run-lifecycle-hook"
            lifecycle_runner.write_text(textwrap.dedent("""\
                #!/bin/sh
                umask 077
                sentinel_name=PROTON_DRIVE_FIXTURE_SENTINEL
                if [ "${1-}" = --scrubbed ]; then
                    shift
                    [ "$#" -eq 4 ] || exit 96
                    hook_name=$1
                    evidence=$2
                    helper=$3
                    entrypoint=$4
                    /usr/bin/env | /usr/bin/cut -d= -f1 | /usr/bin/sort > \
                        "$evidence/$hook_name.environment-names"
                    if /usr/bin/grep -Fx -- "$sentinel_name" \
                        "$evidence/$hook_name.environment-names" >/dev/null; then
                        printf '%s\\n' false > "$evidence/$hook_name.sentinel-absent"
                        exit 97
                    fi
                    printf '%s\\n' true > "$evidence/$hook_name.sentinel-absent"
                    /usr/bin/env -i \
                        HOME="$HOME" \
                        LANG="$LANG" \
                        PATH="$PATH" \
                        XDG_CONFIG_HOME="$XDG_CONFIG_HOME" \
                        XDG_DATA_HOME="$XDG_DATA_HOME" \
                        XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
                        "$helper" "$entrypoint" \
                        > "$evidence/$hook_name.stdout" \
                        2> "$evidence/$hook_name.stderr"
                    hook_status=$?
                    printf '%s\\n' "$hook_status" > "$evidence/$hook_name.status"
                    exit "$hook_status"
                fi
                [ "$#" -eq 8 ] || exit 95
                hook_name=$1
                evidence=$2
                fixture_home=$3
                fixture_config=$4
                fixture_data=$5
                fixture_runtime=$6
                helper=$7
                entrypoint=$8
                if [ "${PROTON_DRIVE_FIXTURE_SENTINEL+x}" = x ]; then
                    printf '%s\\n' true > "$evidence/$hook_name.sentinel-present"
                else
                    printf '%s\\n' false > "$evidence/$hook_name.sentinel-present"
                    exit 98
                fi
                exec /usr/bin/env -i \
                    HOME="$fixture_home" \
                    LANG=C.UTF-8 \
                    PATH=/usr/bin:/bin \
                    XDG_CONFIG_HOME="$fixture_config" \
                    XDG_DATA_HOME="$fixture_data" \
                    XDG_RUNTIME_DIR="$fixture_runtime" \
                    "$0" --scrubbed "$hook_name" "$evidence" "$helper" "$entrypoint"
            """))
            lifecycle_runner.chmod(0o700)

            information = mount.stat()
            nonce = "12" * 32
            mount_tag = "proton-drive-desktop-" + "34" * 32
            common = {
                "mount": str(mount),
                "device": information.st_dev,
                "inode": information.st_ino,
                "created": True,
                "nonce": nonce,
                "mount_tag": mount_tag,
            }
            marker = private_runtime / "mountpoint.json"
            phase = private_runtime / "mountpoint-phase.json"
            marker.write_text(json.dumps(
                {**common, "mount_id": "91"}, separators=(",", ":")
            ))
            phase.write_text(json.dumps(
                {"phase": "cleanup-retained", **common}, separators=(",", ":")
            ))
            marker.chmod(0o600)
            phase.chmod(0o600)
            os.setxattr(
                mount,
                "user.proton-drive-desktop.identity",
                nonce.encode("ascii"),
            )
            os.setxattr(mount, "user.keep", b"preserve-fixture-xattr")
            before = real_manager_cleanup_retention_snapshot(
                mount, marker, phase
            )
            if before["directory"]["contents"]:
                raise RuntimeError("synthetic recovery mountpoint is not empty")
            expected_xattrs = dict(before["directory"]["xattrs_hex"])
            if expected_xattrs.pop("user.proton-drive-desktop.identity", None) != nonce.encode("ascii").hex():
                raise RuntimeError("synthetic recovery mountpoint has the wrong product identity")

            explicit_stop_environment = {
                "DBUS_SESSION_BUS_ADDRESS": bus_address,
                "HOME": str(home),
                "LANG": "C.UTF-8",
                "PATH": "/usr/bin:/bin",
                "XDG_CONFIG_HOME": str(config_home),
                "XDG_DATA_HOME": str(data_home),
                "XDG_RUNTIME_DIR": str(fixture_runtime),
            }
            lifecycle_arguments = (
                str(hooks), str(home), str(config_home), str(data_home),
                str(fixture_runtime), str(fixture_helper),
            )
            start_pre_command = shlex.join([
                str(lifecycle_runner), "start-pre", *lifecycle_arguments, "_prepare",
            ])
            post_stop_command = shlex.join([
                str(lifecycle_runner), "post-stop", *lifecycle_arguments, "_post-stop",
            ])
            sentinel_name = "PROTON_DRIVE_FIXTURE_SENTINEL"
            sentinel_value = "nonsecret-fixture-sentinel-7b36"
            transient_command = [
                "/usr/bin/systemd-run", "--user", f"--unit={unit_name}",
                "--no-ask-password", "--no-pager", "--quiet",
                "--expand-environment=no", "--service-type=oneshot",
                f"--setenv={sentinel_name}={sentinel_value}",
                "--property=CollectMode=inactive",
                "--property=Restart=no", "--property=UMask=0077",
                "--property=TimeoutStartSec=15s",
                "--property=TimeoutStopSec=15s",
                f"--property=ExecStartPre={start_pre_command}",
                f"--property=ExecStopPost={post_stop_command}",
                "/usr/bin/true",
            ]
            loaded = manager("show", unit_name, "--property=LoadState", "--value")
            if loaded.returncode != 0 or loaded.stdout.strip() != "not-found":
                raise RuntimeError(f"fixture unit name is already loaded: {unit_name}")

            qualification = None
            teardown = None
            transient_created = False
            referenced = False
            reference_owner = None
            try:
                manager_operations.append(["start-transient-unit", unit_name])
                cleanup_safe = False
                launch_error = None
                automatic_start = None
                try:
                    automatic_start = command_runner(
                        transient_command,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        env=manager_environment,
                        timeout=30,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired) as error:
                    launch_error = error
                launch_diagnostic = (
                    str(launch_error) if launch_error is not None
                    else f"exit {automatic_start.returncode}: {automatic_start.stderr.strip()}"
                )
                try:
                    loaded_after_start = manager(
                        "show", unit_name, "--property=LoadState", "--value"
                    )
                except (OSError, subprocess.TimeoutExpired) as error:
                    raise RuntimeError(
                        f"{unit_name}: launch {launch_diagnostic}; unable to determine unit state: {error}; "
                        f"fixture files retained at {root}"
                    ) from error
                if (
                    loaded_after_start.returncode != 0
                    or loaded_after_start.stdout.strip() not in ("loaded", "not-found")
                ):
                    raise RuntimeError(
                        f"{unit_name}: launch {launch_diagnostic}; unable to determine transient fixture load state: "
                        f"{loaded_after_start.stdout.strip()} {loaded_after_start.stderr.strip()}; "
                        f"fixture files retained at {root}"
                    )
                transient_created = loaded_after_start.stdout.strip() == "loaded"
                if not transient_created:
                    if (
                        isinstance(launch_error, subprocess.TimeoutExpired)
                        or (automatic_start is not None and automatic_start.returncode != 0)
                    ):
                        raise RuntimeError(
                            f"{unit_name}: launch outcome unresolved: {launch_diagnostic}; "
                            f"fixture files retained at {root}; later checked unit cleanup is required"
                        ) from launch_error
                    cleanup_safe = True
                    if launch_error is not None:
                        raise RuntimeError(f"{unit_name}: transient fixture launch failed: {launch_error}") from launch_error
                    raise RuntimeError(
                        f"{unit_name}: transient fixture launch failed "
                        f"(exit {automatic_start.returncode}): "
                        + automatic_start.stderr.strip()
                    )
                owner_factory = (
                    PersistentSystemdUnitReference
                    if reference_owner_factory is None
                    else reference_owner_factory
                )
                reference_owner = owner_factory()
                manager_operations.append(["ref-unit", unit_name])
                reference_returncode = reference_owner.call("RefUnit", unit_name)
                if reference_returncode < 0:
                    raise RuntimeError(
                        f"{unit_name}: unable to reference transient fixture unit"
                    )
                referenced = True
                manager_after_start = show_fixture_unit(unit_name)
                require_unit_identity(manager_after_start, unit_name)
                if launch_error is not None:
                    raise RuntimeError(f"{unit_name}: transient fixture launch failed: {launch_error}") from launch_error
                if automatic_start.returncode == 0:
                    raise RuntimeError("fixture startup unexpectedly succeeded")
                if (
                    manager_after_start["ActiveState"] != "failed"
                    or manager_after_start["SubState"] != "failed"
                    or manager_after_start["Result"] != "exit-code"
                    or manager_after_start["MainPID"] != "0"
                    or manager_after_start["ControlPID"] != "0"
                ):
                    raise RuntimeError("transient fixture has the wrong failed state")
                require_exec_result(
                    manager_after_start, "ExecStartPre", lifecycle_runner, 1
                )
                require_exec_result(
                    manager_after_start, "ExecStopPost", lifecycle_runner, 0
                )
                hook_evidence = {
                    name: read_hook_evidence(hooks, name)
                    for name in ("start-pre", "post-stop")
                }
                required_environment_names = {
                    "HOME", "LANG", "PATH", "XDG_CONFIG_HOME",
                    "XDG_DATA_HOME", "XDG_RUNTIME_DIR",
                }
                supported_shell_environment_names = {"PWD", "SHLVL", "_"}
                for name in ("start-pre", "post-stop"):
                    if hook_evidence[name]["sentinel_present"] != "true\n":
                        raise RuntimeError(
                            f"{sentinel_name} was absent before lifecycle scrub"
                        )
                    if hook_evidence[name]["sentinel_absent"] != "true\n":
                        raise RuntimeError(
                            f"{sentinel_name} reached a scrubbed lifecycle hook"
                        )
                    observed_environment_names = (
                        hook_evidence[name]["environment_names"].splitlines()
                    )
                    observed_environment_name_set = set(observed_environment_names)
                    if (
                        len(observed_environment_names)
                        != len(observed_environment_name_set)
                        or not required_environment_names.issubset(
                            observed_environment_name_set
                        )
                        or observed_environment_name_set
                        - required_environment_names
                        - supported_shell_environment_names
                    ):
                        raise RuntimeError(
                            f"{name} lifecycle environment was not minimal"
                        )
                if (
                    hook_evidence["start-pre"]["status"] != "1\n"
                    or hook_evidence["start-pre"]["stdout"]
                    or hook_evidence["start-pre"]["stderr"]
                    != INTERRUPTED_CLEANUP_DIAGNOSTIC + "\n"
                ):
                    raise RuntimeError(
                        "ExecStartPre did not reach interrupted cleanup exactly"
                    )
                if (
                    hook_evidence["post-stop"]["status"] != "0\n"
                    or hook_evidence["post-stop"]["stdout"]
                    or hook_evidence["post-stop"]["stderr"]
                ):
                    raise RuntimeError("ExecStopPost produced an unexpected diagnostic")
                after_failed_start = real_manager_cleanup_retention_snapshot(
                    mount, marker, phase
                )
                if after_failed_start != before:
                    raise RuntimeError(
                        "failed automatic startup changed retained recovery evidence"
                    )

                manager_operations.append(["public-helper-stop", unit_name])
                explicit_stop = command_runner(
                    [str(fixture_helper), "stop"],
                    cwd=root,
                    env=explicit_stop_environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=30,
                    check=False,
                )
                if (
                    explicit_stop.returncode != 0
                    or explicit_stop.stdout != "stopped\n"
                    or explicit_stop.stderr
                ):
                    raise RuntimeError(
                        "isolated explicit stop failed: "
                        + explicit_stop.stderr.strip()
                    )
                after_explicit_stop = real_manager_cleanup_retention_snapshot(
                    mount, marker, phase
                )
                if (
                    after_explicit_stop["marker"] is not None
                    or after_explicit_stop["phase"] is not None
                ):
                    raise RuntimeError("explicit stop retained private recovery records")
                before_directory = before["directory"]
                after_directory = after_explicit_stop["directory"]
                for key in ("device", "inode", "uid", "mode", "contents"):
                    if after_directory[key] != before_directory[key]:
                        raise RuntimeError(
                            f"explicit stop changed directory {key}"
                        )
                if after_directory["xattrs_hex"] != expected_xattrs:
                    raise RuntimeError("explicit stop changed retained non-product xattrs")
                manager_after_stop = show_fixture_unit(unit_name)
                require_unit_identity(manager_after_stop, unit_name)
                if (
                    manager_after_stop["ActiveState"] not in ("inactive", "failed")
                    or manager_after_stop["MainPID"] != "0"
                    or manager_after_stop["ControlPID"] != "0"
                ):
                    raise RuntimeError("explicit stop retained a fixture process")

                qualification = {
                    "automatic_start_returncode": automatic_start.returncode,
                    "manager_after_start": manager_after_start,
                    "hooks": hook_evidence,
                    "before": before,
                    "after_failed_start": after_failed_start,
                    "explicit_stop": {
                        "returncode": explicit_stop.returncode,
                        "stdout": explicit_stop.stdout,
                        "stderr": explicit_stop.stderr,
                    },
                    "after_explicit_stop": after_explicit_stop,
                    "manager_after_explicit_stop": manager_after_stop,
                }
            finally:
                try:
                    if transient_created:
                        teardown = checked_teardown(
                            unit_name, reference_owner, referenced
                        )
                        cleanup_safe = True
                finally:
                    if reference_owner is not None:
                        reference_owner.close()

            if qualification is None or teardown is None:
                raise RuntimeError("real user-manager qualification produced no receipt")
            prohibited_operations = {"daemon-reload", "link", "show-environment"}
            if any(
                operation and operation[0] in prohibited_operations
                for operation in manager_operations
            ):
                raise RuntimeError("fixture used a manager-wide or linked-unit operation")
            for operation in manager_operations:
                if operation[:1] in (
                    ["stop"], ["reset-failed"], ["ref-unit"], ["unref-unit"],
                    ["start-transient-unit"], ["public-helper-stop"],
                ):
                    if len(operation) != 2 or operation[1] != unit_name:
                        raise RuntimeError("fixture operation targeted the wrong unit")
                if operation[:1] == ["show"] and len(operation) > 1:
                    if operation[1].endswith(".service") and operation[1] != unit_name:
                        raise RuntimeError("fixture operation targeted the wrong unit")

            receipt = {
                "fixture": "proton-drive-cleanup-retention/v2",
                "unit": unit_name,
                "source_helper_sha256": hashlib.sha256(source_helper).hexdigest(),
                "fixture_helper_sha256": hashlib.sha256(
                    fixture_helper_bytes
                ).hexdigest(),
                "service_name_replacements": replacement_count,
                "fixture_helper_change": "unique-test-unit-binding-only",
                "transient_interface": "systemd-run/StartTransientUnit",
                "sentinel": {
                    "name": sentinel_name,
                    "present_before_scrub": True,
                    "absent_after_scrub": True,
                },
                "manager_operations": manager_operations,
                **qualification,
                "teardown": teardown,
            }
            receipt_path = evidence_directory / f"{unit_name}.json"
            if receipt_path.exists() or receipt_path.is_symlink():
                raise RuntimeError(f"refusing to overwrite evidence: {receipt_path}")
            receipt_text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        finally:
            alias_cleanup_error = None
            if manager_socket_alias is not None:
                try:
                    alias_information = manager_socket_alias.lstat()
                    if (
                        not stat.S_ISLNK(alias_information.st_mode)
                        or os.readlink(manager_socket_alias) != str(manager_socket)
                    ):
                        raise RuntimeError(
                            "fixture manager socket alias changed unexpectedly"
                        )
                    manager_socket_alias.unlink()
                except (OSError, RuntimeError) as error:
                    alias_cleanup_error = error
                    cleanup_safe = False
            if cleanup_safe:
                shutil.rmtree(temporary)
            if alias_cleanup_error is not None:
                raise RuntimeError(
                    "fixture manager socket alias cleanup failed: "
                    f"{alias_cleanup_error}; fixture files retained at {root}"
                ) from alias_cleanup_error

    descriptor, temporary_receipt_name = tempfile.mkstemp(
        prefix=f".{receipt_path.name}.",
        suffix=".tmp",
        dir=evidence_directory,
    )
    temporary_receipt = pathlib.Path(temporary_receipt_name)
    try:
        with os.fdopen(descriptor, "w") as receipt_file:
            descriptor = -1
            receipt_file.write(receipt_text)
            receipt_file.flush()
            os.fchmod(receipt_file.fileno(), 0o600)
        os.replace(temporary_receipt, receipt_path)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        with contextlib.suppress(FileNotFoundError):
            temporary_receipt.unlink()
        raise
    return receipt_path


class SyntheticUnitReferenceOwner:
    def __init__(self, boundary):
        self.boundary = boundary
        self.calls = []
        self.closed = False

    def call(self, method, unit_name):
        self.calls.append((method, unit_name))
        if self.closed:
            return -errno.ENOTCONN
        if unit_name != self.boundary.unit:
            raise AssertionError(f"wrong reference unit: {unit_name!r}")
        if method == "RefUnit":
            self.boundary.reference_connection = self
            self.boundary.referenced = True
            if self.boundary.fault == "reference-disconnect":
                self.close()
            return 0
        if method == "UnrefUnit":
            if self.boundary.fault == "teardown-release-exception":
                raise OSError("constructed release exception")
            if self.boundary.fault == "release":
                return -errno.EIO
            if (
                self.boundary.reference_connection is not self
                or not self.boundary.referenced
            ):
                return -errno.ENXIO
            self.boundary.referenced = False
            return 0
        raise AssertionError(f"unexpected reference operation: {method!r}")

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.boundary.reference_connection is self:
            self.boundary.reference_connection = None
            self.boundary.referenced = False


class SyntheticRealManagerBoundary:
    sentinel_name = "PROTON_DRIVE_FIXTURE_SENTINEL"
    sentinel_value = "nonsecret-fixture-sentinel-7b36"
    lifecycle_environment_names = (
        "HOME",
        "LANG",
        "PATH",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_RUNTIME_DIR",
    )

    def __init__(self, fault=None):
        self.fault = fault
        self.calls = []
        self.created = False
        self.reset = False
        self.referenced = False
        self.reference_connection = None
        self.reference_owners = []
        self.state = "failed"
        self.unit = None
        self.launcher = None
        self.hooks = None
        self.mount = None
        self.marker = None
        self.phase = None
        self.teardown_started = False
        self.shell_environment_names = {}
        self.helper_environment_names = {}

    def open_reference_owner(self):
        owner = SyntheticUnitReferenceOwner(self)
        self.reference_owners.append(owner)
        return owner

    @staticmethod
    def completed(arguments, returncode=0, stdout="", stderr=""):
        return subprocess.CompletedProcess(
            arguments, returncode, stdout=stdout, stderr=stderr
        )

    def _write_hook_evidence(self, command, status, diagnostic):
        fields = shlex.split(command)
        hook_name = fields[1]
        self.launcher = fields[0]
        self.hooks = pathlib.Path(fields[2])
        data_home = pathlib.Path(fields[5])
        fixture_runtime = pathlib.Path(fields[6])
        self.mount = data_home / "proton-drive-desktop/files"
        self.marker = fixture_runtime / "proton-drive-desktop/mountpoint.json"
        self.phase = fixture_runtime / "proton-drive-desktop/mountpoint-phase.json"
        if self.fault == "real-shell-environment":
            helper_names = self.hooks / f"{hook_name}.helper-environment-names"
            recording_helper = self.hooks / f"{hook_name}.recording-helper"
            recording_helper.write_text(
                "#!/usr/bin/python3\n"
                "import os\n"
                "import pathlib\n"
                "import sys\n"
                f"pathlib.Path({str(helper_names)!r}).write_text("
                '"".join(f"{name}\\n" for name in sorted(os.environ)))\n'
                + (
                    "sys.stderr.write("
                    + repr(INTERRUPTED_CLEANUP_DIAGNOSTIC + "\n")
                    + ")\nraise SystemExit(1)\n"
                    if status == 1
                    else "raise SystemExit(0)\n"
                )
            )
            recording_helper.chmod(0o700)
            arguments = [
                fields[0], *fields[1:7], str(recording_helper), fields[8]
            ]
            completed = subprocess.run(
                arguments,
                cwd=pathlib.Path(self.launcher).parent,
                env={
                    self.sentinel_name: self.sentinel_value,
                    "ARBITRARY_INHERITED": "constructed-inherited-value",
                    "PATH": "/usr/bin:/bin",
                },
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
                check=False,
            )
            if completed.returncode != status:
                raise AssertionError(
                    f"real lifecycle runner returned {completed.returncode}"
                )
            self.shell_environment_names[hook_name] = set(
                (self.hooks / f"{hook_name}.environment-names")
                .read_text()
                .splitlines()
            )
            self.helper_environment_names[hook_name] = set(
                helper_names.read_text().splitlines()
            )
            return
        present = "true\n"
        absent = "false\n" if self.fault == "sentinel-leak" else "true\n"
        names = list(self.lifecycle_environment_names)
        if self.fault == "sentinel-leak":
            names.append(self.sentinel_name)
        (self.hooks / f"{hook_name}.sentinel-present").write_text(present)
        (self.hooks / f"{hook_name}.sentinel-absent").write_text(absent)
        (self.hooks / f"{hook_name}.environment-names").write_text(
            "".join(f"{name}\n" for name in sorted(names))
        )
        (self.hooks / f"{hook_name}.stdout").write_text("")
        (self.hooks / f"{hook_name}.stderr").write_text(diagnostic)
        (self.hooks / f"{hook_name}.status").write_text(f"{status}\n")

    def _manager_properties(self):
        identifier = (
            "proton-drive-wrong-unit.service"
            if self.fault == "wrong-unit"
            else self.unit
        )
        active = "failed" if self.state == "failed" else "inactive"
        substate = "failed" if self.state == "failed" else "dead"
        result = "exit-code" if self.state == "failed" else "success"
        main_pid = "4242" if self.fault == "process-remains" else "0"
        return "\n".join((
            f"Id={identifier}",
            "LoadState=loaded",
            "Transient=yes",
            f"ActiveState={active}",
            f"SubState={substate}",
            f"Result={result}",
            f"MainPID={main_pid}",
            "ControlPID=0",
            (
                "ExecStartPre={ path=" + str(self.launcher)
                + " ; argv[]=" + str(self.launcher)
                + " start-pre ; code=exited ; status=1 }"
            ),
            (
                "ExecStopPost={ path=" + str(self.launcher)
                + " ; argv[]=" + str(self.launcher)
                + " post-stop ; code=exited ; status=0 }"
            ),
        )) + "\n"

    def __call__(self, arguments, **kwargs):
        arguments = list(arguments)
        self.calls.append(arguments)
        if arguments == ["/usr/bin/rclone", "version"]:
            if self.fault == "rclone-unavailable":
                raise FileNotFoundError("constructed missing rclone")
            version = (
                b"rclone v0.0.0\n"
                if self.fault == "wrong-rclone"
                else RCLONE_VERSION_OUTPUT
            )
            return self.completed(arguments, stdout=version)

        if arguments[:2] == ["/usr/bin/systemctl", "--user"]:
            operation = arguments[2:]
            if operation == ["show", "--property=Version", "--value"]:
                return self.completed(arguments, stdout="257\n")
            if "daemon-reload" in operation or "show-environment" in operation:
                raise AssertionError(f"manager-wide operation: {operation!r}")
            if (
                self.unit is None
                and operation[:1] == ["show"]
                and operation[-2:] == ["--property=LoadState", "--value"]
            ):
                self.unit = operation[1]
            if operation[:2] == ["show", self.unit]:
                if self.teardown_started:
                    if operation[-2:] == ["--property=LoadState", "--value"]:
                        if self.fault == "teardown-collection-exception":
                            raise OSError("constructed collection exception")
                    elif self.fault == "teardown-show-failure":
                        return self.completed(arguments, 1, stderr="constructed show failure")
                    elif self.fault == "teardown-show-malformed":
                        return self.completed(arguments, stdout="malformed")
                    elif self.fault == "teardown-show-wrong-identity":
                        return self.completed(arguments, stdout=self._manager_properties().replace(f"Id={self.unit}", "Id=wrong.service"))
                    elif self.fault == "teardown-show-exception":
                        raise OSError("constructed show exception")
                if operation[-2:] == ["--property=LoadState", "--value"]:
                    if self.created and self.fault == "launch-probe-unavailable":
                        return self.completed(arguments, 1, stderr="constructed unavailable probe")
                    if self.created and self.fault == "launch-probe-malformed":
                        return self.completed(arguments, stdout="constructed malformed probe")
                    if self.created and self.fault == "launch-probe-timeout":
                        raise subprocess.TimeoutExpired(arguments, 10)

                    if not self.created or (self.reset and not self.referenced):
                        load_state = (
                            "loaded" if self.fault == "collection" and self.reset
                            else "not-found"
                        )
                        return self.completed(
                            arguments, stdout=f"{load_state}\n"
                        )
                    return self.completed(arguments, stdout="loaded\n")
                return self.completed(arguments, stdout=self._manager_properties())
            if operation == ["stop", self.unit]:
                self.teardown_started = True
                if self.fault == "teardown-stop-exception":
                    raise OSError("constructed stop exception")
                if self.fault == "teardown-stop-timeout":
                    raise subprocess.TimeoutExpired(arguments, 10)
                if not self.created:
                    return self.completed(arguments, 1, stderr="constructed absent unit")
                if self.fault == "manager-stop":
                    return self.completed(arguments, 1, stderr="constructed stop fault")
                if self.fault not in ("stop-retains-failure", "reset-retains-failure"):
                    self.state = "inactive"
                return self.completed(arguments)
            if operation == ["reset-failed", self.unit]:
                if self.fault == "teardown-reset-exception":
                    raise OSError("constructed reset exception")
                if self.fault == "reset-failed":
                    return self.completed(arguments, 1, stderr="constructed reset fault")
                self.reset = True
                if self.fault != "reset-retains-failure":
                    self.state = "inactive"
                return self.completed(arguments)
            raise AssertionError(f"wrong or unexpected manager operation: {operation!r}")

        if arguments[0] == "/usr/bin/systemd-run":
            self.unit = next(
                value.removeprefix("--unit=")
                for value in arguments if value.startswith("--unit=")
            )
            if self.fault == "launch-rejected":
                return self.completed(arguments, 1, stderr="constructed launcher rejection")
            if self.fault == "launch-exception-before-creation":
                raise OSError("constructed launch exception")
            if self.fault == "launch-timeout-before-creation":
                raise subprocess.TimeoutExpired(arguments, 30)

            properties = [
                value.removeprefix("--property=")
                for value in arguments if value.startswith("--property=")
            ]
            pre = next(
                value.removeprefix("ExecStartPre=")
                for value in properties if value.startswith("ExecStartPre=")
            )
            post = next(
                value.removeprefix("ExecStopPost=")
                for value in properties if value.startswith("ExecStopPost=")
            )
            pre_diagnostic = (
                "constructed prerequisite failure\n"
                if self.fault == "wrong-diagnostic"
                else INTERRUPTED_CLEANUP_DIAGNOSTIC + "\n"
            )
            if self.fault == "launch-timeout-delayed-creation":
                self.pending_creation = (pre, post, pre_diagnostic)
                raise subprocess.TimeoutExpired(arguments, 30)
            if self.fault == "launch-response-lost-delayed-creation":
                self.pending_creation = (pre, post, pre_diagnostic)
                return self.completed(
                    arguments, 1, stderr="constructed connection lost after submission"
                )
            self._write_hook_evidence(pre, 1, pre_diagnostic)
            self._write_hook_evidence(post, 0, "")
            self.created = True
            if self.fault == "launch-timeout-after-creation":
                raise subprocess.TimeoutExpired(arguments, 30, stderr="constructed launcher timeout")
            return self.completed(arguments, 1, stderr="constructed expected start failure")

        if self.unit and pathlib.Path(arguments[0]).name == "proton-drive-desktop-fixture":
            if self.fault == "explicit-stop":
                return self.completed(
                    arguments, 1, stderr="constructed explicit-stop fault\n"
                )
            self.marker.unlink()
            self.phase.unlink()
            os.removexattr(
                self.mount,
                "user.proton-drive-desktop.identity",
                follow_symlinks=False,
            )
            if self.fault not in ("stop-retains-failure", "reset-retains-failure"):
                self.state = "inactive"
            return self.completed(arguments, stdout="stopped\n")

        raise AssertionError(f"unexpected command: {arguments!r}")


@unittest.skipUnless(sys.platform == "linux", "Linux user-manager fixture model")
class RealUserManagerCleanupRetentionFixtureTests(unittest.TestCase):
    def run_synthetic_fixture(self, fault=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = pathlib.Path(temporary.name)
        runtime = root / "run"
        evidence = root / "evidence"
        runtime.mkdir(mode=0o700)
        manager_directory = runtime / "systemd"
        manager_directory.mkdir(mode=0o700)
        manager_socket_path = manager_directory / "private"
        manager_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        manager_socket.bind(str(manager_socket_path))
        os.chmod(manager_socket_path, 0o600)
        self.addCleanup(manager_socket.close)
        boundary = SyntheticRealManagerBoundary(fault)
        boundary.manager_socket = manager_socket_path
        environment = mock.patch.dict(
            os.environ,
            {"XDG_RUNTIME_DIR": str(runtime)},
            clear=True,
        )
        environment.start()
        self.addCleanup(environment.stop)
        return evidence, boundary

    def test_private_runtime_manager_socket_alias_is_narrow_and_temporary(self):
        evidence, boundary = self.run_synthetic_fixture()
        source_before = boundary.manager_socket.lstat()
        alias_observations = []
        disposal_observations = []
        remove_tree = shutil.rmtree

        def observe_command(arguments, **kwargs):
            if pathlib.Path(arguments[0]).name == "proton-drive-desktop-fixture":
                alias = boundary.marker.parent.parent / "systemd/private"
                alias_information = alias.stat()
                alias_observations.append({
                    "is_symlink": alias.is_symlink(),
                    "target": os.readlink(alias),
                    "target_identity": (
                        alias_information.st_dev,
                        alias_information.st_ino,
                    ),
                })
            return boundary(arguments, **kwargs)

        def observe_disposal(path, *args, **kwargs):
            path = pathlib.Path(path)
            fixture_root = pathlib.Path(boundary.launcher).parent
            if path == fixture_root:
                alias = boundary.marker.parent.parent / "systemd/private"
                disposal_observations.append({
                    "alias_absent": not alias.exists() and not alias.is_symlink(),
                    "source_is_socket": stat.S_ISSOCK(
                        boundary.manager_socket.lstat().st_mode
                    ),
                })
            return remove_tree(path, *args, **kwargs)

        with mock.patch.object(shutil, "rmtree", observe_disposal):
            receipt_path = run_real_user_manager_cleanup_retention(
                evidence,
                command_runner=observe_command,
                reference_owner_factory=boundary.open_reference_owner,
            )

        self.assertTrue(receipt_path.is_file())
        self.assertEqual(1, len(alias_observations))
        self.assertEqual(True, alias_observations[0]["is_symlink"])
        self.assertEqual(
            str(boundary.manager_socket), alias_observations[0]["target"]
        )
        self.assertEqual(
            (source_before.st_dev, source_before.st_ino),
            alias_observations[0]["target_identity"],
        )
        self.assertEqual(
            [{"alias_absent": True, "source_is_socket": True}],
            disposal_observations,
        )
        source_after = boundary.manager_socket.lstat()
        self.assertEqual(
            (source_before.st_dev, source_before.st_ino),
            (source_after.st_dev, source_after.st_ino),
        )

    def test_additional_unrelated_xattr_is_preserved_against_the_baseline(self):
        for change in (None, "remove", "alter", "retain-product"):
            with self.subTest(change=change):
                evidence, boundary = self.run_synthetic_fixture()
                set_xattr = os.setxattr
                def with_extra_attribute(path, name, value, *args, **kwargs):
                    set_xattr(path, name, value, *args, **kwargs)
                    if name == "user.keep":
                        set_xattr(path, "user.additional", b"additional-fixture-value")
                def observe_command(arguments, **kwargs):
                    result = boundary(arguments, **kwargs)
                    if pathlib.Path(arguments[0]).name == "proton-drive-desktop-fixture":
                        if change == "remove":
                            os.removexattr(boundary.mount, "user.additional")
                        elif change == "alter":
                            set_xattr(boundary.mount, "user.additional", b"changed-value")
                        elif change == "retain-product":
                            set_xattr(boundary.mount, "user.proton-drive-desktop.identity", b"12" * 32)
                    return result
                with mock.patch.object(os, "setxattr", side_effect=with_extra_attribute):
                    if change is None:
                        receipt_path = run_real_user_manager_cleanup_retention(
                            evidence, command_runner=observe_command,
                            reference_owner_factory=boundary.open_reference_owner,
                        )
                        receipt = json.loads(receipt_path.read_text())
                        before = receipt["before"]["directory"]["xattrs_hex"]
                        after = receipt["after_explicit_stop"]["directory"]["xattrs_hex"]
                        self.assertEqual(b"additional-fixture-value".hex(), before["user.additional"])
                        self.assertEqual(before["user.additional"], after["user.additional"])
                        self.assertNotIn("user.proton-drive-desktop.identity", after)
                    else:
                        with self.assertRaisesRegex(RuntimeError, "changed retained non-product xattrs"):
                            run_real_user_manager_cleanup_retention(
                                evidence, command_runner=observe_command,
                                reference_owner_factory=boundary.open_reference_owner,
                            )
                        self.assertEqual([], list(evidence.glob("*.json")))

    def test_stopped_failed_unit_is_reset_before_reference_release(self):
        evidence, boundary = self.run_synthetic_fixture("stop-retains-failure")
        receipt_path = run_real_user_manager_cleanup_retention(
            evidence, command_runner=boundary,
            reference_owner_factory=boundary.open_reference_owner,
        )
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual("failed", receipt["manager_after_explicit_stop"]["ActiveState"])
        self.assertEqual("failed", receipt["teardown"]["after_stop"]["ActiveState"])
        self.assertEqual("inactive", receipt["teardown"]["after_reset"]["ActiveState"])
        self.assertEqual("0", receipt["teardown"]["after_reset"]["MainPID"])
        self.assertEqual("0", receipt["teardown"]["after_reset"]["ControlPID"])
        self.assertEqual("not-found", receipt["teardown"]["collected_load_state"])
        self.assertTrue(all(owner.closed for owner in boundary.reference_owners))
        self.assertFalse(pathlib.Path(boundary.launcher).exists())

    def test_unsuccessful_state_reset_cannot_publish_a_receipt(self):
        evidence, boundary = self.run_synthetic_fixture("reset-retains-failure")
        with self.assertRaisesRegex(RuntimeError, "did not become inactive after reset"):
            run_real_user_manager_cleanup_retention(
                evidence, command_runner=boundary,
                reference_owner_factory=boundary.open_reference_owner,
            )
        self.assertEqual([], list(evidence.glob("*.json")))
        self.assertTrue(pathlib.Path(boundary.launcher).exists())
        self.assertTrue(all(owner.closed for owner in boundary.reference_owners))

    def test_rejected_launcher_keeps_its_diagnostic_without_stopping_an_absent_unit(self):
        evidence, boundary = self.run_synthetic_fixture("launch-rejected")
        with self.assertRaisesRegex(RuntimeError, "constructed launcher rejection"):
            run_real_user_manager_cleanup_retention(
                evidence,
                command_runner=boundary,
                reference_owner_factory=boundary.open_reference_owner,
            )
        self.assertFalse(boundary.created)
        self.assertNotIn(["/usr/bin/systemctl", "--user", "stop", boundary.unit], boundary.calls)
        self.assertEqual([], list(evidence.glob("*.json")))

    def test_timed_out_launcher_cleans_its_created_unit_before_disposing_files(self):
        evidence, boundary = self.run_synthetic_fixture("launch-timeout-after-creation")
        runner = boundary
        stopped_with_files_present = []
        def observe_stop(arguments, **kwargs):
            if arguments == ["/usr/bin/systemctl", "--user", "stop", boundary.unit]:
                stopped_with_files_present.append(pathlib.Path(boundary.launcher).exists())
            return runner(arguments, **kwargs)
        with self.assertRaises((RuntimeError, subprocess.TimeoutExpired)):
            run_real_user_manager_cleanup_retention(
                evidence, command_runner=observe_stop,
                reference_owner_factory=boundary.open_reference_owner,
            )
        self.assertEqual([True], stopped_with_files_present)
        self.assertTrue(boundary.reset)
        self.assertFalse(boundary.referenced)
        self.assertTrue(all(owner.closed for owner in boundary.reference_owners))
        self.assertEqual([], list(evidence.glob("*.json")))

    def test_unresolved_launch_probe_preserves_files_and_names_the_launch_failure(self):
        evidence, boundary = self.run_synthetic_fixture("launch-probe-unavailable")
        with self.assertRaises(RuntimeError) as failure:
            run_real_user_manager_cleanup_retention(
                evidence, command_runner=boundary,
                reference_owner_factory=boundary.open_reference_owner,
            )
        self.assertIn(boundary.unit, str(failure.exception))
        self.assertTrue(pathlib.Path(boundary.launcher).exists(), "unresolved unit still needs its fixture files")
        self.assertIn("constructed expected start failure", str(failure.exception))
        self.assertIn("constructed unavailable probe", str(failure.exception))
        self.assertEqual([], list(evidence.glob("*.json")))
        self.assertNotIn(["/usr/bin/systemctl", "--user", "stop", boundary.unit], boundary.calls)

    def test_unavailable_launch_outcome_does_not_invent_creation_or_collection(self):
        for fault in ("launch-probe-malformed", "launch-probe-timeout"):
            with self.subTest(fault=fault):
                evidence, boundary = self.run_synthetic_fixture(fault)
                with self.assertRaises(RuntimeError) as failure:
                    run_real_user_manager_cleanup_retention(
                        evidence, command_runner=boundary,
                        reference_owner_factory=boundary.open_reference_owner,
                    )
                self.assertIn(boundary.unit, str(failure.exception))
                self.assertIn("constructed expected start failure", str(failure.exception))
                self.assertIn("fixture files retained at", str(failure.exception))
                self.assertTrue(pathlib.Path(boundary.launcher).exists())
                self.assertNotIn(["/usr/bin/systemctl", "--user", "stop", boundary.unit], boundary.calls)
                self.assertEqual([], list(evidence.glob("*.json")))

    def test_launch_exceptions_before_creation_preserve_failure_without_teardown(self):
        for fault in ("launch-exception-before-creation",):
            with self.subTest(fault=fault):
                evidence, boundary = self.run_synthetic_fixture(fault)
                with self.assertRaises(RuntimeError) as failure:
                    run_real_user_manager_cleanup_retention(
                        evidence, command_runner=boundary,
                        reference_owner_factory=boundary.open_reference_owner,
                    )
                self.assertIn(boundary.unit, str(failure.exception))
                self.assertIn("transient fixture launch failed", str(failure.exception))
                self.assertFalse(boundary.created)
                self.assertNotIn(["/usr/bin/systemctl", "--user", "stop", boundary.unit], boundary.calls)
                self.assertEqual([], list(evidence.glob("*.json")))
                self.assertEqual(
                    [boundary.manager_socket.parent],
                    list((evidence.parent / "run").iterdir()),
                )
                self.assertTrue(stat.S_ISSOCK(boundary.manager_socket.lstat().st_mode))

    def test_unresolved_launch_preserves_inputs_for_late_creation(self):
        for fault in (
            "launch-timeout-before-creation", "launch-timeout-delayed-creation",
            "launch-response-lost-delayed-creation",
        ):
            with self.subTest(fault=fault):
                evidence, boundary = self.run_synthetic_fixture(fault)
                negative_probe = []
                launched = []
                def observe_command(arguments, **kwargs):
                    if arguments[0] == "/usr/bin/systemd-run":
                        launched.append(list(arguments))
                    result = boundary(arguments, **kwargs)
                    if (launched and arguments == ["/usr/bin/systemctl", "--user", "show",
                                                   boundary.unit, "--property=LoadState", "--value"]):
                        negative_probe.append(result.stdout.strip())
                    return result
                with self.assertRaises(RuntimeError) as failure:
                    run_real_user_manager_cleanup_retention(
                        evidence, command_runner=observe_command,
                        reference_owner_factory=boundary.open_reference_owner,
                    )
                self.assertEqual(["not-found"], negative_probe)
                self.assertFalse(boundary.created)
                pre = next(value.removeprefix("--property=ExecStartPre=")
                           for value in launched[0] if value.startswith("--property=ExecStartPre="))
                fields = shlex.split(pre)
                launcher = pathlib.Path(fields[0])
                helper = pathlib.Path(fields[7])
                self.assertTrue(launcher.is_file(), "late unit creation still needs its lifecycle runner")
                self.assertTrue(helper.is_file(), "late unit creation still needs its helper")
                self.assertIn(boundary.unit, str(failure.exception))
                self.assertIn("launch outcome unresolved", str(failure.exception))
                self.assertIn(str(launcher.parent), str(failure.exception))
                self.assertEqual([], list(evidence.glob("*.json")))
                self.assertFalse(boundary.teardown_started)
                self.assertFalse(boundary.reset)
                if fault in (
                    "launch-timeout-delayed-creation", "launch-response-lost-delayed-creation"
                ):
                    # Deliver the original queued creation only after the negative
                    # probe and the fixture's return. This is not a launcher retry.
                    delayed_pre, delayed_post, diagnostic = boundary.pending_creation
                    boundary._write_hook_evidence(delayed_pre, 1, diagnostic)
                    boundary._write_hook_evidence(delayed_post, 0, "")
                    boundary.created = True
                    self.assertTrue(boundary.hooks.joinpath("post-stop.status").is_file())
                    self.assertTrue(launcher.is_file())
                    self.assertTrue(helper.is_file())
                    self.assertEqual([], list(evidence.glob("*.json")))

    def test_teardown_failures_name_the_unit_and_keep_unresolved_files(self):
        cases = {
            "teardown-show-failure": "unable to read transient fixture unit state",
            "teardown-show-malformed": "manager properties are malformed",
            "teardown-show-wrong-identity": "manager returned properties for the wrong unit",
            "teardown-stop-exception": "constructed stop exception",
            "teardown-stop-timeout": "timed out",
            "teardown-show-exception": "constructed show exception",
            "teardown-reset-exception": "constructed reset exception",
            "teardown-release-exception": "constructed release exception",
            "teardown-collection-exception": "constructed collection exception",
        }
        for fault, diagnostic in cases.items():
            with self.subTest(fault=fault):
                evidence, boundary = self.run_synthetic_fixture(fault)
                with self.assertRaises((RuntimeError, OSError, subprocess.TimeoutExpired)) as failure:
                    run_real_user_manager_cleanup_retention(
                        evidence, command_runner=boundary,
                        reference_owner_factory=boundary.open_reference_owner,
                    )
                self.assertIn(boundary.unit, str(failure.exception))
                self.assertIn(diagnostic, str(failure.exception))
                self.assertTrue(pathlib.Path(boundary.launcher).exists())
                self.assertEqual([], list(evidence.glob("*.json")))
                self.assertTrue(all(owner.closed for owner in boundary.reference_owners))

    def test_only_exact_interrupted_cleanup_diagnostic_qualifies(self):
        evidence, boundary = self.run_synthetic_fixture()

        receipt_path = run_real_user_manager_cleanup_retention(
            evidence,
            command_runner=boundary,
            reference_owner_factory=boundary.open_reference_owner,
        )
        receipt = json.loads(receipt_path.read_text())

        self.assertEqual(
            INTERRUPTED_CLEANUP_DIAGNOSTIC + "\n",
            receipt["hooks"]["start-pre"]["stderr"],
        )
        self.assertEqual("1\n", receipt["hooks"]["start-pre"]["status"])
        self.assertEqual("", receipt["hooks"]["post-stop"]["stderr"])
        self.assertEqual("0\n", receipt["hooks"]["post-stop"]["status"])
        self.assertIn("status=1", receipt["manager_after_start"]["ExecStartPre"])
        self.assertIn("status=0", receipt["manager_after_start"]["ExecStopPost"])

    def test_temporary_root_disposal_failure_refuses_a_final_receipt(self):
        evidence, boundary = self.run_synthetic_fixture()
        temporary_directory = tempfile.TemporaryDirectory

        class DisposalFailure:
            def __init__(self, *args, **kwargs):
                self.temporary = temporary_directory(*args, **kwargs)

            def __enter__(self):
                return self.temporary.__enter__()

            def __exit__(self, *args):
                self.temporary.__exit__(*args)
                raise OSError("constructed temporary-root disposal failure")

        with mock.patch.object(tempfile, "TemporaryDirectory", DisposalFailure):
            with self.assertRaisesRegex(
                OSError, "constructed temporary-root disposal failure"
            ):
                run_real_user_manager_cleanup_retention(
                    evidence,
                    command_runner=boundary,
                    reference_owner_factory=boundary.open_reference_owner,
                )

        self.assertEqual([], list(evidence.glob("*.json")))

    def test_receipt_publication_observes_a_disposed_temporary_root(self):
        evidence, boundary = self.run_synthetic_fixture()
        replace = os.replace
        publications = []

        def observe_publication(source, destination):
            source = pathlib.Path(source)
            destination = pathlib.Path(destination)
            fixture_root = pathlib.Path(boundary.launcher).parent
            publications.append({
                "root_absent": not fixture_root.exists(),
                "source_parent": source.parent,
                "destination_parent": destination.parent,
                "source_mode": stat.S_IMODE(source.stat().st_mode),
            })
            return replace(source, destination)

        with mock.patch.object(os, "replace", observe_publication):
            receipt_path = run_real_user_manager_cleanup_retention(
                evidence,
                command_runner=boundary,
                reference_owner_factory=boundary.open_reference_owner,
            )

        self.assertEqual([receipt_path], list(evidence.glob("*.json")))
        self.assertEqual(0o600, stat.S_IMODE(receipt_path.stat().st_mode))
        self.assertEqual(1, len(publications))
        self.assertEqual(
            {
                "root_absent": True,
                "source_parent": evidence,
                "destination_parent": evidence,
                "source_mode": 0o600,
            },
            publications[0],
        )

    def test_one_reference_owner_spans_recovery_and_releases_its_own_reference(self):
        evidence, boundary = self.run_synthetic_fixture()

        receipt_path = run_real_user_manager_cleanup_retention(
            evidence,
            command_runner=boundary,
            reference_owner_factory=boundary.open_reference_owner,
        )
        receipt = json.loads(receipt_path.read_text())

        self.assertEqual(1, len(boundary.reference_owners))
        owner = boundary.reference_owners[0]
        self.assertEqual(
            [
                ("RefUnit", receipt["unit"]),
                ("UnrefUnit", receipt["unit"]),
            ],
            owner.calls,
        )
        self.assertTrue(owner.closed)
        self.assertLess(
            receipt["manager_operations"].index(["ref-unit", receipt["unit"]]),
            receipt["manager_operations"].index(
                ["public-helper-stop", receipt["unit"]]
            ),
        )
        self.assertLess(
            receipt["manager_operations"].index(
                ["public-helper-stop", receipt["unit"]]
            ),
            receipt["manager_operations"].index(["unref-unit", receipt["unit"]]),
        )

    def test_reference_owner_disconnect_refuses_receipt_after_checked_cleanup(self):
        evidence, boundary = self.run_synthetic_fixture("reference-disconnect")

        with self.assertRaisesRegex(RuntimeError, "reference release failed"):
            run_real_user_manager_cleanup_retention(
                evidence,
                command_runner=boundary,
                reference_owner_factory=boundary.open_reference_owner,
            )

        self.assertEqual([], list(evidence.glob("*.json")))
        self.assertEqual(1, len(boundary.reference_owners))
        self.assertTrue(boundary.reference_owners[0].closed)
        self.assertTrue(boundary.reset)
        self.assertIn(
            ["/usr/bin/systemctl", "--user", "stop", boundary.unit],
            boundary.calls,
        )

    def test_generated_lifecycle_runner_scrubs_shell_and_helper_environments(self):
        evidence, boundary = self.run_synthetic_fixture("real-shell-environment")

        receipt_path = run_real_user_manager_cleanup_retention(
            evidence,
            command_runner=boundary,
            reference_owner_factory=boundary.open_reference_owner,
        )

        required = set(boundary.lifecycle_environment_names)
        allowed_shell_names = required | {"PWD", "SHLVL", "_"}
        for hook_name in ("start-pre", "post-stop"):
            with self.subTest(hook=hook_name):
                observed_shell_names = boundary.shell_environment_names[hook_name]
                self.assertLessEqual(required, observed_shell_names)
                self.assertLessEqual(observed_shell_names, allowed_shell_names)
                self.assertEqual(
                    required, boundary.helper_environment_names[hook_name]
                )
                self.assertNotIn(
                    boundary.sentinel_name,
                    boundary.shell_environment_names[hook_name],
                )
                self.assertNotIn(
                    "ARBITRARY_INHERITED",
                    boundary.shell_environment_names[hook_name],
                )
        self.assertTrue(receipt_path.is_file())
        self.assertIn(
            ["/usr/bin/systemctl", "--user", "reset-failed", boundary.unit],
            boundary.calls,
        )

    def test_constructed_sentinel_leak_is_rejected_without_its_value(self):
        evidence, boundary = self.run_synthetic_fixture("sentinel-leak")

        with self.assertRaisesRegex(
            RuntimeError, boundary.sentinel_name
        ) as failure:
            run_real_user_manager_cleanup_retention(
                evidence,
                command_runner=boundary,
                reference_owner_factory=boundary.open_reference_owner,
            )

        retained_text = str(failure.exception)
        for path in evidence.rglob("*") if evidence.exists() else ():
            if path.is_file() and not path.is_symlink():
                retained_text += path.read_text(errors="replace")
        self.assertNotIn(boundary.sentinel_value, retained_text)
        self.assertEqual([], list(evidence.glob("*.json")))

    def test_transient_fixture_never_reloads_or_links_manager_units(self):
        evidence, boundary = self.run_synthetic_fixture()

        receipt_path = run_real_user_manager_cleanup_retention(
            evidence,
            command_runner=boundary,
            reference_owner_factory=boundary.open_reference_owner,
        )
        receipt = json.loads(receipt_path.read_text())

        flattened = [argument for call in boundary.calls for argument in call]
        self.assertNotIn("/usr/bin/busctl", flattened)
        self.assertNotIn("daemon-reload", flattened)
        self.assertNotIn("show-environment", flattened)
        self.assertNotIn("link", flattened)
        self.assertEqual(
            "systemd-run/StartTransientUnit", receipt["transient_interface"]
        )
        for operation in receipt["manager_operations"]:
            if operation[0] in {"stop", "reset-failed"}:
                self.assertEqual([operation[0], receipt["unit"]], operation)
            elif operation[0] == "show" and operation[1].endswith(".service"):
                self.assertEqual(receipt["unit"], operation[1])

    def test_constructed_wrong_unit_properties_cannot_qualify(self):
        evidence, boundary = self.run_synthetic_fixture("wrong-unit")

        with self.assertRaisesRegex(RuntimeError, "wrong unit"):
            run_real_user_manager_cleanup_retention(
                evidence,
                command_runner=boundary,
                reference_owner_factory=boundary.open_reference_owner,
            )

        self.assertEqual([], list(evidence.glob("*.json")))

    def test_constructed_wrong_rclone_version_cannot_produce_a_receipt(self):
        calls = []

        def command_runner(arguments, **kwargs):
            calls.append(list(arguments))
            if arguments == ["/usr/bin/rclone", "version"]:
                return subprocess.CompletedProcess(
                    arguments, 0, stdout=b"rclone v0.0.0\n"
                )
            self.fail(f"manager operation followed wrong rclone: {arguments!r}")

        evidence, boundary = self.run_synthetic_fixture()
        with self.assertRaisesRegex(
            RuntimeError, "rclone 1.75.2 is unavailable"
        ):
            run_real_user_manager_cleanup_retention(
                evidence, command_runner=command_runner,
                reference_owner_factory=boundary.open_reference_owner,
            )

        self.assertEqual([["/usr/bin/rclone", "version"]], calls)
        self.assertFalse(evidence.exists())

    def test_constructed_unavailable_rclone_cannot_produce_a_receipt(self):
        evidence, boundary = self.run_synthetic_fixture("rclone-unavailable")

        with self.assertRaisesRegex(
            RuntimeError, "rclone 1.75.2 is unavailable"
        ):
            run_real_user_manager_cleanup_retention(
                evidence,
                command_runner=boundary,
                reference_owner_factory=boundary.open_reference_owner,
            )

        self.assertEqual(
            [["/usr/bin/rclone", "version"]], boundary.calls
        )
        self.assertFalse(evidence.exists())

    def test_constructed_prerequisite_diagnostic_cannot_qualify(self):
        evidence, boundary = self.run_synthetic_fixture("wrong-diagnostic")

        with self.assertRaisesRegex(
            RuntimeError, "did not reach interrupted cleanup exactly"
        ):
            run_real_user_manager_cleanup_retention(
                evidence,
                command_runner=boundary,
                reference_owner_factory=boundary.open_reference_owner,
            )

        self.assertEqual([], list(evidence.glob("*.json")))

    def test_each_constructed_teardown_fault_refuses_a_receipt(self):
        expected = {
            "explicit-stop": "isolated explicit stop failed",
            "manager-stop": "teardown stop failed",
            "process-remains": "retained a process after stop",
            "reset-failed": "failure reset failed",
            "release": "reference release failed",
            "collection": "was not collected",
        }
        for fault, diagnostic in expected.items():
            with self.subTest(constructed_fault=fault):
                evidence, boundary = self.run_synthetic_fixture(fault)

                with self.assertRaisesRegex(RuntimeError, diagnostic):
                    run_real_user_manager_cleanup_retention(
                        evidence,
                        command_runner=boundary,
                        reference_owner_factory=boundary.open_reference_owner,
                    )

                self.assertEqual([], list(evidence.glob("*.json")))

    def test_documented_real_manager_command_rejects_relative_evidence(self):
        guide = (ROOT / "docs/PROTON_DRIVE.md").read_text()
        procedure = guide.split(
            "### Qualify cleanup retention with a real user manager", 1
        )[1].split("Baloo's [settings schema]", 1)[0]
        documented_command = re.search(
            r"python3 tests/test_proton_drive_desktop\.py \\\n"
            r"  --real-user-manager-cleanup-retention \"\$evidence_dir\"",
            procedure,
        )
        self.assertIsNotNone(documented_command)

        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            result = subprocess.run(
                [
                    sys.executable,
                    str(pathlib.Path(__file__).resolve()),
                    "--real-user-manager-cleanup-retention",
                    "relative-evidence",
                ],
                cwd=root,
                env={"PYTHONDONTWRITEBYTECODE": "1"},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
                check=False,
            )

            self.assertEqual(1, result.returncode)
            self.assertEqual("", result.stdout)
            self.assertEqual("evidence directory must be absolute\n", result.stderr)
            self.assertFalse((root / "relative-evidence").exists())


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--real-user-manager-cleanup-retention":
        try:
            retained_receipt = run_real_user_manager_cleanup_retention(
                sys.argv[2]
            )
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            print(error, file=sys.stderr)
            raise SystemExit(1)
        print(retained_receipt)
        raise SystemExit(0)
    unittest.main()
