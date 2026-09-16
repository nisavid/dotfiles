from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tarfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.age_tooling_test_support import require_age_tooling_or_skip

ROOT = Path(__file__).resolve().parents[1]
PROVISIONER = ROOT / "scripts/provision-age-admission-signer"
REAL_BUILDER = ROOT / "scripts/build-age-admission-provider-fixture"
SOURCE_MODES = {
    "home/private_dot_local/bin/executable_proton-pass-age-admission": "100644",
    "home/private_dot_local/bin/executable_proton-pass-ensure-ready": "100755",
    "scripts/admit-age-envelopes": "100755",
    "scripts/agent_equipment_public_data.py": "100644",
    "scripts/build-age-admission-provider-fixture": "100755",
    "scripts/create-age-admission-receipt": "100755",
    "scripts/prepare-age-admission-recovery-preimage": "100755",
    "scripts/privacy-scan": "100755",
    "scripts/privacy_age_admission.py": "100644",
    "scripts/privacy_age_envelopes.py": "100644",
    "scripts/privacy_age_integrity_gate.py": "100755",
    "scripts/provision-age-admission-signer": "100755",
    "scripts/run-trusted-age-admission": "100755",
}


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("ascii")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    return subprocess.run(
        [
            "git",
            "-c",
            "protocol.allow=never",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-C",
            os.fspath(repository),
            *arguments,
        ],
        check=True,
        capture_output=True,
        env=environment,
        timeout=20,
    )


def selected_age_tooling_archive_or_skip() -> tuple[Path, str]:
    raw_archive = os.environ.get("AGE_TOOLING_ARCHIVE")
    expected_digest = os.environ.get("AGE_TOOLING_ARCHIVE_SHA256")
    message = (
        "set AGE_TOOLING_ARCHIVE and AGE_TOOLING_ARCHIVE_SHA256 to one "
        "checksum-pinned age archive for this runner"
    )
    if not raw_archive or not expected_digest:
        require_age_tooling_or_skip(message)
    if len(expected_digest) != 64 or any(
        character not in "0123456789abcdef" for character in expected_digest
    ):
        require_age_tooling_or_skip("AGE_TOOLING_ARCHIVE_SHA256 is invalid")
    archive = Path(raw_archive)
    if not archive.is_absolute():
        require_age_tooling_or_skip("AGE_TOOLING_ARCHIVE must be absolute")
    try:
        archive_data = archive.read_bytes()
    except OSError as error:
        require_age_tooling_or_skip(
            "the selected age tooling archive is unavailable", cause=error
        )
    if sha256(archive_data) != expected_digest:
        require_age_tooling_or_skip(
            "the selected age tooling archive checksum is invalid"
        )
    return archive, expected_digest


def trusted_path_ancestors_supported(path: Path) -> bool:
    owner = os.geteuid()
    current = path
    while True:
        info = current.lstat()
        writable = bool(info.st_mode & 0o022)
        root_owned_sticky = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid not in {0, owner}
            or writable
            and not root_owned_sticky
        ):
            return False
        parent = current.parent
        if parent == current:
            return True
        current = parent


