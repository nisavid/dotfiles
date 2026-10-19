#!/usr/bin/env python3
"""Synthetic transport tests; these never contact an inference provider."""

from __future__ import annotations

import contextlib
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


broker = load_module("trigger_eval_broker")
worker = load_module("trigger_eval_worker")
FIXTURE_BEARER = "fixture/broker-canary"
FIXTURE_UPSTREAM_TEXT = "SYNTHETIC_UPSTREAM_ERROR_CANARY"


class FakeResponse:
    def __init__(self, body=b'{"id":"response-test","output":[]}', status=200, content_type="application/json"):
        self.status = status
        self.body = io.BytesIO(body)
        self.content_type = content_type

    def getheader(self, name, default=None):
        return self.content_type if name.lower() == "content-type" else default

    def read1(self, size):
        return self.body.read(size)


class FakeConnection:
    def __init__(self, factory, host, timeout):
        self.factory = factory
        self.host = host
        self.timeout = timeout
        self.sock = None
        self.closed = False

    def connect(self):
        pass

    def request(self, method, path, body, headers):
        self.factory.calls.append((self.host, method, path, json.loads(body), headers))

    def getresponse(self):
        return self.factory.response_factory()

    def close(self):
        self.closed = True


class FakeFactory:
    def __init__(self, response_factory=FakeResponse):
        self.calls = []
        self.connections = []
        self.response_factory = response_factory

    def __call__(self, host, timeout):
        connection = FakeConnection(self, host, timeout)
        self.connections.append(connection)
        return connection


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=3)
        self.path = str(path)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class MemorySocket:
    def __init__(self, data):
        self.input = io.BytesIO(data)
        self.output = bytearray()

    def makefile(self, mode, *args):
        return self.input

    def sendall(self, data):
        self.output.extend(data)

    def settimeout(self, timeout):
        pass


def run_handler(handler, data, server):
    transport = MemorySocket(data)
    handler(transport, ("127.0.0.1", 1), server)
    return bytes(transport.output)


def decode_response(raw):
    head, body = raw.split(b"\r\n\r\n", 1)
    lines = head.decode().split("\r\n")
    return int(lines[0].split()[1]), dict(line.split(": ", 1) for line in lines[1:]), body


@contextlib.contextmanager
def running_broker(factory=None, kind="chatgpt"):
    factory = factory or FakeFactory()
    credentials = broker.Credentials(kind, FIXTURE_BEARER, "fixture-account" if kind == "chatgpt" else None)
    server = SimpleNamespace(credentials=credentials, connection_factory=factory, requests_started=0)
    yield server, server, factory


def request(path, value=None, *, method="POST", target="/v1/responses", headers=None):
    value = value if value is not None else {"model": "gpt-test", "input": "Select a skill", "stream": True}
    body = json.dumps(value).encode()
    headers = dict(headers or {"Content-Type": "application/json"})
    headers["Content-Length"] = str(len(body))
    raw = f"{method} {target} HTTP/1.1\r\n".encode()
    raw += b"".join(f"{key}: {value}\r\n".encode() for key, value in headers.items())
    return decode_response(run_handler(broker.BrokerHandler, raw + b"\r\n" + body, path))


def raw_request(path, data):
    return run_handler(broker.BrokerHandler, data, path)


