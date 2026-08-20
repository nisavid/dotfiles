#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/proton-pass-startup-bindings.XXXXXX")
test_dir=${test_dir:A}
trap 'rm -rf -- "$test_dir"' EXIT HUP INT TERM

fail() {
  print -ru2 -- "FAIL: $*"
  return 1
}

assert_line() {
  local line=$1 file=$2
  grep -Fqx -- "$line" "$file" || fail "missing line in ${file:t}: $line"
}

unit_source=$repo_root/home/dot_config/systemd/user/proton-pass-ensure-ready.service
wants_source=$repo_root/home/dot_config/systemd/user/plasma-workspace.target.wants/symlink_proton-pass-ensure-ready.service
agent_template=$repo_root/home/private_Library/private_LaunchAgents/io.nisavid.secret-exec-provider-ready.plist.tmpl
activation_template=$repo_root/home/run_after_activate-proton-pass-provider-ready.zsh.tmpl
ignore_template=$repo_root/home/.chezmoiignore

[[ -f $unit_source ]] || fail 'the Linux user unit must be managed'
[[ -f $wants_source ]] || fail 'the Plasma target wants link must be managed'
[[ -f $agent_template ]] || fail 'the macOS LaunchAgent must be managed'
[[ -f $activation_template ]] || fail 'the provider-readiness activation hook must be managed'

if [[ $OSTYPE == linux* ]]; then
  systemd_test_bin=
  for systemd_candidate in /usr/lib/systemd/systemd /lib/systemd/systemd; do
    if [[ -x $systemd_candidate ]]; then
      systemd_test_bin=$systemd_candidate
      break
    fi
  done
  [[ -n $systemd_test_bin ]] ||
    fail 'Linux must provide the systemd manager binary for transaction testing'

  transaction_dir=$test_dir/systemd-transaction
  mkdir -p -- "$transaction_dir"
  for transaction_target in \
    plasma-workspace.target graphical-session.target \
    xdg-desktop-autostart.target basic.target shutdown.target; do
    print -r -- "[Unit]
Description=Isolated ${transaction_target} fixture" >"$transaction_dir/$transaction_target"
  done
  print -r -- '[Unit]
Description=Isolated KWallet fixture

[Service]
Type=oneshot
ExecStart=/bin/true' >"$transaction_dir/plasma-kwallet-pam.service"

  transaction_log=$test_dir/systemd-transaction.log
  if ! SYSTEMD_UNIT_PATH="${transaction_dir}:${unit_source:h}" \
    SYSTEMD_GENERATOR_PATH=/dev/null \
    SYSTEMD_ENVIRONMENT_GENERATOR_PATH=/dev/null \
    SYSTEMD_LOG_LEVEL=info \
    "$systemd_test_bin" --test --user \
      --unit=proton-pass-ensure-ready.service >"$transaction_log" 2>&1; then
    print -u2 -r -- "$(<"$transaction_log")"
    fail 'systemd must construct the isolated readiness transaction'
  fi
  transaction_output=$(<"$transaction_log")
  for prerequisite_target in plasma-workspace.target graphical-session.target; do
    [[ $transaction_output == *"Action: $prerequisite_target -> verify-active"* ]] ||
      fail "systemd must verify inactive $prerequisite_target at transaction start"
    [[ $transaction_output != *"Action: $prerequisite_target -> start"* ]] ||
      fail "the readiness transaction must not pull in $prerequisite_target"
  done
  [[ $transaction_output ==
    *'Action: proton-pass-ensure-ready.service -> start'* ]] ||
    fail 'systemd must gate the readiness start behind prerequisite verification jobs'
  [[ $transaction_output ==
    *'RequisiteOf: proton-pass-ensure-ready.service'* ]] ||
    fail 'systemd must retain prerequisite verification edges in the manager graph'
  [[ $transaction_output ==
    *'ConsistsOf: proton-pass-ensure-ready.service'* ]] ||
    fail 'systemd must retain PartOf stop propagation in the manager graph'
