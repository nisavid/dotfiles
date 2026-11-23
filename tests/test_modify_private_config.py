from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
TEMPLATE = ROOT / "home/dot_codex/modify_private_config.toml.tmpl"
INSTRUCTIONS_DATA = ROOT / "home/.chezmoidata/codex-instructions.toml"
RETIRED = (
    ("github", "yeet"),
    ("superpowers", "finishing-a-development-branch"),
    ("superpowers", "executing-plans"),
    ("superpowers", "subagent-driven-development"),
    ("superpowers", "writing-plans"),
    ("superpowers", "test-driven-development"),
    ("superpowers", "dispatching-parallel-agents"),
)


def skill_entries(config: str) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for block in config.split("[[skills.config]]")[1:]:
        path = re.search(r"(?m)^path\s*=\s*['\"]([^'\"]+)['\"]", block)
        enabled = re.search(r"(?m)^enabled\s*=\s*(true|false)\s*$", block)
        if path:
            entries.append(
                {
                    "path": path.group(1),
                    "enabled": enabled is not None and enabled.group(1) == "true",
                }
            )
    return entries


def rendered_modifier(home: Path, darwin: bool = False, *, source: Path | None = None) -> str:
    data = {
        "chezmoi": {"homeDir": str(home), "os": "darwin" if darwin else "linux", "hostname": "test-host"},
        # Supply the one tracked copy of the instruction budget, so a render from a
        # substituted source tree still has it.
        "codexInstructions": tomllib.loads(INSTRUCTIONS_DATA.read_text())["codexInstructions"],
        "gitIdentity": {"publicFixture": True, "selection": {"default": "personal", "byHostname": {}},
                        "identities": {"personal": {"editorTarget": "cursor", "branchPrefix": "nisavid/"}}},
    }
    return subprocess.run(
        ["chezmoi", "-S", str(source or ROOT / "home"), "execute-template", "--override-data", json.dumps(data)],
        input=TEMPLATE.read_text(), text=True, capture_output=True, check=True, timeout=10,
    ).stdout


class DynamicSkillDisableModifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.home = Path(self.temporary_directory.name)
        self.cache = self.home / ".codex/plugins/cache"
        self.work = base64.b64encode(b"writable_roots = []\nprojects = []\n").decode()

    def install(self, provenance: str, plugin: str, version: str, skill: str) -> Path:
        path = (
            self.cache / provenance / plugin / version / "skills" / skill / "SKILL.md"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {skill}\n", encoding="utf-8")
        return path

    def install_personal(self, skill: str) -> Path:
        path = self.home / ".agents/skills" / skill / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {skill}\n", encoding="utf-8")
        return path

    def run_modifier(self, config: str, *, darwin: bool = False, script: str | None = None,
                     environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        script = rendered_modifier(self.home, darwin) if script is None else script
        # Exercise the full launcher with synthetic catalog data only.
        script = script.replace("# python3 reads the script", f"export WORK_TOML_B64={self.work}\n# python3 reads the script")
        return subprocess.run(
            ["/bin/bash", "-c", script], input=config, text=True, capture_output=True,
            env=os.environ | (environment or {}), timeout=10,
        )

    def apply(self, config: str, *, darwin: bool = False) -> str:
        result = self.run_modifier(config, darwin=darwin)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_rejects_modified_or_missing_wheel(self) -> None:
        source = self.home / "source"
        vendor = source / ".chezmoitemplates/vendor/tomlkit-0.15.2.whl.b64"
        vendor.parent.mkdir(parents=True)
        # Replace the actual included file before rendering, including source
        # delimiters that would execute before a check in an unescaped include.
        for replacement in (
            "", base64.b64encode(b"substituted wheel").decode(),
            '\"\"\"); print(os.environ["WORK_TOML_B64"]); raise SystemExit(91); #',
            "PYEOF\nprintf injected\n#",
        ):
            with self.subTest(replacement=replacement):
                vendor.write_text(replacement)
                script = rendered_modifier(self.home, source=source)
                result = self.run_modifier("", script=script)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("integrity check failed", result.stderr)

    def test_python_reads_the_script_from_fd_3_without_a_path(self) -> None:
        # bash 3.2 on macOS mis-scans text inside a process substitution, so the
        # Python body must be a top-level heredoc. Python must read it from fd 3
        # through -c, never as a /dev/fd path: with Python older than 3.10.9 or
        # 3.11.1 on macOS, the zip-import probe of a /dev/fd script moves the
        # shared offset to the end, Python runs an empty module and exits 0, and
        # chezmoi then deletes the Codex config (CPython GH-87235).
        for darwin in (False, True):
            with self.subTest(darwin=darwin):
                script = rendered_modifier(self.home, darwin)
                self.assertFalse("<(" in script, "the modifier must not use a process substitution")
                self.assertFalse("/dev/fd/" in script, "the modifier must not give Python a /dev/fd path")
                launches = [line for line in script.splitlines() if line.startswith("python3 ")]
                self.assertEqual(launches, [
                    "python3 -I -S -c 'import sys; exec(compile(open(3, \"rb\").read(), "
                    "\"codex-modifier\", \"exec\"))' 3<<'PYEOF'"
                ])

    def test_runs_without_package_manager_cache_or_ambient_imports(self) -> None:
        poison = self.home / "poison"
        poison.mkdir()
        marker = self.home / "poison-ran"
        for name in ("tomlkit.py", "sitecustomize.py", "usercustomize.py"):
            (poison / name).write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\nraise RuntimeError('ambient code')\n")
        bin_dir = self.home / "bin"
        bin_dir.mkdir()
        (bin_dir / "python3").symlink_to(sys.executable)
        for name in ("uv", "pip", "pip3", "curl", "wget"):
            tool = bin_dir / name
            tool.write_text(f"#!/bin/sh\n: > '{marker}'\nexit 92\n")
            tool.chmod(0o755)
        result = self.run_modifier('unrelated = "preserved" # keep comment\n', environment={
            "PATH": str(bin_dir), "PYTHONPATH": str(poison), "PYTHONHOME": str(poison),
            "PYTHONUSERBASE": str(poison), "UV_CACHE_DIR": str(self.home / "empty-cache"),
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())
        self.assertIn('unrelated = "preserved" # keep comment', result.stdout)

    def test_discovers_all_versions_provenances_and_retired_skills(self) -> None:
        expected: set[str] = set()
        for index, (plugin, skill) in enumerate(RETIRED):
            expected.add(str(self.install("source-a", plugin, "1.0.0", skill)))
            expected.add(str(self.install_personal(skill)))
            if index % 2 == 0:
                expected.add(str(self.install("source-b", plugin, "2.0.0", skill)))

        unrelated = self.install("source-a", "github", "1.0.0", "other")
        stale = self.cache / "old-source/github/0.0.1/skills/yeet/SKILL.md"
        config = textwrap.dedent(
            f"""
            [[skills.config]]
            path = {str(stale)!r}
            enabled = true

            [[skills.config]]
            path = {str(unrelated)!r}
            enabled = true
            """
        )

        entries = skill_entries(self.apply(config))
        disabled = {entry["path"] for entry in entries if entry.get("enabled") is False}

        self.assertEqual(disabled, expected)
        self.assertNotIn(str(stale), {entry["path"] for entry in entries})
        self.assertIn({"path": str(unrelated), "enabled": True}, entries)

    def test_reapplication_is_idempotent(self) -> None:
        for plugin, skill in RETIRED:
            self.install("source-a", plugin, "1.0.0", skill)

        once = self.apply("")
        twice = self.apply(once)

        self.assertEqual(twice, once)
        entries = skill_entries(twice)
        self.assertEqual(len(entries), len(RETIRED))

    def test_removes_cross_host_retired_personal_and_plugin_entries(self) -> None:
        current = self.install("source-a", "github", "1.0.0", "yeet")
        cross_host_paths = {
            "/home/test-user/.agents/skills/executing-plans/SKILL.md",
            "/home/test-user/.codex/plugins/cache/superpowers/superpowers/9.9.9/skills/"
            "dispatching-parallel-agents/SKILL.md",
        }
        config = "\n".join(
            f"[[skills.config]]\npath = {path!r}\nenabled = false\n"
            for path in cross_host_paths
        )

        entries = skill_entries(self.apply(config))
        paths = {entry["path"] for entry in entries}

        self.assertTrue(cross_host_paths.isdisjoint(paths))
        self.assertIn(str(current), paths)

    def test_removes_retired_serena_mcp_and_keeps_memory_root(self) -> None:
        self.work = base64.b64encode(
            b'writable_roots = [".serena/memories"]\nprojects = []\n'
        ).decode()
        config = textwrap.dedent(
            f"""
            [mcp_servers.serena]
            command = "serena"

            [sandbox_workspace_write]
            writable_roots = ["/tmp/keep", "{self.home}/.serena/memories"]
            """
        )

        parsed = tomllib.loads(self.apply(config))

        self.assertNotIn("serena", parsed["mcp_servers"])
        roots = parsed["sandbox_workspace_write"]["writable_roots"]
        self.assertIn("/tmp/keep", roots)
        self.assertIn(str(self.home / ".serena/memories"), roots)

    def test_adds_approved_darwin_writable_roots(self) -> None:
        self.work = base64.b64encode(
            b'writable_roots = ["src/private-project/.git"]\nprojects = []\n'
        ).decode()
        expected = {
            "src/private-project/.git",
            ".local/share/chezmoi.wt",
            ".config/docker/buildx",
            ".config/containers/podman/machine",
            ".local/share/containers",
            ".vite-plus",
            "node_modules/.vite-temp",
            ".local/share/mise",
            "Library/pnpm",
            ".config/.wrangler/logs",
            ".config/mastic",
            ".local/share/mastic",
            ".pg0/instances",
            ".config/mlxctl",
            ".local/share/mlxctl",
            "Library/Logs/mlxctl",
            "Library/Logs/mlxd",
            ".serena/memories",
        }

        parsed = tomllib.loads(self.apply("", darwin=True))
        roots = set(parsed["sandbox_workspace_write"]["writable_roots"])

        self.assertTrue({str(self.home / path) for path in expected} <= roots)

    def top_level_budget_lines(self, config: str) -> list[str]:
        """Return the project_doc_max_bytes lines that sit before the first table."""
        lines: list[str] = []
        for line in config.splitlines():
            if line.lstrip().startswith("["):
                break
            if re.match(r"\s*project_doc_max_bytes\s*=", line):
                lines.append(line)
        return lines

    def test_sets_instruction_budget_at_top_level(self) -> None:
        budget = tomllib.loads(INSTRUCTIONS_DATA.read_text())["codexInstructions"]["projectDocMaxBytes"]
        self.assertIsInstance(budget, int)
        inputs = {
            "absent key with tables only": '[tui]\ntheme = "other"\n\n[mcp_servers.fixture]\ncommand = "x"\n',
            "other value": 'project_doc_max_bytes = 1234\n\n[tui]\ntheme = "other"\n',
            "other value beside other keys": 'unrelated = "keep"\nproject_doc_max_bytes = 99999999\n\n[tui]\nk = 1\n',
            "empty file": "",
            "nested table last": '[a]\nx = 1\n[a.b]\ny = 2\n',
        }
        for name, config in inputs.items():
            with self.subTest(name):
                once = self.apply(config)
                parsed = tomllib.loads(once)
                self.assertEqual(parsed["project_doc_max_bytes"], budget)
                self.assertEqual(len(re.findall(r"(?m)^\s*project_doc_max_bytes\s*=", once)), 1)
                self.assertEqual(len(self.top_level_budget_lines(once)), 1)
                for key, value in parsed.items():
                    if isinstance(value, dict):
                        self.assertNotIn("project_doc_max_bytes", value, key)
                self.assertEqual(self.apply(once), once)

    def test_instruction_budget_leaves_other_settings_unchanged(self) -> None:
        config = 'unrelated = "keep" # keep comment\n\n[projects."/fixture"]\ntrust_level = "untrusted"\n'
        without_budget = tomllib.loads(self.apply(config))
        without_budget.pop("project_doc_max_bytes")
        baseline = tomllib.loads(config)
        self.assertEqual(without_budget["unrelated"], baseline["unrelated"])
        self.assertEqual(without_budget["projects"]["/fixture"], baseline["projects"]["/fixture"])
        self.assertIn("# keep comment", self.apply(config))

    def test_adds_linux_roots_and_explicit_private_paths(self) -> None:
        self.work = base64.b64encode(
            b'writable_roots = ["src/private-project/.git"]\n'
            b'projects = ["src/private-project", "src/existing-project"]\n'
        ).decode()
        config = textwrap.dedent(
            f"""
            [sandbox_workspace_write]
            writable_roots = ["/tmp/keep", "{self.home}/src/private-project/.git"]

            [projects."{self.home}/src/existing-project"]
            trust_level = "untrusted"

            [hooks.state]
            fixture_hash = "keep"
            """
        )
        result = self.apply(config)
        parsed = tomllib.loads(result)
        roots = set(parsed["sandbox_workspace_write"]["writable_roots"])

        self.assertEqual(
            roots,
            {
                "/tmp/keep",
                str(self.home / "src/private-project/.git"),
                str(self.home / ".codex/worktrees"),
                str(self.home / ".t3/worktrees"),
                str(self.home / ".local/share/chezmoi"),
                str(self.home / ".local/share/chezmoi.wt"),
                str(self.home / ".local/state/provingkit/deletion-queue"),
            },
        )
        self.assertEqual(
            parsed["projects"][str(self.home / "src/private-project")],
            {"trust_level": "trusted"},
        )
        self.assertEqual(
            parsed["projects"][str(self.home / "src/existing-project")],
            {"trust_level": "untrusted"},
        )
        self.assertEqual(parsed["hooks"]["state"], {"fixture_hash": "keep"})
        self.assertEqual(self.apply(result), result)


if __name__ == "__main__":
    unittest.main()