class BrokerTests(unittest.TestCase):
    def test_credentials_reject_headers_and_unknown_controls(self):
        fixture_invalid = "bad\r\nX-Extra: canary"
        for value in (
            {"kind": "openai", "token": fixture_invalid},
            {"kind": "chatgpt", "token": FIXTURE_BEARER, "account_id": "bad\naccount"},
            {"kind": "openai", "token": FIXTURE_BEARER, "upstream": "https://attacker.invalid"},
            {"kind": "unknown", "token": FIXTURE_BEARER},
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                broker.Credentials.parse(value)
        self.assertEqual(broker.Credentials.parse({"kind": "chatgpt", "token": FIXTURE_BEARER}).bearer, FIXTURE_BEARER)
        self.assertNotIn(FIXTURE_BEARER, repr(broker.Credentials("chatgpt", FIXTURE_BEARER)))

    def test_fixed_upstream_overrides_all_caller_identity_headers_and_env(self):
        fixture_ambient = "fixture/ambient-canary"
        fixture_caller = "Bearer " + "fixture/caller-canary"
        with mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://attacker.invalid", "OPENAI_API_KEY": fixture_ambient}):
            with running_broker() as (path, server, factory):
                status, headers, body = request(path, headers={
                    "Content-Type": "application/json", "Authorization": fixture_caller,
                    "Host": "attacker.invalid", "ChatGPT-Account-ID": "wrong-account",
                    "Cookie": "cookie-canary", "X-Upstream": "https://attacker.invalid",
                })
        self.assertEqual(status, 200)
        host, method, target, value, sent = factory.calls[0]
        self.assertEqual((host, method, target), ("chatgpt.com", "POST", "/backend-api/codex/responses"))
        self.assertEqual(sent["Authorization"], f"Bearer {FIXTURE_BEARER}")
        self.assertEqual(sent["ChatGPT-Account-ID"], "fixture-account")
        self.assertNotIn("Cookie", sent)
        self.assertNotIn("X-Upstream", sent)
        self.assertNotIn("ambient-canary", json.dumps(sent))
        self.assertNotIn(FIXTURE_BEARER.encode(), body)
        self.assertTrue(all(connection.closed for connection in factory.connections))

    def test_api_key_endpoint_and_stateless_requests(self):
        with running_broker(kind="openai") as (path, server, factory):
            status, _, _ = request(path, {"model": "gpt-test", "input": [], "store": True,
                                        "tools": [{"type": "function", "name": "read_skill"},
                                                  {"type": "custom", "name": "shell"}]})
        self.assertEqual(status, 200)
        self.assertEqual(factory.calls[0][:3], ("api.openai.com", "POST", "/v1/responses"))
        self.assertIs(factory.calls[0][3]["store"], False)
        self.assertNotIn("background", factory.calls[0][3])
        self.assertNotIn("ChatGPT-Account-ID", factory.calls[0][4])

    def test_hosted_tools_and_remote_retrieval_fail_before_upstream(self):
        bad_values = [
            {"tools": [{"type": kind}]} for kind in
            ("web_search", "web_search_preview", "file_search", "code_interpreter", "computer", "mcp", "image_generation")
        ] + [
            {"tool_choice": {"type": "web_search"}},
            {"tool_choice": {"type": "allowed_tools", "tools": [{"type": "web_search"}]}},
            {"input": [{"type": "input_image", "image_url": "https://attacker.invalid"}]},
            {"input": [{"type": "input_file", "file_id": "file-canary"}]},
            {"input": [{"type": "item_reference", "id": "stored-item"}]},
            {"previous_response_id": "stored-response"},
            {"conversation": "stored-conversation"},
            {"prompt": {"id": "stored-prompt"}},
            {"background": True},
            {"access_programs": {"some_future_feature": True}},
            {"tools": {"type": "function"}},
        ]
        with running_broker() as (path, server, factory):
            for value in bad_values:
                with self.subTest(value=value):
                    status, _, _ = request(path, {"model": "gpt-test", **value})
                    self.assertEqual(status, 400)
            self.assertFalse(factory.calls)

    def test_namespace_tools_allow_only_local_descendants(self):
        for child, expected in (({"type": "function", "name": "read_skill"}, 200),
                                ({"type": "custom", "name": "shell"}, 200),
                                ({"type": "web_search"}, 400),
                                ({"type": "mcp", "server_url": "https://attacker.invalid"}, 400)):
            with self.subTest(child=child), running_broker() as (path, _, factory):
                namespace = {"type": "namespace", "name": "nested", "tools": [child]}
                value = {"model": "gpt-test", "tools": [{"type": "namespace", "name": "functions", "tools": [namespace]}]}
                self.assertEqual(request(path, value)[0], expected)
                self.assertEqual(bool(factory.calls), expected == 200)

    def test_input_references_and_control_items_fail_before_upstream(self):
        bad_items = [
            {"id": "fixture/stored-item"},
            {"id": "fixture/stored-item", "type": None},
            {"id": "fixture/stored-item", "type": "item_reference"},
            {"id": "fixture/stored-item", "type": "message"},
            {"id": "fixture/stored-item", "type": "reasoning"},
            {"id": "fixture/stored-item", "type": "function_call_output"},
            {"type": "additional_tools", "role": "developer", "tools": [{"type": "web_search"}]},
            {"type": "configuration_update", "reasoning": {"effort": "high"}},
            {"type": "program", "program": "fixture/program"},
            {"type": "tool_search_call", "execution": "server", "arguments": {}},
            {"type": "tool_search_output", "tools": [{"type": "mcp", "server_url": "https://attacker.invalid"}]},
            {"type": "web_search_call", "action": {"type": "search", "query": "canary"}},
            {"type": "message", "role": "user", "content": [{"type": "input_audio", "audio_url": "https://attacker.invalid"}]},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "canary", "file_id": "file-canary"}]},
            {"type": "function_call_output", "call_id": "call-local", "output": [{"id": "fixture/stored-item"}]},
            {"type": "function_call_output", "call_id": "call-local", "output": [{"type": "input_image", "image_url": "https://attacker.invalid"}]},
            {"type": "custom_tool_call_output", "call_id": "call-local", "output": {"type": "item_reference", "id": "fixture/stored-item"}},
            {"type": "message", "role": "user", "content": [], "tools": [{"type": "web_search"}]},
        ]
        for item in bad_items:
            with self.subTest(item=item), running_broker() as (path, _, factory):
                self.assertEqual(request(path, {"model": "gpt-test", "input": [item]})[0], 400)
                self.assertFalse(factory.calls)
        for value in (None, {}, 1, [None], ["text"]):
            with self.subTest(input=value), running_broker() as (path, _, factory):
                self.assertEqual(request(path, {"model": "gpt-test", "input": value})[0], 400)
                self.assertFalse(factory.calls)

    def test_responses_lite_declarations_allow_only_local_tools(self):
        declarations = {
            "type": "additional_tools", "id": "fixture/local-tools", "role": "developer",
            "tools": [{"type": "namespace", "name": "functions", "description": "Local tools", "tools": [
                {"type": "function", "name": "exec_command", "description": "Run a local command",
                 "strict": False, "parameters": {"type": "object", "properties": {}}},
                {"type": "custom", "name": "apply_patch", "description": "Edit a local file", "format": {"type": "text"}},
            ]}],
        }
        with running_broker() as (path, _, factory):
            self.assertEqual(request(path, {"model": "gpt-6.1-sol", "input": [declarations]})[0], 200)
            self.assertEqual(factory.calls[0][3]["input"], [declarations])
            self.assertNotIn("tools", factory.calls[0][3])
        bad_items = [
            {**declarations, "role": "user"},
            {**declarations, "id": {"id": "fixture/stored-item"}},
            {**declarations, "tools": None},
            {**declarations, "tools": {"type": "function"}},
            {**declarations, "unknown_control": True},
            {"type": "additional_tools", "id": "fixture/stored-item"},
        ]
        for hosted in ("web_search", "file_search", "mcp", "code_interpreter", "tool_search"):
            bad_items.extend([
                {**declarations, "tools": [{"type": hosted}]},
                {**declarations, "tools": [{"type": "namespace", "name": "functions", "tools": [
                    {"type": "namespace", "name": "nested", "tools": [{"type": hosted}]},
                ]}]},
            ])
        for item in bad_items:
            with self.subTest(item=item), running_broker() as (path, _, factory):
                self.assertEqual(request(path, {"model": "gpt-6.1-sol", "input": [item]})[0], 400)
                self.assertFalse(factory.calls)

    def test_inline_message_reasoning_and_local_call_history_is_preserved(self):
        history = [
            {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "Select a skill"}]},
            {"type": "message", "id": "fixture/message", "role": "assistant", "phase": "commentary",
             "content": [{"type": "output_text", "text": "Reading the skill", "annotations": [], "logprobs": []}]},
            {"type": "reasoning", "id": "fixture/reasoning", "encrypted_content": "fixture/encrypted-content",
             "summary": [{"type": "summary_text", "text": "Read the matching skill"}],
             "content": [{"type": "reasoning_text", "text": "Use local shell"}]},
            {"type": "function_call", "id": "fixture/function", "name": "exec_command", "namespace": "functions",
             "call_id": "fixture/call", "arguments": '{"cmd":"cat SKILL.md"}'},
            {"type": "function_call_output", "call_id": "fixture/call", "output": "TRIGGER_SENTINEL"},
            {"type": "function_call_output", "call_id": "fixture/call", "output": [{"type": "input_text", "text": "TRIGGER_SENTINEL"}]},
            {"type": "custom_tool_call", "id": "fixture/custom", "call_id": "fixture/custom-call", "name": "shell", "input": "cat SKILL.md"},
            {"type": "custom_tool_call_output", "call_id": "fixture/custom-call", "output": "TRIGGER_SENTINEL"},
            {"type": "custom_tool_call_output", "call_id": "fixture/custom-call", "output": [{"type": "input_text", "text": "TRIGGER_SENTINEL"}]},
            {"type": "agent_message", "author": "assistant", "recipient": "all", "content": [{"type": "input_text", "text": "Done"}]},
        ]
        with running_broker() as (path, _, factory):
            self.assertEqual(request(path, {"model": "gpt-test", "input": history})[0], 200)
            self.assertEqual(factory.calls[0][3]["input"], history)

    def test_path_method_and_http_framing_bypasses_fail_closed(self):
        with running_broker() as (path, server, factory):
            for target in ("/v1/responses?url=https://attacker.invalid", "http://attacker.invalid/v1/responses",
                           "/v1/responses/", "/v1/../responses", "/shutdown", "/v1/models", "//v1/responses"):
                with self.subTest(target=target):
                    self.assertNotEqual(request(path, target=target)[0], 200)
            for method in ("GET", "PUT", "CONNECT", "TRACE"):
                self.assertNotEqual(request(path, method=method)[0], 200)
            for extra in (
                b"Content-Length: 2\r\nContent-Length: 2\r\n",
                b"Transfer-Encoding: chunked\r\nContent-Length: 2\r\n",
                b"Content-Encoding: gzip\r\nContent-Length: 2\r\n",
                b"Content-Length: +2\r\n",
                b"Content-Length: 99999999\r\n",
                b"Content-Length: 2\r\nExpect: 100-continue\r\n",
            ):
                response = raw_request(path, b"POST /v1/responses HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\n" + extra + b"\r\n{}")
                self.assertNotIn(b" 200 ", response.split(b"\r\n", 1)[0])
            self.assertFalse(factory.calls)

    def test_upstream_errors_and_redirects_never_forward_body(self):
        for status in (301, 302, 401, 403, 429, 500):
            factory = FakeFactory(lambda: FakeResponse(FIXTURE_UPSTREAM_TEXT.encode(), status))
            with self.subTest(status=status), running_broker(factory) as (path, server, _):
                returned, _, body = request(path)
            self.assertEqual(returned, 401 if status in (401, 403) else 502)
            self.assertNotIn(FIXTURE_UPSTREAM_TEXT.encode(), body)
            self.assertEqual(len(factory.calls), 1)
            if status in (401, 403):
                self.assertIn(b"Refresh the host login", body)

    def test_json_and_sse_errors_are_sanitized(self):
        bodies = [
            (b'{"error":{"message":"' + FIXTURE_UPSTREAM_TEXT.encode() + b'"}}', "application/json"),
            (b'data: {"type":"error","message":"' + FIXTURE_UPSTREAM_TEXT.encode() + b'"}\n\n', "text/event-stream"),
            (b'data: {"type":"response.failed","response":{"error":{"message":"' + FIXTURE_UPSTREAM_TEXT.encode() + b'"}}}\n\n', "text/event-stream"),
        ]
        for body, content_type in bodies:
            with self.subTest(content_type=content_type):
                with running_broker(FakeFactory(lambda: FakeResponse(body, content_type=content_type))) as (path, _, _):
                    status, _, returned = request(path)
                self.assertEqual(status, 502)
                self.assertNotIn(FIXTURE_UPSTREAM_TEXT.encode(), returned)

    def test_sse_stream_preserves_model_output_but_not_error_details(self):
        body = (b'event: response.output_text.delta\r\ndata: {"type":"response.output_text.delta","delta":"TRIGGER_SENTINEL"}\r\n\r\n'
                b'event: error\ndata: {"type":"error","message":"' + FIXTURE_UPSTREAM_TEXT.encode() + b'"}\n\n')
        with running_broker(FakeFactory(lambda: FakeResponse(body, content_type="text/event-stream"))) as (path, _, _):
            status, headers, returned = request(path)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/event-stream")
        self.assertIn(b"TRIGGER_SENTINEL", returned)
        self.assertIn(b"Inference failed", returned)
        self.assertNotIn(FIXTURE_UPSTREAM_TEXT.encode(), returned)

    def test_sse_private_metadata_is_dropped_without_interrupting_responses(self):
        events = [
            {"type": "codex.rate_limits", "private": FIXTURE_BEARER},
            {"type": "response.created", "response": {"id": "fixture-response"}},
            {"type": "codex.response.metadata", "private": FIXTURE_UPSTREAM_TEXT},
            {"type": "response.output_text.delta", "delta": "TRIGGER_SENTINEL"},
            {"type": "responsesapi.websocket_timing", "private": "fixture-timing"},
            {"type": "response.completed", "response": {"status": "completed"}},
        ]
        body = b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events) + b"data: [DONE]\n\n"
        with running_broker(FakeFactory(lambda: FakeResponse(body, content_type="text/event-stream"))) as (path, _, _):
            status, _, returned = request(path)
        self.assertEqual(status, 200)
        expected = [event for event in events if event["type"].startswith("response.")]
        frames = returned.split(b"\n\n")
        self.assertEqual([json.loads(frame[6:]) for frame in frames[:-2]], expected)
        self.assertEqual(frames[-2], b"data: [DONE]")
        for private in (FIXTURE_BEARER, FIXTURE_UPSTREAM_TEXT, "fixture-timing", "Inference failed"):
            self.assertNotIn(private.encode(), returned)

    def test_sse_invalid_types_and_private_error_frames_still_fail_closed(self):
        for event in ({}, {"type": None}, {"type": []}, {"type": 3},
                      {"type": "codex.response.metadata", "error": {"message": FIXTURE_UPSTREAM_TEXT}}):
            with self.subTest(event=event):
                body = b"data: " + json.dumps(event).encode() + b"\n\n"
                with running_broker(FakeFactory(lambda: FakeResponse(body, content_type="text/event-stream"))) as (path, _, _):
                    status, _, returned = request(path)
                self.assertEqual(status, 502)
                self.assertNotIn(FIXTURE_UPSTREAM_TEXT.encode(), returned)

    def test_request_response_and_time_limits(self):
        with running_broker() as (path, server, factory):
            server.requests_started = broker.MAX_REQUESTS
            self.assertEqual(request(path)[0], 429)
            self.assertFalse(factory.calls)
        with mock.patch.object(broker, "MAX_RESPONSE_BYTES", 8):
            with running_broker() as (path, _, _):
                self.assertEqual(request(path)[0], 502)
        with mock.patch.object(broker, "REQUEST_TIMEOUT", 0):
            with running_broker() as (path, _, factory):
                self.assertEqual(request(path)[0], 502)
                self.assertFalse(factory.calls)

    def test_success_response_cannot_reflect_broker_credential(self):
        for content_type, body in (
            ("application/json", json.dumps({"output": FIXTURE_BEARER}).encode()),
            ("text/event-stream", b'data: ' + json.dumps({"type": "response.output_text.delta", "delta": FIXTURE_BEARER}).encode() + b'\n\n'),
        ):
            with self.subTest(content_type=content_type):
                with running_broker(FakeFactory(lambda: FakeResponse(body, content_type=content_type))) as (path, _, _):
                    status, _, returned = request(path)
                self.assertEqual(status, 502)
                self.assertNotIn(FIXTURE_BEARER.encode(), returned)
        escaped = "".join(f"\\u{ord(character):04x}" for character in FIXTURE_BEARER)
        body = ('{"output":[{"text":"prefix' + escaped + 'suffix"}]}').encode()
        with running_broker(FakeFactory(lambda: FakeResponse(body))) as (path, _, _):
            status, _, returned = request(path)
        self.assertEqual(status, 502)
        self.assertNotIn(FIXTURE_BEARER.encode(), returned)

    def test_upstream_network_factory_ignores_proxy_environment(self):
        with mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://attacker.invalid", "ALL_PROXY": "http://attacker.invalid"}):
            connection = broker._new_https_connection("api.openai.com", 5)
        self.assertIsInstance(connection, http.client.HTTPSConnection)
        self.assertEqual(connection.host, "api.openai.com")
        self.assertIsNone(connection._tunnel_host)
        connection.close()


