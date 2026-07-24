from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "home"
HINDSIGHT_SOURCE_ROOT = SOURCE / "dot_config/private_hindsight-control-plane"
CATPPUCCIN_CONFIG_EXTERNALS = (
    "bat-catppuccin.toml.tmpl",
    "gitui-catppuccin.toml.tmpl",
    "glamour-catppuccin.toml.tmpl",
    "lazygit-catppuccin.toml.tmpl",
    "micro-catppuccin.toml.tmpl",
)
ZPROFILE_ORIGINAL = (
    "# Added by another application\nsource ~/.other/init.zsh 2>/dev/null || :\n"
)
ZPROFILE_MANAGED_BLOCK = """\
# >>> secret-exec managed zprofile >>>
function {
  local managed_zprofile=${ZDOTDIR:-$HOME/.config/zsh}/zprofile.zsh
  [[ -r $managed_zprofile ]] && source $managed_zprofile
}
# <<< secret-exec managed zprofile <<<
"""


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
            "XDG_DATA_HOME": str(runtime / "data"),
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

    def test_zsh_external_and_post_update_hook_apply_together(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            root = Path(temporary)
            source = root / "source"
            external = root / "zsh-config"
            destination = root / "home"
            source.mkdir()
            external.mkdir()
            destination.mkdir()
            environment, arguments = self.environment(root, destination)
            environment |= {
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
            }

            (external / ".zprofile").write_text(
                ZPROFILE_ORIGINAL,
                encoding="utf-8",
            )
            (external / "zprofile.zsh").write_text(
                "ZPROFILE_FIXTURE_LOADED=yes\n",
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "init", "--quiet", "--initial-branch=main"],
                cwd=external,
                env=environment,
                check=True,
            )
            subprocess.run(
                ["git", "add", ".zprofile", "zprofile.zsh"],
                cwd=external,
                env=environment,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "commit.gpgsign=false",
                    "-c",
                    "user.name=Chezmoi test",
                    "-c",
                    "user.email=chezmoi-test@example.invalid",
                    "commit",
                    "--quiet",
                    "-m",
                    "test: add zsh fixture",
                ],
                cwd=external,
                env=environment,
                check=True,
            )

            externals = source / ".chezmoiexternals"
            externals.mkdir()
            (externals / "zsh-config.toml").write_text(
                '[".config/zsh"]\n'
                'type = "git-repo"\n'
                f'url = "{external.as_uri()}"\n'
                'refreshPeriod = "24h"\n',
                encoding="utf-8",
            )
            shutil.copy2(
                SOURCE / "run_after_update-zprofile-hook.py.tmpl",
                source / "run_after_update-zprofile-hook.py.tmpl",
            )

            command = [
                "chezmoi",
                "-S",
                str(source),
                *arguments,
                "--refresh-externals=never",
                "apply",
            ]
            first_apply = subprocess.run(
                command,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(first_apply.returncode, 0, first_apply.stderr)
            self.assertNotIn("inconsistent state", first_apply.stderr)

            zprofile = destination / ".config/zsh/.zprofile"
            expected = f"{ZPROFILE_ORIGINAL}\n{ZPROFILE_MANAGED_BLOCK}".encode()
            self.assertTrue((destination / ".config/zsh/.git").is_dir())
            self.assertEqual(zprofile.read_bytes(), expected)
            self.assertEqual(stat.S_IMODE(zprofile.stat().st_mode), 0o644)
            sourced = subprocess.run(
                [
                    "zsh",
                    "-f",
                    "-c",
                    'source "$ZDOTDIR/.zprofile"; '
                    "[[ ${ZPROFILE_FIXTURE_LOADED:-} == yes ]]",
                ],
                env=environment | {"ZDOTDIR": str(destination / ".config/zsh")},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(sourced.returncode, 0, sourced.stderr)

            original_metadata = zprofile.stat()
            second_apply = subprocess.run(
                command,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(second_apply.returncode, 0, second_apply.stderr)
            self.assertEqual(zprofile.read_bytes(), expected)
            reapplied_metadata = zprofile.stat()
            self.assertEqual(
                stat.S_IMODE(reapplied_metadata.st_mode),
                0o644,
            )
            self.assertEqual(reapplied_metadata.st_ino, original_metadata.st_ino)
            self.assertEqual(
                reapplied_metadata.st_mtime_ns,
                original_metadata.st_mtime_ns,
            )

    def test_full_source_init_and_scoped_apply_have_consistent_ownership(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
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

    def test_hindsight_keeps_paths_bytes_and_private_modes(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
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
                        "execute-template",
                    ],
                    env=environment,
                    input=source.read_bytes(),
                    capture_output=True,
                    check=True,
                )
                self.assertEqual(target.read_bytes(), rendered.stdout)
            self.assertEqual(actual_targets, expected_targets)

    def test_externals_retain_targets_and_refresh_contracts(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            root = Path(temporary)
            destination = root / "home"
            destination.mkdir()
            environment, arguments = self.environment(root, destination)

            zsh = (SOURCE / ".chezmoiexternals/zsh-config.toml").read_text(
                encoding="utf-8"
            )
            self.assertEqual(
                zsh,
                '[".config/zsh"]\n'
                'type = "git-repo"\n'
                'url = "https://github.com/nisavid/zsh-config"\n'
                'refreshPeriod = "24h"\n',
            )

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