fi

link_source=$test_dir/link-source
link_home=$test_dir/link-home
link_config=$test_dir/link-chezmoi.toml
mkdir -p -- \
  "$link_source/dot_config/systemd/user/plasma-workspace.target.wants" \
  "$link_home"
cp -- "$unit_source" "$link_source/dot_config/systemd/user/"
cp -- "$wants_source" \
  "$link_source/dot_config/systemd/user/plasma-workspace.target.wants/"
: >"$link_config"
HOME=$link_home chezmoi -S "$link_source" -D "$link_home" \
  --config "$link_config" apply
rendered_wants=$link_home/.config/systemd/user/plasma-workspace.target.wants/proton-pass-ensure-ready.service
[[ -L $rendered_wants ]] ||
  fail 'chezmoi must render the Plasma target membership as a symlink'
[[ $(readlink "$rendered_wants") == '../proton-pass-ensure-ready.service' ]] ||
  fail 'the rendered Plasma target membership must remain relative'

fixture_home=$test_dir/home
mkdir -p -- "$fixture_home"
darwin_override='{"chezmoi":{"homeDir":"'"$fixture_home"'","os":"darwin"}}'
rendered_agent=$test_dir/provider-ready.plist
chezmoi -S "$repo_root/home" execute-template --override-data "$darwin_override" \
  <"$agent_template" >"$rendered_agent"
python3 - "$rendered_agent" "$fixture_home/.local/bin/proton-pass-startup" <<'PY'
import plistlib
import sys

with open(sys.argv[1], "rb") as stream:
    agent = plistlib.load(stream)

expected = {
    "Label": "io.nisavid.secret-exec-provider-ready",
    "LimitLoadToSessionType": "Aqua",
    "ProcessType": "Background",
    "ProgramArguments": [sys.argv[2]],
    "RunAtLoad": True,
}
if agent != expected:
    raise SystemExit(f"unexpected LaunchAgent contract: {agent!r}")
PY

for os_name in linux darwin freebsd; do
  chezmoi -S "$repo_root/home" execute-template \
    --override-data "{\"chezmoi\":{\"os\":\"$os_name\"}}" \
    <"$ignore_template" >"$test_dir/$os_name-ignore"
done

assert_line Library "$test_dir/linux-ignore"
! grep -Fqx -- '.config/systemd' "$test_dir/linux-ignore" ||
  fail 'Linux must manage the provider-readiness systemd tree'
! grep -Fqx -- '.config/environment.d/98-proton-pass.conf' "$test_dir/linux-ignore" ||
  fail 'Linux must manage the Proton Pass provider selector'

! grep -Fqx -- Library "$test_dir/darwin-ignore" ||
  fail 'macOS must manage the provider-readiness LaunchAgent'
assert_line '.config/systemd' "$test_dir/darwin-ignore"
assert_line '.config/environment.d/98-proton-pass.conf' "$test_dir/darwin-ignore"

assert_line Library "$test_dir/freebsd-ignore"
assert_line '.config/systemd' "$test_dir/freebsd-ignore"
assert_line '.config/environment.d/98-proton-pass.conf' "$test_dir/freebsd-ignore"

rendered_linux_activation=$test_dir/rendered-activate-linux
rendered_darwin_activation=$test_dir/rendered-activate-darwin
linux_override='{"chezmoi":{"homeDir":"'"$fixture_home"'","os":"linux"}}'
chezmoi -S "$repo_root/home" execute-template --override-data "$linux_override" \
  <"$activation_template" >"$rendered_linux_activation"
chezmoi -S "$repo_root/home" execute-template --override-data "$darwin_override" \
  <"$activation_template" >"$rendered_darwin_activation"
zsh -n "$rendered_linux_activation" ||
  fail 'the rendered Linux activation must parse as Zsh'
zsh -n "$rendered_darwin_activation" ||
  fail 'the rendered macOS activation must parse as Zsh'

print -r -- 'Proton Pass startup binding checks passed'
