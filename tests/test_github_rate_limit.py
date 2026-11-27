import json
from copy import deepcopy
from pathlib import Path
import shutil
import shlex
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
    login = "config get user --host github.com"
    quota = "api --hostname github.com rate_limit"

    def sample(self, body, status=0, before="fixture", after="fixture", calls=None,
               profile_header="# secret-exec-github-login=fixture\n",
               hosts_before=b"github.com:\n    user: fixture\n", hosts_after=None):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            hosts = fixture / ".config/gh/hosts.yml"
            hosts.parent.mkdir(parents=True)
            hosts.write_bytes(hosts_before)
            if hosts_after is not None:
                (fixture / "new-hosts").write_bytes(hosts_after)
            profile = fixture / ".config/secret-exec/profiles/github.env"
            profile.parent.mkdir(parents=True)
            if profile_header is not None:
                profile.write_text(profile_header)
            for name, value in (("before", before), ("after", after)):
                if value is not None:
                    (fixture / name).write_text(value + "\n")
            (fixture / "response").write_text(body)
            gh = fixture / "gh"
            gh.write_text(f"""#!/bin/sh
printf '%s\\n' "$*" >> calls
echo 'unexpected diagnostic' >&2
case "$*" in
  '{self.login}')
    echo 'updated by a config migration' >> "$GH_CONFIG_DIR/hosts.yml"
    if [ -f requested ]; then /bin/cat after; else /bin/cat before; fi;;
  '{self.quota}')
    : > requested
    echo 'updated by an API migration' >> "${{GH_CONFIG_DIR:-$HOME/.config/gh}}/hosts.yml"
    if [ -f new-hosts ]; then /bin/mv new-hosts .config/gh/hosts.yml; fi
    /bin/cat response
    exit {status};;
  *) exit 2;;
esac
""")
            gh.chmod(0o755)
            result = subprocess.run(
                [sys.executable, str(SAMPLER)], cwd=fixture, capture_output=True,
                env={"PATH": tmp, "HOME": tmp}, timeout=5,
            )
            if calls is None:
                calls = [self.login, self.quota] if status else [self.login, self.quota, self.login]
            log = fixture / "calls"
            self.assertEqual(log.read_text().splitlines() if log.exists() else [], calls)
            self.assertEqual(hosts.read_bytes(), hosts_before if hosts_after is None else hosts_after)
            return result

    def test_token_key_in_either_snapshot_stops_the_sample(self):
        for unsafe in (
            b"github.com:\n    oauth_token: would-be-value\n",
            b'{"github.com":{"users":{"fixture":{"oauth_token":""}}}}',
            b'{"github.com":{"oauth_\\u0074oken":"would-be-value"}}',
        ):
            for phase in ("before", "after"):
                with self.subTest(phase=phase, config=unsafe):
                    calls = [] if phase == "before" else [self.login, self.quota]
                    result = self.sample(json.dumps(RESPONSE), calls=calls, **{"hosts_" + phase: unsafe})
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, b"")
                    self.assertEqual(result.stderr, b"GitHub rate limit unavailable\n")

    def test_bad_login_discards_sample_and_never_retries(self):
        for bad in ("different", "", None):
            for phase in ("before", "after"):
                with self.subTest(phase=phase, login=bad):
                    calls = [self.login] if phase == "before" else [self.login, self.quota, self.login]
                    result = self.sample(json.dumps(RESPONSE), calls=calls, **{phase: bad})
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, b"")
                    self.assertEqual(result.stderr, b"GitHub rate limit unavailable\n")

    def test_missing_or_ambiguous_deploy_binding_stops_before_gh(self):
        for header in (None, "", "# secret-exec-github-login=\n",
                       "# secret-exec-github-login=fixture\n" * 2):
            with self.subTest(header=header):
                result = self.sample(json.dumps(RESPONSE), profile_header=header, calls=[])
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(result.stderr, b"GitHub rate limit unavailable\n")

    @unittest.skipUnless(shutil.which("gh"), "GitHub CLI required for its configuration format")
    def test_real_config_uses_only_the_host_login_and_observes_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config"
            gh_dir = root / "gh-config"
            gh_dir.mkdir()
            profile = config / "secret-exec/profiles/github.env"
            profile.parent.mkdir(parents=True)
            template = ROOT / "home/dot_config/private_secret-exec/private_profiles/private_github.env.tmpl"
            profile.write_bytes(subprocess.check_output(
                [shutil.which("chezmoi"), "-S", tmp, "execute-template",
                 "--override-data-file", str(ROOT / "tests/fixtures/secret-exec-public.toml"),
                 "--override-data", '{"chezmoi":{"hostname":"second-host"}}'],
                input=template.read_bytes(), env={"HOME": tmp, "PATH": "/usr/bin:/bin"},
            ))
            (gh_dir / "config.yml").write_text("version: 1\nuser: fixture-secondary\n")
            real_gh = shlex.quote(shutil.which("gh"))
            stub = root / "gh"
            stub.write_text(f"""#!/bin/sh
case "$*" in
  '{self.login}') exec {real_gh} "$@";;
  '{self.quota}')
    : > requested
    /bin/mv replacement gh-config/hosts.yml
    /bin/cat response;;
  *) exit 2;;
esac
""")
            stub.chmod(0o755)
            (root / "response").write_text(json.dumps(RESPONSE))
            for before, after, ok in (
                ("fixture-secondary", "FIXTURE-SECONDARY", True),
                ("fixture-secondary", "other", False),
                ("", "fixture-secondary", False),
            ):
                with self.subTest(before=before, after=after):
                    requested = root / "requested"
                    requested.unlink(missing_ok=True)
                    for target, login in ((gh_dir / "hosts.yml", before), (root / "replacement", after)):
                        host = {"user": login} if login else {}
                        target.write_text(json.dumps({"github.com": host}))
                    result = subprocess.run(
                        [sys.executable, str(SAMPLER)], cwd=root, capture_output=True,
                        env={"HOME": tmp, "PATH": tmp, "XDG_CONFIG_HOME": str(config),
                             "GH_CONFIG_DIR": str(gh_dir)}, timeout=10,
                    )
                    self.assertEqual(requested.exists(), bool(before))
                    self.assertEqual(result.returncode == 0, ok, result.stderr)
                    expected_line = b"5000 0 5000 1795800600 7000 6983 17 1795801200\n" if ok else b""
                    self.assertEqual(result.stdout, expected_line)
                    self.assertEqual(result.stderr, b"" if ok else b"GitHub rate limit unavailable\n")

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
    def verify(self, records, cursor="test-cursor", active=True, listed=True, defect=None, activate=True):
        # The verification begins at epoch second 550; the next firings are 600 and 900.
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp)

            def command(name, body):
                path = fixture / name
                path.write_text("#!/bin/sh\n" + body)
                path.chmod(0o755)

            deployed = fixture / ".local/bin/github-rate-limit"
            deployed.parent.mkdir(parents=True)
            deployed.write_bytes(b"old sampler" if defect == "sampler" else SAMPLER.read_bytes())
            deployed.chmod(0o644 if defect == "non-executable" else 0o755)
            unit_dir = fixture / ".config/systemd/user"
            wants = unit_dir / "timers.target.wants/github-rate-limit.timer"
            wants.parent.mkdir(parents=True)
            service = unit_dir / "github-rate-limit.service"
            timer_file = unit_dir / "github-rate-limit.timer"
            for unit in (service, timer_file):
                src = ROOT / "home/dot_config/systemd/user" / unit.name
                unit.write_bytes(b"old unit" if defect == unit.suffix else src.read_bytes())
            if defect != "missing link":
                wants.symlink_to(Path("..") / (service.name if defect == "wrong link" else timer_file.name))
            status = 'printf "%s\\n" "$@" > status-args\n'
            if defect == "pending apply":
                status += 'echo " M modified"\n'
            command("chezmoi", status + ("exit 1\n" if defect == "status error" else "exit 0\n"))
            for tool in ("jq", "awk", "cmp", "dirname"):
                (fixture / tool).symlink_to(shutil.which(tool))
            command("date", 'echo 550\n')
            command("sleep", '[ -f captured ] && [ "$1" = 386 ] && : > elapsed\n')
            timer = "github-rate-limit" if listed else "unrelated"
            command("systemctl", f"""case "$*" in
  '--user daemon-reload'|'--user start github-rate-limit.timer') echo "$*" >> activation;;
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
            result = subprocess.run(
                ["/bin/bash", str(ROOT / "tests/verify-github-rate-limit-timer.sh")]
                + (["--activate"] if activate else []),
                cwd=fixture, env={"HOME": tmp, "PATH": tmp},
                capture_output=True, timeout=5,
            )
            activation = fixture / "activation"
            actions = activation.read_text().splitlines() if activation.exists() else []
            self.assertEqual(actions, [] if defect or not activate else ["--user daemon-reload", "--user start github-rate-limit.timer"])
            if not defect or defect in ("pending apply", "status error"):
                self.assertEqual((fixture / "status-args").read_text().splitlines(), [
                    "--source", str(ROOT / "home"), "status", "--",
                    str(deployed), str(service), str(timer_file), str(wants),
                ])
            return result

    def test_only_two_distinct_numeric_samples_in_their_scheduled_windows_pass(self):
        sample = "5 0 5 101 8 2 6 102"
        first = (600, sample, "a" * 32)
        second = (935, sample, "b" * 32)
        accepted = self.verify([first, second])
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(self.verify([first, second], activate=False).returncode, 0)
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

    def test_requires_current_sampler_active_listed_timer_and_cursor(self):
        records = [(t, "5 0 5 101 8 2 6 102", i * 32) for t, i in [(601, "a"), (901, "b")]]
        for missing in ({"active": False}, {"listed": False}, {"cursor": ""}):
            with self.subTest(missing=missing):
                self.assertNotEqual(self.verify(records, **missing).returncode, 0)

    def test_installation_defects_prevent_reload_and_start_even_with_good_samples(self):
        records = [(t, "5 0 5 101 8 2 6 102", i * 32) for t, i in [(601, "a"), (901, "b")]]
        for defect in ("sampler", "non-executable", ".service", ".timer", "missing link",
                       "wrong link", "pending apply", "status error"):
            with self.subTest(defect=defect):
                self.assertNotEqual(self.verify(records, defect=defect).returncode, 0)
