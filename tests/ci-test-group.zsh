#!/usr/bin/env zsh
# Keep scripts/ci-test-group in step with the GitHub Actions test steps it
# partitions, until those workflows call the script themselves.
set -euo pipefail
setopt extendedglob

repo_root=${0:A:h:h}
script=$repo_root/scripts/ci-test-group

fail() {
  print -ru2 -- "FAIL: $*"
  exit 1
}

# Print the trimmed lines of one step's `run: |` block.
run_block() {
  emulate -L zsh
  local workflow=$1 step=$2
  awk -v step="- name: $step" '
    function indent(s) { match(s, /^ */); return RLENGTH }
    !in_step && index($0, step) && substr($0, indent($0) + 1) == step {
      in_step = 1; step_indent = indent($0); next
    }
    in_step && !in_run && /^ *run: \|$/ { in_run = 1; run_indent = indent($0); next }
    in_step && !in_run && /^ *- name: / && indent($0) == step_indent { exit }
    in_run {
      if ($0 ~ /^ *$/) next
      if (indent($0) <= run_indent) exit
      sub(/^ +/, ""); print
    }
  ' "$workflow"
}

# Lines that the script expresses differently on purpose.
typeset -A equivalents=(
  'set -euo pipefail' ''
  'if [[ "$RUNNER_OS" == Linux ]]; then' 'if [[ "$(uname -s)" == Linux ]]; then'
  'exit 1' 'return 1'
  'captured_state_output="$({' 'captured_state_output="$({'
)

typeset -A script_lines
while IFS= read -r line; do
  line=${line##[[:space:]]#}
  [[ -n $line ]] && script_lines[$line]=1
done < "$script"

integer checked=0
check_step() {
  local workflow=$repo_root/.github/workflows/$1 step=$2 line expected
  local -a lines
  lines=("${(@f)$(run_block "$workflow" "$step")}")
  (( ${#lines} > 1 )) || fail "no run block found for $1: $step"
  for line in "${lines[@]}"; do
    expected=$line
    if (( ${+equivalents[$line]} )); then
      expected=${equivalents[$line]}
      [[ -z $expected ]] && continue
    fi
    (( ${+script_lines[$expected]} )) ||
      fail "scripts/ci-test-group is missing a command from $1 ($step): $line"
    (( ++checked ))
  done
}

check_step platform-portability.yml 'Verify shell syntax'
check_step platform-portability.yml 'Verify platform bindings'
check_step platform-portability.yml 'Verify private-skill transaction'
check_step zsh-deployment-portability.yml 'Verify user-session deployment contracts'

listed=("${(@f)$(bash "$script" --list)}")
[[ ${(j: :)listed} == 'shell-bindings proton-pass discover python-checks zsh-deployment' ]] ||
  fail "unexpected group list: ${(j: :)listed}"
for group in "${listed[@]}"; do
  grep -Eq "^group_${group//-/_}\(\) \{$" "$script" ||
    fail "group $group has no function"
done
bash "$script" no-such-group >/dev/null 2>&1 && fail 'an unknown group must fail'

print -r -- "ci test group checks passed ($checked workflow lines)"
