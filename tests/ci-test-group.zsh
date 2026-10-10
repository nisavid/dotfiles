#!/usr/bin/env zsh
# Keep every CI definition running exactly the groups in scripts/ci-test-group,
# and keep test commands in the script rather than in the workflow.
#
# Both CI definitions are pinned below, apart from comments and blank lines.
# YAML can spell a skip, a condition, a soft fail, a block step, a container
# override or a different checkout many ways, so a pin is the one check that
# sees them all. When a CI definition changes on purpose, update its pin here
# and keep every invariant the pin's comment lists.
#
# These checks catch accidental and "temporary" changes, not deliberate evasion
# of the checks themselves, which review has to catch.
set -euo pipefail

repo_root=${0:A:h:h}
script=$repo_root/scripts/ci-test-group
portability=$repo_root/.github/workflows/platform-portability.yml
buildkite=$repo_root/.buildkite/pipeline.yml

fail() {
  print -ru2 -- "FAIL: $*"
  exit 1
}

# Print a CI file without comment lines or blank lines.
code_lines() {
  LC_ALL=C grep -Ev '^[[:space:]]*(#.*)?$' "$1" || true
}

# Fail unless a CI file's code lines equal its pin, showing the difference.
require_pin() {
  local file=$1 pin_name=$2 expected=$3 actual
  actual=$(code_lines "$file")
  [[ $actual == "$expected" ]] ||
    fail "${file#$repo_root/} differs from $pin_name in tests/ci-test-group.zsh. Keep the invariants listed there, then update the pin:"$'\n'"$(diff -u <(print -r -- "$expected") <(print -r -- "$actual") | tail -n +3)"
}

groups=("${(@f)$(bash "$script" --list)}")
[[ ${(j: :)groups} == 'shell-bindings proton-pass discover python-checks age-admission age-provisioning zsh-deployment' ]] ||
  fail "unexpected group list: ${(j: :)groups}"
for group in "${groups[@]}"; do
  grep -Eq "^group_${group//-/_}\(\) \{$" "$script" ||
    fail "group $group has no function"
