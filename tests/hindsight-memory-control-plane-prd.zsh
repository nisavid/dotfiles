#!/usr/bin/env zsh
emulate -L zsh
setopt errexit nounset pipefail

repo_root=${0:A:h:h}
prd=$repo_root/docs/HINDSIGHT_MEMORY_CONTROL_PLANE_PRD.md
catalog=$repo_root/home/.private-prd-01.toml.age

fail() {
  print -u2 -r -- "hindsight memory control plane PRD: $*"
  return 1
}

[[ -f $prd ]] || fail 'public PRD is missing'
[[ -f $catalog ]] || fail 'encrypted private deployment catalog is missing'
/usr/bin/grep -Fq -- 'private deployment catalog' "$prd" || \
  fail 'public PRD does not define the private deployment-catalog seam'

if /usr/bin/grep -Eq -- '`(repo|project|workflow):[[:alnum:]][^`]*`' "$prd"; then
  fail 'public PRD contains a concrete deployment tag'
fi

if chezmoi --source "$repo_root/home" managed | /usr/bin/grep -Fq -- '.private-prd-01.toml.age'; then
  fail 'encrypted deployment catalog unexpectedly has a managed plaintext target'
fi

print -r -- 'hindsight memory control plane PRD: public contract PASS'
