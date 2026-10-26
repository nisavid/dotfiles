from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "home"
ZSH_EXTERNAL = SOURCE / ".chezmoiexternals/zsh-config.toml"
ZSH_ARCHIVE_FILES = {
    "zshenv.zsh": (b'export ZDOTDIR="$HOME/.config/zsh"\nZSHENV_FIXTURE_LOADED=yes\n', 0o644),
    "zprofile.zsh": (b"ZPROFILE_FIXTURE_LOADED=yes\n", 0o644),
    "zshrc.zsh": (
        b'for fragment in "$ZDOTDIR"/zshrc.d/*.zsh(N); do source "$fragment"; done\n',
        0o644,
    ),
    "zshrc.d/fixture.zsh": (b"ZSHRC_FIXTURE_LOADED=yes\n", 0o644),
    "dot_literal.zsh": (b"LITERAL_FILENAME_FIXTURE_LOADED=yes\n", 0o644),
    "executable_literal.zsh": (b"#!/usr/bin/env zsh\nexit 0\n", 0o755),
    "private_literal.bin": (b"\x00\xff\r\nliteral archive bytes\n", 0o644),
}
ZSH_ARCHIVE_SYMLINKS = {
    ".zprofile": "zprofile.zsh",
    ".zshrc": "zshrc.zsh",
    "symlink_literal.zsh": "dot_literal.zsh",
}
HINDSIGHT_SOURCE_ROOT = SOURCE / "dot_config/private_hindsight-control-plane"
HINDSIGHT_FIXTURE = ROOT / "tests/fixtures/hindsight-public.toml"
SECRET_EXEC_SOURCE_ROOT = SOURCE / "dot_config/private_secret-exec"
SECRET_EXEC_FIXTURE = ROOT / "tests/fixtures/secret-exec-public.toml"
PR_CREATOR_SOURCE = (
    SOURCE
    / "dot_agents/skills/publishing-reviewable-prs/scripts"
    / "literal_create_reviewable_pr.py"
)
TEMP_ROOT = Path(tempfile.gettempdir()).resolve()
CATPPUCCIN_CONFIG_EXTERNALS = (
    "bat-catppuccin.toml.tmpl",
    "gitui-catppuccin.toml.tmpl",
    "glamour-catppuccin.toml.tmpl",
    "lazygit-catppuccin.toml.tmpl",
    "micro-catppuccin.toml.tmpl",
)
class ChezmoiSourceOwnershipTests(unittest.TestCase):
    def environment(
        self,
        root: Path,
        destination: Path,
    ) -> tuple[dict[str, str], list[str]]:
        runtime = root / "runtime"
        runtime.mkdir()
        config = runtime / "chezmoi.toml"
        environment = os.environ | {
            "HOME": str(destination),
            "XDG_CACHE_HOME": str(runtime / "cache"),
            "XDG_CONFIG_HOME": str(destination / ".config"),
            "XDG_DATA_HOME": str(destination / ".local/share"),
            "XDG_STATE_HOME": str(runtime / "state"),
            "CHEZMOI_CONFIG_FILE": str(config),
        }
        arguments = [
            "-D",
            str(destination),
            "-c",
            str(config),
            "--cache",
            str(runtime / "cache"),
            "--persistent-state",
            str(runtime / "state.boltdb"),
            "--no-tty",
        ]
        return environment, arguments

    def write_zsh_archive(
        self,
        archive: Path,
        replacements: dict[str, bytes] | None = None,
    ) -> None:
        files = ZSH_ARCHIVE_FILES | {
            name: (content, ZSH_ARCHIVE_FILES.get(name, (b"", 0o644))[1])
            for name, content in (replacements or {}).items()
        }
        with tarfile.open(archive, "w:gz") as output:
            for name, (content, mode) in files.items():
                member = tarfile.TarInfo(f"zsh-config-fixture/{name}")
                member.mode = mode
                member.size = len(content)
                output.addfile(member, io.BytesIO(content))
            for name, target in ZSH_ARCHIVE_SYMLINKS.items():
                member = tarfile.TarInfo(f"zsh-config-fixture/{name}")
                member.type = tarfile.SYMTYPE
                member.mode = 0o777
                member.linkname = target
                output.addfile(member)

    def zsh_external_fixture(
        self,
        root: Path,
    ) -> tuple[Path, Path, Path, dict[str, str], list[str]]:
        source = root / "source"
        destination = root / "home"
        source.mkdir()
        destination.mkdir()
        archive = root / "zsh-config.tar.gz"
        self.write_zsh_archive(archive)
        environment, arguments = self.environment(root, destination)

        # Exercise the deployed declaration. Only its transport and expected
        # digest change, so archive/checksum/extraction regressions reach apply.
        declaration = ZSH_EXTERNAL.read_text(encoding="utf-8")
        external = tomllib.loads(declaration)[".config/zsh"]
        self.assertEqual(external["type"], "archive")
        checksum = external["checksum"]["sha256"]
        declaration = declaration.replace(
            f'url = "{external["url"]}"', f'url = "{archive.as_uri()}"', 1
        ).replace(checksum, hashlib.sha256(archive.read_bytes()).hexdigest(), 1)
        externals = source / ".chezmoiexternals"
        externals.mkdir()
        (externals / "zsh-config.toml").write_text(declaration, encoding="utf-8")
        shutil.copy2(SOURCE / "symlink_dot_zshenv", source / "symlink_dot_zshenv")

        # An existing checkout may retain Git metadata, but apply must never
        # invoke Git to clone, fetch, or pull this dependency anymore.
        binary_directory = root / "bin"
        binary_directory.mkdir()
        git_trap = binary_directory / "git"
        git_trap.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$*" >> "$ZSH_FIXTURE_GIT_CALLS"\nexit 95\n',
            encoding="utf-8",
        )
        git_trap.chmod(0o755)
        environment |= {
            "PATH": f'{binary_directory}{os.pathsep}{environment["PATH"]}',
            "ZSH_FIXTURE_GIT_CALLS": str(root / "git-calls"),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        return source, destination, archive, environment, arguments

    def apply_zsh_external(
        self,
        source: Path,
        environment: dict[str, str],
        arguments: list[str],
        refresh: str = "never",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "chezmoi",
                "-S",
                str(source),
                *arguments,
                f"--refresh-externals={refresh}",
                "apply",
            ],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def zsh_tree_snapshot(self, directory: Path) -> dict[str, tuple[object, ...]]:
        snapshot = {}
        for path in directory.rglob("*"):
            metadata = path.lstat()
            contents = (
                os.readlink(path)
                if path.is_symlink()
                else path.read_bytes() if path.is_file() else None
            )
            snapshot[str(path.relative_to(directory))] = (
                stat.S_IFMT(metadata.st_mode),
                stat.S_IMODE(metadata.st_mode),
                contents,
                metadata.st_ino,
                metadata.st_mtime_ns,
            )
        return snapshot

    def assert_zsh_fixture_starts(self, environment: dict[str, str]) -> None:
        started = subprocess.run(
            [
                "zsh",
                "-d",
                "-l",
                "-i",
                "-c",
                '[[ $ZDOTDIR == "$HOME/.config/zsh" && '
                '${ZSHENV_FIXTURE_LOADED:-} == yes && '
                '${ZPROFILE_FIXTURE_LOADED:-} == yes && '
                '${ZSHRC_FIXTURE_LOADED:-} == yes ]] || exit 1; '
                'source "$ZDOTDIR/symlink_literal.zsh"; '
                '[[ ${LITERAL_FILENAME_FIXTURE_LOADED:-} == yes ]]',
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(started.returncode, 0, started.stderr)

    def test_zsh_pinned_archive_preserves_bytes_symlinks_and_startup(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temporary:
            root = Path(temporary)
            source, destination, _, environment, arguments = self.zsh_external_fixture(root)
            first_apply = self.apply_zsh_external(source, environment, arguments)
            self.assertEqual(first_apply.returncode, 0, first_apply.stderr)
            self.assertNotIn("inconsistent state", first_apply.stderr)

            installed = destination / ".config/zsh"
            self.assertFalse((installed / ".git").exists())
            for name, (content, mode) in ZSH_ARCHIVE_FILES.items():
                with self.subTest(name=name):
                    self.assertEqual((installed / name).read_bytes(), content)
                    self.assertEqual(stat.S_IMODE((installed / name).stat().st_mode), mode)
            for name, target in ZSH_ARCHIVE_SYMLINKS.items():
                with self.subTest(name=name):
                    self.assertTrue((installed / name).is_symlink())
                    self.assertEqual(os.readlink(installed / name), target)
            self.assertFalse((installed / ".literal.zsh").exists())
            self.assertEqual(os.readlink(destination / ".zshenv"), ".config/zsh/zshenv.zsh")
            self.assert_zsh_fixture_starts(environment)

            original = self.zsh_tree_snapshot(installed)
            original_zshenv = self.zsh_tree_snapshot(destination)[".zshenv"]
            for refresh in ("never", "always"):
                with self.subTest(refresh=refresh):
                    applied = self.apply_zsh_external(source, environment, arguments, refresh)
                    self.assertEqual(applied.returncode, 0, applied.stderr)
                    self.assertEqual(self.zsh_tree_snapshot(installed), original)
                    self.assertEqual(
                        self.zsh_tree_snapshot(destination)[".zshenv"], original_zshenv
                    )
                    self.assert_zsh_fixture_starts(environment)
            self.assertFalse(Path(environment["ZSH_FIXTURE_GIT_CALLS"]).exists())

    def test_zsh_archive_migration_preserves_git_profiles_and_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temporary:
            root = Path(temporary)
            source, destination, _, environment, arguments = self.zsh_external_fixture(root)
            installed = destination / ".config/zsh"
            installed.mkdir(parents=True)
            (installed / "zprofile.zsh").write_bytes(b"STALE_CHECKOUT=yes\n")
            # Use a real legacy checkout, including its independent local HEAD.
            git = shutil.which("git")
            self.assertIsNotNone(git)
            subprocess.run(
                [git, "init", "--quiet", "--initial-branch=host-local"],
                cwd=installed,
                env=environment,
                check=True,
            )
            subprocess.run(
                [
                    git,
                    # Newer Git can detach maintenance after commit; keep the
                    # fixture quiescent before snapshotting its metadata.
                    "-c", "maintenance.auto=false",
                    "-c", "commit.gpgsign=false",
                    "-c", "user.name=Chezmoi test",
                    "-c", "user.email=chezmoi-test@example.invalid",
                    "commit", "--quiet", "--allow-empty", "-m", "test: legacy checkout",
                ],
                cwd=installed,
                env=environment,
                check=True,
            )
            local_files = {
                "profiles/host-local.zsh": b"HOST_LOCAL_PROFILE=yes\n",
                "zshrc.d/host.local.zsh": b"HOST_LOCAL_FRAGMENT=yes\n",
                ".zcompdump": b"host-specific completion cache\n",
                "runtime/history": b"host-specific shell history\n",
            }
            for name, content in local_files.items():
                path = installed / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            local_links = {
                name: ZSH_ARCHIVE_SYMLINKS[name] for name in (".zprofile", ".zshrc")
            }
            for name, target in local_links.items():
                (installed / name).symlink_to(target)
            original_git = self.zsh_tree_snapshot(installed / ".git")
            before = self.zsh_tree_snapshot(installed)
            original_local = {name: before[name] for name in (*local_files, *local_links)}
            for refresh in ("never", "always"):
                with self.subTest(refresh=refresh):
                    applied = self.apply_zsh_external(source, environment, arguments, refresh)
                    self.assertEqual(applied.returncode, 0, applied.stderr)
                    self.assertEqual(self.zsh_tree_snapshot(installed / ".git"), original_git)
                    self.assertEqual(
                        (installed / "zprofile.zsh").read_bytes(),
                        ZSH_ARCHIVE_FILES["zprofile.zsh"][0],
                    )
                    after = self.zsh_tree_snapshot(installed)
                    for name, original in original_local.items():
                        self.assertEqual(after[name], original)
                    self.assert_zsh_fixture_starts(environment)
            self.assertFalse(Path(environment["ZSH_FIXTURE_GIT_CALLS"]).exists())

    def test_zsh_archive_checksum_rejects_changed_startup_and_added_fragment(self) -> None:
        attacks = {
            "changed startup": {
                "zprofile.zsh": b'print compromised > "$HOME/checksum-boundary-crossed"\n',
            },
            "added sourceable fragment": {
                "zshrc.d/alternate-startup.zsh":
                    b'print compromised > "$HOME/checksum-boundary-crossed"\n',
            },
        }
        for attack, replacements in attacks.items():
            with self.subTest(attack=attack), tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temporary:
                root = Path(temporary)
                source, destination, archive, environment, arguments = self.zsh_external_fixture(root)
                installed = destination / ".config/zsh"
                first_apply = self.apply_zsh_external(source, environment, arguments)
                self.assertEqual(first_apply.returncode, 0, first_apply.stderr)
                healthy = self.zsh_tree_snapshot(installed)
                self.write_zsh_archive(archive, replacements)

                rejected = self.apply_zsh_external(source, environment, arguments, "always")
                self.assertNotEqual(rejected.returncode, 0, rejected.stdout)
                self.assertIn("sha256 mismatch", rejected.stderr.lower())
                self.assertEqual(self.zsh_tree_snapshot(installed), healthy)
                self.assertFalse((installed / "zshrc.d/alternate-startup.zsh").exists())
                self.assert_zsh_fixture_starts(environment)
                self.assertFalse((destination / "checksum-boundary-crossed").exists())
                self.assertFalse(Path(environment["ZSH_FIXTURE_GIT_CALLS"]).exists())

    def test_full_source_init_and_scoped_apply_have_consistent_ownership(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "home"
            shutil.copytree(SOURCE, source)
            destination.mkdir()
            environment, arguments = self.environment(root, destination)

            initialized = subprocess.run(
                ["chezmoi", "-S", str(source), *arguments, "init"],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            self.assertNotIn("inconsistent state", initialized.stderr)

            applied = subprocess.run(
                [
                    "chezmoi",
                    "-S",
                    str(source),
                    *arguments,
                    "--source-path",
                    "--refresh-externals=never",
                    "apply",
                    "--parent-dirs",
                    str(source / "dot_config/bat/config"),
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertNotIn("inconsistent state", applied.stderr)
            self.assertEqual(
                (destination / ".config/bat/config").read_bytes(),
                (source / "dot_config/bat/config").read_bytes(),
            )

    def test_unbound_hindsight_is_ignored_and_preserves_existing_targets(self) -> None:
        sources = [
            *HINDSIGHT_SOURCE_ROOT.rglob("*.tmpl"),
            *(SOURCE / "private_dot_local/bin").glob("*hindsight*.tmpl"),
            *(SOURCE / "private_dot_local/lib/hindsight-runtime").rglob("*.tmpl"),
            *(SOURCE / "dot_agents/skills").glob("*hindsight*.tmpl"),
            *(SOURCE / ".chezmoitemplates").glob("*hindsight*.tmpl"),
            SOURCE / ".chezmoiignore",
            SOURCE / ".chezmoidata/hindsight.toml",
        ]
        for platform in ("linux", "darwin"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory(
                dir=TEMP_ROOT,
            ) as temporary:
                root = Path(temporary)
                source = root / "source"
                destination = root / "home"
                for original in sources:
                    copied = source / original.relative_to(SOURCE)
                    copied.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(original, copied)

                existing = (
                    destination / ".config/hindsight-control-plane/installation.json"
                )
                existing.parent.mkdir(parents=True)
                existing.write_bytes(b"unmanaged fixture\n")
                existing.chmod(0o600)
                environment, arguments = self.environment(root, destination)
                command = [
                    "chezmoi",
                    "-S",
                    str(source),
                    *arguments,
                    "--override-data",
                    '{"chezmoi":{"os":"' + platform + '"}}',
                    "--refresh-externals=never",
                ]
                managed = subprocess.run(
                    [*command, "managed"],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertNotIn("hindsight", managed.stdout)
                applied = subprocess.run(
                    [*command, "apply"],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(applied.returncode, 0, applied.stderr)
                self.assertEqual(existing.read_bytes(), b"unmanaged fixture\n")
                self.assertEqual(stat.S_IMODE(existing.stat().st_mode), 0o600)
                self.assertEqual(
                    {
                        path
                        for path in destination.rglob("*")
                        if path.is_file() or path.is_symlink()
                    },
                    {existing},
                )

    def test_hindsight_keeps_paths_bytes_and_private_modes(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temporary:
            root = Path(temporary)
            destination = root / "home"
            destination.mkdir()
            environment, arguments = self.environment(root, destination)
            sources = sorted(HINDSIGHT_SOURCE_ROOT.rglob("*.tmpl"))

            applied = subprocess.run(
                [
                    "chezmoi",
                    "-S",
                    str(SOURCE),
                    *arguments,
                    "--override-data",
                    '{"chezmoi":{"os":"darwin"}}',
                    "--override-data-file",
                    str(HINDSIGHT_FIXTURE),
                    "--source-path",
                    "--refresh-externals=never",
                    "apply",
                    "--parent-dirs",
                    *map(str, sources),
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertEqual(
                stat.S_IMODE((destination / ".config").stat().st_mode),
                0o755,
            )
            hindsight = destination / ".config/hindsight-control-plane"
            self.assertEqual(stat.S_IMODE(hindsight.stat().st_mode), 0o700)
            self.assertEqual(
                stat.S_IMODE((hindsight / "harnesses").stat().st_mode),
                0o700,
            )

            expected_targets = {
                Path(".config/hindsight-control-plane/installation.json"),
                Path(".config/hindsight-control-plane/inventory.json"),
                Path(".config/hindsight-control-plane/provider-runtime-policy.json"),
                Path(
                    ".config/hindsight-control-plane/harnesses/"
                    "claude-code-destination.json"
                ),
                Path(
                    ".config/hindsight-control-plane/harnesses/codex-destination.json"
                ),
                Path(
                    ".config/hindsight-control-plane/harnesses/cursor-destination.json"
                ),
            }
            actual_targets: set[Path] = set()
            for source in sources:
                target_path = subprocess.run(
                    [
                        "chezmoi",
                        "-S",
                        str(SOURCE),
                        *arguments,
                        "--override-data",
                        '{"chezmoi":{"os":"darwin"}}',
                        "--override-data-file",
                        str(HINDSIGHT_FIXTURE),
                        "target-path",
                        "--source-path",
                        str(source),
                    ],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                target = Path(target_path.stdout.strip())
                actual_targets.add(target.relative_to(destination))
                self.assertTrue(target.is_file())
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
                rendered = subprocess.run(
                    [
                        "chezmoi",
                        "-S",
                        str(SOURCE),
                        *arguments,
                        "--override-data",
                        '{"chezmoi":{"os":"darwin"}}',
                        "--override-data-file",
                        str(HINDSIGHT_FIXTURE),
                        "execute-template",
                    ],
                    env=environment,
                    input=source.read_bytes(),
                    capture_output=True,
                    check=True,
                )
                self.assertEqual(target.read_bytes(), rendered.stdout)
            self.assertEqual(actual_targets, expected_targets)

    def test_secret_exec_state_directory_is_private(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temporary:
            root = Path(temporary)
            destination = root / "home"
            destination.mkdir()
            environment, arguments = self.environment(root, destination)
            sources = sorted(SECRET_EXEC_SOURCE_ROOT.rglob("*.tmpl"))
            self.assertTrue(
                sources,
                f"no secret-exec templates found under {SECRET_EXEC_SOURCE_ROOT}",
            )

            applied = subprocess.run(
                [
                    "chezmoi",
                    "-S",
                    str(SOURCE),
                    *arguments,
                    "--override-data",
                    '{"chezmoi":{"hostname":"test-host"}}',
                    "--override-data-file",
                    str(SECRET_EXEC_FIXTURE),
                    "--source-path",
                    "--refresh-externals=never",
                    "apply",
                    "--parent-dirs",
                    *map(str, sources),
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(applied.returncode, 0, applied.stderr)
            secret_exec = destination / ".config/secret-exec"
            self.assertTrue(secret_exec.is_dir())
            self.assertEqual(stat.S_IMODE(secret_exec.stat().st_mode), 0o700)

    def test_pr_creator_keeps_literal_target_name(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temporary:
            root = Path(temporary)
            destination = root / "home"
            destination.mkdir()
            environment, arguments = self.environment(root, destination)

            target = subprocess.run(
                [
                    "chezmoi",
                    "-S",
                    str(SOURCE),
                    *arguments,
                    "target-path",
                    "--source-path",
                    str(PR_CREATOR_SOURCE),
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )
            expected = (
                destination
                / ".agents/skills/publishing-reviewable-prs/scripts"
                / "create_reviewable_pr.py"
            )
            self.assertEqual(Path(target.stdout.strip()), expected)

    def test_zsh_external_requires_an_immutable_archive_and_checksum(self) -> None:
        externals = tomllib.loads(ZSH_EXTERNAL.read_text(encoding="utf-8"))
        self.assertEqual(set(externals), {".config/zsh"})
        zsh = externals[".config/zsh"]
        self.assertEqual(zsh["type"], "archive")
        self.assertRegex(
            zsh["url"],
            r"\Ahttps://github\.com/nisavid/zsh-config/archive/[0-9a-f]{40}\.tar\.gz\Z",
        )
        self.assertRegex(zsh["checksum"]["sha256"], r"\A[0-9a-f]{64}\Z")
        self.assertEqual(zsh["stripComponents"], 1)
        self.assertIs(zsh["exact"], False)
        self.assertNotIn("refreshPeriod", zsh)
        self.assertFalse({"clone", "pull"}.intersection(zsh))
        self.assertNotIn("git-repo", zsh.values())

    def test_externals_retain_targets_and_refresh_contracts(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temporary:
            root = Path(temporary)
            destination = root / "home"
            destination.mkdir()
            environment, arguments = self.environment(root, destination)

            for name in CATPPUCCIN_CONFIG_EXTERNALS:
                with self.subTest(name=name):
                    source = SOURCE / ".chezmoiexternals" / name
                    rendered = subprocess.run(
                        [
                            "chezmoi",
                            "-S",
                            str(SOURCE),
                            *arguments,
                            "execute-template",
                        ],
                        env=environment,
                        input=source.read_bytes(),
                        capture_output=True,
                        check=True,
                    )
                    text = rendered.stdout.decode("utf-8")
                    targets = re.findall(r'^\["([^"]+)"\]$', text, re.MULTILINE)
                    types = re.findall(r'^type = "([^"]+)"$', text, re.MULTILINE)
                    refresh_periods = re.findall(
                        r'^refreshPeriod = "([^"]+)"$',
                        text,
                        re.MULTILINE,
                    )
                    urls = re.findall(r'^url = "([^"]+)"$', text, re.MULTILINE)
                    self.assertTrue(targets)
                    self.assertEqual(len(types), len(targets))
                    self.assertEqual(len(refresh_periods), len(targets))
                    self.assertEqual(len(urls), len(targets))
                    for target in targets:
                        self.assertTrue(target.startswith(".config/"), target)
                    self.assertEqual(set(types), {"file"})
                    self.assertEqual(set(refresh_periods), {"24h"})
                    self.assertTrue(
                        all(
                            url.startswith("https://github.com/catppuccin/")
                            for url in urls
                        )
                    )


if __name__ == "__main__":
    unittest.main()
