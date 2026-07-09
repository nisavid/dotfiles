#!/usr/bin/env zsh
set -euo pipefail

repo_dir="${0:A:h:h}"
tmp_dir="$(mktemp -d)"
trap 'rm -rf -- "$tmp_dir"' EXIT

rendered_stack_lib="$tmp_dir/hindsight-embed-stack.zsh"
(
  cd "$repo_dir"
  chezmoi execute-template < home/private_dot_local/lib/hindsight-embed-stack.zsh.tmpl > "$rendered_stack_lib"
)

service_lib="$tmp_dir/hindsight-embed-service.zsh"
/usr/bin/sed '/^main "\$@"$/d' \
  "$repo_dir/home/private_dot_local/bin/executable_hindsight-embed-service" > "$service_lib"

test_home="$tmp_dir/home"
mkdir -p "$test_home/.hindsight/profiles"

(
  export HOME="$test_home"
  export HINDSIGHT_EMBED_PROFILE="missing-profile"
  source "$rendered_stack_lib"
  if hindsight_stack_profile_exists; then
    print -ru2 -- "missing profile unexpectedly exists"
    exit 1
  fi
)

touch "$test_home/.hindsight/profiles/present-profile.env"
(
  export HOME="$test_home"
  export HINDSIGHT_EMBED_PROFILE="present-profile"
  source "$rendered_stack_lib"
  hindsight_stack_profile_exists
)

rg -F -q 'uvx hindsight-embed configure --profile "$profile" --port "$api_port"' "$repo_dir/docs/HINDSIGHT.md" || {
  print -ru2 -- "setup guide must use interactive configure"
  exit 1
}

if rg -A1 '^uvx hindsight-embed configure' "$repo_dir/docs/HINDSIGHT.md" | rg -q -- '--env'; then
  print -ru2 -- "interactive configure must not receive --env"
  exit 1
fi

rg -F -q 'hindsight-embed profile set-env "$profile" HINDSIGHT_BANK_ID "$bank_id"' "$repo_dir/docs/HINDSIGHT.md" || {
  print -ru2 -- "setup guide must set the bank after interactive configuration"
  exit 1
}

if rg -n 'systalyze|engineering' "$repo_dir/docs/HINDSIGHT.md" >/dev/null; then
  print -ru2 -- "setup guide must use generic profile and bank placeholders"
  exit 1
fi

rg -F -q '[Hindsight local stack](docs/HINDSIGHT.md)' "$repo_dir/README.md" || {
  print -ru2 -- "README must link to the Hindsight setup guide"
  exit 1
}

status_output="$tmp_dir/status.out"
if HOME="$test_home" \
  HINDSIGHT_EMBED_STACK_LIB="$rendered_stack_lib" \
  HINDSIGHT_EMBED_PROFILE="missing-profile" \
  zsh "$repo_dir/home/private_dot_local/bin/executable_hindsight-embed-service" status \
  >"$status_output" 2>&1; then
  print -ru2 -- "status unexpectedly succeeded for a missing profile"
  exit 1
fi

rg -F -q 'configured profile: missing (missing-profile)' "$status_output" || {
  print -ru2 -- "status did not report the missing profile"
  exit 1
}

mkdir -p "$test_home/Library/LaunchAgents" "$test_home/.local/bin"
(
  cd "$repo_dir"
  chezmoi execute-template < home/Library/LaunchAgents/com.hindsight.embed.stack.plist.tmpl \
    > "$test_home/Library/LaunchAgents/com.hindsight.embed.stack.plist"
)
touch "$test_home/.local/bin/hindsight-embed-supervisor"
chmod 700 "$test_home/.local/bin/hindsight-embed-supervisor"
runtime_helper="$tmp_dir/hindsight-embed-stop-profile-services.py"
touch "$runtime_helper"

assert_missing_profile_blocks_mutation() {
  local command="$1"
  local mutation_marker="$tmp_dir/${command}.mutated"
  local output="$tmp_dir/${command}.out"

  if (
    export HOME="$test_home"
    export HINDSIGHT_EMBED_STACK_LIB="$rendered_stack_lib"
    export HINDSIGHT_EMBED_PROFILE="missing-profile"
    export HINDSIGHT_EMBED_UVX="/usr/bin/true"
    export HINDSIGHT_EMBED_PYTHON="/usr/bin/true"
    export HINDSIGHT_EMBED_STOP_HELPER="$runtime_helper"

    source "$service_lib"
    load_stack_lib

    bootout_if_loaded() {
      touch "$mutation_marker"
    }
    load_launchd_service() {
      touch "$mutation_marker"
    }

    case "$command" in
      start)
        start_launchd_service
        ;;
      install)
        install_service
        ;;
    esac
  ) >"$output" 2>&1; then
    print -ru2 -- "${command} unexpectedly succeeded for a missing profile"
    return 1
  fi

  if [[ -e "$mutation_marker" ]]; then
    print -ru2 -- "${command} reached a launchd mutation for a missing profile"
    return 1
  fi

  rg -F -q "configured profile 'missing-profile' does not exist" "$output" || {
    print -ru2 -- "${command} did not report the missing profile preflight"
    return 1
  }
}

assert_missing_profile_blocks_mutation start
assert_missing_profile_blocks_mutation install
