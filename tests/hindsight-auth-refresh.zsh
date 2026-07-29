#!/usr/bin/env zsh
set -euo pipefail

repo_dir="${0:A:h:h}"
fixture="$repo_dir/tests/fixtures/hindsight-public.toml"
tmp_dir="$(mktemp -d)"
trap '/bin/rm -rf -- "$tmp_dir"' EXIT

fixture_value() {
  local key=$1
  chezmoi -S "$repo_dir/home" \
    --override-data-file "$fixture" \
    execute-template \
    "{{ index .hindsight \"$key\" }}"
}

test_home="$tmp_dir/home"
codex="$test_home/$(fixture_value codexExecutable)"
codex_home="$test_home/$(fixture_value authRefreshCodexHome)"
controller="$test_home/$(fixture_value installRoot)/bin/hindsight-memory"
wrapper="$tmp_dir/hindsight-embed-service"
calls="$tmp_dir/calls"

mkdir -p "${codex:h}" "$codex_home" "${controller:h}"
chmod 700 "$test_home" "$codex_home"

cat >"$codex" <<'ZSH'
#!/usr/bin/env zsh
set -euo pipefail
print -r -- "codex:${CODEX_HOME}:$*" >>"$HINDSIGHT_TEST_CALLS"
[[ "${HINDSIGHT_TEST_LOGIN_FAIL:-0}" == 0 ]]
ZSH
cat >"$controller" <<'ZSH'
#!/usr/bin/env zsh
set -euo pipefail
print -r -- "controller:$*" >>"$HINDSIGHT_TEST_CALLS"
ZSH
chmod 700 "$codex" "$controller"

HOME="$test_home" \
  chezmoi -S "$repo_dir/home" \
    --override-data-file "$fixture" \
    execute-template \
    <"$repo_dir/home/private_dot_local/bin/executable_hindsight-embed-service.tmpl" \
    >"$wrapper"
chmod 700 "$wrapper"

HINDSIGHT_TEST_CALLS="$calls" "$wrapper" auth-refresh
expected_home="$codex_home"
grep -Fx "codex:${expected_home}:login" "$calls" >/dev/null
grep -Fx "codex:${expected_home}:login status" "$calls" >/dev/null
grep -Fx \
  "controller:service restart --config $test_home/$(fixture_value installationPath)" \
  "$calls" >/dev/null

: >"$calls"
if HINDSIGHT_TEST_CALLS="$calls" HINDSIGHT_TEST_LOGIN_FAIL=1 \
  "$wrapper" auth-refresh >/dev/null 2>&1; then
  print -ru2 -- "auth refresh unexpectedly accepted a failed login"
  exit 1
fi
if grep -F 'controller:' "$calls" >/dev/null; then
  print -ru2 -- "auth refresh restarted the service after a failed login"
  exit 1
fi

chmod 750 "$codex_home"
if HINDSIGHT_TEST_CALLS="$calls" "$wrapper" auth-refresh >/dev/null 2>&1; then
  print -ru2 -- "auth refresh accepted an unsafe credential directory"
  exit 1
fi

print -r -- "hindsight auth refresh: PASS"
