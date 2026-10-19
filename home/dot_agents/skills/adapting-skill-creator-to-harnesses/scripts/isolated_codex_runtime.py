#!/usr/bin/env python3
"""Credential-separated container runtime for native and ACPX trigger probes.

The model/tool process has no host mounts, credentials, or external network.
Its only connection to the authenticated broker is a per-probe Unix socket.
The container engine and the locally built image are trusted operator tooling.
"""

from __future__ import annotations

import json
import os
import re
import select
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any


DEFAULT_IMAGE = "nisavid-trigger-eval:codex-0.163.0-acpx-0.19.6"
PROBE_HOME = Path("/home/probe")
PROBE_CWD = Path("/work")
PROBE_CODEX_HOME = PROBE_HOME / ".codex"
BROKER_COMMAND = ["python3", "-I", "/opt/trigger/trigger_eval_broker.py"]
WORKER_COMMAND = ["python3", "-I", "/opt/trigger/trigger_eval_worker.py", "serve"]
WORKER_ENV = {
    "HOME": str(PROBE_HOME),
    "CODEX_HOME": str(PROBE_CODEX_HOME),
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "NO_COLOR": "1",
    "NO_BROWSER": "1",
    "CODEX_PATH": "/usr/local/bin/codex",
    "MODEL_PROVIDER": "trigger-broker",
    "INITIAL_AGENT_MODE": "agent-full-access",
}


class IsolationError(RuntimeError):
    """Required isolation or broker authentication is unavailable."""


def probe_config(name: str | None) -> str:
    # The outer container is the security boundary. Nested Codex sandboxes
    # need extra kernel privileges and would block the local inference relay.
    # Neither runner ever uses this configuration outside that boundary.
    config = '''sandbox_mode = "danger-full-access"
approval_policy = "never"
web_search = "disabled"
model_provider = "trigger-broker"
allow_login_shell = false

[features]
shell_tool = true

[shell_environment_policy]
inherit = "none"

[model_providers.trigger-broker]
name = "Isolated trigger evaluation"
base_url = "http://127.0.0.1:8765/v1"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
'''
    if name is not None:
        skill = PROBE_CODEX_HOME / "skills" / name / "SKILL.md"
        config += f'''
[[skills.config]]
path = {json.dumps(str(skill))}
enabled = true
'''
    return config


def load_credentials(codex_home: Path) -> dict[str, str]:
    """Read only the credential needed by the broker; never export refresh tokens."""
    try:
        with (codex_home / "auth.json").open("rb") as source:
            raw = source.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("oversized auth file")
        auth = json.loads(raw)
        if not isinstance(auth, dict):
            raise ValueError("invalid auth object")
        api_key = auth.get("OPENAI_API_KEY")
        if isinstance(api_key, str) and api_key:
            return {"kind": "api_key", "token": api_key}
        tokens = auth.get("tokens")
        if isinstance(tokens, dict):
            access_token = tokens.get("access_token")
            account_id = tokens.get("account_id")
            if isinstance(access_token, str) and access_token:
                result = {"kind": "chatgpt", "token": access_token}
                if isinstance(account_id, str) and account_id:
                    result["account_id"] = account_id
                return result
    except (OSError, ValueError, TypeError):
        pass
    # Do not include source bytes, parser exceptions, or credential values.
    raise IsolationError(
        "The broker requires a valid auth.json in --codex-home. Log in or refresh "
        "Codex outside the evaluator first; keyring-only and ambient-key authentication "
        "are not imported into trigger probes."
    )


def add_runtime_arguments(parser: Any) -> None:
    parser.add_argument("--container-runtime", default="docker", help="Trusted local Docker-compatible engine")
    parser.add_argument("--runtime-image", default=DEFAULT_IMAGE, help="Locally built isolated runtime image; never pulled automatically")


