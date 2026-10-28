"""Generated overlay entries for direct-MCP stdio routes."""

from __future__ import annotations

from collections.abc import Mapping

STDIO_WORKING_DIRECTORY = "/"
"""The filesystem root: no parent from which npm or a Node version manager could
pick up project files."""

_PROVIDER_KEYS = frozenset({"kind", "server_name", "transport", "command", "arguments"})


def stdio_overlay_entry(
    harness: str,
    provider: Mapping[str, object],
) -> dict[str, object]:
    """Return the owned fields of *harness*'s server entry for *provider*.

    *provider* is a validated catalog ``direct_mcp`` stdio provider. The entry
    keeps the catalog command and argument order and adds
    ``STDIO_WORKING_DIRECTORY``. A literal argument passes through, a secret
    profile reference renders as the profile name, and a secret reference
    renders its template with ``{reference}`` replaced by the variable name,
    so the entry names secrets and never holds one.

    ``command`` is the catalog command token. When the command is installed at
    a fixed path, such as ``secret-exec``, the adapter substitutes that path.
    """

    if harness not in {"codex", "cursor"}:
        raise ValueError(
            f"{harness} stdio overlay entries are unsupported: only Codex and "
            "Cursor entries have a working-directory field"
        )
    if (
        set(provider) != _PROVIDER_KEYS
        or provider.get("kind") != "direct_mcp"
        or provider.get("transport") != "stdio"
    ):
        raise ValueError("stdio overlay entry needs a direct-MCP stdio provider")
    command = provider.get("command")
    arguments = provider.get("arguments")
    if type(command) is not str or not isinstance(arguments, (list, tuple)):
        raise ValueError("stdio overlay entry provider command or arguments are invalid")
    entry: dict[str, object] = {"type": "stdio"} if harness == "cursor" else {}
    entry["command"] = command
    entry["args"] = [_rendered_argument(argument) for argument in arguments]
    entry["cwd"] = STDIO_WORKING_DIRECTORY
    return entry


def _rendered_argument(argument: object) -> str:
    if not isinstance(argument, Mapping):
        raise ValueError("stdio overlay entry argument is invalid")
    keys = set(argument)
    if keys == {"literal"}:
        value = argument.get("literal")
        if type(value) is str:
            return value
    elif keys == {"secret_profile_reference"}:
        value = argument.get("secret_profile_reference")
        if type(value) is str:
            return value
    elif keys == {"secret_reference", "template"}:
        name = argument.get("secret_reference")
        template = argument.get("template")
        if (
            type(name) is str
            and type(template) is str
            and template.count("{reference}") == 1
        ):
            return template.replace("{reference}", name)
    raise ValueError("stdio overlay entry argument is invalid")
