#!/usr/bin/env zsh
emulate -L zsh
setopt errexit nounset pipefail

repo_root=${0:A:h:h}
identity=${HOME}/.config/age/key.txt
phase=$(mktemp -d "${TMPDIR:-/tmp}/private-skills-test.XXXXXX")
trap 'rm -rf -- "$phase"' EXIT HUP INT TERM
chmod 700 "$phase"

fail() {
  print -u2 -r -- "FAIL: $*"
  return 1
}

assert_contains() {
  local file=$1 text=$2 label=$3
  /usr/bin/grep -Fq -- "$text" "$file" || fail "$label"
}

assert_not_contains() {
  local file=$1 text=$2 label=$3
  ! /usr/bin/grep -Fq -- "$text" "$file" || fail "$label"
}

decrypt_pair() {
  local number=$1
  age -d -i "$identity" -o "$phase/$number.path" \
    "$repo_root/home/.private-skill-$number-path.age" >/dev/null 2>&1 || fail "pair $number path did not decrypt"
  age -d -i "$identity" -o "$phase/$number.body" \
    "$repo_root/home/.private-skill-$number-body.age" >/dev/null 2>&1 || fail "pair $number body did not decrypt"
  chmod 600 "$phase/$number.path" "$phase/$number.body"
}

validate_skill() {
  local number=$1 expected_path=$2 expected_name body
  expected_name=${expected_path:t}
  body=$phase/$number.body
  [[ "$(<"$phase/$number.path")" == "$expected_path" ]] || fail "pair $number path is wrong"
  [[ "$(stat -f '%Lp' "$phase/$number.path")" == 600 ]] || fail "pair $number path plaintext mode is not 0600"
  [[ "$(stat -f '%Lp' "$body")" == 600 ]] || fail "pair $number body plaintext mode is not 0600"
  [[ "$(sed -n '1p' "$body")" == --- ]] || fail "pair $number has no opening frontmatter delimiter"
  [[ "$(awk 'NR > 1 && $0 == "---" { exit } $1 == "name:" { print $2; exit }' "$body")" == "$expected_name" ]] ||
    fail "pair $number frontmatter name does not match its path"
}

frontmatter_description() {
  /usr/bin/awk 'NR > 1 && $0 == "---" { exit } $1 == "description:" { sub(/^[^:]*:[[:space:]]*/, ""); print; exit }' "$1"
}

test_neutral_encrypted_layout_and_wrapper() {
  local wrapper=$repo_root/home/run_onchange_after_restore-private-skills.sh.tmpl rendered=$phase/wrapper number kind
  for number in 01 02; do
    for kind in path body; do
      [[ -f $repo_root/home/.private-skill-$number-$kind.age ]] || fail "neutral pair $number $kind is missing"
      assert_contains "$wrapper" ".private-skill-$number-$kind.age\" | sha256sum" \
        "wrapper does not hash pair $number $kind for onchange detection"
    done
  done
  [[ ! -e $repo_root/home/.private-skill-path.age ]] || fail 'legacy private path ciphertext remains'
  [[ ! -e $repo_root/home/.private-worktrees-skill.md.age ]] || fail 'legacy private body ciphertext remains'
  chezmoi execute-template <"$wrapper" >"$rendered"
  chmod 600 "$rendered"
  assert_contains "$rendered" "$repo_root/scripts/private-skill-transaction" 'wrapper does not invoke the repository transaction helper'
  assert_contains "$rendered" 'restore --identity' 'wrapper does not pass the configured age identity'
  [[ $(/usr/bin/grep -c -- '--pair' "$wrapper") == 2 ]] || fail 'wrapper does not pass exactly two path/body pairs'
  assert_not_contains "$wrapper" '| decrypt' 'wrapper still renders decrypted private content'
}

test_worktree_pressure_scenarios() {
  local body=$phase/01.body
  validate_skill 01 working-in-systalyze-worktrees
  assert_contains "$body" \
    'Own target checkout discovery, target-mode selection, preservation and safety boundaries, local-cluster-role routing, and keeping local development scaffolding out of pushed product history.' \
    'worktree skill does not own the complete worktree responsibility boundary'
  assert_contains "$body" \
    'Current repo-local AGENTS files, development skills, manifests, scripts, and CI own exact package runners, setup commands, branch topology, and verification breadth.' \
    'worktree skill does not assign exact operational policy to current repo-local sources'
  assert_contains "$body" 'dynamically inspect the current branch and worktree state' 'worktree skill does not require live state inspection'
  assert_contains "$body" 'Current repository evidence takes precedence over frozen global guidance' \
    'frozen-global versus current-repository conflict has the wrong precedence'
  assert_contains "$body" 'stop before consequential mutation' 'ambiguous precedence does not stop consequential mutation'
  assert_contains "$body" 'Do not freeze branch stacks, package runners, gitlink handling, or universal smoke commands' \
    'worktree skill retains frozen implementation assumptions'
}

test_site_publication_pressure_scenarios() {
  local body=$phase/02.body description
  validate_skill 02 publishing-systalyze-sites
  description=$(frontmatter_description "$body")
  [[ $description == 'Use when Here.now publication is explicitly authorized AND the audience is explicitly Systalyze-internal.' ]] ||
    fail 'site skill frontmatter is not a trigger-only conjunctive description'
  assert_contains "$body" 'Set the site password to `stlz`' 'site skill does not own the internal password'
  assert_contains "$body" 'Use the Systalyze product visual language' 'site skill does not own the product visual language'
  assert_contains "$body" 'provide color-scheme-aware themes' 'site skill does not own color-scheme-aware themes'
  assert_contains "$body" 'Public Here.now publication does not trigger this skill' 'public Here.now incorrectly triggers the extension'
  assert_contains "$body" 'A local-only presentation of four or more captures does not trigger this skill.' \
    'local-only multi-capture scenario is not a single bound non-trigger statement'
  assert_contains "$body" 'extends the upstream `here-now` skill without modifying it' 'upstream extension boundary is absent'
  assert_contains "$body" 'shared password is not proof of audience authorization and is not stronger access control' \
    'password is conflated with audience authorization or access control'
  assert_contains "$body" 'Generic capture count and sizing policy stays outside this skill' \
    'generic capture policy leaked into the private extension'
}

test_neutral_encrypted_layout_and_wrapper
decrypt_pair 01
decrypt_pair 02
test_worktree_pressure_scenarios
test_site_publication_pressure_scenarios
print -r -- 'private skill tests: PASS'