done
bash "$script" no-such-group >/dev/null 2>&1 && fail 'an unknown group must fail'
# Matrix lines for the pins: one list item per group, in order.
workflow_groups=${(F)${(@)groups/#/          - }}
pipeline_groups=$workflow_groups

# The pins skip comment lines, but YAML also ends lines at CR, NEL, LS and PS,
# so such a character could hide live content inside a comment. The Buildkite
# pipeline must be printable ASCII. The workflow may hold other UTF-8, such as
# the job name's middle dot, but no control characters or line breaks other
# than LF. Offending lines are printed with cat -v, so the bytes show.
for ci_file in "$portability" "$buildkite"; do
  [[ -f $ci_file ]] || fail "${ci_file#$repo_root/} is missing"
done
hidden=$(LC_ALL=C grep -anv '^[ -~]*$' "$buildkite" | cat -v) || hidden=
[[ -z $hidden ]] ||
  fail "${buildkite#$repo_root/} must hold only printable ASCII lines:"$'\n'"$hidden"
hidden=$(LC_ALL=C grep -anE $'[\x01-\x09\x0b-\x1f\x7f]|\xc2\x85|\xe2\x80[\xa8\xa9]' "$portability" | cat -v) ||
  hidden=
[[ -z $hidden ]] ||
  fail "${portability#$repo_root/} must not hold control characters or line breaks other than LF:"$'\n'"$hidden"

# GitHub Actions pin. Invariants: each platform matrix lists every group with
# no exclude, include or condition; the checkout is the pull request's own,
# tested in place; the Run test group step runs bash scripts/ci-test-group with
# GROUP from matrix.group, under shell: bash with no BASH_ENV or defaults; no
# step continues on error; each named platform aggregate needs only its own
# matrix job, always runs, and fails unless that entire matrix succeeded.
expected_workflow=$(cat <<'PIN'
name: Platform portability
on:
  pull_request:
  push:
    branches:
      - main
  workflow_dispatch:
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
permissions:
  contents: read
env:
  AGE_VERSION: "1.3.1"
  CHEZMOI_VERSION: "2.71.0"
jobs:
  verify:
    name: macos-15 · ${{ matrix.group }}
    runs-on: macos-15
    timeout-minutes: 45
    strategy:
      fail-fast: false
      matrix:
        group:
@GROUPS@
    steps:
      - name: Check out source
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          persist-credentials: false
      - name: Select Python
        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97
        with:
          python-version: "3.12"
      - name: Install Python runtime dependencies
        shell: bash
        run: python3 -m pip install uv==0.11.32
      - name: Install macOS dependencies
        shell: bash
        env:
          HOMEBREW_NO_AUTO_UPDATE: "1"
          HOMEBREW_NO_INSTALL_UPGRADE: "1"
          HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK: "1"
        run: |
          set -euo pipefail
          brew install bat flock jq ripgrep
          case "$(uname -m)" in
            arm64)
              archive=chezmoi_${CHEZMOI_VERSION}_darwin_arm64.tar.gz
              digest=8b03d7be6b5d500a503c712ae6da7dd6817b6c3328223b4ae8be7a8be5a2fa3a
              age_archive=age-v${AGE_VERSION}-darwin-arm64.tar.gz
              age_digest=01120ea2cbf0463d4c6bd767f99f3271bbed1cdc8a9aa718a76ba1fe4f01998b
              ;;
            x86_64)
              archive=chezmoi_${CHEZMOI_VERSION}_darwin_amd64.tar.gz
              digest=12b78b365528597ad701f5117fa71f6c42b5b1e65d8075e19c48472ad81faf30
              age_archive=age-v${AGE_VERSION}-darwin-amd64.tar.gz
              age_digest=2b233301ad21ab7b1eabd9ae1198a164005fa4928fcdd745d47c39f8593209d7
              ;;
            *)
              printf 'unsupported macOS architecture: %s\n' "$(uname -m)" >&2
              exit 1
              ;;
          esac
          package="$RUNNER_TEMP/$archive"
          curl --fail --location --silent --show-error \
            --output "$package" \
            "https://github.com/twpayne/chezmoi/releases/download/v${CHEZMOI_VERSION}/$archive"
          printf '%s  %s\n' "$digest" "$package" | shasum -a 256 --check
          mkdir -p "$RUNNER_TEMP/chezmoi-bin"
          tar -xzf "$package" -C "$RUNNER_TEMP/chezmoi-bin" chezmoi
          age_package="$RUNNER_TEMP/$age_archive"
          curl --fail --location --silent --show-error \
            --output "$age_package" \
            "https://github.com/FiloSottile/age/releases/download/v${AGE_VERSION}/$age_archive"
          printf '%s  %s\n' "$age_digest" "$age_package" | shasum -a 256 --check
          {
            printf 'AGE_TOOLING_ARCHIVE=%s\n' "$age_package"
            printf 'AGE_TOOLING_ARCHIVE_SHA256=%s\n' "$age_digest"
          } >>"$GITHUB_ENV"
          tar -xzf "$age_package" -C "$RUNNER_TEMP"
          install -m 0755 \
            "$RUNNER_TEMP/age/age" \
            "$RUNNER_TEMP/age/age-keygen" \
            "$RUNNER_TEMP/age/age-inspect" \
            "$RUNNER_TEMP/chezmoi-bin"
          printf '%s\n' "$RUNNER_TEMP/chezmoi-bin" >>"$GITHUB_PATH"
      - name: Verify chezmoi version
        shell: bash
        run: chezmoi --version | grep -Fq "chezmoi version v${CHEZMOI_VERSION},"
      - name: Verify age parser version
        shell: bash
        run: |
          set -euo pipefail
          test "$(age --version)" = "v${AGE_VERSION}"
          test "$(age-inspect --version)" = "v${AGE_VERSION}"
      - name: Run test group
        shell: bash
        env:
          AGE_TOOLING_DIRECTORY: ${{ runner.temp }}/chezmoi-bin
          GROUP: ${{ matrix.group }}
        run: bash scripts/ci-test-group "$GROUP"
  verify-linux:
    name: ubuntu-24.04 · ${{ matrix.group }}
    runs-on: ubuntu-24.04
    timeout-minutes: 45
    strategy:
      fail-fast: false
      matrix:
        group:
