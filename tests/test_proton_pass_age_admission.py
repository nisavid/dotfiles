from __future__ import annotations

import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_SOURCE = (
    ROOT / "home/private_dot_local/bin/executable_proton-pass-age-admission"
)
NON_PROVIDER_SUPPORT = frozenset({"python3", "ssh-keygen"})


def resolved_non_provider_support(name: str) -> Path:
    if name not in NON_PROVIDER_SUPPORT:
        raise AssertionError(f"unsupported test command: {name}")
    raw_command = sys.executable if name == "python3" else shutil.which(name)
    if raw_command is None:
        raise unittest.SkipTest(f"required test support command is unavailable: {name}")
    return Path(raw_command).resolve(strict=True)


def _run(*arguments: str, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, check=True, **kwargs)  # type: ignore[arg-type]


_DIAGNOSTIC_EVENT_LIMIT = 512
_DIAGNOSTIC_TRACE_LIMIT = 128 * 1024
_DIAGNOSTIC_LATE_RETIREMENT_SECONDS = 2.0


def _adapter_diagnostic_harness(trace_path: Path, body: str) -> str:
    template = r'''\
import json
import os
import pathlib
import runpy
import shutil
import signal
import subprocess
import sys
import time

_DIAGNOSTIC_EVENT_LIMIT = 512
_DIAGNOSTIC_TRACE_LIMIT = 128 * 1024
_DIAGNOSTIC_TRACE_PATH = pathlib.Path(__TRACE_PATH__)
_diagnostic_adapter_globals = None
_diagnostic_dropped = 0
_diagnostic_events = []
_diagnostic_sequence = 0
_diagnostic_started = time.monotonic()


def _diagnostic_record(event, **fields):
    global _diagnostic_dropped, _diagnostic_sequence
    try:
        observation = {
            "elapsed_ms": round((time.monotonic() - _diagnostic_started) * 1000, 3),
            "event": event,
            "sequence": _diagnostic_sequence,
        }
        _diagnostic_sequence += 1
        observation.update(fields)
        _diagnostic_events.append(observation)
        if len(_diagnostic_events) > _DIAGNOSTIC_EVENT_LIMIT:
            del _diagnostic_events[0]
            _diagnostic_dropped += 1
    except BaseException:
        pass


def _diagnostic_classify(error, adapter_globals=None):
    try:
        if adapter_globals is None:
            adapter_globals = _diagnostic_adapter_globals
        if adapter_globals is not None:
            interrupted = adapter_globals.get("AdmissionAdapterInterrupted")
            if isinstance(interrupted, type) and isinstance(error, interrupted):
                return {
                    "classification": "adapter-interrupted",
                    "signal": int(error.signum),
                }
            adapter_error = adapter_globals.get("AdmissionAdapterError")
            if isinstance(adapter_error, type) and isinstance(error, adapter_error):
                result = {"classification": "adapter-error"}
                cause = getattr(error, "__cause__", None)
                if isinstance(cause, OSError):
                    result["cause_classification"] = "os-error"
                    result["cause_errno"] = cause.errno
                return result
        if isinstance(error, subprocess.TimeoutExpired):
            return {"classification": "subprocess-timeout"}
        if isinstance(error, subprocess.SubprocessError):
            return {"classification": "subprocess-error"}
        if isinstance(error, OSError):
            return {"classification": "os-error", "errno": error.errno}
        if isinstance(error, SystemExit):
            status = error.code if isinstance(error.code, int) else None
            return {"classification": "system-exit", "status": status}
        return {"classification": "other-base-exception"}
    except BaseException:
        return {"classification": "diagnostic-classification-failed"}


def _diagnostic_adapter_state(adapter_globals):
    try:
        state = {}
        for name in ("_PRIVATE_ROOT_STATE", "_PROCESS_STATE"):
            value = adapter_globals.get(name)
            if isinstance(value, str):
                state[name.removeprefix("_").lower()] = value
        process_group = adapter_globals.get("_ACTIVE_PROCESS_GROUP")
        if isinstance(process_group, int):
            state["active_process_group"] = process_group
        process = adapter_globals.get("_ACTIVE_PROCESS")
        process_pid = getattr(process, "pid", None)
        if isinstance(process_pid, int):
            state["active_process_pid"] = process_pid
        return state
    except BaseException:
        return {"state_classification": "diagnostic-state-failed"}


def _diagnostic_wrap_adapter_call(adapter_globals, name):
    original = adapter_globals[name]

    def diagnostic_adapter_call(*arguments, **keywords):
        fields = _diagnostic_adapter_state(adapter_globals)
        if name == "_terminate_process_group" and arguments:
            pid = getattr(arguments[0], "pid", None)
            if isinstance(pid, int):
                fields["pid"] = pid
        _diagnostic_record(f"adapter.{name}.start", **fields)
        try:
            result = original(*arguments, **keywords)
        except BaseException as error:
            fields = _diagnostic_adapter_state(adapter_globals)
            fields.update(_diagnostic_classify(error, adapter_globals))
            _diagnostic_record(f"adapter.{name}.error", **fields)
            raise
        fields = _diagnostic_adapter_state(adapter_globals)
        if isinstance(result, bool):
            fields["result"] = result
        _diagnostic_record(f"adapter.{name}.return", **fields)
        return result

    adapter_globals[name] = diagnostic_adapter_call


def _diagnostic_run_adapter(source, arguments):
    global _diagnostic_adapter_globals
    namespace = runpy.run_path(source, run_name="_synthetic_diagnostic_adapter")
    adapter_globals = namespace["main"].__globals__
    _diagnostic_adapter_globals = adapter_globals
    for name in (
        "create_receipt",
        "_cleanup_after_failure",
        "_cleanup_private_tree",
        "_terminate_process_group",
    ):
        _diagnostic_wrap_adapter_call(adapter_globals, name)
    sys.argv = [source, *arguments]
    _diagnostic_record("adapter.main.start", **_diagnostic_adapter_state(adapter_globals))
    try:
        status = adapter_globals["main"]()
    except BaseException as error:
        fields = _diagnostic_adapter_state(adapter_globals)
        fields.update(_diagnostic_classify(error, adapter_globals))
        _diagnostic_record("adapter.main.error", **fields)
        raise
    _diagnostic_record(
        "adapter.main.return",
        status=status if isinstance(status, int) else None,
        **_diagnostic_adapter_state(adapter_globals),
    )
    raise SystemExit(status)


_real_killpg = os.killpg


def _diagnostic_killpg(process_group, signum):
    try:
        result = _real_killpg(process_group, signum)
    except OSError as error:
        _diagnostic_record(
            "os.killpg",
            errno=error.errno,
            process_group=process_group,
            result="error",
            signal=int(signum),
        )
        raise
    _diagnostic_record(
        "os.killpg",
        process_group=process_group,
        result="present" if int(signum) == 0 else "sent",
        signal=int(signum),
    )
    return result


os.killpg = _diagnostic_killpg
_real_popen_init = subprocess.Popen.__init__
_real_popen_poll = subprocess.Popen.poll
_real_popen_wait = subprocess.Popen.wait


def _diagnostic_popen_init(self, *arguments, **keywords):
    _diagnostic_record("subprocess.Popen.start")
    try:
        _real_popen_init(self, *arguments, **keywords)
    except BaseException as error:
        fields = _diagnostic_classify(error)
        _diagnostic_record("subprocess.Popen.error", **fields)
        raise
    _diagnostic_record("subprocess.Popen.return", pid=self.pid)


def _diagnostic_popen_poll(self, *arguments, **keywords):
    try:
        status = _real_popen_poll(self, *arguments, **keywords)
    except BaseException as error:
        fields = _diagnostic_classify(error)
        _diagnostic_record("subprocess.Popen.poll.error", pid=self.pid, **fields)
        raise
    _diagnostic_record(
        "subprocess.Popen.poll",
        pid=self.pid,
        result="running" if status is None else "exited",
        status=status,
    )
    return status


def _diagnostic_popen_wait(self, *arguments, **keywords):
    try:
        status = _real_popen_wait(self, *arguments, **keywords)
    except BaseException as error:
        fields = _diagnostic_classify(error)
        _diagnostic_record("subprocess.Popen.wait.error", pid=self.pid, **fields)
        raise
    _diagnostic_record("subprocess.Popen.wait.return", pid=self.pid, status=status)
    return status


subprocess.Popen.__init__ = _diagnostic_popen_init
subprocess.Popen.poll = _diagnostic_popen_poll
subprocess.Popen.wait = _diagnostic_popen_wait
_real_rmtree = shutil.rmtree


def _diagnostic_rmtree(path, *arguments, **keywords):
    try:
        name = pathlib.Path(path).name
        target = "private-root" if name.startswith("proton-pass-age-admission.") else "other"
    except BaseException:
        target = "unclassified"
    _diagnostic_record("shutil.rmtree.start", target=target)
    try:
        result = _real_rmtree(path, *arguments, **keywords)
    except BaseException as error:
        fields = _diagnostic_classify(error)
        _diagnostic_record("shutil.rmtree.error", target=target, **fields)
        raise
    _diagnostic_record("shutil.rmtree.return", target=target)
    return result


shutil.rmtree = _diagnostic_rmtree


def _diagnostic_write_trace(outcome):
    try:
        payload = {
            "events": _diagnostic_events,
            "events_dropped": _diagnostic_dropped,
            "outcome": outcome,
            "schema": 1,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "ascii"
        )
        if len(encoded) > _DIAGNOSTIC_TRACE_LIMIT:
            payload["events"] = _diagnostic_events[-64:]
            payload["events_dropped"] += max(0, len(_diagnostic_events) - 64)
            payload["trace_truncated"] = True
            encoded = json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            ).encode("ascii")
        if len(encoded) > _DIAGNOSTIC_TRACE_LIMIT:
            encoded = b'{"classification":"diagnostic-trace-oversized","schema":1}'
        _DIAGNOSTIC_TRACE_PATH.write_bytes(encoded)
    except BaseException:
        pass


_diagnostic_outcome = {"classification": "body-returned"}
try:
__BODY__
except BaseException as error:
    _diagnostic_outcome = _diagnostic_classify(error)
    _diagnostic_record("harness.error", **_diagnostic_outcome)
    raise
finally:
    _diagnostic_write_trace(_diagnostic_outcome)
'''
    source = textwrap.dedent(template).replace(
        "__TRACE_PATH__", repr(os.fspath(trace_path))
    )
    return source.replace(
        "__BODY__", textwrap.indent(textwrap.dedent(body).strip(), "    ")
    )


