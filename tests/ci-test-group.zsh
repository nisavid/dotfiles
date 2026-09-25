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

# Lines only the script needs: this check itself and a local declaration.
typeset -A script_only=(
  'zsh -f tests/ci-test-group.zsh' 1
  'local captured_state_output captured_state_status' 1
)

# Print the trimmed, non-empty body lines of one group function.
group_lines() {
  emulate -L zsh
  awk -v start="group_${1//-/_}() {" '
    $0 == start { in_group = 1; next }
    in_group && $0 == "}" { exit }
    in_group { sub(/^ +/, ""); if ($0 != "") print }
  ' "$script"
}

# Compare a workflow's test steps with the groups that partition them, in both
# directions, so neither side can gain or lose a command unnoticed.
integer checked=0
typeset -a partitioned_groups
check_partition() {
  local label=$1 step_list=$2 group_list=$3 step group line
  local workflow=$repo_root/.github/workflows/$label
  local -a steps groups lines
  local -A expected actual
  steps=("${(@s:|:)step_list}")
  groups=("${(@s: :)group_list}")
  partitioned_groups+=("${groups[@]}")
  for step in "${steps[@]}"; do
    lines=("${(@f)$(run_block "$workflow" "$step")}")
    (( ${#lines} > 1 )) || fail "no run block found for $label: $step"
    for line in "${lines[@]}"; do
      if (( ${+equivalents[$line]} )); then
        line=${equivalents[$line]}
        [[ -z $line ]] && continue
      fi
      expected[$line]=1
    done
  done
  for group in "${groups[@]}"; do
    lines=("${(@f)$(group_lines "$group")}")
    (( ${#lines} > 0 )) || fail "group $group has no commands"
    for line in "${lines[@]}"; do
      (( ${+script_only[$line]} )) || actual[$line]=1
    done
  done
  for line in "${(@k)expected}"; do
    (( ${+actual[$line]} )) ||
      fail "groups ($group_list) are missing a command from $label: $line"
    (( ++checked ))
  done
  for line in "${(@k)actual}"; do
    (( ${+expected[$line]} )) ||
      fail "groups ($group_list) run a command that $label does not: $line"
  done
}

check_partition platform-portability.yml \
  'Verify shell syntax|Verify platform bindings|Verify private-skill transaction' \
  'shell-bindings proton-pass discover python-checks'
check_partition zsh-deployment-portability.yml \
  'Verify user-session deployment contracts' \
  'zsh-deployment'

listed=("${(@f)$(bash "$script" --list)}")
[[ ${(j: :)${(o)listed}} == ${(j: :)${(o)partitioned_groups}} ]] ||
  fail 'every group must partition exactly one workflow'
[[ ${(j: :)listed} == 'shell-bindings proton-pass discover python-checks zsh-deployment' ]] ||
  fail "unexpected group list: ${(j: :)listed}"
for group in "${listed[@]}"; do
  grep -Eq "^group_${group//-/_}\(\) \{$" "$script" ||
    fail "group $group has no function"
done
bash "$script" no-such-group >/dev/null 2>&1 && fail 'an unknown group must fail'

print -r -- "ci test group checks passed ($checked workflow lines)"
