#!/usr/bin/env python3
"""Deterministic Responses fixture, included only in the container-tests target.

It requests a genuine shell-tool read, and returns the sentinel only after that
tool's output appears in a subsequent request. No upstream model is contacted.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import trigger_eval_broker as broker  # noqa: E402
from trigger_eval_broker import BrokerServer, Credentials  # noqa: E402


SOCKET_PATH = Path("/broker-socket/inference.sock")
SKILL_PATH = "/home/test/.codex/skills/container-canary/SKILL.md"
SENTINEL = "CONTAINER_CANARY_SENTINEL"


def request_shape(value: Any) -> Any:
    """Keep schema failures actionable without returning prompt or credential text."""
    if isinstance(value, dict):
        return {key: child if key == "type" and isinstance(child, str) else request_shape(child)
                for key, child in value.items()}
    if isinstance(value, list):
        return [request_shape(child) for child in value[:8]]
    return type(value).__name__


production_prepare_request = broker.prepare_request


def prepare_fixture_request(body: bytes) -> bytes:
    try:
        return production_prepare_request(body)
    except ValueError:
        broker.INVALID_REQUEST = "Fixture request schema rejected: " + json.dumps(request_shape(json.loads(body)))
        raise


broker.prepare_request = prepare_fixture_request


def objects(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def local_functions(tools: list[dict[str, Any]], namespace: str | None = None):
    for tool in tools:
        if tool.get("type") == "namespace":
            yield from local_functions(tool["tools"], tool["name"])
        elif tool.get("type") == "function":
            yield tool["name"], namespace


def output_item(request: dict[str, Any]) -> dict[str, Any]:
    for item in objects(request.get("input", [])):
        if item.get("type") == "function_call_output" and SENTINEL in str(item.get("output", "")):
            return {
                "type": "message", "id": "msg_canary", "status": "completed",
                "role": "assistant", "content": [
                    {"type": "output_text", "text": SENTINEL, "annotations": []},
                ],
            }
    tools = list(request.get("tools", []))
    for item in request.get("input", []):
        if isinstance(item, dict) and item.get("type") == "additional_tools":
            tools.extend(item["tools"])
    available = dict(local_functions(tools))
    for candidate in ("exec_command", "shell_command", "shell"):
        name = next((key for key in available if key.split(".")[-1] == candidate), None)
        if name is None:
            continue
        command = f"cat {SKILL_PATH}"
        args: dict[str, Any]
        if candidate == "exec_command":
            args = {"cmd": command, "max_output_tokens": 1000}
        elif candidate == "shell_command":
            args = {"command": command}
        else:
            args = {"command": ["/bin/sh", "-c", command]}
        return {
            "type": "function_call", "id": "fc_canary", "status": "completed",
            "call_id": "call_canary", "name": name, "namespace": available[name],
            "arguments": json.dumps(args),
        }
    raise ValueError("The harness did not advertise a supported shell tool")


def response_events(item: dict[str, Any]) -> list[dict[str, Any]]:
    response = {
        "id": "resp_canary", "object": "response", "created_at": 1,
        "status": "in_progress", "output": [],
    }
    events = [{"type": "response.created", "response": response}]
    events.append({"type": "response.output_item.added", "output_index": 0, "item": item})
    if item["type"] == "message":
        part = item["content"][0]
        events.extend([
            {"type": "response.content_part.added", "item_id": item["id"], "output_index": 0, "content_index": 0, "part": part},
            {"type": "response.output_text.delta", "item_id": item["id"], "output_index": 0, "content_index": 0, "delta": SENTINEL},
            {"type": "response.output_text.done", "item_id": item["id"], "output_index": 0, "content_index": 0, "text": SENTINEL},
        ])
    events.append({"type": "response.output_item.done", "output_index": 0, "item": item})
    events.append({
        "type": "response.completed",
        "response": {
            **response, "status": "completed", "output": [item],
            "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
        },
    })
    return events


class FixtureResponse:
    status = 200

    def __init__(self, request: dict[str, Any]) -> None:
        events = response_events(output_item(request))
        self.body = io.BytesIO("".join(f"data: {json.dumps(event)}\n\n" for event in events).encode())

    def getheader(self, name: str, default: str = "") -> str:
        return "text/event-stream" if name.lower() == "content-type" else default

    def read1(self, size: int) -> bytes:
        return self.body.read(size)


class FixtureConnection:
    """Production broker transport seam, available only in this test image."""

    def __init__(self, host: str, timeout: float) -> None:
        if host not in {"api.openai.com", "chatgpt.com"}:
            raise ValueError("Unexpected broker upstream")
        self.sock = self
        self.request_body: dict[str, Any] = {}

    def settimeout(self, timeout: float) -> None:
        pass

    def connect(self) -> None:
        pass

    def request(self, method: str, path: str, *, body: bytes, headers: dict[str, str]) -> None:
        if method != "POST" or path not in {"/v1/responses", "/backend-api/codex/responses"}:
            raise ValueError("Unexpected broker request")
        if not headers.get("Authorization", "").startswith("Bearer " + "fixture/broker-credential-"):
            raise ValueError("Fixture accepts only synthetic credentials")
        self.request_body = json.loads(body)

    def getresponse(self) -> FixtureResponse:
        return FixtureResponse(self.request_body)

    def close(self) -> None:
        pass


def main() -> None:
    # Match the production broker's input and readiness contract. The supplied
    # synthetic credential is deliberately never returned to a caller.
    credentials = Credentials.parse(json.loads(sys.stdin.readline()))
    with BrokerServer(SOCKET_PATH, credentials, connection_factory=FixtureConnection) as server:
        print("READY", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