def _synthetic_process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    return True


def _observe_synthetic_group_retirement(
    process_group: int, initially_present: bool
) -> dict[str, bool | float | None]:
    started = time.monotonic()
    present = initially_present
    while (
        present
        and time.monotonic() - started < _DIAGNOSTIC_LATE_RETIREMENT_SECONDS
    ):
        time.sleep(0.01)
        present = _synthetic_process_group_exists(process_group)
    return {
        "initially_present": initially_present,
        "present_at_deadline": present,
        "retired_after_ms": (
            round((time.monotonic() - started) * 1000, 3)
            if initially_present and not present
            else None
        ),
    }


def _synthetic_diagnostic_message(
    trace_path: Path, **observations: object
) -> str:
    trace: object
    try:
        size = trace_path.stat().st_size
        if size > _DIAGNOSTIC_TRACE_LIMIT:
            trace = {"classification": "diagnostic-trace-oversized"}
        else:
            trace = json.loads(trace_path.read_bytes())
            if not isinstance(trace, dict):
                trace = {"classification": "diagnostic-trace-invalid"}
    except OSError as error:
        trace = {
            "classification": "diagnostic-trace-unavailable",
            "errno": error.errno,
        }
    except (TypeError, ValueError):
        trace = {"classification": "diagnostic-trace-invalid"}
    return "synthetic diagnostic: " + json.dumps(
        {"observations": observations, "trace": trace},
        sort_keys=True,
        separators=(",", ":"),
    )


class ProtonPassAgeAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_parent = Path(tempfile.gettempdir()).resolve(strict=True)
        self.temporary = tempfile.TemporaryDirectory(
            prefix="proton-pass-age-admission.", dir=temporary_parent
        )
        self.root = Path(self.temporary.name).resolve(strict=True)
        self.bin = self.root / "bin"
        self.bin.mkdir(mode=0o700)
        self.support_bin = self.root / "support-bin"
        self.support_bin.mkdir(mode=0o700)
        self.ssh_keygen = resolved_non_provider_support("ssh-keygen")
        for name in sorted(NON_PROVIDER_SUPPORT):
            source = resolved_non_provider_support(name)
            (self.support_bin / name).symlink_to(source)
        self.adapter = self.bin / "proton-pass-age-admission"
        shutil.copy2(ADAPTER_SOURCE, self.adapter)
        self.adapter.chmod(0o700)

        self.signing_key = self.root / "fixture-signing-key"
        _run(
            os.fspath(self.ssh_keygen),
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-f",
            os.fspath(self.signing_key),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.fingerprint = self._fingerprint(self.signing_key)
        self.key_bytes = self.signing_key.read_bytes()

        self.base = self.root / "base"
        self.head = self.root / "head"
        self.base.mkdir()
        self.head.mkdir()
        self.identity = self.root / "age-identity"
        self.identity.write_text("disposable identity fixture\n", encoding="ascii")
        self.identity.chmod(0o600)
        self.admitter = self.base / "scripts/admit-age-envelopes"
        self.admitter.parent.mkdir()
        self.admitter.write_text("fixture\n", encoding="ascii")
        self.admitter.chmod(0o755)
        self.output = self.root / "receipt.txt"
        self.provider_marker = self.root / "provider.marker"
        self.readiness_marker = self.root / "readiness.marker"
        self.preflight_marker = self.root / "preflight.marker"
        self.preflight_outcome = self.root / "preflight.outcome"
        self.preflight_outcome.write_text("required\n", encoding="ascii")
        self.preflight_stderr = self.root / "preflight.stderr"
        self.preflight_stderr.write_bytes(b"")
        self.wrapper_marker = self.root / "wrapper.marker"

        self._write_executable(
            "proton-pass-ensure-ready",
            f"""
            #!/bin/sh
            test -z "${{PROTON_PASS_PERSONAL_ACCESS_TOKEN-}}" || exit 91
            printf ready > {os.fspath(self.readiness_marker)!r}
            exit 0
            """,
        )
        self._write_provider(self.signing_key)
        self.wrapper = self.root / "trusted-wrapper"
        self._write_wrapper(
            """
            output_path.write_text("fixture receipt\\n", encoding="ascii")
            output_path.chmod(0o600)
            """
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_executable(self, name: str, source: str) -> Path:
        path = self.bin / name
        path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
        path.chmod(0o700)
        return path

    def _fingerprint(self, key: Path) -> str:
        result = _run(
            os.fspath(self.ssh_keygen),
            "-lf",
            os.fspath(key.with_suffix(".pub")),
            "-E",
            "sha256",
            capture_output=True,
        )
        return result.stdout.decode("ascii").split()[1]

    def _write_provider(
        self,
        payload: Path | None,
        *,
        delay_seconds: int = 0,
        exit_status: int = 0,
    ) -> None:
        payload_statement = (
            f"data = pathlib.Path({os.fspath(payload)!r}).read_bytes()"
            if payload is not None
            else "data = b''"
        )
        self._write_executable(
            "pass-cli",
            f"""
            #!/usr/bin/env python3
            import os
            import pathlib
            import sys
            import time

            expected = [
                "item", "view", "--share-id", "fixture_share_286",
                "--item-id", "fixture_item_286", "--field", "SSH.private_key",
                "--output", "human",
            ]
            if sys.argv[1:] != expected:
                raise SystemExit(92)
            if os.environ.get("PROTON_PASS_PERSONAL_ACCESS_TOKEN"):
                raise SystemExit(93)
            if sys.platform.startswith("linux") and os.environ.get(
                "PROTON_PASS_LINUX_KEYRING"
            ) != "dbus":
                raise SystemExit(94)
            if os.environ.get("PROTON_PASS_NO_UPDATE_CHECK") != "1":
                raise SystemExit(95)
            if os.environ.get("PROTON_PASS_AGENT_REASON") != (
                "age-admission signing-key retrieval"
            ):
                raise SystemExit(96)
            {payload_statement}
            if data and any(data in os.fsencode(value) for value in os.environ.values()):
                raise SystemExit(97)
            if data and data in os.fsencode(" ".join(sys.argv)):
                raise SystemExit(98)
            pathlib.Path({os.fspath(self.provider_marker)!r}).write_text(
                "selected-field", encoding="ascii"
            )
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
            time.sleep({delay_seconds})
            raise SystemExit({exit_status})
            """,
        )

    def _write_wrapper(self, behavior: str) -> None:
        source = f"""\
from __future__ import annotations

import os
import pathlib
import shutil
import stat
import sys
import tempfile

arguments = sys.argv[1:]
separator = arguments.index("--")
creator_arguments = arguments[separator + 1:]
if creator_arguments[:2] == ["--operation", "preflight"]:
    expected_preflight = [
        "--operation", "preflight",
        "--base-repository", {os.fspath(self.base)!r},
        "--base-commit", {"a" * 40!r},
        "--head-repository", {os.fspath(self.head)!r},
        "--head-commit", {"b" * 40!r},
    ]
    if creator_arguments != expected_preflight:
        raise SystemExit(89)
    pathlib.Path({os.fspath(self.preflight_marker)!r}).write_text(
        "classified", encoding="ascii"
    )
    outcome = pathlib.Path({os.fspath(self.preflight_outcome)!r}).read_text(
        encoding="ascii"
    ).strip()
    diagnostic = pathlib.Path({os.fspath(self.preflight_stderr)!r}).read_bytes()
    sys.stderr.buffer.write(diagnostic)
    sys.stderr.buffer.flush()
    print(outcome)
    if outcome == "required":
        raise SystemExit(0)
    if outcome == "not-required":
        raise SystemExit(10)
    raise SystemExit(11)
key_path = pathlib.Path(arguments[arguments.index("--signing-key") + 1])
output_path = pathlib.Path(arguments[arguments.index("--output") + 1])
expected = pathlib.Path({os.fspath(self.signing_key)!r}).read_bytes()
actual = key_path.read_bytes()
if (
    actual != expected
    or stat.S_IMODE(key_path.stat().st_mode) != 0o600
    or stat.S_IMODE(key_path.parent.stat().st_mode) != 0o700
):
    raise SystemExit(81)
decoded = expected.decode("ascii")
if any(decoded in argument for argument in sys.argv):
    raise SystemExit(82)
if any(decoded in value for value in os.environ.values()):
    raise SystemExit(83)
staged_root = pathlib.Path(tempfile.mkdtemp(prefix="age-admission-sign."))
staged_key = staged_root / "signing-key"
shutil.copyfile(key_path, staged_key)
staged_key.chmod(0o600)
pathlib.Path({os.fspath(self.wrapper_marker)!r}).write_text(
    f"{{key_path}}\\n{{staged_key}}\\n{{output_path}}\\n", encoding="utf-8"
)
"""
        self.wrapper.write_text(
            source + textwrap.dedent(behavior).lstrip(),
            encoding="utf-8",
        )
        self.wrapper.chmod(0o755)

    def _command(self, **overrides: str) -> list[str]:
        values = {
            "share_id": "fixture_share_286",
            "item_id": "fixture_item_286",
            "expected_fingerprint": self.fingerprint,
            "trusted_launcher": os.fspath(self.wrapper),
            "base_repository": os.fspath(self.base),
            "base_commit": "a" * 40,
            "head_repository": os.fspath(self.head),
            "head_commit": "b" * 40,
            "repository": "fixture/dotfiles",
            "identity": os.fspath(self.identity),
            "trusted_admitter": os.fspath(self.admitter),
            "output": os.fspath(self.output),
        }
        values.update(overrides)
        return [
            os.fspath(self.adapter),
            "--share-id",
            values["share_id"],
            "--item-id",
            values["item_id"],
            "--expected-fingerprint",
            values["expected_fingerprint"],
            "--trusted-launcher",
            values["trusted_launcher"],
            "--base-repository",
            values["base_repository"],
            "--base-commit",
            values["base_commit"],
            "--head-repository",
            values["head_repository"],
            "--head-commit",
            values["head_commit"],
            "--repository",
            values["repository"],
            "--identity",
            values["identity"],
            "--trusted-admitter",
            values["trusted_admitter"],
            "--output",
            values["output"],
        ]

    def _environment(self) -> dict[str, str]:
        home = self.root / "home"
        home.mkdir(mode=0o700, exist_ok=True)
        return {
            "HOME": os.fspath(home),
            "LC_ALL": "C",
            "PATH": os.pathsep.join((os.fspath(self.bin), os.fspath(self.support_bin))),
            "TEMP": os.fspath(self.root),
            "TMP": os.fspath(self.root),
            "TMPDIR": os.fspath(self.root),
        }

    def test_selected_field_creates_receipt_and_removes_private_copies(self) -> None:
        result = subprocess.run(
            self._command(),
            check=False,
            capture_output=True,
            env=self._environment(),
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"")
        self.assertEqual(self.readiness_marker.read_text(encoding="ascii"), "ready")
        self.assertEqual(
            self.provider_marker.read_text(encoding="ascii"), "selected-field"
        )
        self.assertEqual(self.output.read_text(encoding="ascii"), "fixture receipt\n")
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)
        private_paths = self.wrapper_marker.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(private_paths), 3)
        self.assertTrue(
            Path(private_paths[1]).is_relative_to(Path(private_paths[0]).parent)
        )
        self.assertTrue(
            Path(private_paths[2]).is_relative_to(Path(private_paths[0]).parent)
        )
        for private_path in private_paths:
            self.assertFalse(Path(private_path).exists())
        self.assertNotIn(self.key_bytes, result.stdout)
        self.assertNotIn(self.key_bytes, result.stderr)

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "Linux exposes ssh-keygen through PATH for fake-only child observation",
    )
    def test_agent_reason_is_scoped_to_selected_field_retrieval(self) -> None:
        reason_log = self.root / "agent-reason.log"
        absent = "<absent>"
        self._write_executable(
            "proton-pass-ensure-ready",
            f"""
            #!/usr/bin/env python3
            import os
            import pathlib

            with pathlib.Path({os.fspath(reason_log)!r}).open(
                "a", encoding="ascii"
            ) as stream:
                print(
                    "readiness\\t"
                    + os.environ.get("PROTON_PASS_AGENT_REASON", {absent!r}),
                    file=stream,
                )
            """,
        )
        self._write_executable(
            "pass-cli",
            f"""
            #!/usr/bin/env python3
            import os
            import pathlib
            import sys

            expected = [
                "item", "view", "--share-id", "fixture_share_286",
                "--item-id", "fixture_item_286", "--field", "SSH.private_key",
                "--output", "human",
            ]
            if sys.argv[1:] != expected:
                raise SystemExit(92)
            with pathlib.Path({os.fspath(reason_log)!r}).open(
                "a", encoding="ascii"
            ) as stream:
                print(
                    "retrieval\\t"
                    + os.environ.get("PROTON_PASS_AGENT_REASON", {absent!r}),
                    file=stream,
                )
            sys.stdout.buffer.write(
                pathlib.Path({os.fspath(self.signing_key)!r}).read_bytes()
            )
            """,
        )
        self._write_executable(
            "ssh-keygen",
            f"""
            #!/usr/bin/env python3
            import os
            import pathlib
            import sys

            with pathlib.Path({os.fspath(reason_log)!r}).open(
                "a", encoding="ascii"
            ) as stream:
                print(
                    "ssh-keygen\\t"
                    + os.environ.get("PROTON_PASS_AGENT_REASON", {absent!r}),
                    file=stream,
                )
            real_tool = {os.fspath(self.ssh_keygen)!r}
            os.execv(real_tool, [real_tool, *sys.argv[1:]])
            """,
        )
        self.wrapper.write_text(
            textwrap.dedent(
                f"""\
                import os
                import pathlib
                import stat
                import sys

                arguments = sys.argv[1:]
                separator = arguments.index("--")
                creator_arguments = arguments[separator + 1:]
                preflight = creator_arguments[:2] == ["--operation", "preflight"]
                role = "preflight" if preflight else "receipt"
                with pathlib.Path({os.fspath(reason_log)!r}).open(
                    "a", encoding="ascii"
                ) as stream:
                    print(
                        role
                        + "\\t"
                        + os.environ.get("PROTON_PASS_AGENT_REASON", {absent!r}),
                        file=stream,
                    )
                if preflight:
                    print("required")
                    raise SystemExit(0)
                key_path = pathlib.Path(
                    arguments[arguments.index("--signing-key") + 1]
                )
                output_path = pathlib.Path(arguments[arguments.index("--output") + 1])
                if (
                    key_path.read_bytes()
                    != pathlib.Path({os.fspath(self.signing_key)!r}).read_bytes()
                    or stat.S_IMODE(key_path.stat().st_mode) != 0o600
                ):
                    raise SystemExit(81)
                output_path.write_text("fixture receipt\\n", encoding="ascii")
                output_path.chmod(0o600)
                """
            ),
            encoding="ascii",
        )
        self.wrapper.chmod(0o755)
        environment = self._environment()
        environment["PROTON_PASS_AGENT_REASON"] = "hostile inherited reason"

        result = subprocess.run(
            self._command(),
            check=False,
            capture_output=True,
            env=environment,
            timeout=30,
        )

        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (0, b"", b""),
        )
        self.assertEqual(self.output.read_text(encoding="ascii"), "fixture receipt\n")
        self.assertEqual(
            reason_log.read_text(encoding="ascii").splitlines(),
            [
                f"preflight\t{absent}",
                f"readiness\t{absent}",
                "retrieval\tage-admission signing-key retrieval",
                f"ssh-keygen\t{absent}",
                f"receipt\t{absent}",
            ],
        )

    def test_preflight_stops_before_provider_when_admission_is_not_required_or_indeterminate(
        self,
    ) -> None:
        for outcome in ("not-required", "indeterminate"):
            with self.subTest(outcome=outcome):
                self.preflight_outcome.write_text(f"{outcome}\n", encoding="ascii")
                self.preflight_marker.unlink(missing_ok=True)
                self.readiness_marker.unlink(missing_ok=True)
                self.provider_marker.unlink(missing_ok=True)
                self.wrapper_marker.unlink(missing_ok=True)
                self.output.unlink(missing_ok=True)

                result = subprocess.run(
                    self._command(),
                    check=False,
                    capture_output=True,
                    env=self._environment(),
                    timeout=30,
                )

                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(
                    result.stderr,
                    b"proton-pass age admission failed\n",
                )
                self.assertEqual(
                    self.preflight_marker.read_text(encoding="ascii"),
                    "classified",
                )
                self.assertFalse(self.readiness_marker.exists())
                self.assertFalse(self.provider_marker.exists())
                self.assertFalse(self.wrapper_marker.exists())
                self.assertFalse(self.output.exists())
                self.assertEqual(
                    list(self.root.glob("proton-pass-age-admission.*")),
                    [],
                )

    def test_preflight_diagnostics_stop_before_readiness_and_provider_access(
        self,
    ) -> None:
        cases = (
            ("required with stderr", "required", b"required diagnostic sentinel\n"),
            (
                "not-required with stderr",
                "not-required",
                b"not-required diagnostic sentinel\n",
            ),
            (
                "indeterminate with stderr",
                "indeterminate",
                b"indeterminate diagnostic sentinel\n",
            ),
            (
                "required with oversized stderr",
                "required",
                b"oversized diagnostic sentinel:" + b"x" * (128 * 1024),
            ),
        )
        for name, outcome, diagnostic in cases:
            with self.subTest(name=name):
                self.preflight_outcome.write_text(f"{outcome}\n", encoding="ascii")
                self.preflight_stderr.write_bytes(diagnostic)
                self.preflight_marker.unlink(missing_ok=True)
                self.readiness_marker.unlink(missing_ok=True)
                self.provider_marker.unlink(missing_ok=True)
                self.wrapper_marker.unlink(missing_ok=True)
                self.output.unlink(missing_ok=True)

                result = subprocess.run(
                    self._command(),
                    check=False,
                    capture_output=True,
                    env=self._environment(),
                    timeout=30,
                )

                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(
                    result.stderr,
                    b"proton-pass age admission failed\n",
                )
                self.assertNotIn(b"diagnostic sentinel", result.stdout)
                self.assertNotIn(b"diagnostic sentinel", result.stderr)
                self.assertEqual(
                    self.preflight_marker.read_text(encoding="ascii"),
                    "classified",
                )
                self.assertFalse(self.readiness_marker.exists())
                self.assertFalse(self.provider_marker.exists())
                self.assertFalse(self.wrapper_marker.exists())
                self.assertFalse(self.output.exists())
                self.assertEqual(
                    list(self.root.glob("proton-pass-age-admission.*")),
                    [],
                )

    def test_failed_wrapper_removes_output_and_private_copies(self) -> None:
        self._write_wrapper(
            """
            output_path.write_text("unusable receipt\\n", encoding="ascii")
            output_path.chmod(0o600)
            raise SystemExit(77)
            """
        )

        result = subprocess.run(
            self._command(),
            check=False,
            capture_output=True,
            env=self._environment(),
            timeout=30,
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"proton-pass age admission failed\n")
        self.assertFalse(self.output.exists())
        private_paths = self.wrapper_marker.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(private_paths), 3)
        for private_path in private_paths:
            self.assertFalse(Path(private_path).exists())
        self.assertNotIn(self.key_bytes, result.stdout)
        self.assertNotIn(self.key_bytes, result.stderr)

    def test_successful_wrapper_must_install_a_private_receipt(self) -> None:
        scenarios = {
            "missing": "raise SystemExit(0)",
            "empty": ('output_path.write_bytes(b"\\n"[:0])\noutput_path.chmod(0o600)'),
            "readable": (
                'output_path.write_text("fixture receipt\\n", encoding="ascii")\n'
                "output_path.chmod(0o644)"
            ),
        }
        for label, behavior in scenarios.items():
            with self.subTest(label=label):
                self.output.unlink(missing_ok=True)
                self.wrapper_marker.unlink(missing_ok=True)
                self._write_wrapper(behavior)

                result = subprocess.run(
                    self._command(),
                    check=False,
                    capture_output=True,
                    env=self._environment(),
                    timeout=30,
                )

                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(
                    result.stderr,
                    b"proton-pass age admission failed\n",
                )
                self.assertFalse(self.output.exists())
                private_paths = self.wrapper_marker.read_text(
                    encoding="utf-8"
                ).splitlines()
                for private_path in private_paths:
                    self.assertFalse(Path(private_path).exists())

    def test_rejects_unavailable_malformed_mismatched_encrypted_truncated_and_oversized_data(
        self,
    ) -> None:
        malformed = self.root / "malformed-key"
        malformed.write_bytes(b"not an SSH private key\n")
        malformed.chmod(0o600)
        truncated = self.root / "truncated-key"
        truncated.write_bytes(self.key_bytes[: len(self.key_bytes) // 2])
        truncated.chmod(0o600)
        oversized = self.root / "oversized-key"
        oversized.write_bytes(b"x" * (64 * 1024 + 1))
        oversized.chmod(0o600)

        other_key = self.root / "other-key"
        _run(
            os.fspath(self.ssh_keygen),
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-f",
            os.fspath(other_key),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        encrypted_key = self.root / "encrypted-key"
        _run(
            os.fspath(self.ssh_keygen),
            "-q",
            "-t",
            "ed25519",
            "-N",
            "disposable-fixture-passphrase",
            "-f",
            os.fspath(encrypted_key),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        non_ed25519_key = self.root / "non-ed25519-key"
        _run(
            os.fspath(self.ssh_keygen),
            "-q",
            "-t",
            "rsa",
            "-b",
            "2048",
            "-N",
            "",
            "-f",
            os.fspath(non_ed25519_key),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        scenarios = (
            ("missing", None, self.fingerprint, 0),
            ("unavailable", None, self.fingerprint, 75),
            ("malformed", malformed, self.fingerprint, 0),
            ("mismatched", other_key, self.fingerprint, 0),
            ("encrypted", encrypted_key, self._fingerprint(encrypted_key), 0),
            (
                "matching-non-ed25519",
                non_ed25519_key,
                self._fingerprint(non_ed25519_key),
                0,
            ),
            ("truncated", truncated, self.fingerprint, 0),
            ("oversized", oversized, self.fingerprint, 0),
        )
        for label, payload, fingerprint, exit_status in scenarios:
            with self.subTest(label=label):
                self.provider_marker.unlink(missing_ok=True)
                self.wrapper_marker.unlink(missing_ok=True)
                self.output.unlink(missing_ok=True)
                self._write_provider(payload, exit_status=exit_status)

                result = subprocess.run(
                    self._command(expected_fingerprint=fingerprint),
                    check=False,
                    capture_output=True,
                    env=self._environment(),
                    timeout=30,
                )

                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(
                    result.stderr,
                    b"proton-pass age admission failed\n",
                )
                self.assertFalse(self.output.exists())
                self.assertFalse(self.wrapper_marker.exists())
                self.assertEqual(
                    list(self.root.glob("proton-pass-age-admission.*")),
                    [],
                )
                if payload is not None:
                    payload_bytes = payload.read_bytes()
                    self.assertNotIn(payload_bytes, result.stdout)
                    self.assertNotIn(payload_bytes, result.stderr)

    def test_provider_timeout_removes_partial_private_file(self) -> None:
        self._write_provider(self.signing_key, delay_seconds=10)

        result = subprocess.run(
            self._command(),
            check=False,
            capture_output=True,
            env=self._environment(),
            timeout=10,
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"proton-pass age admission failed\n")
        self.assertFalse(self.output.exists())
        self.assertFalse(self.wrapper_marker.exists())
        self.assertEqual(list(self.root.glob("proton-pass-age-admission.*")), [])
        self.assertNotIn(self.key_bytes, result.stdout)
        self.assertNotIn(self.key_bytes, result.stderr)

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "Linux uses the PATH-selected production ssh-keygen",
    )
    def test_path_selected_public_key_derivation_output_is_bounded(self) -> None:
        self._write_executable(
            "ssh-keygen",
            """
            #!/usr/bin/env python3
            import sys
            import time

            sys.stdout.buffer.write(b"x" * 2048)
            sys.stdout.buffer.flush()
            time.sleep(30)
            """,
        )

        started = time.monotonic()
        result = subprocess.run(
            self._command(),
            check=False,
            capture_output=True,
            env=self._environment(),
            timeout=10,
        )

        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"proton-pass age admission failed\n")
        self.assertFalse(self.output.exists())
        self.assertFalse(self.wrapper_marker.exists())
        self.assertEqual(list(self.root.glob("proton-pass-age-admission.*")), [])

    @unittest.skipUnless(
        sys.platform == "darwin",
        "Darwin production pin is platform-specific",
    )
    def test_darwin_public_key_derivation_ignores_path_override(self) -> None:
        path_override_marker = self.root / "path-ssh-keygen.marker"
        self._write_executable(
            "ssh-keygen",
            f"""
            #!/bin/sh
            printf invoked > {os.fspath(path_override_marker)!r}
            exit 97
            """,
        )

        result = subprocess.run(
            self._command(),
            check=False,
            capture_output=True,
            env=self._environment(),
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertFalse(path_override_marker.exists())
        self.assertEqual(self.output.read_text(encoding="ascii"), "fixture receipt\n")

    def test_receipt_timeout_removes_output_and_private_copies(self) -> None:
        self._write_wrapper(
            """
            import time
            output_path.write_text("incomplete receipt\\n", encoding="ascii")
            output_path.chmod(0o600)
            time.sleep(30)
            """
        )

        result = subprocess.run(
            [*self._command(), "--receipt-timeout-seconds", "1"],
            check=False,
            capture_output=True,
            env=self._environment(),
            timeout=10,
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"proton-pass age admission failed\n")
        self.assertFalse(self.output.exists())
        private_paths = self.wrapper_marker.read_text(encoding="utf-8").splitlines()
        for private_path in private_paths:
            self.assertFalse(Path(private_path).exists())

    def test_receipt_is_published_only_after_transient_cleanup_error_recovers(
        self,
    ) -> None:
        self._write_wrapper(
            f"""
            import subprocess

            output_path.write_text("fixture receipt\\n", encoding="ascii")
            output_path.chmod(0o600)
            cleanup_parent = pathlib.Path({os.fspath(self.root)!r})
            cleanup_parent.chmod(0o500)
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    (
                        "import pathlib, time; time.sleep(0.2); "
                        "pathlib.Path("
                        + {os.fspath(self.root)!r}.__repr__()
                        + ").chmod(0o700)"
                    ),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            """
        )

        result = subprocess.run(
            self._command(),
            check=False,
            capture_output=True,
            env=self._environment(),
            timeout=30,
        )

        self.root.chmod(0o700)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(self.output.read_text(encoding="ascii"), "fixture receipt\n")
        private_paths = self.wrapper_marker.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(private_paths), 3)
        for private_path in private_paths:
            self.assertFalse(Path(private_path).exists())

    def test_unrecoverable_cleanup_error_cannot_leave_a_receipt(self) -> None:
        self._write_wrapper(
            f"""
            output_path.write_text("fixture receipt\\n", encoding="ascii")
            output_path.chmod(0o600)
            pathlib.Path({os.fspath(self.root)!r}).chmod(0o500)
            """
        )

        result = subprocess.run(
            self._command(),
            check=False,
            capture_output=True,
            env=self._environment(),
            timeout=30,
        )

        self.root.chmod(0o700)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"proton-pass age admission failed\n")
        self.assertFalse(self.output.exists())
        private_paths = self.wrapper_marker.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(private_paths), 3)
        for private_path in private_paths:
            self.assertFalse(Path(private_path).exists())
        self.assertNotIn(self.key_bytes, result.stdout)
        self.assertNotIn(self.key_bytes, result.stderr)

    def test_term_during_private_tree_cleanup_cannot_leave_a_receipt(self) -> None:
        signal_marker = self.root / "late-signal.marker"
        self._write_wrapper(
            f"""
            import subprocess

            cleanup_delay = key_path.parent / "cleanup-delay"
            cleanup_delay.mkdir()
            for index in range(25000):
                (cleanup_delay / str(index)).touch()
            output_path.write_text("fixture receipt\\n", encoding="ascii")
            output_path.chmod(0o600)
            parent_pid = os.getppid()
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    (
                        "import os, pathlib, signal, time; time.sleep(0.05); "
                        f"os.kill({{parent_pid}}, signal.SIGTERM); "
                        "pathlib.Path("
                        + {os.fspath(signal_marker)!r}.__repr__()
                        + ").write_text('sent')"
                    ),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            """
        )

        result = subprocess.run(
            self._command(),
            check=False,
            capture_output=True,
            env=self._environment(),
            timeout=30,
        )

        for _ in range(100):
            if signal_marker.exists():
                break
            time.sleep(0.01)
        self.assertEqual(result.returncode, 143)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"proton-pass age admission interrupted\n")
        self.assertEqual(signal_marker.read_text(encoding="ascii"), "sent")
        self.assertFalse(self.output.exists())
        private_paths = self.wrapper_marker.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(private_paths), 3)
        for private_path in private_paths:
            self.assertFalse(Path(private_path).exists())
        self.assertNotIn(self.key_bytes, result.stdout)
        self.assertNotIn(self.key_bytes, result.stderr)

    def test_term_interruption_removes_output_and_private_copies(self) -> None:
        self._write_wrapper(
            """
            import time
            output_path.write_text("incomplete receipt\\n", encoding="ascii")
            output_path.chmod(0o600)
            time.sleep(30)
            """
        )
        process = subprocess.Popen(
            self._command(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._environment(),
        )
        for _ in range(100):
            if self.wrapper_marker.exists():
                break
            time.sleep(0.05)
        self.assertTrue(self.wrapper_marker.exists())

        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)

        self.assertEqual(process.returncode, 143)
        self.assertEqual(stdout, b"")
        self.assertEqual(stderr, b"proton-pass age admission interrupted\n")
        self.assertFalse(self.output.exists())
        private_paths = self.wrapper_marker.read_text(encoding="utf-8").splitlines()
        for private_path in private_paths:
            self.assertFalse(Path(private_path).exists())
        self.assertNotIn(self.key_bytes, stdout)
        self.assertNotIn(self.key_bytes, stderr)

    def test_term_during_popen_acquisition_retires_the_real_child_group(self) -> None:
        self.wrapper.write_text(
            textwrap.dedent(
                """\
                import time

                time.sleep(30)
                """
            ),
            encoding="ascii",
        )
        self.wrapper.chmod(0o755)
        boundary_child_path = self.root / "boundary-child.pid"
        diagnostic_path = self.root / "popen-acquisition-diagnostic.json"
        harness = _adapter_diagnostic_harness(
            diagnostic_path,
            f"""\
            real_popen = subprocess.Popen
            triggered = False

            def signal_before_return(*arguments, **keywords):
                global triggered
                process = real_popen(*arguments, **keywords)
                if not triggered:
                    triggered = True
                    pathlib.Path({os.fspath(boundary_child_path)!r}).write_text(
                        str(process.pid), encoding="ascii"
                    )
                    _diagnostic_record(
                        "synthetic.signal-injected",
                        child_pid=process.pid,
                        process_pid=os.getpid(),
                        signal=int(signal.SIGTERM),
                    )
                    os.kill(os.getpid(), signal.SIGTERM)
                return process

            subprocess.Popen = signal_before_return
            source = sys.argv[1]
            _diagnostic_run_adapter(source, sys.argv[2:])
            """,
        )

        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-S",
                "-c",
                harness,
                os.fspath(self.adapter),
                *self._command()[1:],
            ],
            check=False,
            capture_output=True,
            env=self._environment(),
            start_new_session=True,
            timeout=10,
        )

        child_pid = int(boundary_child_path.read_text(encoding="ascii"))
        child_survived = _synthetic_process_group_exists(child_pid)
        late_retirement = _observe_synthetic_group_retirement(
            child_pid, child_survived
        )
        if late_retirement["present_at_deadline"]:
            os.killpg(child_pid, signal.SIGKILL)
        diagnostic = _synthetic_diagnostic_message(
            diagnostic_path,
            child_group=late_retirement,
            child_pid=child_pid,
            returncode=result.returncode,
        )
        self.assertTrue(
            (result.returncode, result.stdout, result.stderr)
            == (143, b"", b"proton-pass age admission interrupted\n"),
            diagnostic,
        )
        self.assertFalse(child_survived, diagnostic)
        self.assertFalse(self.output.exists(), diagnostic)
        self.assertEqual(
            list(self.root.glob("proton-pass-age-admission.*")), [], diagnostic
        )

    def test_term_during_private_root_acquisition_stops_before_child_effects(
        self,
    ) -> None:
        boundary_root_path = self.root / "boundary-root.path"
        harness = textwrap.dedent(
            f"""\
            import os
            import pathlib
            import runpy
            import signal
            import sys
            import tempfile

            real_mkdtemp = tempfile.mkdtemp
            triggered = False

            def signal_before_return(*arguments, **keywords):
                global triggered
                path = real_mkdtemp(*arguments, **keywords)
                if not triggered:
                    triggered = True
                    pathlib.Path({os.fspath(boundary_root_path)!r}).write_text(
                        path, encoding="utf-8"
                    )
                    os.kill(os.getpid(), signal.SIGTERM)
                return path

            tempfile.mkdtemp = signal_before_return
            source = sys.argv[1]
            sys.argv = [source, *sys.argv[2:]]
            runpy.run_path(source, run_name="__main__")
            """
        )

        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-S",
                "-c",
                harness,
                os.fspath(self.adapter),
                *self._command()[1:],
            ],
            check=False,
            capture_output=True,
            env=self._environment(),
            start_new_session=True,
            timeout=10,
        )

        created_root = Path(boundary_root_path.read_text(encoding="utf-8"))
        root_survived = created_root.exists()
        if root_survived:
            shutil.rmtree(created_root)
        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (143, b"", b"proton-pass age admission interrupted\n"),
        )
        self.assertFalse(root_survived)
        self.assertFalse(self.preflight_marker.exists())
        self.assertFalse(self.readiness_marker.exists())
        self.assertFalse(self.provider_marker.exists())
        self.assertFalse(self.output.exists())

    def test_inherited_blocked_signals_are_cleared_before_child_effects(
        self,
    ) -> None:
        termination_signals = (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
        termination_signal_numbers = {int(signum) for signum in termination_signals}

        for signum in termination_signals:
            with self.subTest(signal=signum.name):
                child_state_path = self.root / f"child-state-{int(signum)}.json"
                diagnostic_path = (
                    self.root / f"inherited-signal-{int(signum)}-diagnostic.json"
                )
                supervisor = _adapter_diagnostic_harness(
                    diagnostic_path,
                    """\
                    termination_signals = (
                        signal.SIGHUP,
                        signal.SIGINT,
                        signal.SIGTERM,
                    )
                    signal.pthread_sigmask(signal.SIG_BLOCK, termination_signals)
                    for inherited_signum in termination_signals:
                        signal.signal(inherited_signum, signal.SIG_IGN)
                    source = sys.argv[1]
                    _diagnostic_run_adapter(source, sys.argv[2:])
                    """,
                )
                self.output.unlink(missing_ok=True)
                self.wrapper.write_text(
                    textwrap.dedent(
                        f"""\
                        import json
                        import os
                        import pathlib
                        import signal
                        import time

                        termination_signals = (
                            signal.SIGHUP,
                            signal.SIGINT,
                            signal.SIGTERM,
                        )
                        blocked = signal.pthread_sigmask(signal.SIG_BLOCK, set())
                        pathlib.Path({os.fspath(child_state_path)!r}).write_text(
                            json.dumps(
                                {{
                                    "blocked": sorted(int(item) for item in blocked),
                                    "ignored": {{
                                        str(int(item)): signal.getsignal(item)
                                        == signal.SIG_IGN
                                        for item in termination_signals
                                    }},
                                    "pgid": os.getpgrp(),
                                    "pid": os.getpid(),
                                    "private_root": os.environ["TMPDIR"],
                                }},
                                sort_keys=True,
                            ),
                            encoding="ascii",
                        )
                        time.sleep(30)
                        """
                    ),
                    encoding="ascii",
                )
                self.wrapper.chmod(0o755)
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-I",
                        "-B",
                        "-S",
                        "-c",
                        supervisor,
                        os.fspath(self.adapter),
                        *self._command()[1:],
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=self._environment(),
                    start_new_session=True,
                )
                child_state = None
                private_root = None
                stdout = b""
                stderr = b""
                observed_status = None
                adapter_group_survived = False
                child_group_survived = False
                child_group_observation = None
                private_root_survived = False
                try:
                    deadline = time.monotonic() + 5
                    while (
                        not child_state_path.exists()
                        and process.poll() is None
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.01)
                    if child_state_path.exists():
                        child_state = json.loads(child_state_path.read_bytes())
                        private_root = Path(child_state["private_root"])
                        process.send_signal(signum)
                        try:
                            stdout, stderr = process.communicate(timeout=5)
                        except subprocess.TimeoutExpired:
                            pass
                        observed_status = process.returncode
                        adapter_group_survived = _synthetic_process_group_exists(
                            process.pid
                        )
                        child_group_survived = _synthetic_process_group_exists(
                            child_state["pgid"]
                        )
                        child_group_observation = (
                            _observe_synthetic_group_retirement(
                                child_state["pgid"], child_group_survived
                            )
                        )
                        private_root_survived = private_root.exists()
                finally:
                    if process.poll() is None:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.communicate(timeout=5)
                    if child_state is None and child_state_path.exists():
                        child_state = json.loads(child_state_path.read_bytes())
                        private_root = Path(child_state["private_root"])
                    if child_state is not None:
                        child_group = child_state["pgid"]
                        if _synthetic_process_group_exists(child_group):
                            try:
                                os.killpg(child_group, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                        cleanup_deadline = time.monotonic() + 5
                        while (
                            _synthetic_process_group_exists(child_group)
                            and time.monotonic() < cleanup_deadline
                        ):
                            time.sleep(0.01)
                    if private_root is not None and private_root.exists():
                        shutil.rmtree(private_root)

                safe_child_state = None
                if child_state is not None:
                    safe_child_state = {
                        "blocked": child_state["blocked"],
                        "ignored": child_state["ignored"],
                        "pgid": child_state["pgid"],
                        "pid": child_state["pid"],
                    }
                diagnostic = _synthetic_diagnostic_message(
                    diagnostic_path,
                    adapter_group_survived=adapter_group_survived,
                    child_group=child_group_observation,
                    child_group_survived=child_group_survived,
                    child_state=safe_child_state,
                    private_root_survived=private_root_survived,
                    returncode=observed_status,
                    signal=int(signum),
                )
                self.assertIsNotNone(child_state, diagnostic)
                assert child_state is not None
                self.assertEqual(
                    set(child_state["blocked"]).intersection(
                        termination_signal_numbers
                    ),
                    set(),
                    diagnostic,
                )
                self.assertFalse(any(child_state["ignored"].values()), diagnostic)
                self.assertTrue(
                    (observed_status, stdout, stderr)
                    == (
                        128 + int(signum),
                        b"",
                        b"proton-pass age admission interrupted\n",
                    ),
                    diagnostic,
                )
                self.assertFalse(adapter_group_survived, diagnostic)
                self.assertFalse(child_group_survived, diagnostic)
                self.assertFalse(private_root_survived, diagnostic)
                self.assertFalse(self.output.exists(), diagnostic)

    def test_normal_child_with_resistant_descendant_is_retired_and_fails(
        self,
    ) -> None:
        descendant_state = self.root / "resistant-descendant.json"
        descendant_source = textwrap.dedent(
            f"""\
            import json
            import os
            import pathlib
            import signal
            import time

            termination_signals = (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
            blocked = signal.pthread_sigmask(signal.SIG_BLOCK, set())
            inherited_ignored = {{
                str(int(signum)): signal.getsignal(signum) == signal.SIG_IGN
                for signum in termination_signals
            }}
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            pathlib.Path({os.fspath(descendant_state)!r}).write_text(
                json.dumps(
                    {{
                        "blocked": sorted(int(signum) for signum in blocked),
                        "inherited_ignored": inherited_ignored,
                        "pgid": os.getpgrp(),
                        "pid": os.getpid(),
                    }},
                    sort_keys=True,
                ),
                encoding="ascii",
            )
            time.sleep(30)
            """
        )
        self.wrapper.write_text(
            textwrap.dedent(
                f"""\
                import pathlib
                import subprocess
                import sys
                import time

                state = pathlib.Path({os.fspath(descendant_state)!r})
                subprocess.Popen(
                    [sys.executable, "-c", {descendant_source!r}],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                deadline = time.monotonic() + 5
                while not state.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                if not state.exists():
                    raise SystemExit(95)
                print("required")
                """
            ),
            encoding="ascii",
        )
        self.wrapper.chmod(0o755)

        result = subprocess.run(
            self._command(),
            check=False,
            capture_output=True,
            env=self._environment(),
            timeout=10,
        )

        state = __import__("json").loads(descendant_state.read_bytes())
        descendant_pid = state["pid"]
        process_group = state["pgid"]
        pid_survived = True
        group_survived = True
        try:
            os.kill(descendant_pid, 0)
        except ProcessLookupError:
            pid_survived = False
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            group_survived = False
        if group_survived:
            os.killpg(process_group, signal.SIGKILL)
        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (1, b"", b"proton-pass age admission failed\n"),
        )
        self.assertEqual(
            set(state["blocked"]).intersection(
                {int(signal.SIGHUP), int(signal.SIGINT), int(signal.SIGTERM)}
            ),
            set(),
        )
        self.assertFalse(any(state["inherited_ignored"].values()))
        self.assertFalse(pid_survived)
        self.assertFalse(group_survived)
        self.assertFalse(self.readiness_marker.exists())
        self.assertFalse(self.provider_marker.exists())
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob("proton-pass-age-admission.*")), [])

    def test_repeated_signals_during_private_cleanup_keep_the_first_status(
        self,
    ) -> None:
        cleanup_started = self.root / "cleanup-started"
        cleanup_release = self.root / "cleanup-release"
        cleanup_count = self.root / "cleanup-count"
        harness = textwrap.dedent(
            f"""\
            import os
            import pathlib
            import runpy
            import shutil
            import sys
            import time

            real_rmtree = shutil.rmtree
            calls = 0

            def paused_rmtree(path, *arguments, **keywords):
                global calls
                calls += 1
                if pathlib.Path(path).name.startswith("proton-pass-age-admission."):
                    pathlib.Path({os.fspath(cleanup_started)!r}).write_text(
                        "started", encoding="ascii"
                    )
                    deadline = time.monotonic() + 5
                    release = pathlib.Path({os.fspath(cleanup_release)!r})
                    while not release.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                return real_rmtree(path, *arguments, **keywords)

            shutil.rmtree = paused_rmtree
            source = sys.argv[1]
            sys.argv = [source, *sys.argv[2:]]
            try:
                runpy.run_path(source, run_name="__main__")
            finally:
                pathlib.Path({os.fspath(cleanup_count)!r}).write_text(
                    str(calls), encoding="ascii"
                )
            """
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-B",
                "-S",
                "-c",
                harness,
                os.fspath(self.adapter),
                *self._command()[1:],
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._environment(),
            start_new_session=True,
        )
        deadline = time.monotonic() + 5
        while not cleanup_started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(cleanup_started.exists(), "private cleanup did not start")

        process.send_signal(signal.SIGTERM)
        time.sleep(0.05)
        process.send_signal(signal.SIGINT)
        process.send_signal(signal.SIGHUP)
        cleanup_release.write_text("release", encoding="ascii")
        stdout, stderr = process.communicate(timeout=10)

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (143, b"", b"proton-pass age admission interrupted\n"),
        )
        self.assertEqual(cleanup_count.read_text(encoding="ascii"), "1")
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob("proton-pass-age-admission.*")), [])

    def test_signal_with_unverified_private_cleanup_reports_failure(self) -> None:
        retained_root_path = self.root / "retained-root.path"
        harness = textwrap.dedent(
            f"""\
            import os
            import pathlib
            import runpy
            import shutil
            import signal
            import sys

            real_rmtree = shutil.rmtree
            triggered = False

            def failing_rmtree(path, *arguments, **keywords):
                global triggered
                if pathlib.Path(path).name.startswith("proton-pass-age-admission."):
                    pathlib.Path({os.fspath(retained_root_path)!r}).write_text(
                        os.fspath(path), encoding="utf-8"
                    )
                    if not triggered:
                        triggered = True
                        os.kill(os.getpid(), signal.SIGTERM)
                    raise OSError("synthetic cleanup uncertainty")
                return real_rmtree(path, *arguments, **keywords)

            shutil.rmtree = failing_rmtree
            source = sys.argv[1]
            sys.argv = [source, *sys.argv[2:]]
            runpy.run_path(source, run_name="__main__")
            """
        )

        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-S",
                "-c",
                harness,
                os.fspath(self.adapter),
                *self._command()[1:],
            ],
            check=False,
            capture_output=True,
            env=self._environment(),
            start_new_session=True,
            timeout=10,
        )

        retained_root = Path(retained_root_path.read_text(encoding="utf-8"))
        retained = retained_root.exists()
        if retained:
            shutil.rmtree(retained_root)
        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (1, b"", b"proton-pass age admission failed\n"),
        )
        self.assertTrue(retained)
        self.assertFalse(self.output.exists())

    def test_nonisolated_python_is_rejected_before_provider_access(self) -> None:
        result = subprocess.run(
            [sys.executable, os.fspath(self.adapter), *self._command()[1:]],
            check=False,
            capture_output=True,
            env=self._environment(),
            timeout=10,
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(
            result.stderr,
            b"proton-pass age admission requires isolated Python\n",
        )
        self.assertFalse(self.provider_marker.exists())
        self.assertFalse(self.wrapper_marker.exists())
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
