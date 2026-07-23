from __future__ import annotations

import base64
import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
TEMPLATE = ROOT / "home/dot_codex/modify_private_config.toml.tmpl"
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


def modifier_python() -> str:
    source = TEMPLATE.read_text(encoding="utf-8")
    start = source.index("import os, sys, base64, tomlkit")
    end = source.index("\nPYEOF", start)
    code = source[start:end]
    return code.replace(
        'if {{ if eq .chezmoi.os "darwin" }}True{{ else }}False{{ end }} else []',
        "if False else []",
    )


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

    def apply(self, config: str) -> str:
        environment = os.environ | {
            "HOMEDIR": str(self.home),
            "EDITOR_TARGET": "cursor",
            "GIT_BRANCH_PREFIX": "nisavid/",
            "WORK_TOML_B64": self.work,
        }
        result = subprocess.run(
            [
                "uv",
                "run",
                "--quiet",
                "--with",
                "tomlkit",
                "python3",
                "-c",
                modifier_python(),
            ],
            input=config,
            text=True,
            capture_output=True,
            check=True,
            env=environment,
        )
        return result.stdout

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
            "/home/nisavid/.agents/skills/executing-plans/SKILL.md",
            "/home/nisavid/.codex/plugins/cache/superpowers/superpowers/9.9.9/skills/"
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


if __name__ == "__main__":
    unittest.main()