class IsolatedCodexRuntime:
    """Own and tear down one evaluator, broker, and socket volume."""

    broker_command = BROKER_COMMAND
    worker_command = WORKER_COMMAND

    def __init__(
        self,
        *,
        codex_home: Path,
        skill_path: Path | None,
        engine: str = "docker",
        image: str = DEFAULT_IMAGE,
        timeout: int = 60,
    ) -> None:
        self.codex_home = codex_home
        self.skill_path = skill_path
        self.engine = engine
        self.image = image
        self.timeout = max(1, timeout)
        identity = uuid.uuid4().hex
        self.worker_name = f"trigger-eval-worker-{identity}"
        self.broker_name = f"trigger-eval-broker-{identity}"
        self.volume_name = f"trigger-eval-socket-{identity}"
        self._broker: subprocess.Popen[str] | None = None
        self._entered = False
        self._resources_started = False
        self._host_env = {
            key: value for key, value in os.environ.items()
            if key in {"PATH", "HOME", "XDG_RUNTIME_DIR", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH", "CONTAINER_HOST"}
        }

    def _engine(self, args: list[str], *, input: str | None = None, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.engine, *args], input=input, text=True, capture_output=True,
            env=self._host_env, timeout=timeout or self.timeout,
        )

    def _checked(self, args: list[str], *, input: str | None = None) -> subprocess.CompletedProcess[str]:
        result = self._engine(args, input=input)
        if result.returncode:
            raise IsolationError("Container runtime operation failed; verify the local engine and build the documented runtime image.")
        return result

    def __enter__(self) -> IsolatedCodexRuntime:
        resolved = shutil.which(self.engine)
        if not resolved:
            raise IsolationError("A working local container engine is required; trigger evaluation will not fall back to host execution.")
        self.engine = resolved
        if not self.image or self.image.startswith("-"):
            raise IsolationError("Invalid runtime image reference")
        self._checked(["image", "inspect", self.image])
        skills = []
        if self.skill_path is not None:
            name = self.skill_path.parent.name
            if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) is None or len(name) > 64:
                raise IsolationError("Probe skill name must be a lowercase slug of at most 64 characters")
            skills = [{"name": name, "content": self.skill_path.read_text(encoding="utf-8")}]
        else:
            name = None
        credentials = load_credentials(self.codex_home)
        try:
            self._resources_started = True
            self._checked(["volume", "create", self.volume_name])
            common = [
                "--pull=never", "--read-only", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--user=1000:1000",
                "--pids-limit=256", "--memory=1g", "--cpus=2",
                "--tmpfs=/tmp:rw,nosuid,nodev,size=128m,uid=1000,gid=1000,mode=700",
            ]
            broker_cmd = [
                self.engine, "run", "--rm", "--interactive", "--name", self.broker_name,
                *common, "--mount", f"type=volume,src={self.volume_name},dst=/broker-socket",
                "--entrypoint=env", self.image, "-i", "PATH=/usr/local/bin:/usr/bin:/bin",
                "HOME=/tmp", *self.broker_command,
            ]
            self._broker = subprocess.Popen(
                broker_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, env=self._host_env,
            )
            assert self._broker.stdin is not None and self._broker.stdout is not None
            self._broker.stdin.write(json.dumps(credentials) + "\n")
            self._broker.stdin.close()
            # Only a fixed readiness line is emitted by the credential-bearing
            # process. No broker output is retained as an evaluation artifact.
            ready, _, _ = select.select([self._broker.stdout], [], [], self.timeout)
            if not ready or self._broker.stdout.readline(128) != "READY\n":
                raise IsolationError("Credential broker did not become ready; no probe was started")
            self._checked([
                "run", "--rm", "--detach", "--name", self.worker_name, *common,
                "--network=none",
                "--tmpfs=/home/probe:rw,nosuid,nodev,size=256m,uid=1000,gid=1000,mode=700",
                "--tmpfs=/work:rw,nosuid,nodev,size=128m,uid=1000,gid=1000,mode=700",
                "--mount", f"type=volume,src={self.volume_name},dst=/broker-socket,readonly",
                "--entrypoint=env", self.image, "-i", *[f"{k}={v}" for k, v in WORKER_ENV.items()],
                *self.worker_command,
            ])
            self._checked([
                "exec", "--interactive", self.worker_name, "env", "-i",
                *[f"{k}={v}" for k, v in WORKER_ENV.items()],
                "python3", "-I", "/opt/trigger/trigger_eval_worker.py", "init",
            ], input=json.dumps({"skills": skills, "config": probe_config(name)}))
            self._entered = True
            return self
        except BaseException:
            self.close()
            raise
        finally:
            credentials.clear()

    def run(self, argv: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        if not self._entered:
            raise IsolationError("Probe runtime is not active")
        if not argv or argv[0].startswith("-"):
            raise IsolationError("Invalid probe command")
        try:
            return self._engine([
                "exec", "--workdir=/work", self.worker_name, "env", "-i",
                *[f"{k}={v}" for k, v in WORKER_ENV.items()], *argv,
            ], timeout=timeout)
        except subprocess.TimeoutExpired:
            # Killing the engine client alone leaves an exec process running.
            # Destroy the complete sandbox before returning the timeout.
            self.close()
            raise

    def close(self) -> None:
        self._entered = False
        if not self._resources_started:
            return
        failures = []
        for name in (self.worker_name, self.broker_name):
            try:
                result = self._engine(["rm", "--force", name], timeout=15)
                # --rm may already have removed an exited container. Only
                # that explicit absence is harmless; engine errors must surface.
                absent = result.stderr.strip() == f"Error response from daemon: No such container: {name}"
                if result.returncode and not absent:
                    failures.append(name)
            except (OSError, subprocess.TimeoutExpired):
                failures.append(name)
        if self._broker is not None:
            try:
                self._broker.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._broker.kill()
                self._broker.wait()
            if self._broker.stdout is not None:
                self._broker.stdout.close()
        try:
            result = self._engine(["volume", "rm", self.volume_name], timeout=15)
            if result.returncode:
                failures.append(self.volume_name)
        except (OSError, subprocess.TimeoutExpired):
            failures.append(self.volume_name)
        self._resources_started = False
        if failures:
            raise IsolationError("Container cleanup failed; remove these isolated resources: " + ", ".join(failures))

    def __exit__(self, *_: Any) -> None:
        self.close()
