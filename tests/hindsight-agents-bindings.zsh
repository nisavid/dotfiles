#!/usr/bin/env zsh
set -euo pipefail

repo_dir="${0:A:h:h}"
agents_root="${HINDSIGHT_AGENTS_ROOT:-$HOME/src/nisavid/agents}"
tmp_dir="$(mktemp -d)"
trap '/bin/rm -rf -- "$tmp_dir"' EXIT
managed_python_relative="$(
  chezmoi -S "$repo_dir/home" \
    --override-data-file "$repo_dir/home/.chezmoidata/hindsight.toml" \
    execute-template '{{ .hindsight.managedPython }}'
)"
managed_python="$HOME/$managed_python_relative"
[[ -x "$managed_python" ]] || {
  print -ru2 -- "configured Hindsight Python is unavailable: $managed_python"
  exit 1
}

for relative in \
  tooling/hindsight/bin/hindsight-memory \
  tooling/hindsight/bin/hindsight-embed-supervisor \
  tooling/hindsight/bin/hindsight-keychain-resolver \
  tooling/hindsight/lib/hindsight_memory_control_plane/portable_install.py \
  tooling/hindsight/lib/hindsight_memory_control_plane/provider_runtime.py \
  tooling/hindsight/skills/hindsight-memory-import/SKILL.md \
  tooling/hindsight/skills/hindsight-memory-onboarding/SKILL.md \
  tooling/hindsight/skills/hindsight-memory-runtime/SKILL.md; do
  [[ -f "$agents_root/$relative" ]] || {
    print -ru2 -- "missing reusable Hindsight asset: $agents_root/$relative"
    exit 1
  }
done

render() {
  local source="$1" target="$2"
  chezmoi -S "$repo_dir/home" \
    --override-data-file "$repo_dir/home/.chezmoidata/hindsight.toml" \
    execute-template < "$repo_dir/$source" > "$target"
}

render home/private_dot_config/hindsight-control-plane/private_inventory.json.tmpl \
  "$tmp_dir/inventory.json"
render home/private_dot_config/hindsight-control-plane/private_installation.json.tmpl \
  "$tmp_dir/installation.json"
render home/private_dot_config/hindsight-control-plane/private_provider-runtime-policy.json.tmpl \
  "$tmp_dir/provider-runtime-policy.json"
for harness in codex claude-code cursor; do
  render "home/private_dot_config/hindsight-control-plane/private_harnesses/private_${harness}-destination.json.tmpl" \
    "$tmp_dir/${harness}-destination.json"
done
render home/private_dot_local/bin/executable_hindsight-memory.tmpl \
  "$tmp_dir/hindsight-memory"
render home/private_dot_local/bin/executable_hindsight-embed-supervisor.tmpl \
  "$tmp_dir/hindsight-embed-supervisor"
render home/private_dot_local/bin/executable_hindsight-harness-session.tmpl \
  "$tmp_dir/hindsight-harness-session"
for skill in hindsight-memory-import hindsight-memory-onboarding hindsight-memory-runtime; do
  render "home/dot_agents/skills/symlink_${skill}.tmpl" "$tmp_dir/${skill}.link"
done

for skill in hindsight-memory-import hindsight-memory-onboarding hindsight-memory-runtime; do
  [[ "$(<"$tmp_dir/${skill}.link")" == \
    "$HOME/.local/opt/hindsight-control-plane/active/skills/${skill}" ]]
done
grep -F "install_root=\"$HOME/.local/opt/hindsight-control-plane\"" \
  "$tmp_dir/hindsight-memory" >/dev/null
grep -F 'exec "$install_root/bin/hindsight-memory" "$@"' \
  "$tmp_dir/hindsight-memory" >/dev/null
grep -F "install_root=\"$HOME/.local/opt/hindsight-control-plane\"" \
  "$tmp_dir/hindsight-embed-supervisor" >/dev/null
grep -F 'exec "$install_root/bin/hindsight-embed-supervisor" "$@"' \
  "$tmp_dir/hindsight-embed-supervisor" >/dev/null
