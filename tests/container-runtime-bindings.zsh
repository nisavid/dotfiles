#!/usr/bin/env zsh
set -euo pipefail

repo_dir="${0:A:h:h}"
modifier="$repo_dir/home/private_dot_docker/modify_private_config.json"
test_dir="$(mktemp -d)"
trap 'rm -rf "$test_dir"' EXIT

mkdir -p \
  "$test_dir/with-orbstack" \
  "$test_dir/without-orbstack" \
  "$test_dir/stale-orbstack" \
  "$test_dir/impostor-orbstack"
print -r -- '#!/usr/bin/env bash
[[ "$*" == "context inspect orbstack --format {{.Endpoints.docker.Host}}" ]] || exit 1
printf "unix://%s/.orbstack/run/docker.sock\n" "$HOME"' \
  >"$test_dir/with-orbstack/docker"
print -r -- '#!/usr/bin/env bash
[[ "$*" == *"--max-time 2 --unix-socket $HOME/.orbstack/run/docker.sock http://localhost/_ping" ]] || exit 1
printf "OK\n"' \
  >"$test_dir/with-orbstack/curl"
print -r -- '#!/usr/bin/env bash
exit 1' \
  >"$test_dir/without-orbstack/docker"
print -r -- '#!/usr/bin/env bash
exit 1' \
  >"$test_dir/without-orbstack/curl"
print -r -- '#!/usr/bin/env bash
if [[ "$*" == "context inspect orbstack --format {{.Endpoints.docker.Host}}" ]]; then
  printf "unix://%s/.orbstack/run/docker.sock\n" "$HOME"
  exit 0
fi
exit 1' \
  >"$test_dir/stale-orbstack/docker"
print -r -- '#!/usr/bin/env bash
exit 28' \
  >"$test_dir/stale-orbstack/curl"
print -r -- '#!/usr/bin/env bash
if [[ "$*" == "context inspect orbstack --format {{.Endpoints.docker.Host}}" ]]; then
  printf "unix:///tmp/not-orbstack.sock\n"
  exit 0
fi
exit 1' \
  >"$test_dir/impostor-orbstack/docker"
print -r -- '#!/usr/bin/env bash
printf "OK\n"' \
  >"$test_dir/impostor-orbstack/curl"
chmod 0700 \
  "$test_dir/with-orbstack/docker" \
  "$test_dir/with-orbstack/curl" \
  "$test_dir/without-orbstack/docker" \
  "$test_dir/without-orbstack/curl" \
  "$test_dir/stale-orbstack/docker" \
  "$test_dir/stale-orbstack/curl" \
  "$test_dir/impostor-orbstack/docker" \
  "$test_dir/impostor-orbstack/curl"

fixture='{"auths":{"registry.example":{"auth":"credential-canary"}},"currentContext":"default","features":{"containerd-snapshotter":true}}'
stale_fixture='{"auths":{"registry.example":{"auth":"credential-canary"}},"currentContext":"orbstack","features":{"containerd-snapshotter":true}}'
rendered="$(
  print -r -- "$fixture" |
    PATH="$test_dir/with-orbstack:$PATH" /bin/bash "$modifier"
)"

print -r -- "$rendered" | jq -e '
  .currentContext == "orbstack" and
  .auths["registry.example"].auth == "credential-canary" and
  .features["containerd-snapshotter"] == true
' >/dev/null

empty_rendered="$(
  PATH="$test_dir/with-orbstack:$PATH" /bin/bash "$modifier" </dev/null
)"
print -r -- "$empty_rendered" | jq -e '
  . == {"currentContext":"orbstack"}
' >/dev/null

unavailable_rendered="$(
  print -r -- "$fixture" |
    PATH="$test_dir/without-orbstack:$PATH" /bin/bash "$modifier"
)"
print -r -- "$unavailable_rendered" | jq -e '
  .currentContext == "default" and
  .auths["registry.example"].auth == "credential-canary" and
  .features["containerd-snapshotter"] == true
' >/dev/null

unavailable_empty="$(
  PATH="$test_dir/without-orbstack:$PATH" /bin/bash "$modifier" </dev/null
)"
print -r -- "$unavailable_empty" | jq -e '. == {}' >/dev/null

for unavailable_context in stale-orbstack impostor-orbstack; do
  unavailable_rendered="$(
    print -r -- "$fixture" |
      PATH="$test_dir/$unavailable_context:$PATH" /bin/bash "$modifier"
  )"
  print -r -- "$unavailable_rendered" | jq -e '
    .currentContext == "default" and
    .auths["registry.example"].auth == "credential-canary" and
    .features["containerd-snapshotter"] == true
  ' >/dev/null
done

for unavailable_context in without-orbstack stale-orbstack impostor-orbstack; do
  stale_rendered="$(
    print -r -- "$stale_fixture" |
      PATH="$test_dir/$unavailable_context:$PATH" /bin/bash "$modifier"
  )"
  print -r -- "$stale_rendered" | jq -e '
    (has("currentContext") | not) and
    .auths["registry.example"].auth == "credential-canary" and
    .features["containerd-snapshotter"] == true
  ' >/dev/null
done

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

managed_path="$(
  PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
  source "$repo_dir/home/dot_config/environment.d/01-podman.conf"
  print -r -- "$PATH"
)"
[[ "$managed_path" == \
  "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/opt/podman/bin" ]]

print -r -- "container runtime bindings: PASS"
