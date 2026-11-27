import json
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SAMPLER = ROOT / "home/private_dot_local/bin/executable_github-rate-limit"
RESPONSE = {
    "resources": {
        "core": {"limit": 5000, "remaining": 0, "used": 5000, "reset": 1795800600},
        "graphql": {"limit": 7000, "remaining": 6983, "used": 17, "reset": 1795801200},
        "search": {"limit": 30},
    },
    "message": "unexpected response detail",
}


class GitHubRateLimitTest(unittest.TestCase):
    def sample(self, body, status=0):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            (fixture / "response").write_text(body)
            gh = fixture / "gh"
            gh.write_text(
                '#!/bin/sh\n'
                'printf "%s\\n" "$*" >> calls\n'
                'printf "%s\\n" "unexpected diagnostic" >&2\n'
                '/bin/cat response\n'
                f'exit {status}\n'
            )
            gh.chmod(0o755)
            result = subprocess.run(
                [sys.executable, str(SAMPLER)], cwd=fixture, capture_output=True,
                env={"PATH": tmp, "HOME": tmp}, timeout=5,
            )
            self.assertTrue((fixture / "calls").exists(), result.stderr)
            self.assertEqual((fixture / "calls").read_text(), "api --hostname github.com rate_limit\n")
            return result

    def test_sample_contains_only_the_eight_counters(self):
        result = self.sample(json.dumps(RESPONSE))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"5000 0 5000 1795800600 7000 6983 17 1795801200\n")
        self.assertEqual(result.stderr, b"")

    def test_failed_read_reports_one_error_and_no_sample(self):
        result = self.sample(json.dumps(RESPONSE), status=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"GitHub rate limit unavailable\n")

    def test_unusable_response_reports_only_the_error(self):
        bodies = ["invalid response", "{}"]
        for value in ("unexpected detail\nsecond line", True, -1, 1.5):
            response = deepcopy(RESPONSE)
            response["resources"]["graphql"]["reset"] = value
            bodies.append(json.dumps(response))

        for body in bodies:
            with self.subTest(body=body):
                result = self.sample(body)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(result.stderr, b"GitHub rate limit unavailable\n")