grep -F 'CONTROLLER = HOME / ".local/opt/hindsight-control-plane" / "bin/hindsight-memory"' \
  "$tmp_dir/hindsight-harness-session" >/dev/null
grep -F 'RESOLVER = HOME / ".local/libexec/hindsight-keychain-resolver"' \
  "$tmp_dir/hindsight-harness-session" >/dev/null
grep -F 'HINDSIGHT_MEMORY_CONTROL_CAPABILITY' \
  "$tmp_dir/hindsight-harness-session" >/dev/null
grep -F 'MINT_LOCATOR = "keychain://io.nisavid.hindsight/mint-authority"' \
  "$tmp_dir/hindsight-harness-session" >/dev/null
if grep -R -F "$agents_root" "$tmp_dir" >/dev/null; then
  print -ru2 -- "mutable agents checkout leaked into rendered bindings"
  exit 1
fi
"$managed_python" -m py_compile "$tmp_dir/hindsight-harness-session"
PYTHONPYCACHEPREFIX="$tmp_dir/pycache" "$managed_python" -m py_compile \
  "$repo_dir/home/private_dot_local/lib/hindsight-runtime/sitecustomize.py"

user_name="$(/usr/bin/id -un)"
/usr/bin/env -i \
  HOME="$HOME" \
  USER="$user_name" \
  LOGNAME="$user_name" \
  PATH=/usr/bin:/bin:/usr/sbin:/sbin \
  "$managed_python" -I - "$tmp_dir/hindsight-harness-session" <<'PY'
import importlib.machinery
import importlib.util
from pathlib import Path
import sys

path = Path(sys.argv[1])
loader = importlib.machinery.SourceFileLoader(
    "hindsight_harness_session",
    str(path),
)
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
for harness, command, expected in (
    ("codex", "codex", Path.home() / ".local/bin/codex"),
    ("claude-code", "claude", Path.home() / ".local/bin/claude"),
    ("cursor", "cursor", Path.home() / ".local/bin/cursor"),
):
    assert module.bind_harness_command(harness, [command, "--version"]) == [
        str(expected),
        "--version",
    ]
try:
    module.bind_harness_command("codex", ["python3"])
except RuntimeError:
    pass
else:
    raise AssertionError("unbound harness executable was accepted")
PY

"$managed_python" -I - "$tmp_dir" "$repo_dir" "$agents_root" <<'PY'
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib

sys.path.insert(0, str(Path(sys.argv[3]) / "tooling/hindsight/lib"))

from hindsight_memory_control_plane.inventory import load_inventory
from hindsight_memory_control_plane.portable_install import InstallationConfig
from hindsight_memory_control_plane.provider_runtime import ProviderRuntimePolicy

root = Path(sys.argv[1])
repo = Path(sys.argv[2])
consumer_data = tomllib.loads(
    (repo / "home/.chezmoidata/hindsight.toml").read_text()
)["hindsight"]
release_commit = consumer_data["releaseCommit"]
release_version = consumer_data["releaseVersion"]
assert subprocess.run(
    ["/usr/bin/git", "-C", str(Path(sys.argv[3])), "rev-parse", "HEAD"],
    check=True,
    stdout=subprocess.PIPE,
    text=True,
).stdout.strip() == release_commit
assert subprocess.run(
    [
        "/usr/bin/git",
        "-C",
        str(Path(sys.argv[3])),
        "status",
        "--porcelain",
        "--",
        "tooling/hindsight",
    ],
    check=True,
    stdout=subprocess.PIPE,
    text=True,
).stdout == ""
assert re.fullmatch(r"\d{4}\.\d{2}\.\d{2}\+[0-9a-f]{7}", release_version)
assert release_version.endswith(f"+{release_commit[:7]}")
inventory = load_inventory(root / "inventory.json")
assert inventory.machine["id"] == "stlz-ivan-mbp"
assert [item["id"] for item in inventory.harnesses] == [
    "codex", "claude-code", "cursor"
]
assert {item["id"] for item in inventory.banks if item["writable"]} == {
    "engineering"
}

