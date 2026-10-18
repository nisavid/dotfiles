#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
launcher_source=$repo_root/home/private_dot_local/bin/executable_secret-exec
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/github-identity-binding.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT
unset SECRET_EXEC_INJECTED_PROFILES GITHUB_PERSONAL_ACCESS_TOKEN GH_TOKEN
export FAKE_CALLS_LOG=$test_dir/calls.log
export FAKE_GH_CONFIG_LOG=$test_dir/gh-config.log
# A caller-controlled gh configuration that would reroute the check's request.
caller_gh_config=$test_dir/caller-gh-config
launch_tmpdir=$test_dir/tmp
mkdir -p -- "$caller_gh_config" "$launch_tmpdir"
# Reach TMPDIR through a symbolic link, as macOS does through /var.
launch_tmpdir_link=$test_dir/tmp-link
ln -s -- tmp "$launch_tmpdir_link"
print -r -- 'http_unix_socket: /nonexistent/secret-exec-test.sock' > "$caller_gh_config/config.yml"
export FAKE_CALLER_GH_CONFIG_DIR=$caller_gh_config
# The caller's own GH_TOKEN must reach the consumer untouched.
caller_gh_value=caller-gh-value
typeset -a caller_gh_environment=(GH_TOKEN=$caller_gh_value
  FAKE_EXPECTED_TARGET_GH_TOKEN=$caller_gh_value)

