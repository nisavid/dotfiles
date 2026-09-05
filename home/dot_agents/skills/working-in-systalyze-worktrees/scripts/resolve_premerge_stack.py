"""Resolve Systalyze's temporary pre-merge stack surfaces fail-closed."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from types import FrameType
from typing import Any, NamedTuple
from urllib.parse import urlparse

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHELL_ASSIGNMENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
PR_IDENTITY_KEYS = ("number", "headRefName", "headRefOid")
PR_QUERY_LIMIT = 1000
COMMAND_TIMEOUT_SECONDS = 60.0
PROCESS_TERMINATION_GRACE_SECONDS = 1.0
TRUSTED_FAILURE_EXECUTABLE = Path("/usr/bin/false")
TRUSTED_OPENSSH_EXECUTABLE = Path("/usr/bin/ssh")
TRUSTED_GIT_EXECUTABLES = (Path("/usr/bin/git"),)
TRUSTED_GITHUB_CLI_EXECUTABLES = (
    Path("/opt/homebrew/bin/gh"),
    Path("/usr/local/bin/gh"),
    Path("/usr/bin/gh"),
)
GITHUB_TOKEN_ENVIRONMENT_VARIABLE = "GH_TOKEN"
DEFAULT_REMOTE_PORTS = {"https": 443, "ssh": 22}
TLS_TRUST_ANCHOR_CONFIG_KEYS = ("http.sslCAInfo", "http.sslCAPath")
GIT_TLS_TRUST_ANCHOR_ENVIRONMENT_VARIABLES = (
    "CURL_CA_BUNDLE",
    "GIT_SSL_CAINFO",
    "GIT_SSL_CAPATH",
)
GITHUB_TLS_TRUST_ANCHOR_ENVIRONMENT_VARIABLES = (
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
)
DYNAMIC_LOADER_OVERRIDE_ENVIRONMENT_VARIABLES = (
    "LD_AUDIT",
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "DYLD_FALLBACK_FRAMEWORK_PATH",
    "DYLD_FALLBACK_LIBRARY_PATH",
    "DYLD_FRAMEWORK_PATH",
    "DYLD_INSERT_LIBRARIES",
    "DYLD_LIBRARY_PATH",
    "DYLD_ROOT_PATH",
    "DYLD_SHARED_CACHE_DIR",
    "DYLD_VERSIONED_FRAMEWORK_PATH",
    "DYLD_VERSIONED_LIBRARY_PATH",
)
OPENSSL_OVERRIDE_ENVIRONMENT_VARIABLES = (
    "OPENSSL_CONF",
    "OPENSSL_CONF_INCLUDE",
    "OPENSSL_ENGINES",
    "OPENSSL_MODULES",
)


class ContractError(Exception):
    def __init__(self, code: str, **evidence: object) -> None:
        super().__init__(code)
        self.code = code
        self.evidence = evidence


class ShellWord(NamedTuple):
    value: str
    raw: str


class VerifiedRemote(NamedTuple):
    url: str
    identity: str


GitConfigSnapshot = tuple[tuple[str, str], ...]
GitHttpsAuthentication = tuple[str, str]
SshDestination = tuple[str, int]
CachedAliases = dict[str, "str | None"]


def sha256_fingerprint(value: bytes) -> str:
    verify_openssl_environment()
    import hashlib

    return "sha256:" + hashlib.sha256(value).hexdigest()


def process_output_hashes(
    result: subprocess.CompletedProcess[bytes],
) -> dict[str, str]:
    return {
        "stdoutSha256": sha256_fingerprint(result.stdout),
        "stderrSha256": sha256_fingerprint(result.stderr),
    }


def complete_cleanup_action(action: Callable[[], Any]) -> Any:
    while True:
        try:
            return action()
        except (KeyboardInterrupt, SystemExit):
            continue


def terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        try:
            complete_cleanup_action(lambda: os.killpg(process.pid, signal.SIGTERM))
        except ProcessLookupError:
            pass
    else:
        try:
            complete_cleanup_action(process.terminate)
        except ProcessLookupError:
            pass
    try:
        complete_cleanup_action(
            lambda: process.communicate(timeout=PROCESS_TERMINATION_GRACE_SECONDS)
        )
    except subprocess.TimeoutExpired:
        pass
    if os.name == "posix":
        try:
            complete_cleanup_action(lambda: os.killpg(process.pid, signal.SIGKILL))
        except ProcessLookupError:
            pass
    else:
        try:
            complete_cleanup_action(process.kill)
        except ProcessLookupError:
            pass
    for pipe in (process.stdout, process.stderr):
        if pipe is not None:
            complete_cleanup_action(pipe.close)
    try:
        complete_cleanup_action(
            lambda: process.wait(timeout=PROCESS_TERMINATION_GRACE_SECONDS)
        )
    except subprocess.TimeoutExpired:
        pass


def terminate_process_group_uninterruptibly(
    process: subprocess.Popen[bytes],
) -> None:
    while True:
        try:
            terminate_process_group(process)
            return
        except (KeyboardInterrupt, SystemExit):
            continue


def propagate_command_signal(signum: int) -> None:
    if signum == signal.SIGINT:
        raise KeyboardInterrupt
    raise SystemExit(128 + signum)


def run_process_bytes(
    arguments: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout_seconds: float,
) -> subprocess.CompletedProcess[bytes]:
    process: subprocess.Popen[bytes] | None = None
    pending_signal: int | None = None
    tearing_down = False
    finalizing = False
    previous_handlers: dict[int, Any] = {}

    def request_termination(signum: int, _frame: FrameType | None) -> None:
        nonlocal pending_signal, tearing_down
        if pending_signal is None:
            pending_signal = signum
        interrupt_command = process is not None and not tearing_down and not finalizing
        if process is not None:
            tearing_down = True
        if interrupt_command:
            propagate_command_signal(signum)

    if os.name == "posix" and threading.current_thread() is threading.main_thread():
        for signum, expected_handler in (
            (signal.SIGTERM, signal.SIG_DFL),
            (signal.SIGINT, signal.default_int_handler),
        ):
            previous_handler = signal.getsignal(signum)
            if previous_handler == expected_handler:
                previous_handlers[signum] = previous_handler
                signal.signal(signum, request_termination)
    try:
        try:
            process = subprocess.Popen(
                arguments,
                cwd=cwd,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=os.name == "posix",
            )
            if pending_signal is not None:
                tearing_down = True
                propagate_command_signal(pending_signal)
            stdout, stderr = process.communicate(timeout=timeout_seconds)
            result = subprocess.CompletedProcess(
                arguments,
                process.returncode,
                stdout,
                stderr,
            )
            finalizing = True
            return result
        except BaseException:
            tearing_down = True
            finalizing = True
            raise
    finally:
        finalizing = True
        try:
            if process is not None:
                terminate_process_group_uninterruptibly(process)
        finally:
            for signum, previous_handler in previous_handlers.items():
                signal.signal(signum, previous_handler)
        if pending_signal is not None:
            propagate_command_signal(pending_signal)


def decode_process_output(
    result: subprocess.CompletedProcess[bytes],
    *,
    failure_code: str,
    command_name: str,
    **evidence: object,
) -> subprocess.CompletedProcess[str]:
    try:
        stdout = result.stdout.decode("utf-8")
        stderr = result.stderr.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ContractError(
            failure_code,
            command=command_name,
            outputEncodingInvalid=True,
            **process_output_hashes(result),
            **evidence,
        ) from error
    return subprocess.CompletedProcess(
        result.args,
        result.returncode,
        stdout,
        stderr,
    )


def apply_git_config_snapshot(
    environment: dict[str, str], snapshot: GitConfigSnapshot
) -> None:
    for variable in tuple(environment):
        if variable in {
            "GIT_CONFIG",
            "GIT_CONFIG_COUNT",
            "GIT_CONFIG_GLOBAL",
            "GIT_CONFIG_NOSYSTEM",
            "GIT_CONFIG_PARAMETERS",
            "GIT_CONFIG_SYSTEM",
        } or re.fullmatch(r"GIT_CONFIG_(?:KEY|VALUE)_\d+", variable):
            environment.pop(variable, None)

    isolated = []
    for key, value in snapshot:
        normalized_key = key.casefold()
        if normalized_key.startswith("credential.") or (
            normalized_key.startswith(("http.", "https."))
            and normalized_key.endswith(".extraheader")
        ):
            continue
        if normalized_key in {
            "core.sshcommand",
            "ssh.variant",
        } or normalized_key.startswith(("http.", "https.", "protocol.")):
            isolated.append((key, value))

    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_COUNT": str(len(isolated)),
        }
    )
    for index, (key, value) in enumerate(isolated):
        environment[f"GIT_CONFIG_KEY_{index}"] = key
        environment[f"GIT_CONFIG_VALUE_{index}"] = value


def apply_git_https_authentication(
    environment: dict[str, str],
    authentication: GitHttpsAuthentication | None,
    *,
    uses_ssh_transport: bool | None,
    isolated_git_config: bool,
) -> None:
    if authentication is None:
        return
    if uses_ssh_transport is not False or not isolated_git_config:
        raise ValueError("Git HTTPS authentication requires isolated HTTPS Git")
    remote_url, token = authentication
    if (
        urlparse(remote_url).scheme != "https"
        or not token
        or any(character.isspace() for character in token)
    ):
        raise ValueError("invalid Git HTTPS authentication")
    for variable in tuple(environment):
        if variable == "GIT_CURL_VERBOSE" or variable.startswith("GIT_TRACE"):
            environment.pop(variable, None)
    count = int(environment.get("GIT_CONFIG_COUNT", "0"))
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
    header_name = "Authorization"
    header_value = f"Basic {encoded}"
    settings = (
        (f"http.{remote_url}.extraHeader", f"{header_name}: {header_value}"),
        (f"http.{remote_url}.followRedirects", "false"),
    )
    environment["GIT_CONFIG_COUNT"] = str(count + len(settings))
    for offset, (key, value) in enumerate(settings, start=count):
        environment[f"GIT_CONFIG_KEY_{offset}"] = key
        environment[f"GIT_CONFIG_VALUE_{offset}"] = value


def remove_dynamic_loader_environment(environment: dict[str, str]) -> None:
    for variable in DYNAMIC_LOADER_OVERRIDE_ENVIRONMENT_VARIABLES:
        environment.pop(variable, None)


def remove_openssl_environment(environment: dict[str, str]) -> None:
    for variable in OPENSSL_OVERRIDE_ENVIRONMENT_VARIABLES:
        environment.pop(variable, None)


def verify_dynamic_loader_environment() -> None:
    configured = sorted(
        variable
        for variable in DYNAMIC_LOADER_OVERRIDE_ENVIRONMENT_VARIABLES
        if variable in os.environ
    )
    if configured:
        raise ContractError(
            "DYNAMIC_LOADER_ENVIRONMENT_UNSUPPORTED",
            settings=configured,
        )


def verify_openssl_environment() -> None:
    configured = sorted(
        variable
        for variable in OPENSSL_OVERRIDE_ENVIRONMENT_VARIABLES
        if variable in os.environ
    )
    if configured:
        raise ContractError(
            "OPENSSL_ENVIRONMENT_UNSUPPORTED",
            settings=configured,
        )


def trusted_top_level_executable(
    command_name: str,
    *,
    failure_code: str,
) -> Path:
    if command_name == "git":
        candidates = TRUSTED_GIT_EXECUTABLES
    elif command_name == "gh":
        candidates = TRUSTED_GITHUB_CLI_EXECUTABLES
    else:
        raise ValueError(f"unsupported trusted executable: {command_name}")

    for configured in candidates:
        if not configured.is_absolute():
            continue
        try:
            executable = configured.resolve(strict=True)
        except OSError:
            continue
        if executable.is_file() and os.access(executable, os.X_OK):
            return executable
    raise ContractError(
        failure_code,
        command=command_name,
        executableUnavailable=True,
    )


def pin_top_level_executable(
    arguments: list[str],
    *,
    failure_code: str,
) -> tuple[list[str], str]:
    command_name = Path(arguments[0]).name
    if arguments[0] not in {"git", "gh"}:
        return arguments, command_name
    executable = trusted_top_level_executable(
        arguments[0],
        failure_code=failure_code,
    )
    return [str(executable), *arguments[1:]], command_name


def configured_ssh_command(
    cwd: Path,
    environment: dict[str, str],
    *,
    failure_code: str,
    timeout_seconds: float,
) -> str:
    if "GIT_SSH_COMMAND" in environment:
        return environment["GIT_SSH_COMMAND"]
    git_executable = trusted_top_level_executable(
        "git",
        failure_code=failure_code,
    )
    try:
        raw_result = run_process_bytes(
            [str(git_executable), "config", "--get", "core.sshCommand"],
            cwd=cwd,
            environment=environment,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise ContractError(
            failure_code,
            command="git",
            sshCommandQueryTimedOut=True,
            timeoutSeconds=timeout_seconds,
        ) from error
    except OSError as error:
        raise ContractError(
            failure_code,
            command="git",
            sshCommandQueryFailed=True,
            osError=type(error).__name__,
        ) from error
    if raw_result.returncode == 1:
        return "ssh"
    if raw_result.returncode != 0:
        raise ContractError(
            failure_code,
            command="git",
            sshCommandQueryFailed=True,
            returnCode=raw_result.returncode,
            **process_output_hashes(raw_result),
        )
    result = decode_process_output(
        raw_result,
        failure_code=failure_code,
        command_name="git",
        sshCommandQueryFailed=True,
    )
    return result.stdout.rstrip("\n")


def literal_program_name(
    shell_word: ShellWord,
    *,
    failure_code: str,
    command_name: str,
) -> str:
    """Return a basename only when the shell word needs no runtime expansion."""
    validate_literal_shell_word(
        shell_word,
        failure_code=failure_code,
        command_name=command_name,
    )
    return Path(shell_word.value).name.casefold()


def validate_literal_shell_word(
    shell_word: ShellWord,
    *,
    failure_code: str,
    command_name: str,
    leading_assignment: bool = False,
) -> None:
    """Reject shell words whose value would change when the command executes."""
    quote: str | None = None
    escaped = False
    assignment_value_start = (
        shell_word.raw.index("=") + 1 if leading_assignment else None
    )
    for index, character in enumerate(shell_word.raw):
        if escaped:
            escaped = False
            continue
        if quote == "'":
            if character == "'":
                quote = None
            continue
        if character == "\\":
            escaped = True
            continue
        if quote == '"':
            if character == '"':
                quote = None
            elif character in {"$", "`"}:
                raise ContractError(
                    failure_code,
                    command=command_name,
                    sshCommandUnsupported=True,
                )
            continue
        if character in {"'", '"'}:
            quote = character
        elif (
            character in {"$", "`", "*", "?", "["}
            or (character in {"{", "}"} and not leading_assignment)
            or (character == "#" and index == 0)
            or (
                character == "~"
                and (
                    index == 0
                    or (
                        assignment_value_start is not None
                        and (
                            index == assignment_value_start
                            or (
                                index > assignment_value_start
                                and shell_word.raw[index - 1] == ":"
                            )
                        )
                    )
                )
            )
        ):
            raise ContractError(
                failure_code,
                command=command_name,
                sshCommandUnsupported=True,
            )


def trusted_openssh_executable(
    shell_word: ShellWord,
    *,
    failure_code: str,
    command_name: str,
) -> Path:
    if literal_program_name(
        shell_word,
        failure_code=failure_code,
        command_name=command_name,
    ) not in {"ssh", "ssh.exe"}:
        raise ContractError(
            failure_code,
            command=command_name,
            sshCommandUnsupported=True,
        )
    try:
        trusted = TRUSTED_OPENSSH_EXECUTABLE.resolve(strict=True)
    except OSError as error:
        raise ContractError(
            failure_code,
            command=command_name,
            sshExecutableUnavailable=True,
        ) from error
    if not trusted.is_file() or not os.access(trusted, os.X_OK):
        raise ContractError(
            failure_code,
            command=command_name,
            sshExecutableUnavailable=True,
        )

    if shell_word.value.casefold() in {"ssh", "ssh.exe"}:
        return trusted
    candidate = Path(shell_word.value)
    if not candidate.is_absolute():
        raise ContractError(
            failure_code,
            command=command_name,
            sshExecutableUntrusted=True,
        )
    try:
        candidate = candidate.resolve(strict=True)
    except OSError as error:
        raise ContractError(
            failure_code,
            command=command_name,
            sshExecutableUntrusted=True,
        ) from error
    if candidate != trusted:
        raise ContractError(
            failure_code,
            command=command_name,
            sshExecutableUntrusted=True,
        )
    return trusted


def ssh_program_index(
    shell_words: list[ShellWord],
    *,
    failure_code: str,
    command_name: str,
) -> int:
    """Locate SSH after shell assignments and an optional env wrapper."""
    program_index = 0
    # Shell assignment recognition happens before quote removal, while env sees
    # quote-removed argv. Preserve that grammar distinction deliberately.
    while program_index < len(shell_words) and SHELL_ASSIGNMENT_PATTERN.fullmatch(
        shell_words[program_index].raw
    ):
        program_index += 1

    if program_index < len(shell_words) and literal_program_name(
        shell_words[program_index],
        failure_code=failure_code,
        command_name=command_name,
    ) in {"env", "env.exe"}:
        program_index += 1
        while program_index < len(shell_words):
            word = shell_words[program_index].value
            if word == "--":
                program_index += 1
                break
            if SHELL_ASSIGNMENT_PATTERN.fullmatch(word) or word in {
                "-i",
                "--ignore-environment",
            }:
                program_index += 1
                continue
            if word in {"-u", "--unset", "-C", "--chdir"}:
                program_index += 2
                if program_index > len(shell_words):
                    raise ContractError(
                        failure_code,
                        command=command_name,
                        sshCommandInvalid=True,
                    )
                continue
            if (word.startswith(("-u", "-C")) and len(word) > 2) or word.startswith(
                ("--unset=", "--chdir=")
            ):
                program_index += 1
                continue
            if word.startswith("-"):
                raise ContractError(
                    failure_code,
                    command=command_name,
                    sshCommandUnsupported=True,
                )
            break

    if program_index >= len(shell_words):
        raise ContractError(
            failure_code,
            command=command_name,
            sshCommandInvalid=True,
        )
    return program_index


def parse_ssh_shell_words(
    ssh_command: str,
    *,
    failure_code: str,
    command_name: str,
) -> list[ShellWord]:
    if not ssh_command.strip():
        raise ContractError(
            failure_code,
            command=command_name,
            sshCommandInvalid=True,
        )
    if "\n" in ssh_command or "\r" in ssh_command:
        raise ContractError(
            failure_code,
            command=command_name,
            sshCommandUnsupported=True,
        )
    try:
        lexer = shlex.shlex(ssh_command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        shell_words: list[ShellWord] = []
        raw_cursor = 0
        while (word := lexer.get_token()) is not None:
            # tell() may include a punctuation delimiter held in shlex's
            # character pushback. Such tokens make the command unsupported
            # below; retain their exact raw spelling for validation.
            raw_end = lexer.instream.tell()
            while raw_end > 0 and ssh_command[raw_end - 1].isspace():
                raw_end -= 1
            raw_start = raw_cursor
            while raw_start < raw_end and ssh_command[raw_start].isspace():
                raw_start += 1
            shell_words.append(ShellWord(word, ssh_command[raw_start:raw_end]))
            raw_cursor = raw_end
    except ValueError as error:
        raise ContractError(
            failure_code,
            command=command_name,
            sshCommandInvalid=True,
        ) from error

    if not shell_words or any(
        re.fullmatch(r"[();<>|&]+", word.value) for word in shell_words
    ):
        raise ContractError(
            failure_code,
            command=command_name,
            sshCommandUnsupported=True,
        )
    return shell_words


def plink_injected_arguments(
    configured_arguments: list[str],
    port: int,
    *,
    failure_code: str,
    command_name: str,
) -> list[str]:
    index = 0
    while index < len(configured_arguments):
        argument = configured_arguments[index]
        if argument == "-batch":
            index += 1
            continue
        if argument == "-P" and index + 1 < len(configured_arguments):
            if configured_arguments[index + 1] == str(port):
                index += 2
                continue
        elif argument == f"-P{port}":
            index += 1
            continue
        raise ContractError(
            failure_code,
            command=command_name,
            sshCommandUnsupported=True,
        )
    return ["-batch", "-P", str(port)]


def ssh_injected_arguments(
    program: str,
    configured_arguments: list[str],
    ssh_destination: SshDestination | None,
    *,
    failure_code: str,
    command_name: str,
) -> list[str]:
    if program in {"ssh", "ssh.exe"}:
        arguments = ["-o", "BatchMode=yes"]
        if ssh_destination is not None:
            host, port = ssh_destination
            host_key_alias = (
                host if port == DEFAULT_REMOTE_PORTS["ssh"] else f"[{host}]:{port}"
            )
            arguments.extend(
                [
                    "-F",
                    os.devnull,
                    "-o",
                    "StrictHostKeyChecking=yes",
                    "-o",
                    "ProxyCommand=none",
                    "-o",
                    "ProxyJump=none",
                    "-o",
                    f"HostName={host}",
                    "-o",
                    f"HostKeyAlias={host_key_alias}",
                    "-o",
                    f"Port={port}",
                ]
            )
        return arguments
    if program in {"plink", "plink.exe", "tortoiseplink", "tortoiseplink.exe"}:
        if ssh_destination is None:
            return ["-batch"]
        return plink_injected_arguments(
            configured_arguments,
            ssh_destination[1],
            failure_code=failure_code,
            command_name=command_name,
        )
    raise ContractError(
        failure_code,
        command=command_name,
        sshCommandUnsupported=True,
    )


def noninteractive_ssh_command(
    ssh_command: str,
    *,
    failure_code: str,
    command_name: str,
    ssh_destination: SshDestination | None = None,
) -> str:
    shell_words = parse_ssh_shell_words(
        ssh_command,
        failure_code=failure_code,
        command_name=command_name,
    )
    leading_assignment_count = 0
    while leading_assignment_count < len(shell_words) and (
        SHELL_ASSIGNMENT_PATTERN.fullmatch(shell_words[leading_assignment_count].raw)
    ):
        leading_assignment_count += 1
    for index, shell_word in enumerate(shell_words):
        validate_literal_shell_word(
            shell_word,
            failure_code=failure_code,
            command_name=command_name,
            leading_assignment=index < leading_assignment_count,
        )

    program_index = ssh_program_index(
        shell_words,
        failure_code=failure_code,
        command_name=command_name,
    )
    program = literal_program_name(
        shell_words[program_index],
        failure_code=failure_code,
        command_name=command_name,
    )
    configured_arguments = [word.value for word in shell_words[program_index + 1 :]]
    trusted_program: Path | None = None
    if ssh_destination is not None:
        if program_index != 0:
            raise ContractError(
                failure_code,
                command=command_name,
                sshCommandUnsupported=True,
            )
        trusted_program = trusted_openssh_executable(
            shell_words[program_index],
            failure_code=failure_code,
            command_name=command_name,
        )
        program = "ssh"
        if configured_arguments:
            raise ContractError(
                failure_code,
                command=command_name,
                sshCommandUnsupported=True,
            )
    injected_arguments = ssh_injected_arguments(
        program,
        configured_arguments,
        ssh_destination,
        failure_code=failure_code,
        command_name=command_name,
    )
    hardened_words = [word.value for word in shell_words]
    if trusted_program is not None:
        hardened_words[program_index] = str(trusted_program)
    hardened_words[program_index + 1 : program_index + 1] = injected_arguments
    if ssh_destination is not None:
        hardened_words.extend(("-S", "none"))
    hardened_fragments = []
    for index, word in enumerate(hardened_words):
        if index < leading_assignment_count:
            name, value = word.split("=", maxsplit=1)
            hardened_fragments.append(f"{name}={shlex.quote(value)}")
        else:
            hardened_fragments.append(shlex.quote(word))
    return " ".join(hardened_fragments)


def pin_git_ssh_variant(
    environment: dict[str, str],
    ssh_destination: SshDestination | None,
) -> None:
    if ssh_destination is not None:
        environment["GIT_SSH_VARIANT"] = "ssh"


def run(
    arguments: list[str],
    *,
    cwd: Path,
    failure_code: str,
    allowed_returncodes: tuple[int, ...] = (0,),
    timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
    github_host: str | None = None,
    github_config_dir: Path | None = None,
    github_authentication: str = "",
    uses_ssh_transport: bool | None = None,
    ssh_destination: SshDestination | None = None,
    git_config_snapshot: GitConfigSnapshot | None = None,
    git_https_authentication: GitHttpsAuthentication | None = None,
    object_directory: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    arguments, command_name = pin_top_level_executable(
        arguments,
        failure_code=failure_code,
    )
    environment = os.environ.copy()
    remove_dynamic_loader_environment(environment)
    remove_openssl_environment(environment)
    for variable in (
        "GIT_DIR",
        "GIT_EXEC_PATH",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_SHALLOW_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_SSL_NO_VERIFY",
        "GIT_TEMPLATE_DIR",
        "SSLKEYLOGFILE",
        "SSH_SK_HELPER",
        "SSH_SK_PROVIDER",
    ):
        environment.pop(variable, None)
    environment.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": str(TRUSTED_FAILURE_EXECUTABLE),
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GCM_INTERACTIVE": "never",
            "GH_PROMPT_DISABLED": "1",
            "SSH_ASKPASS": str(TRUSTED_FAILURE_EXECUTABLE),
            "SSH_ASKPASS_REQUIRE": "never",
        }
    )
    if github_host is not None:
        environment["GH_HOST"] = github_host
    if github_config_dir is not None:
        environment["GH_CONFIG_DIR"] = str(github_config_dir)
    if github_authentication:
        for variable in (
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "GH_ENTERPRISE_TOKEN",
            "GITHUB_ENTERPRISE_TOKEN",
        ):
            environment.pop(variable, None)
        environment[GITHUB_TOKEN_ENVIRONMENT_VARIABLE] = github_authentication
    if object_directory is not None:
        environment["GIT_OBJECT_DIRECTORY"] = str(object_directory)
    if git_config_snapshot is not None:
        apply_git_config_snapshot(environment, git_config_snapshot)
    apply_git_https_authentication(
        environment,
        git_https_authentication,
        uses_ssh_transport=uses_ssh_transport,
        isolated_git_config=git_config_snapshot is not None,
    )
    if uses_ssh_transport is True:
        pin_git_ssh_variant(environment, ssh_destination)
        ssh_command = configured_ssh_command(
            cwd,
            environment,
            failure_code=failure_code,
            timeout_seconds=timeout_seconds,
        )
        environment["GIT_SSH_COMMAND"] = noninteractive_ssh_command(
            ssh_command,
            failure_code=failure_code,
            command_name=command_name,
            ssh_destination=ssh_destination,
        )
    elif uses_ssh_transport is False:
        # A verified non-SSH URL may still be subject to a later Git URL rewrite.
        # Block that transport transition without interpreting the user's wrapper.
        environment["GIT_SSH_COMMAND"] = str(TRUSTED_FAILURE_EXECUTABLE)
    try:
        raw_result = run_process_bytes(
            arguments,
            cwd=cwd,
            environment=environment,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise ContractError(
            failure_code,
            command=command_name,
            timeoutSeconds=timeout_seconds,
        ) from error
    except OSError as error:
        raise ContractError(
            failure_code,
            command=command_name,
            osError=type(error).__name__,
        ) from error
    if raw_result.returncode not in allowed_returncodes:
        # Process output may contain credential-helper or remote details. Keep
        # diagnostic correlation without copying those bytes into task evidence.
        raise ContractError(
            failure_code,
            returnCode=raw_result.returncode,
            **process_output_hashes(raw_result),
        )
    return decode_process_output(
        raw_result,
        failure_code=failure_code,
        command_name=command_name,
    )


def git(
    repo: Path,
    *arguments: str,
    failure_code: str = "GIT_COMMAND_FAILED",
    allowed_returncodes: tuple[int, ...] = (0,),
    uses_ssh_transport: bool | None = None,
    ssh_destination: SshDestination | None = None,
    git_config_snapshot: GitConfigSnapshot | None = None,
    git_https_authentication: GitHttpsAuthentication | None = None,
    object_directory: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return run(
        ["git", *arguments],
        cwd=repo,
        failure_code=failure_code,
        allowed_returncodes=allowed_returncodes,
        uses_ssh_transport=uses_ssh_transport,
        ssh_destination=ssh_destination,
        git_config_snapshot=git_config_snapshot,
        git_https_authentication=git_https_authentication,
        object_directory=object_directory,
    )


def normalize_remote_url(value: str) -> str | None:
    try:
        remote_url = value.strip()
        scp_match = re.fullmatch(
            r"(?:(?P<user>[A-Za-z0-9._-]+)@)?"
            r"(?P<host>[^/:]+):(?P<path>.+)",
            remote_url,
        )
        if scp_match and "://" not in remote_url:
            user = scp_match.group("user")
            host = scp_match.group("host")
            path = scp_match.group("path")
            if "[" in host or "]" in host or "?" in path or "#" in path:
                return None
            authority = f"{user.casefold()}@" if user is not None else ""
            authority += host.lower()
            return f"ssh://{authority}/{path.strip('/').removesuffix('.git').lower()}"

        parsed = urlparse(remote_url)
        if parsed.params or parsed.query or parsed.fragment:
            return None
        if parsed.scheme in {"https", "ssh"}:
            hostname = parsed.hostname
            port = parsed.port
            if hostname is None:
                return None
            if port is not None and port < 1:
                return None
            if parsed.password is not None or (
                parsed.scheme == "https" and parsed.username is not None
            ):
                return None
            username = parsed.username
            if username is not None and not re.fullmatch(r"[A-Za-z0-9._-]+", username):
                return None
            authority = (
                f"{username.casefold()}@"
                if parsed.scheme == "ssh" and username is not None
                else ""
            )
            authority += hostname.lower()
            if port is not None and port != DEFAULT_REMOTE_PORTS[parsed.scheme]:
                authority += f":{port}"
            return (
                f"{parsed.scheme}://{authority}/"
                f"{parsed.path.strip('/').removesuffix('.git').lower()}"
            )
        if parsed.scheme == "file":
            return str(Path(parsed.path).resolve())
        if remote_url.startswith("/"):
            return str(Path(remote_url).resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    return None


def validate_surfaces(surfaces: object) -> set[str]:
    if not isinstance(surfaces, list) or len(surfaces) != 2:
        raise ContractError("MANIFEST_INVALID")

    names: set[str] = set()
    roles: set[str] = set()
    refs: set[str] = set()
    for surface in surfaces:
        if not isinstance(surface, dict) or set(surface) != {"name", "role", "ref"}:
            raise ContractError("MANIFEST_INVALID")
        name = surface["name"]
        role = surface["role"]
        ref = surface["ref"]
        if not all(isinstance(value, str) and value for value in (name, role, ref)):
            raise ContractError("MANIFEST_INVALID")
        if not ref.startswith("refs/heads/") or any(
            character.isspace() for character in ref
        ):
            raise ContractError("MANIFEST_INVALID")
        if name in names or role in roles or ref in refs:
            raise ContractError("MANIFEST_INVALID")
        names.add(name)
        roles.add(role)
        refs.add(ref)

    if roles != {"product-base", "qa-overlay"}:
        raise ContractError("MANIFEST_INVALID")
    return names


def validate_relationships(relationships: object, names: set[str]) -> None:
    if not isinstance(relationships, list) or len(relationships) != 1:
        raise ContractError("MANIFEST_INVALID")
    for relationship in relationships:
        if not isinstance(relationship, dict) or set(relationship) != {
            "left",
            "right",
            "require",
        }:
            raise ContractError("MANIFEST_INVALID")
        if not all(
            isinstance(relationship[key], str) and relationship[key]
            for key in ("left", "right", "require")
        ):
            raise ContractError("MANIFEST_INVALID")
        if (
            relationship["left"] not in names
            or relationship["right"] not in names
            or relationship["left"] == relationship["right"]
            or relationship["require"] != "common-ancestor"
        ):
            raise ContractError("MANIFEST_INVALID")


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError("MANIFEST_INVALID") from error

    required = {
        "schemaVersion",
        "repository",
        "remoteUrls",
        "surfaces",
        "relationships",
    }
    if not isinstance(document, dict) or set(document) != required:
        raise ContractError("MANIFEST_INVALID")
    if document["schemaVersion"] != 1 or not isinstance(document["repository"], str):
        raise ContractError("MANIFEST_INVALID")
    repository_parts = document["repository"].split("/")
    if (
        len(repository_parts) != 3
        or not all(repository_parts)
        or any(character.isspace() for character in document["repository"])
    ):
        raise ContractError("MANIFEST_INVALID")
    if not isinstance(document["remoteUrls"], list) or not document["remoteUrls"]:
        raise ContractError("MANIFEST_INVALID")
    if not all(isinstance(value, str) and value for value in document["remoteUrls"]):
        raise ContractError("MANIFEST_INVALID")
    if any(normalize_remote_url(value) is None for value in document["remoteUrls"]):
        raise ContractError("MANIFEST_INVALID")

    names = validate_surfaces(document["surfaces"])
    validate_relationships(document["relationships"], names)

    return document


def read_git_config_snapshot(repo: Path) -> GitConfigSnapshot:
    result = git(
        repo,
        "config",
        "--null",
        "--list",
        failure_code="REPOSITORY_CONFIG_INVALID",
        git_config_snapshot=(),
    )
    entries = []
    for record in result.stdout.split("\0"):
        if not record:
            continue
        key, separator, value = record.partition("\n")
        if not key:
            raise ContractError("REPOSITORY_CONFIG_INVALID")
        if not separator:
            value = "true"
        entries.append((key, value))
    return tuple(entries)


def resolve_git_path(repo: Path, name: str) -> Path:
    result = git(
        repo,
        "rev-parse",
        "--git-path",
        name,
        failure_code="REPOSITORY_STATE_INVALID",
    )
    path = Path(result.stdout.strip())
    return path if path.is_absolute() else (repo / path).resolve()


def config_value_is_true(value: str) -> bool:
    normalized = value.strip().casefold()
    return normalized not in {"", "false", "no", "off", "0"}


def config_subsection_key_matches(
    key: str,
    *,
    section: str,
    subsection: str,
    variable: str,
) -> bool:
    configured_section, section_separator, remainder = key.partition(".")
    configured_subsection, variable_separator, configured_variable = (
        remainder.rpartition(".")
    )
    return (
        bool(section_separator)
        and bool(variable_separator)
        and configured_section.casefold() == section.casefold()
        and configured_subsection == subsection
        and configured_variable.casefold() == variable.casefold()
    )


def urlmatched_git_boolean(
    remote_url: str,
    setting: str,
    config_snapshot: GitConfigSnapshot,
) -> bool | None:
    with tempfile.TemporaryDirectory(
        prefix="resolve-premerge-stack-config-"
    ) as directory:
        configured = git(
            Path(directory),
            "config",
            "--bool",
            "--get-urlmatch",
            setting,
            remote_url,
            failure_code="REPOSITORY_CONFIG_INVALID",
            allowed_returncodes=(0, 1),
            git_config_snapshot=config_snapshot,
        )
    if configured.returncode == 1:
        return None
    value = configured.stdout.strip()
    if value == "true":
        return True
    if value == "false":
        return False
    raise ContractError("REPOSITORY_CONFIG_INVALID")


def verify_https_transport_security(
    remote_url: str,
    config_snapshot: GitConfigSnapshot,
) -> None:
    for variable in GITHUB_TLS_TRUST_ANCHOR_ENVIRONMENT_VARIABLES:
        if variable in os.environ:
            raise ContractError(
                "TLS_TRUST_ANCHOR_OVERRIDE_UNSUPPORTED",
                source="environment",
                setting=variable,
            )
    if urlparse(remote_url).scheme != "https":
        return
    if urlmatched_git_boolean(remote_url, "http.sslVerify", config_snapshot) is False:
        raise ContractError(
            "TLS_VERIFICATION_DISABLED",
            source="gitConfig",
        )
    if urlmatched_git_boolean(remote_url, "http.saveCookies", config_snapshot) is True:
        raise ContractError(
            "HTTP_COOKIE_PERSISTENCE_UNSUPPORTED",
            source="gitConfig",
        )
    with tempfile.TemporaryDirectory(
        prefix="resolve-premerge-stack-config-"
    ) as directory:
        for setting in TLS_TRUST_ANCHOR_CONFIG_KEYS:
            configured = git(
                Path(directory),
                "config",
                "--get-urlmatch",
                setting,
                remote_url,
                failure_code="REPOSITORY_CONFIG_INVALID",
                allowed_returncodes=(0, 1),
                git_config_snapshot=config_snapshot,
            )
            if configured.returncode == 0:
                raise ContractError(
                    "TLS_TRUST_ANCHOR_OVERRIDE_UNSUPPORTED",
                    source="gitConfig",
                    setting=setting,
                )
    if "GIT_SSL_NO_VERIFY" in os.environ and config_value_is_true(
        os.environ["GIT_SSL_NO_VERIFY"]
    ):
        raise ContractError(
            "TLS_VERIFICATION_DISABLED",
            source="environment",
        )
    for variable in GIT_TLS_TRUST_ANCHOR_ENVIRONMENT_VARIABLES:
        if variable in os.environ:
            raise ContractError(
                "TLS_TRUST_ANCHOR_OVERRIDE_UNSUPPORTED",
                source="environment",
                setting=variable,
            )


def verify_repository_state(
    repo: Path,
    remote: str,
    config_snapshot: GitConfigSnapshot,
) -> None:
    if os.path.lexists(resolve_git_path(repo, "info/grafts")):
        raise ContractError("REPOSITORY_GRAFTS_UNSUPPORTED")

    shallow = git(
        repo,
        "rev-parse",
        "--is-shallow-repository",
        failure_code="REPOSITORY_STATE_INVALID",
    ).stdout.strip()
    if shallow == "true":
        raise ContractError("SHALLOW_REPOSITORY_UNSUPPORTED")
    if shallow != "false":
        raise ContractError("REPOSITORY_STATE_INVALID")

    for key, value in config_snapshot:
        normalized_key = key.casefold()
        if normalized_key == "extensions.partialclone" and value:
            raise ContractError("PROMISOR_REPOSITORY_UNSUPPORTED")
        if (
            normalized_key.startswith("remote.")
            and normalized_key.endswith(".promisor")
            and config_value_is_true(value)
        ):
            raise ContractError("PROMISOR_REPOSITORY_UNSUPPORTED")

    fetch_refspecs = [
        value
        for key, value in config_snapshot
        if config_subsection_key_matches(
            key,
            section="remote",
            subsection=remote,
            variable="fetch",
        )
    ]
    expected_refspec = f"refs/heads/*:refs/remotes/{remote}/*"
    if not fetch_refspecs or any(
        value.removeprefix("+") != expected_refspec for value in fetch_refspecs
    ):
        raise ContractError("REMOTE_FETCH_REFSPEC_UNSUPPORTED")


def ssh_destination_for_identity(identity: str) -> SshDestination | None:
    parsed = urlparse(identity)
    if parsed.scheme != "ssh":
        return None
    if parsed.hostname is None:
        raise ContractError("REMOTE_IDENTITY_MISMATCH")
    port = parsed.port
    return parsed.hostname, DEFAULT_REMOTE_PORTS["ssh"] if port is None else port


def verify_repository_identity(repository: str, remote_identity: str) -> str:
    host, owner, name = repository.split("/")
    try:
        parsed = urlparse(remote_identity)
        remote_host = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ContractError("REMOTE_IDENTITY_MISMATCH") from error
    if parsed.scheme not in {"https", "ssh"}:
        # Local paths are accepted only by packaged test fixtures. Production
        # manifests bind their repository to a network remote identity.
        return host
    if remote_host is None:
        raise ContractError("REMOTE_IDENTITY_MISMATCH")
    if port is not None:
        remote_host += f":{port}"
    remote_path = parsed.path.strip("/").removesuffix(".git")
    if (
        remote_host.casefold() != host.casefold()
        or remote_path.casefold() != f"{owner}/{name}".casefold()
    ):
        raise ContractError("REMOTE_IDENTITY_MISMATCH")
    return remote_host.casefold()


def verify_remote(
    remote: str,
    manifest: dict[str, Any],
    config_snapshot: GitConfigSnapshot,
) -> VerifiedRemote:
    remote_urls = [
        value
        for key, value in config_snapshot
        if config_subsection_key_matches(
            key,
            section="remote",
            subsection=remote,
            variable="url",
        )
    ]
    if not remote_urls:
        raise ContractError("REMOTE_NOT_FOUND")
    identities = [normalize_remote_url(remote_url) for remote_url in remote_urls]
    expected = {
        identity
        for value in manifest["remoteUrls"]
        if (identity := normalize_remote_url(value)) is not None
    }
    if not identities or any(
        identity is None or identity not in expected for identity in identities
    ):
        raise ContractError("REMOTE_IDENTITY_MISMATCH")
    remote_identity = identities[0]
    assert remote_identity is not None
    return VerifiedRemote(remote_urls[0], remote_identity)


def query_aliases(
    transport_repo: Path,
    remote_url: str,
    surfaces: list[dict[str, str]],
    *,
    initial: bool,
    uses_ssh_transport: bool,
    ssh_destination: SshDestination | None,
    git_config_snapshot: GitConfigSnapshot,
    git_https_authentication: GitHttpsAuthentication | None = None,
) -> dict[str, str]:
    result = git(
        transport_repo,
        "ls-remote",
        "--refs",
        remote_url,
        *(surface["ref"] for surface in surfaces),
        failure_code="ALIAS_QUERY_FAILED",
        uses_ssh_transport=uses_ssh_transport,
        ssh_destination=ssh_destination,
        git_config_snapshot=git_config_snapshot,
        git_https_authentication=git_https_authentication,
    )
    observed: dict[str, list[str]] = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2:
            observed.setdefault(fields[1], []).append(fields[0])

    resolved: dict[str, str] = {}
    for surface in surfaces:
        matches = observed.get(surface["ref"], [])
        if len(matches) != 1 or not SHA_PATTERN.fullmatch(matches[0]):
            code = (
                "ALIAS_MISSING"
                if initial and not matches
                else "ALIAS_CHANGED_DURING_RESOLUTION"
            )
            raise ContractError(
                code,
                surface=surface["name"],
                ref=surface["ref"],
                observedRefs={
                    requested["ref"]: observed.get(requested["ref"], [])
                    for requested in surfaces
                },
            )
        resolved[surface["name"]] = matches[0]
    return resolved


def fetch_immutable_objects(
    transport_repo: Path,
    object_directory: Path,
    remote_url: str,
    aliases: dict[str, str],
    *,
    negotiation_tips: tuple[str, ...],
    uses_ssh_transport: bool,
    ssh_destination: SshDestination | None,
    git_config_snapshot: GitConfigSnapshot,
    git_https_authentication: GitHttpsAuthentication | None = None,
) -> None:
    git(
        transport_repo,
        "fetch",
        # Git 2.29 spelling; newer Git treats this as --no-auto-maintenance.
        "--no-auto-gc",
        "--no-tags",
        "--no-write-fetch-head",
        "--recurse-submodules=no",
        *(f"--negotiation-tip={oid}" for oid in negotiation_tips),
        remote_url,
        *dict.fromkeys(aliases.values()),
        failure_code="ALIAS_OBJECT_FETCH_FAILED",
        uses_ssh_transport=uses_ssh_transport,
        ssh_destination=ssh_destination,
        git_config_snapshot=git_config_snapshot,
        git_https_authentication=git_https_authentication,
        object_directory=object_directory,
    )
    for oid in aliases.values():
        git(
            transport_repo,
            "cat-file",
            "-e",
            f"{oid}^{{commit}}",
            failure_code="ALIAS_NOT_COMMIT",
            object_directory=object_directory,
        )


def is_ancestor(
    graph_repo: Path,
    object_directory: Path,
    ancestor: str,
    descendant: str,
) -> bool:
    result = git(
        graph_repo,
        "merge-base",
        "--is-ancestor",
        ancestor,
        descendant,
        failure_code="ANCESTRY_CHECK_FAILED",
        allowed_returncodes=(0, 1),
        object_directory=object_directory,
    )
    return result.returncode == 0


def find_merge_base(
    graph_repo: Path,
    object_directory: Path,
    left: str,
    right: str,
) -> str:
    result = git(
        graph_repo,
        "merge-base",
        left,
        right,
        failure_code="RELATIONSHIP_CHECK_FAILED",
        allowed_returncodes=(0, 1),
        object_directory=object_directory,
    )
    merge_base_oid = result.stdout.strip()
    if result.returncode != 0 or not SHA_PATTERN.fullmatch(merge_base_oid):
        raise ContractError("RELATIONSHIP_MISMATCH", leftOid=left, rightOid=right)
    return merge_base_oid


def read_cached_aliases(
    repo: Path,
    remote: str,
    surfaces: list[dict[str, str]],
) -> CachedAliases:
    cached_aliases: CachedAliases = {}
    for surface in surfaces:
        branch = surface["ref"].removeprefix("refs/heads/")
        cached_ref = f"refs/remotes/{remote}/{branch}"
        referenced = git(
            repo,
            "rev-parse",
            "--verify",
            "--quiet",
            cached_ref,
            allowed_returncodes=(0, 1),
        )
        if referenced.returncode == 1:
            cached_aliases[surface["name"]] = None
            continue
        referenced_oid = referenced.stdout.strip()
        if not SHA_PATTERN.fullmatch(referenced_oid):
            raise ContractError(
                "CACHED_ALIAS_OBJECT_UNAVAILABLE",
                surface=surface["name"],
                ref=cached_ref,
            )
        cached = git(
            repo,
            "rev-parse",
            "--verify",
            "--quiet",
            f"{cached_ref}^{{commit}}",
            allowed_returncodes=(0, 1),
        )
        cached_oid = cached.stdout.strip()
        if (
            cached.returncode == 1
            or not SHA_PATTERN.fullmatch(cached_oid)
            or cached_oid != referenced_oid
        ):
            raise ContractError(
                "CACHED_ALIAS_OBJECT_UNAVAILABLE",
                surface=surface["name"],
                ref=cached_ref,
                observedOid=referenced_oid,
            )
        cached_aliases[surface["name"]] = cached_oid
    return cached_aliases


def collect_public_negotiation_tips(
    graph_repo: Path,
    object_directory: Path,
    bindings: dict[str, dict[str, Any]],
) -> tuple[str, ...]:
    candidates = dict.fromkeys(
        oid
        for binding in bindings.values()
        for key in ("headRefOid", "baseRefOid")
        if isinstance((oid := binding.get(key)), str) and SHA_PATTERN.fullmatch(oid)
    )
    available = []
    for oid in candidates:
        present = git(
            graph_repo,
            "cat-file",
            "-e",
            f"{oid}^{{commit}}",
            failure_code="NEGOTIATION_TIP_CHECK_FAILED",
            allowed_returncodes=(0, 1, 128),
            object_directory=object_directory,
        )
        if present.returncode == 0:
            available.append(oid)
    return tuple(available)


def verify_cached_aliases(
    graph_repo: Path,
    object_directory: Path,
    cached_aliases: CachedAliases,
    aliases: dict[str, str],
) -> None:
    for surface, previous_oid in cached_aliases.items():
        if previous_oid is None:
            continue
        current_oid = aliases[surface]
        if previous_oid != current_oid and not is_ancestor(
            graph_repo,
            object_directory,
            previous_oid,
            current_oid,
        ):
            raise ContractError(
                "UNEXPECTED_ALIAS_REWRITE",
                surface=surface,
                previousOid=previous_oid,
                currentOid=current_oid,
            )


def read_github_auth_token(repo: Path, github_host: str) -> str:
    result = run(
        ["gh", "auth", "token", "--hostname", github_host],
        cwd=repo,
        failure_code="PR_QUERY_FAILED",
        github_host=github_host,
    )
    token = result.stdout.strip()
    if not token or any(character.isspace() for character in token):
        raise ContractError(
            "PR_QUERY_FAILED",
            command="gh",
            githubTokenInvalid=True,
        )
    return token


def load_pull_requests(
    repo: Path,
    repository: str,
    github_host: str,
    github_config_dir: Path,
    github_token: str,
) -> list[dict[str, Any]]:
    result = run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repository,
            "--state",
            "open",
            "--limit",
            str(PR_QUERY_LIMIT),
            "--json",
            "number,headRefName,headRefOid,baseRefName,baseRefOid,isCrossRepository,isDraft,url",
        ],
        cwd=repo,
        failure_code="PR_QUERY_FAILED",
        github_host=github_host,
        github_config_dir=github_config_dir,
        github_authentication=github_token,
    )
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ContractError("PR_QUERY_INVALID") from error
    if not isinstance(document, list) or not all(
        isinstance(entry, dict) for entry in document
    ):
        raise ContractError("PR_QUERY_INVALID")
    if len(document) >= PR_QUERY_LIMIT:
        raise ContractError("PR_QUERY_TRUNCATED", limit=PR_QUERY_LIMIT)
    return document


def bind_pull_requests(
    surfaces: list[dict[str, str]],
    aliases: dict[str, str],
    pull_requests: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    bindings: dict[str, dict[str, Any]] = {}
    seen_numbers: set[int] = set()
    alias_branches = {
        surface["ref"].removeprefix("refs/heads/") for surface in surfaces
    }
    forbidden_alias_heads = sorted(
        {
            head
            for pull_request in pull_requests
            if isinstance((head := pull_request.get("headRefName")), str)
            and head in alias_branches
            and pull_request.get("isCrossRepository") is not True
        }
    )
    if forbidden_alias_heads:
        raise ContractError("PR_IDENTITY_MISMATCH", aliasHeads=forbidden_alias_heads)
    for surface in surfaces:
        oid = aliases[surface["name"]]
        matches = [
            pull_request
            for pull_request in pull_requests
            if pull_request.get("headRefOid") == oid
            and pull_request.get("isCrossRepository") is False
        ]
        if len(matches) != 1 or not isinstance(matches[0].get("number"), int):
            raise ContractError(
                "PR_IDENTITY_MISMATCH",
                surface=surface["name"],
                oid=oid,
                matchCount=len(matches),
            )
        pull_request = matches[0]
        if pull_request["number"] in seen_numbers:
            raise ContractError(
                "PR_IDENTITY_MISMATCH", surface=surface["name"], oid=oid
            )
        seen_numbers.add(pull_request["number"])
        bindings[surface["name"]] = {
            key: pull_request.get(key)
            for key in (
                "number",
                "headRefName",
                "headRefOid",
                "baseRefName",
                "baseRefOid",
                "isCrossRepository",
                "isDraft",
                "url",
            )
        }
    return bindings


def pull_request_identities(
    bindings: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        name: {key: binding[key] for key in PR_IDENTITY_KEYS}
        for name, binding in bindings.items()
    }


def resolve(arguments: argparse.Namespace) -> dict[str, Any]:
    repo = Path(arguments.repo).resolve()
    manifest_path = (
        Path(__file__).resolve().parents[1] / "references" / "premerge-stack.json"
    )
    manifest = load_manifest(manifest_path)
    git_config_snapshot = read_git_config_snapshot(repo)
    verified_remote = verify_remote(arguments.remote, manifest, git_config_snapshot)
    verify_https_transport_security(verified_remote.url, git_config_snapshot)
    verify_repository_state(repo, arguments.remote, git_config_snapshot)
    github_host = verify_repository_identity(
        manifest["repository"], verified_remote.identity
    )
    github_token = read_github_auth_token(repo, github_host)
    ssh_destination = ssh_destination_for_identity(verified_remote.identity)
    uses_ssh_transport = ssh_destination is not None
    git_https_authentication = (
        (verified_remote.url, github_token)
        if urlparse(verified_remote.url).scheme == "https"
        else None
    )
    surfaces = manifest["surfaces"]
    object_directory = resolve_git_path(repo, "objects")
    cached_aliases = read_cached_aliases(repo, arguments.remote, surfaces)
    with tempfile.TemporaryDirectory(prefix="resolve-premerge-stack-") as directory:
        transport_root = Path(directory)
        transport_repo = transport_root / "transport.git"
        github_config_dir = transport_root / "gh-config"
        github_config_dir.mkdir(mode=0o700)
        git(
            transport_root,
            "init",
            "--bare",
            "--object-format=sha1",
            str(transport_repo),
            failure_code="TRANSPORT_REPOSITORY_FAILED",
            git_config_snapshot=(),
        )
        aliases = query_aliases(
            transport_repo,
            verified_remote.url,
            surfaces,
            initial=True,
            uses_ssh_transport=uses_ssh_transport,
            ssh_destination=ssh_destination,
            git_config_snapshot=git_config_snapshot,
            git_https_authentication=git_https_authentication,
        )
        pull_requests = load_pull_requests(
            repo,
            manifest["repository"],
            github_host,
            github_config_dir,
            github_token,
        )
        bindings = bind_pull_requests(surfaces, aliases, pull_requests)
        negotiation_tips = collect_public_negotiation_tips(
            transport_repo,
            object_directory,
            bindings,
        )
        fetch_immutable_objects(
            transport_repo,
            object_directory,
            verified_remote.url,
            aliases,
            negotiation_tips=negotiation_tips,
            uses_ssh_transport=uses_ssh_transport,
            ssh_destination=ssh_destination,
            git_config_snapshot=git_config_snapshot,
            git_https_authentication=git_https_authentication,
        )
        verify_cached_aliases(
            transport_repo,
            object_directory,
            cached_aliases,
            aliases,
        )

        relationships = []
        for relationship in manifest["relationships"]:
            left_oid = aliases[relationship["left"]]
            right_oid = aliases[relationship["right"]]
            merge_base_oid = find_merge_base(
                transport_repo,
                object_directory,
                left_oid,
                right_oid,
            )
            relationships.append(
                {
                    **relationship,
                    "leftOid": left_oid,
                    "rightOid": right_oid,
                    "mergeBaseOid": merge_base_oid,
                    "leftIsAncestorOfRight": is_ancestor(
                        transport_repo,
                        object_directory,
                        left_oid,
                        right_oid,
                    ),
                    "rightIsAncestorOfLeft": is_ancestor(
                        transport_repo,
                        object_directory,
                        right_oid,
                        left_oid,
                    ),
                }
            )

        final_aliases = query_aliases(
            transport_repo,
            verified_remote.url,
            surfaces,
            initial=False,
            uses_ssh_transport=uses_ssh_transport,
            ssh_destination=ssh_destination,
            git_config_snapshot=git_config_snapshot,
            git_https_authentication=git_https_authentication,
        )
        if final_aliases != aliases:
            raise ContractError(
                "ALIAS_CHANGED_DURING_RESOLUTION",
                before=aliases,
                after=final_aliases,
            )

        final_pull_requests = load_pull_requests(
            repo,
            manifest["repository"],
            github_host,
            github_config_dir,
            github_token,
        )
        final_bindings = bind_pull_requests(surfaces, aliases, final_pull_requests)
        initial_identities = pull_request_identities(bindings)
        final_identities = pull_request_identities(final_bindings)
        if final_identities != initial_identities:
            raise ContractError(
                "PR_CHANGED_DURING_RESOLUTION",
                before=initial_identities,
                after=final_identities,
            )

        aliases_after_pr_query = query_aliases(
            transport_repo,
            verified_remote.url,
            surfaces,
            initial=False,
            uses_ssh_transport=uses_ssh_transport,
            ssh_destination=ssh_destination,
            git_config_snapshot=git_config_snapshot,
            git_https_authentication=git_https_authentication,
        )
        if aliases_after_pr_query != aliases:
            raise ContractError(
                "ALIAS_CHANGED_DURING_RESOLUTION",
                before=aliases,
                after=aliases_after_pr_query,
            )

    resolved_surfaces = {
        surface["name"]: {
            "role": surface["role"],
            "ref": surface["ref"],
            "oid": aliases[surface["name"]],
            "pullRequest": final_bindings[surface["name"]],
        }
        for surface in surfaces
    }
    return {
        "schemaVersion": 1,
        "repository": manifest["repository"],
        "remote": arguments.remote,
        "remoteIdentity": verified_remote.identity,
        "remoteIdentityFingerprint": sha256_fingerprint(
            verified_remote.identity.encode("utf-8")
        ),
        "surfaces": resolved_surfaces,
        "relationships": relationships,
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--remote", default="origin")
    return parser.parse_args()


def main() -> int:
    try:
        verify_dynamic_loader_environment()
        verify_openssl_environment()
        document = resolve(parse_arguments())
    except ContractError as error:
        print(
            json.dumps(
                {"error": {"code": error.code, "evidence": error.evidence}},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
