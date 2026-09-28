#!/usr/bin/env zsh
# Keep every CI definition running exactly the groups in scripts/ci-test-group,
# and keep test commands in the script rather than in the workflows.
set -euo pipefail

repo_root=${0:A:h:h}
script=$repo_root/scripts/ci-test-group
portability=$repo_root/.github/workflows/platform-portability.yml
deployment=$repo_root/.github/workflows/zsh-deployment-portability.yml
buildkite=$repo_root/.buildkite/pipeline.yml

fail() {
  print -ru2 -- "FAIL: $*"
  exit 1
}

# Print the items of each `<key>:` block list in a YAML file, in order.
list_items() {
  emulate -L zsh
  awk -v key="$2:" '
    { line = $0; sub(/^ +/, "", line) }
    line == key { in_list = 1; next }
    in_list && line ~ /^- / { sub(/^- /, "", line); print line; next }
    { in_list = 0 }
  ' "$1"
}

# Count the lines that run exactly this command as a step's `run:` value.
count_runs() {
  emulate -L zsh
  awk -v run="run: $2" '
    { line = $0; sub(/^ +/, "", line) }
    line == run { n++ }
    END { print n + 0 }
  ' "$1"
}

groups=("${(@f)$(bash "$script" --list)}")
[[ ${(j: :)groups} == 'shell-bindings proton-pass discover python-checks zsh-deployment' ]] ||
  fail "unexpected group list: ${(j: :)groups}"
for group in "${groups[@]}"; do
  grep -Eq "^group_${group//-/_}\(\) \{$" "$script" ||
    fail "group $group has no function"
done
bash "$script" no-such-group >/dev/null 2>&1 && fail 'an unknown group must fail'

# GitHub Actions: platform-portability runs every group except zsh-deployment
# in its matrix, and zsh-deployment-portability runs zsh-deployment on each OS.
matrix=("${(@f)$(list_items "$portability" group)}")
[[ ${(j: :)matrix} == ${(j: :)groups[1,-2]} ]] ||
  fail "platform-portability.yml matrix groups: ${(j: :)matrix}"
(( $(count_runs "$portability" 'bash scripts/ci-test-group "$GROUP"') == 1 )) ||
  fail 'platform-portability.yml must run its matrix group in one step'
(( $(count_runs "$deployment" 'bash scripts/ci-test-group zsh-deployment') == 2 )) ||
  fail 'zsh-deployment-portability.yml must run zsh-deployment on macOS and Ubuntu'

# A test command added to a workflow directly would skip Buildkite and, in the
# platform matrix, run once per group.
for workflow in $portability $deployment; do
  stray=$(grep -En '(tests|scripts)/' "$workflow" | grep -Fv 'scripts/ci-test-group') &&
    fail "${workflow:t} runs a command outside scripts/ci-test-group:"$'\n'"$stray"
done

# Buildkite: the Linux and macOS matrices each run every group.
matrix=("${(@f)$(list_items "$buildkite" matrix)}")
[[ ${(j: :)matrix} == "${(j: :)groups} ${(j: :)groups}" ]] ||
  fail "Buildkite matrix groups: ${(j: :)matrix}"

print -r -- 'ci test group checks passed'
