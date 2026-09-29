#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
source_root=${PROTON_PASS_AGENT_READINESS_SOURCE_ROOT:-$repo_root}
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/proton-pass-agent-readiness.XXXXXX")
trap '/bin/rm -rf -- "$test_dir"' EXIT

# exit, not return: errexit inside a function skips zsh's EXIT trap.
fail() {
  print -u2 -r -- "$1"
  exit 1
}

fixture_home=$test_dir/home
fixture_bin=$fixture_home/.local/bin
profile_dir=$fixture_home/.config/secret-exec/profiles
state_home=$fixture_home/.local/state
mkdir -p -- "$fixture_bin" "$profile_dir" "$state_home"
chmod 700 "$fixture_home/.config/secret-exec" "$profile_dir"

launcher=$fixture_bin/secret-exec
readiness=$fixture_bin/proton-pass-ensure-ready
native_store=$fixture_bin/secret-exec-native-store
fixture_process_lister=$fixture_bin/fixture-ps
cat > "$fixture_process_lister" <<'EOF'
#!/bin/zsh -f
set -euo pipefail

[[ $* == '-eo pid=,pgid=' ]] || exit 75
zmodload zsh/system
print -r -- "$PPID $PPID"
print -r -- "$sysparams[pid] $PPID"
EOF
chmod 700 "$fixture_process_lister"