@GROUPS@
    steps:
      - name: Check out source
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          persist-credentials: false
      - name: Select Python
        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97
        with:
          python-version: "3.12"
      - name: Install Linux dependencies
        shell: bash
        run: |
          set -euo pipefail
          sudo apt-get -qq update
          sudo apt-get -qq install -y --no-install-recommends \
            acl bat ca-certificates curl dbus-daemon dbus-tests gcc git jq libc6-dev \
            libglib2.0-bin openssh-client procps psmisc python3 ripgrep systemd util-linux zsh
          [[ -e /usr/local/bin/bat ]] || sudo ln -s /usr/bin/batcat /usr/local/bin/bat
          rclone_version=1.75.1
          rclone_archive=rclone-v${rclone_version}-linux-amd64.zip
          rclone_package="$RUNNER_TEMP/$rclone_archive"
          curl --fail --location --silent --show-error \
            --output "$rclone_package" \
            "https://downloads.rclone.org/v${rclone_version}/$rclone_archive"
          printf '%s  %s\n' \
            982b5aa772841168f8e380f139e9e787b2a105403e32b94da8676a0e1c0a13ab \
            "$rclone_package" | sha256sum --check
          python3 -m zipfile -e "$rclone_package" "$RUNNER_TEMP/rclone"
          sudo install -m 0755 \
            "$RUNNER_TEMP/rclone/rclone-v${rclone_version}-linux-amd64/rclone" /usr/bin/rclone
          rclone_output=$(/usr/bin/rclone version)
          test "${rclone_output%%$'\n'*}" = "rclone v1.75.1"
          archive=chezmoi_${CHEZMOI_VERSION}_linux_amd64.tar.gz
          package="$RUNNER_TEMP/$archive"
          curl --fail --location --silent --show-error \
            --output "$package" \
            "https://github.com/twpayne/chezmoi/releases/download/v${CHEZMOI_VERSION}/$archive"
          printf '%s  %s\n' \
            6ea2040ecc0e82d3dac604289e100b0157afefcd94ebb818e5f6e31655156d34 \
            "$package" | sha256sum --check
          mkdir -p "$RUNNER_TEMP/chezmoi-bin"
          tar -xzf "$package" -C "$RUNNER_TEMP/chezmoi-bin" chezmoi
          age_archive=age-v${AGE_VERSION}-linux-amd64.tar.gz
          age_digest=bdc69c09cbdd6cf8b1f333d372a1f58247b3a33146406333e30c0f26e8f51377
          age_package="$RUNNER_TEMP/$age_archive"
          curl --fail --location --silent --show-error \
            --output "$age_package" \
            "https://github.com/FiloSottile/age/releases/download/v${AGE_VERSION}/$age_archive"
          printf '%s  %s\n' \
            "$age_digest" \
            "$age_package" | sha256sum --check
          {
            printf 'AGE_TOOLING_ARCHIVE=%s\n' "$age_package"
            printf 'AGE_TOOLING_ARCHIVE_SHA256=%s\n' "$age_digest"
          } >>"$GITHUB_ENV"
          tar -xzf "$age_package" -C "$RUNNER_TEMP"
          install -m 0755 \
            "$RUNNER_TEMP/age/age" \
            "$RUNNER_TEMP/age/age-keygen" \
            "$RUNNER_TEMP/age/age-inspect" \
            "$RUNNER_TEMP/chezmoi-bin"
          printf '%s\n' "$RUNNER_TEMP/chezmoi-bin" >>"$GITHUB_PATH"
          uv_archive=uv-x86_64-unknown-linux-gnu.tar.gz
          uv_package="$RUNNER_TEMP/$uv_archive"
          curl --fail --location --silent --show-error \
            --output "$uv_package" \
            "https://github.com/astral-sh/uv/releases/download/0.11.32/$uv_archive"
          printf '%s  %s\n' \
            aab924fd522efd06f1c5f3b93a243864fc453132c94b2dc49f1371b528a4b967 \
            "$uv_package" | sha256sum --check
          tar -xzf "$uv_package" -C "$RUNNER_TEMP"
          install -m 0755 \
            "$RUNNER_TEMP/uv-x86_64-unknown-linux-gnu/uv" \
            "$RUNNER_TEMP/uv-x86_64-unknown-linux-gnu/uvx" \
            "$RUNNER_TEMP/chezmoi-bin"
      - name: Verify chezmoi version
        shell: bash
        run: chezmoi --version | grep -Fq "chezmoi version v${CHEZMOI_VERSION},"
      - name: Verify age parser version
        shell: bash
        run: |
          set -euo pipefail
          test "$(age --version)" = "v${AGE_VERSION}"
          test "$(age-inspect --version)" = "v${AGE_VERSION}"
      - name: Verify uv version
        shell: bash
        run: uv --version | grep -Eq '^uv 0\.11\.32( |$)'
      - name: Run test group
        shell: bash
        env:
          AGE_TOOLING_DIRECTORY: ${{ runner.temp }}/chezmoi-bin
          GROUP: ${{ matrix.group }}
        run: bash scripts/ci-test-group "$GROUP"
  linux-aggregate:
    name: linux portability
    if: always()
    needs:
      - verify-linux
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    steps:
      - name: Require every Linux group
        env:
          VERIFY_RESULT: ${{ needs.verify-linux.result }}
        run: test "$VERIFY_RESULT" = success
  aggregate:
    name: platform portability
    if: always()
    needs:
      - verify
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    steps:
      - name: Require every group
        env:
          VERIFY_RESULT: ${{ needs.verify.result }}
        run: test "$VERIFY_RESULT" = success
