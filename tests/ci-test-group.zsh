#!/usr/bin/env zsh
# Keep every CI definition running exactly the groups in scripts/ci-test-group,
# and keep test commands in the script rather than in the workflow.
set -euo pipefail

repo_root=${0:A:h:h}
script=$repo_root/scripts/ci-test-group
portability=$repo_root/.github/workflows/platform-portability.yml
buildkite=$repo_root/.buildkite/pipeline.yml

fail() {
  print -ru2 -- "FAIL: $*"
  exit 1
}

# Print the items of each `<key>:` block list in a YAML file (- for stdin), in order.
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

# Print each workflow job, id line first, that has a line reading exactly this
# text once its indentation is removed.
job_with() {
  emulate -L zsh
  awk -v text="$2" '
    function flush() { if (found) printf "%s", job; job = ""; found = 0 }
    /^[^[:space:]]/ { flush(); in_jobs = ($0 == "jobs:"); next }
    !in_jobs { next }
    /^  [^[:space:]]/ { flush() }
    { job = job $0 "\n"; line = $0; sub(/^ +/, "", line); if (line == text) found = 1 }
    END { flush() }
  ' "$1"
}

groups=("${(@f)$(bash "$script" --list)}")
[[ ${(j: :)groups} == 'shell-bindings proton-pass discover python-checks age-admission age-provisioning zsh-deployment' ]] ||
  fail "unexpected group list: ${(j: :)groups}"
for group in "${groups[@]}"; do
  grep -Eq "^group_${group//-/_}\(\) \{$" "$script" ||
    fail "group $group has no function"
done
bash "$script" no-such-group >/dev/null 2>&1 && fail 'an unknown group must fail'

# GitHub Actions: platform-portability runs every group in one macOS matrix
# job, and an aggregate job reports that job's result as one check.
matrix=("${(@f)$(list_items "$portability" group)}")
[[ ${(j: :)matrix} == ${(j: :)groups} ]] ||
  fail "platform-portability.yml matrix groups: ${(j: :)matrix}"
(( $(count_runs "$portability" 'bash scripts/ci-test-group "$GROUP"') == 1 )) ||
  fail 'platform-portability.yml must run its matrix group in one step'
matrix_job=$(job_with "$portability" 'run: bash scripts/ci-test-group "$GROUP"')
matrix_job_id=${${matrix_job%%:*}// /}
[[ $matrix_job == *$'\n    runs-on: macos-'<->$'\n'* ]] ||
  fail 'platform-portability.yml must run its matrix job on macOS only'
# A matrix exclude or include, or a condition, could drop a listed group.
grep -Eq '^[[:space:]]*(- )?(exclude|include|if):' <<<"$matrix_job" &&
  fail "the $matrix_job_id job must run every listed group, without exclude, include or if"

# Branch protection requires this check name. A skipped required check passes,
# so the aggregate must run and fail whenever the matrix job does not succeed.
aggregate=$(job_with "$portability" 'name: platform portability')
[[ -n $aggregate ]] ||
  fail 'platform-portability.yml has no "platform portability" job'
needs=("${(@f)$(print -r -- "$aggregate" | list_items - needs)}")
[[ ${(j: :)needs} == "$matrix_job_id" ]] ||
  fail "the aggregate job must need only $matrix_job_id, not: ${(j: :)needs}"
[[ $aggregate == *$'\n    if: always()\n'* ]] ||
  fail 'the aggregate job must run even when the matrix job fails'
[[ $aggregate == *$'\n    steps:\n      - name: Require every group\n        env:\n          VERIFY_RESULT: ${{ needs.'$matrix_job_id$'.result }}\n        run: test "$VERIFY_RESULT" = success' ]] ||
  fail "the aggregate job's only step must require needs.$matrix_job_id.result to be success"
# continue-on-error would let a failure pass.
grep -Eq '^[[:space:]]*(- )?continue-on-error:' "$portability" &&
  fail "${portability:t} must not use continue-on-error"

# A test command added to the workflow directly would skip Buildkite and run
# once per group. Only comments and the group step may name tests or scripts.
stray=$(grep -En '(tests|scripts)[./]|unittest|pytest' "$portability" |
  grep -Ev '^[0-9]+:[[:space:]]*(#|run: bash scripts/ci-test-group "\$GROUP"$)') &&
  fail "${portability:t} runs a command outside scripts/ci-test-group:"$'\n'"$stray"

# Buildkite: one Linux matrix runs every group, and no step runs on macOS.
(( $(grep -Ec '^[[:space:]]*matrix:' "$buildkite") == 1 )) ||
  fail 'the Buildkite pipeline must have exactly one matrix'
matrix=("${(@f)$(list_items "$buildkite" matrix)}")
[[ ${(j: :)matrix} == ${(j: :)groups} ]] ||
  fail "Buildkite matrix groups: ${(j: :)matrix}"
(( $(grep -c 'run-group\.sh' "$buildkite") == 1 )) &&
  [[ $(<$buildkite) == *$'\n        command: .buildkite/run-group.sh "{{matrix}}"\n        agents:\n          queue: linux-'* ]] ||
  fail 'only the Buildkite matrix step may run .buildkite/run-group.sh, with "{{matrix}}" on a linux- queue'
queues=$(grep -En '^[[:space:]]*queue:' "$buildkite" | grep -Ev '^[0-9]+:[[:space:]]*queue: linux-') &&
  fail "every Buildkite step must run on a linux- queue:"$'\n'"$queues"
# Buildkite has no aggregate job, so a skipped, filtered or soft-failing step
# would leave buildkite/dotfiles green without running the groups.
skips=$(grep -En '^[[:space:]]*(- )?(skip|if|if_changed|branches|soft_fail):' "$buildkite") &&
  fail "the Buildkite pipeline must not skip, filter or soft-fail a step:"$'\n'"$skips"

print -r -- 'ci test group checks passed'
