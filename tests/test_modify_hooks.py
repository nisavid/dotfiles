from __future__ import annotations

import json
import shlex
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any


TEMPLATE = Path(__file__).parents[1] / "home" / "dot_codex" / "modify_hooks.json.tmpl"
TEST_HOME = "/Users/test"
GUARD_PATH = f"{TEST_HOME}/.codex/scripts/block_pr_fill.py"


def run_modifier(
    document: Any, home_dir: str = TEST_HOME
) -> subprocess.CompletedProcess[str]:
    try:
        rendered = subprocess.run(
            [
                "chezmoi",
                "execute-template",
                "--override-data",
                json.dumps({"chezmoi": {"homeDir": home_dir}}),
            ],
            input=TEMPLATE.read_text(encoding="utf-8"),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except FileNotFoundError as error:
        raise AssertionError("chezmoi is required to test hook rendering") from error
    if rendered.returncode:
        raise AssertionError(rendered.stderr)
    return subprocess.run(
        [sys.executable, "-c", rendered.stdout],
        input=json.dumps(document),
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def apply_modifier(
    document: Any, home_dir: str = TEST_HOME
) -> dict[str, Any]:
    result = run_modifier(document, home_dir)
    if result.returncode:
        raise AssertionError(f"stdout={result.stdout!r}\nstderr={result.stderr}")
    return json.loads(result.stdout)


def guard_hooks(document: dict[str, Any]) -> list[dict[str, Any]]:
    canonical_command = shlex.join(["python3", GUARD_PATH])
    canonical_hook = {
        "type": "command",
        "command": canonical_command,
        "timeout": 12,
        "statusMessage": "Checking canonical PR publication",
    }
    return [
        matcher["hooks"][0]
        for matcher in document["hooks"]["PreToolUse"]
        if matcher == {"hooks": [canonical_hook]}
    ]


class ModifyHooksTests(unittest.TestCase):
    def test_adds_canonical_guard_to_empty_document(self) -> None:
        modified = apply_modifier({})
        self.assertEqual(len(guard_hooks(modified)), 1)
        self.assertEqual(guard_hooks(modified)[0]["timeout"], 12)

    def test_shell_quotes_guard_paths_as_one_argument(self) -> None:
        home_dir = r"/Users/test/\1 odd $home's"
        guard_path = f"{home_dir}/.codex/scripts/block_pr_fill.py"
        modified = apply_modifier({}, home_dir=home_dir)
        command = modified["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertEqual(shlex.split(command), ["python3", guard_path])

    def test_deduplicates_guard_while_preserving_other_hooks_and_metadata(
        self,
    ) -> None:
        document = {
            "version": 1,
            "hooks": {
                "PostToolUse": [{"hooks": [{"command": "post-command"}]}],
                "PreToolUse": [
                    "future-matcher-shape",
                    {
                        "matcher": "Bash",
                        "custom": "preserve-me",
                        "hooks": [
                            {"type": "command", "command": "first-command"},
                            {
                                "type": "command",
                                "command": f"python3 '{GUARD_PATH}'",
                                "timeout": 3,
                            },
                            {
                                "type": "command",
                                "command": f'python3 -u "{GUARD_PATH}"',
                            },
                            {
                                "type": "command",
                                "command": f'/usr/bin/env python3 "{GUARD_PATH}"',
                            },
                            {
                                "type": "command",
                                "command": f'/usr/bin/env -- python3 "{GUARD_PATH}"',
                            },
                            {
                                "type": "prompt",
                                "command": f'python3 "{GUARD_PATH}"',
                            },
                            {"type": "command", "command": "second-command"},
                        ],
                    },
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": f'python3 "{GUARD_PATH}"',
                            }
                        ]
                    },
                ],
            },
        }

        modified = apply_modifier(document)

        self.assertEqual(modified["version"], 1)
        self.assertEqual(
            modified["hooks"]["PostToolUse"], document["hooks"]["PostToolUse"]
        )
        self.assertEqual(len(guard_hooks(modified)), 1)
        self.assertEqual(guard_hooks(modified)[0]["timeout"], 12)
        self.assertEqual(modified["hooks"]["PreToolUse"][0], "future-matcher-shape")
        preserved = next(
            matcher
            for matcher in modified["hooks"]["PreToolUse"]
            if isinstance(matcher, dict) and matcher.get("matcher") == "Bash"
        )
        self.assertEqual(preserved["matcher"], "Bash")
        self.assertEqual(preserved["custom"], "preserve-me")
        self.assertEqual(
            [hook["command"] for hook in preserved["hooks"]],
            ["first-command", f'python3 "{GUARD_PATH}"', "second-command"],
        )

    def test_deduplicates_expandable_home_guard_path_spellings(self) -> None:
        home_guard_path = "$HOME/.codex/scripts/block_pr_fill.py"
        braced_home_guard_path = "${HOME}/.codex/scripts/block_pr_fill.py"
        tilde_guard_path = "~/.codex/scripts/block_pr_fill.py"
        equivalent = (
            home_guard_path,
            f'"{home_guard_path}"',
            braced_home_guard_path,
            f'"{braced_home_guard_path}"',
            tilde_guard_path,
            f'python3 "{home_guard_path}"',
            f"python3 {braced_home_guard_path}",
            f"python3 {tilde_guard_path}",
            f'python3 -u "{home_guard_path}"',
            f'/usr/bin/env python3 "{braced_home_guard_path}"',
            f"/usr/bin/env -- python3 {tilde_guard_path}",
        )
        literal = (
            f"python3 '{home_guard_path}'",
            f"python3 '{braced_home_guard_path}'",
            f'python3 "{tilde_guard_path}"',
            f"python3 \\{home_guard_path}",
        )
        context_changing_env = f'env FOO=bar python3 "{home_guard_path}"'
        document = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            *(
                                {"type": "command", "command": command}
                                for command in equivalent
                            ),
                            *(
                                {"type": "command", "command": command}
                                for command in literal
                            ),
                            {
                                "type": "command",
                                "command": context_changing_env,
                            },
                        ],
                    }
                ]
            }
        }

        modified = apply_modifier(document)

        self.assertEqual(len(guard_hooks(modified)), 1)
        commands = [
            hook["command"]
            for matcher in modified["hooks"]["PreToolUse"]
            if isinstance(matcher, dict)
            for hook in matcher.get("hooks", [])
            if isinstance(hook, dict)
        ]
        for command in equivalent:
            self.assertNotIn(command, commands)
        for command in literal:
            self.assertIn(command, commands)
        self.assertIn(context_changing_env, commands)

    def test_rejects_invalid_hook_shapes_without_output(self) -> None:
        cases = (
            ([], "root"),
            ({"hooks": None}, "hooks"),
            ({"hooks": {"PreToolUse": {}}}, "PreToolUse"),
            ({"hooks": {"PreToolUse": [{"hooks": None}]}}, "matcher"),
        )
        for document, message in cases:
            with self.subTest(document=document):
                result = run_modifier(document)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn(message, result.stderr)

    def test_reapply_is_stable(self) -> None:
        initial = {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Read", "hooks": [{"command": "read-command"}]}
                ]
            }
        }
        once = apply_modifier(initial)
        twice = apply_modifier(once)
        self.assertEqual(twice, once)

    def test_preserves_unrelated_commands_that_only_pass_guard_path_as_data(
        self,
    ) -> None:
        unrelated = f'python3 verify-hook.py "{GUARD_PATH}"'
        context_changing_env = (
            f'env FOO=bar python3 "{GUARD_PATH}"',
            f'env -i python3 "{GUARD_PATH}"',
            f'env -C /private/tmp python3 "{GUARD_PATH}"',
        )
        direct = GUARD_PATH
        document = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {"type": "command", "command": unrelated},
                            *(
                                {"type": "command", "command": command}
                                for command in context_changing_env
                            ),
                            {"type": "command", "command": direct},
                        ],
                    }
                ]
            }
        }

        modified = apply_modifier(document)
        commands = [
            hook["command"]
            for matcher in modified["hooks"]["PreToolUse"]
            if isinstance(matcher, dict)
            for hook in matcher.get("hooks", [])
            if isinstance(hook, dict)
        ]
        self.assertIn(unrelated, commands)
        for command in context_changing_env:
            self.assertIn(command, commands)
        self.assertNotIn(direct, commands)
        self.assertIn(shlex.join(["python3", GUARD_PATH]), commands)


if __name__ == "__main__":
    unittest.main()
