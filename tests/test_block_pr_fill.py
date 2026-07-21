from __future__ import annotations

import importlib.util
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = (
    Path(__file__).parents[1] / "home" / "dot_codex" / "scripts" / "block_pr_fill.py"
)
SPEC = importlib.util.spec_from_file_location("block_pr_fill", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MODULE.VALIDATOR = Path(__file__).parent / "fixtures" / "validate_navigation.py"
CANONICAL_BODY = "<!-- test-canonical-change-navigation -->\n"


def payload(tool_name: str, tool_input: dict[str, str]) -> dict[str, object]:
    return {"tool_name": tool_name, "tool_input": tool_input}


class BlockPrFillTests(unittest.TestCase):
    def assert_direct_and_nested_blocked(self, command: str) -> None:
        direct = payload("Bash", {"command": command})
        self.assertTrue(MODULE.blocks(direct), command)
        code = f"await tools.exec_command({{cmd: {json.dumps(command)}}})"
        nested = payload("functions.exec", {"code": code})
        self.assertTrue(MODULE.blocks(nested), command)
        self.assertTrue(MODULE._block_message(nested))

    def assert_direct_and_nested_allowed(self, command: str) -> None:
        direct = payload("Bash", {"command": command})
        self.assertFalse(MODULE.blocks(direct), command)
        code = f"await tools.exec_command({{cmd: {json.dumps(command)}}})"
        nested = payload("functions.exec", {"code": code})
        self.assertFalse(MODULE.blocks(nested), command)

    def test_blocks_every_fill_variant(self) -> None:
        for flag in ("--fill", "--fill-first", "--fill-verbose"):
            with self.subTest(flag=flag):
                self.assertTrue(
                    MODULE.blocks(payload("Bash", {"command": f"gh pr create {flag}"}))
                )

    def test_blocks_qualified_gh_path(self) -> None:
        self.assertTrue(
            MODULE.blocks(
                payload(
                    "exec_command",
                    {"cmd": "/opt/homebrew/bin/gh pr create --draft --fill"},
                )
            )
        )

    def test_blocks_repo_flag_and_short_fill(self) -> None:
        commands = (
            "gh -R acme/app pr create -f",
            "gh --repo acme/app pr create -df",
            "gh --repo=acme/app pr new -f",
            "gh --hostname github.com pr create --fill",
            "printf x | gh pr create --fill",
            "{ gh pr create --fill; }",
            "env GH_HOST=github.com gh pr create --fill",
            "gh -Racme/app pr create --fill",
            "gh pr create --fill=true",
            "echo ok\ngh pr create --fill",
            "exec gh pr create --fill",
            "time gh pr create --fill",
            "! gh pr create --fill",
            "if gh pr create --fill; then echo bad; fi",
            "sudo gh pr create --fill",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(MODULE.blocks(payload("Bash", {"command": command})))

    def test_blocks_common_exec_wrappers(self) -> None:
        commands = (
            "nice -n 5 gh pr create --fill",
            "nohup gh pr create --fill",
            "timeout --kill-after=2s 5s gh pr create --fill",
            "watch --interval 2 gh pr create --fill",
            "watch --interval 2 'gh pr create --fill'",
            "printf x | xargs -n 1 gh pr create --fill",
            "nice nohup timeout 5s gh pr create --fill",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(MODULE.blocks(payload("Bash", {"command": command})))

    def test_normalizes_control_prefix_options_and_builtin_command(self) -> None:
        blocked_commands = (
            "command -- gh pr ready 7",
            "command -p gh pr ready 7",
            "exec -- gh pr ready 7",
            "time -p gh pr ready 7",
            "time -- gh pr ready 7",
            "builtin command gh pr ready 7",
            "builtin command -p gh pr ready 7",
            "/usr/bin/env gh pr ready 7",
            "/usr/bin/time -p gh pr ready 7",
            "time -p -p gh pr ready 7",
        )
        for command in blocked_commands:
            with self.subTest(command=command):
                self.assert_direct_and_nested_blocked(command)

        for command in ("command -- git status", "time -p git status"):
            with self.subTest(command=command):
                self.assertFalse(MODULE.blocks(payload("Bash", {"command": command})))

    def test_resolves_literal_shell_assignments_and_blocks_dynamic_indirection(
        self,
    ) -> None:
        blocked_commands = (
            "GH=gh; $GH pr create --fill",
            "COMMAND='gh pr ready 2'; eval \"$COMMAND\"",
            'eval "$UNRESOLVED_COMMAND"',
            "$UNRESOLVED_COMMAND pr create --fill",
        )
        for command in blocked_commands:
            with self.subTest(command=command):
                self.assertTrue(MODULE.blocks(payload("Bash", {"command": command})))

        allowed_commands = (
            "COMMAND='git status'; eval \"$COMMAND\"",
            "COMMAND=git; $COMMAND status --short",
            "eval 'echo $HOME'",
        )
        for command in allowed_commands:
            with self.subTest(command=command):
                self.assertFalse(MODULE.blocks(payload("Bash", {"command": command})))

        message = MODULE._block_message(
            payload("Bash", {"command": 'eval "$UNRESOLVED_COMMAND"'})
        )
        self.assertIn("`eval`", message)
        self.assertIn("safety could not be proven", message)
        self.assertIn("Stop and surface this blocker", message)

    def test_inspects_env_split_builtin_and_command_substitution_routes(self) -> None:
        blocked_commands = (
            "env -S 'gh pr ready 7'",
            "env --split-string='gh pr ready 7'",
            "nice env -S 'gh pr ready 7'",
            "COMMAND='gh pr ready 7'; builtin eval \"$COMMAND\"",
            "echo `gh pr ready 7`",
            'echo "$(gh pr ready 7)"',
        )
        for command in blocked_commands:
            with self.subTest(command=command):
                self.assert_direct_and_nested_blocked(command)

        self.assert_direct_and_nested_blocked(
            r'''printf '%s' 'safe\'"$(gh pr ready 7)"'''
        )

        allowed_commands = (
            "env -S 'git status --short'",
            "COMMAND='git status'; builtin eval \"$COMMAND\"",
            "builtin echo ok",
            'echo "$(git status --short)"',
            "printf '%s\\n' '`gh pr ready 7`'",
            "printf '%s\\n' '$(gh pr ready 7)'",
        )
        for command in allowed_commands:
            with self.subTest(command=command):
                self.assertFalse(MODULE.blocks(payload("Bash", {"command": command})))

    def test_treats_hash_as_comment_only_at_shell_word_boundaries(self) -> None:
        blocked_commands = (
            "true x#; gh pr ready 7",
            "echo foo{#bar,baz}; gh pr ready 7",
            'echo foo#bar "$(gh pr ready 7)"',
            "echo foo#bar `gh pr ready 7`",
        )
        for command in blocked_commands:
            with self.subTest(command=command):
                self.assert_direct_and_nested_blocked(command)

        self.assertFalse(
            MODULE.blocks(payload("Bash", {"command": "echo ok # gh pr ready 7"}))
        )

    def test_unproven_indirection_is_loud_at_direct_and_nested_boundaries(self) -> None:
        cases = (
            ("gh-secret-extension 7 --title bad", "gh-secret-extension"),
            ("env -S", "env -S"),
            ('builtin eval "$UNKNOWN"', "eval"),
            ("echo `unterminated", "command substitution"),
            ('python3 "$SCRIPT"', "python3 script"),
        )
        for command, route in cases:
            with self.subTest(command=command):
                direct = payload("Bash", {"command": command})
                nested = payload(
                    "functions.exec",
                    {
                        "code": (
                            f"await tools.exec_command({{cmd: {json.dumps(command)}}})"
                        )
                    },
                )
                for request in (direct, nested):
                    self.assertTrue(MODULE.blocks(request))
                    message = MODULE._block_message(request)
                    self.assertIn(route, message)
                    self.assertIn("safety could not be proven", message)
                    self.assertIn("Stop and surface this blocker", message)

    def test_normalizes_aliases_before_exact_helper_recognition(self) -> None:
        malicious = (
            "PYTHON=python3; $PYTHON /tmp/update_reviewable_pr.py text --garbage"
        )
        self.assert_direct_and_nested_blocked(malicious)

        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as script:
            script.write("print('unrelated')\n")
            script.flush()
            command = f'SCRIPT={shlex.quote(script.name)}; python3 "$SCRIPT"'
            self.assertFalse(MODULE.blocks(payload("Bash", {"command": command})))

    def test_inspects_readable_literal_shell_and_python_scripts(self) -> None:
        self.assert_direct_and_nested_blocked("./mutate.sh")
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".sh"
        ) as shell_script:
            shell_script.write("gh pr ready 7\n")
            shell_script.flush()
            self.assert_direct_and_nested_blocked(
                f"bash {shlex.quote(shell_script.name)}"
            )
            os.chmod(shell_script.name, 0o755)
            shell_script.seek(0)
            shell_script.write("#!/bin/sh\ngh pr ready 7\n")
            shell_script.truncate()
            shell_script.flush()
            self.assert_direct_and_nested_blocked(shlex.quote(shell_script.name))

        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".py"
        ) as python_script:
            python_script.write(
                "import subprocess\nsubprocess.run(['gh', 'pr', 'ready', '7'])\n"
            )
            python_script.flush()
            self.assert_direct_and_nested_blocked(
                f"python3 {shlex.quote(python_script.name)}"
            )
            python_script.seek(0)
            python_script.write(
                "from subprocess import run\nrun(['gh', 'pr', 'ready', '7'])\n"
            )
            python_script.truncate()
            python_script.flush()
            self.assert_direct_and_nested_blocked(
                f"python3 {shlex.quote(python_script.name)}"
            )

        self.assert_direct_and_nested_blocked(
            "python3 -c \"import os; os.system('gh pr ready 7')\""
        )

        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".js"
        ) as node_script:
            node_script.write(
                "require('node:child_process').execSync('gh pr ready 7')\n"
            )
            node_script.flush()
            self.assert_direct_and_nested_blocked(
                f"node {shlex.quote(node_script.name)}"
            )
        self.assert_direct_and_nested_blocked(
            "node -e \"require('node:child_process').execSync('gh pr ready 7')\""
        )

    def test_resolves_relative_scripts_against_verified_workdir(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            safe_scripts = {
                "gradlew": "#!/bin/sh\nprintf '%s\\n' safe\n",
                "prettier": "#!/usr/bin/env node\nconsole.log('safe')\n",
                "verify.py": "#!/usr/bin/env python3\nprint('safe')\n",
            }
            for name, source in safe_scripts.items():
                path = root / name
                path.write_text(source, encoding="utf-8")
                path.chmod(0o755)
                command = f"./{name}"
                self.assertFalse(
                    MODULE.blocks(
                        payload("Bash", {"command": command, "workdir": str(root)})
                    )
                )
                nested = (
                    "await tools.exec_command({"
                    f"cmd: {json.dumps(command)}, workdir: {json.dumps(str(root))}"
                    "})"
                )
                self.assertFalse(
                    MODULE.blocks(payload("functions.exec", {"code": nested}))
                )

            mutation = root / "mutate.sh"
            mutation.write_text("#!/bin/sh\ngh pr ready 7\n", encoding="utf-8")
            mutation.chmod(0o755)
            self.assertTrue(
                MODULE.blocks(
                    payload(
                        "Bash",
                        {"command": "./mutate.sh", "workdir": str(root)},
                    )
                )
            )
            nested = (
                "await tools.exec_command({cmd: './mutate.sh', "
                f"workdir: {json.dumps(str(root))}}})"
            )
            self.assertTrue(MODULE.blocks(payload("functions.exec", {"code": nested})))

            safe_root = root / "verify"
            safe_root.write_text("#!/bin/sh\nprintf safe\n", encoding="utf-8")
            safe_root.chmod(0o755)
            subdirectory = root / "sub"
            subdirectory.mkdir()
            nested_mutation = subdirectory / "verify"
            nested_mutation.write_text("#!/bin/sh\ngh pr ready 7\n", encoding="utf-8")
            nested_mutation.chmod(0o755)
            for command in ("cd sub && ./verify", "pushd sub && ./verify"):
                with self.subTest(command=command):
                    self.assertTrue(
                        MODULE.blocks(
                            payload(
                                "Bash",
                                {"command": command, "workdir": str(root)},
                            )
                        )
                    )

    def test_defaults_relative_script_resolution_to_hook_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            safe = root / "verify"
            safe.write_text("#!/bin/sh\nprintf safe\n", encoding="utf-8")
            safe.chmod(0o755)
            direct = payload("Bash", {"command": "./verify"})
            nested = payload(
                "functions.exec",
                {"code": "await tools.exec_command({cmd: './verify'})"},
            )
            with mock.patch.object(MODULE.Path, "cwd", return_value=root):
                self.assertFalse(MODULE.blocks(direct))
                self.assertFalse(MODULE.blocks(nested))

    def test_allows_known_non_pr_python_module_runners(self) -> None:
        commands = (
            "python3 -m unittest tests.test_example",
            "python -m unittest discover -s tests",
            "python3 -m pytest -q",
            "python3 -m py_compile src/example.py",
            "python3 -m compileall src",
            "python3 -m ruff check .",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assert_direct_and_nested_allowed(command)

    def test_blocks_unknown_or_locally_shadowed_python_modules(self) -> None:
        request = payload("Bash", {"command": "python3 -m arbitrary.runner"})
        self.assertTrue(MODULE.blocks(request))
        self.assertIn("python module", MODULE._block_message(request))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative_path in (
                "unittest.py",
                "pytest/__init__.py",
                "ruff/__main__.py",
            ):
                candidate = root / relative_path
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text("print('shadowed')\n", encoding="utf-8")
                command = f"python3 -m {relative_path.split('/', 1)[0].removesuffix('.py')}"
                with self.subTest(relative_path=relative_path):
                    shadowed = payload(
                        "Bash", {"command": command, "workdir": str(root)}
                    )
                    self.assertTrue(MODULE.blocks(shadowed))
                    self.assertIn("python module", MODULE._block_message(shadowed))

    def test_blocks_python_module_runners_with_an_overridden_import_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            injected = root / "injected"
            injected.mkdir()
            (injected / "unittest.py").write_text(
                "print('shadowed')\n", encoding="utf-8"
            )
            clean_workdir = root / "clean"
            clean_workdir.mkdir()
            for command in (
                f"PYTHONPATH={shlex.quote(str(injected))} python3 -m unittest",
                f"env PYTHONPATH={shlex.quote(str(injected))} python3 -m unittest",
            ):
                with self.subTest(command=command):
                    request = payload(
                        "Bash", {"command": command, "workdir": str(clean_workdir)}
                    )
                    self.assertTrue(MODULE.blocks(request))
                    self.assertIn("python module", MODULE._block_message(request))

    def test_shell_parse_only_modes_do_not_execute_inspected_source(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as script:
            script.write('for item in "$inventory"; do gh pr ready 7; done\n')
            script.flush()
            path = shlex.quote(script.name)
            for command in (
                f"zsh -n {path}",
                f"bash --noexec {path}",
                f"fish --no-execute {path}",
                "zsh -n",
                "bash --noexec",
                "fish --no-execute",
            ):
                with self.subTest(command=command):
                    self.assert_direct_and_nested_allowed(command)

    def test_shell_parse_only_lookalikes_and_execution_remain_guarded(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as script:
            script.write("gh pr ready 7\n")
            script.flush()
            path = shlex.quote(script.name)
            for command in (
                f"zsh {path}",
                f"bash --norc {path}",
                "zsh -c 'gh pr ready 7'",
            ):
                with self.subTest(command=command):
                    self.assertTrue(MODULE.blocks(payload("Bash", {"command": command})))

    def test_blocks_source_less_interpreters_that_can_execute_stdin(self) -> None:
        commands = (
            "printf '%s\\n' 'gh pr ready 7' | sh",
            "printf '%s\\n' 'gh pr ready 7' | bash",
            "printf '%s\\n' 'import os; os.system(\"gh pr ready 7\")' | python3",
            "printf '%s\\n' 'require(\"child_process\").execSync(\"gh pr ready 7\")' | node",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assert_direct_and_nested_blocked(command)

    def test_inspects_only_statically_provable_sourced_scripts(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as script:
            script.write("git status --short\n")
            script.flush()
            path = shlex.quote(script.name)
            self.assertFalse(
                MODULE.blocks(payload("Bash", {"command": f"source {path}"}))
            )
            self.assertFalse(
                MODULE.blocks(
                    payload(
                        "Bash",
                        {"command": f'SCRIPT={path}; source "$SCRIPT"'},
                    )
                )
            )
            self.assertFalse(
                MODULE.blocks(payload("Bash", {"command": f"builtin source {path}"}))
            )
            script.seek(0)
            script.truncate()
            script.write("gh pr ready 7\n")
            script.flush()
            self.assertTrue(
                MODULE.blocks(payload("Bash", {"command": f"source {path}"}))
            )
            self.assert_direct_and_nested_blocked(f"builtin source {path}")
        self.assertTrue(MODULE.blocks(payload("Bash", {"command": 'source "$SCRIPT"'})))

    def test_resolves_static_gh_aliases_and_blocks_unproven_gh_routes(self) -> None:
        aliases = {
            "pe": "pr edit",
            "nested": "pe",
            "pv": "pr view",
            "shell-edit": '!gh pr edit "$1" --title bad',
        }
        with mock.patch.object(MODULE, "_gh_aliases", return_value=aliases):
            self.assertTrue(
                MODULE.blocks(payload("Bash", {"command": "gh pe 7 --title changed"}))
            )
            self.assertTrue(
                MODULE.blocks(
                    payload("Bash", {"command": "gh nested 7 --title changed"})
                )
            )
            self.assertFalse(MODULE.blocks(payload("Bash", {"command": "gh pv 7"})))
            shell_alias = payload(
                "Bash", {"command": "gh shell-edit 7 --title changed"}
            )
            self.assertTrue(MODULE.blocks(shell_alias))
            self.assertIn("`gh alias shell-edit`", MODULE._block_message(shell_alias))

        with mock.patch.object(MODULE, "_gh_aliases", return_value={}):
            extension = payload(
                "Bash", {"command": "gh some-extension 7 --title changed"}
            )
            self.assertTrue(MODULE.blocks(extension))
            message = MODULE._block_message(extension)
            self.assertIn("`gh some-extension`", message)
            self.assertIn("safety could not be proven", message)
            self.assertTrue(
                MODULE.blocks(payload("Bash", {"command": "gh pr future-operation 7"}))
            )
            extension_exec = payload(
                "Bash", {"command": "gh extension exec custom-pr-editor 7"}
            )
            self.assertTrue(MODULE.blocks(extension_exec))
            self.assertIn("`gh extension exec`", MODULE._block_message(extension_exec))
            self.assertFalse(
                MODULE.blocks(payload("Bash", {"command": "gh repo view"}))
            )
            self.assertFalse(MODULE.blocks(payload("Bash", {"command": "gh version"})))
            self.assertFalse(
                MODULE.blocks(payload("Bash", {"command": "gh --version"}))
            )

    def test_caches_gh_alias_discovery(self) -> None:
        MODULE._gh_aliases.cache_clear()
        response = mock.Mock(
            returncode=0,
            stdout="co: pr checkout\npe: pr edit\n",
        )
        with mock.patch.object(MODULE.subprocess, "run", return_value=response) as run:
            self.assertEqual(MODULE._gh_aliases()["pe"], "pr edit")
            self.assertEqual(MODULE._gh_aliases()["pe"], "pr edit")
        self.assertEqual(run.call_count, 1)
        MODULE._gh_aliases.cache_clear()

    def test_names_unproven_nested_route_at_outer_tool_boundary(self) -> None:
        code = "await tools.exec_command({cmd: 'gh some-extension 7 --title changed'})"
        request = payload("functions.exec", {"code": code})
        with mock.patch.object(MODULE, "_gh_aliases", return_value={}):
            self.assertTrue(MODULE.blocks(request))
            message = MODULE._block_message(request)
        self.assertIn("`gh some-extension`", message)
        self.assertIn("this tool boundary", message)
        self.assertIn("delegated tool", message)

    def test_blocks_nested_exec_command(self) -> None:
        commands = ("gh pr create --fill", "gh -R acme/app pr create -f")
        for command in commands:
            with self.subTest(command=command):
                code = f"await tools.exec_command({{cmd: '{command}'}})"
                self.assertTrue(
                    MODULE.blocks(payload("functions.exec", {"code": code}))
                )
        escaped = (
            'await tools.exec_command({cmd: "gh pr create --title \\"x\\" --fill"})'
        )
        self.assertTrue(MODULE.blocks(payload("functions.exec", {"code": escaped})))
        raw = "await tools.exec_command({cmd: 'gh pr create --fill'})"
        self.assertTrue(MODULE.blocks({"tool_name": "exec", "tool_input": raw}))

        decoy_commands = (
            "await tools.exec_command({/* cmd: 'git status' */ cmd: 'gh pr create --fill'})",
            "await tools.exec_command({note: \"cmd: 'git status'\", cmd: 'gh pr create --fill'})",
        )
        for code in decoy_commands:
            with self.subTest(code=code):
                self.assertTrue(
                    MODULE.blocks(payload("functions.exec", {"code": code}))
                )

    def test_fails_closed_for_unresolved_nested_calls(self) -> None:
        code_samples = (
            "await tools.exec_command({cmd: `gh pr create ${fillFlag}`})",
            r"await tools.exec_command({cmd: `\x67h pr create --fill`})",
            r"await tools.exec_command({cmd: `\u0067h pr create --fill`})",
            "const note = `status ${await tools.exec_command({cmd: 'gh pr create --fill'})}`",
            "const note = `status ${/}/.test('}') && await tools.exec_command({cmd: 'gh pr create --fill'})}`",
            "const note = `status ${await tools.github__update_pull_request({pull_number: 1, body: 'bad'})}`",
            "await tools.codex_apps__github_create_pull_request({title: 'x', body: 'generated'})",
            "await tools.github__update_pull_request({pull_number: 1, body: 'generated'})",
        )
        for code in code_samples:
            with self.subTest(code=code):
                self.assertTrue(
                    MODULE.blocks(payload("functions.exec", {"code": code}))
                )
        self.assertFalse(
            MODULE.blocks(
                payload(
                    "functions.exec",
                    {"code": "await tools[`clock__curr_time`]({})"},
                )
            )
        )
        for code in (
            "await tools['github__update_pull_request']({pull_number: 2})",
            "await tools?.['github__update_pull_request']({pull_number: 2})",
            "await tools['github__update_issue']({issue_number: 2})",
        ):
            with self.subTest(code=code):
                self.assertFalse(
                    MODULE.blocks(payload("functions.exec", {"code": code}))
                )

        benign = "await tools.exec_command({cmd: 'git status --short'})"
        self.assertFalse(MODULE.blocks(payload("functions.exec", {"code": benign})))
        benign_interpolation = "const note = `status ${summary}`; return note"
        self.assertFalse(
            MODULE.blocks(payload("functions.exec", {"code": benign_interpolation}))
        )
        safe_tool_interpolation = (
            "const note = `status ${await tools.exec_command({cmd: 'git status'})}`"
        )
        self.assertFalse(
            MODULE.blocks(payload("functions.exec", {"code": safe_tool_interpolation}))
        )
        literal_tool_text = (
            "const note = `tools.exec_command({cmd: 'gh pr create --fill'})`; "
            "return note"
        )
        self.assertFalse(
            MODULE.blocks(payload("functions.exec", {"code": literal_tool_text}))
        )

    def test_allows_statically_resolved_unrelated_nested_commands(self) -> None:
        code_samples = (
            "const command = 'git status'; await tools.exec_command({cmd: command})",
            "const chars = 'git status\\n'; await tools.write_stdin({chars})",
        )
        for code in code_samples:
            with self.subTest(code=code):
                self.assertFalse(
                    MODULE.blocks(payload("functions.exec", {"code": code}))
                )

        dangerous = (
            "const pr_command = 'gh pr create --fill'; "
            "await tools.exec_command({cmd: pr_command})"
        )
        self.assertTrue(MODULE.blocks(payload("functions.exec", {"code": dangerous})))
        computed_pr = (
            "const command = buildPrCommand(); await tools.exec_command({cmd: command})"
        )
        self.assertTrue(MODULE.blocks(payload("functions.exec", {"code": computed_pr})))

    def test_fails_closed_for_opaque_computed_commands_and_connector_aliases(
        self,
    ) -> None:
        code_samples = (
            "const command = makeCommand(); await tools.exec_command({cmd: command})",
            "await tools.exec_command({cmd: ['gh', 'pr', 'create'].join(' ')})",
            "const call = tools.github__create_pull_request; await call({body: 'bad'})",
            "await tools['github__create_pull_request']({body: 'bad'})",
            "await tools['github__mark_pull_request_ready_for_review']({pull_number: 2})",
            "const ready = tools['github__mark_pull_request_ready_for_review']; "
            "await ready({pull_number: 2})",
            "const optional_call = tools?.github__update_pull_request; "
            "await optional_call?.({pull_number: 2, body: 'bad'})",
            "const optional_ready = tools?.['github__mark_pull_request_ready_for_review']; "
            "await optional_ready?.({pull_number: 2})",
            'const op = "update_" + "pull_request"; '
            "await tools[op]({pull_number: 2, body: 'bad'})",
            "await tools[`github__update_pull_request`]({pull_number: 2, body: 'bad'})",
            "await tools[`github__mark_pull_request_ready_for_review`]({pull_number: 2})",
            "await tools.github__update_pull_request?.({pull_number: 2, body: 'bad'})",
            "await tools?.['github__update_pull_request']({pull_number: 2, body: 'bad'})",
            "await tools['github__update_pull_request']?.({pull_number: 2, body: 'bad'})",
            "await tools?.[`github__update_pull_request`]({pull_number: 2, body: 'bad'})",
        )
        for code in code_samples:
            with self.subTest(code=code):
                self.assertTrue(
                    MODULE.blocks(payload("functions.exec", {"code": code}))
                )
        self.assertFalse(
            MODULE.blocks(
                payload(
                    "functions.exec",
                    {
                        "code": "await tools[`github__update_pull_request`]({pull_number: 2})"
                    },
                )
            )
        )

    def test_fails_closed_for_indirect_nested_shell_tool_routes(self) -> None:
        code_samples = (
            'await tools["exec_command"]({cmd: "gh pr ready 7"})',
            "const run = tools.exec_command; await run({cmd: 'gh pr ready 7'})",
            "await Reflect.apply(tools.exec_command, tools, [{cmd: 'gh pr ready 7'}])",
            "const write = tools.write_stdin; "
            "await write({session_id: 1, chars: 'gh pr ready 7\\n'})",
            "await tools.exec_command?.({cmd: 'gh pr ready 7'})",
            "await tools.exec_command.call(tools, {cmd: 'gh pr ready 7'})",
            "await tools.exec_command.apply(tools, [{cmd: 'gh pr ready 7'}])",
            "const {exec_command: run} = tools; await run({cmd: 'gh pr ready 7'})",
            "const {exec_command: run, write_stdin: write} = tools; "
            "await run({cmd: 'gh pr ready 7'})",
            "await tools[`exec_command`]({cmd: 'gh pr ready 7'})",
            "await tools[`write_stdin`]({session_id: 1, chars: 'gh pr ready 7\\n'})",
            "await tools?.[`exec_command`]({cmd: 'gh pr ready 7'})",
            "await tools?.['write_stdin']({session_id: 1, chars: 'gh pr ready 7\\n'})",
            "await tools[`exec_command`]?.({cmd: 'gh pr ready 7'})",
            "const optional = tools.exec_command; "
            "await optional?.({cmd: 'gh pr ready 7'})",
        )
        for code in code_samples:
            with self.subTest(code=code):
                request = payload("functions.exec", {"code": code})
                self.assertTrue(MODULE.blocks(request))
                self.assertIn("unproven nested", MODULE._block_message(request))

    def test_ignores_javascript_comments_and_string_mentions(self) -> None:
        code_samples = (
            "// await tools.exec_command({cmd: 'gh pr create --fill'})\nconst ok = true",
            "/* tools.github__create_pull_request({body: 'bad'}) */ const ok = true",
            "const example = \"tools.exec_command({cmd: 'gh pr create --fill'})\"",
        )
        for code in code_samples:
            with self.subTest(code=code):
                self.assertFalse(
                    MODULE.blocks(payload("functions.exec", {"code": code}))
                )

    def test_guards_write_stdin_commands(self) -> None:
        self.assertTrue(
            MODULE.blocks(
                payload(
                    "write_stdin",
                    {"session_id": "12", "chars": "gh pr create --fill\\n"},
                )
            )
        )
        self.assertFalse(
            MODULE.blocks(
                payload("write_stdin", {"session_id": "12", "chars": "echo ok\\n"})
            )
        )

    def test_recurses_into_shell_command_strings(self) -> None:
        blocked_commands = (
            "bash -lc 'gh pr create --fill'",
            "env zsh -c 'gh pr edit 7 --title bad'",
            "if true; then gh pr create --fill; fi",
            "while true; do gh pr create --fill; done",
            'bash -c "$PR_COMMAND"',
        )
        for command in blocked_commands:
            with self.subTest(command=command):
                self.assertTrue(MODULE.blocks(payload("Bash", {"command": command})))

        self.assertFalse(
            MODULE.blocks(
                payload("Bash", {"command": "bash -c 'echo gh pr create --fill'"})
            )
        )
        self.assertFalse(
            MODULE.blocks(payload("Bash", {"command": "bash -c 'echo $HOME'"}))
        )

    def test_blocks_raw_creation_even_with_transport_body(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as body_file:
            body_file.write(
                "<!-- publishing-reviewable-prs: canonical body pending GitHub PR identity -->\n"
            )
            body_file.flush()
            command = (
                "gh -R owner/repo pr create --title 'feat: good' --body-file "
                + shlex.quote(body_file.name)
            )
            self.assertTrue(MODULE.blocks(payload("Bash", {"command": command})))

        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as body_file:
            body_file.write(CANONICAL_BODY)
            body_file.flush()
            command = (
                "gh -R owner/repo pr create --title 'feat: guessed' --body-file "
                + shlex.quote(body_file.name)
            )
            self.assertTrue(MODULE.blocks(payload("Bash", {"command": command})))

    def test_allows_only_well_formed_owned_creator_invocation(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as template:
            template.write("template")
            template.flush()
            command = (
                'python3 "$HOME/.agents/skills/publishing-reviewable-prs/'
                'scripts/create_reviewable_pr.py" --repository acme/app --base main '
                f"--base-oid {'a' * 40} --head acme:widget --head-oid {'b' * 40} "
                "--head-owner acme --title 'feat: widget' --body-template "
                + shlex.quote(template.name)
            )
            self.assertFalse(MODULE.blocks(payload("Bash", {"command": command})))

            wrong_script = command.replace(
                "$HOME/.agents/skills/publishing-reviewable-prs/scripts/",
                "/private/tmp/",
            )
            self.assertTrue(MODULE.blocks(payload("Bash", {"command": wrong_script})))
            relative_template = command.replace(template.name, "template.md")
            self.assertTrue(
                MODULE.blocks(payload("Bash", {"command": relative_template}))
            )
            missing_oid = command.replace(f"--head-oid {'b' * 40} ", "")
            self.assertTrue(MODULE.blocks(payload("Bash", {"command": missing_oid})))
            unqualified_head = command.replace("--head acme:widget", "--head widget")
            self.assertTrue(
                MODULE.blocks(payload("Bash", {"command": unqualified_head}))
            )
            mismatched_owner = command.replace(
                "--head-owner acme", "--head-owner other"
            )
            self.assertTrue(
                MODULE.blocks(payload("Bash", {"command": mismatched_owner}))
            )
            self.assertTrue(
                MODULE.blocks(
                    payload(
                        "Bash", {"command": command.replace("python3 ", "python3 -u ")}
                    )
                )
            )

    def test_allows_only_exact_owned_updater_invocations(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as body_file:
            body_file.write(CANONICAL_BODY)
            body_file.flush()
            script = (
                'python3 "$HOME/.agents/skills/publishing-reviewable-prs/'
                'scripts/update_reviewable_pr.py"'
            )
            common = (
                f" --repository acme/app --pr 2 --base main --base-oid {'a' * 40}"
                f" --head acme:widget --head-oid {'b' * 40} --head-owner acme"
                f" --expected-title-sha256 {'c' * 64}"
                f" --expected-body-sha256 {'d' * 64}"
            )
            text_command = (
                script
                + " text"
                + common
                + " --expected-state draft --title changed --body-file "
                + shlex.quote(body_file.name)
            )
            ready_command = script + " ready" + common
            self.assertFalse(MODULE.blocks(payload("Bash", {"command": text_command})))
            self.assertFalse(MODULE.blocks(payload("Bash", {"command": ready_command})))
            aliased_python = "PYTHON=python3; $PYTHON" + text_command.removeprefix(
                "python3"
            )
            self.assertFalse(
                MODULE.blocks(payload("Bash", {"command": aliased_python}))
            )

            blocked_commands = (
                text_command.replace(
                    "update_reviewable_pr.py", "/tmp/update_reviewable_pr.py"
                ),
                text_command.replace("--head acme:widget", "--head widget"),
                text_command.replace("--head-owner acme", "--head-owner other"),
                text_command.replace(f" --expected-body-sha256 {'d' * 64}", ""),
                text_command.replace(
                    "--expected-state draft", "--expected-state invalid"
                ),
                text_command + " --unexpected value",
                ready_command + " --title changed",
                text_command.replace("python3 ", "python3 -u "),
            )
            for command in blocked_commands:
                with self.subTest(command=command):
                    self.assertTrue(
                        MODULE.blocks(payload("Bash", {"command": command}))
                    )

    def test_requires_absolute_literal_body_file(self) -> None:
        blocked_commands = (
            "gh pr create --title 'feat: bad' --body-file body.md",
            'gh pr create --title "$title" --body-file "$body_file"',
            "gh pr edit 101 -tchanged -Fbody.md",
        )
        for command in blocked_commands:
            with self.subTest(command=command):
                self.assertTrue(
                    MODULE.blocks(
                        payload("Bash", {"command": command, "workdir": "/private/tmp"})
                    )
                )

    def test_blocks_raw_cli_text_edits_even_with_canonical_body(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as body_file:
            body_file.write(CANONICAL_BODY)
            body_file.flush()
            body_path = shlex.quote(body_file.name)
            command = f"gh -Racme/app pr edit 2 -tchanged -F{body_path}"
            self.assertTrue(MODULE.blocks(payload("Bash", {"command": command})))
        self.assertTrue(
            MODULE.blocks(
                payload("Bash", {"command": "gh -R owner/repo pr edit 101 -tbad"})
            )
        )

    def test_allows_fill_text_in_non_shell_patch(self) -> None:
        code = "await tools.apply_patch('Never run gh pr create --fill')"
        self.assertFalse(MODULE.blocks(payload("functions.exec", {"code": code})))

    def test_allows_fill_text_as_shell_data(self) -> None:
        commands = (
            "rg -n 'gh pr create --fill' .",
            "printf '%s\\n' 'gh pr create --fill'",
            "echo gh pr create --fill",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertFalse(MODULE.blocks(payload("Bash", {"command": command})))

    def test_ignores_shell_comments_and_nonexecuted_heredoc_data(self) -> None:
        commands = (
            "echo ok # gh pr create --fill",
            "cat <<'EOF'\ngh pr create --fill\nEOF\n",
            "cat > /tmp/example <<EOF\ngh pr edit 2 --title bad\nEOF\n",
            "printf '%s\\n' '<<EOF'",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertFalse(MODULE.blocks(payload("Bash", {"command": command})))

    def test_inspects_shell_heredocs_and_blocks_api_stdin(self) -> None:
        commands = (
            "bash <<'EOF'\ngh pr create --fill\nEOF\n",
            "gh api repos/acme/app/pulls/7 --input - <<'EOF'\n"
            '{"body":"generated"}\nEOF\n',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(MODULE.blocks(payload("Bash", {"command": command})))

    def test_blocks_fill_after_shell_control_operator(self) -> None:
        self.assertTrue(
            MODULE.blocks(
                payload("Bash", {"command": "cd /tmp && gh pr create --fill"})
            )
        )

    def test_blocks_connector_pr_creation_without_canonical_body(self) -> None:
        for body in (None, "", "## Summary\nGenerated text"):
            with self.subTest(body=body):
                self.assertTrue(
                    MODULE.blocks(
                        {
                            "tool_name": "codex_apps__github_create_pull_request",
                            "tool_input": {"title": "feat: widget", "body": body},
                        }
                    )
                )

    def test_blocks_noncanonical_cli_create_and_text_edit(self) -> None:
        commands = (
            "gh pr create --title 'feat: bad' --body 'generated summary'",
            "gh pr edit 42 --title 'feat: changed'",
            "gh pr edit 42 --body 'generated summary'",
            "gh -R acme/app pr ready 42",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(MODULE.blocks(payload("Bash", {"command": command})))

    def test_blocks_connector_pr_creation_with_exact_transport(self) -> None:
        self.assertTrue(
            MODULE.blocks(
                {
                    "tool_name": "github__create_pull_request",
                    "tool_input": {
                        "title": "feat: widget",
                        "body": "<!-- publishing-reviewable-prs: canonical body pending GitHub PR identity -->\n",
                    },
                }
            )
        )
        self.assertTrue(
            MODULE.blocks(
                {
                    "tool_name": "codex_apps__github_update_pull_request",
                    "tool_input": {"pr_number": 1, "body": None},
                }
            )
        )

    def test_guards_connector_title_and_body_updates(self) -> None:
        self.assertTrue(
            MODULE.blocks(
                {
                    "tool_name": "github__update_pull_request",
                    "tool_input": {"title": "feat: changed"},
                }
            )
        )
        self.assertTrue(
            MODULE.blocks(
                {
                    "tool_name": "github__update_pull_request",
                    "tool_input": {"pull_number": 2, "draft": False},
                }
            )
        )
        self.assertTrue(
            MODULE.blocks(
                {
                    "tool_name": "github__mark_pull_request_ready_for_review",
                    "tool_input": {"pull_number": 2},
                }
            )
        )
        self.assertTrue(
            MODULE.blocks(
                {
                    "tool_name": "github__update_pull_request",
                    "tool_input": {
                        "repository_full_name": "acme/app",
                        "pull_number": 2,
                        "title": "feat: changed",
                        "body": CANONICAL_BODY,
                    },
                }
            )
        )

    def test_blocks_raw_cli_edits_regardless_of_identity(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as body_file:
            body_file.write(CANONICAL_BODY)
            body_file.flush()
            path = shlex.quote(body_file.name)
            valid = f"gh -R acme/app pr edit 2 --title changed --body-file {path}"
            self.assertTrue(MODULE.blocks(payload("Bash", {"command": valid})))
            invalid_commands = (
                f"gh pr edit 2 --title changed --body-file {path}",
                f"gh -R other/repo pr edit 2 --title changed --body-file {path}",
                f"gh -R acme/app pr edit branch --title changed --body-file {path}",
            )
            for command in invalid_commands:
                with self.subTest(command=command):
                    self.assertTrue(
                        MODULE.blocks(payload("Bash", {"command": command}))
                    )

    def test_blocks_rest_api_pr_text_mutations(self) -> None:
        commands = (
            "gh api repos/acme/app/pulls -X POST -f title=x -f body=generated",
            "gh api repos/{owner}/{repo}/pulls -X POST -f title=x -f body=generated",
            "gh api -X PATCH repos/acme/app/pulls/7 -f body=generated",
            "gh api -X PATCH repos/{owner}/{repo}/pulls/7 -f body=generated",
            "gh api -X PATCH repos/acme/app/pulls/7 -F draft=false",
            "gh api repos/acme/app/issues/7 --method PATCH --raw-field title=x",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(MODULE.blocks(payload("Bash", {"command": command})))

        self.assertFalse(
            MODULE.blocks(payload("Bash", {"command": "gh api repos/acme/app/pulls/7"}))
        )

    def test_blocks_direct_curl_rest_and_graphql_pr_mutations(self) -> None:
        commands = (
            "curl -X PATCH https://api.github.com/repos/acme/app/pulls/7 "
            '-d \'{"title":"changed"}\'',
            "curl --request POST https://api.github.com/repos/acme/app/pulls "
            '--data \'{"title":"created"}\'',
            "curl https://api.github.com/graphql --json "
            '\'{"query":"mutation { updatePullRequest(input: {}) { clientMutationId } }"}\'',
            "curl -XPATCH https://api.github.com/repos/acme/app/pulls/7 "
            '-d\'{"title":"changed"}\'',
            "curl -X PATCH https://API.GITHUB.COM/repos/acme/app/pulls/7 "
            '-d \'{"title":"changed"}\'',
            "curl -X PATCH https://api.github.com/repos/acme/app/pulls/7 "
            "--data-urlencode title=changed",
            "BASE=https://api.github.com/repos/acme/app; "
            'curl -X PATCH "${BASE}/pulls/7" -d \'{"title":"changed"}\'',
            "wget --method=PATCH "
            '--body-data=\'{"title":"changed"}\' '
            "https://api.github.com/repos/acme/app/pulls/7",
            "wget --method=PATCH "
            '--post-data=\'{"title":"changed"}\' '
            "https://api.github.com/repos/acme/app/pulls/7",
            "BASE=xhttps://api.github.com/repos/acme/app/pulls/7; "
            'curl -XPATCH "${BASE#x}" -d\'{"title":"changed"}\'',
            "HOST=api.github.com; "
            'curl -XPATCH "https://${HOST}/repos/acme/app/pulls/7" '
            '-d\'{"title":"changed"}\'',
            r'''curl -X PATCH https://api.github.com/repos/acme/app/pulls/7 --json '{"bo\u0064y":"changed"}' ''',
            r'''curl -X PATCH https://api.github.com/repos/acme/app/pulls/7 -H 'Content-Type: application/json' --data-binary '{"ti\u0074le":"changed"}' ''',
            r'''curl -X PATCH https://api.github.com/repos/acme/app/pulls/7 --json '{"dra\u0066t":false}' ''',
            r'''curl -X PATCH https://api.github.com/repos/acme/app/pulls/7 --json '{"bo\u0064y":' ''',
            r'''curl https://api.github.com/graphql --json '{"query":"mu\u0074ation { updatePullRequest(input: {}) { clientMutationId } }"}' ''',
            r'''curl https://api.github.com/graphql --json '{"query":' ''',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assert_direct_and_nested_blocked(command)

        self.assertFalse(
            MODULE.blocks(
                payload(
                    "Bash",
                    {"command": "curl https://api.github.com/repos/acme/app/pulls/7"},
                )
            )
        )
        self.assert_direct_and_nested_allowed(
            """curl -X PATCH https://api.github.com/repos/acme/app/pulls/7 --json '{"labels":["safe"]}'"""
        )
        self.assert_direct_and_nested_allowed(
            """curl https://api.github.com/graphql --json '{"query":"query { viewer { login } }"}'"""
        )
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as config:
            config.write(
                "url = https://api.github.com/repos/acme/app/pulls/7\n"
                "request = PATCH\n"
                'data = {"title":"changed"}\n'
            )
            config.flush()
            self.assert_direct_and_nested_blocked(
                f"curl --config {shlex.quote(config.name)}"
            )
            self.assert_direct_and_nested_blocked(
                f"wget --config {shlex.quote(config.name)}"
            )

    def test_blocks_python_http_client_pr_mutations(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".py"
        ) as script:
            script.write(
                "import requests\n"
                "requests.patch("
                "'https://api.github.com/repos/acme/app/pulls/7', "
                "json={'title': 'changed'})\n"
            )
            script.flush()
            self.assert_direct_and_nested_blocked(f"python3 {shlex.quote(script.name)}")
            script.seek(0)
            script.write(
                "import requests\n"
                "def build_payload():\n    return {'title': 'changed'}\n"
                "requests.patch("
                "'https://api.github.com/repos/acme/app/pulls/7', "
                "build_payload())\n"
            )
            script.truncate()
            script.flush()
            self.assert_direct_and_nested_blocked(f"python3 {shlex.quote(script.name)}")
            script.seek(0)
            script.write(
                "import requests\nsession = requests.Session()\n"
                "session.request("
                "'PATCH', 'https://api.github.com/repos/acme/app/pulls/7', "
                "{'title': 'changed'})\n"
            )
            script.truncate()
            script.flush()
            self.assert_direct_and_nested_blocked(f"python3 {shlex.quote(script.name)}")
            script.seek(0)
            script.write(
                "import subprocess\nrunner = subprocess.run\n"
                "runner(['gh', 'pr', 'ready', '7'])\n"
            )
            script.truncate()
            script.flush()
            self.assert_direct_and_nested_blocked(f"python3 {shlex.quote(script.name)}")
            script.seek(0)
            script.write(
                "import subprocess\n(run, show) = (subprocess.run, print)\n"
                "run(['gh', 'pr', 'ready', '7'])\n"
            )
            script.truncate()
            script.flush()
            self.assert_direct_and_nested_blocked(f"python3 {shlex.quote(script.name)}")
            script.seek(0)
            script.write("import subprocess\nsubprocess.getoutput('gh pr ready 7')\n")
            script.truncate()
            script.flush()
            self.assert_direct_and_nested_blocked(f"python3 {shlex.quote(script.name)}")
            script.seek(0)
            script.write("import os\nos.execvp('gh', ['gh', 'pr', 'ready', '7'])\n")
            script.truncate()
            script.flush()
            self.assert_direct_and_nested_blocked(f"python3 {shlex.quote(script.name)}")
            script.seek(0)
            script.write(
                "import requests\nsession = requests.Session()\n"
                "session.patch("
                "'https://api.github.com/repos/acme/app/pulls/7', "
                "json=dict(title='changed'))\n"
            )
            script.truncate()
            script.flush()
            self.assert_direct_and_nested_blocked(f"python3 {shlex.quote(script.name)}")
            script.seek(0)
            script.write(
                "from urllib.request import Request, urlopen\n"
                "request = Request("
                "'https://api.github.com/repos/acme/app/pulls/7', "
                "data=b'{\"title\":\"changed\"}', method='PATCH')\n"
                "urlopen(request)\n"
            )
            script.truncate()
            script.flush()
            self.assert_direct_and_nested_blocked(f"python3 {shlex.quote(script.name)}")
            script.seek(0)
            script.write("import os\nos.execlp('gh', 'gh', 'pr', 'ready', '7')\n")
            script.truncate()
            script.flush()
            self.assert_direct_and_nested_blocked(f"python3 {shlex.quote(script.name)}")
            script.seek(0)
            script.write(
                "import subprocess\nrunner = also = subprocess.run\n"
                "runner(['gh', 'pr', 'ready', '7'])\n"
            )
            script.truncate()
            script.flush()
            self.assert_direct_and_nested_blocked(f"python3 {shlex.quote(script.name)}")

    def test_blocks_node_process_and_http_pr_mutations(self) -> None:
        sources = (
            "require('node:child_process').spawnSync('gh', ['pr', 'ready', '7'])",
            "require('node:child_process').execFileSync('gh', ['pr', 'ready', '7'])",
            "const {spawnSync: run} = require('node:child_process'); "
            "run('gh', ['pr', 'ready', '7'])",
            "import * as cp from 'node:child_process'; "
            "cp.spawnSync('gh', ['pr', 'ready', '7'])",
            "const cp = await import('node:child_process'); "
            "cp.spawnSync('gh', ['pr', 'ready', '7'])",
            "require('node:child_process').fork('mutate.js')",
            "fetch('https://api.github.com/repos/acme/app/pulls/7', "
            "{method: 'PATCH', body: JSON.stringify({title: 'changed'})})",
            "require('node:https').request("
            "'https://api.github.com/repos/acme/app/pulls/7', "
            "{method: 'PATCH'}, () => {}).end(buildPayload())",
            "fetch('https://api.github.com/graphql', {method: 'POST', "
            "body: JSON.stringify({query: 'mutation { updatePullRequest("
            "input: {}) { clientMutationId } }'})})",
        )
        for source in sources:
            with self.subTest(source=source):
                self.assert_direct_and_nested_blocked("node -e " + shlex.quote(source))

    def test_resolves_or_rejects_dynamic_sensitive_gh_arguments(self) -> None:
        blocked_commands = (
            'OPT=--title; gh pr edit 7 "$OPT" changed',
            'OPT=--body; gh issue edit 7 --repo acme/app "$OPT" changed',
            'ENDPOINT=repos/acme/app/pulls/7; gh api "$ENDPOINT" -X PATCH -f title=x',
            'METHOD=PATCH; gh api repos/acme/app/pulls/7 -X "$METHOD" -f title=x',
            'FIELD=title=x; gh api repos/acme/app/pulls/7 -X PATCH -f "$FIELD"',
            'gh api "$UNKNOWN_ENDPOINT" -X PATCH -f title=x',
            'OPT=x--title; gh pr edit 7 "${OPT#x}" changed',
            "ENDPOINT=xrepos/acme/app/pulls/7; "
            'gh api "${ENDPOINT#x}" -X PATCH -f title=x',
            'QUERY=xmutation; gh api graphql -f "query=${QUERY#x}"',
            "T=tion; gh api graphql -f "
            '"query=muta$T { updatePullRequest(input: {}) { clientMutationId } }"',
        )
        for command in blocked_commands:
            with self.subTest(command=command):
                self.assert_direct_and_nested_blocked(command)

        self.assertFalse(
            MODULE.blocks(
                payload(
                    "Bash",
                    {"command": 'OPT=--add-label; gh pr edit 7 "$OPT" bug'},
                )
            )
        )

    def test_classifies_cli_issue_edits_authoritatively(self) -> None:
        issue_title = "gh -R acme/app issue edit 7 --title changed"
        with mock.patch.object(MODULE, "_issue_target_kind", return_value="issue"):
            self.assertFalse(MODULE.blocks(payload("Bash", {"command": issue_title})))
        with mock.patch.object(
            MODULE, "_issue_target_kind", return_value="pull_request"
        ):
            self.assertTrue(MODULE.blocks(payload("Bash", {"command": issue_title})))
        with mock.patch.object(MODULE, "_issue_target_kind", return_value=None):
            self.assertTrue(MODULE.blocks(payload("Bash", {"command": issue_title})))

        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as body_file:
            body_file.write(CANONICAL_BODY)
            body_file.flush()
            command = (
                "gh -R acme/app issue edit 2 --title changed --body-file "
                + shlex.quote(body_file.name)
            )
            with mock.patch.object(
                MODULE, "_issue_target_kind", return_value="pull_request"
            ):
                self.assertTrue(MODULE.blocks(payload("Bash", {"command": command})))

    def test_parses_issue_selectors_after_text_flags(self) -> None:
        commands = (
            "gh -R acme/app issue edit --title changed 7",
            "gh -R acme/app issue edit --title=changed 7",
            "gh -R acme/app issue edit -tchanged 7",
            "gh issue edit 7 --repo acme/app --title changed",
            "gh issue edit 7 -Racme/app --title changed",
        )
        with mock.patch.object(MODULE, "_issue_target_kind", return_value="issue"):
            for command in commands:
                with self.subTest(command=command):
                    self.assertFalse(
                        MODULE.blocks(payload("Bash", {"command": command}))
                    )

    def test_malformed_hook_input_denies_loudly(self) -> None:
        for raw, route in (("not-json", "malformed"), ("[]", "non-object")):
            with self.subTest(raw=raw):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT)],
                    input=raw,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                output = json.loads(result.stderr)
                reason = output["hookSpecificOutput"]["permissionDecisionReason"]
                self.assertIn(route, reason)
                self.assertIn("safety could not be proven", reason)
                self.assertEqual(
                    output["hookSpecificOutput"]["permissionDecision"], "deny"
                )

    def test_rejects_multi_target_issue_edits_after_text_flags(self) -> None:
        command = "gh -R acme/app issue edit --title changed 7 8"
        request = payload("Bash", {"command": command})
        with mock.patch.object(MODULE, "_issue_target_kind") as classify:
            self.assertTrue(MODULE.blocks(request))
        classify.assert_not_called()
        self.assertIn("one issue number at a time", MODULE._block_message(request))

    def test_rejects_multi_target_issue_text_edits_before_lookup(self) -> None:
        command = "gh -R acme/app issue edit 7 8 --title changed"
        request = payload("Bash", {"command": command})
        with mock.patch.object(MODULE, "_issue_target_kind") as classify:
            self.assertTrue(MODULE.blocks(request))
        classify.assert_not_called()
        self.assertIn("one issue number at a time", MODULE._block_message(request))

    def test_caches_authoritative_issue_classification(self) -> None:
        MODULE._issue_target_kind.cache_clear()
        response = mock.Mock(
            returncode=0,
            stdout='{"number":7,"pull_request":{"url":"https://api.github.com/pulls/7"}}',
        )
        with mock.patch.object(MODULE.subprocess, "run", return_value=response) as run:
            self.assertEqual(MODULE._issue_target_kind("acme/app", 7), "pull_request")
            self.assertEqual(MODULE._issue_target_kind("acme/app", 7), "pull_request")
        self.assertEqual(run.call_count, 1)
        MODULE._issue_target_kind.cache_clear()

    def test_subprocess_calls_share_a_bounded_hook_deadline(self) -> None:
        response = mock.Mock(returncode=0, stdout="")
        with (
            mock.patch.object(MODULE, "_HOOK_DEADLINE", 110.0),
            mock.patch.object(
                MODULE.time, "monotonic", side_effect=(109.5, 110.1)
            ),
            mock.patch.object(
                MODULE.subprocess, "run", return_value=response
            ) as run,
        ):
            MODULE._budgeted_run(["gh", "--version"], check=False)
            self.assertAlmostEqual(run.call_args.kwargs["timeout"], 0.5)
            with self.assertRaises(subprocess.TimeoutExpired):
                MODULE._budgeted_run(["gh", "--version"], check=False)
        self.assertEqual(run.call_count, 1)

    def test_main_reuses_one_deadline_for_decision_and_message(self) -> None:
        observed_deadlines: list[float | None] = []

        def decide(_payload: dict[str, object]) -> bool:
            observed_deadlines.append(MODULE._HOOK_DEADLINE)
            return True

        def message(_payload: dict[str, object]) -> str:
            observed_deadlines.append(MODULE._HOOK_DEADLINE)
            return "blocked"

        request = payload("Bash", {"command": "gh pr ready 7"})
        with (
            mock.patch.object(MODULE, "_HOOK_DEADLINE", None),
            mock.patch.object(MODULE.time, "monotonic", return_value=100.0),
            mock.patch.object(MODULE.sys, "stdin", io.StringIO(json.dumps(request))),
            mock.patch.object(MODULE.sys, "stderr", io.StringIO()),
            mock.patch.object(MODULE, "blocks", side_effect=decide),
            mock.patch.object(MODULE, "_block_message", side_effect=message),
        ):
            self.assertEqual(MODULE.main(), 2)
        self.assertEqual(observed_deadlines, [110.0, 110.0])

    def test_classifies_rest_issue_edits_authoritatively(self) -> None:
        command = "gh api repos/acme/app/issues/7 -X PATCH -f title=changed"
        with mock.patch.object(MODULE, "_issue_target_kind", return_value="issue"):
            self.assertFalse(MODULE.blocks(payload("Bash", {"command": command})))
        with mock.patch.object(
            MODULE, "_issue_target_kind", return_value="pull_request"
        ):
            self.assertTrue(MODULE.blocks(payload("Bash", {"command": command})))
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as body_file:
                body_file.write(CANONICAL_BODY)
                body_file.flush()
                canonical_command = (
                    "gh api repos/acme/app/issues/7 -X PATCH -f body=@"
                    + shlex.quote(body_file.name)
                )
                self.assertTrue(
                    MODULE.blocks(payload("Bash", {"command": canonical_command}))
                )

    def test_classifies_issue_connectors_authoritatively(self) -> None:
        connector = {
            "tool_name": "github__update_issue",
            "tool_input": {
                "owner": "acme",
                "repo": "app",
                "issue_number": 7,
                "title": "changed",
            },
        }
        with mock.patch.object(MODULE, "_issue_target_kind", return_value="issue"):
            self.assertFalse(MODULE.blocks(connector))
        with mock.patch.object(
            MODULE, "_issue_target_kind", return_value="pull_request"
        ):
            self.assertTrue(MODULE.blocks(connector))
            canonical_connector = {
                **connector,
                "tool_input": {
                    **connector["tool_input"],
                    "body": CANONICAL_BODY,
                },
            }
            self.assertTrue(MODULE.blocks(canonical_connector))
        with mock.patch.object(MODULE, "_issue_target_kind", return_value=None):
            self.assertTrue(MODULE.blocks(connector))

    def test_classifies_nested_issue_connectors_without_comment_false_positives(
        self,
    ) -> None:
        actual = (
            "await tools.github__update_issue({owner: 'acme', repo: 'app', "
            "issue_number: 7, title: 'changed'})"
        )
        with mock.patch.object(MODULE, "_issue_target_kind", return_value="issue"):
            self.assertFalse(MODULE.blocks(payload("functions.exec", {"code": actual})))
        with mock.patch.object(
            MODULE, "_issue_target_kind", return_value="pull_request"
        ):
            self.assertTrue(MODULE.blocks(payload("functions.exec", {"code": actual})))

        quoted_keys = (
            'await tools.github__update_issue({"owner": "acme", "repo": "app", '
            '"issue_number": 7, "title": "changed"})'
        )
        with mock.patch.object(
            MODULE, "_issue_target_kind", return_value="pull_request"
        ):
            self.assertTrue(
                MODULE.blocks(payload("functions.exec", {"code": quoted_keys}))
            )
        self.assertTrue(
            MODULE.blocks(
                payload(
                    "functions.exec",
                    {"code": "await tools.github__update_issue({...payload})"},
                )
            )
        )

    def test_blocks_graphql_pr_text_mutations(self) -> None:
        mutation = (
            "gh api graphql -f "
            "'query=mutation { updatePullRequest(input: {}) { pullRequest { id } } }'"
        )
        self.assertTrue(MODULE.blocks(payload("Bash", {"command": mutation})))
        ready_mutation = (
            "gh api graphql -f "
            "'query=mutation { markPullRequestReadyForReview(input: {}) "
            "{ pullRequest { id } } }'"
        )
        self.assertTrue(MODULE.blocks(payload("Bash", {"command": ready_mutation})))
        self.assertTrue(
            MODULE.blocks(
                payload("Bash", {"command": "gh api graphql -f query=$QUERY"})
            )
        )
        query = "gh api graphql -f 'query=query { viewer { login } }'"
        self.assertFalse(MODULE.blocks(payload("Bash", {"command": query})))

        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as query_file:
            query_file.write(
                '{"query":"mutation { updateIssue(input: {}) { issue { id } } }"}'
            )
            query_file.flush()
            command = "gh api graphql --input " + shlex.quote(query_file.name)
            self.assertFalse(MODULE.blocks(payload("Bash", {"command": command})))

        issue_text_mutation = (
            "gh api graphql "
            "-f 'query=mutation($id: ID!, $title: String!) { "
            "updateIssue(input: {id: $id, title: $title}) { issue { id } } }' "
            "-f id=I_kwDOExample -f title=changed"
        )
        with mock.patch.object(
            MODULE,
            "_graphql_node_identity",
            return_value=("issue", ("acme/app", 7)),
        ):
            self.assertFalse(
                MODULE.blocks(payload("Bash", {"command": issue_text_mutation}))
            )
        with mock.patch.object(MODULE, "_graphql_node_identity", return_value=None):
            self.assertTrue(
                MODULE.blocks(payload("Bash", {"command": issue_text_mutation}))
            )
        with mock.patch.object(
            MODULE,
            "_graphql_node_identity",
            return_value=("pull_request", ("acme/app", 7)),
        ):
            self.assertTrue(
                MODULE.blocks(payload("Bash", {"command": issue_text_mutation}))
            )
        self.assertFalse(
            MODULE.blocks(
                {
                    "tool_name": "github__update_pull_request",
                    "tool_input": {"state": "closed"},
                }
            )
        )

    def test_allows_unrelated_fill_flag(self) -> None:
        self.assertFalse(
            MODULE.blocks(payload("Bash", {"command": "some-tool --fill output.txt"}))
        )


if __name__ == "__main__":
    unittest.main()