policy_data = json.loads((root / "provider-runtime-policy.json").read_text())
policy = ProviderRuntimePolicy.load(policy_data)
assert policy.failover_order == ("personal-codex", "work-codex", "hatchery")
hatchery = policy.member("hatchery")
assert hatchery.max_concurrent == 1
assert hatchery.timeout_seconds == 300
assert hatchery.max_retries == 1
assert hatchery.priority("reflect") < hatchery.priority("retain")
assert hatchery.priority("retain") < hatchery.priority("consolidation")

installation_path = root / "installation.json"
installation = InstallationConfig.read(installation_path)
assert installation.installation_mode == "adopt"
assert installation.platform == "launchd"
assert installation.timers == ()
raw_installation = json.loads(installation_path.read_text())
assert raw_installation["services"][0]["label"] == (
    "io.nisavid.hindsight.stlz-ivan-mbp.stack"
)
assert (
    raw_installation["health_checks"][0]["credentials"]
    == raw_installation["services"][0]["credentials"]
)
assert (
    raw_installation["health_checks"][0]["environment"]
    == raw_installation["services"][0]["environment"]
)
assert raw_installation["credential_resolver"]["path"] == str(
    Path.home() / ".local/libexec/hindsight-keychain-resolver"
)
for surface in [raw_installation["health_checks"][0], raw_installation["services"][0]]:
    environment = surface["environment"]
    assert environment["HINDSIGHT_API_AUDIT_LOG_ENABLED"] == "false"
    assert environment["HINDSIGHT_API_LLM_TRACE_ENABLED"] == "false"
    assert environment["HINDSIGHT_API_WORKER_ID"] == "stlz-ivan-mbp-systalyze"
    assert environment["HINDSIGHT_MEMORY_BROKER_WAIT_SECONDS"] == "300"
    assert environment["HINDSIGHT_API_TENANT_EXTENSION"].endswith(
        ":ApiKeyTenantExtension"
    )

resolver = Path(sys.argv[3]) / "tooling/hindsight/bin/hindsight-keychain-resolver"
assert hashlib.sha256(resolver.read_bytes()).hexdigest() == raw_installation[
    "credential_resolver"
]["sha256"]

for harness in ("codex", "claude-code", "cursor"):
    destination = json.loads((root / f"{harness}-destination.json").read_text())
    assert destination["schema_version"] == 1
    assert destination["harness_id"] == harness
    paths = [
        destination["hooks_path"],
        destination["settings_path"],
        destination["tools_path"],
        destination["rollback_root"],
    ]
    assert len(paths) == len(set(paths))
    assert all(Path(path).is_absolute() for path in paths)

serialized = "\n".join(path.read_text() for path in root.glob("*.json"))
for forbidden in (
    "HINDSIGHT_API_TENANT_API_KEY",
    "HINDSIGHT_CP_ACCESS_KEY",
    "Bearer ",
    "codex-home:/",
):
    assert forbidden not in serialized
PY

for retired in \
  home/private_Library/private_LaunchAgents/com.hindsight.embed.stack.plist.tmpl \
  home/private_dot_hindsight/codex.json.tmpl \
  home/private_dot_hindsight/claude-code.json.tmpl \
  home/private_dot_hindsight/cursor.json.tmpl \
  home/private_dot_local/bin/executable_hindsight-embed-service.tmpl \
  home/private_dot_local/bin/executable_hindsight-embed-single-bank-cleanup.tmpl \
  home/private_dot_local/lib/hindsight-embed-stack.zsh.tmpl \
  home/private_dot_local/lib/hindsight-runtime/hindsight_llm_failover.py \
  home/private_dot_local/libexec/executable_resolve-hindsight-credential; do
  [[ ! -e "$repo_dir/$retired" ]] || {
    print -ru2 -- "mutable-source Hindsight binding remains: $retired"
    exit 1
  }
done

print -r -- "hindsight portable consumer bindings: PASS"