class WorkerTests(unittest.TestCase):
    def test_initialize_keeps_exact_probe_body_and_no_auth(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            body = "---\nname: probe-skill\ndescription: synthetic\n---\nTRIGGER_SENTINEL\n"
            worker.initialize({"skills": [{"name": "probe-skill", "content": body}], "config": "model_provider='trigger-broker'\n"}, home=home)
            for root in (".agents", ".codex"):
                self.assertEqual((home / root / "skills/probe-skill/SKILL.md").read_text(), body)
            config = json.loads((home / ".acpx/config.json").read_text())
            self.assertEqual(config["agents"]["codex"]["command"], "/usr/local/bin/codex-acp")
            self.assertEqual(config["authPolicy"], "skip")
            self.assertFalse((home / ".codex/auth.json").exists())

    def test_initialize_supports_empty_preflight_and_rejects_traversal_or_multiple_skills(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            worker.initialize({"skills": [], "config": ""}, home=home)
            self.assertTrue((home / ".codex/config.toml").exists())
            self.assertFalse((home / ".agents/skills").exists())
        for name in ("../outside", "/tmp/outside", ".", "..", "with/slash", "bad\nname", ""):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    worker.initialize({"skills": [{"name": name, "content": "body"}], "config": ""}, home=Path(directory))
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            worker.initialize({"skills": [{"name": "one", "content": "a"}, {"name": "two", "content": "b"}], "config": ""}, home=Path(directory))

    def test_initialize_rejects_existing_symlink_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            outside = Path(directory) / "outside"
            home.mkdir()
            outside.mkdir()
            (home / ".agents").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                worker.initialize({"skills": [{"name": "probe", "content": "body"}], "config": ""}, home=home)
            self.assertEqual(list(outside.iterdir()), [])

    def test_relay_uses_unix_socket_and_rejects_forward_proxy_targets(self):
        with running_broker() as (endpoint, _, factory):
            class InMemoryBrokerConnection:
                def request(self, method, path, body, headers):
                    self.result = request(endpoint, json.loads(body), method=method, target=path, headers=headers)

                def getresponse(self):
                    status, headers, body = self.result
                    return FakeResponse(body, status, headers["Content-Type"])

                def close(self):
                    pass

            with mock.patch.object(worker, "BrokerConnection", InMemoryBrokerConnection):
                for target, expected in (("/v1/responses", 200), ("http://attacker.invalid/v1/responses", 400),
                                         ("/v1/responses?x=1", 400), ("//v1/responses", 400)):
                    body = json.dumps({"model": "gpt-test", "input": []}).encode()
                    raw = f"POST {target} HTTP/1.1\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nAuthorization: caller-canary\r\n\r\n".encode() + body
                    status, headers, returned = decode_response(run_handler(worker.RelayHandler, raw, SimpleNamespace()))
                    self.assertEqual(status, expected)
                    self.assertNotIn(FIXTURE_BEARER.encode(), returned)
            self.assertEqual(len(factory.calls), 1)
            self.assertEqual(factory.calls[0][4]["Authorization"], f"Bearer {FIXTURE_BEARER}")

    def test_relay_connection_is_fixed_unix_socket(self):
        with mock.patch.object(worker.socket, "socket") as create:
            connection = worker.BrokerConnection()
            connection.connect()
            create.assert_called_once_with(socket.AF_UNIX, socket.SOCK_STREAM)
            create.return_value.connect.assert_called_once_with("/broker-socket/inference.sock")

    def test_real_unix_socket_transport_when_available(self):
        try:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.close()
        except PermissionError:
            self.skipTest("This execution environment forbids AF_UNIX sockets")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inference.sock"
            with broker.BrokerServer(path, broker.Credentials("openai", FIXTURE_BEARER), connection_factory=FakeFactory()) as server:
                thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
                thread.start()
                try:
                    connection = UnixConnection(path)
                    connection.request("POST", "/v1/responses", json.dumps({"model": "gpt-test", "input": []}), {"Content-Type": "application/json"})
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertNotIn(FIXTURE_BEARER.encode(), response.read())
                    connection.close()
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                finally:
                    server.shutdown()
                    thread.join(3)

    def test_relay_readiness_retries_then_succeeds(self):
        with mock.patch.object(worker.socket, "create_connection", side_effect=[OSError, mock.MagicMock()]) as connect:
            with mock.patch.object(worker.time, "sleep"):
                worker.wait_for_relay()
        self.assertEqual(connect.call_count, 2)


if __name__ == "__main__":
    unittest.main()
