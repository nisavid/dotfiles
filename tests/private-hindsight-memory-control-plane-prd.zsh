#!/usr/bin/env zsh
emulate -L zsh
setopt errexit nounset pipefail
umask 077

repo_root=${0:A:h:h}
catalog=$repo_root/home/.private-prd-01.toml.age
prd=$repo_root/docs/HINDSIGHT_MEMORY_CONTROL_PLANE_PRD.md
encryption_doc=$repo_root/docs/ENCRYPTION.md
validator=$repo_root/tests/hindsight_memory_control_plane_prd_validation.py
identity=$HOME/.config/age/key.txt
publication_base=${PUBLICATION_BASE_REF:-origin/main}
phase=$(mktemp -d "${TMPDIR:-/tmp}/private-hindsight-prd-test.XXXXXX")
plaintext=$phase/catalog.toml
trap 'rm -rf -- "$phase"' EXIT HUP INT TERM

fail() {
  print -u2 -r -- "private hindsight memory control plane PRD: $*"
  return 1
}

[[ $(stat -f '%Lp' "$phase") == 700 ]] || fail 'private validation phase mode is not 0700'
[[ -f $catalog ]] || fail 'encrypted deployment catalog is missing'
[[ -f $identity ]] || fail 'age identity is missing'
[[ $(stat -f '%Lp' "$identity") == 600 ]] || fail 'age identity mode is not 0600'
[[ $(head -n 1 "$catalog") == 'age-encryption.org/v1' ]] || fail 'catalog is not age ciphertext'
/usr/bin/grep -Fq -- '.private-prd-01.toml.age' "$encryption_doc" || \
  fail 'encryption documentation does not identify the private catalog'
/usr/bin/grep -Fq -- 'plaintext private partial, deployment catalog' "$encryption_doc" || \
  fail 'source-tree plaintext prohibition omits deployment catalogs'

age -d -i "$identity" -o "$plaintext" "$catalog" >/dev/null 2>&1 || \
  fail 'catalog did not decrypt'
[[ $(stat -f '%Lp' "$plaintext") == 600 ]] || fail 'decrypted catalog mode is not 0600'

python3 "$validator" "$plaintext" "$prd" "$repo_root" "$publication_base"

print -r -- 'private hindsight memory control plane PRD: catalog PASS'