PIN
)
require_pin "$portability" 'the GitHub Actions pin' "${expected_workflow//@GROUPS@/$workflow_groups}"
# Branch protection matches the check by job name, so no job in another
# workflow may carry it.
workflows=("$repo_root"/.github/workflows/*.(yml|yaml)(N))
others=(${workflows:#$portability})
if (( ${#others} )); then
  names=$(grep -Ein '(platform|linux) portability' "${others[@]}" /dev/null |
    grep -Ev '^[^:]+:[0-9]+:[[:space:]]*#') || names=
  [[ -z $names ]] ||
    fail 'only platform-portability.yml may define the "platform portability" and "linux portability" checks:'$'\n'"$names"
fi

# Exercise the actual aggregate shell command with all Actions dependency
# results. A skipped or cancelled matrix must never become a passing gate.
for aggregate in aggregate linux-aggregate; do
  aggregate_command=$(awk -v job="  $aggregate:" '
    $0 == job { found = 1; next }
    found && /^  [^ ]/ { exit }
    found && /^        run: / { sub(/^        run: /, ""); print; exit }
  ' "$portability")
  [[ -n $aggregate_command ]] || fail "$aggregate has no aggregate command"
  for dependency_result in success failure cancelled skipped ''; do
    aggregate_status=0
    VERIFY_RESULT=$dependency_result bash -e -c "$aggregate_command" || aggregate_status=$?
    if [[ $dependency_result == success ]]; then
      (( aggregate_status == 0 )) || fail "$aggregate rejects a successful matrix"
    else
      (( aggregate_status != 0 )) || fail "$aggregate accepts matrix result '$dependency_result'"
    fi
  done
done

# Retained Buildkite source pin. This pipeline is archived and supplies no
# required check. These offline checks preserve its historical behavior:
# one Linux matrix runs every group through run-group.sh, with no skip,
# condition, soft fail, block, input or trigger step, and no container
# override; then the timing annotation runs.
expected_pipeline=$(cat <<'PIN'
steps:
  - group: ":linux: Ubuntu"
    key: linux
    steps:
      - label: ":linux: {{matrix}}"
        command: .buildkite/run-group.sh "{{matrix}}"
        agents:
          queue: linux-medium
        plugins:
          - docker#v5.14.0:
              image: "ubuntu:24.04"
              workdir: /work/dotfiles
              mount-buildkite-agent: true
        timeout_in_minutes: 25
        matrix:
@GROUPS@
        retry:
          automatic:
            - exit_status: -1
              limit: 2
  - label: ":stopwatch: Timings"
    depends_on:
      - linux
    allow_dependency_failure: true
    agents:
      queue: linux-small
    command: .buildkite/annotate-timings.sh
PIN
)
require_pin "$buildkite" 'the Buildkite pin' "${expected_pipeline/@GROUPS@/$pipeline_groups}"
# Repository hooks, symlinked files, or a step that uploads more pipeline
# would run outside the pin.
[[ ! -e $repo_root/.buildkite/hooks && ! -L $repo_root/.buildkite/hooks ]] ||
  fail 'the repository must not have Buildkite hooks'
links=$(find "$repo_root/.buildkite" -type l) || links=
[[ -z $links ]] || fail '.buildkite must not hold symlinks:'$'\n'"$links"
if uploads=$(grep -RIEn 'pipeline([[:space:]"'\''\\]|$)+upload|pipeline[[:space:]]*\\$' \
  "$repo_root/.buildkite" "$script"); then
  uploads=$(grep -Ev '^[^:]+:[0-9]+:[[:space:]]*#' <<<"$uploads") || uploads=
  [[ -z $uploads ]] || fail 'Buildkite steps must not upload pipeline steps:'$'\n'"$uploads"
elif (( $? > 1 )); then
  fail 'could not scan the Buildkite scripts for pipeline uploads'
fi

# Exercise the retained run-group.sh Linux path without provider access, as
# the docker plugin runs it: in a copy of the checkout, under a clean
# environment holding the plugin's Buildkite variables, with root-only
# provisioning stubbed, downloads blocked and a fake scripts/ci-test-group.
# Every group must run alone and exit with its own status. A failed apt-get, a
# failed download on a fresh agent, and a failed buildkite-agent must not turn
# a job green.
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
trap 'rm -rf -- "$scratch"; exit 1' HUP INT TERM
mkdir -p "$scratch/stubs" "$scratch/tools/bin" "$scratch/tools/venv/bin" "$scratch/job"
for stub in chown ln useradd; do
  print -r -- '#!/bin/sh' >"$scratch/stubs/$stub"
done
print -r -- '#!/bin/sh
case " $* " in *" ${GUARD_APT_FAILS:-none} "*) exit 100 ;; esac' >"$scratch/stubs/apt-get"
print -r -- '#!/bin/sh
[ -z "${GUARD_AGENT_FAILS:-}" ] || exit 1' >"$scratch/stubs/buildkite-agent"
print -r -- '#!/bin/sh
echo "curl must not run in this check: $*" >&2
exit 7' >"$scratch/stubs/curl"
print -r -- '#!/bin/sh
case "$1" in -m) echo x86_64 ;; *) echo Linux ;; esac' >"$scratch/stubs/uname"
# A cold agent has no CI user yet.
print -r -- '#!/bin/sh
if [ "$#" -eq 1 ] && [ "$1" = -u ]; then echo 0
elif [ -n "${GUARD_COLD:-}" ]; then exit 1
else echo 1000; fi' >"$scratch/stubs/id"
print -r -- '#!/bin/sh
while [ "$#" -gt 0 ] && [ "$1" != -- ]; do shift; done
shift
exec "$@"' >"$scratch/stubs/runuser"
chmod +x "$scratch"/stubs/*
for entry in "$repo_root"/*(DN); do
  [[ ${entry:t} == .git ]] || cp -pR "$entry" "$scratch/job/"
done
job_runner=$scratch/job/.buildkite/run-group.sh
runner_text=$(<$job_runner)
tools_line=$'\n      tools=/opt/dotfiles-ci\n'
tools_redirect=$'\n      tools='${(qq)scratch}$'/tools\n'
[[ $runner_text == *$tools_line* && $runner_text != *$tools_line*$tools_line* ]] ||
  fail '.buildkite/run-group.sh must keep the one line "      tools=/opt/dotfiles-ci", which this check redirects to a scratch directory'
print -r -- "${runner_text/$tools_line/$tools_redirect}" >"$job_runner"
[[ $(<$job_runner) == *$tools_redirect* ]] ||
  fail 'could not redirect .buildkite/run-group.sh to the scratch tools directory'
age_line=$(grep -E '^readonly AGE_VERSION=' "$job_runner") ||
  fail '.buildkite/run-group.sh must set readonly AGE_VERSION'
age_version=$(bash -c "$age_line"'; printf %s "$AGE_VERSION"') && [[ -n $age_version ]] ||
  fail ".buildkite/run-group.sh's AGE_VERSION line must set a version: $age_line"
warm_tools=("$scratch/tools/.installed" "$scratch/tools/age-v${age_version}-linux-amd64.tar.gz")
touch "${warm_tools[@]}"
run_job() {
  emulate -L zsh
  local group=$1 fake_status=$2
  print -r -- '#!/usr/bin/env bash
printf "%s\n" "$*" >>'"${(q)scratch}"'/ran
exit '"$fake_status" >"$scratch/job/scripts/ci-test-group"
  chmod +x "$scratch/job/scripts/ci-test-group"
  : >"$scratch/ran"
  run_status=0
  (cd "$scratch/job" && env -i PATH="$scratch/stubs:$PATH" HOME=/root \
    BUILDKITE_JOB_ID=guard BUILDKITE_BUILD_ID=guard BUILDKITE_AGENT_ACCESS_TOKEN=guard \
    BUILDKITE_AGENT_JOB_API_SOCKET=/nonexistent BUILDKITE_AGENT_JOB_API_TOKEN=guard \
    ${GUARD_APT_FAILS:+GUARD_APT_FAILS=$GUARD_APT_FAILS} \
    ${GUARD_AGENT_FAILS:+GUARD_AGENT_FAILS=1} ${GUARD_COLD:+GUARD_COLD=1} \
    sh -e -c '.buildkite/run-group.sh "$1"' sh "$group") >"$scratch/log" 2>&1 ||
    run_status=$?
}
job_log() { print -r -- "ran: $(<$scratch/ran)"$'\n'"$(tail -n 5 "$scratch/log")"; }
integer i=0
for group in "${groups[@]}"; do
  (( i += 1 ))
  # The first group gets every status; the others a shared, an own and 0.
  if (( i == 1 )); then statuses=({1..255} 0); else statuses=(1 $(( 10 + i )) 0); fi
  for fake_status in "${statuses[@]}"; do
    run_job "$group" "$fake_status"
    [[ $run_status == "$fake_status" && $(<$scratch/ran) == "$group" ]] ||
      fail ".buildkite/run-group.sh $group must run only that group and exit with its status: the group exited $fake_status and the job $run_status"$'\n'"$(job_log)"
  done
done
for GUARD_APT_FAILS in update install; do
  run_job zsh-deployment 0
  (( run_status != 0 )) ||
    fail ".buildkite/run-group.sh must fail when apt-get $GUARD_APT_FAILS fails"$'\n'"$(job_log)"
done
unset GUARD_APT_FAILS
# Real jobs start in a fresh container, with no tools and no CI user.
rm -f -- "${warm_tools[@]}"
GUARD_COLD=1
run_job zsh-deployment 0
unset GUARD_COLD
(( run_status != 0 )) && grep -q 'curl must not run' "$scratch/log" ||
  fail '.buildkite/run-group.sh must download its tools on a fresh agent and fail when a download fails'$'\n'"$(job_log)"
touch "${warm_tools[@]}"
GUARD_AGENT_FAILS=1
run_job zsh-deployment 1
unset GUARD_AGENT_FAILS
(( run_status == 1 )) ||
  fail ".buildkite/run-group.sh must keep a failed group's status when buildkite-agent fails: the job exited $run_status"$'\n'"$(job_log)"

print -r -- 'ci test group checks passed'
