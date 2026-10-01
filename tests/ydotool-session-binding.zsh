#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/ydotool-session-binding.XXXXXX")
test_dir=${test_dir:A}
trap 'rm -rf -- "$test_dir"' EXIT HUP INT TERM

# zsh skips EXIT traps when errexit fires inside a function.
TRAPZERR() {
  if [[ -o errexit ]] && (( ZSH_SUBSHELL == 0 && ${#funcstack} > 1 )); then
    rm -rf -- "$test_dir"
  fi
}

# exit, not return: errexit inside a function skips zsh's EXIT trap.
fail() {
  print -ru2 -- "FAIL: $*"
  exit 1
}

assert_line() {
  local line=$1 file=$2
  grep -Fqx -- "$line" "$file" || fail "missing line in ${file:t}: $line"
}

user_units=$repo_root/home/dot_config/systemd/user
dropin_source=$user_units/ydotool.service.d/50-graphical-session.conf
wants_source=$user_units/graphical-session.target.wants/symlink_ydotool.service
remove_source=$repo_root/home/.chezmoiremove
package_unit=/usr/lib/systemd/user/ydotool.service
boot_link=.config/systemd/user/default.target.wants/ydotool.service

[[ -f $dropin_source ]] || fail 'the ydotool session drop-in must be managed'
[[ -f $wants_source ]] || fail 'the graphical-session wants link must be managed'
assert_line 'Requisite=graphical-session.target' "$dropin_source"
assert_line 'PartOf=graphical-session.target' "$dropin_source"
assert_line 'After=graphical-session.target' "$dropin_source"
assert_line "$boot_link" "$remove_source"

# Render the managed pieces into a scratch home that already carries the
# boot-time link `systemctl --user enable ydotool.service` creates.
link_source=$test_dir/link-source
link_home=$test_dir/link-home
link_config=$test_dir/link-chezmoi.toml
mkdir -p -- \
  "$link_source/dot_config/systemd/user/ydotool.service.d" \
  "$link_source/dot_config/systemd/user/graphical-session.target.wants" \
  "$link_home/${boot_link:h}"
cp -- "$dropin_source" "$link_source/dot_config/systemd/user/ydotool.service.d/"
cp -- "$wants_source" \
  "$link_source/dot_config/systemd/user/graphical-session.target.wants/"
cp -- "$remove_source" "$link_source/"
ln -s -- "$package_unit" "$link_home/$boot_link"
: >"$link_config"
HOME=$link_home chezmoi -S "$link_source" -D "$link_home" \
  --config "$link_config" apply
rendered_units=$link_home/.config/systemd/user
rendered_wants=$rendered_units/graphical-session.target.wants/ydotool.service
[[ -L $rendered_wants ]] ||
  fail 'chezmoi must render the graphical-session membership as a symlink'
[[ $(readlink "$rendered_wants") == "$package_unit" ]] ||
  fail "the graphical-session membership must link to $package_unit"
[[ ! -e $link_home/$boot_link && ! -L $link_home/$boot_link ]] ||
  fail 'chezmoi must retire the boot-time default.target.wants link'

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

  # Stand in for the package unit so the transaction never depends on the
  # host's ydotool installation; the rendered drop-in and wants link apply.
  fixture_dir=$test_dir/systemd-fixtures
  mkdir -p -- "$fixture_dir"
  print -r -- '[Unit]
Description=Isolated ydotoold fixture

[Service]
ExecStart=/bin/true

[Install]
WantedBy=default.target' >"$fixture_dir/ydotool.service"
  for fixture_target in graphical-session.target basic.target shutdown.target; do
    print -r -- "[Unit]
Description=Isolated ${fixture_target} fixture" >"$fixture_dir/$fixture_target"
  done

  # A user-mode manager needs a runtime directory even under --test; supply a
  # private one so the transaction never depends on the caller's session.
  transaction_runtime_dir=$test_dir/systemd-runtime
  mkdir -m 0700 -- "$transaction_runtime_dir"

  run_transaction() {
    local unit=$1 log=$test_dir/transaction-${1}.log
    if ! XDG_RUNTIME_DIR=$transaction_runtime_dir \
      SYSTEMD_UNIT_PATH="${fixture_dir}:${rendered_units}" \
      SYSTEMD_GENERATOR_PATH=/dev/null \
      SYSTEMD_ENVIRONMENT_GENERATOR_PATH=/dev/null \
      SYSTEMD_LOG_LEVEL=info \
      "$systemd_test_bin" --test --user --unit="$unit" >"$log" 2>&1; then
      print -u2 -r -- "$(<"$log")"
      fail "systemd must construct the isolated $unit transaction"
    fi
    REPLY=$(<"$log")
  }

  run_transaction ydotool.service
  [[ $REPLY == *'Action: graphical-session.target -> verify-active'* ]] ||
    fail 'systemd must verify the graphical session before starting ydotoold'
  [[ $REPLY != *'Action: graphical-session.target -> start'* ]] ||
    fail 'starting ydotoold must not pull in graphical-session.target'
  [[ $REPLY == *'Action: ydotool.service -> start'* ]] ||
    fail 'systemd must gate the ydotoold start behind session verification'
  [[ $REPLY == *'RequisiteOf: ydotool.service'* ]] ||
    fail 'systemd must retain the session prerequisite edge'
  [[ $REPLY == *'ConsistsOf: ydotool.service'* ]] ||
    fail 'systemd must stop ydotoold when the graphical session stops'

  run_transaction graphical-session.target
  [[ $REPLY == *'Action: ydotool.service -> start'* ]] ||
    fail 'starting the graphical session must start ydotoold'
fi

print -r -- 'ydotool session binding checks passed'
