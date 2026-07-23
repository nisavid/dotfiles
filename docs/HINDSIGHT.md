# Hindsight on Ivan's workstation

The reusable control plane lives in
[`nisavid/agents`](https://github.com/nisavid/agents/tree/8c3c9a4835cf73c96cf9bf5c5dd1b0b024023031/tooling/hindsight).
This repository contains only Ivan's machine inventory, protected credential
locators, provider selection, native harness destinations, and installed-release
bindings.

The target path is:

```text
harness -> controller hook -> session bridge -> capability broker
        -> authenticated Hindsight API -> engineering
```

`engineering` is the only automatic write bank. Existing noncanonical banks,
profiles, and stores are not installation inputs and remain untouched until the
separate migration gates in `nisavid/agents` issues #11, #21, and #23 are
satisfied.

## Owned configuration

| Surface | Source | Installed target |
| --- | --- | --- |
| Machine inventory | `home/private_dot_config/hindsight-control-plane/private_inventory.json.tmpl` | `~/.config/hindsight-control-plane/inventory.json` |
| Portable lifecycle | `home/private_dot_config/hindsight-control-plane/private_installation.json.tmpl` | `~/.config/hindsight-control-plane/installation.json` |
| Provider policy | `home/private_dot_config/hindsight-control-plane/private_provider-runtime-policy.json.tmpl` | `~/.config/hindsight-control-plane/provider-runtime-policy.json` |
| Harness destinations | `home/private_dot_config/hindsight-control-plane/private_harnesses/` | `~/.config/hindsight-control-plane/harnesses/` |
| Keychain resolver binding | `home/.chezmoidata/hindsight.toml` | `~/.local/libexec/hindsight-keychain-resolver` |
| Provider bootstrap | `home/private_dot_local/lib/hindsight-runtime/sitecustomize.py` | `~/.local/lib/hindsight-runtime/sitecustomize.py` |

The pinned reusable release is recorded in
`home/.chezmoidata/hindsight.toml`. The installer copies that release into an
immutable, content-addressed directory under
`~/.local/opt/hindsight-control-plane`; running services and shell bindings do
not execute a mutable source checkout.

The three controller credentials live as generic passwords in the macOS login
Keychain. Configuration contains only these opaque locators:

- `keychain://io.nisavid.hindsight/data-plane`
- `keychain://io.nisavid.hindsight/mint-authority`
- `keychain://io.nisavid.hindsight/ui-access-key`

The native resolver lives in
[`nisavid/agents`](https://github.com/nisavid/agents/tree/8c3c9a4835cf73c96cf9bf5c5dd1b0b024023031/tooling/hindsight/native/macos-keychain-resolver).
Its exact-executable Keychain ACL prevents unintended same-user programs from
reading the items directly. Deliberate invocation of the exact approved
resolver remains possible; this is an executable-capability boundary, not a
signed client-identity boundary.

The resolver never puts values in files, command arguments, logs, shell startup
state, or browser storage. `hindsight-harness-session` resolves the mint
authority only into the controller launcher's environment; the launcher removes
it before starting a harness and gives the harness only a private bridge
locator.

## Adoption preflight

Perform adoption from a fresh operator shell after all Codex, Claude Code, and
Cursor sessions are closed. Do not run it from a harness session that is being
migrated.

1. Check out the exact `hindsight.releaseCommit` from
   `home/.chezmoidata/hindsight.toml` in a clean `nisavid/agents` worktree.
2. Confirm the Hindsight operation set is idle and snapshot the current
   LaunchAgent, hook files, upstream integration settings, provider profile,
   authentication state, and service status.
3. Render and inspect the consumer files:

   ```zsh
   chezmoi cat ~/.config/hindsight-control-plane/inventory.json | jq .
   chezmoi cat ~/.config/hindsight-control-plane/installation.json | jq .
   chezmoi cat ~/.config/hindsight-control-plane/provider-runtime-policy.json | jq .
   ```

4. Install the native resolver from the verified reusable release by following
   the protected immutable-install block in the reusable
   [`adoption.md`](https://github.com/nisavid/agents/blob/8c3c9a4835cf73c96cf9bf5c5dd1b0b024023031/tooling/hindsight/docs/adoption.md).
   Require its printed digest to equal the configured
   `credential_resolver.sha256`. Then apply only the consumer configuration,
   provider bootstrap, and Cursor's empty upstream settings document. Do not
   replace the live service wrapper or LaunchAgent yet.

   ```zsh
   (
     emulate -L zsh
     setopt ERR_EXIT NO_UNSET PIPE_FAIL
     guard_file="$(/usr/bin/mktemp)"
     trap '/bin/rm -f -- "$guard_file"' EXIT
     /usr/bin/shasum -a 256 \
       ~/.local/bin/hindsight-memory \
       ~/.local/bin/hindsight-embed-supervisor \
       ~/Library/LaunchAgents/com.hindsight.embed.stack.plist >"$guard_file"
     chezmoi apply -- \
       ~/.config/hindsight-control-plane \
       ~/.local/lib/hindsight-runtime/sitecustomize.py \
       ~/.hindsight/cursor-upstream-settings.json
     /usr/bin/shasum -a 256 -c "$guard_file"
   )
   ```

5. Initialize the three internal controller credentials without printing them:

   ```zsh
   ~/.local/libexec/hindsight-keychain-resolver --initialize
   ~/.local/libexec/hindsight-keychain-resolver --status
   ```

6. Create the private runtime directories with mode `0700`:

   ```zsh
   install -d -m 700 \
     ~/.local/state/hindsight-control-plane/memory \
     ~/.local/state/hindsight-control-plane/memory/bridge-locators \
     ~/.local/state/hindsight-control-plane/memory/bridges \
     ~/.local/state/hindsight-control-plane/harness-rollbacks \
     ~/.local/state/hindsight-control-plane/harness-tools
   ```

7. Validate the inventory with the pinned candidate CLI and validate the
   provider policy through `ProviderRuntimePolicy.load`. The repository test
   `tests/hindsight-agents-bindings.zsh` performs both checks without mutating
   the live service.

   Run this read-only identity check. It prints only the four non-secret values
   and exits nonzero on any mismatch:

   ```zsh
   ~/.local/share/uv/python/cpython-3.13.14-macos-aarch64-none/bin/python3.13 -I - <<'PY'
   import json
   from pathlib import Path

   home = Path.home()
   profile = (home / ".hindsight/active_profile").read_text().strip()
   values = {}
   counts = {"HINDSIGHT_API_PORT": 0, "HINDSIGHT_BANK_ID": 0}
   for line in (home / ".hindsight/profiles/systalyze.env").read_text().splitlines():
       if "=" in line and not line.lstrip().startswith("#"):
           key, value = line.split("=", 1)
           key = key.strip()
           if key in counts:
               counts[key] += 1
           values[key] = value.strip()
   if any(count != 1 for count in counts.values()):
       raise SystemExit("live Hindsight identity contains missing or duplicate keys")
   installation = json.loads(
       (home / ".config/hindsight-control-plane/installation.json").read_text()
   )
   observed = {
       "profile": profile,
       "api_port": values.get("HINDSIGHT_API_PORT"),
       "data_root": installation.get("data_root"),
       "bank": values.get("HINDSIGHT_BANK_ID"),
   }
   expected = {
       "profile": "systalyze",
       "api_port": "7979",
       "data_root": str(home / ".pg0/instances/hindsight-embed-systalyze"),
       "bank": "engineering",
   }
   data_root = Path(expected["data_root"])
   if observed != expected or not data_root.is_dir() or data_root.is_symlink():
       raise SystemExit("live Hindsight identity does not match the adoption contract")
   print(json.dumps(observed, sort_keys=True))
   PY
   ```

Any mismatch is a migration decision and stops adoption.

## Profile preparation

The provider adapter preserves this exact order and policy:

1. personal Codex OAuth home;
2. work Codex OAuth home;
3. Hatchery;
4. Hatchery concurrency one, 300-second timeout, one transient retry;
5. reflect and interactive calls ahead of retain and consolidation;
6. quota-aware cooldown for both Codex members.

After the no-active-session gate, use the pinned release's
`bin/hindsight-embed-uvx` wrapper to persist these non-secret profile values:

```zsh
/bin/chmod 700 \
  ~/.hindsight/codex-nisavid \
  ~/.hindsight/codex-systalyze

prepare_hindsight_profile() (
emulate -L zsh
setopt ERR_EXIT NO_UNSET PIPE_FAIL

agents_checkout="${HINDSIGHT_AGENTS_CHECKOUT:?set to the clean agents checkout}"
dotfiles_checkout="${
  HINDSIGHT_DOTFILES_CHECKOUT:?set to this dotfiles branch checkout
}"
repository_root="${agents_checkout:A}"
consumer_root="${dotfiles_checkout:A}"
release_root="$repository_root/tooling/hindsight"
data_file="$consumer_root/home/.chezmoidata/hindsight.toml"
read_consumer_value() {
  local key="$1" line value=
  local count=0
  while IFS= read -r line; do
    if [[ "$line" =~ \
      "^${key}[[:space:]]*=[[:space:]]*\"([^\"]+)\"[[:space:]]*$" ]]; then
      value="$match[1]"
      (( count += 1 ))
    fi
  done <"$data_file"
  [[ "$count" == 1 ]] || return 1
  print -r -- "$value"
}
expected_commit="$(read_consumer_value releaseCommit)"
[[ -r "$data_file" && -d "$release_root" &&
   "$(/usr/bin/git -C "$repository_root" rev-parse HEAD)" == "$expected_commit" &&
   -z "$(/usr/bin/git -C "$repository_root" status --porcelain)" ]] || return 1
embed="$release_root/bin/hindsight-embed-uvx"
profile=systalyze
export HINDSIGHT_EMBED_UVX_EXECUTABLE=~/.local/bin/uvx

set_profile_env() {
  "$embed" hindsight-embed profile set-env "$profile" "$1" "$2"
}
set_profile_env HINDSIGHT_API_AUDIT_LOG_ENABLED false
set_profile_env HINDSIGHT_API_LLM_TRACE_ENABLED false
set_profile_env HINDSIGHT_API_WORKER_ID stlz-ivan-mbp-systalyze
set_profile_env HINDSIGHT_API_LLM_PROVIDER openai-codex
set_profile_env HINDSIGHT_API_LLM_MODEL gpt-5.3-codex-spark
set_profile_env HINDSIGHT_API_LLM_API_KEY provider-policy:personal-codex
set_profile_env HINDSIGHT_API_LLM_1_PROVIDER openai-codex
set_profile_env HINDSIGHT_API_LLM_1_MODEL gpt-5.3-codex-spark
set_profile_env HINDSIGHT_API_LLM_1_API_KEY provider-policy:work-codex
set_profile_env HINDSIGHT_API_LLM_2_PROVIDER lmstudio
set_profile_env HINDSIGHT_API_LLM_2_MODEL Qwen3.6-35B-A3B-MTP-GGUF-UD-Q4_K_XL
set_profile_env HINDSIGHT_API_LLM_2_BASE_URL \
  http://hatchery.komodo-vector.ts.net:13305/v1
set_profile_env HINDSIGHT_API_LLM_STRATEGY '{"mode":"failover"}'
unfunction set_profile_env
unfunction read_consumer_value
)
prepare_hindsight_profile
profile_status=$?
unfunction prepare_hindsight_profile
(( profile_status == 0 )) || return "$profile_status" 2>/dev/null || exit "$profile_status"
```

Before cutover, parse `~/.hindsight/profiles/systalyze.env` without sourcing it
and verify that every key above has exactly the expected value:

```zsh
~/.local/share/uv/python/cpython-3.13.14-macos-aarch64-none/bin/python3.13 -I - <<'PY'
from pathlib import Path

expected = {
    "HINDSIGHT_API_AUDIT_LOG_ENABLED": "false",
    "HINDSIGHT_API_LLM_TRACE_ENABLED": "false",
    "HINDSIGHT_API_WORKER_ID": "stlz-ivan-mbp-systalyze",
    "HINDSIGHT_API_LLM_PROVIDER": "openai-codex",
    "HINDSIGHT_API_LLM_MODEL": "gpt-5.3-codex-spark",
    "HINDSIGHT_API_LLM_API_KEY": "provider-policy:personal-codex",
    "HINDSIGHT_API_LLM_1_PROVIDER": "openai-codex",
    "HINDSIGHT_API_LLM_1_MODEL": "gpt-5.3-codex-spark",
    "HINDSIGHT_API_LLM_1_API_KEY": "provider-policy:work-codex",
    "HINDSIGHT_API_LLM_2_PROVIDER": "lmstudio",
    "HINDSIGHT_API_LLM_2_MODEL": "Qwen3.6-35B-A3B-MTP-GGUF-UD-Q4_K_XL",
    "HINDSIGHT_API_LLM_2_BASE_URL": "http://hatchery.komodo-vector.ts.net:13305/v1",
    "HINDSIGHT_API_LLM_STRATEGY": '{"mode":"failover"}',
}
observed = {}
for line in (Path.home() / ".hindsight/profiles/systalyze.env").read_text().splitlines():
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    if key in expected:
        if key in observed:
            raise SystemExit(f"profile persistence contains duplicate {key}")
        observed[key] = value
if observed != expected:
    raise SystemExit("profile persistence does not match the approved provider plan")
PY
```

Do not print the profile file: it also contains existing provider material. Do
not restart the legacy service here. The portable cutover below owns the single
managed restart after authentication, privacy, worker, provider, and service
bindings are coherent.

These markers are not credentials. The version-gated provider bootstrap
resolves them to protected OAuth-home paths only inside the Hindsight process.

## Managed cutover

The preflight snapshot must include three protected executable commands:

- `stop_legacy` stops and unloads `com.hindsight.embed.stack`, then proves it is
  stopped;
- `rollback_preflight` supports `--verify-only` and
  `--restore-and-reload`;
- `activation_acceptance` verifies manifest parity, broker, control, API, UI,
  fleet, all three active harness routes, capability lifecycle, and the
  expected inventory, route, policy, artifact, and profile-set digests.

Set each variable to its absolute command path, set
`HINDSIGHT_AGENTS_CHECKOUT` to the clean pinned checkout, and run the transition
as one fail-fast command:

```zsh
: "${HINDSIGHT_AGENTS_CHECKOUT:?set to the clean agents checkout}"
: "${HINDSIGHT_DOTFILES_CHECKOUT:?set to this dotfiles branch checkout}"
: "${stop_legacy:?set to the protected stop command}"
: "${rollback_preflight:?set to the protected rollback command}"
: "${activation_acceptance:?set to the protected acceptance command}"
export HINDSIGHT_AGENTS_CHECKOUT stop_legacy rollback_preflight activation_acceptance
cutover_script="${
  HINDSIGHT_DOTFILES_CHECKOUT:A
}/scripts/hindsight-control-plane-cutover.zsh"
[[ -f "$cutover_script" ]]
/bin/zsh "$cutover_script"
```

Only after this command succeeds, apply the immutable-release shell and skill
bindings and archive the old LaunchAgent outside `~/Library/LaunchAgents`.
Retain the rollback snapshot through the acceptance window.

The portable installer injects the data-plane token only into the Hindsight API,
broker adapter, and UI's server-side data-plane proxy. It enables
`ApiKeyTenantExtension` against the existing database and performs no bank or
schema migration.

## Harness activation

For each destination under
`~/.config/hindsight-control-plane/harnesses`, run the reusable
`harness-config stage`, `plan`, `apply`, and `status` sequence documented in
the installed release's `docs/adoption.md`. The matching public source is
[`tooling/hindsight/docs/adoption.md`](https://github.com/nisavid/agents/blob/8c3c9a4835cf73c96cf9bf5c5dd1b0b024023031/tooling/hindsight/docs/adoption.md).
Review and approve each destination-bound digest separately.

Activation preserves unrelated hooks and plugin settings while it:

- installs controller-owned recall, checkpoint, compaction, close, and explicit
  tool hooks;
- removes direct endpoint, bank, and credential authority from upstream
  Hindsight settings;
- disables upstream auto-recall and auto-retain;
- disables Claude's knowledge tools through its verified empty-MCP-server mode;
- leaves Cursor inactive until its controller path passes a fresh smoke session.

Start CLI sessions through `hindsight-harness-session`. Before a GUI launch,
stage a one-use envelope for the exact native session ID:

```zsh
hindsight-harness-session codex launch -- codex
hindsight-harness-session claude-code launch -- claude
hindsight-harness-session cursor stage-gui --session-id SESSION_ID
```

Run fresh Codex, Claude Code, and Cursor smoke sessions. Verify bounded recall,
full-epoch replacement checkpoints, pre-compaction checkpoints, clean outcome
retention, reflect, read-only mental models, normal close, capability expiry and
revocation, durable watermarks, and writes to `engineering` only.

## Rollback

Rollback preserves data and follows this order:

1. stop new harness sessions and drain broker writes;
2. run each approved `harness-config rollback` and verify the restored native
   files;
3. uninstall the portable generation without deleting its data root;
4. restore the complete pre-adoption snapshot: consumer configuration,
   Keychain resolver binding, provider bootstrap, shell and skill bindings,
   provider profile, authentication and privacy flags, native hook and upstream
   integration settings, and the original LaunchAgent;
5. verify the restored snapshot digests, then start the original service once;
6. verify the temporary direct bindings, provider chain, API, UI, control, and
   fleet;
7. retain the failed generation and evidence for diagnosis.

## Integration and data migration boundaries

The reusable integration upgrader is installed, but no timer is configured
until upstream publishes a real same-origin manifest and a broker-compatible
transport artifact with a verifier identity. Synthetic example catalogs are
never used on this machine. Direct-only upstream releases may be staged after a
real catalog exists, but they receive no memory authority.

Container-based acceptance and future airlocks use OrbStack. Podman is not a
runtime dependency for Hindsight. Existing Podman workloads remain running only
until they are migrated without interruption; no new Hindsight or general
container work targets Podman. The broader workload-by-workload retirement
contract is in
`docs/PODMAN_TO_ORBSTACK_MIGRATION_PRD.md`.

“Task 7 Step 5” is only the read-only discovery gate. No command in this guide
authorizes copying, merging, renaming, or deleting a bank, profile, document,
fact, observation, or legacy store.
