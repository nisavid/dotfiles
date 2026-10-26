from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "home"
TEMPLATE = SOURCE / "run_before_install-zsh-config.zsh.tmpl"
UPSTREAM = "https://github.com/nisavid/zsh-config"


class ZshConfigPinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.remote = self.root / "upstream"
        self.remote.mkdir()
        self.target = self.home / ".config/zsh"
        self.env = os.environ | {
            "HOME": str(self.home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "Zsh pin fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Zsh pin fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        }
        self.git(self.remote, "init", "--quiet", "--initial-branch=main")
        (self.remote / "zshenv.zsh").write_text('export ZSH_PIN_LOADED=reviewed\n')
        (self.remote / "startup.zsh").write_text('export ZSH_PIN_GUI=reviewed\n')
        (self.remote / ".zprofile").symlink_to("zshenv.zsh")
        self.commit("reviewed")
        self.pin = self.git(self.remote, "rev-parse", "HEAD").stdout.strip()
        self.digest = self.archive_digest(self.pin)

    def git(self, directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
             "-C", str(directory), *args],
            env=self.env, text=True, capture_output=True, check=True,
        )

    def commit(self, message: str) -> None:
        self.git(self.remote, "add", ".")
        self.git(self.remote, "commit", "--quiet", "-m", message)

    def archive_digest(self, revision: str) -> str:
        archive = subprocess.run(
            ["git", "-C", str(self.remote), "-c", "tar.umask=0002",
             "archive", "--format=tar", revision],
            env=self.env, capture_output=True, check=True,
        ).stdout
        return hashlib.sha256(archive).hexdigest()

    def render(self, revision: str | None = None, digest: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["chezmoi", "-S", str(SOURCE), "execute-template", "--override-data",
             json.dumps({"chezmoi": {"homeDir": str(self.home)}, "zshConfig": {
                 "releaseCommit": self.pin if revision is None else revision,
                 "gitArchiveSha256": self.digest if digest is None else digest,
             }})],
            input=TEMPLATE.read_text(), env=self.env, text=True, capture_output=True,
        )

    def apply(self, revision: str | None = None, digest: str | None = None) -> subprocess.CompletedProcess[str]:
        rendered = self.render(revision, digest)
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertTrue(rendered.stdout.startswith("#!/bin/zsh -f\n"))
        # Substitute only the fixture transport, never a product bypass switch.
        script = self.root / "install-zsh-config"
        script.write_text(rendered.stdout.replace(UPSTREAM, self.remote.as_uri()))
        return subprocess.run(
            ["zsh", "-f", str(script)], env=self.env, text=True, capture_output=True,
        )

    def assert_success(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_branch_advance_cannot_change_fresh_or_repeated_apply(self) -> None:
        (self.remote / "zshenv.zsh").write_text('export ZSH_PIN_LOADED=unreviewed\n')
        (self.remote / "startup.zsh").write_text('export ZSH_PIN_GUI=unreviewed\n')
        self.commit("unreviewed branch advance")
        self.assert_success(self.apply())
        self.assertEqual(self.git(self.target, "rev-parse", "HEAD").stdout.strip(), self.pin)
        self.assertTrue((self.target / ".git").is_dir())
        zprofile = self.target / ".zprofile"
        before = zprofile.lstat()
        (self.target / "profile.d").mkdir()
        local_profile = self.target / "profile.d/personal.local.zshrc"
        local_profile.write_text("# host-local profile\n")
        self.assert_success(self.apply())
        after = zprofile.lstat()
        self.assertEqual((before.st_ino, before.st_mtime_ns, before.st_mode),
                         (after.st_ino, after.st_mtime_ns, after.st_mode))
        self.assertEqual(os.readlink(zprofile), "zshenv.zsh")
        self.assertEqual(local_profile.read_text(), "# host-local profile\n")
        self.assertEqual(self.git(self.target, "status", "--porcelain", "--untracked-files=no").stdout, "")
        (self.home / ".zshenv").symlink_to(".config/zsh/zshenv.zsh")
        shell = subprocess.run(
            ["zsh", "-c", '[[ $ZSH_PIN_LOADED == reviewed ]]'],
            env=self.env, text=True, capture_output=True,
        )
        self.assert_success(shell)
        gui = subprocess.run(
            ["zsh", "-f", "-c", 'source "$HOME/.config/zsh/startup.zsh" launcher darwin; '
             '[[ $ZSH_PIN_GUI == reviewed ]]'],
            env=self.env, text=True, capture_output=True,
        )
        self.assert_success(gui)

    def test_pin_advance_preserves_git_and_local_profiles_and_removes_retired_files(self) -> None:
        self.assert_success(self.apply())
        metadata = (self.target / ".git").stat().st_ino
        local_profile = self.target / "personal.local.zsh"
        local_profile.write_text("# retain me\n")
        (self.remote / ".zprofile").unlink()
        (self.remote / "zshenv.zsh").write_text('export ZSH_PIN_LOADED=next\n')
        self.commit("next reviewed release")
        next_pin = self.git(self.remote, "rev-parse", "HEAD").stdout.strip()
        self.assert_success(self.apply(next_pin, self.archive_digest(next_pin)))
        self.assertEqual((self.target / ".git").stat().st_ino, metadata)
        self.assertEqual(local_profile.read_text(), "# retain me\n")
        self.assertFalse((self.target / ".zprofile").is_symlink())
        self.assertEqual(self.git(self.target, "rev-parse", "HEAD").stdout.strip(), next_pin)

    def test_chezmoi_runs_the_pin_hook_before_binding_shell_startup(self) -> None:
        source = self.root / "source"
        source.mkdir()
        rendered = self.render()
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        (source / "run_before_install-zsh-config.zsh").write_text(
            rendered.stdout.replace(UPSTREAM, self.remote.as_uri())
        )
        (source / "symlink_dot_zshenv").write_text(".config/zsh/zshenv.zsh\n")
        result = subprocess.run(
            ["chezmoi", "-S", str(source), "-D", str(self.home),
             "-c", str(self.root / "chezmoi.toml"), "--cache", str(self.root / "cache"),
             "--persistent-state", str(self.root / "state.boltdb"), "--no-tty", "apply"],
            env=self.env, text=True, capture_output=True,
        )
        self.assert_success(result)
        self.assertTrue((self.home / ".zshenv").is_symlink())
        self.assertEqual(self.git(self.target, "rev-parse", "HEAD").stdout.strip(), self.pin)

    def test_untracked_checkout_collision_is_preserved(self) -> None:
        self.assert_success(self.apply())
        collision = self.target / "future.zsh"
        collision.write_text("# host-local work\n")
        (self.remote / "future.zsh").write_text("# next upstream file\n")
        self.commit("next release with conflicting path")
        next_pin = self.git(self.remote, "rev-parse", "HEAD").stdout.strip()
        result = self.apply(next_pin, self.archive_digest(next_pin))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(collision.read_text(), "# host-local work\n")
        self.assertEqual(self.git(self.target, "rev-parse", "HEAD").stdout.strip(), self.pin)

    def test_ignored_local_profile_collision_is_preserved(self) -> None:
        (self.remote / ".gitignore").write_text("*.local.zsh\nprofile.d/*.local.zshrc\n")
        self.commit("profile ignore rules")
        initial_pin = self.git(self.remote, "rev-parse", "HEAD").stdout.strip()
        self.assert_success(self.apply(initial_pin, self.archive_digest(initial_pin)))
        (self.target / "profile.d").mkdir()
        names = ("personal.local.zsh", "profile.d/personal.local.zshrc")
        for name in names:
            (self.target / name).write_text("# host-local work\n")
            (self.remote / name).parent.mkdir(exist_ok=True)
            (self.remote / name).write_text("# next upstream file\n")
            self.git(self.remote, "add", "--force", name)
        self.commit("next release with ignored path collision")
        next_pin = self.git(self.remote, "rev-parse", "HEAD").stdout.strip()
        result = self.apply(next_pin, self.archive_digest(next_pin))
        self.assertNotEqual(result.returncode, 0)
        for name in names:
            self.assertEqual((self.target / name).read_text(), "# host-local work\n")
        self.assertEqual(self.git(self.target, "rev-parse", "HEAD").stdout.strip(), initial_pin)

    def test_checksum_mismatch_never_installs_or_replaces_startup(self) -> None:
        fresh = self.apply(digest="0" * 64)
        self.assertNotEqual(fresh.returncode, 0)
        self.assertIn("checksum mismatch", fresh.stderr)
        self.assertFalse(self.target.exists())
        self.assert_success(self.apply())
        before = (self.target / "zshenv.zsh").read_bytes()
        (self.remote / "zshenv.zsh").write_text("# changed upstream\n")
        self.commit("changed upstream")
        next_pin = self.git(self.remote, "rev-parse", "HEAD").stdout.strip()
        bad = self.apply(next_pin, self.digest)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("checksum mismatch", bad.stderr)
        self.assertEqual((self.target / "zshenv.zsh").read_bytes(), before)
        self.assertEqual(self.git(self.target, "rev-parse", "HEAD").stdout.strip(), self.pin)

    def test_missing_commit_fails_without_installing(self) -> None:
        self.assertNotEqual(self.apply(revision="f" * 40).returncode, 0)
        self.assertFalse(self.target.exists())

    def test_dirty_tracked_and_staged_files_are_preserved(self) -> None:
        self.assert_success(self.apply())
        entrypoint = self.target / "zshenv.zsh"
        entrypoint.write_text("# local work\n")
        for staged in (False, True):
            with self.subTest(staged=staged):
                if staged:
                    self.git(self.target, "add", "zshenv.zsh")
                result = self.apply()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("tracked local changes", result.stderr)
                self.assertEqual(entrypoint.read_text(), "# local work\n")

    def test_symlink_target_is_not_followed(self) -> None:
        self.target.parent.mkdir()
        self.target.symlink_to(self.remote, target_is_directory=True)
        result = self.apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("standalone Git checkout", result.stderr)
        self.assertTrue(self.target.is_symlink())

    def test_malformed_pin_and_digest_fail_before_script_execution(self) -> None:
        for revision in ("main", "a" * 39, "A" * 40, "a" * 41):
            with self.subTest(revision=revision):
                self.assertNotEqual(self.render(revision=revision).returncode, 0)
        for digest in ("", "0" * 63, "G" * 64):
            with self.subTest(digest=digest):
                self.assertNotEqual(self.render(digest=digest).returncode, 0)

    def test_production_pin_has_no_floating_external(self) -> None:
        pin = tomllib.loads((SOURCE / ".chezmoidata/zsh-config.toml").read_text())["zshConfig"]
        self.assertRegex(pin["releaseCommit"], r"^[0-9a-f]{40}$")
        self.assertRegex(pin["gitArchiveSha256"], r"^[0-9a-f]{64}$")
        self.assertFalse((SOURCE / ".chezmoiexternals/zsh-config.toml").exists())


if __name__ == "__main__":
    unittest.main()
