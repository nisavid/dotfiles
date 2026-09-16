#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
launcher_source=$repo_root/home/private_dot_local/bin/executable_secret-exec
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/github-identity-binding.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT

fixture_home=$test_dir/home
profile_dir=$fixture_home/.config/secret-exec/profiles
bin_dir=$test_dir/bin
mkdir -p -- "$profile_dir" "$bin_dir" "$fixture_home/.local/bin"
chmod 700 "$fixture_home/.config" "$fixture_home/.config/secret-exec" "$profile_dir"

launcher=$fixture_home/.local/bin/secret-exec
cp -- "$launcher_source" "$launcher"
chmod 700 "$launcher"
cat > "$fixture_home/.local/bin/proton-pass-ensure-ready" <<'EOF'
#!/bin/zsh -f
exit 0
EOF
cat > "$bin_dir/pass-cli" <<'EOF'
#!/bin/zsh -f
print -r -- fixture-token
EOF
cat > "$bin_dir/gh" <<'EOF'
#!/bin/zsh -f
[[ $GH_TOKEN == fixture-token ]] || exit 71
[[ $* == 'api --hostname github.com user --jq .login' ]] || exit 73
print -r -- "${FAKE_GITHUB_LOGIN:-fixture-personal}"
EOF
cat > "$bin_dir/target" <<'EOF'
#!/bin/zsh -f
[[ $GITHUB_PERSONAL_ACCESS_TOKEN == fixture-token ]] || exit 72
print -r -- target-ran
EOF
chmod 700 "$fixture_home/.local/bin/proton-pass-ensure-ready" \
  "$bin_dir/pass-cli" "$bin_dir/gh" "$bin_dir/target"
cat > "$profile_dir/github.env" <<'EOF'
# secret-exec-github-profile=github-fixture-personal
# secret-exec-github-login=fixture-personal
GITHUB_PERSONAL_ACCESS_TOKEN=pass://fixture-vault/item/password
EOF
chmod 600 "$profile_dir/github.env"

run_launcher() {
  HOME=$fixture_home \
  XDG_CONFIG_HOME=$fixture_home/.config \
  XDG_STATE_HOME=$test_dir/state \
  PATH=$bin_dir:/usr/bin:/bin \
  GH_HOST=enterprise.invalid \
  FAKE_GITHUB_LOGIN=${1:-fixture-personal} \
  "$launcher" github -- target
}

[[ $(run_launcher) == target-ran ]] ||
  { print -u2 -r -- 'matching GitHub identity must start the consumer'; exit 1; }

set +e
wrong_output=$(run_launcher fixture-other 2>&1)
wrong_status=$?
set -e
(( wrong_status != 0 )) ||
  { print -u2 -r -- 'mismatched GitHub identity must fail closed'; exit 1; }
[[ $wrong_output == *'GitHub identity self-check failed'* ]] ||
  { print -u2 -r -- 'mismatched GitHub identity must report a redacted failure'; exit 1; }
[[ $wrong_output != *target-ran* ]] ||
  { print -u2 -r -- 'mismatched GitHub identity must not start the consumer'; exit 1; }

mv -- "$bin_dir/gh" "$bin_dir/gh-real"
ln -s -- "$bin_dir/gh-real" "$bin_dir/gh"
set +e
untrusted_output=$(run_launcher 2>&1)
untrusted_status=$?
set -e
(( untrusted_status != 0 )) && [[ $untrusted_output != *target-ran* ]] ||
  { print -u2 -r -- 'an untrusted GitHub checker must not start the consumer'; exit 1; }

print -r -- 'github identity binding checks passed'
