#!/bin/zsh
setopt ERR_EXIT NO_UNSET PIPE_FAIL

: "${HINDSIGHT_AGENTS_CHECKOUT:?set to the clean agents checkout}"
: "${stop_legacy:?set to the protected stop command}"
: "${rollback_preflight:?set to the protected rollback command}"
: "${activation_acceptance:?set to the protected acceptance command}"

user_id="$(/usr/bin/id -u)"
protected_command_binding() {
  local executable="$1" owner mode links ancestor acl_entry digest device_inode
  local -a acl_listing
  [[ "$executable" == /* && -f "$executable" && ! -L "$executable" ]] ||
    return 1
  [[ -x "$executable" ]] || return 1
  owner="$(/usr/bin/stat -f '%u' "$executable")" || return 1
  [[ "$owner" == "$user_id" || "$owner" == 0 ]] || return 1
  mode="$(/usr/bin/stat -f '%Lp' "$executable")" || return 1
  (( (8#$mode & 8#022) == 0 )) || return 1
  links="$(/usr/bin/stat -f '%l' "$executable")" || return 1
  [[ "$links" == 1 ]] || return 1
  acl_listing=("${(@f)$(/bin/ls -lde "$executable")}") || return 1
  for acl_entry in "${acl_listing[@]}"; do
    [[ ! "$acl_entry" =~ \
      '^[[:space:]]*[0-9]+:.*[[:space:]]allow[[:space:]]' ]] || return 1
  done

  ancestor="${executable:h}"
  while true; do
    [[ -d "$ancestor" && ! -L "$ancestor" ]] || return 1
    owner="$(/usr/bin/stat -f '%u' "$ancestor")" || return 1
    [[ "$owner" == "$user_id" || "$owner" == 0 ]] || return 1
    mode="$(/usr/bin/stat -f '%Lp' "$ancestor")" || return 1
    (( (8#$mode & 8#022) == 0 )) || return 1
    acl_listing=("${(@f)$(/bin/ls -lde "$ancestor")}") || return 1
    for acl_entry in "${acl_listing[@]}"; do
      [[ ! "$acl_entry" =~ \
        '^[[:space:]]*[0-9]+:.*[[:space:]]allow[[:space:]]' ]] || return 1
    done
    [[ "$ancestor" == / ]] && break
    ancestor="${ancestor:h}"
  done

  read -r digest _ < <(/usr/bin/shasum -a 256 "$executable") || return 1
  device_inode="$(/usr/bin/stat -f '%d:%i' "$executable")" || return 1
  print -r -- "$device_inode:$digest"
}

run_bound_command() {
  local executable="$1" binding="$2" observed
  shift 2
  observed="$(protected_command_binding "$executable")" || return 1
  [[ "$observed" == "$binding" ]] || return 1
  "$executable" "$@"
}

stop_binding="$(protected_command_binding "$stop_legacy")"
rollback_binding="$(protected_command_binding "$rollback_preflight")"
acceptance_binding="$(protected_command_binding "$activation_acceptance")"

script_dir="${0:A:h}"
repo_dir="${script_dir:h}"
source_root="$repo_dir/home"
data_file="$source_root/.chezmoidata/hindsight.toml"
repository_root="${HINDSIGHT_AGENTS_CHECKOUT:A}"
release_root="$repository_root/tooling/hindsight"
managed_python="$HOME/.local/share/uv/python/cpython-3.13.14-macos-aarch64-none/bin/python3.13"
installation_config="$HOME/.config/hindsight-control-plane/installation.json"
read_hindsight_value() {
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
expected_commit="$(read_hindsight_value releaseCommit)"
expected_version="$(read_hindsight_value releaseVersion)"
candidate="$release_root/bin/hindsight-memory"
[[ -r "$data_file" && -d "$release_root" ]]
[[ -x "$managed_python" && -f "$candidate" && -r "$installation_config" ]]
[[ "$(/usr/bin/git -C "$repository_root" rev-parse HEAD)" == "$expected_commit" ]]
[[ -z "$(/usr/bin/git -C "$repository_root" status --porcelain)" ]]
[[ "$expected_version" =~ '^[0-9]{4}[.][0-9]{2}[.][0-9]{2}[+][0-9a-f]{7}$' ]]
[[ "${expected_version##*+}" == "${expected_commit[1,7]}" ]]

run_bound_command "$rollback_preflight" "$rollback_binding" --verify-only

rollback_required=true
rollback_once() {
  local rc=$?
  trap - EXIT INT TERM HUP
  if [[ "$rollback_required" == true ]]; then
    rollback_required=false
    run_bound_command \
      "$rollback_preflight" \
      "$rollback_binding" \
      --restore-and-reload || rc=$?
  fi
  exit "$rc"
}
trap rollback_once EXIT
trap 'exit 130' INT TERM HUP

run_bound_command "$stop_legacy" "$stop_binding" || exit $?
"$managed_python" "$candidate" install \
  --config "$installation_config" \
  --release-root "$release_root" \
  --version "$expected_version"

installed="$HOME/.local/opt/hindsight-control-plane/bin/hindsight-memory"
"$installed" verify --config "$installation_config"
run_bound_command "$activation_acceptance" "$acceptance_binding" || exit $?

rollback_required=false
trap - EXIT INT TERM HUP