class ProvisioningInputs:
    SIGNER = (
        b"-----BEGIN " + b"OPENSSH " + b"PRIVATE KEY-----\n"
        b"issue286-fast-fixture-private-key\n"
        b"-----END " + b"OPENSSH " + b"PRIVATE KEY-----\n"
    )
    LOGIN_CREDENTIAL = "p" + "st_issue286" + "::synthetic-token"

    def __init__(self, root: Path, *, real_local_tools: bool = False) -> None:
        root = root.resolve(strict=True)
        self.root = root
        self.real_local_tools = real_local_tools
        self.private = root / "private"
        self.private.mkdir(mode=0o700)
        self.owner_session = self.private / "owner-session"
        self.primary_session = self.private / "primary-session"
        self.owner_session.mkdir(mode=0o700)
        self.primary_session.mkdir(mode=0o700)
        self.source = root / "reviewed-source"
        self.source.mkdir(mode=0o700)
        self.manifest = root / "reviewed-source-manifest.json"
        self.archive = root / "age-v1.3.1-synthetic.tar.gz"
        self.request = self.private / "request.json"
        self.state = self.private / "operation"
        self.fake_bin = root / "bin"
        self.fake_bin.mkdir(mode=0o700)
        self.support_bin = root / "support-bin"
        self.support_bin.mkdir(mode=0o700)
        self.provider_state = self.private / "provider-state.json"
        self.provider_log = self.private / "provider-log.jsonl"
        self.control = self.private / "provider-control.json"
        self.child_marker = self.private / "provider-child.json"
        self.child_term_log = Path(os.fspath(self.child_marker) + ".terms")
        self.stored_signer = self.private / "provider-stored-signer"
        self.fake_home = self.private / "home"
        self.xdg_config = self.private / "xdg-config"
        self.xdg_state = self.private / "xdg-state"
        self.temporary_directory = self.private / "tmp"
        for directory in (
            self.fake_home,
            self.xdg_config,
            self.xdg_state,
            self.temporary_directory,
        ):
            directory.mkdir(mode=0o700)
        self._write_control({})
        self._write_provider_state()
        self._write_fake_pass_cli()
        if not real_local_tools:
            self._write_fake_ssh_keygen()
            self._write_fake_age_archive()
        else:
            self.archive, self.archive_sha256 = selected_age_tooling_archive_or_skip()
        self._write_support_bin()
        self._write_source_repository()
        self._write_request()

    def _write_support_bin(self) -> None:
        commands = ["git", "python3"]
        age_tooling_directory: Path | None = None
        if self.real_local_tools:
            raw_directory = os.environ.get("AGE_TOOLING_DIRECTORY")
            if not raw_directory or not Path(raw_directory).is_absolute():
                require_age_tooling_or_skip(
                    "AGE_TOOLING_DIRECTORY must select one absolute tooling directory"
                )
            try:
                age_tooling_directory = Path(raw_directory).resolve(strict=True)
            except OSError as error:
                require_age_tooling_or_skip(
                    "AGE_TOOLING_DIRECTORY is unavailable", cause=error
                )
            commands.extend(("age", "age-inspect", "age-keygen", "ssh-keygen"))
        for name in commands:
            if age_tooling_directory is not None and name in {
                "age",
                "age-inspect",
                "age-keygen",
            }:
                candidate = age_tooling_directory / name
            else:
                selected = (
                    sys.executable if name == "python3" else shutil.which(name)
                )
                candidate = Path(selected) if selected is not None else None
            if candidate is None:
                message = f"{name} is unavailable for the disposable test tool path"
                if self.real_local_tools:
                    require_age_tooling_or_skip(message)
                raise AssertionError(message)
            try:
                resolved = candidate.resolve(strict=True)
                info = resolved.stat(follow_symlinks=False)
            except OSError as error:
                message = (
                    f"{name} is unavailable for the disposable test tool path"
                )
                if self.real_local_tools:
                    require_age_tooling_or_skip(message, cause=error)
                raise AssertionError(message) from error
            if not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o111:
                message = f"{name} is not an executable regular file"
                if self.real_local_tools:
                    require_age_tooling_or_skip(message)
                raise AssertionError(message)
            (self.support_bin / name).symlink_to(resolved)

    @staticmethod
    def fake_age_tool() -> bytes:
        body = textwrap.dedent(
            """\
            import base64
            import json
            import os
            import sys

            name = os.path.basename(sys.argv[0])
            arguments = sys.argv[1:]
            if arguments == ["--version"]:
                print("v1.3.1")
                raise SystemExit(0)
            if name == "age-keygen" and arguments == ["-pq"]:
                print("# public key: age1pq1syntheticfixtureonly")
                identity = "AGE-" + "SECRET-KEY-PQ-1SYNTHETICFIXTUREONLY"
                print(identity)
                raise SystemExit(0)
            if name == "age-keygen" and arguments[:1] == ["-y"]:
                print("age1pq1syntheticfixtureonly")
                raise SystemExit(0)
            if name == "age-inspect" and arguments == ["--json", "-"]:
                data = sys.stdin.buffer.read()
                if not data.startswith(b"age-encryption.org/v1\\n"):
                    raise SystemExit(1)
                print(json.dumps({
                    "version": "age-encryption.org/v1",
                    "postquantum": "yes",
                    "armor": False,
                    "stanza_types": ["mlkem768x25519"],
                    "sizes": {
                        "header": 24,
                        "armor": 0,
                        "overhead": 0,
                        "min_payload": 1,
                        "max_payload": 64,
                        "min_padding": 0,
                        "max_padding": 0,
                    },
                }))
                raise SystemExit(0)
            if name == "age" and "--decrypt" in arguments:
                data = sys.stdin.buffer.read()
                prefix = b"age-encryption.org/v1\\n"
                if not data.startswith(prefix):
                    raise SystemExit(1)
                sys.stdout.buffer.write(base64.b64decode(data[len(prefix):]))
                raise SystemExit(0)
            if name == "age" and "--recipient" in arguments:
                plaintext = sys.stdin.buffer.read()
                sys.stdout.buffer.write(
                    b"age-encryption.org/v1\\n" + base64.b64encode(plaintext)
                )
                raise SystemExit(0)
            raise SystemExit(96)
            """
        ).encode("ascii")
        return f"#!{sys.executable} -B\n".encode() + body

    def _write_fake_age_archive(self) -> None:
        tool = self.fake_age_tool()
        with tarfile.open(self.archive, "w:gz") as archive:
            for name in ("age", "age-inspect", "age-keygen"):
                info = tarfile.TarInfo(f"age/{name}")
                info.mode = 0o755
                info.size = len(tool)
                info.mtime = 0
                archive.addfile(info, io.BytesIO(tool))
        self.archive.chmod(0o600)
        self.archive_sha256 = sha256(self.archive.read_bytes())

    @staticmethod
    def _public_key() -> bytes:
        algorithm = b"ssh-ed25519"
        key = bytes(range(32))
        blob = (
            struct.pack(">I", len(algorithm))
            + algorithm
            + struct.pack(">I", len(key))
            + key
        )
        return b"ssh-ed25519 " + base64.b64encode(blob) + b" issue286-age-admission\n"

    def _write_fake_ssh_keygen(self) -> None:
        body = textwrap.dedent(
            f"""\
            import os
            import sys

            arguments = sys.argv[1:]
            if "-f" not in arguments:
                raise SystemExit(96)
            target = arguments[arguments.index("-f") + 1]
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(descriptor, {self.SIGNER!r})
            os.close(descriptor)
            descriptor = os.open(target + ".pub", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(descriptor, {self._public_key()!r})
            os.close(descriptor)
            """
        ).encode("ascii")
        path = self.fake_bin / "ssh-keygen"
        path.write_bytes(f"#!{sys.executable} -B\n".encode() + body)
        path.chmod(0o755)

    @staticmethod
    def trusted_launcher_stub() -> bytes:
        body = textwrap.dedent(
            """\
            import sys
            arguments = sys.argv[1:]
            if "--operation" in arguments and arguments[arguments.index("--operation") + 1] == "preflight":
                print("required")
                raise SystemExit(0)
            raise SystemExit(97)
            """
        ).encode("ascii")
        return f"#!{sys.executable} -B\n".encode() + body

    def provider_adapter_stub(self) -> bytes:
        body = textwrap.dedent(
            f"""\
            import json
            import os
            import sys

            arguments = sys.argv[1:]
            output = arguments[arguments.index("--output") + 1]
            record = {{
                "args": arguments,
                "age_tooling": os.environ.get("AGE_TOOLING_DIRECTORY"),
                "kind": "provider-adapter",
                "key_provider": os.environ.get("PROTON_PASS_KEY_PROVIDER"),
                "linux_keyring": os.environ.get("PROTON_PASS_LINUX_KEYRING"),
                "reason": os.environ.get("PROTON_PASS_AGENT_REASON"),
                "session": os.environ.get("PROTON_PASS_SESSION_DIR"),
                "token_present": "PROTON_PASS_PERSONAL_ACCESS_TOKEN" in os.environ,
            }}
            with open({os.fspath(self.provider_log)!r}, "a", encoding="ascii") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\\n")
            descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(descriptor, b"synthetic-receipt\\n")
            os.close(descriptor)
            """
        ).encode("ascii")
        return f"#!{sys.executable} -B\n".encode() + body

    def readiness_stub(self) -> bytes:
        body = textwrap.dedent(
            f"""\
            import json
            import os
            with open({os.fspath(self.provider_log)!r}, "a", encoding="ascii") as stream:
                stream.write(json.dumps({{
                    "args": [],
                    "age_tooling": os.environ.get("AGE_TOOLING_DIRECTORY"),
                    "kind": "readiness",
                    "key_provider": os.environ.get("PROTON_PASS_KEY_PROVIDER"),
                    "linux_keyring": os.environ.get("PROTON_PASS_LINUX_KEYRING"),
                    "reason": os.environ.get("PROTON_PASS_AGENT_REASON"),
                    "session": os.environ.get("PROTON_PASS_SESSION_DIR"),
                    "token_present": "PROTON_PASS_PERSONAL_ACCESS_TOKEN" in os.environ,
                }}, sort_keys=True) + "\\n")
            """
        ).encode("ascii")
        return f"#!{sys.executable} -B\n".encode() + body

    @staticmethod
    def verifier_stub() -> bytes:
        return (
            f"#!{sys.executable} -B\nprint('privacy age integrity boundary verified')\n"
        ).encode("ascii")

    @staticmethod
    def peer_stub(name: str) -> bytes:
        return (
            f"#!{sys.executable} -B\n"
            f'"""Synthetic reviewed-source stub for {name}."""\n'
            "raise SystemExit(0)\n"
        ).encode("ascii")

    def _source_bytes(self, relative: str) -> bytes:
        if self.real_local_tools:
            return (ROOT / relative).read_bytes()
        if relative == "scripts/build-age-admission-provider-fixture":
            return REAL_BUILDER.read_bytes()
        if relative == "scripts/provision-age-admission-signer":
            return PROVISIONER.read_bytes()
        if (
            relative
            == "home/private_dot_local/bin/executable_proton-pass-age-admission"
        ):
            return self.provider_adapter_stub()
        if relative == "home/private_dot_local/bin/executable_proton-pass-ensure-ready":
            return self.readiness_stub()
        if relative == "scripts/run-trusted-age-admission":
            return self.trusted_launcher_stub()
        if relative == "scripts/privacy_age_integrity_gate.py":
            return self.verifier_stub()
        return self.peer_stub(relative)

    def _write_source_repository(self) -> None:
        run_git(self.source, "init", "--quiet")
        for relative, mode in SOURCE_MODES.items():
            destination = self.source / relative
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination.write_bytes(self._source_bytes(relative))
            destination.chmod(0o755 if mode == "100755" else 0o644)
        run_git(self.source, "add", "--all")
        run_git(
            self.source,
            "-c",
            "user.name=Synthetic Provisioning",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "synthetic reviewed source",
        )
        self.commit = run_git(self.source, "rev-parse", "HEAD").stdout.decode().strip()
        entries = []
        for relative in sorted(SOURCE_MODES):
            record = run_git(self.source, "ls-tree", self.commit, "--", relative).stdout
            metadata, raw_path = record.rstrip(b"\n").split(b"\t", 1)
            mode, kind, object_id = metadata.split(b" ", 2)
            self.assert_source_record(relative, mode, kind, raw_path)
            blob = run_git(
                self.source, "cat-file", "blob", object_id.decode("ascii")
            ).stdout
            entries.append(
                {
                    "mode": mode.decode("ascii"),
                    "path": relative,
                    "sha256": sha256(blob),
                }
            )
        self.manifest_document = {
            "commit": self.commit,
            "entries": entries,
            "schema": "issue286-reviewed-source-manifest/v1",
        }
        self.manifest.write_bytes(canonical_json(self.manifest_document))
        self.manifest.chmod(0o600)

    @staticmethod
    def assert_source_record(
        relative: str, mode: bytes, kind: bytes, path: bytes
    ) -> None:
        if (mode.decode(), kind, path.decode()) != (
            SOURCE_MODES[relative],
            b"blob",
            relative,
        ):
            raise AssertionError((relative, mode, kind, path))

    def _write_provider_state(self) -> None:
        self.provider_state.write_bytes(
            canonical_json(
                {
                    "agent": False,
                    "agent_expire_time": None,
                    "item": False,
                    "logged_in": False,
                    "revoked": False,
                }
            )
        )
        self.provider_state.chmod(0o600)

    def _write_control(self, behaviors: dict[str, str]) -> None:
        self.control.write_bytes(canonical_json({"behaviors": behaviors}))
        self.control.chmod(0o600)

    def set_behaviors(self, **behaviors: str) -> None:
        self._write_control(behaviors)

    def _write_fake_pass_cli(self) -> None:
        body = textwrap.dedent(
            f"""\
            import hashlib
            import json
            import os
            import signal
            import sys
            import time

            STATE = {os.fspath(self.provider_state)!r}
            CONTROL = {os.fspath(self.control)!r}
            LOG = {os.fspath(self.provider_log)!r}
            MARKER = {os.fspath(self.child_marker)!r}
            PRIMARY_SESSION = {os.fspath(self.primary_session)!r}
            RECOVERY_SESSION = {os.fspath(self.state / "private/recovery-session")!r}
            SIGNER = {os.fspath(self.stored_signer)!r}
            LOGIN_CREDENTIAL = {self.LOGIN_CREDENTIAL!r}

            def load(path):
                with open(path, encoding="ascii") as stream:
                    return json.load(stream)

            def save(value):
                pending = STATE + ".pending"
                with open(pending, "w", encoding="ascii") as stream:
                    json.dump(value, stream, ensure_ascii=True, indent=2, sort_keys=True)
                    stream.write("\\n")
                os.chmod(pending, 0o600)
                os.replace(pending, STATE)

            arguments = sys.argv[1:]
            session = os.environ.get("PROTON_PASS_SESSION_DIR")
            login_credential = os.environ.get("PROTON_PASS_PERSONAL_ACCESS_TOKEN")
            reason = os.environ.get("PROTON_PASS_AGENT_REASON")
            kind = "unknown"
            if arguments == ["--version"]:
                kind = "version"
            elif arguments[:3] == ["item", "create", "custom"]:
                kind = "item-create"
            elif arguments[:2] == ["item", "list"]:
                kind = "item-list"
            elif arguments[:2] == ["item", "view"]:
                kind = "item-view"
            elif arguments[:2] == ["item", "delete"]:
                kind = "item-delete"
            elif arguments[:2] == ["agent", "create"]:
                kind = "agent-create"
            elif arguments[:2] == ["agent", "list"]:
                kind = "agent-list"
            elif arguments[:2] == ["agent", "monitor"]:
                kind = "agent-monitor"
            elif arguments[:2] == ["agent", "delete"]:
                kind = "agent-delete"
            elif arguments == ["login"]:
                kind = "agent-login"
            elif arguments == ["logout", "--force"]:
                kind = "local-logout"
            elif arguments[:1] == ["info"]:
                kind = "info"
            record = {{
                "args": arguments,
                "age_tooling": os.environ.get("AGE_TOOLING_DIRECTORY"),
                "blocked_termination_signals": sorted(
                    member.value
                    for member in signal.pthread_sigmask(signal.SIG_BLOCK, ())
                    if member in {{signal.SIGHUP, signal.SIGINT, signal.SIGTERM}}
                ),
                "ignored_termination_signals": [
                    member.value
                    for member in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
                    if signal.getsignal(member) == signal.SIG_IGN
                ],
                "key_provider": os.environ.get("PROTON_PASS_KEY_PROVIDER"),
                "kind": kind,
                "linux_keyring": os.environ.get("PROTON_PASS_LINUX_KEYRING"),
                "reason": reason,
                "session": session,
                "token_digest": hashlib.sha256(login_credential.encode()).hexdigest() if login_credential else None,
                "token_present": login_credential is not None,
            }}
            with open(LOG, "a", encoding="ascii") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\\n")

            state = load(STATE)
            behavior = load(CONTROL).get("behaviors", {{}}).get(kind, "success")
            if behavior == "resistant-descendant":
                ready_read, ready_write = os.pipe()
                descendant_pid = os.fork()
                if descendant_pid == 0:
                    os.close(ready_read)
                    signal.signal(signal.SIGTERM, signal.SIG_IGN)
                    os.write(ready_write, b"1")
                    os.close(ready_write)
                    os.close(sys.stdout.fileno())
                    os.close(sys.stderr.fileno())
                    while True:
                        signal.pause()
                os.close(ready_write)
                if os.read(ready_read, 1) != b"1":
                    raise SystemExit(94)
                os.close(ready_read)
                with open(MARKER, "w", encoding="ascii") as stream:
                    json.dump(
                        {{
                            "descendant_pid": descendant_pid,
                            "kind": kind,
                            "pgid": os.getpgrp(),
                            "pid": os.getpid(),
                        }},
                        stream,
                    )
                behavior = "success"
            if behavior == "sleep-ignore-term":
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
            elif behavior == "sleep-count-term":
                def record_term(_signum, _frame):
                    descriptor = os.open(
                        MARKER + ".terms",
                        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                        0o600,
                    )
                    os.write(descriptor, b"1")
                    os.close(descriptor)

                signal.signal(signal.SIGTERM, record_term)
            if behavior.startswith("sleep"):
                with open(MARKER, "w", encoding="ascii") as stream:
                    json.dump(
                        {{"kind": kind, "pgid": os.getpgrp(), "pid": os.getpid()}},
                        stream,
                    )
                if behavior == "sleep-after-output":
                    if kind == "item-create":
                        state["item"] = True
                        save(state)
                        print("item_issue286", flush=True)
                    elif kind == "agent-create":
                        state["agent"] = True
                        state["agent_expire_time"] = int(time.time()) + 3600
                        state["revoked"] = False
                        save(state)
                        print(json.dumps({{"token": "PROTON_PASS_PERSONAL_ACCESS_TOKEN=" + LOGIN_CREDENTIAL, "instruction": "synthetic"}}), flush=True)
                time.sleep(120)
            if behavior == "overflow":
                sys.stdout.buffer.write(b"x" * (1024 * 1024 + 1))
                raise SystemExit(0)
            if behavior == "nonzero-valid":
                if kind == "item-create":
                    print("item_issue286")
                elif kind == "agent-create":
                    print(json.dumps({{"token": "PROTON_PASS_PERSONAL_ACCESS_TOKEN=" + LOGIN_CREDENTIAL, "instruction": "synthetic"}}))
                raise SystemExit(7)
            if behavior == "nonzero":
                print("synthetic provider failure", file=sys.stderr)
                raise SystemExit(7)
            if behavior == "malformed":
                print("{{malformed")
                raise SystemExit(0)
            if behavior == "noisy":
                print("warning", file=sys.stderr)

            if kind == "version":
                print("Proton Pass CLI 2.3.3 (abcdef0)")
            elif kind == "info":
                if "--output" not in arguments:
                    print("ready")
                elif session == {os.fspath(self.owner_session)!r}:
                    print(json.dumps({{
                        "release_track": "stable", "id": "user_issue286",
                        "username": "Synthetic Owner", "email": "owner@example.invalid",
                        "session_has_lock": False,
                    }}))
                elif session == {os.fspath(self.primary_session)!r}:
                    print(json.dumps({{
                        "release_track": "stable", "id": "N/A",
                        "personal_access_token_name": "[Agent] issue286-primary",
                        "session_has_lock": False,
                    }}))
                elif state["logged_in"]:
                    print(json.dumps({{
                        "release_track": "stable", "id": "N/A",
                        "personal_access_token_name": "[Agent] issue286-recovery",
                        "session_has_lock": False,
                    }}))
                else:
                    raise SystemExit(9)
            elif kind == "item-create":
                template = arguments[arguments.index("--from-template") + 1]
                with open(template, encoding="ascii") as stream:
                    value = json.load(stream)["sections"][0]["fields"][0]["value"]
                with open(SIGNER, "w", encoding="ascii") as stream:
                    stream.write(value)
                os.chmod(SIGNER, 0o600)
                state["item"] = True
                save(state)
                if behavior == "drift-after-success":
                    with open(sys.argv[0], "rb") as stream:
                        replacement = stream.read() + b"\\n# runtime PATH drift\\n"
                    pending = sys.argv[0] + ".replacement"
                    with open(pending, "wb") as stream:
                        stream.write(replacement)
                    os.chmod(pending, 0o755)
                    os.replace(pending, sys.argv[0])
                print("item_issue286")
            elif kind == "item-list":
                items = []
                if state["item"] and behavior != "empty":
                    record = {{
                        "id": "item_issue286", "share_id": "share_issue286",
                        "vault_id": "vault_issue286", "state": "Active", "flags": [],
                        "create_time": "2026-09-16T00:00:00", "modify_time": "2026-09-16T00:00:00",
                        "title": "issue286-item", "item_type": "custom",
                    }}
                    items.append(record)
                    if behavior == "duplicate":
                        items.append(dict(record))
                print(json.dumps({{"items": items}}))
            elif kind == "item-view":
                if session not in {{PRIMARY_SESSION, RECOVERY_SESSION}}:
                    raise SystemExit(11)
                if state["revoked"] and session == RECOVERY_SESSION:
                    print("revoked", file=sys.stderr)
                    raise SystemExit(8)
                with open(SIGNER, "rb") as stream:
                    sys.stdout.buffer.write(stream.read())
            elif kind == "item-delete":
                state["item"] = False
                save(state)
                print("Item item_issue286 deleted successfully")
            elif kind == "agent-create":
                state["agent"] = True
                state["agent_expire_time"] = int(time.time()) + 3600
                state["revoked"] = False
                save(state)
                print(json.dumps({{
                    "token": "PROTON_PASS_PERSONAL_ACCESS_TOKEN=" + LOGIN_CREDENTIAL,
                    "instruction": "synthetic login instruction",
                }}))
            elif kind == "agent-list":
                agents = []
                if state["agent"] and behavior != "empty":
                    record = {{"pat_id": "pat_issue286", "name": "issue286-recovery", "expire_time": state["agent_expire_time"]}}
                    agents.append(record)
                    if behavior == "duplicate":
                        agents.append(dict(record))
                print(json.dumps(agents))
            elif kind == "agent-login":
                if login_credential != LOGIN_CREDENTIAL:
                    raise SystemExit(10)
                state["logged_in"] = True
                save(state)
                print("Successfully logged in as personal access token: issue286-recovery")
            elif kind == "agent-monitor":
                print(json.dumps([{{
                    "record_id": "record_issue286", "vault_id": "vault_issue286",
                    "object_id": "item_issue286", "action": "ItemRead",
                    "payload": {{"reason": "age-admission signing-key retrieval", "vault_name": "Synthetic Vault", "item_name": "issue286-item"}},
                    "action_time": "2026-09-16T00:00:00Z",
                }}]))
            elif kind == "agent-delete":
                state["agent"] = False
                state["revoked"] = True
                save(state)
                print("Agent 'issue286-recovery' deleted successfully")
            elif kind == "local-logout":
                state["logged_in"] = False
                save(state)
                print("Executing force logout")
                print("Successfully performed force logout")
            else:
                raise SystemExit(95)
            """
        ).encode("ascii")
        path = self.fake_bin / "pass-cli"
        path.write_bytes(f"#!{sys.executable} -B\n".encode() + body)
        path.chmod(0o755)
        self.pass_cli = path

    def _write_request(
        self,
        *,
        mode: str = "qualification",
        qualification: str | None = "source-test",
        qualified_clean: dict[str, str] | None = None,
    ) -> None:
        self.request_document = {
            "age_tooling": {
                "archive": os.fspath(self.archive),
                "sha256": self.archive_sha256,
            },
            "mode": mode,
            "pass_cli": {
                "build_sha256": sha256(self.pass_cli.read_bytes()),
                "version_stdout": "Proton Pass CLI 2.3.3 (abcdef0)\n",
            },
            "private_parent": os.fspath(self.private),
            "provider": {
                "expiration": "1h",
                "item_title": "issue286-item",
                "recovery_agent_name": "issue286-recovery",
                "share_id": "share_issue286",
                "vault_name": "Synthetic Vault",
            },
            "provider_schema": {
                "command_schema": "issue286-pass-cli-2.3.3-provider-commands/v1",
                "reconciliation_manifest_sha256": "1bab100ede30e745b674a5f961c1a1d7347875454685876da5e923248a330bcb",
                "source_commit": "51a4c9b110a0ffe6e81f4f5d3877b9e5a0c24112",
            },
            "qualification": qualification,
            "qualified_clean": qualified_clean,
            "reviewed_source": {
                "commit": self.commit,
                "manifest": {
                    "path": os.fspath(self.manifest),
                    "sha256": sha256(self.manifest.read_bytes()),
                },
                "repository": os.fspath(self.source),
            },
            "schema": "issue286-provisioning/v1",
            "sessions": {
                "owner": os.fspath(self.owner_session),
                "primary_enrollment": os.fspath(self.primary_session),
                "primary_enrollment_name": "issue286-primary",
            },
        }
        self.rewrite_request()

    def rewrite_request(self) -> None:
        self.request.write_bytes(canonical_json(self.request_document))
        self.request.chmod(0o600)

    def environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        bootstrap_field = "PROTON_PASS_PERSONAL_ACCESS" + "_TOKEN"
        environment.update(
            {
                "HOME": os.fspath(self.fake_home),
                "PATH": os.pathsep.join(
                    (os.fspath(self.fake_bin), os.fspath(self.support_bin))
                ),
                "PROTON_PASS_AGENT_REASON": "hostile inherited reason",
                "PROTON_PASS_LINUX_KEYRING": "hostile inherited keyring",
                "PYTHONPYCACHEPREFIX": os.fspath(self.root / "pycache"),
                "TEMP": os.fspath(self.temporary_directory),
                "TMP": os.fspath(self.temporary_directory),
                "TMPDIR": os.fspath(self.temporary_directory),
                "XDG_CONFIG_HOME": os.fspath(self.xdg_config),
                "XDG_STATE_HOME": os.fspath(self.xdg_state),
            }
        )
        environment[bootstrap_field] = "hostile inherited token"
        return environment

    def command(self, verb: str = "start") -> list[str]:
        command = [
            sys.executable,
            "-I",
            "-B",
            "-S",
            os.fspath(PROVISIONER),
            verb,
        ]
        if verb == "start":
            command.extend(["--request", os.fspath(self.request)])
        command.extend(["--state-directory", os.fspath(self.state)])
        return command

    def run(
        self, verb: str = "start", *, timeout: int = 40
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            self.command(verb),
            check=False,
            capture_output=True,
            env=self.environment(),
            timeout=timeout,
        )

    def log(self) -> list[dict[str, object]]:
        if not self.provider_log.exists():
            return []
        return [json.loads(line) for line in self.provider_log.read_text().splitlines()]

    def provider_document(self) -> dict[str, object]:
        return json.loads(self.provider_state.read_bytes())

    def write_provider_document(self, value: dict[str, object]) -> None:
        self.provider_state.write_bytes(canonical_json(value))
        self.provider_state.chmod(0o600)

    def start_process(self) -> subprocess.Popen[bytes]:
        try:
            self.child_marker.unlink()
        except FileNotFoundError:
            pass
        return subprocess.Popen(
            self.command(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.environment(),
        )

    def start_fault_process(self, fault: str) -> subprocess.Popen[bytes]:
        runner = self.private / f"fault-runner-{fault}.py"
        trace = self.private / f"fault-trace-{fault}.jsonl"
        body = textwrap.dedent(
            f"""\
            import errno
            import json
            import os
            from pathlib import Path
            import runpy
            import signal
            import subprocess
            import sys

            FAULT = {fault!r}
            STATE = {os.fspath(self.state)!r}
            TARGET = {os.fspath(PROVISIONER)!r}
            TRACE = {os.fspath(trace)!r}
            triggered = False
            fault_pgid = None
            effect_capture_descriptor = None
            effect_capture_signaled = False
            terminal_descriptor = None
            terminal_fault_triggered = False
            terminal_write_faulted = False
            real_fsync = os.fsync
            real_mkdir = Path.mkdir
            real_killpg = os.killpg
            real_open = os.open
            real_popen = subprocess.Popen
            real_replace = os.replace
            real_sigmask = signal.pthread_sigmask

            if FAULT == "inherited-signal-state":
                for member in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
                    signal.signal(member, signal.SIG_IGN)
                signal.pthread_sigmask(
                    signal.SIG_BLOCK, (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
                )

            def record(event, **fields):
                with open(TRACE, "a", encoding="ascii") as stream:
                    stream.write(json.dumps({{"event": event, **fields}}, sort_keys=True) + "\\n")

            def injecting_mkdir(path, *args, **kwargs):
                global triggered
                result = real_mkdir(path, *args, **kwargs)
                if (
                    FAULT == "state-mkdir-signal"
                    and not triggered
                    and os.fspath(path) == STATE
                ):
                    triggered = True
                    record("state-mkdir-returned")
                    os.kill(os.getpid(), signal.SIGTERM)
                return result

            def observing_popen(*args, **kwargs):
                global fault_pgid, triggered
                command = args[0] if args else kwargs.get("args")
                command_list = [os.fspath(value) for value in command]
                if command_list == ["pass-cli", "--version"]:
                    child_kind = "version"
                elif command_list[:3] == ["pass-cli", "item", "create"]:
                    child_kind = "item-create"
                elif command_list[:3] == ["pass-cli", "agent", "delete"]:
                    child_kind = "agent-delete"
                else:
                    child_kind = "other"
                is_item_create = child_kind == "item-create"
                if FAULT == "inherited-signal-state":
                    blocked = signal.pthread_sigmask(signal.SIG_BLOCK, ())
                    record(
                        "child-signal-boundary",
                        blocked=[
                            member.value
                            for member in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
                            if member in blocked
                        ],
                        ignored=[
                            member.value
                            for member in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
                            if signal.getsignal(member) == signal.SIG_IGN
                        ],
                    )
                if FAULT == "popen-pre-spawn-signal" and is_item_create:
                    triggered = True
                    record("popen-not-spawned")
                    os.kill(os.getpid(), signal.SIGTERM)
                    raise OSError(errno.EINTR, "synthetic pre-spawn interruption")
                if triggered:
                    record("post-signal-popen", command=command_list)
                process = real_popen(*args, **kwargs)
                fault_kind = {{
                    "classification-persist-failure": "item-create",
                    "unverified-agent-delete-retirement": "agent-delete",
                    "unverified-item-retirement": "item-create",
                    "unverified-version-retirement": "version",
                }}.get(FAULT)
                if child_kind == fault_kind:
                    fault_pgid = process.pid
                    record("fault-child-returned", kind=child_kind, pgid=process.pid)
                if FAULT == "popen-post-spawn-signal" and is_item_create:
                    triggered = True
                    record("popen-returned", pgid=process.pid, pid=process.pid)
                    os.kill(os.getpid(), signal.SIGTERM)
                return process

            def faulting_killpg(pgid, signum):
                if (
                    FAULT.startswith("unverified-")
                    and pgid == fault_pgid
                    and signum == 0
                ):
                    record("group-probe-unverified", pgid=pgid)
                    raise PermissionError(errno.EPERM, "synthetic group probe failure")
                return real_killpg(pgid, signum)

            def faulting_replace(source, destination):
                if (
                    FAULT == "classification-persist-failure"
                    and os.fspath(destination) == os.path.join(STATE, "state.json")
                ):
                    try:
                        document = json.loads(Path(source).read_bytes())
                    except (FileNotFoundError, json.JSONDecodeError):
                        document = None
                    if (
                        isinstance(document, dict)
                        and document.get("outcome") == "reconciliation-required"
                        and document.get("resources", {{}})
                        .get("item", {{}})
                        .get("state")
                        == "unknown"
                    ):
                        record("classification-persist-failed")
                        raise OSError(errno.EIO, "synthetic classification persistence failure")
                return real_replace(source, destination)

            def faulting_open(path, flags, *args, **kwargs):
                global effect_capture_descriptor, terminal_descriptor
                if (
                    FAULT == "terminal-commit-failure"
                    and os.fspath(path) == os.path.join(STATE, "qualified-clean.json")
                    and flags & os.O_CREAT
                ):
                    record("terminal-open-failed")
                    raise OSError(errno.EIO, "synthetic terminal commit failure")
                descriptor = real_open(path, flags, *args, **kwargs)
                if (
                    FAULT == "post-effect-capture-fsync-signal"
                    and os.fspath(path)
                    == os.path.join(STATE, "captures", "0001.stdout")
                    and not flags & os.O_CREAT
                ):
                    effect_capture_descriptor = descriptor
                if (
                    FAULT == "terminal-partial-commit-failure"
                    and os.fspath(path) == os.path.join(STATE, "qualified-clean.json")
                    and flags & os.O_CREAT
                ):
                    terminal_descriptor = descriptor
                    record("terminal-file-created")
                return descriptor

            def faulting_fsync(descriptor):
                global effect_capture_signaled, terminal_write_faulted
                if (
                    FAULT == "post-effect-capture-fsync-signal"
                    and descriptor == effect_capture_descriptor
                    and not effect_capture_signaled
                ):
                    effect_capture_signaled = True
                    result = real_fsync(descriptor)
                    record("post-effect-capture-fsynced")
                    os.kill(os.getpid(), signal.SIGTERM)
                    return result
                if (
                    FAULT == "terminal-partial-commit-failure"
                    and descriptor == terminal_descriptor
                    and not terminal_write_faulted
                ):
                    terminal_write_faulted = True
                    record("terminal-file-fsync-failed")
                    raise OSError(errno.EIO, "synthetic terminal fsync failure")
                return real_fsync(descriptor)

            def faulting_sigmask(how, mask):
                global terminal_fault_triggered
                terminal_mask = {{signal.SIGHUP, signal.SIGINT, signal.SIGTERM}}
                if (
                    not terminal_fault_triggered
                    and how == signal.SIG_BLOCK
                    and set(mask) == terminal_mask
                    and FAULT
                    in {{"terminal-post-block-signal", "terminal-pre-block-signal"}}
                ):
                    terminal_fault_triggered = True
                    if FAULT == "terminal-pre-block-signal":
                        record("terminal-pre-block-signal")
                        os.kill(os.getpid(), signal.SIGTERM)
                        return real_sigmask(how, mask)
                    saved = real_sigmask(how, mask)
                    record("terminal-post-block-signal")
                    os.kill(os.getpid(), signal.SIGTERM)
                    return saved
                if (
                    FAULT == "terminal-mask-block-failure"
                    and how == signal.SIG_BLOCK
                    and set(mask) == terminal_mask
                ):
                    record("terminal-mask-block-failed")
                    raise OSError(errno.EIO, "synthetic signal-mask failure")
                if (
                    FAULT == "terminal-commit-failure"
                    and how == signal.SIG_BLOCK
                    and set(mask) == terminal_mask
                ):
                    saved = real_sigmask(how, mask)
                    record("terminal-mask-blocked")
                    return saved
                if FAULT == "terminal-commit-failure" and how == signal.SIG_SETMASK:
                    result = real_sigmask(how, mask)
                    record("terminal-mask-restored")
                    return result
                return real_sigmask(how, mask)

            Path.mkdir = injecting_mkdir
            os.fsync = faulting_fsync
            os.killpg = faulting_killpg
            os.open = faulting_open
            os.replace = faulting_replace
            signal.pthread_sigmask = faulting_sigmask
            subprocess.Popen = observing_popen
            sys.argv = [TARGET, *sys.argv[1:]]
            runpy.run_path(TARGET, run_name="__main__")
            """
        ).encode("ascii")
        runner.write_bytes(body)
        runner.chmod(0o600)
        return subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-B",
                "-S",
                os.fspath(runner),
                *self.command()[5:],
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.environment(),
        )

    def fault_trace(self, fault: str) -> list[dict[str, object]]:
        path = self.private / f"fault-trace-{fault}.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    def wait_for_child(self, kind: str, *, timeout: float = 15) -> int:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                marker = json.loads(self.child_marker.read_bytes())
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(0.01)
                continue
            if marker.get("kind") == kind and isinstance(marker.get("pid"), int):
                return marker["pid"]
            time.sleep(0.01)
        raise AssertionError(f"{kind} child did not start")

    def child_marker_document(self) -> dict[str, object]:
        return json.loads(self.child_marker.read_bytes())


