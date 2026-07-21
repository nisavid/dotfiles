#!/usr/bin/env python3
"""Statically block recognized noncanonical GitHub PR publication routes."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from functools import lru_cache
import hashlib
import importlib.util
import json
import os
import posixpath
import re
import shlex
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


JAVASCRIPT_LITERAL = r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`"
NESTED_EXEC_CALL_RE = re.compile(r"\bexec_command\s*\(")
NESTED_WRITE_STDIN_CALL_RE = re.compile(r"\bwrite_stdin\s*\(")
SHELL_OPERATORS = {";", "&&", "||", "|", "(", ")", "{", "}"}
SHELL_OPERATOR_CHARACTERS = set(";&|()!\n")
SHELL_INTERPRETERS = {"bash", "dash", "fish", "ksh", "sh", "zsh"}
SHELL_PARSE_ONLY_LONG_OPTIONS = {"--noexec", "--no-exec", "--no-execute"}
HOOK_SUBPROCESS_BUDGET_SECONDS = 10.0
SUBPROCESS_TIMEOUT_SECONDS = 4.0
MAX_TRUSTED_BYTECODE_BYTES = 1_048_576
_HOOK_DEADLINE: float | None = None
PYTHON_NON_PR_MODULE_RUNNERS = {
    "compileall",
    "py_compile",
    "pytest",
    "ruff",
    "unittest",
}
CONTROL_PREFIXES = {
    "!",
    "command",
    "do",
    "elif",
    "exec",
    "if",
    "then",
    "time",
    "until",
    "while",
}
GH_GLOBAL_VALUE_OPTIONS = {"-R", "--repo", "--hostname"}
REPOSITORY_RE = re.compile(r"(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)")
OID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
PR_URL_RE = re.compile(
    r"https://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/pull/(?P<pr>\d+)/?"
)
ISSUE_URL_RE = re.compile(
    r"https://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/issues/(?P<issue>\d+)/?"
)
PR_CREATE_VALUE_OPTIONS = {
    "-a",
    "--assignee",
    "-B",
    "--base",
    "-b",
    "--body",
    "-F",
    "--body-file",
    "-H",
    "--head",
    "-l",
    "--label",
    "-m",
    "--milestone",
    "-p",
    "--project",
    "--recover",
    "-r",
    "--reviewer",
    "-T",
    "--template",
    "-t",
    "--title",
}
PR_CREATE_VALUE_SHORT_OPTIONS = {
    option[1:] for option in PR_CREATE_VALUE_OPTIONS if len(option) == 2
}
GH_API_VALUE_OPTIONS = {
    "-F",
    "--field",
    "-H",
    "--header",
    "--cache",
    "--hostname",
    "--input",
    "-p",
    "--preview",
    "-f",
    "--raw-field",
    "-q",
    "--jq",
    "-t",
    "--template",
    "-X",
    "--method",
}
GH_API_VALUE_SHORT_OPTIONS = {"F", "H", "f", "p", "q", "t", "X"}
ISSUE_EDIT_VALUE_OPTIONS = {
    "--add-assignee",
    "--add-label",
    "--add-project",
    "-b",
    "--body",
    "-F",
    "--body-file",
    "-m",
    "--milestone",
    "--remove-assignee",
    "--remove-label",
    "--remove-milestone",
    "--remove-project",
    "-t",
    "--title",
}
ISSUE_EDIT_VALUE_SHORT_OPTIONS = {
    option[1:] for option in ISSUE_EDIT_VALUE_OPTIONS if len(option) == 2
}
GH_SAFE_TOP_LEVEL_COMMANDS = {
    "alias",
    "attestation",
    "auth",
    "browse",
    "cache",
    "codespace",
    "completion",
    "config",
    "extension",
    "gist",
    "help",
    "label",
    "org",
    "release",
    "repo",
    "ruleset",
    "run",
    "search",
    "secret",
    "ssh-key",
    "status",
    "variable",
    "version",
    "workflow",
}
GH_SAFE_PR_OPERATIONS = {
    "checks",
    "checkout",
    "close",
    "comment",
    "diff",
    "list",
    "lock",
    "merge",
    "reopen",
    "review",
    "status",
    "unlock",
    "view",
}
GH_SAFE_ISSUE_OPERATIONS = {
    "close",
    "comment",
    "create",
    "delete",
    "develop",
    "list",
    "lock",
    "pin",
    "reopen",
    "status",
    "transfer",
    "unlock",
    "unpin",
    "view",
}
SHELL_META_RE = re.compile(r"[$`*?\[\]{}]")
DYNAMIC_COMMAND_RE = re.compile(r"^\s*(?:\$\{?[A-Za-z_]|\$\(|`)")
SHELL_VARIABLE_RE = re.compile(
    r"^\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))$"
)
SHELL_ASSIGNMENT_RE = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$")
GRAPHQL_DYNAMIC_VALUE_RE = re.compile(r"^\$[A-Za-z_][A-Za-z0-9_]*$")
REST_PULLS_RE = re.compile(r"(?:^|/)repos/[^/]+/[^/]+/pulls(?:/(?P<number>\d+))?/?$")
REST_ISSUE_RE = re.compile(
    r"(?:^|/)repos/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<number>\d+)/?$"
)
REST_REVIEW_REPLY_ROUTE_RE = re.compile(
    r"^repos/[^/]+/[^/]+/pulls/[^/]+/comments/?$"
)
REST_REVIEW_REPLY_RE = re.compile(
    r"^repos/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/"
    r"(?P<repo>[A-Za-z0-9_.-]+)/pulls/(?P<number>[1-9][0-9]*)/comments/?$"
)
GRAPHQL_DIRECT_PR_MUTATION_RE = re.compile(
    r"\b(?:createPullRequest|updatePullRequest|markPullRequestReadyForReview)\b",
    re.I,
)
GRAPHQL_UPDATE_ISSUE_RE = re.compile(r"\bupdateIssue\b", re.I)
GRAPHQL_RESOLVE_REVIEW_THREAD_RE = re.compile(r"\bresolveReviewThread\b", re.I)
GRAPHQL_RESOLVE_REVIEW_THREAD_QUERY_RE = re.compile(
    r"^mutation\(\$(?P<variable>[A-Za-z_][A-Za-z0-9_]*):ID!\)"
    r"\{resolveReviewThread\(input:\{threadId:\$(?P=variable)\}\)"
    r"\{thread\{(?:id\s+isResolved|isResolved\s+id)\}\}\}$"
)
VALIDATOR = (
    Path.home()
    / ".agents/skills/writing-reviewable-pr-descriptions/scripts/validate_change_navigation.py"
)
PUBLISHER = (
    Path.home()
    / ".agents/skills/publishing-reviewable-prs/scripts/reviewable_pr.py"
)
PUBLISHER_ARGUMENTS = {
    str(PUBLISHER),
}
EXPANDABLE_PUBLISHER_ARGUMENTS = {
    "$HOME/.agents/skills/publishing-reviewable-prs/scripts/reviewable_pr.py",
    "${HOME}/.agents/skills/publishing-reviewable-prs/scripts/reviewable_pr.py",
}
UPDATER = (
    Path.home()
    / ".agents/skills/publishing-reviewable-prs/scripts/update_reviewable_pr.py"
)
UPDATER_ARGUMENTS = {
    str(UPDATER),
}
EXPANDABLE_UPDATER_ARGUMENTS = {
    "$HOME/.agents/skills/publishing-reviewable-prs/scripts/update_reviewable_pr.py",
    "${HOME}/.agents/skills/publishing-reviewable-prs/scripts/update_reviewable_pr.py",
}
REVIEWABLE_PR_STATE = (
    Path.home()
    / ".agents/skills/publishing-reviewable-prs/scripts/reviewable_pr_state.py"
)
TRUSTED_HELP_ONLY_SCRIPTS = {
    PUBLISHER: "bf6f16692097d72fdb9008450577852069da95fe948e14875662802a2c95236d",
    UPDATER: "8af340214cfc19e1e6b4ce885a90af4f795307b846363a8b8ececde47632da43",
    REVIEWABLE_PR_STATE: (
        "f06c51077e814ff689a995aff75cb08bbe609507b588349e7838f4c8eb901a4c"
    ),
}
BYTECODE_VALIDATOR_SOURCE = """\
import importlib.util
import marshal
import os
import sys
import types

try:
    limit = int(sys.argv[1])
    for index in range(2, len(sys.argv), 5):
        source_path, cache_path, optimization, device, inode = sys.argv[index : index + 5]
        with open(source_path, "rb") as source_file:
            expected = compile(
                source_file.read(),
                source_path,
                "exec",
                dont_inherit=True,
                optimize=int(optimization),
            )
        with open(cache_path, "rb") as cache_file:
            status = os.fstat(cache_file.fileno())
            if status.st_dev != int(device) or status.st_ino != int(inode):
                raise ValueError("cache identity changed")
            bytecode = cache_file.read(limit + 1)
        if (
            not 16 <= len(bytecode) <= limit
            or bytecode[:4] != importlib.util.MAGIC_NUMBER
        ):
            raise ValueError("invalid bytecode cache")
        cached = marshal.loads(bytecode[16:])
        if not isinstance(cached, types.CodeType) or cached != expected:
            raise ValueError("bytecode mismatch")
except BaseException:
    sys.exit(1)
