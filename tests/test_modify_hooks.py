from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any


TEMPLATE = Path(__file__).parents[1] / "home" / "dot_codex" / "modify_hooks.json.tmpl"
TEST_HOME = "/Users/test"
OBSOLETE_PATH = f"{TEST_HOME}/.codex/scripts/block_pr_fill.py"


def run_modifier_raw(
    raw: str, home_dir: str = TEST_HOME
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
        input=raw,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def run_modifier(
    document: Any, home_dir: str = TEST_HOME
) -> subprocess.CompletedProcess[str]:
    return run_modifier_raw(json.dumps(document), home_dir)


def apply_modifier(
    document: Any, home_dir: str = TEST_HOME
) -> dict[str, Any]:
    result = run_modifier(document, home_dir)
    if result.returncode:
        raise AssertionError(f"stdout={result.stdout!r}\nstderr={result.stderr}")
    return json.loads(result.stdout)


class ModifyHooksTests(unittest.TestCase):
    def test_does_not_activate_hooks_and_preserves_noop_bytes(self) -> None:
        cases = (
            "",
            "{}\n",
            '{\n  "disabled": true,\n  "theme": "dark"\n}\n',
            '{"hooks":{"PreToolUse":[]},"disabled":true}\n',
        )
        for raw in cases:
            with self.subTest(raw=raw):
                result = run_modifier_raw(raw)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, raw)

    def test_removes_supported_legacy_command_shapes(self) -> None:
        home_path = "$HOME/.codex/scripts/block_pr_fill.py"
        braced_home_path = "${HOME}/.codex/scripts/block_pr_fill.py"
        tilde_path = "~/.codex/scripts/block_pr_fill.py"
        commands = (
            OBSOLETE_PATH,
            f"python3 '{OBSOLETE_PATH}'",
            f'python3 -u "{OBSOLETE_PATH}"',
            f'/usr/bin/python "{OBSOLETE_PATH}"',
            f'/usr/bin/env python3 "{OBSOLETE_PATH}"',
            f'/usr/bin/env -- python3 "{OBSOLETE_PATH}"',
            home_path,
            f'"{home_path}"',
            braced_home_path,
            f'"{braced_home_path}"',
            tilde_path,
            f'python3 "{home_path}"',
            f"python3 {braced_home_path}",
            f"python3 {tilde_path}",
            f'python3 -u "{home_path}"',
            f'/usr/bin/env python3 "{braced_home_path}"',
            f"/usr/bin/env -- python3 {tilde_path}",
        )
        hooks = []
        for index, command in enumerate(commands):
            hook: dict[str, Any] = {"command": command}
            if index:
                hook["type"] = "command"
            if index == 1:
                hook["disabled"] = True
            hooks.append(hook)
        document = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": hooks,
                    }
                ]
            }
        }

        modified = apply_modifier(document)

        self.assertEqual(modified["hooks"]["PreToolUse"], [])

    def test_removes_disabled_obsolete_hooks_and_preserves_other_state(
        self,
    ) -> None:
        prompt_hook = {
            "type": "prompt",
            "command": f'python3 "{OBSOLETE_PATH}"',
            "disabled": True,
        }
        document = {
            "version": 1,
            "disabled": True,
            "hooks": {
                "disabled": True,
                "PostToolUse": [{"hooks": [{"command": "post-command"}]}],
                "PreToolUse": [
                    "future-matcher-shape",
                    {
                        "matcher": "Bash",
                        "custom": "preserve-me",
                        "disabled": True,
                        "hooks": [
                            {
                                "type": "command",
                                "command": "first-command",
                                "disabled": True,
                            },
                            {
                                "type": "command",
                                "command": f"python3 '{OBSOLETE_PATH}'",
                                "disabled": True,
                            },
                            prompt_hook,
                            {"type": "command", "command": "second-command"},
                        ],
                    },
                    {
                        "matcher": "Bash",
                        "disabled": True,
                        "hooks": [
                            {
                                "type": "command",
                                "command": OBSOLETE_PATH,
                                "disabled": True,
                            }
                        ],
                    },
                ],
            },
        }

        modified = apply_modifier(document)

        self.assertTrue(modified["disabled"])
        self.assertTrue(modified["hooks"]["disabled"])
        self.assertEqual(
            modified["hooks"]["PostToolUse"], document["hooks"]["PostToolUse"]
        )
        self.assertEqual(
            modified["hooks"]["PreToolUse"],
            [
                "future-matcher-shape",
                {
                    "matcher": "Bash",
                    "custom": "preserve-me",
                    "disabled": True,
                    "hooks": [
                        {
                            "type": "command",
                            "command": "first-command",
                            "disabled": True,
                        },
                        prompt_hook,
                        {"type": "command", "command": "second-command"},
                    ],
                },
            ],
        )

    def test_preserves_unrelated_commands_and_obsolete_path_as_data(self) -> None:
        home_path = "$HOME/.codex/scripts/block_pr_fill.py"
        tilde_path = "~/.codex/scripts/block_pr_fill.py"
        commands = (
            "first-command",
            f'python3 verify-hook.py "{OBSOLETE_PATH}"',
            f'printf "%s" "{OBSOLETE_PATH}"',
            f'env FOO=bar python3 "{home_path}"',
            f'env -i python3 "{home_path}"',
            f'env -C /private/tmp python3 "{home_path}"',
            f'sh -c \'python3 "{OBSOLETE_PATH}"\'',
            f'python3 "{OBSOLETE_PATH}" --check',
            f"python3 '{home_path}'",
            f'python3 "{tilde_path}"',
        )
        document = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {"type": "command", "command": command}
                            for command in commands
                        ],
                    }
                ]
            }
        }
        raw = json.dumps(document, separators=(",", ":")) + "\n"

        result = run_modifier_raw(raw)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, raw)

    def test_reapply_is_byte_stable_after_removal(self) -> None:
        document = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": f'python3 "{OBSOLETE_PATH}"',
                            },
                            {"type": "command", "command": "keep-command"},
                        ],
                    }
                ]
            }
        }
        raw = json.dumps(document, separators=(",", ":")) + "\n"

        once = run_modifier_raw(raw)
        self.assertEqual(once.returncode, 0, once.stderr)
        twice = run_modifier_raw(once.stdout)
        self.assertEqual(twice.returncode, 0, twice.stderr)

        self.assertEqual(twice.stdout, once.stdout)
        self.assertEqual(
            json.loads(once.stdout)["hooks"]["PreToolUse"][0]["hooks"],
            [{"type": "command", "command": "keep-command"}],
        )

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


if __name__ == "__main__":
    unittest.main()