fail() {
  print -u2 -r -- "$1"
  exit 1
}

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
print -r -- pass-cli >> "$FAKE_CALLS_LOG"
[[ -z ${FAKE_PASS_EXIT:-} ]] || exit $FAKE_PASS_EXIT
print -r -- fixture-token
EOF
cat > "$bin_dir/gh" <<'EOF'
#!/bin/zsh -f
print -r -- gh >> "$FAKE_CALLS_LOG"
print -r -- "${GH_CONFIG_DIR-}" >> "$FAKE_GH_CONFIG_LOG"
[[ -n ${GH_CONFIG_DIR-} && $GH_CONFIG_DIR != $FAKE_CALLER_GH_CONFIG_DIR &&
  -d $GH_CONFIG_DIR && -z $(print -rl -- $GH_CONFIG_DIR/*(ND)) ]] || exit 74
for transport_name in HTTPS_PROXY https_proxy HTTP_PROXY http_proxy \
  ALL_PROXY all_proxy SSL_CERT_FILE SSL_CERT_DIR; do
  (( ! ${(P)+transport_name} )) || exit 76
done
# Standard error chatter that names the token and the request, and carries a
# status mid-line, must neither decide the outcome nor reach the launch's
# output.
print -u2 -r -- "gh-chatter (HTTP 200) Get https://api.github.com/user with ${GH_TOKEN-}"
[[ -z ${FAKE_GH_EXIT:-} ]] || exit $FAKE_GH_EXIT
[[ $GH_TOKEN == fixture-token ]] || exit 71
[[ $* == 'api --hostname github.com user --jq .login' ]] || exit 73
if [[ -n ${FAKE_GH_HTTP_STATUS:-} ]]; then
  # As gh does: the status on standard error, after the response's JSON
  # message when it carries one; --jq reads an empty JSON body as null.
  if [[ -n ${FAKE_GH_HTTP_BARE:-} ]]; then
    print -r -- null
    print -u2 -r -- "gh: HTTP $FAKE_GH_HTTP_STATUS"
  else
    print -r -- "{\"message\":\"gh-refusal\",\"status\":\"$FAKE_GH_HTTP_STATUS\"}"
    print -u2 -r -- "gh: gh-refusal (HTTP $FAKE_GH_HTTP_STATUS)"
  fi
  exit 1
fi
# An error gh reports without a status, such as an errors list or a page --jq
# cannot read.
if [[ -n ${FAKE_GH_ERROR_LINE:-} ]]; then
  print -u2 -r -- "$FAKE_GH_ERROR_LINE"
  exit 1
fi
[[ -z ${FAKE_GH_DELAY:-} ]] || sleep $FAKE_GH_DELAY
print -r -- "${FAKE_GITHUB_LOGIN:-fixture-personal}"
EOF
cat > "$bin_dir/target" <<'EOF'
#!/bin/zsh -f
print -r -- target >> "$FAKE_CALLS_LOG"
[[ ${GH_CONFIG_DIR-} == $FAKE_CALLER_GH_CONFIG_DIR ]] || exit 75
[[ ${HTTPS_PROXY-} == http://127.0.0.1:9 && ${SSL_CERT_FILE-} == /nonexistent/ca.pem ]] || exit 77
[[ ${GH_TOKEN-unset} == ${FAKE_EXPECTED_TARGET_GH_TOKEN-unset} ]] || exit 78
[[ $GITHUB_PERSONAL_ACCESS_TOKEN == fixture-token ]] || exit 72
print -r -- target-ran
EOF
for notifier_name in notify-send osascript; do
  cat > "$bin_dir/$notifier_name" <<'EOF'
#!/bin/zsh -f
print -r -- notify >> "$FAKE_CALLS_LOG"
EOF
done
chmod 700 "$fixture_home/.local/bin/proton-pass-ensure-ready" \
  "$bin_dir/pass-cli" "$bin_dir/gh" "$bin_dir/target" \
  "$bin_dir/notify-send" "$bin_dir/osascript"
cat > "$profile_dir/github.env" <<'EOF'
# secret-exec-github-profile=github-fixture-personal
# secret-exec-github-login=fixture-personal
GITHUB_PERSONAL_ACCESS_TOKEN=pass://fixture-vault/item/password
EOF
chmod 600 "$profile_dir/github.env"

typeset -a launch_environment=()

launch() {
  local login=$1
  shift
  env HOME=$fixture_home \
    XDG_CONFIG_HOME=$fixture_home/.config \
    XDG_STATE_HOME=$test_dir/state \
    PATH=$bin_dir:/usr/bin:/bin \
    GH_HOST=enterprise.invalid \
    GH_CONFIG_DIR=$caller_gh_config \
    HTTPS_PROXY=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 \
    HTTP_PROXY=http://127.0.0.1:9 http_proxy=http://127.0.0.1:9 \
    ALL_PROXY=http://127.0.0.1:9 all_proxy=http://127.0.0.1:9 \
    SSL_CERT_FILE=/nonexistent/ca.pem SSL_CERT_DIR=/nonexistent \
    TMPDIR=$launch_tmpdir_link \
    FAKE_GITHUB_LOGIN=$login \
    "${caller_gh_environment[@]}" \
    "${launch_environment[@]}" \
    "$launcher" "$@"
}

run_launcher() {
  launch "${1:-fixture-personal}" github -- target
}

# Runs one launch that must fail closed with exactly the given diagnostic.
expect_fail_closed() {
  local expected_diagnostic=$1 label=$2
  shift 2
  : > "$FAKE_CALLS_LOG"
  local output
  integer launch_status
  set +e
  output=$(launch "$@" 2>&1)
  launch_status=$?
  set -e
  (( launch_status == 1 )) || fail "$label must fail closed: status=$launch_status"
  [[ $output == "secret-exec: $expected_diagnostic" ]] ||
    fail "$label must report only its value-free diagnostic"
  [[ $(<"$FAKE_CALLS_LOG") != *target* ]] || fail "$label must not start the consumer"
}

# Each identity-check failure names its cause and nothing else: no token, no
# login, and none of gh's own output.
check_failed='GitHub identity self-check failed'
config_create_diagnostic="$check_failed: cannot create a private gh configuration under TMPDIR"
config_trust_diagnostic="$check_failed: another user can change TMPDIR or a directory above it"
mismatch_diagnostic="$check_failed: the token belongs to a different GitHub account than the profile expects"
rejected_diagnostic="$check_failed: GitHub rejected the token (HTTP 401: expired or revoked)"
refused_diagnostic="$check_failed: GitHub refused the request (HTTP 503)"
bare_refused_diagnostic="$check_failed: GitHub refused the request (HTTP 502)"
no_status_diagnostic="$check_failed: no HTTP status was reported"
timeout_diagnostic="$check_failed: no answer from GitHub within 3 seconds"

# A passing check prints nothing of its own, not even gh's chatter.
[[ $(run_launcher 2>&1) == target-ran ]] ||
  { print -u2 -r -- 'matching GitHub identity must start the consumer and print nothing else'; exit 1; }
# The check ran against its own empty configuration, which is gone afterwards.
isolated_gh_config=$(<"$FAKE_GH_CONFIG_LOG")
[[ $isolated_gh_config == ${launch_tmpdir:P}/* && ! -e $isolated_gh_config ]] ||
  fail 'the identity check must use and then remove a private gh configuration'
[[ -z $(print -rl -- $launch_tmpdir/*(ND)) ]] ||
  fail 'the identity check must not leave temporary files'
caller_gh_environment=()
[[ $(run_launcher) == target-ran ]] ||
  fail 'without a caller GH_TOKEN the consumer must not receive one'
caller_gh_environment=(GH_TOKEN=$caller_gh_value
  FAKE_EXPECTED_TARGET_GH_TOKEN=$caller_gh_value)
# The private configuration must sit where no other user can swap it.
chmod 777 "$launch_tmpdir"
expect_fail_closed "$config_trust_diagnostic" \
  'a world-writable temporary directory' fixture-personal github -- target
chmod 1777 "$launch_tmpdir"
[[ $(run_launcher) == target-ran ]] ||
  fail 'a sticky temporary directory must still start the consumer'
chmod 700 "$launch_tmpdir"
launch_environment=(TMPDIR=$test_dir/missing-tmp)
expect_fail_closed "$config_create_diagnostic" \
  'a missing temporary directory' fixture-personal github -- target
launch_environment=()

set +e
wrong_output=$(run_launcher fixture-other 2>&1)
wrong_status=$?
set -e
(( wrong_status != 0 )) ||
  { print -u2 -r -- 'mismatched GitHub identity must fail closed'; exit 1; }
[[ $wrong_output == "secret-exec: $mismatch_diagnostic" ]] ||
  { print -u2 -r -- 'mismatched GitHub identity must report a redacted mismatch'; exit 1; }
for confidential_value in fixture-token fixture-personal fixture-other gh-chatter; do
  [[ $wrong_output != *${confidential_value}* ]] ||
    { print -u2 -r -- 'identity failure must not disclose credentials or logins'; exit 1; }
done
[[ $wrong_output != *target-ran* ]] ||
  { print -u2 -r -- 'mismatched GitHub identity must not start the consumer'; exit 1; }

# gh's own failures are told apart by cause: a token GitHub rejects, another
# refusal whose status gh reports, with or without a message, a failure gh
# reports without a status, and no answer before the deadline.
launch_environment=(FAKE_GH_HTTP_STATUS=401)
expect_fail_closed "$rejected_diagnostic" \
  'a token GitHub rejects' fixture-personal github -- target
launch_environment=(FAKE_GH_HTTP_STATUS=503)
expect_fail_closed "$refused_diagnostic" \
  'a request GitHub refuses' fixture-personal github -- target
launch_environment=(FAKE_GH_HTTP_STATUS=502 FAKE_GH_HTTP_BARE=1)
expect_fail_closed "$bare_refused_diagnostic" \
  'a refusal without a message' fixture-personal github -- target
launch_environment=(FAKE_GH_EXIT=1)
expect_fail_closed "$no_status_diagnostic" \
  'a checker that fails before any request' fixture-personal github -- target
launch_environment=('FAKE_GH_ERROR_LINE=gh: gh-first-error')
expect_fail_closed "$no_status_diagnostic" \
  'an errors list gh reports without a status' fixture-personal github -- target
launch_environment=("FAKE_GH_ERROR_LINE=invalid character '<' looking for beginning of value")
expect_fail_closed "$no_status_diagnostic" \
  'an error page --jq cannot read' fixture-personal github -- target
launch_environment=(FAKE_GH_DELAY=10)
expect_fail_closed "$timeout_diagnostic" \
  'a checker that outlives its deadline' fixture-personal github -- target
launch_environment=()

# Best-effort covers the provider only: every identity-check failure fails
# closed (the #320 rebase rule, part a).
: > "$FAKE_CALLS_LOG"
[[ $(launch fixture-personal --best-effort github -- target 2>&1) == target-ran ]] ||
  fail 'a best-effort launch with a matching GitHub identity must start the consumer and print nothing else'
[[ $(<"$FAKE_CALLS_LOG") == $'pass-cli\ngh\ntarget' ]] ||
  fail 'a best-effort GitHub launch must resolve and check before starting the consumer'
expect_fail_closed "$mismatch_diagnostic" \
  'a best-effort launch with a mismatched GitHub identity' \
  fixture-other --best-effort github -- target
launch_environment=(FAKE_GH_EXIT=1)
expect_fail_closed "$no_status_diagnostic" \
  'a best-effort launch whose GitHub checker fails' \
  fixture-personal --best-effort github -- target
launch_environment=(FAKE_PASS_EXIT=9)
: > "$FAKE_CALLS_LOG"
set +e
provider_output=$(launch fixture-personal --best-effort github -- target 2>&1)
provider_status=$?
set -e
(( provider_status == 72 )) ||
  fail "a best-effort GitHub launch must start the consumer when the provider fails: status=$provider_status"
[[ $provider_output == $'secret-exec: failed to resolve GITHUB_PERSONAL_ACCESS_TOKEN\nsecret-exec: starting target without github credentials' ]] ||
  fail 'a best-effort GitHub provider failure must report the usual fallback'
provider_calls=(${(f)"$(<"$FAKE_CALLS_LOG")"})
(( ${provider_calls[(Ie)target]} && ! ${provider_calls[(Ie)gh]} )) ||
  fail 'a best-effort GitHub provider failure must skip the identity check'
launch_environment=()
full_github_profile=$(<"$profile_dir/github.env")
print -r -- "${full_github_profile/'# secret-exec-github-login=fixture-personal'$'\n'/}" \
  > "$profile_dir/github.env"
expect_fail_closed 'GitHub identity self-check metadata is missing' \
  'a best-effort launch without GitHub identity metadata' \
  fixture-personal --best-effort github -- target
print -r -- "$full_github_profile" > "$profile_dir/github.env"

# An inherited github marker never skips resolution or the identity check
# (the #320 rebase rule, part b).
resolved_fixture_value=$(zsh -f "$bin_dir/pass-cli")
: > "$FAKE_CALLS_LOG"
launch_environment=(SECRET_EXEC_INJECTED_PROFILES=github
  GITHUB_PERSONAL_ACCESS_TOKEN=$resolved_fixture_value)
expect_fail_closed "$mismatch_diagnostic" \
  'an inherited github profile with a mismatched identity' \
  fixture-other github -- target
: > "$FAKE_CALLS_LOG"
[[ $(run_launcher) == target-ran ]] ||
  fail 'an inherited github profile with a matching identity must start the consumer'
[[ $(<"$FAKE_CALLS_LOG") == $'pass-cli\ngh\ntarget' ]] ||
  fail 'an inherited github profile must be resolved and checked again'
# Nor does an inherited fallback marker skip them.
: > "$FAKE_CALLS_LOG"
launch_environment=(SECRET_EXEC_FALLBACK_PROFILES=github)
[[ $(run_launcher) == target-ran ]] ||
  fail 'a github fallback marker must not stop a checked launch'
[[ $(<"$FAKE_CALLS_LOG") == $'pass-cli\ngh\ntarget' ]] ||
  fail 'a github fallback marker must not skip resolution or the identity check'
launch_environment=()

homebrew_bin=$test_dir/homebrew/Cellar/gh/1.0.0/bin
mkdir -p -- "$homebrew_bin"
mv -- "$bin_dir/gh" "$homebrew_bin/gh"
ln -s -- ../homebrew/Cellar/gh/1.0.0/bin/gh "$bin_dir/gh"
[[ $(run_launcher) == target-ran ]] ||
  { print -u2 -r -- 'a trusted Homebrew GitHub checker must start the consumer'; exit 1; }

# No other user may swap the checker after its own checks: every directory
# above it must resist renames, so one writable by its group or by others
# must be sticky.
checker_ancestor=$test_dir/homebrew/Cellar
chmod 775 "$checker_ancestor"
expect_fail_closed 'a trusted GitHub identity checker is required' \
  'a group-writable checker ancestor' fixture-personal github -- target
chmod 1775 "$checker_ancestor"
[[ $(run_launcher) == target-ran ]] ||
  fail 'a sticky group-writable checker ancestor must stay trusted'
chmod 777 "$checker_ancestor"
expect_fail_closed 'a trusted GitHub identity checker is required' \
  'a world-writable checker ancestor' fixture-personal github -- target
chmod 1777 "$checker_ancestor"
[[ $(run_launcher) == target-ran ]] ||
  fail 'a sticky world-writable checker ancestor must stay trusted'
chmod 755 "$checker_ancestor"

# An ACL that lets another user change the checker or a directory above it is
# write access too. macOS lists ACLs apart from the mode bits; a Linux POSIX
# ACL's write grants show in the group bits, as its mask.
if [[ $OSTYPE == darwin* ]]; then
  chmod +a 'everyone allow add_file,delete_child' "$checker_ancestor"
  expect_fail_closed 'a trusted GitHub identity checker is required' \
    'an ACL that grants changes to a checker ancestor' fixture-personal github -- target
  chmod -N "$checker_ancestor"
  chmod +a 'everyone allow write' "$homebrew_bin/gh"
  expect_fail_closed 'a trusted GitHub identity checker is required' \
    'an ACL that grants changes to the checker' fixture-personal github -- target
  chmod -N "$homebrew_bin/gh"
  # macOS home directories carry this entry.
  chmod +a 'everyone deny delete' "$checker_ancestor"
  [[ $(run_launcher) == target-ran ]] ||
    fail 'a deny-only ACL on a checker ancestor must stay trusted'
  chmod -N "$checker_ancestor"
elif command -v setfacl >/dev/null &&
  setfacl -m u:nobody:rwx "$checker_ancestor" 2>/dev/null; then
  expect_fail_closed 'a trusted GitHub identity checker is required' \
    'a POSIX ACL that grants writes to a checker ancestor' fixture-personal github -- target
  setfacl -m u:nobody:rx "$checker_ancestor"
  [[ $(run_launcher) == target-ran ]] ||
    fail 'a read-only POSIX ACL on a checker ancestor must stay trusted'
  setfacl -b "$checker_ancestor"
fi

chmod 720 "$homebrew_bin/gh"
set +e
untrusted_output=$(run_launcher 2>&1)
untrusted_status=$?
set -e
(( untrusted_status != 0 )) && [[ $untrusted_output != *target-ran* ]] ||
  { print -u2 -r -- 'an untrusted GitHub checker must not start the consumer'; exit 1; }

[[ -z $(print -rl -- $launch_tmpdir/*(ND)) ]] ||
  fail 'failed identity checks must not leave temporary files'

print -r -- 'github identity binding checks passed'
