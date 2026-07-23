#!/usr/bin/env zsh
set -euo pipefail

repo_dir="${0:A:h:h}"
modifier="$repo_dir/home/private_dot_docker/modify_private_config.json"

fixture='{"auths":{"registry.example":{"auth":"credential-canary"}},"currentContext":"default","features":{"containerd-snapshotter":true}}'
rendered="$(print -r -- "$fixture" | /bin/bash "$modifier")"

print -r -- "$rendered" | jq -e '
  .currentContext == "orbstack" and
  .auths["registry.example"].auth == "credential-canary" and
  .features["containerd-snapshotter"] == true
' >/dev/null

empty_rendered="$(/bin/bash "$modifier" </dev/null)"
print -r -- "$empty_rendered" | jq -e '
  . == {"currentContext":"orbstack"}
' >/dev/null
if print -r -- null | /bin/bash "$modifier" >/dev/null 2>&1; then
  print -ru2 -- "non-object Docker configuration was accepted"
  exit 1
fi
if print -r -- $'{}\n{}' | /bin/bash "$modifier" >/dev/null 2>&1; then
  print -ru2 -- "multiple Docker configuration values were accepted"
  exit 1
fi

grep -F 'Legacy Podman command paths' \
  "$repo_dir/home/dot_config/environment.d/01-podman.conf" >/dev/null

print -r -- "container runtime bindings: PASS"
