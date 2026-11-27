import json
from copy import deepcopy
from pathlib import Path
import shutil
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


class JournalCadenceTest(unittest.TestCase):
    def verify(self, records, cursor="test-cursor", active=True, listed=True):
        # The verification begins at epoch second 550; the next firings are 600 and 900.
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp)

            def command(name, body):
                path = fixture / name
                path.write_text("#!/bin/sh\n" + body)
                path.chmod(0o755)

            for tool in ("jq", "awk"):
                (fixture / tool).symlink_to(shutil.which(tool))
            command("date", 'echo 550\n')
            command("sleep", '[ -f captured ] && [ "$1" = 386 ] && : > elapsed\n')
            timer = "github-rate-limit" if listed else "unrelated"
            command("systemctl", f"""case "$*" in
  '--user is-active --quiet github-rate-limit.timer') exit {0 if active else 1};;
  '--user list-timers --full --no-legend --no-pager github-rate-limit.timer')
    echo 'NEXT LEFT LAST PASSED {timer}.timer {timer}.service';;
  *) exit 2;;
esac
""")
            command("journalctl", """case "$*" in
  '--user -b -n 1 -o json --output-fields=__CURSOR') : > captured && /bin/cat cursor;;
  '--user -b --after-cursor=test-cursor _SYSTEMD_USER_UNIT=github-rate-limit.service -o json --output-fields=MESSAGE,_SYSTEMD_INVOCATION_ID')
    [ -f elapsed ] && /bin/cat records;;
  *) exit 2;;
esac
""")
            (fixture / "cursor").write_text(json.dumps({"__CURSOR": cursor}))
            (fixture / "records").write_text("\n".join(json.dumps({
                "__REALTIME_TIMESTAMP": str(seconds * 1_000_000),
                "MESSAGE": message,
                "_SYSTEMD_INVOCATION_ID": invocation,
            }) for seconds, message, invocation in records))
            return subprocess.run(
                ["/bin/bash", str(ROOT / "tests/verify-github-rate-limit-timer.sh")],
                cwd=fixture, env={"HOME": tmp, "PATH": tmp},
                capture_output=True, timeout=5,
            )

    def test_only_two_distinct_numeric_samples_in_their_scheduled_windows_pass(self):
        sample = "5 0 5 101 8 2 6 102"
        first = (600, sample, "a" * 32)
        second = (935, sample, "b" * 32)
        accepted = self.verify([first, second])
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        for reason, records in {
            "one second apart across a boundary": [(899, *first[1:]), (900, *second[1:])],
            "nearly ten minutes apart": [first, (1199, *second[1:])],
            "stale pair": [(300, *first[1:]), (600, *second[1:])],
            "missing firing": [first],
            "duplicate sample": [first, first, second],
            "one service invocation": [first, (905, sample, first[2])],
            "error instead of counters": [first, (930, "unavailable", second[2])],
            "extra text": [first, (910, sample + "\n", second[2])],
        }.items():
            with self.subTest(reason=reason):
                self.assertNotEqual(self.verify(records).returncode, 0)

    def test_requires_an_active_listed_timer_and_a_cursor(self):
        records = [(t, "5 0 5 101 8 2 6 102", i * 32) for t, i in [(601, "a"), (901, "b")]]
        for missing in ({"active": False}, {"listed": False}, {"cursor": ""}):
            with self.subTest(missing=missing):
                self.assertNotEqual(self.verify(records, **missing).returncode, 0)