# The task sandbox denies fixed /bin/ps inside zpty. Substitute only that
# process-list boundary in disposable copies so the real seam remains runnable.
launcher_text=$(<"$source_root/home/private_dot_local/bin/executable_secret-exec")
launcher_text=${launcher_text//\/bin\/ps -eo pid=,pgid=/$fixture_process_lister -eo pid=,pgid=}
print -r -- "$launcher_text" > "$launcher"
readiness_text=$(<"$source_root/home/private_dot_local/bin/executable_proton-pass-ensure-ready")
readiness_text=${readiness_text//\/bin\/ps -eo pid=,pgid=/$fixture_process_lister -eo pid=,pgid=}
print -r -- "$readiness_text" > "$readiness"
chmod 700 "$launcher" "$readiness"

cat > "$profile_dir/agent.env" <<'EOF'
AGENT_FIXTURE_VALUE=pass://fixture/agent/password
EOF
chmod 600 "$profile_dir/agent.env"

cat > "$fixture_bin/pass-cli" <<'EOF'
#!/bin/zsh -f
set -euo pipefail

bootstrap_field=PROTON_PASS_PERSONAL_ACCESS
bootstrap_field+=_TOKEN
case $1 in
  info)
    print -r -- info >> "$FAKE_PASS_LOG"
    [[ ${PROTON_PASS_NO_UPDATE_CHECK:-} == 1 ]] || exit 64
    [[ -z ${${(P)bootstrap_field}:-} ]] || exit 65
    # Daily telemetry, Rust backtraces, and provider log levels all change the
    # provider's text.
    [[ ${PROTON_PASS_DISABLE_TELEMETRY:-} == 1 ]] || exit 72
    (( ! ${+RUST_BACKTRACE} && ! ${+RUST_LIB_BACKTRACE} )) || exit 73
    (( ! ${+PASS_LOG_LEVEL} && ! ${+MUON_LOG_LEVEL} )) || exit 77
    case $(<"$FAKE_SESSION_STATE") in
      ready) exit 0 ;;
      absent)
        print -u2 -rl -- \
          'Command is not logout there is no session' \
          'Error: This operation requires an authenticated client'
        exit 1
        ;;
      orphaned)
        print -u2 -rl -- \
          'Error: Error getting personal access token name' \
          '' \
          'Caused by:' \
          '    0: Error sending request' \
          '    1: failed to authenticate: non-existent session' \
          '    2: non-existent session'
        exit 1
        ;;
      unknown)
        print -u2 -rl -- \
          'Operation not permitted while accessing the native keyring' \
          'Error: This operation requires an authenticated client'
        exit 1
        ;;
      *) exit 66 ;;
    esac
    ;;
  login)
    print -r -- login >> "$FAKE_PASS_LOG"
    [[ $# == 1 ]] || exit 67
    [[ ${${(P)bootstrap_field}:-} == fake-bootstrap-value ]] || exit 68
    (( ! ${+PASS_LOG_LEVEL} && ! ${+MUON_LOG_LEVEL} )) || exit 77
    # pass-cli 2.3.3 refuses login while local authentication remains stored.
    if [[ -e $FAKE_LOCAL_SESSION ]]; then
      print -r -- 'Client is already authenticated. Log out if you want to log in again'
      print -u2 -r -- 'Error: Already authenticated'
      exit 1
    fi
    : > "$FAKE_LOCAL_SESSION"
    print -r -- ready > "$FAKE_SESSION_STATE"
    ;;
  logout)
    print -r -- "$*" >> "$FAKE_PASS_LOG"
    [[ $# == 2 && $2 == --force ]] || exit 74
    [[ -z ${${(P)bootstrap_field}:-} ]] || exit 75
    if [[ $OSTYPE == linux* ]]; then
      [[ ${PROTON_PASS_LINUX_KEYRING:-} == dbus ]] || exit 76
    fi
    print -r -- 'Executing force logout'
    print -r -- 'Successfully performed force logout'
    /bin/rm -f -- "$FAKE_LOCAL_SESSION"
    ;;
  item)
    print -r -- item >> "$FAKE_PASS_LOG"
    [[ $# == 5 && $2 == view && $3 == --output && $4 == human &&
      $5 == pass://fixture/agent/password ]] || exit 69
    [[ $(<"$FAKE_SESSION_STATE") == ready ]] || exit 70
    print -r -- fake-consumer-value
    ;;
  *) exit 71 ;;
esac
EOF
chmod 700 "$fixture_bin/pass-cli"

cat > "$native_store" <<'EOF'
#!/bin/zsh -f
set -euo pipefail

[[ $* == proton-bootstrap ]] || exit 72
print -r -- proton-bootstrap >> "$FAKE_NATIVE_STORE_LOG"
[[ ! -e $FAKE_NATIVE_STORE_UNAVAILABLE ]] || exit 73
print -r -- fake-bootstrap-value
EOF
chmod 700 "$native_store"

cat > "$fixture_bin/check-agent-fixture" <<'EOF'
#!/bin/zsh -f
set -euo pipefail

[[ ${AGENT_FIXTURE_VALUE:-} == fake-consumer-value ]] || exit 74
: > "$FAKE_TARGET_MARKER"
EOF
chmod 700 "$fixture_bin/check-agent-fixture"

export HOME=$fixture_home
export XDG_CONFIG_HOME=$fixture_home/.config
export XDG_STATE_HOME=$state_home
export PATH=$fixture_bin:/usr/bin:/bin
export FAKE_SESSION_STATE=$test_dir/session-state
export FAKE_LOCAL_SESSION=$test_dir/local-session
export FAKE_PASS_LOG=$test_dir/pass.log
export FAKE_NATIVE_STORE_LOG=$test_dir/native-store.log
export FAKE_NATIVE_STORE_UNAVAILABLE=$test_dir/native-store-unavailable
export FAKE_TARGET_MARKER=$test_dir/target-ran
# Readiness must scrub inherited backtrace and provider log-level requests
# before provider probes and login.
export RUST_BACKTRACE=1 RUST_LIB_BACKTRACE=full
export PASS_LOG_LEVEL=debug MUON_LOG_LEVEL=debug

status_file=$state_home/secret-exec/proton-pass-readiness.status

print -r -- absent > "$FAKE_SESSION_STATE"
rm -f -- "$FAKE_LOCAL_SESSION"
: > "$FAKE_PASS_LOG"
: > "$FAKE_NATIVE_STORE_LOG"
"$launcher" agent -- check-agent-fixture
[[ -e $FAKE_TARGET_MARKER ]] ||
  fail 'the recorded absent-session diagnostic must recover before starting the consumer'
[[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogin\ninfo\nitem' ]] ||
  fail 'the recorded absent-session diagnostic must complete one repair before resolution'
[[ $(<"$FAKE_NATIVE_STORE_LOG") == proton-bootstrap ]] ||
  fail 'the recorded absent-session diagnostic must reach native-store bootstrap'

# The provider dropped the session while local authentication remains, so
# login alone is refused until forced local cleanup removes it.
print -r -- orphaned > "$FAKE_SESSION_STATE"
: > "$FAKE_LOCAL_SESSION"
: > "$FAKE_PASS_LOG"
: > "$FAKE_NATIVE_STORE_LOG"
rm -f -- "$FAKE_TARGET_MARKER"
set +e
orphaned_output=$("$launcher" agent -- check-agent-fixture 2>&1)
orphaned_status=$?
set -e
(( orphaned_status == 0 )) ||
  fail "an orphaned provider session must recover: $orphaned_output"
[[ -e "$FAKE_TARGET_MARKER" ]] ||
  fail 'an orphaned provider session must recover before starting the consumer'
[[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogout --force\nlogin\ninfo\nitem' ]] ||
  fail 'an orphaned provider session must be cleaned up before its one repair login'
[[ $(<"$FAKE_NATIVE_STORE_LOG") == proton-bootstrap ]] ||
  fail 'an orphaned provider session must reach native-store bootstrap'
grep -Fqx 'reason=repaired' "$status_file" ||
  fail 'an orphaned provider session repair must record its value-free reason'

print -r -- orphaned > "$FAKE_SESSION_STATE"
: > "$FAKE_LOCAL_SESSION"
: > "$FAKE_PASS_LOG"
: > "$FAKE_NATIVE_STORE_LOG"
: > "$FAKE_NATIVE_STORE_UNAVAILABLE"
rm -f -- "$FAKE_TARGET_MARKER"
set +e
orphaned_store_output=$("$launcher" agent -- check-agent-fixture 2>&1)
orphaned_store_status=$?
set -e
rm -f -- "$FAKE_NATIVE_STORE_UNAVAILABLE"
(( orphaned_store_status != 0 )) ||
  fail 'an orphaned session with an unavailable native store must fail closed'
[[ $orphaned_store_output ==
  'proton-pass-ensure-ready: the native bootstrap item is unavailable or locked' ]] ||
  fail 'an orphaned session with an unavailable native store must report the store failure'
[[ $(<"$FAKE_PASS_LOG") == $'info\ninfo' ]] ||
  fail 'an orphaned session must not be cleaned up before the bootstrap item is available'
[[ -e $FAKE_LOCAL_SESSION ]] ||
  fail 'an orphaned session must keep local authentication when the bootstrap item is unavailable'
grep -Fqx 'reason=native-store-unavailable' "$status_file" ||
  fail 'an orphaned session with an unavailable native store must record its reason'

print -r -- unknown > "$FAKE_SESSION_STATE"
: > "$FAKE_PASS_LOG"
: > "$FAKE_NATIVE_STORE_LOG"
rm -f -- "$FAKE_TARGET_MARKER"
set +e
unknown_output=$("$launcher" agent -- check-agent-fixture 2>&1)
unknown_status=$?
set -e
(( unknown_status != 0 )) || fail 'an unknown provider diagnostic must fail closed'
[[ ! -e $FAKE_TARGET_MARKER ]] || fail 'an unknown provider diagnostic must not start the consumer'
[[ ! -s $FAKE_NATIVE_STORE_LOG ]] || fail 'an unknown provider diagnostic must not read the bootstrap item'
[[ $unknown_output ==
  'proton-pass-ensure-ready: provider-session readiness could not be classified' ]] ||
  fail 'an unknown provider diagnostic must report the readiness failure without unlock advice'

print -r -- absent > "$FAKE_SESSION_STATE"
: > "$FAKE_PASS_LOG"
: > "$FAKE_NATIVE_STORE_LOG"
: > "$FAKE_NATIVE_STORE_UNAVAILABLE"
set +e
store_output=$("$launcher" agent -- check-agent-fixture 2>&1)
store_status=$?
set -e
rm -f -- "$FAKE_NATIVE_STORE_UNAVAILABLE"
(( store_status != 0 )) || fail 'an unavailable native store must fail closed'
[[ $store_output ==
  'proton-pass-ensure-ready: the native bootstrap item is unavailable or locked' ]] ||
  fail 'an unavailable native store must preserve its actionable value-free readiness error'

! grep -F 'fake-bootstrap-value' "$status_file" \
  "$FAKE_PASS_LOG" "$FAKE_NATIVE_STORE_LOG" >/dev/null ||
  fail 'readiness artifacts must not contain the fake bootstrap value'

print -r -- 'Proton Pass agent readiness checks passed'
