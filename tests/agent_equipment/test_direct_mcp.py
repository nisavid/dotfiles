from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path

from agent_equipment.direct_mcp import STDIO_WORKING_DIRECTORY, stdio_overlay_entry
from agent_equipment.model import freeze_json

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "home/dot_config/agent-equipment/catalog-v1.json"
CHROME_DEVTOOLS_ROUTES = {
    "route:codex/direct-chrome-devtools": {
        "command": "npx",
        "args": ["-y", "chrome-devtools-mcp@1.7.0"],
        "cwd": "/",
    },
    "route:cursor/direct-chrome-devtools": {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "chrome-devtools-mcp@1.7.0"],
        "cwd": "/",
    },
}
# The devEngines declaration a stray `pnpm init` left in the home directory.
STRAY_PACKAGE_JSON = {
    "name": "stray",
    "devEngines": {"packageManager": {"name": "pnpm", "version": "12.11.2"}},
}
STRAY_NAMES = ("package.json", ".npmrc", "node_modules", ".nvmrc", ".node-version")
# Records its working directory, its arguments, and every stray project file
# visible from the working directory upward, then fails as npm 12 does when a
# visible package.json declares devEngines.
RECORDING_NPX = """#!/bin/sh
record=$NPX_RECORD
printf 'cwd %s\\n' "$(pwd -P)" > "$record"
for argument in "$@"; do
  printf 'arg %s\\n' "$argument" >> "$record"
done
blocked=
directory=$(pwd -P)
while :; do
  for name in package.json .npmrc node_modules .nvmrc .node-version; do
    if [ -e "$directory/$name" ]; then
      printf 'seen %s\\n' "$directory/$name" >> "$record"
    fi
  done
  if [ -f "$directory/package.json" ] &&
    grep -q devEngines "$directory/package.json"; then
    blocked=$directory/package.json
  fi
  [ "$directory" = / ] && break
  directory=$(dirname "$directory")
done
if [ -n "$blocked" ]; then
  echo "npm error code EBADDEVENGINES ($blocked)" >&2
  exit 1
fi
"""
SUBPROCESS_TIMEOUT_SECONDS = 30.0


def _catalog_routes() -> Iterator[tuple[str, str, dict[str, object]]]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

    def walk(value: object) -> Iterator[tuple[str, str, dict[str, object]]]:
        if isinstance(value, dict):
            identity = value.get("identity")
            provider = value.get("provider")
            if (
                isinstance(identity, str)
                and identity.startswith("route:")
                and isinstance(provider, dict)
            ):
                harness = identity.removeprefix("route:").split("/", 1)[0]
                yield identity, harness, provider
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    yield from walk(catalog)


def _route_provider(identity: str) -> tuple[str, dict[str, object]]:
    matches = [
        (harness, provider)
        for route, harness, provider in _catalog_routes()
        if route == identity
    ]
    if len(matches) != 1:
        raise AssertionError(f"{identity} is not exactly one catalog route")
    return matches[0]


