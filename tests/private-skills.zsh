#!/usr/bin/env zsh
emulate -L zsh
setopt errexit nounset pipefail extended_glob

repo_root=${0:A:h:h}
identity=${HOME}/.config/age/key.txt
phase=$(mktemp -d "${TMPDIR:-/tmp}/private-skills-test.XXXXXX")
trap 'rm -rf -- "$phase"' EXIT HUP INT TERM
chmod 700 "$phase"

fail() {
  print -u2 -r -- "FAIL: $*"
  return 1
}

mode_of() {
  case "$(uname -s)" in
    Darwin) stat -f '%Lp' "$1" ;;
    Linux) stat -c '%a' -- "$1" ;;
    *) fail "unsupported test platform: $(uname -s)" ;;
  esac
}

frontmatter_field() {
  local field=$1 file=$2
  /usr/bin/awk -v field="$field" '
    NR > 1 && $0 == "---" { exit }
    $1 == field ":" {
      sub(/^[^:]*:[[:space:]]*/, "")
      print
      exit
    }
  ' "$file"
}

wrapper=$repo_root/home/run_onchange_after_restore-private-skills.sh.tmpl
rendered=$phase/wrapper
path_ciphers=("$repo_root"/home/.private-skill-*-path.age(N.))
(( ${#path_ciphers} )) || fail 'no encrypted private-skill pairs found'

typeset -A seen_names
for path_cipher in "${path_ciphers[@]}"; do
  stem=${path_cipher:t}
  number=${${stem#.private-skill-}%-path.age}
  body_cipher=$repo_root/home/.private-skill-$number-body.age
  [[ -f $body_cipher ]] || fail "pair $number has no encrypted body"

  path_plain=$phase/$number.path
  body_plain=$phase/$number.body
  age -d -i "$identity" -o "$path_plain" "$path_cipher" >/dev/null 2>&1 ||
    fail "pair $number path did not decrypt"
  age -d -i "$identity" -o "$body_plain" "$body_cipher" >/dev/null 2>&1 ||
    fail "pair $number body did not decrypt"
  chmod 600 "$path_plain" "$body_plain"

  [[ "$(mode_of "$path_plain")" == 600 ]] || fail "pair $number path mode is not 0600"
  [[ "$(mode_of "$body_plain")" == 600 ]] || fail "pair $number body mode is not 0600"

  skill_path=$(<"$path_plain")
  [[ $skill_path == [A-Za-z0-9][A-Za-z0-9_.-]# ]] ||
    fail "pair $number path is not one safe skill segment"
  (( ! ${+seen_names[$skill_path]} )) || fail "pair $number duplicates another skill path"
  seen_names[$skill_path]=1

  [[ "$(<"$body_plain")" == ---* ]] || fail "pair $number has no frontmatter"
  [[ "$(frontmatter_field name "$body_plain")" == "$skill_path" ]] ||
    fail "pair $number frontmatter name does not match its path"
  [[ -n "$(frontmatter_field description "$body_plain")" ]] ||
    fail "pair $number has no frontmatter description"

  /usr/bin/grep -Fq -- "${path_cipher:t}\" | sha256sum" "$wrapper" ||
    fail "wrapper does not hash pair $number path ciphertext"
  /usr/bin/grep -Fq -- "${body_cipher:t}\" | sha256sum" "$wrapper" ||
    fail "wrapper does not hash pair $number body ciphertext"
done

chezmoi -S "$repo_root/home" execute-template <"$wrapper" >"$rendered"
chmod 600 "$rendered"
/usr/bin/grep -Fq -- "$repo_root/scripts/private-skill-transaction" "$rendered" ||
  fail 'wrapper does not invoke the transaction helper'
/usr/bin/grep -Fq -- 'restore --identity' "$rendered" ||
  fail 'wrapper does not pass the configured age identity'
[[ $(/usr/bin/grep -c -- '--pair' "$wrapper") == ${#path_ciphers} ]] ||
  fail 'wrapper pair count does not match the encrypted source inventory'
! /usr/bin/grep -Fq -- '| decrypt' "$wrapper" ||
  fail 'wrapper still renders decrypted private content'

print -r -- 'private skill tests: PASS'
