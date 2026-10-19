#!/usr/bin/env python3
"""Initialize disposable probe files and relay inference to the broker socket."""

from __future__ import annotations

import http.client
import http.server
import json
import re
import socket
import sys
import time
from pathlib import Path
from typing import Any

HOME = Path("/home/probe")
SOCKET_PATH = "/broker-socket/inference.sock"
MAX_BODY = 4 * 1024 * 1024
MAX_RESPONSE = 16 * 1024 * 1024


class BrokerConnection(http.client.HTTPConnection):
    def __init__(self) -> None:
        super().__init__("localhost", timeout=125)

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(SOCKET_PATH)


class RelayHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "TriggerRelay"
    sys_version = ""

    def setup(self) -> None:
        self.request.settimeout(10)
        super().setup()

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        self._error(code)

    def _error(self, code: int) -> None:
        self.close_connection = True
        body = b'{"error":{"message":"Trigger evaluation inference relay rejected or could not complete the request."}}'
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass

    def handle_expect_100(self) -> bool:
        self._error(400)
        return False

    def do_POST(self) -> None:
        self.close_connection = True
        lengths = self.headers.get_all("Content-Length", [])
        types = self.headers.get_all("Content-Type", [])
        if (
            self.path != "/v1/responses"
            or self.requestline.split()[1] != "/v1/responses"
            or self.headers.get("Transfer-Encoding") is not None
            or self.headers.get("Content-Encoding") is not None
            or self.headers.get("Expect") is not None
            or len(lengths) != 1
            or not re.fullmatch(r"[0-9]{1,10}", lengths[0])
            or len(types) != 1
            or types[0].split(";", 1)[0].strip().lower() != "application/json"
        ):
            self._error(400)
            return
        size = int(lengths[0])
        if not 0 < size <= MAX_BODY:
            self._error(413)
            return
        connection = None
        started = False
        try:
            body = self.rfile.read(size)
            if len(body) != size:
                raise ValueError
            connection = BrokerConnection()
            connection.request("POST", "/v1/responses", body=body, headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type not in {"text/event-stream", "application/json"}:
                raise ValueError
            self.send_response(response.status)
            self.send_header("Content-Type", content_type)
            self.send_header("Connection", "close")
            self.end_headers()
            started = True
            total = 0
            while True:
                chunk = response.read1(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_RESPONSE:
                    raise ValueError
                self.wfile.write(chunk)
                self.wfile.flush()
        except (OSError, ValueError, http.client.HTTPException):
            if not started:
                self._error(502)
        finally:
            if connection is not None:
                connection.close()


class RelayServer(http.server.HTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:
        pass


def initialize(value: Any, *, home: Path = HOME) -> None:
    if not isinstance(value, dict) or set(value) != {"skills", "config"}:
        raise ValueError("Invalid worker initialization")
    skills = value["skills"]
    config = value["config"]
    if not isinstance(skills, list) or len(skills) > 1 or not isinstance(config, str) or len(config) > 65536:
        raise ValueError("Invalid worker initialization")
    for skill in skills:
        if not isinstance(skill, dict) or set(skill) != {"name", "content"}:
            raise ValueError("Invalid worker initialization")
        name = skill["name"]
        content = skill["content"]
        if not isinstance(name, str) or len(name) > 64 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
            raise ValueError("Invalid worker skill name")
        if not isinstance(content, str) or len(content.encode("utf-8")) > 1024 * 1024:
            raise ValueError("Invalid worker skill content")
        # The parent initializes a fresh tmpfs before starting any evaluator process.
        for relative in (Path(".agents/skills") / name, Path(".codex/skills") / name):
            target = _directory(home, relative)
            with (target / "SKILL.md").open("x", encoding="utf-8") as output:
                output.write(content)
    codex = _directory(home, Path(".codex"))
    with (codex / "config.toml").open("x", encoding="utf-8") as output:
        output.write(config)
    acpx = _directory(home, Path(".acpx"))
    with (acpx / "config.json").open("x", encoding="utf-8") as output:
        output.write(json.dumps({"agents": {"codex": {"command": "/usr/local/bin/codex-acp"}}, "authPolicy": "skip"}) + "\n")


def _directory(home: Path, relative: Path) -> Path:
    if home.is_symlink() or not home.is_dir():
        raise ValueError("Worker home must be a real directory")
    current = home
    for component in relative.parts:
        current /= component
        if current.is_symlink():
            raise ValueError("Worker paths must not be symlinks")
        current.mkdir(exist_ok=True)
    return current


def wait_for_relay() -> None:
    deadline = time.monotonic() + 5
    while True:
        try:
            with socket.create_connection(("127.0.0.1", 8765), timeout=0.25):
                return
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError("Worker inference relay was not ready")
            time.sleep(0.05)


def main() -> int:
    try:
        if sys.argv[1:] == ["init"]:
            raw = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError
            initialize(json.loads(raw))
            wait_for_relay()
            print("READY", flush=True)
        elif sys.argv[1:] == ["serve"]:
            with RelayServer(("127.0.0.1", 8765), RelayHandler) as server:
                print("READY", flush=True)
                server.serve_forever(poll_interval=0.25)
        else:
            raise ValueError
    except Exception:
        print("Trigger evaluation worker could not start.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
