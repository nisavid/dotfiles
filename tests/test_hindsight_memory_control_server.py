import http.client
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "home" / "private_dot_local" / "lib"
sys.path.insert(0, str(LIB))

from hindsight_memory_control_plane.control_server import (
    ControlServer,
    ControlServerError,
)


KEY = "control-" + "k" * 40
DIGEST = "a" * 64
DATA_PLANE_TOKEN = "data-plane-token-value"
SIGNING_MATERIAL = "private-signing-material-value"


class ControlServerTest(unittest.TestCase):
    def setUp(self):
        self.resolutions = 0
        self.material_resolutions = 0
        self.session_calls = []

        def resolve_key():
            self.resolutions += 1
            return KEY

        def session_operation(operation, request):
            self.session_calls.append((operation, request))
            return {
                "session_id": request["session_id"],
                "state": {
                    "mint": "staged",
                    "status": "active",
                    "close": "closed",
                }[operation],
            }

        def resolve_forbidden_material():
            self.material_resolutions += 1
            return (DATA_PLANE_TOKEN, SIGNING_MATERIAL)

        self.server = ControlServer(
            host="127.0.0.1",
            port=0,
            access_key_resolver=resolve_key,
            forbidden_material_resolver=resolve_forbidden_material,
            status_provider=lambda: {
                "schema_version": 1,
                "state": "inactive",
                "policy_digest": DIGEST,
                "active_sessions": 0,
            },
            plan_provider=lambda plan_digest: {
                "schema_version": 1,
                "plan_digest": plan_digest,
                "destructive": False,
                "actions": [],
            },
            session_operator=session_operation,
            max_request_bytes=512,
            max_response_bytes=1024,
        )
        self.server.start()

    def tearDown(self):
        self.server.close()

    def request(self, method, path, *, body=None, headers=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.port, timeout=2
        )
        encoded = None if body is None else json.dumps(body).encode()
        supplied = dict(headers or {})
        if encoded is not None:
            supplied.setdefault("Content-Type", "application/json")
        connection.request(method, path, body=encoded, headers=supplied)
        response = connection.getresponse()
        payload = response.read()
        connection.close()
        return response.status, dict(response.getheaders()), json.loads(payload)

    @staticmethod
    def auth():
        return {"Authorization": f"Bearer {KEY}"}

    def test_bind_is_literal_loopback_only(self):
        for host in ("0.0.0.0", "localhost", "192.0.2.1", "::"):
            with (
                self.subTest(host=host),
                self.assertRaisesRegex(ControlServerError, "BIND_DENIED"),
            ):
                ControlServer(
                    host=host,
                    port=0,
                    access_key_resolver=lambda: KEY,
                    forbidden_material_resolver=lambda: (),
                    status_provider=lambda: {},
                    plan_provider=lambda digest: {},
                    session_operator=lambda operation, request: {},
                )
        ipv6 = ControlServer(
            host="::1",
            port=0,
            access_key_resolver=lambda: KEY,
            forbidden_material_resolver=lambda: (),
            status_provider=lambda: {},
            plan_provider=lambda digest: {},
            session_operator=lambda operation, request: {},
        )
        ipv6.close()

    def test_every_request_requires_fresh_direct_bearer_authentication(self):
        cases = [
            ({}, 401),
            ({"Authorization": "Bearer wrong"}, 401),
            ({"X-Forwarded-Authorization": f"Bearer {KEY}"}, 401),
            ({"Proxy-Authorization": f"Bearer {KEY}"}, 401),
            (self.auth(), 200),
            (self.auth(), 200),
        ]
        before = self.resolutions
        for headers, expected in cases:
            status, response_headers, body = self.request(
                "GET", "/health", headers=headers
            )
            self.assertEqual(status, expected)
            self.assertEqual(response_headers["Cache-Control"], "no-store")
            self.assertNotIn(KEY, json.dumps(body))
        self.assertEqual(self.resolutions - before, len(cases))

    def test_health_status_and_plan_inspection_are_closed_and_redacted(self):
        status, _, health = self.request("GET", "/health", headers=self.auth())
        self.assertEqual(status, 200)
        self.assertEqual(health, {"schema_version": 1, "status": "ok"})

        status, _, report = self.request(
            "GET", "/v1/status", headers=self.auth()
        )
        self.assertEqual(status, 200)
        self.assertEqual(report["policy_digest"], DIGEST)
        self.assertEqual(report["state"], "inactive")

        status, _, plan = self.request(
            "GET", f"/v1/plans/{DIGEST}", headers=self.auth()
        )
        self.assertEqual(status, 200)
        self.assertEqual(plan["plan_digest"], DIGEST)

        self.server.plan_provider = lambda plan_digest: {
            "schema_version": 1,
            "plan_digest": "b" * 64,
            "destructive": False,
            "actions": [],
        }
        status, _, body = self.request(
            "GET", f"/v1/plans/{DIGEST}", headers=self.auth()
        )
        self.assertEqual(status, 500)
        self.assertEqual(body, {"error": "RESPONSE_INVALID"})

        for method, path in (
            ("GET", "/v1/plans/not-a-digest"),
            ("GET", "/v1/unknown"),
            ("POST", "/v1/status"),
        ):
            with self.subTest(method=method, path=path):
                status, _, body = self.request(
                    method,
                    path,
                    headers=self.auth(),
                    body={} if method == "POST" else None,
                )
                self.assertIn(status, {404, 405})
                self.assertEqual(set(body), {"error"})

    def test_only_redacted_broker_session_operations_are_exposed(self):
        for operation in ("mint", "status", "close"):
            status, _, result = self.request(
                "POST",
                f"/v1/sessions/{operation}",
                headers=self.auth(),
                body={"session_id": "session-1"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(result["session_id"], "session-1")
            self.assertNotIn("capability", json.dumps(result).lower())
        self.assertEqual(
            [item[0] for item in self.session_calls],
            ["mint", "status", "close"],
        )

        for operation in ("exchange", "recall", "retain"):
            status, _, result = self.request(
                "POST",
                f"/v1/sessions/{operation}",
                headers=self.auth(),
                body={"session_id": "session-1"},
            )
            self.assertEqual(status, 404)
            self.assertEqual(result, {"error": "NOT_FOUND"})

        self.server.session_operator = lambda operation, request: {
            "session_id": request["session_id"],
            "state": "active",
            "payload": "private-session-data",
        }
        status, _, result = self.request(
            "POST",
            "/v1/sessions/status",
            headers=self.auth(),
            body={"session_id": "session-1"},
        )
        self.assertEqual(status, 500)
        self.assertEqual(result, {"error": "RESPONSE_INVALID"})
        self.assertNotIn("private-session-data", json.dumps(result))

        def fail_with_private_error(operation, request):
            raise ControlServerError("private-provider-diagnostic")

        self.server.session_operator = fail_with_private_error
        status, _, result = self.request(
            "POST",
            "/v1/sessions/status",
            headers=self.auth(),
            body={"session_id": "session-1"},
        )
        self.assertEqual(status, 500)
        self.assertEqual(result, {"error": "INTERNAL_ERROR"})
        self.assertNotIn("private-provider-diagnostic", json.dumps(result))

    def test_request_and_response_bodies_are_bounded(self):
        status, _, body = self.request(
            "GET",
            "/health",
            headers={**self.auth(), "X-Padding": "x" * 600},
        )
        self.assertEqual(status, 413)
        self.assertEqual(body, {"error": "REQUEST_TOO_LARGE"})

        status, _, body = self.request(
            "POST",
            "/v1/sessions/mint",
            headers=self.auth(),
            body={"session_id": "x" * 600},
        )
        self.assertEqual(status, 413)
        self.assertEqual(body, {"error": "REQUEST_TOO_LARGE"})
        self.assertEqual(self.session_calls, [])

        self.server.status_provider = lambda: {"state": "x" * 2048}
        status, _, body = self.request("GET", "/v1/status", headers=self.auth())
        self.assertEqual(status, 500)
        self.assertEqual(body, {"error": "RESPONSE_INVALID"})

    def test_successful_response_cannot_reveal_control_or_data_plane_material(
        self,
    ):
        forbidden = [
            {"access_key": KEY},
            {"token": "data-plane-token"},
            {"signing_material": "private-signing-material"},
            {"signingMaterial": "private-signing-material"},
            {"nested": {"capability": "private-capability"}},
            {"nested": [{"authorization": "Bearer private"}]},
            {"value": DATA_PLANE_TOKEN},
            {"nested": [{"value": SIGNING_MATERIAL}]},
        ]
        for value in forbidden:
            with self.subTest(value=value):
                self.server.status_provider = lambda value=value: value
                status, _, body = self.request(
                    "GET", "/v1/status", headers=self.auth()
                )
                self.assertEqual(status, 500)
                rendered = json.dumps(body)
                self.assertEqual(body, {"error": "RESPONSE_INVALID"})
                for secret in (
                    KEY,
                    "data-plane-token",
                    "private-signing-material",
                    "private-capability",
                    "Bearer private",
                    DATA_PLANE_TOKEN,
                    SIGNING_MATERIAL,
                ):
                    self.assertNotIn(secret, rendered)

        self.server.status_provider = lambda: {
            "schema_version": 1,
            "state": DATA_PLANE_TOKEN,
            "policy_digest": DIGEST,
            "active_sessions": 0,
        }
        before = self.material_resolutions
        status, _, body = self.request("GET", "/v1/status", headers=self.auth())
        self.assertEqual(status, 500)
        self.assertEqual(body, {"error": "RESPONSE_INVALID"})
        self.assertEqual(self.material_resolutions, before + 1)

    def test_session_input_schema_is_closed_before_operator_dispatch(self):
        invalid = [
            {},
            {"session_id": "session-1", "token": "private"},
            {"session_id": "bad space"},
            {"session_id": 7},
        ]
        for body in invalid:
            status, _, result = self.request(
                "POST", "/v1/sessions/mint", headers=self.auth(), body=body
            )
            self.assertEqual(status, 400)
            self.assertEqual(result, {"error": "SCHEMA_INVALID"})
        self.assertEqual(self.session_calls, [])


if __name__ == "__main__":
    unittest.main()
