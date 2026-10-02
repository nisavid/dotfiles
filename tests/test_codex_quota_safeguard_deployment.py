"""Disposable chezmoi bindings; no live Codex, account, or systemd operations."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    '.chezmoidata/codex-quota-safeguard.toml',
    '.chezmoitemplates/codex-quota-safeguard-selection.tmpl',
    '.chezmoiexternals/codex-quota-safeguard.toml.tmpl',
    'private_dot_local/bin/executable_codex-quota-safeguard.tmpl',
    'dot_config/systemd/user/codex-usage-safeguard.service.tmpl',
    '.chezmoiignore',
)
COMMIT = '0123456789abcdef0123456789abcdef01234567'


@unittest.skipUnless(shutil.which('chezmoi'), 'chezmoi is required')
class SafeguardDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.source = self.root / 'source'
        self.home.mkdir()
        self.source.mkdir()
        for name in FILES:
            dest = self.source / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / 'home' / name, dest)
        self.config = self.root / 'chezmoi.toml'
        self.config.write_text('')
        self.env = {
            'HOME': str(self.home), 'PATH': os.environ['PATH'], 'LANG': 'C.UTF-8',
            'XDG_CONFIG_HOME': str(self.home / '.config'),
            'XDG_DATA_HOME': str(self.home / '.local/share'),
            'XDG_STATE_HOME': str(self.home / '.local/state'),
            'XDG_CACHE_HOME': str(self.root / 'cache'),
            'PYTHONDONTWRITEBYTECODE': '1',
        }
        self.state = self.home / 'existing-state'
        self.state.mkdir(mode=0o700)
        self.lock = self.home / 'legacy-shared.lock'
        self.lock.write_text('')
        self.episode = self.state / 'daybreak.json'
        self.episode.write_text('{"episode":"fixture-episode","delivery":"outcome_unknown"}\n')
        self.private = self.home / 'existing-config.json'
        self.private.write_text(json.dumps({
            'stateDir': str(self.state), 'sharedLock': str(self.lock),
            'nativeContext': {'fixture': True}, 'accounts': [], 'policy': {},
        }))
        self.private.chmod(0o600)
        self.archive = self.root / 'agents.tar.gz'
        with tarfile.open(self.archive, 'w:gz') as archive:
            for filename in ('controller.py', 'companion.py', 'status.py'):
                payload = ('import json, sys\nprint(json.dumps({"entry": ' + repr(filename)
                           + ', "argv": sys.argv[1:]}))\n').encode()
                member = tarfile.TarInfo('agents-' + COMMIT + '/tooling/codex-usage-safeguard/' + filename)
                member.size = len(payload)
                member.mode = 0o644
                archive.addfile(member, io.BytesIO(payload))
        self.digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        # Rewrite only the disposable source's origin, never production selection.
        external = self.source / '.chezmoiexternals/codex-quota-safeguard.toml.tmpl'
        external.write_text(external.read_text().replace(
            'https://github.com/nisavid/agents/archive/{{ $selection.releaseCommit }}.tar.gz',
            self.archive.as_uri(),
        ))

    def chezmoi(self, *args):
        return subprocess.run([
            shutil.which('chezmoi'), '--source', str(self.source), '--destination', str(self.home),
            '--config', str(self.config), '--cache', str(self.root / 'cache'),
            '--persistent-state', str(self.root / 'state.boltdb'), '--no-tty', *args,
        ], env=self.env, cwd=self.root, text=True, capture_output=True)

    def select(self, **overrides):
        data = dict(enabled=True, releaseCommit=COMMIT, archiveSha256=self.digest,
                    configFile=str(self.private), stateDir=str(self.state), sharedLock=str(self.lock))
        data.update(overrides)
        (self.source / '.chezmoidata/codex-quota-safeguard.toml').write_text(
            '[codexQuotaSafeguard]\n' + ''.join(f'{key} = {json.dumps(value)}\n' for key, value in data.items()))

    def snapshot(self):
        return {str(p): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino, p.stat().st_mode & 0o777)
                for p in (self.private, self.lock, self.episode)}

    def test_disabled_default_leaves_existing_bindings_and_state_untouched(self):
        old_launcher = self.home / '.local/bin/codex-quota-safeguard'
        old_launcher.parent.mkdir(parents=True)
        old_launcher.write_text('existing managed elsewhere\n')
        old_unit = self.home / '.config/systemd/user/codex-usage-safeguard.service'
        old_unit.parent.mkdir(parents=True)
        old_unit.write_text('existing watcher unit\n')
        before = self.snapshot()
        result = self.chezmoi('apply', '--force')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(old_launcher.read_text(), 'existing managed elsewhere\n')
        self.assertEqual(old_unit.read_text(), 'existing watcher unit\n')
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.home / '.local/share/codex-quota-safeguard').exists())

    def test_unsupported_platform_omits_targets_and_archive(self):
        self.select()
        for platform in ('darwin', 'windows'):
            result = self.chezmoi('execute-template', '--override-data',
                json.dumps({'chezmoi': {'os': platform}}),
                '{{ includeTemplate "codex-quota-safeguard-selection.tmpl" . }}')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(json.loads(result.stdout)['enabled'])
            for template in (FILES[2], '.chezmoiignore'):
                rendered = self.chezmoi('execute-template', '--override-data',
                    json.dumps({'chezmoi': {'os': platform}}),
                    (self.source / template).read_text())
                self.assertEqual(rendered.returncode, 0, rendered.stderr)
                if template == FILES[2]:
                    self.assertEqual(rendered.stdout.strip(), '')
                else:
                    self.assertIn('.local/bin/codex-quota-safeguard', rendered.stdout)
                    self.assertIn('.config/systemd/user/codex-usage-safeguard.service', rendered.stdout)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux bindings')
    def test_apply_installs_pin_without_activation_and_preserves_state(self):
        self.select()
        before = self.snapshot()
        for _ in range(2):
            result = self.chezmoi('apply', '--force')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.snapshot(), before)
        unit_root = self.home / '.config/systemd/user'
        self.assertEqual([p.name for p in unit_root.iterdir()], ['codex-usage-safeguard.service'])
        unit = (unit_root / 'codex-usage-safeguard.service').read_text()
        self.assertIn('codex-quota-safeguard" controller', unit)
        self.assertNotIn('EnvironmentFile=', unit)
        self.assertNotIn('PIPE_PATH', unit)
        self.assertFalse((self.home / '.codex').exists())
        launcher = self.home / '.local/bin/codex-quota-safeguard'
        self.assertTrue(os.access(launcher, os.X_OK))
        self.assertEqual(self.private.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.state.stat().st_uid, os.geteuid())
        for mode in ('controller', 'companion', 'status'):
            result = subprocess.run([str(launcher), mode], env=self.env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {
                'entry': mode + '.py', 'argv': ['--config', str(self.private), '--state-dir', str(self.state)]})
        self.assertEqual(self.snapshot(), before)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux bindings')
    def test_dry_run_leaves_target_bindings_and_ledger_untouched(self):
        self.select()
        before = self.snapshot()
        result = self.chezmoi('apply', '--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.home / '.local/bin/codex-quota-safeguard').exists())
        self.assertFalse((self.home / '.config/systemd/user/codex-usage-safeguard.service').exists())
        self.assertFalse((self.home / '.local/share/codex-quota-safeguard').exists())

    @unittest.skipUnless(sys.platform == 'linux', 'Linux bindings')
    def test_launch_rejects_rebinding_and_missing_existing_state(self):
        self.select()
        self.assertEqual(self.chezmoi('apply', '--force').returncode, 0)
        launcher = self.home / '.local/bin/codex-quota-safeguard'
        data = json.loads(self.private.read_text())
        for key in ('stateDir', 'sharedLock'):
            changed = data | {key: str(self.home / 'other')}
            self.private.write_text(json.dumps(changed))
            result = subprocess.run([str(launcher), 'controller'], env=self.env, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(key, result.stderr)
        missing_state = dict(data)
        del missing_state['stateDir']
        self.private.write_text(json.dumps(missing_state))
        result = subprocess.run([str(launcher), 'controller'], env=self.env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('stateDir', result.stderr)
        self.private.write_text(json.dumps(data))
        self.lock.unlink()
        result = subprocess.run([str(launcher), 'companion'], env=self.env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.lock.exists())
        result = subprocess.run([str(launcher), 'controller', '--state-dir', str(self.root)], env=self.env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux bindings')
    def test_shared_lock_must_differ_from_the_state_observer_lock(self):
        self.lock = self.state / 'observer.lock'
        self.lock.write_text('')
        data = json.loads(self.private.read_text())
        data['sharedLock'] = str(self.lock)
        self.private.write_text(json.dumps(data))
        self.select()
        self.assertEqual(self.chezmoi('apply', '--force').returncode, 0)
        launcher = self.home / '.local/bin/codex-quota-safeguard'
        result = subprocess.run([str(launcher), 'controller'], env=self.env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('distinct', result.stderr)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux bindings')
    def test_shared_lock_hardlink_is_rejected_without_changing_state(self):
        observer_lock = self.state / 'observer.lock'
        os.link(self.lock, observer_lock)
        self.select()
        self.assertEqual(self.chezmoi('apply', '--force').returncode, 0)
        before = self.snapshot()
        launcher = self.home / '.local/bin/codex-quota-safeguard'
        for mode in ('controller', 'companion', 'status'):
            result = subprocess.run([str(launcher), mode], env=self.env, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('distinct', result.stderr)
            self.assertEqual(result.stdout, '')
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(self.lock.samefile(observer_lock))

    def test_machine_local_data_can_select_the_disabled_public_default(self):
        self.config.write_text('[data.codexQuotaSafeguard]\n' + ''.join(
            f'{key} = {json.dumps(value)}\n' for key, value in dict(
                enabled=True, releaseCommit=COMMIT, archiveSha256=self.digest,
                configFile=str(self.private), stateDir=str(self.state), sharedLock=str(self.lock),
            ).items()))
        result = self.chezmoi('execute-template', '--override-data', '{"chezmoi":{"os":"linux"}}',
            '{{ includeTemplate "codex-quota-safeguard-selection.tmpl" . }}')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['enabled'])

    @unittest.skipUnless(sys.platform == 'linux', 'Linux bindings')
    def test_upgrade_and_code_rollback_keep_the_live_ledger_and_old_release(self):
        before = self.snapshot()
        releases = self.home / '.local/share/codex-quota-safeguard/releases'
        for commit in (COMMIT, 'f' * 40, COMMIT):
            self.select(releaseCommit=commit)
            result = self.chezmoi('apply', '--force')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((releases / commit / 'tooling/codex-usage-safeguard/controller.py').is_file())
            self.assertEqual(self.snapshot(), before)
        self.assertTrue((releases / ('f' * 40)).is_dir())
        self.assertIn(COMMIT, (self.home / '.local/bin/codex-quota-safeguard').read_text())

    def test_enabled_requires_complete_pin_and_paths(self):
        for field in ('releaseCommit', 'archiveSha256', 'configFile', 'stateDir', 'sharedLock'):
            self.select(**{field: ''})
            result = self.chezmoi('execute-template', '--override-data', '{"chezmoi":{"os":"linux"}}',
                '{{ includeTemplate "codex-quota-safeguard-selection.tmpl" . }}')
            self.assertNotEqual(result.returncode, 0, field)
            self.assertIn(field, result.stderr)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux bindings')
    def test_bad_archive_digest_never_changes_existing_state(self):
        self.select(archiveSha256='0' * 64)
        before = self.snapshot()
        result = self.chezmoi('apply', '--force')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.snapshot(), before)