class StdioOverlayEntryTests(unittest.TestCase):
    def test_chrome_devtools_entries_keep_the_pinned_argv_and_start_at_root(
        self,
    ) -> None:
        for identity, expected in CHROME_DEVTOOLS_ROUTES.items():
            with self.subTest(route=identity):
                harness, provider = _route_provider(identity)
                self.assertEqual(stdio_overlay_entry(harness, provider), expected)
                self.assertEqual(
                    stdio_overlay_entry(harness, freeze_json(provider)),
                    expected,
                )

    def test_every_codex_and_cursor_stdio_route_starts_at_root(self) -> None:
        routes = [
            (identity, harness, provider)
            for identity, harness, provider in _catalog_routes()
            if harness in {"codex", "cursor"} and provider.get("transport") == "stdio"
        ]
        self.assertGreater(len(routes), len(CHROME_DEVTOOLS_ROUTES))
        for identity, harness, provider in routes:
            with self.subTest(route=identity):
                entry = stdio_overlay_entry(harness, provider)
                self.assertEqual(entry["cwd"], STDIO_WORKING_DIRECTORY)
                self.assertEqual(entry["command"], provider["command"])
                arguments = provider["arguments"]
                assert isinstance(arguments, list)
                self.assertEqual(len(entry["args"]), len(arguments))
        self.assertEqual(STDIO_WORKING_DIRECTORY, "/")

    def test_secret_arguments_render_as_names(self) -> None:
        harness, provider = _route_provider("route:cursor/direct-github")
        self.assertEqual(
            stdio_overlay_entry(harness, provider)["args"],
            [
                "github",
                "--",
                "npx",
                "-y",
                "mcp-remote@0.1.38",
                "https://api.githubcopilot.com/mcp/",
                "--header",
                "Authorization:Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}",
            ],
        )

    def test_unsupported_harnesses_providers_and_arguments_are_rejected(
        self,
    ) -> None:
        harness, provider = _route_provider("route:codex/direct-chrome-devtools")
        with self.assertRaisesRegex(ValueError, "working-directory field"):
            stdio_overlay_entry("claude", provider)
        http_provider: dict[str, object] = {
            "kind": "direct_mcp",
            "server_name": "remote",
            "transport": "http",
            "url": "https://mcp.example.com/mcp",
        }
        invalid_arguments: tuple[object, ...] = (
            "-y",
            {"literal": 1},
            {"literal": "-y", "template": "{reference}"},
            {"secret_reference": "TOKEN", "template": "{reference}{reference}"},
            {"secret_reference": "TOKEN", "template": "Bearer"},
        )
        invalid_providers: list[dict[str, object]] = [
            http_provider,
            provider | {"kind": "native_plugin"},
            provider | {"env": {}},
            provider | {"command": None},
            provider | {"arguments": "-y chrome-devtools-mcp@1.7.0"},
            *(provider | {"arguments": [argument]} for argument in invalid_arguments),
        ]
        for invalid in invalid_providers:
            with self.subTest(provider=invalid), self.assertRaises(ValueError):
                stdio_overlay_entry(harness, invalid)

    def test_launch_ignores_stray_project_files_above_the_harness_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            scratch = root / "scratch"
            session = scratch / "session"
            session.mkdir(parents=True)
            (scratch / "package.json").write_text(
                json.dumps(STRAY_PACKAGE_JSON),
                encoding="utf-8",
            )
            (scratch / ".npmrc").write_text(
                "registry=http://127.0.0.1:9/\n",
                encoding="utf-8",
            )
            (scratch / "node_modules").mkdir()
            (scratch / ".nvmrc").write_text("18.0.0\n", encoding="utf-8")
            (scratch / ".node-version").write_text("18.0.0\n", encoding="utf-8")
            stray = {str(scratch / name) for name in STRAY_NAMES}
            bin_directory = root / "bin"
            bin_directory.mkdir()
            npx = bin_directory / "npx"
            npx.write_text(RECORDING_NPX, encoding="utf-8")
            npx.chmod(0o755)
            record = root / "record"
            environment = {
                "PATH": os.pathsep.join((str(bin_directory), "/usr/bin", "/bin")),
                "NPX_RECORD": str(record),
            }

            def launch(
                entry: dict[str, object],
                cwd: Path | str,
            ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
                command = entry["command"]
                arguments = entry["args"]
                assert isinstance(command, str) and isinstance(arguments, list)
                completed = subprocess.run(
                    [command, *(str(argument) for argument in arguments)],
                    cwd=cwd,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=SUBPROCESS_TIMEOUT_SECONDS,
                    check=False,
                )
                return completed, record.read_text(encoding="utf-8").splitlines()

            for identity in CHROME_DEVTOOLS_ROUTES:
                with self.subTest(route=identity):
                    harness, provider = _route_provider(identity)
                    entry = stdio_overlay_entry(harness, provider)
                    arguments = entry["args"]
                    assert isinstance(arguments, list)

                    # Without the entry's cwd the harness starts the server
                    # in its own directory, below the stray files.
                    exposed, exposed_record = launch(entry, session)
                    self.assertEqual(exposed.returncode, 1)
                    self.assertIn("EBADDEVENGINES", exposed.stderr)
                    self.assertLessEqual(
                        {f"seen {path}" for path in stray},
                        set(exposed_record),
                    )

                    cwd = entry["cwd"]
                    assert isinstance(cwd, str)
                    neutral, neutral_record = launch(entry, cwd)
                    self.assertEqual(neutral.returncode, 0, neutral.stderr)
                    self.assertEqual(neutral_record[0], "cwd /")
                    self.assertEqual(
                        [line for line in neutral_record if line.startswith("arg ")],
                        [f"arg {argument}" for argument in arguments],
                    )
                    self.assertFalse(
                        {f"seen {path}" for path in stray} & set(neutral_record)
                    )


if __name__ == "__main__":
    unittest.main()
