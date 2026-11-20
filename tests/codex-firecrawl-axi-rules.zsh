#!/usr/bin/env zsh
# Check the Codex exec-policy rules for firecrawl-axi (docs/SECRET_INJECTION.md,
# "Codex exec-policy rule for firecrawl-axi"). The file must land at the
# deployed path, hold no home path or credential, and give the intended
# decision for each command line when Codex itself evaluates it.
#
# The decision checks run `codex execpolicy check`, once as it is and once with
# --resolve-host-executables, the mode Codex itself uses. They are skipped, with
# a message, when CODEX_BIN is unset and no codex binary is found. CODEX_BIN names
# one explicitly, and the test fails when it is not executable. Otherwise the
# first `codex` on PATH outside a secret-exec shim directory is used, so the
# check never launches the shim and its provider lookup.
set -euo pipefail

repo_root=${0:A:h:h}
rules_source=$repo_root/home/dot_codex/rules/firecrawl-axi.rules

# exit, not return: errexit inside a function skips zsh's EXIT trap.
fail() {
  print -u2 -r -- "FAIL: $1"
  exit 1
}

# macOS ends TMPDIR with a slash. Strip it, so the scratch paths below hold no
# doubled slash and compare equal to the normalized paths chezmoi prints.
tmp_root=${TMPDIR:-/tmp}
tmp_root=${tmp_root%/}
test_dir=$(mktemp -d "$tmp_root/codex-firecrawl-axi-rules.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT

# zsh skips EXIT traps when errexit fires inside a function.
TRAPZERR() {
  if [[ -o errexit ]] && (( ZSH_SUBSHELL == 0 && ${#funcstack} > 1 )); then
    rm -rf -- "$test_dir"
  fi
}

[[ -f $rules_source && ! -L $rules_source ]] ||
  fail 'the rules file is missing from the chezmoi source'

# The file names no path under a home folder and holds no credential.
if LC_ALL=C grep -Eiq '(/home/|/Users/|~/|\$HOME|\$\{HOME\}|api[_-]?key|token|password|secret_(key|token|access)|fc-[A-Za-z0-9]{8,})' "$rules_source"; then
  fail 'the rules file must name no home path and no credential'
fi

# The source path deploys the file, with the same bytes, to the rules folder of
# Codex's home. Rendering uses a scratch destination, never the real home.
destination=$test_dir/destination
mkdir -p -- "$destination"
expected_target=$destination/.codex/rules/firecrawl-axi.rules
actual_target=$(chezmoi -S "$repo_root/home" -D "$destination" target-path "$rules_source")
[[ ${actual_target:A} == ${expected_target:A} ]] ||
  fail "the rules file deploys to $actual_target, not $expected_target"
chezmoi -S "$repo_root/home" -D "$destination" cat "$expected_target" > "$test_dir/rendered.rules"
cmp -s -- "$rules_source" "$test_dir/rendered.rules" ||
  fail 'the deployed rules file differs from the source'

# Codex's own rules file is not managed.
[[ ! -e $repo_root/home/dot_codex/rules/default.rules ]] ||
  fail 'default.rules belongs to Codex and must not be managed'

codex_bin=${CODEX_BIN:-}
if [[ -n $codex_bin ]]; then
  [[ -f $codex_bin && -x $codex_bin ]] ||
    fail "CODEX_BIN is set but is not an executable file: $codex_bin"
else
  for dir in $path; do
    dir=${dir%/}
    [[ $dir == */secret-exec/bin ]] && continue
    if [[ -x $dir/codex && ! -d $dir/codex ]]; then
      codex_bin=$dir/codex
      break
    fi
  done
fi
if [[ -z $codex_bin ]]; then
  print -r -- 'SKIP: codex is unavailable, so the exec-policy decisions were not checked (set CODEX_BIN to a codex binary).'
  print -r -- 'PASS: codex-firecrawl-axi-rules (source and deployment checks only)'
  exit 0
fi

# Extra options for `codex execpolicy check`, set for each pass below.
typeset -a check_options=()

# Print the strictest decision Codex gives the command line: allow, prompt,
# forbidden, or none when no rule matches. Loading the file also makes Codex
# validate its match and not_match examples, so a bad example fails here.
decision_for() {
  local output
  output=$("$codex_bin" execpolicy check $check_options --rules "$rules_source" "$@") ||
    fail "codex execpolicy check ${check_options[*]} failed for: $*"
  print -r -- "$output" | jq -er '.decision // "none"' ||
    fail "codex printed no decision for: $*"
}

expect() {
  local want=$1 got
  shift
  got=$(decision_for "$@")
  [[ $got == "$want" ]] || fail "expected $want, got $got, for (${check_options[*]:-default mode}): $*"
}

# This list is kept apart from the one in the rules file, as an independent
# oracle for it.
subcommands=(search scrape map crawl dev-search github-search papers agent monitors)

check_decisions() {
  # Each of the nine subcommands is allowed, bare and after the explicit
  # prefix, with and without arguments.
  for subcommand in $subcommands; do
    expect allow firecrawl-axi $subcommand
    expect allow firecrawl-axi $subcommand example --limit 3
    expect allow secret-exec firecrawl -- firecrawl-axi $subcommand
    expect allow secret-exec firecrawl -- firecrawl-axi $subcommand https://example.com
  done

  # The named cases from the rule's description.
  expect allow firecrawl-axi search example
  expect allow secret-exec firecrawl -- firecrawl-axi search example
  expect none firecrawl-axi parse file.pdf
  expect none secret-exec firecrawl -- firecrawl-axi parse file.pdf
  expect prompt firecrawl-axi setup hooks
  expect prompt firecrawl-axi setup status
  expect prompt secret-exec firecrawl -- firecrawl-axi setup hooks
  expect none secret-exec firecrawl -- sh
  expect none secret-exec firecrawl -- sh -c 'firecrawl-axi search example'
  expect none secret-exec github -- gh auth status
  expect none secret-exec github -- firecrawl-axi search example

  # Anything else about the program stays outside the rule.
  expect none firecrawl-axi
  expect none firecrawl-axi --help
  expect none firecrawl-axi searches example
  expect none sh -c 'firecrawl-axi search example'

  # A program of that name given by a path stays outside the rules. The host
  # executable lines make Codex's basename fallback skip such a program.
  local program
  for program in /usr/local/bin/firecrawl-axi ./firecrawl-axi workspace/bin/firecrawl-axi; do
    expect none $program search example
    expect none $program parse file.pdf
    expect none $program setup hooks
  done
  for program in /usr/local/bin/secret-exec ./secret-exec workspace/bin/secret-exec; do
    expect none $program firecrawl -- firecrawl-axi search example
    expect none $program firecrawl -- firecrawl-axi setup hooks
  done
}

# Codex core evaluates commands with host executable resolution, so that mode
# matters most. The default mode must agree with it.
check_options=()
check_decisions
check_options=(--resolve-host-executables)
check_decisions

print -r -- 'PASS: codex-firecrawl-axi-rules'