"""
REVIEW_STATE = (
    Path.home()
    / ".agents/skills/pr-review-orchestration/scripts/pr_review_state.py"
)
REVIEW_STATE_SHA256 = "3c5f280740fd6e6dfb8d49bb63f99430464bcddd0a608ee4c35689cf00eaf177"
TRUSTED_TASK_TEST_COMMAND = (
    "zsh tooling/hindsight/tests/hindsight-memory-controller.zsh"
)
TRUSTED_TASK_TEST_REPOSITORY = "nisavid/agents"
TRUSTED_TASK_TEST_PATH = Path(
    "tooling/hindsight/tests/hindsight-memory-controller.zsh"
)
TRUSTED_TASK_TEST_TREE_PATH = Path("tooling/hindsight")
TRUSTED_TASK_TEST_TREE = "d51a23a4c49ce9fecd6de53e94cda3063bbc171b"


def _has_exact_expandable_helper_spelling(command: str) -> bool:
    paths = (
        *EXPANDABLE_PUBLISHER_ARGUMENTS,
        *EXPANDABLE_UPDATER_ARGUMENTS,
    )
    return any(
        re.match(
            rf'^\s*(?:python|python3)\s+"{re.escape(path)}"(?:\s|$)',
            command,
        )
        is not None
        for path in paths
    )


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _strings(nested)


def _budgeted_run(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    timeout = SUBPROCESS_TIMEOUT_SECONDS
    if _HOOK_DEADLINE is not None:
        timeout = min(timeout, _HOOK_DEADLINE - time.monotonic())
        if timeout <= 0:
            raise subprocess.TimeoutExpired(arguments, 0)
    return subprocess.run(arguments, timeout=timeout, **kwargs)


def _decode_javascript_literal(literal: str) -> str | None:
    if literal.startswith("`"):
        source = literal[1:-1]
        value: list[str] = []
        index = 0
        while index < len(source):
            if source.startswith("${", index):
                return None
            if source[index] != "\\":
                value.append(source[index])
                index += 1
                continue
            if index + 1 >= len(source) or source[index + 1] not in "\\`":
                return None
            value.append(source[index + 1])
            index += 2
        return "".join(value)
    try:
        value = ast.literal_eval(literal)
    except (SyntaxError, ValueError):
        return None
    return value if isinstance(value, str) else None


def _mask_javascript_strings_and_comments(code: str) -> str:
    """Preserve source positions while hiding non-code occurrences."""
    masked = list(code)
    index = 0
    while index < len(code):
        if code.startswith("//", index):
            end = code.find("\n", index)
            end = len(code) if end < 0 else end
            masked[index:end] = " " * (end - index)
            index = end
            continue
        if code.startswith("/*", index):
            end = code.find("*/", index + 2)
            end = len(code) if end < 0 else end + 2
            for position in range(index, end):
                if code[position] != "\n":
                    masked[position] = " "
            index = end
            continue
        if code[index] not in "'\"`":
            index += 1
            continue
        quote = code[index]
        index += 1
        while index < len(code):
            if code[index] == "\\":
                masked[index] = " "
                if index + 1 < len(code):
                    masked[index + 1] = " "
                index += 2
                continue
            if code[index] == quote:
                index += 1
                break
            if code[index] != "\n":
                masked[index] = " "
            index += 1
    return "".join(masked)


def _mask_javascript_comments(code: str) -> str:
    masked = list(code)
    quote: str | None = None
    index = 0
    while index < len(code):
        if quote is not None:
            if code[index] == "\\":
                index += 2
                continue
            if code[index] == quote:
                quote = None
            index += 1
            continue
        if code[index] in "'\"`":
            quote = code[index]
            index += 1
            continue
        if code.startswith("//", index):
            end = code.find("\n", index)
            end = len(code) if end < 0 else end
            masked[index:end] = " " * (end - index)
            index = end
            continue
        if code.startswith("/*", index):
            end = code.find("*/", index + 2)
            end = len(code) if end < 0 else end + 2
            for position in range(index, end):
                if code[position] != "\n":
                    masked[position] = " "
            index = end
            continue
        index += 1
    return "".join(masked)


def _javascript_template_interpolations(code: str) -> tuple[list[str], bool]:
    """Return executable `${...}` expressions without treating template text as code."""
    expressions: list[str] = []

    def skip_quoted(index: int, quote: str) -> tuple[int, bool]:
        index += 1
        while index < len(code):
            if code[index] == "\\":
                index += 2
                continue
            if code[index] == quote:
                return index + 1, False
            index += 1
        return index, True

    def skip_comment(index: int) -> tuple[int, bool]:
        if code.startswith("//", index):
            end = code.find("\n", index + 2)
            return (len(code) if end < 0 else end), False
        end = code.find("*/", index + 2)
        return (len(code), True) if end < 0 else (end + 2, False)

    def scan_expression(index: int) -> tuple[int, bool]:
        start = index
        depth = 1
        while index < len(code):
            if code.startswith(("//", "/*"), index):
                index, unresolved = skip_comment(index)
                if unresolved:
                    return index, True
                continue
            # Regex literals can contain braces, so a slash needs a full parser.
            if code[index] == "/":
                return index, True
            if code[index] in "'\"":
                index, unresolved = skip_quoted(index, code[index])
                if unresolved:
                    return index, True
                continue
            if code[index] == "`":
                index, unresolved = scan_template(index)
                if unresolved:
                    return index, True
                continue
            if code[index] == "{":
                depth += 1
            elif code[index] == "}":
                depth -= 1
                if depth == 0:
                    expressions.append(code[start:index])
                    return index + 1, False
            index += 1
        return index, True

    def scan_template(index: int) -> tuple[int, bool]:
        index += 1
        while index < len(code):
            if code[index] == "\\":
                index += 2
                continue
            if code[index] == "`":
                return index + 1, False
            if code.startswith("${", index):
                index, unresolved = scan_expression(index + 2)
                if unresolved:
                    return index, True
                continue
            index += 1
        return index, True

    index = 0
    unresolved = False
    while index < len(code):
        if code.startswith(("//", "/*"), index):
            index, unresolved = skip_comment(index)
        elif code[index] in "'\"":
            index, unresolved = skip_quoted(index, code[index])
        elif code[index] == "`":
            index, unresolved = scan_template(index)
        else:
            index += 1
        if unresolved:
            return expressions, True
    return expressions, False


def _javascript_string_bindings(code: str, masked: str) -> dict[str, str | None]:
    bindings: dict[str, str | None] = {}
    declaration_re = re.compile(
        r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*"
    )
    for match in declaration_re.finditer(masked):
        value_start = match.end()
        if value_start >= len(code) or code[value_start] not in "'\"`":
            expression = masked[value_start : value_start + 300].split(";", 1)[0]
            bindings[match.group("name")] = (
                "'suspicious'"
                if re.search(r"(?:\b(?:pr|pull)\b|(?:Pr|Pull)[A-Z])", expression)
                else None
            )
            continue
        literal_match = re.match(JAVASCRIPT_LITERAL, code[value_start:], re.S)
        if literal_match is None:
            bindings[match.group("name")] = None
            continue
        literal = literal_match.group(0)
        value = _decode_javascript_literal(literal)
        if value is None and re.search(
            r"\bgh\s+(?:\S+\s+)*pr\s+(?:create|new|edit)\b", literal
        ):
            bindings[match.group("name")] = literal
        else:
            bindings[match.group("name")] = value
    return bindings


def _nested_literal_commands(
    code: str, call_re: re.Pattern[str]
) -> tuple[list[tuple[str, str | None]], bool]:
    masked = _mask_javascript_strings_and_comments(code)
    bindings = _javascript_string_bindings(code, masked)
    commands: list[tuple[str, str | None]] = []
    suspicious_unresolved = False
    for call in call_re.finditer(masked):
        call_end = _javascript_call_end(masked, call.end() - 1)
        call_source = code[call.start() : call_end]
        workdir, unresolved_workdir = _javascript_literal_property(
            call_source, "workdir"
        )
        if unresolved_workdir:
            suspicious_unresolved = True
        property_name = "cmd" if "exec_command" in call.group(0) else "chars"
        call_masked = masked[call.start() : call_end]
        call_tail = call_masked[call.end() - call.start() :]
        property_match = re.search(
            rf"\b{property_name}\s*:\s*", call_masked
        )
        value_start = (
            call.start() + property_match.end()
            if property_match is not None
            else None
        )
        literal_match = (
            re.match(
                rf"\s*(?P<literal>{JAVASCRIPT_LITERAL})",
                code[value_start:],
                re.S,
            )
            if value_start is not None
            else None
        )
        if literal_match is not None:
            literal = literal_match.group("literal")
            command = _decode_javascript_literal(literal)
            if command is not None:
                commands.append((command, workdir))
            else:
                suspicious_unresolved = True
            continue
        name_match = (
            re.match(
                r"\s*(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)",
                masked[value_start:],
            )
            if value_start is not None
            else None
        )
        if name_match is None:
            shorthand_match = re.search(
                rf"(?:\{{|,)\s*{property_name}\s*(?:,|\}})", call_tail
            )
            if shorthand_match is None:
                suspicious_unresolved = True
                continue
            name = property_name
        else:
            name = name_match.group("name")
        value = bindings.get(name)
        if value is None:
            suspicious_unresolved = True
        elif value.startswith(("'", '"', "`")):
            suspicious_unresolved = True
        else:
            commands.append((value, workdir))
    return commands, suspicious_unresolved


def _javascript_literal_property(
    source: str, property_name: str
) -> tuple[str | None, bool]:
    masked = _mask_javascript_strings_and_comments(source)
    match = re.search(rf"\b{re.escape(property_name)}\s*:\s*", masked)
    if match is None:
        return None, False
    literal_match = re.match(
        rf"\s*(?P<literal>{JAVASCRIPT_LITERAL})", source[match.end() :], re.S
    )
    if literal_match is None:
        return None, True
    value = _decode_javascript_literal(literal_match.group("literal"))
    return value, value is None


def _javascript_call_end(masked: str, open_parenthesis: int) -> int:
    depth = 0
    for index in range(open_parenthesis, len(masked)):
        if masked[index] == "(":
            depth += 1
        elif masked[index] == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    return len(masked)


def _javascript_connector_input(call_source: str) -> tuple[dict[str, Any], bool]:
    masked = _mask_javascript_strings_and_comments(call_source)
    open_parenthesis = masked.find("(")
    if open_parenthesis < 0:
        return {}, True
    argument_source = call_source[open_parenthesis + 1 : -1]
    argument_masked = masked[open_parenthesis + 1 : -1]
    leading = len(argument_masked) - len(argument_masked.lstrip())
    if leading >= len(argument_masked) or argument_masked[leading] != "{":
        return {}, True
    depth = 0
    object_end: int | None = None
    for index in range(leading, len(argument_masked)):
        if argument_masked[index] == "{":
            depth += 1
        elif argument_masked[index] == "}":
            depth -= 1
            if depth == 0:
                object_end = index
                break
    if object_end is None or argument_masked[object_end + 1 :].strip() not in {"", ","}:
        return {}, True

    object_source = argument_source[leading + 1 : object_end]
    object_masked = argument_masked[leading + 1 : object_end]
    entry_start = 0
    delimiters: list[str] = []
    pairs = {"(": ")", "[": "]", "{": "}"}
    entry_ranges: list[tuple[int, int]] = []
    for index, character in enumerate(object_masked):
        if character in pairs:
            delimiters.append(pairs[character])
        elif character in ")]}" and delimiters:
            if character != delimiters.pop():
                return {}, True
        elif character == "," and not delimiters:
            entry_ranges.append((entry_start, index))
            entry_start = index + 1
    if delimiters:
        return {}, True
    entry_ranges.append((entry_start, len(object_source)))

    properties: list[tuple[str, str]] = []
    protected_shorthand = {"title", "body", "draft", "isDraft", "is_draft"}
    property_re = re.compile(
        rf"\s*(?P<key>[A-Za-z_$][A-Za-z0-9_$]*|{JAVASCRIPT_LITERAL})"
        r"(?P<colon>\s*:\s*)?"
    )
    for start, end in entry_ranges:
        entry_source = object_source[start:end]
        entry_masked = object_masked[start:end]
        if not entry_masked.strip():
            continue
        property_match = property_re.match(entry_masked)
        if property_match is None:
            return {}, True
        raw_key = entry_source[
            property_match.start("key") : property_match.end("key")
        ]
        key = (
            _decode_javascript_literal(raw_key)
            if raw_key.startswith(("'", '"', "`"))
            else raw_key
        )
        if key is None:
            return {}, True
        if property_match.group("colon") is None:
            if entry_masked[property_match.end() :].strip() or key in protected_shorthand:
                return {}, True
            continue
        properties.append((key, entry_source[property_match.end() :].lstrip()))

    tool_input: dict[str, Any] = {}
    keys = (
        "repository_full_name",
        "repository",
        "owner",
        "repo",
        "pull_number",
        "pr_number",
        "pullNumber",
        "issue_number",
        "issueNumber",
        "number",
        "title",
        "body",
        "draft",
        "isDraft",
        "is_draft",
    )
    for key, value_source in properties:
        if key not in keys:
            continue
        if value_source.startswith(("'", '"', "`")):
            literal_match = re.match(
                JAVASCRIPT_LITERAL, value_source, re.S
            )
            if literal_match is not None:
                tool_input[key] = _decode_javascript_literal(literal_match.group(0))
                continue
        integer_match = re.match(r"\d+", value_source)
        boolean_match = re.match(r"(?:true|false)\b", value_source)
        if integer_match is not None:
            tool_input[key] = int(integer_match.group(0))
        elif boolean_match is not None:
            tool_input[key] = boolean_match.group(0) == "true"
        else:
            tool_input[key] = None
    return tool_input, False


def _nested_connector_is_noncanonical(code: str) -> bool:
    masked = _mask_javascript_strings_and_comments(code)
    connector_re = re.compile(
        r"(?<![A-Za-z0-9_$.])tools\s*(?:\?\.\s*|\.\s*)"
        r"(?P<name>[A-Za-z0-9_$]*(?:create|update)_"
        r"(?:pull_request|issue))\s*(?:\?\.\s*)?\("
    )

    def alias_is_invoked(alias: str, tail: str) -> bool:
        escaped = re.escape(alias)
        return bool(
            re.search(
                rf"\b{escaped}\s*(?:(?:\?\.\s*)?\(|(?:\?\.|\.)\s*"
                rf"(?:call|apply)\s*\(|(?:\?\.|\.)\s*bind\s*\([^)]*\)\s*\()",
                tail,
            )
            or re.search(rf"\bReflect\.apply\s*\(\s*{escaped}\b", tail)
        )
    for match in connector_re.finditer(masked):
        end = _javascript_call_end(masked, match.end() - 1)
        call_source = code[match.start() : end]
        call_masked = masked[match.start() : end]
        tool_input, unresolved_input = _javascript_connector_input(call_source)
        name = match.group("name").lower()
        if unresolved_input:
            return True
        if (
            name.endswith(("update_pull_request", "update_issue"))
            and "..." in call_masked
        ):
            return True
        if _connector_call_is_noncanonical(name, tool_input):
            return True
    receiver_alias_re = re.compile(
        r"\b(?:const|let|var)\s+(?P<alias>[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*"
        r"(?<![A-Za-z0-9_$.])tools\b"
    )
    for receiver_alias in receiver_alias_re.finditer(masked):
        alias = re.escape(receiver_alias.group("alias"))
        tail = masked[receiver_alias.end() :]
        receiver_member_re = re.compile(
            rf"\b{alias}\s*(?:\?\.\s*|\.\s*)[A-Za-z0-9_$]*"
            r"(?:(?:create|update)_(?:pull_request|issue)|"
            r"pull_request[A-Za-z0-9_$]*ready)[A-Za-z0-9_$]*",
            re.I,
        )
        for receiver_member in receiver_member_re.finditer(tail):
            expression = tail[receiver_member.start() : receiver_member.end()].strip()
            if alias_is_invoked(expression, tail[receiver_member.start() :]):
                return True
        if re.search(
            rf"\b{alias}\s*(?:\?\.\s*)?\[[^\]]+\]\s*(?:\?\.\s*)?\(",
            tail,
        ):
            return True
        destructured_from_alias = re.compile(
            rf"\b(?:const|let|var)\s*\{{(?P<members>[^{{}}]*)\}}\s*=\s*{alias}\b"
        )
        for destructured in destructured_from_alias.finditer(tail):
            invocation_tail = tail[destructured.end() :]
            for computed in re.finditer(
                r"(?:^|,)\s*\[[^\]]+\]\s*:\s*"
                r"(?P<alias>[A-Za-z_$][A-Za-z0-9_$]*)",
                destructured.group("members"),
            ):
                if alias_is_invoked(computed.group("alias"), invocation_tail):
                    return True
            for member in re.finditer(
                r"(?:^|,)\s*(?P<tool>[A-Za-z0-9_$]*"
                r"(?:(?:create|update)_(?:pull_request|issue)|"
                r"pull_request[A-Za-z0-9_$]*ready)[A-Za-z0-9_$]*)"
                r"\s*(?::\s*(?P<alias>[A-Za-z_$][A-Za-z0-9_$]*))?",
                destructured.group("members"),
                re.I,
            ):
                if alias_is_invoked(
                    member.group("alias") or member.group("tool"), invocation_tail
                ):
                    return True
    if re.search(
        r"(?<![A-Za-z0-9_$.])tools\s*(?:\?\.\s*|\.\s*)"
        r"[A-Za-z0-9_$]*(?:(?:mark|set|make)[A-Za-z0-9_$]*"
        r"pull_request[A-Za-z0-9_$]*ready|pull_request[A-Za-z0-9_$]*"
        r"(?:mark|set|make)[A-Za-z0-9_$]*ready)\s*(?:\?\.\s*)?\(",
        masked,
        re.I,
    ):
        return True
    comment_free = _mask_javascript_comments(code)
    alias_re = re.compile(
        r"\b(?:const|let|var)\s+(?P<alias>[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*"
        r"(?:tools(?:\?\.|\.)(?P<dot>[A-Za-z0-9_$]*(?:create|update)_"
        r"(?:pull_request|issue))|tools\s*(?:\?\.\s*)?\[\s*['\"](?P<bracket>[^'\"]*"
        r"(?:create|update)_(?:pull_request|issue))['\"]\s*\])"
    )
    for alias_match in alias_re.finditer(comment_free):
        declaration = alias_match.group(0).lstrip()
        declaration_start = alias_match.start() + len(alias_match.group(0)) - len(declaration)
        if re.match(r"(?:const|let|var)\b", masked[declaration_start:]) is None:
            continue
        if alias_is_invoked(alias_match.group("alias"), masked[alias_match.end() :]):
            return True
    destructured_alias_re = re.compile(
        r"\b(?:const|let|var)\s*\{(?P<members>[^{}]*)\}\s*=\s*tools\b"
    )
    destructured_member_re = re.compile(
        r"(?:^|,)\s*(?P<tool>[A-Za-z_$][A-Za-z0-9_$]*|"
        r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")"
        r"\s*(?::\s*(?P<alias>[A-Za-z_$][A-Za-z0-9_$]*))?"
    )
    for destructured in destructured_alias_re.finditer(masked):
        members_start, members_end = destructured.span("members")
        members = comment_free[members_start:members_end]
        members_masked = masked[members_start:members_end]
        for computed in re.finditer(
            r"(?:^|,)\s*\[[^\]]+\]\s*:\s*(?P<alias>[A-Za-z_$][A-Za-z0-9_$]*)",
            members_masked,
        ):
            if alias_is_invoked(
                computed.group("alias"), masked[destructured.end() :]
            ):
                return True
        for member in destructured_member_re.finditer(members_masked):
            raw_tool = member.group("tool")
            if raw_tool.startswith(("'", '"')):
                raw_tool = members[member.start("tool") : member.end("tool")]
            tool = (
                _decode_javascript_literal(raw_tool)
                if raw_tool.startswith(("'", '"'))
                else raw_tool
            )
            if tool is None or not (
                re.search(r"(?:create|update)_(?:pull_request|issue)$", tool, re.I)
                or _tool_is_ready_mutation(tool)
            ):
                continue
            alias = member.group("alias") or tool
            if alias_is_invoked(alias, masked[destructured.end() :]):
                return True
    ready_alias_re = re.compile(
        r"\b(?:const|let|var)\s+(?P<alias>[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*"
        r"(?:tools(?:\?\.|\.)(?P<dot>[A-Za-z0-9_$]*pull_request[A-Za-z0-9_$]*ready[A-Za-z0-9_$]*)"
        r"|tools\s*(?:\?\.\s*)?\[\s*['\"](?P<bracket>[^'\"]*pull_request[^'\"]*ready[^'\"]*)"
        r"['\"]\s*\])",
        re.I,
    )
    for alias_match in ready_alias_re.finditer(comment_free):
        declaration = alias_match.group(0).lstrip()
        declaration_start = alias_match.start() + len(alias_match.group(0)) - len(declaration)
        if re.match(r"(?:const|let|var)\b", masked[declaration_start:]) is None:
            continue
        tool = alias_match.group("dot") or alias_match.group("bracket")
        if _tool_is_ready_mutation(tool) and alias_is_invoked(
            alias_match.group("alias"), masked[alias_match.end() :]
        ):
            return True
    ready_bracket_call_re = re.compile(
        r"\btools\s*(?:\?\.\s*)?\[\s*['\"](?P<tool>[^'\"]*pull_request[^'\"]*ready[^'\"]*)"
        r"['\"]\s*\]\s*(?:\?\.\s*)?\(",
        re.I,
    )
    if any(
        _tool_is_ready_mutation(match.group("tool"))
        for match in ready_bracket_call_re.finditer(comment_free)
    ):
        return True
    computed_tool_call_re = re.compile(
        r"\btools\s*(?:\?\.\s*)?\[\s*(?P<property>[^\]\r\n]+?)\s*\]"
        r"\s*(?:\?\.\s*)?\("
    )
    for match in computed_tool_call_re.finditer(masked):
        property_source = code[match.start("property") : match.end("property")].strip()
        if re.fullmatch(JAVASCRIPT_LITERAL, property_source, re.S) is None:
            return True
        tool_name = _decode_javascript_literal(property_source)
        if tool_name is None:
            return True
        if tool_name in {"exec_command", "write_stdin"}:
            return True
        if _tool_is_ready_mutation(tool_name):
            return True
        if re.search(r"(?:create|update)_(?:pull_request|issue)$", tool_name, re.I):
            end = _javascript_call_end(masked, match.end() - 1)
            call_source = code[match.start() : end]
            call_masked = masked[match.start() : end]
            if tool_name.lower().endswith(("update_pull_request", "update_issue")) and (
                "..." in call_masked
            ):
                return True
            tool_input, unresolved_input = _javascript_connector_input(call_source)
            if unresolved_input or _connector_call_is_noncanonical(
                tool_name.lower(), tool_input
            ):
                return True
    return False


def _nested_shell_tool_route_is_unresolved(code: str) -> bool:
    masked = _mask_javascript_strings_and_comments(code)
    comment_free = _mask_javascript_comments(code)
    bracket_re = re.compile(
        r"\btools\s*(?:\?\.\s*)?\[\s*['\"](?:exec_command|write_stdin)['\"]\s*\]"
    )
    for match in bracket_re.finditer(comment_free):
        if masked[match.start() : match.start() + len("tools")] == "tools":
            return True

    alias_re = re.compile(
        r"\b(?:const|let|var)\s+(?P<alias>[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*"
        r"tools(?:\?\.|\.)(?:exec_command|write_stdin)\b"
    )
    for match in alias_re.finditer(masked):
        if re.search(
            rf"\b{re.escape(match.group('alias'))}\s*(?:\?\.\s*)?\(",
            masked[match.end() :],
        ):
            return True

    destructured_alias_re = re.compile(
        r"\b(?:const|let|var)\s*\{(?P<body>[^}]*)\}\s*=\s*tools\b"
    )
    for match in destructured_alias_re.finditer(masked):
        for alias_match in re.finditer(
            r"(?:^|,)\s*(?:exec_command|write_stdin)\s*:\s*"
            r"(?P<alias>[A-Za-z_$][A-Za-z0-9_$]*)\b",
            match.group("body"),
        ):
            if re.search(
                rf"\b{re.escape(alias_match.group('alias'))}\s*(?:\?\.\s*)?\(",
                masked[match.end() :],
            ):
                return True

    if re.search(
        r"\btools(?:\?\.|\.)(?:exec_command|write_stdin)\s*"
        r"(?:\?\.\s*\(|\.(?:call|apply)\s*\()",
        masked,
    ):
        return True

    return bool(
        re.search(
            r"\bReflect\.apply\s*\(\s*tools\.(?:exec_command|write_stdin)\b",
            masked,
        )
    )


def _candidate_commands(
    payload: dict[str, Any],
) -> tuple[list[tuple[str, str | None]], bool]:
    tool_name = str(payload.get("tool_name", "")).lower()
    tool_input = payload.get("tool_input", {})
    commands: list[tuple[str, str | None]] = []
    default_workdir = str(Path.cwd())
    if any(token in tool_name for token in ("bash", "shell", "exec_command")):
        if isinstance(tool_input, dict):
            workdir = tool_input.get("workdir")
            command_workdir = workdir if isinstance(workdir, str) else default_workdir
            for key in ("command", "cmd"):
                commands.extend(
                    (command, command_workdir)
                    for command in _strings(tool_input.get(key))
                )
        return commands, False
    if tool_name.endswith("write_stdin"):
        if isinstance(tool_input, dict):
            commands.extend(
                (command, None) for command in _strings(tool_input.get("chars"))
            )
        return commands, False
    if tool_name in {"functions.exec", "exec"}:
        code = (
            tool_input
            if isinstance(tool_input, str)
            else tool_input.get("code", "")
            if isinstance(tool_input, dict)
            else ""
        )
        if not isinstance(code, str):
            return commands, False
        interpolations, unresolved_interpolation = (
            _javascript_template_interpolations(code)
        )
        nested_exec_commands: list[tuple[str, str | None]] = []
        nested_stdin_commands: list[tuple[str, str | None]] = []
        unresolved_exec = unresolved_interpolation
        unresolved_stdin = False
        for fragment in (code, *interpolations):
            if _nested_connector_is_noncanonical(fragment):
                return commands, True
            if _nested_shell_tool_route_is_unresolved(fragment):
                return commands, True
            fragment_exec, fragment_unresolved_exec = _nested_literal_commands(
                fragment, NESTED_EXEC_CALL_RE
            )
            fragment_stdin, fragment_unresolved_stdin = _nested_literal_commands(
                fragment, NESTED_WRITE_STDIN_CALL_RE
            )
            nested_exec_commands.extend(fragment_exec)
            nested_stdin_commands.extend(fragment_stdin)
            unresolved_exec = unresolved_exec or fragment_unresolved_exec
            unresolved_stdin = unresolved_stdin or fragment_unresolved_stdin
        commands.extend(
            (command, workdir or default_workdir)
            for command, workdir in nested_exec_commands
        )
        commands.extend(nested_stdin_commands)
        return commands, unresolved_exec or unresolved_stdin
    return commands, False


def _shell_word_starts_at(command: str, index: int) -> bool:
    return index == 0 or command[index - 1].isspace() or command[index - 1] in ";&|()!"


def _without_shell_comments(command: str) -> str:
    masked = list(command)
    quote: str | None = None
    index = 0
    while index < len(command):
        character = command[index]
        if character == "\\" and quote != "'":
            index += 2
            continue
        if quote is not None:
            if character == quote:
                quote = None
            index += 1
            continue
        if character in "'\"":
            quote = character
            index += 1
            continue
        if character == "`":
            end = command.find("`", index + 1)
            index = len(command) if end < 0 else end + 1
            continue
        if command.startswith("$(", index) and not command.startswith("$((", index):
            end = _parenthesized_command_end(command, index + 2)
            index = len(command) if end is None else end + 1
            continue
        if character == "#" and _shell_word_starts_at(command, index):
            end = command.find("\n", index)
            end = len(command) if end < 0 else end
            masked[index:end] = " " * (end - index)
            index = end
            continue
        index += 1
    return "".join(masked)


class _ShellToken(str):
    literal_shell_meta_positions: frozenset[int]

    def __new__(
        cls, value: str, literal_shell_meta_positions: Iterable[int] = ()
    ) -> _ShellToken:
        token = super().__new__(cls, value)
        token.literal_shell_meta_positions = frozenset(literal_shell_meta_positions)
        return token


def _mask_literal_shell_meta(command: str) -> tuple[str, dict[str, str]]:
    markers = (
        character
        for character in (chr(codepoint) for codepoint in range(0xE000, 0xF900))
        if character not in command
    )
    literal_markers = {
        character: next(markers) for character in ("$", "`", "*", "?", "[")
    }
    masked: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(command):
        character = command[index]
        if character == "\\" and quote != "'":
            escaped = command[index + 1] if index + 1 < len(command) else None
            if escaped in literal_markers:
                masked.append(literal_markers[escaped])
            else:
                masked.append(character)
                if escaped is not None:
                    masked.append(escaped)
            index += 2
            continue
        if character in "'\"":
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            masked.append(character)
        elif quote == "'" and character in {"$", "`"}:
            masked.append(literal_markers[character])
        elif quote is not None and character in {"*", "?", "["}:
            masked.append(literal_markers[character])
        else:
            masked.append(character)
        index += 1
    return "".join(masked), literal_markers


def _segments(command: str) -> Iterable[list[str]]:
    try:
        masked, literal_markers = _mask_literal_shell_meta(
            _without_shell_comments(command)
        )
        lexer = shlex.shlex(
            masked,
            posix=True,
            punctuation_chars=";&|()!\n",
        )
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return
    restored: list[_ShellToken] = []
    literal_characters = {marker: value for value, marker in literal_markers.items()}
    for token in tokens:
        characters: list[str] = []
        literal_positions: list[int] = []
        for character in token:
            if character in literal_characters:
                character = literal_characters[character]
                literal_positions.append(len(characters))
            characters.append(character)
        restored.append(_ShellToken("".join(characters), literal_positions))
    tokens = restored
    current: list[str] = []
    for token in tokens:
        if token in SHELL_OPERATORS or (
            token and all(character in SHELL_OPERATOR_CHARACTERS for character in token)
        ):
            if current:
                yield current
                current = []
        else:
            current.append(token)
    if current:
        yield current


HEREDOC_OPERATOR_RE = re.compile(
    r"<<(?P<strip>-)?\s*(?P<quote>['\"]?)(?P<delimiter>[A-Za-z_][A-Za-z0-9_-]*)(?P=quote)"
)


def _heredoc_specs(line: str) -> list[tuple[int, str, bool]]:
    specs: list[tuple[int, str, bool]] = []
    quote: str | None = None
    index = 0
    while index < len(line):
        character = line[index]
        if character == "\\" and quote != "'":
            index += 2
            continue
        if quote is not None:
            if character == quote:
                quote = None
            index += 1
            continue
        if character in "'\"":
            quote = character
            index += 1
            continue
        if character == "#":
            break
        if line.startswith("<<", index) and not line.startswith("<<<", index):
            match = HEREDOC_OPERATOR_RE.match(line, index)
            if match is not None:
                specs.append(
                    (
                        match.start(),
                        match.group("delimiter"),
                        bool(match.group("strip")),
                    )
                )
                index = match.end()
                continue
        index += 1
    return specs


def _heredoc_receiver_is_shell(command_prefix: str) -> bool:
    segments = list(_segments(command_prefix))
    if not segments:
        return False
    segment = segments[-1]
    index = _skip_prefixes(segment)
    return (
        index < len(segment) and os.path.basename(segment[index]) in SHELL_INTERPRETERS
    )


def _without_heredoc_payloads(command: str) -> tuple[str, list[str]]:
    lines = command.splitlines(keepends=True)
    retained: list[str] = []
    shell_bodies: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        specs = _heredoc_specs(line)
        retained.append(line)
        index += 1
        for position, delimiter, strip_tabs in specs:
            body_lines: list[str] = []
            while index < len(lines):
                candidate = lines[index]
                comparison = candidate.rstrip("\r\n")
                if strip_tabs:
                    comparison = comparison.lstrip("\t")
                index += 1
                if comparison == delimiter:
                    break
                body_lines.append(candidate)
            if _heredoc_receiver_is_shell(line[:position]):
                shell_bodies.append("".join(body_lines))
    return "".join(retained), shell_bodies


def _parenthesized_command_end(command: str, start: int) -> int | None:
    depth = 1
    quote: str | None = None
    index = start
    while index < len(command):
        character = command[index]
        if character == "\\" and quote != "'":
            index += 2
            continue
        if quote == "'":
            if character == "'":
                quote = None
            index += 1
            continue
        if quote == '"':
            if character == '"':
                quote = None
            index += 1
            continue
        if character in "'\"":
            quote = character
            index += 1
            continue
        if character == "`":
            index += 1
            while index < len(command):
                if command[index] == "\\":
                    index += 2
                    continue
                if command[index] == "`":
                    break
                index += 1
            if index >= len(command):
                return None
            index += 1
            continue
        if command.startswith("$(", index) and not command.startswith("$((", index):
            depth += 1
            index += 2
            continue
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _shell_command_substitutions(command: str) -> tuple[list[str], bool]:
    substitutions: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(command):
        character = command[index]
        if character == "\\" and quote != "'":
            index += 2
            continue
        if quote == "'":
            if character == "'":
                quote = None
            index += 1
            continue
        if character == "'" and quote is None:
            quote = "'"
            index += 1
            continue
        if character == '"':
            quote = None if quote == '"' else '"'
            index += 1
            continue
        if character == "#" and quote is None and _shell_word_starts_at(command, index):
            newline = command.find("\n", index)
            index = len(command) if newline < 0 else newline + 1
            continue
        if character == "`":
            end = index + 1
            while end < len(command):
                if command[end] == "\\":
                    end += 2
                    continue
                if command[end] == "`":
                    break
                end += 1
            if end >= len(command):
                return substitutions, True
            substitutions.append(command[index + 1 : end])
            index = end + 1
            continue
        if command.startswith("$(", index) and not command.startswith("$((", index):
            end = _parenthesized_command_end(command, index + 2)
            if end is None:
                return substitutions, True
            substitutions.append(command[index + 2 : end])
            index = end + 1
            continue
        index += 1
    return substitutions, False


def _skip_wrapper(tokens: list[str], index: int) -> int:
    if index >= len(tokens):
        return index
    wrapper = os.path.basename(tokens[index])
    index += 1

    if wrapper == "nice":
        while index < len(tokens):
            token = tokens[index]
            if token == "--":
                return index + 1
            if token in {"-n", "--adjustment"}:
                index += 2
            elif token.startswith("--adjustment=") or re.fullmatch(r"-\d+", token):
                index += 1
            else:
                break
        return index

    if wrapper == "nohup":
        while index < len(tokens) and tokens[index].startswith("-"):
            if tokens[index] == "--":
                return index + 1
            index += 1
        return index

    if wrapper == "timeout":
        while index < len(tokens):
            token = tokens[index]
            if token == "--":
                index += 1
                break
            if token in {"-k", "--kill-after", "-s", "--signal"}:
                index += 2
            elif token.startswith(("--kill-after=", "--signal=")):
                index += 1
            elif token.startswith("-"):
                index += 1
            else:
                break
        return min(index + 1, len(tokens))

    if wrapper == "watch":
        value_options = {"-n", "--interval", "-x", "--exec"}
        while index < len(tokens):
            token = tokens[index]
            if token == "--":
                return index + 1
            if token in value_options:
                index += 2 if token in {"-n", "--interval"} else 1
            elif token.startswith("--interval=") or token.startswith("-"):
                index += 1
            else:
                break
        return index

    if wrapper == "xargs":
        value_options = {
            "-a",
            "--arg-file",
            "-d",
            "--delimiter",
            "-E",
            "--eof",
            "-I",
            "--replace",
            "-L",
            "--max-lines",
            "-n",
            "--max-args",
            "-P",
            "--max-procs",
            "-s",
            "--max-chars",
        }
        while index < len(tokens):
            token = tokens[index]
            if token == "--":
                return index + 1
            if token in value_options:
                index += 2
            elif any(token.startswith(f"{option}=") for option in value_options):
                index += 1
            elif token.startswith("-"):
                index += 1
            else:
                break
        return index

    return index - 1


def _skip_prefixes(tokens: list[str]) -> int:
    index = 0
    while index < len(tokens):
        previous = index
        while index < len(tokens) and re.match(
            r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[index]
        ):
            index += 1
        while index < len(tokens) and tokens[index] in CONTROL_PREFIXES:
            index += 1
        if index < len(tokens) and os.path.basename(tokens[index]) == "sudo":
            index += 1
            while index < len(tokens) and tokens[index].startswith("-"):
                if tokens[index] in {
                    "-u",
                    "--user",
                    "-g",
                    "--group",
                    "-h",
                    "--host",
                }:
                    index += 2
                else:
                    index += 1
        if index < len(tokens) and os.path.basename(tokens[index]) == "env":
            index += 1
            while index < len(tokens):
                token = tokens[index]
                if token == "--":
                    index += 1
                    break
                if token in {
                    "-u",
                    "--unset",
                    "-C",
                    "--chdir",
                    "-S",
                    "--split-string",
                }:
                    index += 2
                elif token.startswith("-") or re.match(
                    r"^[A-Za-z_][A-Za-z0-9_]*=", token
                ):
                    index += 1
                else:
                    break
        if index < len(tokens) and os.path.basename(tokens[index]) in {
            "nice",
            "nohup",
            "timeout",
            "watch",
            "xargs",
        }:
            wrapped_index = _skip_wrapper(tokens, index)
            if wrapped_index == index:
                break
            index = wrapped_index
        if index == previous:
            break
    return index


def _env_split_script(segment: list[str]) -> tuple[bool, str | None]:
    index = 0
    while index < len(segment) and SHELL_ASSIGNMENT_RE.fullmatch(segment[index]):
        index += 1
    while index < len(segment) and segment[index] in CONTROL_PREFIXES:
        index += 1
    if index < len(segment) and segment[index] == "sudo":
        index += 1
        while index < len(segment) and segment[index].startswith("-"):
            if segment[index] in {"-u", "--user", "-g", "--group", "-h", "--host"}:
                index += 2
            else:
                index += 1
    while index < len(segment) and os.path.basename(segment[index]) in {
        "nice",
        "nohup",
        "timeout",
        "xargs",
    }:
        wrapped_index = _skip_wrapper(segment, index)
        if wrapped_index == index:
            break
        index = wrapped_index
    if index >= len(segment) or os.path.basename(segment[index]) != "env":
        return False, None
    index += 1
    while index < len(segment):
        token = segment[index]
        if token in {"-S", "--split-string"}:
            if index + 1 >= len(segment):
                return True, None
            suffix = shlex.join(segment[index + 2 :])
            return True, segment[index + 1] + (f" {suffix}" if suffix else "")
        if token.startswith("--split-string="):
            suffix = shlex.join(segment[index + 1 :])
            value = token.split("=", 1)[1]
            return True, value + (f" {suffix}" if suffix else "")
        if token.startswith("-S") and token != "-S":
            suffix = shlex.join(segment[index + 1 :])
            return True, token[2:] + (f" {suffix}" if suffix else "")
        if token == "--":
            return False, None
        if token in {"-u", "--unset", "-C", "--chdir"}:
            index += 2
        elif token.startswith(("--unset=", "--chdir=")):
            index += 1
        elif token.startswith("-") or SHELL_ASSIGNMENT_RE.fullmatch(token):
            index += 1
        else:
            return False, None
    return False, None


def _watch_script(segment: list[str]) -> str | None:
    index = 0
    while index < len(segment):
        previous = index
        while index < len(segment) and re.match(
            r"^[A-Za-z_][A-Za-z0-9_]*=", segment[index]
        ):
            index += 1
        while index < len(segment) and segment[index] in CONTROL_PREFIXES:
            index += 1
        if index < len(segment) and os.path.basename(segment[index]) == "watch":
            command_index = _skip_wrapper(segment, index)
            return " ".join(segment[command_index:])
        if index < len(segment) and os.path.basename(segment[index]) in {
            "nice",
            "nohup",
            "timeout",
        }:
            index = _skip_wrapper(segment, index)
        if index == previous:
            break
    return None


def _nested_shell_script(segment: list[str]) -> str | None:
    index = _skip_prefixes(segment)
    if (
        index >= len(segment)
        or os.path.basename(segment[index]) not in SHELL_INTERPRETERS
    ):
        return None
    index += 1
    while index < len(segment):
        token = segment[index]
        if token in SHELL_PARSE_ONLY_LONG_OPTIONS or (
            token.startswith("-")
            and not token.startswith("--")
            and "n" in token[1:]
        ):
            return None
        if token in {"-c", "--command"} or (
            token.startswith("-") and not token.startswith("--") and "c" in token[1:]
        ):
            return segment[index + 1] if index + 1 < len(segment) else ""
        if token == "--":
            return None
        if not token.startswith("-"):
            return None
        index += 1
    return None


def _short_option_values(
    arguments: list[str], target_options: set[str], value_options: set[str]
) -> list[str]:
    values: list[str] = []
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if (
            not token.startswith("-")
            or token.startswith("--")
            or token == "-"
            or len(token) == 2
        ):
            index += 1
            continue
        characters = token[1:]
        for offset, short_option in enumerate(characters):
            if short_option not in value_options:
                continue
            remainder = characters[offset + 1 :]
            if short_option in target_options:
                if remainder:
                    values.append(remainder)
                elif index + 1 < len(arguments):
                    values.append(arguments[index + 1])
            break
        index += 1
    return values


def _option_values(
    arguments: list[str], options: set[str], value_short_options: set[str]
) -> list[str]:
    values: list[str] = []
    long_options = {option for option in options if option.startswith("--")}
    short_options = {option[1:] for option in options if len(option) == 2}
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token in options and index + 1 < len(arguments):
            values.append(arguments[index + 1])
            index += 2
            continue
        matched_long = False
        for option in long_options:
            if token.startswith(f"{option}="):
                values.append(token.split("=", 1)[1])
                matched_long = True
                break
        index += 1
        if matched_long:
            continue
    values.extend(_short_option_values(arguments, short_options, value_short_options))
    return values


def _normalize_repository(value: str | None) -> str | None:
    if value is None:
        return None
    match = REPOSITORY_RE.fullmatch(value)
    return value if match else None


def _issue_edit_arguments(
    arguments: list[str], repository: str | None
) -> tuple[list[str], str | None]:
    retained: list[str] = []
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token in GH_GLOBAL_VALUE_OPTIONS:
            if index + 1 >= len(arguments):
                return arguments, None
            if token in {"-R", "--repo"}:
                repository = _normalize_repository(arguments[index + 1])
            index += 2
            continue
        if token.startswith("-R") and token != "-R":
            repository = _normalize_repository(token[2:])
            index += 1
            continue
        if token.startswith("--repo="):
            repository = _normalize_repository(token.split("=", 1)[1])
            index += 1
            continue
        if token.startswith("--hostname="):
            index += 1
            continue
        retained.append(token)
        index += 1
    return retained, repository


@lru_cache(maxsize=1)
def _gh_aliases() -> dict[str, str]:
    try:
        result = _budgeted_run(
            ["gh", "alias", "list"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode:
        return {}
    aliases: dict[str, str] = {}
    for line in result.stdout.splitlines():
        name, separator, expansion = line.partition(":")
        if separator and name.strip() and expansion.strip():
            aliases[name.strip()] = expansion.strip()
    return aliases


def _gh_command(
    segment: list[str], seen_aliases: frozenset[str] = frozenset()
) -> tuple[str, list[str], str | None] | None:
    index = _skip_prefixes(segment)
    if index >= len(segment) or os.path.basename(segment[index]) != "gh":
        return None
    index += 1
    if segment[index:] == ["--version"]:
        return None
    repository: str | None = None
    while index < len(segment):
        token = segment[index]
        if token in GH_GLOBAL_VALUE_OPTIONS:
            if token in {"-R", "--repo"} and index + 1 < len(segment):
                repository = _normalize_repository(segment[index + 1])
            index += 2
        elif token.startswith("-R") and token != "-R":
            repository = _normalize_repository(token[2:])
            index += 1
        elif any(token.startswith(f"{option}=") for option in GH_GLOBAL_VALUE_OPTIONS):
            if token.startswith("--repo="):
                repository = _normalize_repository(token.split("=", 1)[1])
            index += 1
        elif token == "pr" and index + 1 < len(segment):
            operation = segment[index + 1]
            if operation in {"create", "new"}:
                return "create", segment[index + 2 :], repository
            if operation == "edit":
                return "edit", segment[index + 2 :], repository
            if operation == "ready":
                return "ready", segment[index + 2 :], repository
            if operation in GH_SAFE_PR_OPERATIONS:
                return None
            return "unproven", [f"gh pr {operation}"], repository
        elif token == "pr":
            return None
        elif token == "issue" and index + 1 < len(segment):
            if segment[index + 1] == "edit":
                arguments, issue_repository = _issue_edit_arguments(
                    segment[index + 2 :], repository
                )
                return "issue_edit", arguments, issue_repository
            if segment[index + 1] in GH_SAFE_ISSUE_OPERATIONS:
                return None
            return "unproven", [f"gh issue {segment[index + 1]}"], repository
        elif token == "issue":
            return None
        elif token == "api":
            return "api", segment[index + 1 :], repository
        elif (
            token == "extension"
            and index + 1 < len(segment)
            and segment[index + 1] == "exec"
        ):
            return "unproven", ["gh extension exec"], repository
        else:
            aliases = _gh_aliases()
            if token in aliases:
                if token in seen_aliases:
                    return "unproven", [f"gh alias {token}"], repository
                expansion = aliases[token]
                if expansion.startswith("!"):
                    return "unproven", [f"gh alias {token}"], repository
                try:
                    expanded = shlex.split(expansion)
                except ValueError:
                    return "unproven", [f"gh alias {token}"], repository
                if not expanded:
                    return "unproven", [f"gh alias {token}"], repository
                prefix = ["gh"]
                if repository:
                    prefix.extend(["--repo", repository])
                return _gh_command(
                    [*prefix, *expanded, *segment[index + 1 :]],
                    seen_aliases | {token},
                )
            if token in GH_SAFE_TOP_LEVEL_COMMANDS:
                return None
            return "unproven", [f"gh {token}"], repository
    return None


def _literal_absolute_path(value: str) -> Path | None:
    if SHELL_META_RE.search(value):
        return None
    path = Path(value)
    return path if path.is_absolute() else None


def _literal_command_path(value: str, workdir: str | None) -> Path | None:
    absolute = _literal_absolute_path(value)
    if absolute is not None:
        return absolute
    if SHELL_META_RE.search(value) or "/" not in value or workdir is None:
        return None
    root = Path(workdir)
    if not root.is_absolute() or not root.is_dir():
        return None
    try:
        return (root / value).resolve(strict=True)
    except OSError:
        return None


def _literal_directory(value: str, workdir: str | None) -> Path | None:
    if SHELL_META_RE.search(value):
        return None
    path = Path(value)
    if not path.is_absolute():
        if workdir is None:
            return None
        root = Path(workdir)
        if not root.is_absolute() or not root.is_dir():
            return None
        path = root / path
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return None
    return resolved if resolved.is_dir() else None


def _publisher_invocation_is_invalid(segment: list[str]) -> bool | None:
    index = _skip_prefixes(segment)
    if index >= len(segment):
        return None
    executable = os.path.basename(segment[index])
    if executable in {"python", "python3"}:
        index += 1
        if index >= len(segment):
            return None
        if os.path.basename(segment[index]) != PUBLISHER.name and any(
            os.path.basename(token) == PUBLISHER.name for token in segment[index + 1 :]
        ):
            return True
    script = segment[index]
    if os.path.basename(script) != PUBLISHER.name:
        return None
    if script not in PUBLISHER_ARGUMENTS:
        return True
    arguments = segment[index + 1 :]
    required_options = (
        "--repository",
        "--base",
        "--base-oid",
        "--head",
        "--head-oid",
        "--head-owner",
        "--title",
        "--body-template",
    )
    required_values = {
        option: _option_values(arguments, {option}, set())
        for option in required_options
    }
    if any(len(values) != 1 for values in required_values.values()):
        return True
    if _normalize_repository(required_values["--repository"][0]) is None:
        return True
    if not all(
        required_values[option][0].strip()
        for option in ("--base", "--head", "--head-owner", "--title")
    ):
        return True
    head = required_values["--head"][0]
    head_owner = required_values["--head-owner"][0]
    if head.count(":") != 1:
        return True
    qualified_owner, head_branch = head.split(":", 1)
    if not head_branch or qualified_owner != head_owner:
        return True
    if any(
        OID_RE.fullmatch(required_values[option][0]) is None
        for option in ("--base-oid", "--head-oid")
    ):
        return True
    template_path = _literal_absolute_path(required_values["--body-template"][0])
    return template_path is None or not template_path.is_file()


def _strict_long_option_values(
    arguments: list[str], allowed_options: set[str]
) -> dict[str, str] | None:
    values: dict[str, str] = {}
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if "=" in token:
            option, value = token.split("=", 1)
            index += 1
        else:
            option = token
            if option not in allowed_options or index + 1 >= len(arguments):
                return None
            value = arguments[index + 1]
            index += 2
        if option not in allowed_options or option in values:
            return None
        values[option] = value
    return values


def _updater_invocation_is_invalid(segment: list[str]) -> bool | None:
    index = _skip_prefixes(segment)
    if index >= len(segment):
        return None
    executable = os.path.basename(segment[index])
    if executable in {"python", "python3"}:
        index += 1
        if index >= len(segment):
            return None
        if os.path.basename(segment[index]) != UPDATER.name and any(
            os.path.basename(token) == UPDATER.name for token in segment[index + 1 :]
        ):
            return True
    script = segment[index]
    if os.path.basename(script) != UPDATER.name:
        return None
    if script not in UPDATER_ARGUMENTS or index + 1 >= len(segment):
        return True
    operation = segment[index + 1]
    if operation not in {"text", "ready"}:
        return True
    common_options = {
        "--repository",
        "--pr",
        "--base",
        "--base-oid",
        "--head",
        "--head-oid",
        "--head-owner",
        "--expected-title-sha256",
        "--expected-body-sha256",
    }
    text_options = {"--expected-state", "--title", "--body-file"}
    expected_options = common_options | (text_options if operation == "text" else set())
    values = _strict_long_option_values(segment[index + 2 :], expected_options)
    if values is None or values.keys() != expected_options:
        return True
    repository = _normalize_repository(values["--repository"])
    if repository is None:
        return True
    if not values["--pr"].isdigit() or int(values["--pr"]) <= 0:
        return True
    if not values["--base"].strip():
        return True
    if any(
        OID_RE.fullmatch(values[option]) is None
        for option in ("--base-oid", "--head-oid")
    ):
        return True
    if any(
        re.fullmatch(r"[0-9a-f]{64}", values[option]) is None
        for option in ("--expected-title-sha256", "--expected-body-sha256")
    ):
        return True
    head = values["--head"]
    head_owner = values["--head-owner"]
    if head.count(":") != 1:
        return True
    qualified_owner, head_branch = head.split(":", 1)
    if not head_branch or qualified_owner != head_owner:
        return True
    if operation == "ready":
        return False
    if values["--expected-state"] not in {"draft", "ready"}:
        return True
    if not values["--title"].strip():
        return True
    identity = (repository, int(values["--pr"]))
    body_path = _literal_absolute_path(values["--body-file"])
    return (
        body_path is None
        or not body_path.is_file()
        or not _canonical_body(_read_literal_file(str(body_path)), identity)
    )


def _review_state_invocation_is_invalid(segment: list[str]) -> bool | None:
    index = _skip_prefixes(segment)
    if index >= len(segment):
        return None
    executable = os.path.basename(segment[index])
    if executable not in {"python", "python3"}:
        return True if executable == REVIEW_STATE.name else None
    script_index = index + 1
    if script_index >= len(segment):
        return None
    script = segment[script_index]
    if os.path.basename(script) != REVIEW_STATE.name:
        if any(
            os.path.basename(token) == REVIEW_STATE.name
            for token in segment[script_index + 1 :]
        ):
            return True
        return None
    if script != str(REVIEW_STATE):
        return True

    values: dict[str, str] = {}
    flags: set[str] = set()
    arguments = segment[script_index + 1 :]
    position = 0
    while position < len(arguments):
        argument = arguments[position]
        if argument in {"--repo", "--pr"}:
            if argument in values or position + 1 >= len(arguments):
                return True
            values[argument] = arguments[position + 1]
            position += 2
            continue
        if argument.startswith(("--repo=", "--pr=")):
            name, value = argument.split("=", 1)
            if name in values:
                return True
            values[name] = value
            position += 1
            continue
        if argument in {"--summary", "--json", "--write-ledger"}:
            if argument in flags:
                return True
            flags.add(argument)
            position += 1
            continue
        return True

    repository = values.get("--repo")
    pr_number = values.get("--pr", "")
    return not (
        values.keys() == {"--repo", "--pr"}
        and flags
        in (
            {"--summary", "--json"},
            {"--summary", "--json", "--write-ledger"},
        )
        and repository is not None
        and re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", repository) is not None
        and pr_number.isascii()
        and pr_number.isdigit()
        and int(pr_number) > 0
    )


def _review_state_helper_is_trusted() -> bool:
    try:
        resolved = REVIEW_STATE.resolve(strict=True)
        if REVIEW_STATE.is_symlink() or not resolved.is_file():
            return False
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError:
        return False
    return digest == REVIEW_STATE_SHA256


def _trusted_help_only_invocation(segment: list[str]) -> bool:
    if (
        len(segment) != 3
        or segment[0] not in {"python", "python3"}
        or segment[2] != "--help"
    ):
        return False
    script = Path(segment[1])
    if script not in TRUSTED_HELP_ONLY_SCRIPTS:
        return False
    directory = script.parent
    if any(candidate.parent != directory for candidate in TRUSTED_HELP_ONLY_SCRIPTS):
        return False
    try:
        cache_directory = directory / "__pycache__"
        entries = set(directory.iterdir())
        if entries - set(TRUSTED_HELP_ONLY_SCRIPTS) - {cache_directory}:
            return False
        for candidate, candidate_digest in TRUSTED_HELP_ONLY_SCRIPTS.items():
            resolved = candidate.resolve(strict=True)
            if candidate.is_symlink() or not resolved.is_file():
                return False
            digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
            if digest != candidate_digest:
                return False
        if cache_directory in entries and not _trusted_bytecode_cache(
            cache_directory, TRUSTED_HELP_ONLY_SCRIPTS
        ):
            return False
    except OSError:
        return False
    return True


def _trusted_bytecode_cache(
    directory: Path, sources: dict[Path, str]
) -> bool:
    if directory.is_symlink() or not directory.is_dir():
        return False
    source_by_module = {source.stem: source for source in sources}
    cache_tag = sys.implementation.cache_tag
    if cache_tag is None:
        return False
    validation_arguments: list[str] = []
    try:
        for candidate in directory.iterdir():
            if candidate.is_symlink() or not candidate.is_file():
                return False
            match = re.fullmatch(
                rf"(?P<module>[A-Za-z_][A-Za-z0-9_]*)\.{re.escape(cache_tag)}"
                r"(?:\.opt-(?P<opt>[12]))?\.pyc",
                candidate.name,
            )
            if match is None:
                return False
            source = source_by_module.get(match.group("module"))
            if source is None:
                return False
            status = candidate.stat()
            if not 16 <= status.st_size <= MAX_TRUSTED_BYTECODE_BYTES:
                return False
            with candidate.open("rb") as handle:
                magic = handle.read(4)
            if magic != importlib.util.MAGIC_NUMBER:
                return False
            optimization = int(match.group("opt") or "0")
            validation_arguments.extend(
                [
                    str(source),
                    str(candidate),
                    str(optimization),
                    str(status.st_dev),
                    str(status.st_ino),
                ]
            )
        if not validation_arguments:
            return True
        result = _budgeted_run(
            [
                sys.executable,
                "-I",
                "-S",
                "-c",
                BYTECODE_VALIDATOR_SOURCE,
                str(MAX_TRUSTED_BYTECODE_BYTES),
                *validation_arguments,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False
    return result.returncode == 0


def _github_remote_repository(value: str) -> str | None:
    match = re.fullmatch(
        r"(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:)"
        r"(?P<owner>[A-Za-z0-9-]+)/"
        r"(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?",
        value.strip(),
    )
    if match is None:
        return None
    return _normalize_repository(f"{match.group('owner')}/{match.group('repo')}")


def _git_blob_digest(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def _working_tree_matches_git_tree(root: Path, tree_path: Path) -> bool:
    try:
        listing = _budgeted_run(
            ["git", "-C", str(root), "ls-tree", "-rz", "HEAD", "--", str(tree_path)],
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if listing.returncode:
        return False

    expected: dict[Path, tuple[bytes, str]] = {}
    for record in listing.stdout.split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        fields = metadata.split()
        if separator != b"\t" or len(fields) != 3 or fields[1] != b"blob":
            return False
        relative = Path(os.fsdecode(raw_path))
        try:
            relative.relative_to(tree_path)
        except ValueError:
            return False
        expected[relative] = (fields[0], fields[2].decode("ascii"))
    if not expected:
        return False

    actual: set[Path] = set()
    try:
        for directory, directories, filenames in os.walk(
            root / tree_path, followlinks=False
        ):
            directory_path = Path(directory)
            for name in list(directories):
                candidate = directory_path / name
                if candidate.is_symlink():
                    directories.remove(name)
                    filenames.append(name)
            for name in filenames:
                candidate = directory_path / name
                relative = candidate.relative_to(root)
                entry = expected.get(relative)
                if entry is None:
                    return False
                status = candidate.lstat()
                if stat.S_ISLNK(status.st_mode):
                    mode = b"120000"
                    content = os.fsencode(os.readlink(candidate))
                elif stat.S_ISREG(status.st_mode):
                    mode = b"100755" if status.st_mode & 0o111 else b"100644"
                    content = candidate.read_bytes()
                else:
                    return False
                expected_mode, expected_digest = entry
                if mode != expected_mode or _git_blob_digest(content) != expected_digest:
                    return False
                actual.add(relative)
    except (OSError, ValueError):
        return False
    return actual == expected.keys()


def _trusted_task_test_script(segment: list[str], workdir: str | None) -> bool:
    if segment != ["zsh", str(TRUSTED_TASK_TEST_PATH)] or workdir is None:
        return False
    try:
        root = Path(workdir).resolve(strict=True)
        candidate = root / TRUSTED_TASK_TEST_PATH
        script = candidate.resolve(strict=True)
    except OSError:
        return False
    if (
        not root.is_dir()
        or script != root / TRUSTED_TASK_TEST_PATH
        or candidate.is_symlink()
        or not script.is_file()
    ):
        return False
    try:
        top_level = _budgeted_run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        remote = _budgeted_run(
            ["git", "-C", str(root), "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            check=False,
        )
        tree = _budgeted_run(
            [
                "git",
                "-C",
                str(root),
                "rev-parse",
                f"HEAD:{TRUSTED_TASK_TEST_TREE_PATH}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool(
        top_level.returncode == 0
        and Path(top_level.stdout.strip()).resolve() == root
        and remote.returncode == 0
        and _github_remote_repository(remote.stdout)
        == TRUSTED_TASK_TEST_REPOSITORY
        and tree.returncode == 0
        and tree.stdout.strip() == TRUSTED_TASK_TEST_TREE
        and _working_tree_matches_git_tree(root, TRUSTED_TASK_TEST_TREE_PATH)
    )


def _read_literal_file(value: str) -> str | None:
    path = _literal_absolute_path(value)
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _api_endpoint(arguments: list[str]) -> str | None:
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token in GH_API_VALUE_OPTIONS:
            index += 2
            continue
        if any(
            token.startswith(f"{option}=")
            for option in GH_API_VALUE_OPTIONS
            if option.startswith("--")
        ):
            index += 1
            continue
        if token.startswith("-"):
            short_option = token[1:2]
            if short_option in GH_API_VALUE_SHORT_OPTIONS and len(token) == 2:
                index += 2
            else:
                index += 1
            continue
        endpoint = token.split("?", 1)[0].split("#", 1)[0]
        if "://" in endpoint:
            parsed = urlsplit(endpoint)
            if (
                parsed.scheme == "https"
                and parsed.hostname == "api.github.com"
                and parsed.port is None
            ):
                return posixpath.normpath(unquote(parsed.path)).lstrip("/")
            return endpoint
        return posixpath.normpath(unquote(endpoint)).lstrip("/")
    return None


def _issue_edit_identities(
    arguments: list[str], repository: str | None
) -> list[tuple[str, int]] | None:
    identities: list[tuple[str, int]] = []
    index = 0
    positional_only = False
    while index < len(arguments):
        selector = arguments[index]
        if not positional_only and selector == "--":
            positional_only = True
            index += 1
            continue
        if not positional_only and selector in ISSUE_EDIT_VALUE_OPTIONS:
            if index + 1 >= len(arguments):
                return None
            index += 2
            continue
        if not positional_only and any(
            selector.startswith(f"{option}=")
            for option in ISSUE_EDIT_VALUE_OPTIONS
            if option.startswith("--")
        ):
            index += 1
            continue
        if (
            not positional_only
            and selector.startswith("-")
            and not selector.startswith("--")
            and selector[1:2] in ISSUE_EDIT_VALUE_SHORT_OPTIONS
        ):
            index += 1
            continue
        if not positional_only and selector.startswith("-"):
            return None
        url_match = ISSUE_URL_RE.fullmatch(selector) or PR_URL_RE.fullmatch(selector)
        if url_match:
            number = url_match.groupdict().get("issue") or url_match.groupdict().get(
                "pr"
            )
            identities.append(
                (
                    f"{url_match.group('owner')}/{url_match.group('repo')}",
                    int(number),
                )
            )
        elif repository and selector.isdigit() and int(selector) > 0:
            identities.append((repository, int(selector)))
        else:
            return None
        index += 1
    return identities or None


@lru_cache(maxsize=64)
def _issue_target_kind(repository: str, number: int) -> str | None:
    try:
        result = _budgeted_run(
            ["gh", "api", f"repos/{repository}/issues/{number}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or value.get("number") != number:
        return None
    return "pull_request" if isinstance(value.get("pull_request"), dict) else "issue"


@lru_cache(maxsize=64)
def _graphql_node_identity(
    node_id: str,
) -> tuple[str, tuple[str, int] | None] | None:
    query = (
        "query($id: ID!) { node(id: $id) { __typename "
        "... on Issue { number repository { nameWithOwner } } "
        "... on PullRequest { number repository { nameWithOwner } } } }"
    )
    try:
        result = _budgeted_run(
            ["gh", "api", "graphql", "-f", f"query={query}", "-f", f"id={node_id}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    node = value.get("data", {}).get("node") if isinstance(value, dict) else None
    if not isinstance(node, dict):
        return None
    typename = node.get("__typename")
    if typename not in {"Issue", "PullRequest"}:
        return None
    number = node.get("number")
    repository = node.get("repository")
    name_with_owner = (
        repository.get("nameWithOwner") if isinstance(repository, dict) else None
    )
    identity = (
        (name_with_owner, number)
        if isinstance(name_with_owner, str)
        and _normalize_repository(name_with_owner)
        and isinstance(number, int)
        and not isinstance(number, bool)
        and number > 0
        else None
    )
    return ("issue" if typename == "Issue" else "pull_request", identity)


@lru_cache(maxsize=64)
def _graphql_review_thread_repository(thread_id: str) -> str | None:
    query = (
        "query($id: ID!) { node(id: $id) { "
        "... on PullRequestReviewThread { pullRequest { "
        "repository { nameWithOwner } } } } }"
    )
    try:
        result = _budgeted_run(
            [
                "gh",
                "--hostname",
                "github.com",
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-f",
                f"id={thread_id}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    node = value.get("data", {}).get("node") if isinstance(value, dict) else None
    pull_request = node.get("pullRequest") if isinstance(node, dict) else None
    repository = (
        pull_request.get("repository") if isinstance(pull_request, dict) else None
    )
    name_with_owner = (
        repository.get("nameWithOwner") if isinstance(repository, dict) else None
    )
    return _normalize_repository(name_with_owner)


def _json_find_string(value: Any, names: set[str]) -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in names and isinstance(nested, str):
                return nested
        for nested in value.values():
            found = _json_find_string(nested, names)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _json_find_string(nested, names)
            if found is not None:
                return found
    return None


def _graphql_update_issue_node_id(
    query_text: str, fields: dict[str, list[str]], input_content: str | None
) -> str | None:
    for name in ("id", "issueId", "issue_id"):
        if fields.get(name):
            return fields[name][-1]
    literal_match = re.search(r"\bid\s*:\s*['\"](?P<id>[^'\"]+)['\"]", query_text)
    if literal_match:
        return literal_match.group("id")
    if input_content:
        try:
            value = json.loads(input_content)
        except json.JSONDecodeError:
            return None
        return _json_find_string(value, {"id", "issueId", "issue_id"})
    return None


def _graphql_update_issue_changes_text(
    query_text: str, fields: dict[str, list[str]], input_content: str | None
) -> bool:
    if re.search(r"\b(?:title|body)\s*:", query_text):
        return True
    if {"title", "body"} & fields.keys():
        return True
    if input_content:
        try:
            value = json.loads(input_content)
        except json.JSONDecodeError:
            return True
        return _json_find_string(value, {"title", "body"}) is not None
    return False


def _issue_text_edit_is_noncanonical(
    identities: list[tuple[str, int]] | None,
) -> bool:
    if not identities or len(identities) != 1:
        return True
    return _issue_target_kind(*identities[0]) != "issue"


def _changes_pr_text(arguments: list[str]) -> bool:
    return bool(
        _option_values(
            arguments,
            {"-t", "--title", "-b", "--body", "-F", "--body-file"},
            PR_CREATE_VALUE_SHORT_OPTIONS,
        )
    )


def _api_method(arguments: list[str]) -> str:
    methods = _option_values(arguments, {"-X", "--method"}, GH_API_VALUE_SHORT_OPTIONS)
    if methods:
        return methods[-1].upper()
    has_fields = bool(
        _option_values(
            arguments,
            {"-F", "--field", "-f", "--raw-field"},
            GH_API_VALUE_SHORT_OPTIONS,
        )
    )
    has_input = bool(_option_values(arguments, {"--input"}, set()))
    return "POST" if has_fields or has_input else "GET"


def _api_fields(arguments: list[str]) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for raw_field in _option_values(
        arguments,
        {"-F", "--field", "-f", "--raw-field"},
        GH_API_VALUE_SHORT_OPTIONS,
    ):
        name, separator, value = raw_field.partition("=")
        if separator:
            fields.setdefault(name, []).append(value)
    return fields


def _api_input(arguments: list[str]) -> tuple[str | None, bool]:
    input_paths = _option_values(arguments, {"--input"}, GH_API_VALUE_SHORT_OPTIONS)
    if not input_paths:
        return None, False
    if len(input_paths) != 1:
        return None, True
    content = _read_literal_file(input_paths[0])
    return content, content is None


def _api_body(fields: dict[str, list[str]], input_content: str | None) -> str | None:
    if fields.get("body"):
        value = fields["body"][-1]
        if value.startswith("@"):
            return _read_literal_file(value[1:])
        return value
    if input_content:
        try:
            value = json.loads(input_content)
        except json.JSONDecodeError:
            return None
        return _json_find_string(value, {"body"})
    return None


def _strict_review_reply_arguments(arguments: list[str]) -> bool:
    endpoints: list[str] = []
    methods: list[str] = []
    fields: list[tuple[str, str]] = []
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token in {"-X", "--method", "-f", "--raw-field", "-F", "--field"}:
            if index + 1 >= len(arguments):
                return False
            value = arguments[index + 1]
            if token in {"-X", "--method"}:
                methods.append(value)
            else:
                fields.append((token, value))
            index += 2
            continue
        matched = False
        for option in ("--method", "--raw-field", "--field"):
            if token.startswith(f"{option}="):
                value = token.split("=", 1)[1]
                if option == "--method":
                    methods.append(value)
                else:
                    fields.append((option, value))
                matched = True
                break
        if matched:
            index += 1
            continue
        if token.startswith("-X") and token != "-X":
            methods.append(token[2:])
            index += 1
            continue
        if token.startswith(("-f", "-F")) and token[:2] in {"-f", "-F"}:
            fields.append((token[:2], token[2:]))
            index += 1
            continue
        if token in {"--jq", "-q"}:
            if index + 1 >= len(arguments):
                return False
            index += 2
            continue
        if token.startswith("--jq="):
            index += 1
            continue
        if token.startswith("-"):
            return False
        endpoints.append(token)
        index += 1

    if len(endpoints) != 1 or len(methods) != 1 or methods[0].upper() != "POST":
        return False
    endpoint = endpoints[0].split("?", 1)[0].lstrip("/")
    match = REST_REVIEW_REPLY_RE.fullmatch(endpoint)
    if match is None or "?" in endpoints[0]:
        return False
    if _normalize_repository(f"{match.group('owner')}/{match.group('repo')}") is None:
        return False
    parsed_fields: dict[str, list[tuple[str, str]]] = {}
    for option, raw_field in fields:
        name, separator, value = raw_field.partition("=")
        if not separator:
            return False
        parsed_fields.setdefault(name, []).append((option, value))
    if parsed_fields.keys() != {"body", "in_reply_to"}:
        return False
    if any(len(values) != 1 for values in parsed_fields.values()):
        return False
    body_option, body = parsed_fields["body"][0]
    _reply_option, reply_id = parsed_fields["in_reply_to"][0]
    return bool(
        body
        and not (body_option in {"-F", "--field"} and body.startswith("@"))
        and reply_id.isascii()
        and reply_id.isdigit()
        and int(reply_id) > 0
    )


def _review_reply_route_path(arguments: list[str]) -> str | None:
    endpoint = _api_endpoint(arguments)
    if endpoint is None:
        return None
    if "://" in endpoint:
        endpoint = urlsplit(endpoint).path.lstrip("/")
    return endpoint if REST_REVIEW_REPLY_ROUTE_RE.fullmatch(endpoint) else None


def _review_reply_route_is_unproven(arguments: list[str]) -> bool:
    return bool(
        _review_reply_route_path(arguments)
        and not _strict_review_reply_arguments(arguments)
    )


def _review_resolution_query_texts(arguments: list[str]) -> list[str]:
    queries: list[str] = []
    for value in _api_fields(arguments).get("query", []):
        if value.startswith("@"):
            content = _read_literal_file(value[1:])
            if content is not None:
                queries.append(content)
        else:
            queries.append(value)
    input_content, _unresolved_input = _api_input(arguments)
    if input_content:
        queries.append(input_content)
    return queries


def _strict_review_resolution_arguments(
    arguments: list[str], repository: str | None
) -> bool:
    if repository is not None:
        # `gh api` does not accept the repository-selection flags supported by
        # commands such as `gh pr`.  Bind this route with an otherwise unused
        # literal GraphQL variable instead, then verify the thread against it.
        return False
    endpoints: list[str] = []
    methods: list[str] = []
    fields: list[str] = []
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token in {"-X", "--method", "-f", "--raw-field", "-F", "--field"}:
            if index + 1 >= len(arguments):
                return False
            value = arguments[index + 1]
            if token in {"-X", "--method"}:
                methods.append(value)
            else:
                fields.append(value)
            index += 2
            continue
        matched = False
        for option in ("--method", "--raw-field", "--field"):
            if token.startswith(f"{option}="):
                value = token.split("=", 1)[1]
                if option == "--method":
                    methods.append(value)
                else:
                    fields.append(value)
                matched = True
                break
        if matched:
            index += 1
            continue
        if token.startswith("-X") and token != "-X":
            methods.append(token[2:])
            index += 1
            continue
        if token.startswith(("-f", "-F")) and token[:2] in {"-f", "-F"}:
            fields.append(token[2:])
            index += 1
            continue
        if token in {"--jq", "-q"}:
            if index + 1 >= len(arguments):
                return False
            index += 2
            continue
        if token.startswith("--jq="):
            index += 1
            continue
        if token.startswith("-"):
            return False
        endpoints.append(token)
        index += 1

    if endpoints != ["graphql"]:
        return False
    if len(methods) > 1 or (methods and methods[0].upper() != "POST"):
        return False
    parsed_fields: dict[str, list[str]] = {}
    for raw_field in fields:
        name, separator, value = raw_field.partition("=")
        if not separator:
            return False
        parsed_fields.setdefault(name, []).append(value)
    if len(parsed_fields.get("query", [])) != 1:
        return False
    query = parsed_fields["query"][0]
    if query.startswith("@"):
        return False
    normalized_query = re.sub(r"\s*([!$():{}])\s*", r"\1", query.strip())
    query_match = GRAPHQL_RESOLVE_REVIEW_THREAD_QUERY_RE.fullmatch(normalized_query)
    if query_match is None:
        return False
    variable = query_match.group("variable")
    if variable == "repository" or parsed_fields.keys() != {
        "query",
        variable,
        "repository",
    }:
        return False
    if len(parsed_fields[variable]) != 1 or len(parsed_fields["repository"]) != 1:
        return False
    thread_id = parsed_fields[variable][0]
    bound_repository = parsed_fields["repository"][0]
    return bool(
        re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]+",
            bound_repository,
        )
        and re.fullmatch(r"PRRT_[A-Za-z0-9_-]+", thread_id)
        and _graphql_review_thread_repository(thread_id) == bound_repository
    )


def _is_review_resolution_route(arguments: list[str]) -> bool:
    if _api_endpoint(arguments) != "graphql":
        return False
    queries = _review_resolution_query_texts(arguments)
    return any(GRAPHQL_RESOLVE_REVIEW_THREAD_RE.search(query) for query in queries)


def _review_resolution_route_is_unproven(
    arguments: list[str], repository: str | None
) -> bool:
    return _is_review_resolution_route(arguments) and not (
        _strict_review_resolution_arguments(arguments, repository)
    )


def _gh_targets_github_dot_com(
    segment: list[str], bindings: dict[str, str | None]
) -> bool:
    gh_index = _skip_prefixes(segment)
    if gh_index >= len(segment) or os.path.basename(segment[gh_index]) != "gh":
        return False
    index = gh_index + 1
    explicit_hosts: list[str] = []
    while index < len(segment) and segment[index] != "api":
        token = segment[index]
        if token == "--hostname":
            if index + 1 >= len(segment):
                return False
            explicit_hosts.append(segment[index + 1])
            index += 2
            continue
        if token.startswith("--hostname="):
            explicit_hosts.append(token.split("=", 1)[1])
        index += 1
    if explicit_hosts:
        return len(explicit_hosts) == 1 and explicit_hosts[0] == "github.com"
    prefix_hosts = [
        assignment.group("value")
        for token in segment[:gh_index]
        if (assignment := SHELL_ASSIGNMENT_RE.fullmatch(token)) is not None
        and assignment.group("name") == "GH_HOST"
    ]
    if prefix_hosts:
        return all(host == "github.com" for host in prefix_hosts)
    host = bindings.get("GH_HOST", os.environ.get("GH_HOST", "github.com"))
    return host == "github.com"


def _api_changes_pr_text(arguments: list[str]) -> bool:
    endpoint = _api_endpoint(arguments)
    if endpoint is None:
        return False
    method = _api_method(arguments)
    fields = _api_fields(arguments)
    input_content, unresolved_input = _api_input(arguments)
    input_has_pr_text = bool(
        input_content and re.search(r'["\'](?:title|body)["\']\s*:', input_content)
    )
    fields_mark_ready = any(
        value.lower() in {"false", "0"} for value in fields.get("draft", [])
    )
    input_marks_ready = bool(
        input_content
        and re.search(r'["\']draft["\']\s*:\s*false\b', input_content, re.I)
    )

    if endpoint == "graphql":
        queries: list[str] = []
        unresolved_query = False
        for query in fields.get("query", []):
            if query.startswith("@"):
                query_content = _read_literal_file(query[1:])
                if query_content is None:
                    unresolved_query = True
                else:
                    queries.append(query_content)
            elif GRAPHQL_DYNAMIC_VALUE_RE.fullmatch(query):
                unresolved_query = True
            else:
                queries.append(query)
        if unresolved_input or unresolved_query:
            return True
        query_text = "\n".join(queries + ([input_content] if input_content else []))
        if not re.search(r"\bmutation\b", query_text, re.I):
            return False
        if GRAPHQL_DIRECT_PR_MUTATION_RE.search(query_text):
            return True
        if not GRAPHQL_UPDATE_ISSUE_RE.search(query_text):
            return False
        if not _graphql_update_issue_changes_text(query_text, fields, input_content):
            return False
        node_id = _graphql_update_issue_node_id(query_text, fields, input_content)
        if node_id is None:
            return True
        classified = _graphql_node_identity(node_id)
        if classified is None:
            return True
        kind, _identity = classified
        return kind != "issue"

    pulls_match = REST_PULLS_RE.search(endpoint)
    if pulls_match:
        if pulls_match.group("number") is None:
            return method == "POST"
        return method in {"PATCH", "POST"} and (
            bool({"title", "body"} & fields.keys())
            or input_has_pr_text
            or fields_mark_ready
            or input_marks_ready
            or unresolved_input
        )

    issue_match = REST_ISSUE_RE.search(endpoint)
    if issue_match:
        changes_text = method in {"PATCH", "POST"} and (
            bool({"title", "body"} & fields.keys())
            or input_has_pr_text
            or unresolved_input
        )
        if not changes_text:
            return False
        repository = f"{issue_match.group('owner')}/{issue_match.group('repo')}"
        if _normalize_repository(repository) is None or "{" in repository:
            return True
        identity = (repository, int(issue_match.group("number")))
        return _issue_text_edit_is_noncanonical([identity])
    return False


def _curl_changes_pr(
    segment: list[str], bindings: dict[str, str | None]
) -> tuple[bool, str | None]:
    index = _skip_prefixes(segment)
    if index >= len(segment) or os.path.basename(segment[index]) != "curl":
        return False, None
    arguments: list[str] = []
    for argument in segment[index + 1 :]:
        variable = _shell_variable_name(argument)
        if variable is not None:
            value = bindings.get(variable)
            if value is None or any(character.isspace() for character in value):
                return True, "curl argument"
            arguments.append(value)
        else:
            prefix_match = re.match(
                r"^(?:\$\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|"
                r"\$(?P<plain>[A-Za-z_][A-Za-z0-9_]*))(?P<suffix>.+)$",
                argument,
            )
            if prefix_match is not None:
                value = bindings.get(
                    prefix_match.group("braced") or prefix_match.group("plain")
                )
                if value is None or any(character.isspace() for character in value):
                    return True, "curl argument"
                argument = value + prefix_match.group("suffix")
            if ("$" in argument or "`" in argument) and (
                argument.startswith(("$", "`")) or "http" in argument.lower()
            ):
                return True, "curl argument"
            arguments.append(argument)

    method: str | None = None
    data: list[tuple[str, bool]] = []
    urls: list[str] = []
    value_options = {
        "-d",
        "--data",
        "--data-ascii",
        "--data-binary",
        "--data-raw",
        "--data-urlencode",
        "--json",
    }
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token in {"-K", "--config"} or token.startswith(("-K", "--config=")):
            return True, "curl config"
        if token in {"-X", "--request"}:
            if index + 1 >= len(arguments):
                return True, "curl request"
            method = arguments[index + 1].upper()
            index += 2
            continue
        if token.startswith("--request="):
            method = token.split("=", 1)[1].upper()
            index += 1
            continue
        if token.startswith("-X") and token != "-X":
            method = token[2:].upper()
            index += 1
            continue
        if token in value_options:
            if index + 1 >= len(arguments):
                return True, "curl data"
            data.append((arguments[index + 1], token == "--json"))
            index += 2
            continue
        if token.startswith("-d") and token != "-d":
            data.append((token[2:], False))
            index += 1
            continue
        matching_data_option = next(
            (
                option
                for option in value_options
                if option.startswith("--") and token.startswith(f"{option}=")
            ),
            None,
        )
        if matching_data_option is not None:
            data.append(
                (token.split("=", 1)[1], matching_data_option == "--json")
            )
            index += 1
            continue
        parsed_url = urlsplit(token)
        if (
            parsed_url.scheme.lower() in {"http", "https"}
            and parsed_url.hostname
            and parsed_url.hostname.lower() == "api.github.com"
        ):
            if "$" in token or "`" in token:
                return True, "curl URL"
            urls.append(parsed_url.path.lstrip("/"))
        index += 1

    if not urls:
        return False, None
    if len(urls) != 1:
        return True, "curl GitHub API"
    endpoint = urls[0]
    method = method or ("POST" if data else "GET")
    data_content_parts: list[tuple[str, bool]] = []
    for value, explicit_json in data:
        if value.startswith("@"):
            content = _read_literal_file(value[1:])
            if content is None:
                return True, "curl data"
            data_content_parts.append((content, explicit_json))
        else:
            data_content_parts.append((value, explicit_json))
    data_content = "\n".join(content for content, _explicit_json in data_content_parts)

    def decoded_json_changes(fields: set[str]) -> tuple[bool, bool]:
        def contains_sensitive_key(value: Any) -> bool:
            if isinstance(value, dict):
                return any(
                    str(key).lower() in fields or contains_sensitive_key(nested)
                    for key, nested in value.items()
                )
            if isinstance(value, list):
                return any(contains_sensitive_key(nested) for nested in value)
            return False

        for content, explicit_json in data_content_parts:
            stripped = content.lstrip()
            if not explicit_json and not stripped.startswith(("{", "[")):
                continue
            try:
                decoded = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                return False, True
            if contains_sensitive_key(decoded):
                return True, False
        return False, False

    def decoded_json_contains(pattern: str) -> tuple[bool, bool]:
        def contains_matching_string(value: Any) -> bool:
            if isinstance(value, str):
                return bool(re.search(pattern, value, re.I))
            if isinstance(value, dict):
                return any(
                    contains_matching_string(nested) for nested in value.values()
                )
            if isinstance(value, list):
                return any(contains_matching_string(nested) for nested in value)
            return False

        for content, explicit_json in data_content_parts:
            stripped = content.lstrip()
            if not explicit_json and not stripped.startswith(("{", "[")):
                continue
            try:
                decoded = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                return False, True
            if contains_matching_string(decoded):
                return True, False
        return False, False

    if endpoint == "graphql":
        json_mutation, invalid_json = decoded_json_contains(r"\bmutation\b")
        return (
            method in {"POST", "PATCH"}
            and (
                invalid_json
                or json_mutation
                or bool(re.search(r"\bmutation\b", data_content, re.I))
            ),
            None,
        )
    pulls_match = REST_PULLS_RE.fullmatch(endpoint)
    if pulls_match:
        if pulls_match.group("number") is None:
            return method == "POST", None
        json_changes, invalid_json = decoded_json_changes(
            {"title", "body", "draft"}
        )
        if method in {"POST", "PATCH"} and invalid_json:
            return True, "curl JSON"
        return method in {"POST", "PATCH"} and bool(
            json_changes
            or re.search(
                r'(?:["\'](?:title|body|draft)["\']\s*:|'
                r"(?:^|\n)(?:title|body|draft)=)",
                data_content,
                re.I,
            )
        ), None
    issue_match = REST_ISSUE_RE.fullmatch(endpoint)
    issue_json_changes, issue_invalid_json = decoded_json_changes({"title", "body"})
    if issue_match and method in {"POST", "PATCH"} and issue_invalid_json:
        return True, "curl JSON"
    if issue_match and method in {"POST", "PATCH"} and (
        issue_json_changes
        or re.search(
            r'(?:["\'](?:title|body)["\']\s*:|(?:^|\n)(?:title|body)=)',
            data_content,
            re.I,
        )
    ):
        identity = (
            f"{issue_match.group('owner')}/{issue_match.group('repo')}",
            int(issue_match.group("number")),
        )
        return _issue_text_edit_is_noncanonical([identity]), None
    return False, None


def _wget_changes_pr(
    segment: list[str], bindings: dict[str, str | None]
) -> tuple[bool, str | None]:
    index = _skip_prefixes(segment)
    if index >= len(segment) or os.path.basename(segment[index]) != "wget":
        return False, None
    translated = ["curl"]
    arguments = segment[index + 1 :]
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if (
            token in {"--config", "-e", "--execute"}
            or token.startswith(("--config=", "--execute=", "-e="))
            or (token.startswith("-e") and token != "-e")
        ):
            return True, "wget config"
        if token in {
            "--method",
            "--body-data",
            "--body-file",
            "--post-data",
            "--post-file",
        }:
            if index + 1 >= len(arguments):
                return True, "wget argument"
            option = {
                "--method": "--request",
                "--body-data": "--data",
                "--body-file": "--data",
                "--post-data": "--data",
                "--post-file": "--data",
            }[token]
            value = arguments[index + 1]
            translated.extend(
                [
                    option,
                    f"@{value}" if token in {"--body-file", "--post-file"} else value,
                ]
            )
            index += 2
            continue
        matched = next(
            (
                option
                for option in (
                    "--method",
                    "--body-data",
                    "--body-file",
                    "--post-data",
                    "--post-file",
                )
                if token.startswith(f"{option}=")
            ),
            None,
        )
        if matched is not None:
            value = token.split("=", 1)[1]
            translated.extend(
                [
                    {
                        "--method": "--request",
                        "--body-data": "--data",
                        "--body-file": "--data",
                        "--post-data": "--data",
                        "--post-file": "--data",
                    }[matched],
                    f"@{value}" if matched in {"--body-file", "--post-file"} else value,
                ]
            )
        else:
            translated.append(token)
        index += 1
    return _curl_changes_pr(translated, bindings)


def _leading_shell_assignments(segment: list[str]) -> tuple[dict[str, str | None], int]:
    assignments: dict[str, str | None] = {}
    index = 0
    while index < len(segment):
        match = SHELL_ASSIGNMENT_RE.fullmatch(segment[index])
        if match is None:
            break
        value = match.group("value")
        assignments[match.group("name")] = (
            None if SHELL_META_RE.search(value) else value
        )
        index += 1
    return assignments, index


def _shell_variable_name(value: str) -> str | None:
    match = SHELL_VARIABLE_RE.fullmatch(value)
    if match is None:
        return None
    return match.group("braced") or match.group("plain")


def _resolve_shell_value(
    value: str, bindings: dict[str, str | None]
) -> tuple[str | None, bool]:
    variable = _shell_variable_name(value)
    if variable is not None:
        resolved = bindings.get(variable)
        return resolved, resolved is None
    if SHELL_META_RE.search(value):
        return None, True
    return value, False


def _resolve_dynamic_executable(
    segment: list[str], bindings: dict[str, str | None]
) -> tuple[list[str], str | None]:
    index = _skip_prefixes(segment)
    if index >= len(segment):
        return segment, None
    executable = segment[index]
    variable = _shell_variable_name(executable)
    if variable is None:
        if DYNAMIC_COMMAND_RE.search(executable):
            return segment, executable
        return segment, None
    resolved = bindings.get(variable)
    if not resolved:
        return segment, executable
    try:
        replacement = shlex.split(resolved)
    except ValueError:
        return segment, executable
    if not replacement:
        return segment, executable
    return [*segment[:index], *replacement, *segment[index + 1 :]], None


def _resolve_sensitive_gh_arguments(
    segment: list[str], bindings: dict[str, str | None]
) -> tuple[list[str], str | None]:
    index = _skip_prefixes(segment)
    if index >= len(segment) or os.path.basename(segment[index]) != "gh":
        return segment, None
    resolved = list(segment)
    graphql = "api" in resolved[index + 1 :] and "graphql" in resolved[index + 1 :]
    for argument_index in range(index + 1, len(resolved)):
        argument = resolved[argument_index]
        literal_positions = getattr(argument, "literal_shell_meta_positions", frozenset())
        variable = None if literal_positions else _shell_variable_name(argument)
        if variable is not None:
            value = bindings.get(variable)
            if value is None or any(character.isspace() for character in value):
                return segment, "gh argument"
            resolved[argument_index] = value
        elif any(
            character in "$`*?[" and position not in literal_positions
            for position, character in enumerate(argument)
        ):
            literal_graphql_variables = False
            if (
                graphql
                and argument.startswith("query=")
                and "${" not in argument
                and "`" not in argument
            ):
                variable_names = re.findall(
                    r"\$([A-Za-z_][A-Za-z0-9_]*)", argument.removeprefix("query=")
                )
                literal_graphql_variables = bool(variable_names) and not any(
                    name in bindings or name in os.environ for name in variable_names
                )
            if not literal_graphql_variables:
                return segment, "gh argument"
        else:
            resolved[argument_index] = str(argument)
    return resolved, None


def _normalize_control_indirection(
    segment: list[str],
) -> tuple[list[str], str | None]:
    index = 0
    while index < len(segment) and SHELL_ASSIGNMENT_RE.fullmatch(segment[index]):
        index += 1
    while index < len(segment) and os.path.basename(segment[index]) in CONTROL_PREFIXES:
        control = os.path.basename(segment[index])
        index += 1
        if control == "command":
            while index < len(segment) and segment[index].startswith("-"):
                option = segment[index]
                index += 1
                if option == "--":
                    break
                if option in {"-v", "-V"}:
                    return [], None
                if option != "-p":
                    return segment, "command"
        elif control == "exec":
            while index < len(segment) and segment[index].startswith("-"):
                option = segment[index]
                index += 1
                if option == "--":
                    break
                if option == "-a":
                    if index >= len(segment):
                        return segment, "exec"
                    index += 1
                elif option not in {"-c", "-l"}:
                    return segment, "exec"
        elif control == "time":
            while index < len(segment) and segment[index] == "-p":
                index += 1
            if index < len(segment) and segment[index] == "--":
                index += 1
        else:
            continue
    return segment[index:], None


def _normalize_builtin_indirection(
    segment: list[str], bindings: dict[str, str | None]
) -> tuple[list[str], str | None]:
    index = _skip_prefixes(segment)
    if index >= len(segment) or os.path.basename(segment[index]) != "builtin":
        return segment, None
    if index + 1 >= len(segment):
        return segment, "builtin"
    target = segment[index + 1]
    variable = _shell_variable_name(target)
    if variable is not None:
        target = bindings.get(variable) or ""
        if not target:
            return segment, "builtin"
    elif DYNAMIC_COMMAND_RE.search(target):
        return segment, "builtin"
    if target not in {"command", "eval", "source", "."}:
        return segment, None
    return [*segment[:index], target, *segment[index + 2 :]], None


def _normalize_interpreter_entrypoint(
    segment: list[str],
    bindings: dict[str, str | None],
    *,
    allow_expandable_helpers: bool = False,
    trusted_helper_interpreter: bool = False,
) -> tuple[list[str], str | None]:
    index = _skip_prefixes(segment)
    if index >= len(segment) or os.path.basename(segment[index]) not in {
        "python",
        "python3",
    }:
        return segment, None
    script_index = index + 1
    if script_index >= len(segment):
        return segment, None
    script = segment[script_index]
    if script in PUBLISHER_ARGUMENTS | UPDATER_ARGUMENTS:
        if not trusted_helper_interpreter:
            return segment, f"{os.path.basename(segment[index])} script"
        return segment, None
    expandable = EXPANDABLE_PUBLISHER_ARGUMENTS | EXPANDABLE_UPDATER_ARGUMENTS
    if script in expandable:
        if not allow_expandable_helpers:
            return segment, f"{os.path.basename(segment[index])} script"
        resolved = PUBLISHER if script in EXPANDABLE_PUBLISHER_ARGUMENTS else UPDATER
        return [*segment[:script_index], str(resolved), *segment[script_index + 1 :]], None
    variable = _shell_variable_name(script)
    if variable is not None:
        resolved = bindings.get(variable)
        if not resolved:
            return segment, f"{os.path.basename(segment[index])} script"
        return [*segment[:script_index], resolved, *segment[script_index + 1 :]], None
    if DYNAMIC_COMMAND_RE.search(script):
        return segment, f"{os.path.basename(segment[index])} script"
    return segment, None


def _static_eval_script(
    arguments: list[str], bindings: dict[str, str | None]
) -> str | None:
    if not arguments:
        return None
    resolved: list[str] = []
    for argument in arguments:
        variable = _shell_variable_name(argument)
        if variable is not None:
            value = bindings.get(variable)
            if value is None:
                return None
            resolved.append(value)
        elif "$(" in argument or "`" in argument:
            return None
        else:
            resolved.append(argument)
    return " ".join(resolved)


def _static_source_script(
    arguments: list[str], bindings: dict[str, str | None]
) -> str | None:
    if not arguments:
        return None
    source_path, unresolved = _resolve_shell_value(arguments[0], bindings)
    if unresolved or source_path is None:
        return None
    if any(_resolve_shell_value(argument, bindings)[1] for argument in arguments[1:]):
        return None
    path = _literal_absolute_path(source_path)
    if path is None or not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _mask_awk_strings_comments_and_regexes(source: str) -> str:
    masked = list(source)
    index = 0
    expect_operand = True
    brace_depth = 0
    while index < len(source):
        if source[index] == "\n":
            if brace_depth == 0:
                expect_operand = True
            index += 1
            continue
        if source[index] == "#":
            end = source.find("\n", index)
            end = len(source) if end < 0 else end
            masked[index:end] = " " * (end - index)
            index = end
            continue
        if source[index] == '"':
            start = index
            index += 1
            while index < len(source):
                if source[index] == "\\":
                    index += 2
                    continue
                if source[index] == '"':
                    index += 1
                    break
                index += 1
            for position in range(start, min(index, len(source))):
                if source[position] != "\n":
                    masked[position] = " "
            expect_operand = False
            continue
        if source[index] == "/" and expect_operand:
            start = index
            index += 1
            while index < len(source):
                if source[index] == "\\":
                    index += 2
                    continue
                if source[index] == "/":
                    index += 1
                    break
                index += 1
            for position in range(start, min(index, len(source))):
                if source[position] != "\n":
                    masked[position] = " "
            expect_operand = False
            continue
        if source[index].isalpha() or source[index] == "_":
            word = re.match(r"[A-Za-z_][A-Za-z0-9_]*", source[index:])
            assert word is not None
            index += word.end()
            expect_operand = word.group(0) in {"print", "printf", "return"}
            continue
        if source[index] == "$":
            index += 1
            if index < len(source) and source[index] == "(":
                depth = 1
                index += 1
                while index < len(source) and depth:
                    if source[index] == "(":
                        depth += 1
                    elif source[index] == ")":
                        depth -= 1
                    index += 1
            else:
                while index < len(source) and source[index].isalnum():
                    index += 1
            expect_operand = False
            continue
        if source.startswith(("&&", "||"), index):
            expect_operand = True
            index += 2
            continue
        if source[index] in "([{,;=~!?:+-*%^<>":
            expect_operand = True
            if source[index] == "{":
                brace_depth += 1
        elif source[index] in ")]}" or source[index].isdigit():
            expect_operand = False
            if source[index] == "}" and brace_depth:
                brace_depth -= 1
        elif source[index] == "/":
            expect_operand = True
        elif source[index] == "|":
            expect_operand = True
        index += 1
    return "".join(masked)


def _awk_source_executes_commands(source: str) -> bool:
    source = source.replace("\\\n", "")
    masked = _mask_awk_strings_comments_and_regexes(source)
    if re.search(r"(?m)^\s*@(include|load)\b", masked):
        return True
    if re.search(r"\bsystem\s*\(", masked):
        return True
    return bool(re.search(r"(?<!\|)\|(?!\|)&?", masked))


def _awk_program_sources(
    segment: list[str], workdir: str | None, bindings: dict[str, str | None]
) -> tuple[list[str] | None, str | None]:
    index = _skip_prefixes(segment)
    if index >= len(segment) or os.path.basename(segment[index]) not in {
        "awk",
        "gawk",
        "mawk",
        "nawk",
    }:
        return None, None
    arguments = segment[index + 1 :]
    sources: list[str] = []
    has_program_option = False
    safe_flag_options = {
        "--bignum",
        "--characters-as-bytes",
        "--csv",
        "--lint",
        "--non-decimal-data",
        "--posix",
        "--sandbox",
        "--traditional",
    }
    value_options = {"-F", "-v", "--assign", "--field-separator"}

    def static_source(value: str) -> str | None:
        variable = _shell_variable_name(value)
        if variable is not None:
            return bindings.get(variable)
        return value

    def has_shell_expansion(value: str) -> bool:
        if re.search(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", value):
            return True
        return any(
            name in bindings or name in os.environ
            for name in re.findall(r"\$([A-Za-z_][A-Za-z0-9_]*)", value)
        )

    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token == "--":
            index += 1
            break
        if token in {"-l", "--load"} or token.startswith(("-l", "--load=")):
            return None, "awk extension"
        if token in {"-f", "--file"}:
            if index + 1 >= len(arguments):
                return None, "awk program"
            program_path = arguments[index + 1]
            index += 2
            if program_path == "-" or SHELL_META_RE.search(program_path):
                return None, "awk program"
            path = _literal_command_path(program_path, workdir)
            if path is None or not path.is_file():
                return None, "awk program"
            try:
                sources.append(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                return None, "awk program"
            has_program_option = True
            continue
        if token.startswith("--file=") or (token.startswith("-f") and token != "-f"):
            program_path = token.split("=", 1)[1] if "=" in token else token[2:]
            arguments[index:index + 1] = ["-f", program_path]
            continue
        if token in {"-e", "--source"}:
            if index + 1 >= len(arguments):
                return None, "awk program"
            source = static_source(arguments[index + 1])
            if source is None or has_shell_expansion(source):
                return None, "awk program"
            sources.append(source)
            has_program_option = True
            index += 2
            continue
        if token.startswith("--source="):
            source = static_source(token.split("=", 1)[1])
            if source is None or has_shell_expansion(source):
                return None, "awk program"
            sources.append(source)
            has_program_option = True
            index += 1
            continue
        if token in value_options:
            if index + 1 >= len(arguments):
                return None, "awk option"
            index += 2
            continue
        if token.startswith(("-F", "-v")) and token not in {"-F", "-v"}:
            index += 1
            continue
        if token.startswith(("--assign=", "--field-separator=")):
            index += 1
            continue
        if token in safe_flag_options:
            index += 1
            continue
        if token == "-W":
            if index + 1 >= len(arguments) or arguments[index + 1] not in {
                "posix",
                "traditional",
                "lint",
            }:
                return None, "awk option"
            index += 2
            continue
        if token in {"-Wposix", "-Wtraditional", "-Wlint"}:
            index += 1
            continue
        if token.startswith("-"):
            return None, "awk option"
        break
    if not has_program_option:
        if index >= len(arguments):
            return None, "awk program"
        source = static_source(arguments[index])
        if source is None or has_shell_expansion(source):
            return None, "awk program"
        sources.append(source)
    return sources, None


def _literal_interpreter_source(
    segment: list[str],
    workdir: str | None,
    bindings: dict[str, str | None] | None = None,
) -> tuple[str, str | None, str | None]:
    index = _skip_prefixes(segment)
    if index >= len(segment):
        return "", None, None
    executable = os.path.basename(segment[index])
    if executable not in SHELL_INTERPRETERS | {"node", "nodejs", "python", "python3"}:
        direct_path = _literal_command_path(segment[index], workdir)
        if direct_path is None or not direct_path.is_file():
            if "/" in segment[index] and not os.path.isabs(segment[index]):
                return "", None, "relative script"
            return "", None, None
        try:
            source = direct_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return "", None, None
        shebang = source.splitlines()[0] if source.startswith("#!") else ""
        if "python" in shebang:
            return "python", source, None
        if re.search(r"\bnode(?:js)?\b", shebang):
            return "javascript", source, None
        if any(shell in shebang for shell in SHELL_INTERPRETERS):
            return "shell", source, None
        if not os.path.isabs(segment[index]):
            return "", None, "relative executable"
        return "", None, None
    if executable in {"python", "python3"}:
        kind = "python"
    elif executable in {"node", "nodejs"}:
        kind = "javascript"
    else:
        kind = "shell"
    index += 1
    while index < len(segment):
        token = segment[index]
        if kind == "python" and token == "-c":
            if index + 1 >= len(segment):
                return kind, None, "python -c"
            return kind, segment[index + 1], None
        if kind == "javascript" and token in {"-e", "--eval"}:
            if index + 1 >= len(segment):
                return kind, None, "node -e"
            return kind, segment[index + 1], None
        if kind == "javascript" and token.startswith(("--eval=", "-e=")):
            return kind, token.split("=", 1)[1], None
        if token in {"-c", "--command"}:
            return kind, None, None
        if kind == "python" and token == "-m":
            if index + 1 >= len(segment):
                return kind, None, "python module"
            module = segment[index + 1]
            executable_index = _skip_prefixes(segment)
            python_path_overridden = "PYTHONPATH" in (bindings or {}) or any(
                prefix.startswith("PYTHONPATH=")
                for prefix in segment[:executable_index]
            )
            root = Path(workdir) if workdir else Path.cwd()
            module_path = Path(*module.split("."))
            locally_shadowed = any(
                candidate.is_file()
                for candidate in (
                    root / f"{module_path}.py",
                    root / module_path / "__init__.py",
                    root / module_path / "__main__.py",
                )
            )
            if (
                module in PYTHON_NON_PR_MODULE_RUNNERS
                and not locally_shadowed
                and not python_path_overridden
            ):
                return kind, None, None
            return kind, None, "python module"
        if kind == "shell" and (
            token in SHELL_PARSE_ONLY_LONG_OPTIONS
            or (
                token.startswith("-")
                and not token.startswith("--")
                and "n" in token[1:]
            )
        ):
            return kind, None, None
        if token == "--":
            index += 1
            break
        if not token.startswith("-"):
            break
        if kind == "python" and token in {"-W", "-X"}:
            index += 2
        else:
            index += 1
    if index >= len(segment):
        return kind, None, f"{executable} stdin"
    path = _literal_command_path(segment[index], workdir)
    if path is None or not path.is_file():
        return kind, None, f"{executable} script"
    try:
        return kind, path.read_text(encoding="utf-8"), None
    except OSError:
        return kind, None, f"{executable} script"


def _python_embedded_commands(source: str) -> tuple[list[str], bool]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], True
    commands: list[str] = []
    unresolved = bool(
        re.search(r"api\.github\.com", source, re.I)
        and (
            re.search(r"\bmutation\b", source, re.I)
            or (
                re.search(
                    r"(?:['\"](?:PATCH|POST|PUT)['\"]|\.(?:patch|post|put)\s*\()",
                    source,
                    re.I,
                )
                and re.search(r"['\"](?:title|body|draft)['\"]", source, re.I)
            )
        )
    )
    call_names = {
        "os.system",
        "os.popen",
        "os.execl",
        "os.execle",
        "os.execlp",
        "os.execlpe",
        "os.execv",
        "os.execve",
        "os.execvp",
        "os.execvpe",
        "os.spawnl",
        "os.spawnle",
        "os.spawnlp",
        "os.spawnlpe",
        "os.spawnv",
        "os.spawnve",
        "os.spawnvp",
        "os.spawnvpe",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.getoutput",
        "subprocess.getstatusoutput",
        "subprocess.Popen",
        "subprocess.run",
    }
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                if imported.name in {"httpx", "os", "requests", "subprocess"}:
                    aliases[imported.asname or imported.name] = imported.name
        elif isinstance(node, ast.ImportFrom) and node.module in {
            "httpx",
            "os",
            "requests",
            "subprocess",
        }:
            for imported in node.names:
                aliases[imported.asname or imported.name] = (
                    f"{node.module}.{imported.name}"
                )

    def qualified_name(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            parent = qualified_name(node.value)
            return f"{parent}.{node.attr}" if parent else None
        return None

    for node in ast.walk(tree):
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        if value is not None:
            pending = [(target, value) for target in targets]
            while pending:
                target, assigned = pending.pop()
                canonical = qualified_name(assigned)
                if isinstance(target, ast.Name) and canonical in call_names:
                    aliases[target.id] = canonical
                elif (
                    isinstance(target, (ast.Tuple, ast.List))
                    and isinstance(assigned, (ast.Tuple, ast.List))
                    and len(target.elts) == len(assigned.elts)
                ):
                    pending.extend(zip(target.elts, assigned.elts))

    def literal_value(node: ast.AST) -> Any:
        try:
            return ast.literal_eval(node)
        except (ValueError, TypeError):
            return None

    def http_call_changes_pr(node: ast.Call, name: str) -> bool | None:
        http_modules = {"requests", "httpx"}
        module = name.split(".", 1)[0]
        operation = name.rsplit(".", 1)[-1]
        if module not in http_modules and operation not in {
            "patch",
            "post",
            "put",
            "request",
        }:
            return None
        method: str | None
        url_node: ast.AST | None
        if operation == "request":
            if len(node.args) < 2:
                return True
            method_value = literal_value(node.args[0])
            method = method_value.upper() if isinstance(method_value, str) else None
            url_node = node.args[1]
            payload_start = 2
        elif operation in {"post", "put", "patch"}:
            method = operation.upper()
            url_node = node.args[0] if node.args else None
            payload_start = 1
        else:
            return None
        if method is None or url_node is None:
            return True
        url = literal_value(url_node)
        if not isinstance(url, str):
            return True
        parsed = urlsplit(url)
        if not parsed.hostname or parsed.hostname.lower() != "api.github.com":
            return False
        endpoint = parsed.path.lstrip("/")
        payload_nodes = [
            *node.args[payload_start:],
            *[
                keyword.value
                for keyword in node.keywords
                if keyword.arg in {"data", "json", "content"}
            ],
        ]
        payload_values = [literal_value(payload_node) for payload_node in payload_nodes]
        unresolved_payload = any(value is None for value in payload_values)
        payload = "\n".join(
            repr(value) for value in payload_values if value is not None
        )
        if endpoint == "graphql":
            return unresolved_payload or bool(re.search(r"\bmutation\b", payload, re.I))
        pulls_match = REST_PULLS_RE.fullmatch(endpoint)
        if pulls_match:
            if pulls_match.group("number") is None:
                return method == "POST"
            return method in {"POST", "PUT", "PATCH"} and (
                unresolved_payload
                or bool(re.search(r"['\"](?:title|body|draft)['\"]\s*:", payload, re.I))
            )
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = qualified_name(node.func)
        if name is None and isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name is None:
            continue
        http_result = http_call_changes_pr(node, name)
        if http_result is True:
            unresolved = True
            continue
        if http_result is False or name not in call_names:
            continue
        if not node.args:
            unresolved = True
            continue
        if name.startswith("os.execl"):
            arguments = list(node.args)
            if name.endswith(("le", "lpe")) and arguments:
                arguments.pop()
            if len(arguments) < 2:
                unresolved = True
                continue
            command_arguments = [arguments[0], *arguments[2:]]
            if all(
                isinstance(argument, ast.Constant) and isinstance(argument.value, str)
                for argument in command_arguments
            ):
                commands.append(
                    shlex.join([str(argument.value) for argument in command_arguments])
                )
            else:
                unresolved = True
            continue
        if name.startswith("os.spawnl"):
            arguments = list(node.args)
            if name.endswith(("le", "lpe")) and arguments:
                arguments.pop()
            if len(arguments) < 3:
                unresolved = True
                continue
            command_arguments = [arguments[1], *arguments[3:]]
            if all(
                isinstance(argument, ast.Constant) and isinstance(argument.value, str)
                for argument in command_arguments
            ):
                commands.append(
                    shlex.join([str(argument.value) for argument in command_arguments])
                )
            else:
                unresolved = True
            continue
        command = (
            next(
                (
                    argument
                    for argument in reversed(node.args)
                    if isinstance(argument, (ast.List, ast.Tuple))
                ),
                node.args[0],
            )
            if name.startswith(("os.exec", "os.spawn"))
            else node.args[0]
        )
        if isinstance(command, ast.Constant) and isinstance(command.value, str):
            commands.append(command.value)
            continue
        if isinstance(command, (ast.List, ast.Tuple)) and all(
            isinstance(item, ast.Constant) and isinstance(item.value, str)
            for item in command.elts
        ):
            commands.append(shlex.join([str(item.value) for item in command.elts]))
            continue
        unresolved = True
    return commands, unresolved


def _javascript_embedded_commands(source: str) -> tuple[list[str], bool]:
    comment_free = _mask_javascript_comments(source)
    process_methods = {
        "exec",
        "execSync",
        "execFile",
        "execFileSync",
        "fork",
        "spawn",
        "spawnSync",
    }
    child_process_names = {"child_process"}
    binding_re = re.compile(
        r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*"
        r"require\s*\(\s*['\"](?:node:)?child_process['\"]\s*\)"
    )
    child_process_names.update(
        match.group("name") for match in binding_re.finditer(comment_free)
    )
    namespace_import_re = re.compile(
        r"\bimport\s+\*\s+as\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s+from\s*"
        r"['\"](?:node:)?child_process['\"]"
    )
    child_process_names.update(
        match.group("name") for match in namespace_import_re.finditer(comment_free)
    )
    dynamic_import_re = re.compile(
        r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*"
        r"(?:await\s+)?import\s*\(\s*['\"](?:node:)?child_process['\"]\s*\)"
    )
    child_process_names.update(
        match.group("name") for match in dynamic_import_re.finditer(comment_free)
    )
    receiver = "|".join(re.escape(name) for name in sorted(child_process_names))
    command_call_re = re.compile(
        rf"(?:\b(?:{receiver})\b|"
        r"require\s*\(\s*['\"](?:node:)?child_process['\"]\s*\))"
        r"\s*\.\s*(?P<method>exec|execSync|execFile|execFileSync|fork|spawn|spawnSync)"
        r"\s*\("
    )
    direct_methods: dict[str, str] = {}
    destructured_re = re.compile(
        r"\b(?:const|let|var)\s*\{(?P<body>[^}]*)\}\s*=\s*"
        r"require\s*\(\s*['\"](?:node:)?child_process['\"]\s*\)"
    )
    for binding in destructured_re.finditer(comment_free):
        for item in binding.group("body").split(","):
            name, separator, alias = item.strip().partition(":")
            if name in process_methods:
                direct_methods[alias.strip() if separator else name] = name
    import_re = re.compile(
        r"\bimport\s*\{(?P<body>[^}]*)\}\s*from\s*"
        r"['\"](?:node:)?child_process['\"]"
    )
    for binding in import_re.finditer(comment_free):
        for item in binding.group("body").split(","):
            parts = re.split(r"\s+as\s+", item.strip())
            if parts and parts[0] in process_methods:
                direct_methods[parts[-1]] = parts[0]
    direct_assignment_re = re.compile(
        r"\b(?:const|let|var)\s+(?P<alias>[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*"
        r"require\s*\(\s*['\"](?:node:)?child_process['\"]\s*\)\s*\.\s*"
        r"(?P<method>exec|execSync|execFile|execFileSync|fork|spawn|spawnSync)\b"
    )
    for binding in direct_assignment_re.finditer(comment_free):
        direct_methods[binding.group("alias")] = binding.group("method")
    commands: list[str] = []
    rest_mutation = bool(
        re.search(
            r"api\.github\.com/repos/[^/'\"\s]+/[^/'\"\s]+/pulls(?:/\d+)?",
            comment_free,
            re.I,
        )
        and re.search(
            r"(?:\bmethod\s*:\s*['\"](?:PATCH|POST|PUT)['\"]|"
            r"\.(?:patch|post|put)\s*\()",
            comment_free,
            re.I,
        )
    )
    graphql_mutation = bool(
        re.search(r"api\.github\.com/graphql", comment_free, re.I)
        and GRAPHQL_DIRECT_PR_MUTATION_RE.search(comment_free)
    )
    unresolved = rest_mutation or graphql_mutation
    calls = [
        (match.start(), match.end(), match.group("method"))
        for match in command_call_re.finditer(comment_free)
    ]
    if direct_methods:
        aliases = "|".join(re.escape(alias) for alias in sorted(direct_methods))
        direct_call_re = re.compile(rf"\b(?P<alias>{aliases})\s*\(")
        calls.extend(
            (match.start(), match.end(), direct_methods[match.group("alias")])
            for match in direct_call_re.finditer(comment_free)
        )
    for _start, end, method in sorted(calls):
        remainder = source[end:]
        literal_match = re.match(
            rf"\s*(?P<literal>{JAVASCRIPT_LITERAL})", remainder, re.S
        )
        if literal_match is None:
            unresolved = True
            continue
        command = _decode_javascript_literal(literal_match.group("literal"))
        if command is None:
            unresolved = True
        elif method in {"exec", "execSync"}:
            commands.append(command)
        else:
            tail = remainder[literal_match.end() :]
            if not tail.lstrip().startswith(","):
                commands.append(
                    shlex.join(["node", command])
                    if method == "fork"
                    else shlex.join([command])
                )
                continue
            arguments_match = re.match(r"\s*,\s*\[(?P<items>[^][]*)\]", tail, re.S)
            if arguments_match is None:
                unresolved = True
                continue
            arguments = _javascript_literal_list(arguments_match.group("items"))
            if arguments is None:
                unresolved = True
            else:
                commands.append(
                    shlex.join(["node", command, *arguments])
                    if method == "fork"
                    else shlex.join([command, *arguments])
                )
    return commands, unresolved


def _javascript_literal_list(source: str) -> list[str] | None:
    values: list[str] = []
    position = 0
    while position < len(source):
        separator_pattern = r"\s*" if not values else r"\s*,\s*"
        separator = re.match(separator_pattern, source[position:])
        if separator is None:
            return None
        position += separator.end()
        if position >= len(source):
            break
        literal = re.match(JAVASCRIPT_LITERAL, source[position:], re.S)
        if literal is None:
            return None
        value = _decode_javascript_literal(literal.group(0))
        if value is None:
            return None
        values.append(value)
        position += literal.end()
        remainder = source[position:]
        if remainder.strip() and not remainder.lstrip().startswith(","):
            return None
    return values


def _command_assessment(
    command: str,
    depth: int = 0,
    inherited_bindings: dict[str, str | None] | None = None,
    workdir: str | None = None,
    allow_owned_helpers: bool = True,
) -> tuple[bool, str | None]:
    if depth > 8:
        return True, "nested shell recursion"
    bindings = dict(inherited_bindings or {})
    has_exact_expandable_helper = _has_exact_expandable_helper_spelling(command)
    current_workdir = workdir
    directory_stack: list[str] = []
    trusted_review_reply_followup = False
    command_without_data, shell_bodies = _without_heredoc_payloads(command)
    substitutions, unresolved_substitution = _shell_command_substitutions(
        command_without_data
    )
    if unresolved_substitution:
        return True, "command substitution"
    for substitution in substitutions:
        blocked, route = _command_assessment(
            substitution, depth + 1, bindings, workdir, allow_owned_helpers
        )
        if blocked:
            return blocked, route
    for body in shell_bodies:
        blocked, route = _command_assessment(
            body, depth + 1, bindings, workdir, allow_owned_helpers
        )
        if blocked:
            return blocked, route
    for segment_number, segment in enumerate(_segments(command_without_data)):
        review_reply_followup = trusted_review_reply_followup
        trusted_review_reply_followup = False
        assignments, assignment_end = _leading_shell_assignments(segment)
        direct_python = (
            assignment_end == 0
            and bool(segment)
            and segment[0] in {"python", "python3"}
        )
        direct_authenticated_python = (
            assignment_end == 1
            and len(segment) > 1
            and segment[1] in {"python", "python3"}
        )
        direct_trusted_gh = (
            assignment_end < len(segment)
            and segment[assignment_end] == "gh"
            and set(assignments) <= {"GH_HOST", "GH_TOKEN"}
        )
        bindings.update(assignments)
        if assignment_end == len(segment):
            continue
        segment, control_route = _normalize_control_indirection(segment)
        if control_route is not None:
            return True, control_route
        if not segment:
            continue
        executable_index = _skip_prefixes(segment)
        executable_name = (
            os.path.basename(segment[executable_index])
            if executable_index < len(segment)
            else ""
        )
        if executable_name == "export":
            for argument in segment[executable_index + 1 :]:
                if argument in {"-p", "--"}:
                    continue
                if argument.startswith("-"):
                    return True, "export"
                assignment = SHELL_ASSIGNMENT_RE.fullmatch(argument)
                if assignment is not None:
                    value = assignment.group("value")
                    bindings[assignment.group("name")] = (
                        None if SHELL_META_RE.search(value) else value
                    )
                elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", argument):
                    bindings[argument] = os.environ.get(argument)
                else:
                    return True, "export"
            continue
        if executable_name in {"cd", "pushd", "popd"}:
            arguments = segment[executable_index + 1 :]
            if executable_name == "popd":
                if arguments or not directory_stack:
                    return True, "popd"
                current_workdir = directory_stack.pop()
                continue
            while arguments and arguments[0] in {"-L", "-P", "--"}:
                arguments = arguments[1:]
            if len(arguments) > 1:
                return True, executable_name
            target = arguments[0] if arguments else os.environ.get("HOME", "")
            destination = _literal_directory(target, current_workdir)
            if destination is None:
                return True, executable_name
            if executable_name == "pushd":
                if current_workdir is None:
                    return True, "pushd"
                directory_stack.append(current_workdir)
            current_workdir = str(destination)
            continue
        has_env_split, env_script = _env_split_script(segment)
        if has_env_split:
            if not env_script:
                return True, "env -S"
            blocked, route = _command_assessment(
                env_script, depth + 1, bindings, current_workdir, allow_owned_helpers
            )
            if blocked:
                return blocked, route
            continue
        watch_script = _watch_script(segment)
        if watch_script is not None:
            if not watch_script:
                return True, "watch command"
            blocked, route = _command_assessment(
                watch_script, depth + 1, bindings, current_workdir, allow_owned_helpers
            )
            if blocked:
                return blocked, route
        segment, dynamic_route = _resolve_dynamic_executable(segment, bindings)
        if dynamic_route is not None:
            return True, dynamic_route
        segment, builtin_route = _normalize_builtin_indirection(segment, bindings)
        if builtin_route is not None:
            return True, builtin_route
        segment, control_route = _normalize_control_indirection(segment)
        if control_route is not None:
            return True, control_route
        if not segment:
            continue
        segment, dynamic_route = _resolve_dynamic_executable(segment, bindings)
        if dynamic_route is not None:
            return True, dynamic_route
        if (
            allow_owned_helpers
            and depth == 0
            and direct_python
            and not bindings
            and _trusted_help_only_invocation(segment)
        ):
            continue
        review_state_invalid = _review_state_invocation_is_invalid(segment)
        if review_state_invalid is not None:
            authenticated_followup = (
                review_reply_followup
                and depth == 0
                and assignment_end == 1
                and set(assignments) == {"GH_TOKEN"}
                and set(bindings) == {"GH_TOKEN"}
                and direct_authenticated_python
            )
            trusted_review_state = (
                allow_owned_helpers
                and _review_state_helper_is_trusted()
                and depth == 0
                and (
                    (
                        segment_number == 0
                        and direct_python
                        and not bindings
                        and segment[0] in {"python", "python3"}
                    )
                    or authenticated_followup
                )
            )
            if review_state_invalid or not trusted_review_state:
                return True, "review state query"
            continue
        segment, interpreter_route = _normalize_interpreter_entrypoint(
            segment,
            bindings,
            allow_expandable_helpers=(
                allow_owned_helpers
                and depth == 0
                and segment_number == 0
                and direct_python
                and has_exact_expandable_helper
            ),
            trusted_helper_interpreter=(
                allow_owned_helpers
                and depth == 0
                and segment_number == 0
                and direct_python
            ),
        )
        if interpreter_route is not None:
            return True, interpreter_route
        publisher_invalid = _publisher_invocation_is_invalid(segment)
        if publisher_invalid is not None:
            if publisher_invalid:
                return True, None
            continue
        updater_invalid = _updater_invocation_is_invalid(segment)
        if updater_invalid is not None:
            if updater_invalid:
                return True, None
            continue
        executable_index = _skip_prefixes(segment)
        executable = (
            segment[executable_index] if executable_index < len(segment) else None
        )
        executable_name = os.path.basename(executable) if executable else None
        if executable_name and executable_name.startswith("gh-"):
            return True, executable_name
        if executable_name == "eval":
            script = _static_eval_script(segment[executable_index + 1 :], bindings)
            if script is None:
                return True, "eval"
            blocked, route = _command_assessment(
                script, depth + 1, bindings, current_workdir, allow_owned_helpers
            )
            if blocked:
                return blocked, route
            continue
        if executable in {"source", "."}:
            script = _static_source_script(segment[executable_index + 1 :], bindings)
            if script is None:
                return True, executable
            blocked, route = _command_assessment(
                script, depth + 1, bindings, current_workdir, allow_owned_helpers
            )
            if blocked:
                return blocked, route
            continue
        nested_shell = _nested_shell_script(segment)
        if nested_shell is not None:
            variable = _shell_variable_name(nested_shell)
            if variable is not None:
                resolved_shell = bindings.get(variable)
            elif DYNAMIC_COMMAND_RE.search(nested_shell):
                resolved_shell = None
            else:
                resolved_shell = nested_shell
            if not resolved_shell:
                return True, f"{executable_name or 'shell'} -c"
            blocked, route = _command_assessment(
                resolved_shell,
                depth + 1,
                bindings,
                current_workdir,
                allow_owned_helpers,
            )
            if blocked:
                return blocked, route
            continue
        awk_sources, awk_route = _awk_program_sources(
            segment, current_workdir, bindings
        )
        if awk_route is not None:
            return True, awk_route
        if awk_sources is not None:
            if any(_awk_source_executes_commands(source) for source in awk_sources):
                return True, "awk command"
            continue
        if (
            depth == 0
            and segment_number == 0
            and command_without_data.strip() == TRUSTED_TASK_TEST_COMMAND
            and _trusted_task_test_script(segment, current_workdir)
        ):
            continue
        script_kind, script_source, script_route = _literal_interpreter_source(
            segment, current_workdir, bindings
        )
        if script_route is not None:
            return True, script_route
        if script_source is not None:
            if script_kind == "python":
                python_commands, unresolved_python = _python_embedded_commands(
                    script_source
                )
                if unresolved_python:
                    return True, "python command"
                for python_command in python_commands:
                    blocked, route = _command_assessment(
                        python_command,
                        depth + 1,
                        bindings,
                        current_workdir,
                        allow_owned_helpers,
                    )
                    if blocked:
                        return blocked, route
            elif script_kind == "javascript":
                javascript_commands, unresolved_javascript = (
                    _javascript_embedded_commands(script_source)
                )
                if unresolved_javascript:
                    return True, "node command"
                for javascript_command in javascript_commands:
                    blocked, route = _command_assessment(
                        javascript_command,
                        depth + 1,
                        bindings,
                        current_workdir,
                        allow_owned_helpers,
                    )
                    if blocked:
                        return blocked, route
            else:
                blocked, route = _command_assessment(
                    script_source,
                    depth + 1,
                    bindings,
                    current_workdir,
                    allow_owned_helpers,
                )
                if blocked:
                    return blocked, route
            continue
        curl_blocked, curl_route = _curl_changes_pr(segment, bindings)
        if curl_blocked:
            return True, curl_route
        wget_blocked, wget_route = _wget_changes_pr(segment, bindings)
        if wget_blocked:
            return True, wget_route
        operation = _gh_command(segment)
        if operation is not None and operation[0] in {"edit", "issue_edit", "api"}:
            segment, argument_route = _resolve_sensitive_gh_arguments(segment, bindings)
            if argument_route is not None:
                return True, argument_route
            operation = _gh_command(segment)
        if operation is None:
            continue
        name, arguments, repository = operation
        if name == "unproven":
            return True, arguments[0]
        if name == "create":
            return True, None
        elif name == "edit" and _changes_pr_text(arguments):
            return True, None
        elif name == "ready":
            return True, None
        elif name == "issue_edit" and _changes_pr_text(arguments):
            if _issue_text_edit_is_noncanonical(
                _issue_edit_identities(arguments, repository)
            ):
                return True, None
        elif name == "api":
            review_reply = _review_reply_route_path(arguments) is not None
            review_resolution = _is_review_resolution_route(arguments)
            trusted_gh_route = (
                depth == 0
                and segment_number == 0
                and direct_trusted_gh
                and set(bindings) <= {"GH_HOST", "GH_TOKEN"}
            )
            if (review_reply or review_resolution) and not trusted_gh_route:
                return True, "gh executable"
            if (review_reply or review_resolution) and not (
                _gh_targets_github_dot_com(segment, bindings)
            ):
                return True, "GitHub hostname"
            if _review_reply_route_is_unproven(arguments):
                return True, "review reply"
            if _review_resolution_route_is_unproven(arguments, repository):
                return True, "review thread resolution"
            if _api_changes_pr_text(arguments):
                return True, None
            trusted_review_reply_followup = review_reply
    return False, None


def _command_is_noncanonical(
    command: str,
    depth: int = 0,
    workdir: str | None = None,
    allow_owned_helpers: bool = True,
) -> bool:
    return _command_assessment(
        command, depth, workdir=workdir, allow_owned_helpers=allow_owned_helpers
    )[0]


def _command_has_multi_target_issue_text_edit(command: str, depth: int = 0) -> bool:
    if depth > 8:
        return False
    command_without_data, shell_bodies = _without_heredoc_payloads(command)
    if any(
        _command_has_multi_target_issue_text_edit(body, depth + 1)
        for body in shell_bodies
    ):
        return True
    for segment in _segments(command_without_data):
        nested_shell = _nested_shell_script(segment)
        if nested_shell and _command_has_multi_target_issue_text_edit(
            nested_shell, depth + 1
        ):
            return True
        operation = _gh_command(segment)
        if operation is None:
            continue
        name, arguments, repository = operation
        if name != "issue_edit" or not _changes_pr_text(arguments):
            continue
        identities = _issue_edit_identities(arguments, repository)
        if identities is not None and len(identities) > 1:
            return True
    return False


def _canonical_body(body: Any, identity: tuple[str, int] | None) -> bool:
    if not isinstance(body, str) or not VALIDATOR.is_file():
        return False
    if identity is None:
        return False
    repository, pr_number = identity
    try:
        result = _budgeted_run(
            [
                sys.executable,
                str(VALIDATOR),
                "/dev/stdin",
                "--repository",
                repository,
                "--pr",
                str(pr_number),
            ],
            input=body,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _connector_identity(tool_input: dict[str, Any]) -> tuple[str, int] | None:
    repository: str | None = None
    for key in ("repository_full_name", "repository"):
        value = tool_input.get(key)
        if isinstance(value, str):
            repository = _normalize_repository(value)
            if repository:
                break
    if repository is None:
        owner = tool_input.get("owner")
        repo = tool_input.get("repo")
        if isinstance(owner, str) and isinstance(repo, str):
            repository = _normalize_repository(f"{owner}/{repo}")

    pr_number: int | None = None
    for key in (
        "pull_number",
        "pr_number",
        "pullNumber",
        "issue_number",
        "issueNumber",
        "number",
    ):
        value = tool_input.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            pr_number = value
            break
        if isinstance(value, str) and value.isdigit() and int(value) > 0:
            pr_number = int(value)
            break
    if repository is None or pr_number is None:
        return None
    return repository, pr_number


def _connector_call_is_noncanonical(tool_name: str, tool_input: dict[str, Any]) -> bool:
    if tool_name.endswith("create_pull_request"):
        return True
    if tool_name.endswith("update_pull_request"):
        changes_text = "title" in tool_input or "body" in tool_input
        changes_ready = any(
            key in tool_input and tool_input.get(key) in {False, "false", 0, "0", None}
            for key in ("draft", "isDraft", "is_draft")
        )
        return changes_text or changes_ready
    if tool_name.endswith("update_issue"):
        changes_text = "title" in tool_input or "body" in tool_input
        if not changes_text:
            return False
        identity = _connector_identity(tool_input)
        return _issue_text_edit_is_noncanonical(
            [identity] if identity is not None else None
        )
    return False


def _tool_is_ready_mutation(tool_name: str) -> bool:
    return bool(
        re.search(
            r"(?:(?:mark|set|make).*pull_request.*ready|"
            r"pull_request.*(?:mark|set|make).*ready)",
            tool_name,
            re.I,
        )
    )


def _payload_uses_write_stdin(payload: dict[str, Any]) -> bool:
    tool_name = str(payload.get("tool_name", "")).lower()
    if tool_name.endswith("write_stdin"):
        return True
    tool_input = payload.get("tool_input", {})
    code = tool_input.get("code") if isinstance(tool_input, dict) else None
    return isinstance(code, str) and NESTED_WRITE_STDIN_CALL_RE.search(
        _mask_javascript_strings_and_comments(code)
    ) is not None


def blocks(payload: dict[str, Any]) -> bool:
    tool_name = str(payload.get("tool_name", "")).lower()
    tool_input = payload.get("tool_input", {})
    if _tool_is_ready_mutation(tool_name):
        return True
    if tool_name.endswith(
        ("create_pull_request", "update_pull_request", "update_issue")
    ):
        if not isinstance(tool_input, dict):
            return True
        return _connector_call_is_noncanonical(tool_name, tool_input)
    commands, unresolved = _candidate_commands(payload)
    allow_owned_helpers = not _payload_uses_write_stdin(payload)
    return unresolved or any(
        _command_is_noncanonical(
            command,
            workdir=workdir,
            allow_owned_helpers=allow_owned_helpers,
        )
        for command, workdir in commands
    )


def _block_message(payload: dict[str, Any]) -> str:
    commands, unresolved = _candidate_commands(payload)
    allow_owned_helpers = not _payload_uses_write_stdin(payload)
    if any(
        _command_has_multi_target_issue_text_edit(command)
        for command, _workdir in commands
    ):
        return (
            "Blocked multi-target issue text edit: edit one issue number at a time so "
            "the guard can classify it authoritatively as an issue or pull request."
        )
    for command, workdir in commands:
        _blocked, route = _command_assessment(
            command,
            workdir=workdir,
            allow_owned_helpers=allow_owned_helpers,
        )
        if route is not None:
            return (
                f"Blocked unproven command route `{route}`: safety could not be proven. "
                "Stop and surface this blocker at this tool boundary; do not retry through "
                "another shell, alias, extension, subcommand, or delegated tool."
            )
    if unresolved:
        return (
            "Blocked unproven nested delegated command route: safety could not be proven. "
            "Stop and surface this blocker at this tool boundary; do not retry through "
            "another shell, alias, extension, subcommand, or delegated tool."
        )
    return (
        "Blocked noncanonical PR publication: use publishing-reviewable-prs. "
        "New PRs require its guarded creator with exact preflight and final re-read; "
        "text and ready-state updates require its guarded updater."
    )


def _deny(message: str) -> int:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": message,
        },
        "systemMessage": message,
    }
    print(json.dumps(output), file=sys.stderr)
    return 2


def main() -> int:
    global _HOOK_DEADLINE
    _HOOK_DEADLINE = time.monotonic() + HOOK_SUBPROCESS_BUDGET_SECONDS
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return _deny(
            "Blocked malformed PreToolUse payload: safety could not be proven. "
            "Stop and surface this blocker at this tool boundary."
        )
    if not isinstance(payload, dict):
        return _deny(
            "Blocked non-object PreToolUse payload: safety could not be proven. "
            "Stop and surface this blocker at this tool boundary."
        )
    if not blocks(payload):
        return 0
    return _deny(_block_message(payload))


if __name__ == "__main__":
    raise SystemExit(main())