class AgeAdmissionProvisioningTests(unittest.TestCase):
    def make_inputs(
        self, *, real_local_tools: bool = False
    ) -> tuple[TemporaryDirectory[str], ProvisioningInputs]:
        temporary = TemporaryDirectory(prefix="age-admission-provisioning.")
        root = Path(temporary.name).resolve(strict=True)
        root.chmod(0o700)
        return temporary, ProvisioningInputs(root, real_local_tools=real_local_tools)

    def test_fixture_resolves_a_symlinked_temporary_root_before_requesting(self) -> None:
        with TemporaryDirectory(
            prefix=".age-admission-root-alias.", dir=ROOT.parent
        ) as temporary:
            container = Path(temporary).resolve(strict=True)
            target = container / "physical"
            target.mkdir(mode=0o700)
            alias = container / "alias"
            alias.symlink_to(target, target_is_directory=True)

            inputs = ProvisioningInputs(alias)
            result = inputs.run()

            self.assertEqual(inputs.root, target)
            self.assertEqual(
                (result.returncode, result.stdout, result.stderr),
                (0, b"qualified-clean\n", b""),
            )

    def test_invalid_request_fails_without_creating_state(self) -> None:
        with TemporaryDirectory() as temporary:
            private = Path(temporary).resolve(strict=True)
            private.chmod(0o700)
            request = private / "request.json"
            request.write_bytes(b"{}\n")
            request.chmod(0o600)
            state = private / "operation"

            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    "-S",
                    os.fspath(PROVISIONER),
                    "start",
                    "--request",
                    os.fspath(request),
                    "--state-directory",
                    os.fspath(state),
                ],
                check=False,
                capture_output=True,
                timeout=10,
            )

            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b"")
            self.assertEqual(
                result.stderr,
                b"age-admission signer provisioning failed\n",
            )
            self.assertFalse(state.exists())

    def test_source_test_qualification_completes_and_is_production_ineligible(
        self,
    ) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)

        previous_umask = os.umask(0o022)
        try:
            result = inputs.run()
        finally:
            os.umask(previous_umask)

        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (0, b"qualified-clean\n", b""),
        )
        state_bytes = (inputs.state / "state.json").read_bytes()
        state = json.loads(state_bytes)
        self.assertEqual(state_bytes, canonical_json(state))
        self.assertEqual(state["phase"], "qualified-clean")
        self.assertEqual(state["outcome"], "qualified-clean")
        self.assertEqual(state["resources"]["agent"]["state"], "removed")
        self.assertEqual(state["resources"]["item"]["state"], "removed")
        self.assertEqual(state["resources"]["session"]["state"], "removed")
        self.assertEqual(
            state["bindings"]["pass_cli"]["observed_path"],
            os.fspath(inputs.pass_cli.resolve()),
        )
        self.assertTrue(all(state["checks"].values()))
        evidence_path = inputs.state / "qualified-clean.json"
        self.assertEqual(stat.S_IMODE(evidence_path.stat().st_mode), 0o600)
        evidence = json.loads(evidence_path.read_bytes())
        self.assertFalse(evidence["production_eligible"])
        self.assertEqual(evidence["qualification"], "source-test")
        self.assertFalse(evidence["authority"]["real_transition_authority"])
        self.assertNotIn("observed_path", evidence["bindings"]["pass_cli"])
        for relative in (
            "private/admission-ed25519",
            "private/admission-ed25519.pub",
            "private/item-template.json",
            "private/agent-token",
            "private/build-age-admission-provider-fixture",
            "private/fixture-request.json",
            "fixture",
        ):
            self.assertFalse((inputs.state / relative).exists(), relative)

        log = inputs.log()
        self.assertGreater(len(log), 10)
        login = [record for record in log if record["kind"] == "agent-login"]
        self.assertEqual(len(login), 1)
        self.assertTrue(login[0]["token_present"])
        self.assertEqual(
            login[0]["token_digest"],
            sha256(inputs.LOGIN_CREDENTIAL.encode("ascii")),
        )
        for record in log:
            if record is not login[0]:
                self.assertFalse(record["token_present"], record)
            self.assertEqual(record["key_provider"], "keyring", record)
            expected_reason = (
                "age-admission signing-key retrieval"
                if record["kind"] in {"item-view", "provider-adapter"}
                else None
            )
            self.assertEqual(record["reason"], expected_reason, record)
            self.assertEqual(
                record["age_tooling"], os.fspath(inputs.state / "fixture/tools"), record
            )
            if sys.platform.startswith("linux"):
                self.assertEqual(record["linux_keyring"], "dbus", record)
            else:
                self.assertIsNone(record["linux_keyring"], record)
        self.assertNotIn(
            inputs.SIGNER,
            result.stdout
            + result.stderr
            + state_bytes
            + evidence_path.read_bytes()
            + inputs.provider_log.read_bytes(),
        )
        self.assertNotIn(
            inputs.LOGIN_CREDENTIAL.encode("ascii"),
            result.stdout
            + result.stderr
            + state_bytes
            + evidence_path.read_bytes()
            + inputs.provider_log.read_bytes(),
        )

        for directory in (
            inputs.state,
            inputs.state / "private",
            inputs.state / "private/recovery-session",
            inputs.state / "captures",
        ):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        for path in (inputs.state / "captures").iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path.name)

    def test_known_nonzero_create_with_valid_output_remains_unknown(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"item-create": "nonzero-valid"})

        result = inputs.run()

        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (
                20,
                b"",
                b"age-admission signer provisioning requires reconciliation\n",
            ),
        )
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["item"]["state"], "unknown")
        self.assertIsNone(state["resources"]["item"]["id"])
        self.assertEqual(state["pending_request"]["kind"], "item-create")
        self.assertEqual(state["outcome"], "reconciliation-required")
        self.assertEqual([record["kind"] for record in inputs.log()][-1], "item-create")
        self.assertTrue((inputs.state / "private/admission-ed25519").exists())
        self.assertFalse((inputs.state / "qualified-clean.json").exists())

        inputs.set_behaviors(**{"item-list": "empty"})
        resumed = inputs.run("resume")
        self.assertEqual(resumed.returncode, 20)
        resumed_state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(resumed_state["resources"]["item"]["state"], "unknown")
        self.assertIsNone(resumed_state["resources"]["item"]["id"])
        self.assertIsNotNone(
            resumed_state["pending_request"]["targets"]["observed_result"]["status"]
        )

    def test_capture_overflow_stops_before_any_later_provider_request(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"item-create": "overflow"})

        result = inputs.run()

        self.assertEqual(result.returncode, 20)
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["item"]["state"], "unknown")
        capture = inputs.state / state["pending_request"]["captures"]["stdout"]
        self.assertEqual(capture.stat().st_size, 1024 * 1024)
        self.assertEqual([record["kind"] for record in inputs.log()][-1], "item-create")

    def test_status_zero_with_malformed_create_output_is_unknown(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"item-create": "malformed"})

        result = inputs.run()

        self.assertEqual(result.returncode, 20)
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["item"]["state"], "unknown")
        self.assertEqual(state["pending_request"]["kind"], "item-create")
        self.assertFalse((inputs.state / "qualified-clean.json").exists())

    def test_duplicate_item_listing_rolls_back_the_acknowledged_item(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"item-list": "duplicate"})

        result = inputs.run()

        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (1, b"", b"age-admission signer provisioning failed\n"),
        )
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["outcome"], "rolled-back")
        self.assertEqual(state["resources"]["item"]["state"], "removed")
        kinds = [record["kind"] for record in inputs.log()]
        self.assertEqual(kinds[-1], "item-delete")
        self.assertNotIn("agent-create", kinds)

    def test_warning_bearing_agent_listing_never_advances(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"agent-list": "noisy"})

        result = inputs.run()

        self.assertEqual(result.returncode, 1)
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["outcome"], "rolled-back")
        self.assertEqual(state["resources"]["agent"]["state"], "removed")
        self.assertEqual(state["resources"]["item"]["state"], "removed")
        kinds = [record["kind"] for record in inputs.log()]
        self.assertNotIn("agent-login", kinds)

    def test_malformed_audit_evidence_rolls_back_without_terminal_marker(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"agent-monitor": "malformed"})

        result = inputs.run()

        self.assertEqual(result.returncode, 1)
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["outcome"], "rolled-back")
        self.assertFalse(state["checks"]["audit"])
        self.assertEqual(state["resources"]["agent"]["state"], "removed")
        self.assertEqual(state["resources"]["item"]["state"], "removed")
        self.assertEqual(state["resources"]["session"]["state"], "removed")
        self.assertFalse((inputs.state / "qualified-clean.json").exists())

    def test_caught_signal_preserves_ambiguous_write_and_reaps_its_group(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"item-create": "sleep"})
        process = inputs.start_process()
        child_pid = inputs.wait_for_child("item-create")

        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (
                143,
                b"",
                b"age-admission signer provisioning interrupted\n",
            ),
        )
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["item"]["state"], "unknown")
        self.assertEqual(state["pending_request"]["kind"], "item-create")
        self.assertTrue((inputs.state / "private/admission-ed25519").exists())
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)

    def test_repeated_signals_keep_the_first_status_and_one_classification(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"item-create": "sleep-count-term"})
        process = inputs.start_process()
        child_pid = inputs.wait_for_child("item-create")

        started = time.monotonic()
        os.kill(process.pid, signal.SIGTERM)
        time.sleep(0.05)
        os.kill(process.pid, signal.SIGINT)
        os.kill(process.pid, signal.SIGHUP)
        stdout, stderr = process.communicate(timeout=10)
        elapsed = time.monotonic() - started

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (
                143,
                b"",
                b"age-admission signer provisioning interrupted\n",
            ),
        )
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["item"]["state"], "unknown")
        self.assertEqual(state["pending_request"]["kind"], "item-create")
        self.assertEqual(state["request_sequence"], 1)
        self.assertEqual(
            [record["kind"] for record in inputs.log()].count("item-create"), 1
        )
        self.assertEqual(inputs.log()[-1]["kind"], "item-create")
        self.assertEqual(inputs.child_term_log.read_bytes(), b"1")
        self.assertGreaterEqual(elapsed, 1.5)
        self.assertLess(elapsed, 5.0)
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)

    def test_first_catchable_signal_selects_its_128_plus_status(self) -> None:
        for signum in (signal.SIGHUP, signal.SIGINT):
            with self.subTest(signum=signum):
                temporary, inputs = self.make_inputs()
                try:
                    inputs.set_behaviors(version="sleep")
                    process = inputs.start_process()
                    child_pid = inputs.wait_for_child("version")

                    os.kill(process.pid, signum)
                    stdout, stderr = process.communicate(timeout=10)

                    self.assertEqual(
                        (process.returncode, stdout, stderr),
                        (
                            128 + signum,
                            b"",
                            b"age-admission signer provisioning interrupted\n",
                        ),
                    )
                    state = json.loads((inputs.state / "state.json").read_bytes())
                    self.assertEqual(state["outcome"], "local-cleanup-incomplete")
                    self.assertIsNone(state["pending_request"])
                    self.assertTrue(
                        all(
                            resource["state"] == "absent"
                            for resource in state["resources"].values()
                        )
                    )
                    self.assertEqual(inputs.log()[-1]["kind"], "version")
                    with self.assertRaises(ProcessLookupError):
                        os.kill(child_pid, 0)
                finally:
                    temporary.cleanup()

    def test_signal_after_effect_capture_stops_at_its_durable_settlement(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        process = inputs.start_fault_process("post-effect-capture-fsync-signal")

        stdout, stderr = process.communicate(timeout=10)

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (
                143,
                b"",
                b"age-admission signer provisioning interrupted\n",
            ),
        )
        self.assertEqual(
            inputs.fault_trace("post-effect-capture-fsync-signal")[-1],
            {"event": "post-effect-capture-fsynced"},
        )
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["phase"], "fixture-ready")
        self.assertEqual(state["outcome"], "local-cleanup-incomplete")
        self.assertEqual(state["resources"]["item"]["state"], "present")
        self.assertEqual(state["resources"]["item"]["id"], "item_issue286")
        self.assertIsNone(state["pending_request"])
        self.assertEqual([record["kind"] for record in inputs.log()][-1], "item-create")
        self.assertFalse((inputs.state / "qualified-clean.json").exists())

    def test_successful_leader_cannot_hide_a_resistant_descendant(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"item-create": "resistant-descendant"})

        result = inputs.run()

        marker = inputs.child_marker_document()
        descendant_pid = marker["descendant_pid"]
        pgid = marker["pgid"]
        self.assertIsInstance(descendant_pid, int)
        self.assertIsInstance(pgid, int)
        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (
                20,
                b"",
                b"age-admission signer provisioning requires reconciliation\n",
            ),
        )
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["item"]["state"], "present")
        self.assertEqual(state["resources"]["item"]["id"], "item_issue286")
        self.assertIsNone(state["pending_request"])
        self.assertFalse((inputs.state / "qualified-clean.json").exists())
        for probe, label in (
            (lambda: os.kill(descendant_pid, 0), "provider descendant"),
            (lambda: os.killpg(pgid, 0), "provider process group"),
        ):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    probe()
                except ProcessLookupError:
                    break
                time.sleep(0.02)
            else:
                self.fail(f"{label} survived helper return")

    def test_signal_after_state_directory_creation_stops_before_any_child(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        process = inputs.start_fault_process("state-mkdir-signal")

        stdout, stderr = process.communicate(timeout=10)

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (
                143,
                b"",
                b"age-admission signer provisioning interrupted\n",
            ),
        )
        trace = inputs.fault_trace("state-mkdir-signal")
        self.assertEqual(
            [record["event"] for record in trace], ["state-mkdir-returned"]
        )
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["outcome"], "rolled-back")
        self.assertIsNone(state["pending_request"])
        self.assertTrue(
            all(resource["state"] == "absent" for resource in state["resources"].values())
        )
        self.assertEqual(inputs.log(), [])
        self.assertFalse((inputs.state / "qualified-clean.json").exists())
        self.assertFalse((inputs.state / "ready-for-recovery.json").exists())

    def test_signal_after_arming_before_spawn_restores_without_provider_call(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        process = inputs.start_fault_process("popen-pre-spawn-signal")

        stdout, stderr = process.communicate(timeout=10)

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (
                143,
                b"",
                b"age-admission signer provisioning interrupted\n",
            ),
        )
        self.assertEqual(
            [record["event"] for record in inputs.fault_trace("popen-pre-spawn-signal")],
            ["popen-not-spawned"],
        )
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["outcome"], "local-cleanup-incomplete")
        self.assertEqual(state["resources"]["item"]["state"], "absent")
        self.assertIsNone(state["pending_request"])
        self.assertTrue((inputs.state / "private/admission-ed25519").exists())
        self.assertTrue((inputs.state / "fixture").exists())
        self.assertNotIn("item-create", [record["kind"] for record in inputs.log()])

    def test_signal_before_popen_returns_retires_the_registered_group(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        process = inputs.start_fault_process("popen-post-spawn-signal")

        stdout, stderr = process.communicate(timeout=10)

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (
                143,
                b"",
                b"age-admission signer provisioning interrupted\n",
            ),
        )
        trace = inputs.fault_trace("popen-post-spawn-signal")
        self.assertEqual([record["event"] for record in trace], ["popen-returned"])
        child_pid = trace[0]["pid"]
        pgid = trace[0]["pgid"]
        self.assertIsInstance(child_pid, int)
        self.assertIsInstance(pgid, int)
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)
        with self.assertRaises(ProcessLookupError):
            os.killpg(pgid, 0)
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["item"]["state"], "unknown")
        self.assertEqual(state["pending_request"]["kind"], "item-create")
        self.assertEqual(state["outcome"], "reconciliation-required")

    def test_children_do_not_inherit_blocked_or_ignored_termination_signals(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        process = inputs.start_fault_process("inherited-signal-state")

        stdout, stderr = process.communicate(timeout=40)

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (0, b"qualified-clean\n", b""),
        )
        trace = inputs.fault_trace("inherited-signal-state")
        self.assertGreater(len(trace), 10)
        self.assertTrue(
            all(
                record == {
                    "blocked": [],
                    "event": "child-signal-boundary",
                    "ignored": [],
                }
                for record in trace
            ),
            trace,
        )
        provider_log = inputs.log()
        self.assertGreater(len(provider_log), 10)
        signal_observations = [
            record
            for record in provider_log
            if "blocked_termination_signals" in record
        ]
        self.assertGreater(len(signal_observations), 8)
        for record in signal_observations:
            self.assertEqual(record["blocked_termination_signals"], [], record)
            self.assertEqual(record["ignored_termination_signals"], [], record)

    def test_unverified_create_retirement_uses_reconciliation_status(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"item-create": "sleep"})
        process = inputs.start_fault_process("unverified-item-retirement")
        child_pid = inputs.wait_for_child("item-create")

        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (
                20,
                b"",
                b"age-admission signer provisioning requires reconciliation\n",
            ),
        )
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["item"]["state"], "unknown")
        self.assertEqual(state["pending_request"]["kind"], "item-create")
        self.assertEqual(
            state["pending_request"]["targets"]["observed_result"]["outcome"],
            "unverified-retirement",
        )
        self.assertEqual(state["outcome"], "reconciliation-required")
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)

    def test_unverified_read_retirement_uses_cleanup_status(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(version="sleep")
        process = inputs.start_fault_process("unverified-version-retirement")
        child_pid = inputs.wait_for_child("version")

        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (
                21,
                b"",
                b"age-admission signer provisioning cleanup incomplete\n",
            ),
        )
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["outcome"], "local-cleanup-incomplete")
        self.assertIsNone(state["pending_request"])
        self.assertTrue(
            all(resource["state"] == "absent" for resource in state["resources"].values())
        )
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)

    def test_unverified_delete_retirement_uses_cleanup_status(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"agent-delete": "sleep"})
        process = inputs.start_fault_process("unverified-agent-delete-retirement")
        child_pid = inputs.wait_for_child("agent-delete")

        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=15)

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (
                21,
                b"",
                b"age-admission signer provisioning cleanup incomplete\n",
            ),
        )
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["agent"]["state"], "unknown")
        self.assertEqual(state["pending_request"]["kind"], "agent-delete")
        self.assertEqual(state["outcome"], "remote-cleanup-incomplete")
        self.assertTrue((inputs.state / "private/admission-ed25519").exists())
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)

    def test_failed_interruption_classification_uses_failure_status(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"item-create": "sleep"})
        process = inputs.start_fault_process("classification-persist-failure")
        child_pid = inputs.wait_for_child("item-create")

        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (1, b"", b"age-admission signer provisioning failed\n"),
        )
        self.assertIn(
            {"event": "classification-persist-failed"},
            inputs.fault_trace("classification-persist-failure"),
        )
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["item"]["state"], "requesting")
        self.assertEqual(state["pending_request"]["kind"], "item-create")
        self.assertEqual(state["outcome"], "running")
        self.assertFalse((inputs.state / "qualified-clean.json").exists())
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)

    def test_signal_before_terminal_commit_prevents_the_success_marker(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        process = inputs.start_fault_process("terminal-pre-block-signal")

        stdout, stderr = process.communicate(timeout=40)

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (
                143,
                b"",
                b"age-admission signer provisioning interrupted\n",
            ),
        )
        self.assertEqual(
            inputs.fault_trace("terminal-pre-block-signal")[-1],
            {"event": "terminal-pre-block-signal"},
        )
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["outcome"], "local-cleanup-incomplete")
        self.assertNotEqual(state["phase"], "qualified-clean")
        self.assertFalse((inputs.state / "qualified-clean.json").exists())
        self.assertFalse((inputs.state / "ready-for-recovery.json").exists())

    def test_signal_after_terminal_mask_defers_to_the_committed_marker(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        process = inputs.start_fault_process("terminal-post-block-signal")

        stdout, stderr = process.communicate(timeout=40)

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (0, b"qualified-clean\n", b""),
        )
        self.assertEqual(
            inputs.fault_trace("terminal-post-block-signal")[-1],
            {"event": "terminal-post-block-signal"},
        )
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["outcome"], "qualified-clean")
        self.assertTrue((inputs.state / "qualified-clean.json").exists())

    def test_failed_terminal_commit_restores_the_signal_mask_and_fails(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        process = inputs.start_fault_process("terminal-commit-failure")

        stdout, stderr = process.communicate(timeout=40)

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (1, b"", b"age-admission signer provisioning failed\n"),
        )
        events = [
            record["event"]
            for record in inputs.fault_trace("terminal-commit-failure")
        ]
        self.assertEqual(
            events[-3:],
            [
                "terminal-mask-blocked",
                "terminal-open-failed",
                "terminal-mask-restored",
            ],
        )
        self.assertFalse((inputs.state / "qualified-clean.json").exists())
        self.assertFalse((inputs.state / "ready-for-recovery.json").exists())
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertNotIn(state["outcome"], {"qualified-clean", "ready-for-recovery"})

    def test_failed_terminal_mask_block_does_not_leave_success_state(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        process = inputs.start_fault_process("terminal-mask-block-failure")

        stdout, stderr = process.communicate(timeout=40)

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (1, b"", b"age-admission signer provisioning failed\n"),
        )
        self.assertEqual(
            inputs.fault_trace("terminal-mask-block-failure")[-1],
            {"event": "terminal-mask-block-failed"},
        )
        self.assertFalse((inputs.state / "qualified-clean.json").exists())
        self.assertFalse((inputs.state / "ready-for-recovery.json").exists())
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(
            (state["phase"], state["outcome"]),
            ("recovery-readback-verified", "rolled-back"),
        )

    def test_partial_terminal_file_is_removed_when_commit_fails(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        process = inputs.start_fault_process("terminal-partial-commit-failure")

        stdout, stderr = process.communicate(timeout=40)

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (1, b"", b"age-admission signer provisioning failed\n"),
        )
        self.assertEqual(
            inputs.fault_trace("terminal-partial-commit-failure")[-2:],
            [
                {"event": "terminal-file-created"},
                {"event": "terminal-file-fsync-failed"},
            ],
        )
        self.assertFalse((inputs.state / "qualified-clean.json").exists())
        self.assertFalse((inputs.state / "ready-for-recovery.json").exists())
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(
            (state["phase"], state["outcome"]),
            ("recovery-readback-verified", "rolled-back"),
        )

    def test_complete_create_output_can_settle_a_lost_signal_status_only(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"item-create": "sleep-after-output"})
        process = inputs.start_process()
        inputs.wait_for_child("item-create")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                state = json.loads((inputs.state / "state.json").read_bytes())
                capture = inputs.state / state["pending_request"]["captures"]["stdout"]
                if capture.stat().st_size:
                    break
            except (FileNotFoundError, TypeError):
                pass
            time.sleep(0.01)
        else:
            self.fail("source-ordered item output was not captured")

        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (
                143,
                b"",
                b"age-admission signer provisioning interrupted\n",
            ),
        )
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["item"]["state"], "present")
        self.assertEqual(state["resources"]["item"]["id"], "item_issue286")
        self.assertIsNone(state["pending_request"])
        self.assertEqual(state["outcome"], "reconciliation-required")
        self.assertEqual([record["kind"] for record in inputs.log()][-1], "item-create")

    def test_complete_agent_output_can_settle_lost_status_without_login(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"agent-create": "sleep-after-output"})
        process = inputs.start_process()
        inputs.wait_for_child("agent-create")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                state = json.loads((inputs.state / "state.json").read_bytes())
                capture = inputs.state / state["pending_request"]["captures"]["stdout"]
                if capture.stat().st_size:
                    break
            except (FileNotFoundError, TypeError):
                pass
            time.sleep(0.01)
        else:
            self.fail("source-ordered agent output was not captured")

        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (143, b"", b"age-admission signer provisioning interrupted\n"),
        )
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["agent"]["state"], "present")
        self.assertIsNone(state["pending_request"])
        token_path = inputs.state / state["artifacts"]["agent_token"]
        self.assertEqual(
            token_path.read_bytes(),
            (inputs.LOGIN_CREDENTIAL + "\n").encode(),
        )
        kinds = [record["kind"] for record in inputs.log()]
        self.assertNotIn("agent-login", kinds)

    def test_known_nonzero_agent_output_never_creates_a_token_artifact(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"agent-create": "nonzero-valid"})

        result = inputs.run()

        self.assertEqual(result.returncode, 20)
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["agent"]["state"], "unknown")
        self.assertIsNotNone(
            state["pending_request"]["targets"]["observed_result"]["status"]
        )
        self.assertFalse((inputs.state / state["artifacts"]["agent_token"]).exists())
        self.assertEqual(
            [record["kind"] for record in inputs.log()][-1], "agent-create"
        )

    def _host_loss_at_item_create(
        self, inputs: ProvisioningInputs, *, with_output: bool
    ) -> None:
        inputs.set_behaviors(
            **{"item-create": ("sleep-after-output" if with_output else "sleep")}
        )
        process = inputs.start_process()
        child_pid = inputs.wait_for_child("item-create")
        if with_output:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    state = json.loads((inputs.state / "state.json").read_bytes())
                    capture = (
                        inputs.state / state["pending_request"]["captures"]["stdout"]
                    )
                    if capture.stat().st_size:
                        break
                except (FileNotFoundError, TypeError):
                    pass
                time.sleep(0.01)
            else:
                self.fail("source-ordered output was not durable before host loss")
        os.kill(process.pid, signal.SIGKILL)
        process.communicate(timeout=5)
        try:
            os.killpg(child_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.01)

    def test_resume_uses_source_ordered_capture_without_listing_or_retry(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        self._host_loss_at_item_create(inputs, with_output=True)

        result = inputs.run("resume")

        self.assertEqual(result.returncode, 20)
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["item"]["state"], "present")
        self.assertEqual(state["resources"]["item"]["id"], "item_issue286")
        self.assertIsNone(state["pending_request"])
        kinds = [record["kind"] for record in inputs.log()]
        self.assertEqual(kinds.count("item-create"), 1)
        self.assertNotIn("item-list", kinds)

    def test_resume_retains_candidates_and_zero_matches_never_settle(self) -> None:
        for listing_behavior, expected_candidates in (
            ("success", ["item_issue286"]),
            ("empty", []),
        ):
            with self.subTest(listing_behavior=listing_behavior):
                temporary, inputs = self.make_inputs()
                try:
                    self._host_loss_at_item_create(inputs, with_output=False)
                    provider = inputs.provider_document()
                    provider["item"] = True
                    inputs.write_provider_document(provider)
                    inputs.set_behaviors(**{"item-list": listing_behavior})

                    result = inputs.run("resume")

                    self.assertEqual(result.returncode, 20)
                    state = json.loads((inputs.state / "state.json").read_bytes())
                    self.assertEqual(state["resources"]["item"]["state"], "unknown")
                    self.assertEqual(
                        [
                            candidate["id"]
                            for candidate in state["resources"]["item"]["candidates"]
                        ],
                        expected_candidates,
                    )
                    self.assertEqual(state["pending_request"]["kind"], "item-create")
                    kinds = [record["kind"] for record in inputs.log()]
                    self.assertEqual(kinds.count("item-create"), 1)
                    self.assertEqual(kinds.count("item-list"), 1)
                    self.assertNotIn("item-delete", kinds)
                finally:
                    temporary.cleanup()

    def test_resume_rejects_tampered_command_state_before_observation(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"item-create": "nonzero-valid"})
        self.assertEqual(inputs.run().returncode, 20)
        before = inputs.log()
        state_path = inputs.state / "state.json"
        state = json.loads(state_path.read_bytes())
        state["pending_request"]["command"].append("--unreviewed")
        state_path.write_bytes(canonical_json(state))
        state_path.chmod(0o600)

        result = inputs.run("resume")

        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (1, b"", b"age-admission signer provisioning failed\n"),
        )
        self.assertEqual(inputs.log(), before)
        retained = json.loads(state_path.read_bytes())
        self.assertEqual(retained["resources"]["item"]["state"], "unknown")
        self.assertEqual(retained["pending_request"]["kind"], "item-create")

    def test_resume_positive_login_info_stops_without_readiness_or_later_mutation(
        self,
    ) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"agent-login": "nonzero"})
        blocked = inputs.run()
        self.assertEqual(blocked.returncode, 20)
        provider = inputs.provider_document()
        provider["logged_in"] = True
        inputs.write_provider_document(provider)
        before = len(inputs.log())
        inputs.set_behaviors()

        resumed = inputs.run("resume")

        self.assertEqual(resumed.returncode, 20)
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["session"]["state"], "present")
        self.assertIsNone(state["pending_request"])
        resumed_log = inputs.log()[before:]
        self.assertEqual([record["kind"] for record in resumed_log], ["info"])

    def test_positive_agent_after_ambiguous_delete_does_not_settle_removal(
        self,
    ) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"agent-delete": "nonzero"})

        blocked = inputs.run()
        self.assertEqual(blocked.returncode, 21)
        before = len(inputs.log())
        inputs.set_behaviors()
        resumed = inputs.run("resume")

        self.assertEqual(
            (resumed.returncode, resumed.stdout, resumed.stderr),
            (
                21,
                b"",
                b"age-admission signer provisioning cleanup incomplete\n",
            ),
        )
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["agent"]["state"], "unknown")
        self.assertEqual(state["resources"]["agent"]["pat_id"], "pat_issue286")
        self.assertEqual(
            [
                candidate["pat_id"]
                for candidate in state["resources"]["agent"]["candidates"]
            ],
            ["pat_issue286"],
        )
        self.assertEqual(state["pending_request"]["kind"], "agent-delete")
        self.assertEqual(
            [record["kind"] for record in inputs.log()[before:]], ["agent-list"]
        )

    def test_zero_agent_listing_after_ambiguous_delete_does_not_prove_removal(
        self,
    ) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"agent-delete": "nonzero"})
        blocked = inputs.run()
        self.assertEqual(blocked.returncode, 21)
        before = len(inputs.log())
        inputs.set_behaviors(**{"agent-list": "empty"})

        resumed = inputs.run("resume")

        self.assertEqual(resumed.returncode, 21)
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["agent"]["state"], "unknown")
        self.assertEqual(state["resources"]["agent"]["candidates"], [])
        self.assertEqual(state["pending_request"]["kind"], "agent-delete")
        self.assertEqual(
            [record["kind"] for record in inputs.log()[before:]], ["agent-list"]
        )

    def test_positive_item_after_ambiguous_delete_retains_exact_handle(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"item-delete": "nonzero"})
        blocked = inputs.run()
        self.assertEqual(blocked.returncode, 21)
        before = len(inputs.log())
        inputs.set_behaviors()

        resumed = inputs.run("resume")

        self.assertEqual(resumed.returncode, 21)
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["agent"]["state"], "removed")
        self.assertEqual(state["resources"]["item"]["state"], "unknown")
        self.assertEqual(state["resources"]["item"]["id"], "item_issue286")
        self.assertEqual(
            [candidate["id"] for candidate in state["resources"]["item"]["candidates"]],
            ["item_issue286"],
        )
        self.assertEqual(
            [record["kind"] for record in inputs.log()[before:]], ["item-list"]
        )

    def test_ambiguous_logout_preserves_removed_remote_handles_and_local_evidence(
        self,
    ) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"local-logout": "nonzero"})
        blocked = inputs.run()
        self.assertEqual(blocked.returncode, 21)
        before = len(inputs.log())
        inputs.set_behaviors()

        resumed = inputs.run("resume")

        self.assertEqual(resumed.returncode, 21)
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["agent"]["state"], "removed")
        self.assertEqual(state["resources"]["item"]["state"], "removed")
        self.assertEqual(state["resources"]["session"]["state"], "unknown")
        self.assertEqual(state["pending_request"]["kind"], "local-logout")
        self.assertTrue((inputs.state / "private/admission-ed25519").exists())
        self.assertFalse((inputs.state / "qualified-clean.json").exists())
        self.assertEqual([record["kind"] for record in inputs.log()[before:]], ["info"])

    def test_source_test_evidence_cannot_open_the_production_path(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        qualified = inputs.run()
        self.assertEqual(qualified.returncode, 0)
        evidence_path = inputs.state / "qualified-clean.json"
        evidence_binding = {
            "path": os.fspath(evidence_path),
            "sha256": sha256(evidence_path.read_bytes()),
        }
        before = len(inputs.log())
        inputs.state = inputs.private / "production-operation"
        inputs.request = inputs.private / "production-request.json"
        inputs._write_request(
            mode="production",
            qualification=None,
            qualified_clean=evidence_binding,
        )

        result = inputs.run()

        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (1, b"", b"age-admission signer provisioning failed\n"),
        )
        self.assertEqual(len(inputs.log()), before)
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["outcome"], "rolled-back")
        self.assertFalse((inputs.state / "ready-for-recovery.json").exists())

    def test_live_labeled_fixture_evidence_can_prepare_but_not_authorize_recovery(
        self,
    ) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.request_document["qualification"] = "live-disposable-provider"
        inputs.rewrite_request()
        qualified = inputs.run()
        self.assertEqual(qualified.returncode, 0)
        evidence_path = inputs.state / "qualified-clean.json"
        evidence = json.loads(evidence_path.read_bytes())
        self.assertTrue(evidence["production_eligible"])
        evidence_binding = {
            "path": os.fspath(evidence_path),
            "sha256": sha256(evidence_path.read_bytes()),
        }
        inputs.state = inputs.private / "production-operation"
        inputs.request = inputs.private / "production-request.json"
        inputs._write_request(
            mode="production",
            qualification=None,
            qualified_clean=evidence_binding,
        )

        result = inputs.run()

        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (0, b"ready-for-recovery\n", b""),
        )
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["outcome"], "ready-for-recovery")
        for resource in ("agent", "item", "session"):
            self.assertEqual(state["resources"][resource]["state"], "present")
        ready = json.loads((inputs.state / "ready-for-recovery.json").read_bytes())
        self.assertFalse(ready["authority"]["github_mutation_permitted"])
        self.assertFalse(ready["authority"]["real_transition_authority"])
        self.assertTrue(ready["authority"]["recovery_requires_separate_authorization"])
        self.assertEqual(ready["private_state"], "state.json")
        self.assertFalse((inputs.state / "fixture").exists())
        self.assertFalse((inputs.state / "private/admission-ed25519").exists())
        self.assertIsNotNone(state["resources"]["item"]["id"])
        self.assertIsNotNone(state["resources"]["agent"]["pat_id"])

    def test_runtime_path_digest_drift_stops_with_remote_handle_preserved(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"item-create": "drift-after-success"})

        result = inputs.run()

        self.assertEqual(result.returncode, 1)
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["item"]["state"], "present")
        self.assertEqual(state["resources"]["item"]["id"], "item_issue286")
        self.assertEqual(state["outcome"], "local-cleanup-incomplete")
        self.assertTrue((inputs.state / "private/admission-ed25519").exists())
        kinds = [record["kind"] for record in inputs.log()]
        self.assertEqual(kinds[-1], "item-create")
        self.assertNotIn("item-delete", kinds)

    def test_pre_spawn_failure_after_durable_arming_restores_absent_state(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        armed = threading.Event()

        def remove_selected_executable() -> None:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    state = json.loads((inputs.state / "state.json").read_bytes())
                    pending = state.get("pending_request")
                    if (
                        isinstance(pending, dict)
                        and pending.get("kind") == "item-create"
                    ):
                        inputs.pass_cli.rename(inputs.fake_bin / "pass-cli.removed")
                        armed.set()
                        return
                except (FileNotFoundError, json.JSONDecodeError):
                    pass
                time.sleep(0.0005)

        watcher = threading.Thread(target=remove_selected_executable, daemon=True)
        watcher.start()
        result = inputs.run()
        watcher.join(timeout=2)

        self.assertTrue(armed.is_set(), "the mutation was not observed durably armed")
        self.assertEqual(result.returncode, 1)
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["item"]["state"], "absent")
        self.assertIsNone(state["pending_request"])
        self.assertEqual(state["outcome"], "rolled-back")
        kinds = [record["kind"] for record in inputs.log()]
        self.assertEqual(kinds[-1], "info")
        self.assertNotIn("item-create", kinds)

    def test_provider_mutation_timeout_is_unknown_and_retains_capture(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.set_behaviors(**{"item-create": "sleep"})
        started = time.monotonic()

        result = inputs.run(timeout=75)

        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 55)
        self.assertLess(elapsed, 72)
        self.assertEqual(result.returncode, 20)
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["resources"]["item"]["state"], "unknown")
        self.assertEqual(state["pending_request"]["kind"], "item-create")
        for channel in ("stdout", "stderr"):
            capture = inputs.state / state["pending_request"]["captures"][channel]
            self.assertTrue(capture.exists())
            self.assertEqual(stat.S_IMODE(capture.stat().st_mode), 0o600)

    def test_noncanonical_or_symlinked_private_input_is_rejected_before_state(
        self,
    ) -> None:
        for attack in ("duplicate-json", "request-symlink", "loose-parent"):
            with self.subTest(attack=attack):
                temporary = TemporaryDirectory(prefix="age-admission-input-reject.")
                try:
                    private = Path(temporary.name).resolve(strict=True)
                    private.chmod(0o700)
                    request = private / "request.json"
                    if attack == "duplicate-json":
                        request.write_bytes(
                            b'{"schema":"issue286-provisioning/v1","schema":"issue286-provisioning/v1"}\n'
                        )
                        request.chmod(0o600)
                    elif attack == "request-symlink":
                        target = private / "target.json"
                        target.write_bytes(b"{}\n")
                        target.chmod(0o600)
                        request.symlink_to(target)
                    else:
                        private.chmod(0o755)
                        request.write_bytes(b"{}\n")
                        request.chmod(0o600)
                    state = private / "operation"
                    result = subprocess.run(
                        [
                            sys.executable,
                            "-I",
                            "-B",
                            "-S",
                            os.fspath(PROVISIONER),
                            "start",
                            "--request",
                            os.fspath(request),
                            "--state-directory",
                            os.fspath(state),
                        ],
                        check=False,
                        capture_output=True,
                        timeout=10,
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertFalse(state.exists())
                finally:
                    temporary.cleanup()

    def test_reviewed_commit_blobs_override_changed_source_worktree_bytes(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        candidate = inputs.source / "scripts/provision-age-admission-signer"
        candidate.write_bytes(b"#!/bin/sh\nexit 99\n")
        candidate.chmod(0o755)

        result = inputs.run()

        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (0, b"qualified-clean\n", b""),
        )

    def test_manifest_blob_mismatch_is_rejected_before_provider_or_state(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        manifest = json.loads(inputs.manifest.read_bytes())
        manifest["entries"][0]["sha256"] = "0" * 64
        inputs.manifest.write_bytes(canonical_json(manifest))
        inputs.manifest.chmod(0o600)
        inputs.request_document["reviewed_source"]["manifest"]["sha256"] = sha256(
            inputs.manifest.read_bytes()
        )
        inputs.rewrite_request()

        result = inputs.run()

        self.assertEqual(result.returncode, 1)
        self.assertFalse(inputs.state.exists())
        self.assertEqual(inputs.log(), [])

    def test_real_builder_adapter_wrapper_and_verifier_match_the_provisioner_contract(
        self,
    ) -> None:
        temporary, inputs = self.make_inputs(real_local_tools=True)
        self.addCleanup(temporary.cleanup)
        support_temporary = TemporaryDirectory(
            prefix=".age-admission-secure-support.", dir=ROOT.parent
        )
        self.addCleanup(support_temporary.cleanup)
        secure_support = Path(support_temporary.name).resolve(strict=True)
        secure_support.chmod(0o700)
        support_names = sorted(path.name for path in inputs.support_bin.iterdir())
        self.assertEqual(
            support_names,
            ["age", "age-inspect", "age-keygen", "git", "python3", "ssh-keygen"],
        )
        expected_age_tools = Path(
            os.environ["AGE_TOOLING_DIRECTORY"]
        ).resolve(strict=True)
        for name in ("age", "age-inspect", "age-keygen"):
            self.assertEqual(
                (inputs.support_bin / name).resolve(strict=True),
                expected_age_tools / name,
            )
        self.assertEqual(
            sorted(path.name for path in inputs.fake_bin.iterdir()), ["pass-cli"]
        )
        self.assertFalse((inputs.support_bin / "pass-cli").exists())
        for source in inputs.support_bin.iterdir():
            (secure_support / source.name).symlink_to(source.resolve(strict=True))
        inputs.support_bin = secure_support
        if not trusted_path_ancestors_supported(inputs.root):
            self.skipTest("trusted-wrapper ancestors are UID-mapped in this sandbox")

        result = inputs.run(timeout=180)

        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (0, b"qualified-clean\n", b""),
        )
        evidence = json.loads((inputs.state / "qualified-clean.json").read_bytes())
        self.assertEqual(evidence["qualification"], "source-test")
        self.assertFalse(evidence["production_eligible"])
        self.assertFalse(evidence["authority"]["real_transition_authority"])
        self.assertFalse((inputs.state / "fixture").exists())
        self.assertFalse((inputs.state / "private/admission-ed25519").exists())
        log = inputs.log()
        self.assertGreaterEqual(sum(record["kind"] == "item-view" for record in log), 3)
        self.assertEqual(sum(record["kind"] == "agent-login" for record in log), 1)


if __name__ == "__main__":
    unittest.main()
