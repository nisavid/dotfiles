# Representation-neutral path, snapshot, and encrypted-recovery primitives.

die() {
  printf 'private-skill-transaction: %s\n' "$*" >&2
  exit 1
}

mode_of() {
  /usr/bin/stat -f '%Lp' "$1"
}

identity_of() {
  /usr/bin/stat -f '%i' "$1"
}

state_root() {
  printf '%s\n' "${XDG_STATE_HOME:-$HOME/.local/state}/chezmoi/private-skill-transaction"
}

ensure_lock() {
  local root parent lock before after parent_before
  root=$(state_root)
  parent=${root%/*}
  if [[ ! -e $parent ]]; then /bin/mkdir -m 700 -p "$parent"; fi
  [[ -d $parent && ! -L $parent && $(mode_of "$parent") == 700 ]] ||
    die 'lock parent must have mode 0700'
  if [[ ! -e $root ]]; then /bin/mkdir -m 700 "$root"; fi
  [[ -d $root && ! -L $root && $(mode_of "$root") == 700 ]] ||
    die 'state directory must have mode 0700'
  parent_before=$(identity_of "$root")
  lock=$root/lock
  if [[ ! -e $lock ]]; then
    (umask 077; set -o noclobber; : >"$lock") 2>/dev/null || true
  fi
  [[ -f $lock && ! -L $lock ]] || die 'lock must be a regular file'
  [[ $(mode_of "$lock") == 600 ]] || die 'lock must have mode 0600'
  before=$(identity_of "$lock")
  exec 9<>"$lock"
  after=$(/usr/bin/stat -Lf '%i' /dev/fd/9)
  [[ $before == "$after" ]] || die 'lock descriptor identity changed'
  [[ $(mode_of "$root") == 700 && $(identity_of "$root") == "$parent_before" &&
     $(identity_of "$lock") == "$before" ]] ||
    die 'lock parent or file changed during open'
  /usr/bin/lockf -s -t 0 9 || die 'another private-skill transaction is active'
}

opaque_token() {
  if command -v uuidgen >/dev/null 2>&1; then
    uuidgen | /usr/bin/tr '[:upper:]' '[:lower:]'
  else
    printf '%s-%s-%s\n' "$$" "$RANDOM" "$(/bin/date +%s)"
  fi
}

sha256_file() {
  /usr/bin/shasum -a 256 "$1" | /usr/bin/awk '{print $1}'
}

sync_boundary() {
  /bin/sync
}

write_pointer() {
  local recovery=$1 table_digest=$2 state=$3 new_digest=${4:--} temporary
  temporary=$recovery/.pointer.$$
  printf 'version=1\ntable=%s\nnew=%s\nstate=%s\n' \
    "$table_digest" "$new_digest" "$state" >"$temporary"
  /bin/chmod 600 "$temporary"
  /bin/mv -f "$temporary" "$recovery/pointer"
  sync_boundary
}

cleanup_orphan_prepublication_phases() {
  local root phase
  root=$(state_root)
  while IFS= read -r -d '' phase; do
    [[ -d $phase && ! -L $phase && $(mode_of "$phase") == 700 ]] ||
      die 'orphan phase directory is not a validated private directory'
    /bin/rm -rf "$phase"
  done < <(/usr/bin/find "$root" -maxdepth 1 -type d -name 'phase.*' -print0)
  sync_boundary
}

discard_plaintext_then_recovery() {
  local phase=$1 recovery=$2
  /bin/rm -rf "$phase"
  sync_boundary
  /bin/rm -rf "$recovery"
  sync_boundary
}

validate_relative_target() {
  local rel=$1 part
  [[ -n $rel && $rel != /* && $rel != */ && $rel != *//* ]] || return 1
  [[ ! $rel =~ [[:cntrl:]] ]] || return 1
  IFS=/ read -r -a parts <<<"$rel"
  for part in "${parts[@]}"; do
    [[ -n $part && $part != . && $part != .. ]] || return 1
  done
  return 0
}

assert_no_symlink_ancestor() {
  local target=$1 relative current part
  [[ $target == /* ]] || die 'target path is not absolute'
  relative=${target#/}; current=
  IFS=/ read -r -a parts <<<"$relative"
  for ((part=0; part<${#parts[@]}-1; part++)); do
    current=$current/${parts[part]}
    [[ -L $current ]] && die "target has a symlink ancestor: $target"
    [[ ! -e $current ]] && return 0
    [[ -d $current ]] || die "target has a non-directory ancestor: $target"
  done
}

snapshot_target() {
  local target=$1 index=$2 snapshot=$3 type mode link='-' hash='-'
  if [[ -L $target ]]; then
    type=link; mode=$(/usr/bin/stat -f '%Lp' "$target"); link=$(/usr/bin/readlink "$target")
  elif [[ -f $target ]]; then
    type=file; mode=$(mode_of "$target"); hash=$(sha256_file "$target")
    /bin/cp -p "$target" "$snapshot/item.$index"
  elif [[ -d $target ]]; then
    type=dir; mode=$(mode_of "$target")
    validate_snapshot_tree "$target" || die 'directory snapshot contains an unsupported node type'
    /usr/bin/tar -cf "$snapshot/item.$index.tar" -C "$target" .
  elif [[ -e $target ]]; then
    die "unsupported live target type"
  else
    type=absent; mode=-
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$index" "$target" "$type" "$mode" "$link" "$hash" >>"$snapshot/manifest"
}

validate_snapshot_tree() {
  local root=$1 entry
  while IFS= read -r -d '' entry; do
    [[ -L $entry || -f $entry || -d $entry ]] || return 1
  done < <(/usr/bin/find "$root" -mindepth 1 -print0)
}

encrypt_directory() {
  local directory=$1 output=$2 recipient=$3 archive
  archive=$directory.tar
  /usr/bin/tar -cf "$archive" -C "$directory" .
  /bin/chmod 600 "$archive"
  age -r "$recipient" -o "$output" "$archive"
  /bin/chmod 600 "$output"
  /bin/rm -f "$archive"
}

extract_internal_snapshot() {
  local archive=$1 destination=$2
  (umask 000; /usr/bin/tar -xpf "$archive" -C "$destination")
}

old_state_matches() {
  local old=$1 index=$2 target=$3 record type mode link hash compare scratch
  record=$(/usr/bin/awk -F '\t' -v i="$index" '$1 == i { print; exit }' "$old/manifest")
  IFS=$'\t' read -r _ _ type mode link hash <<<"$record"
  case $type in
    absent) [[ ! -e $target && ! -L $target ]] ;;
    link) [[ -L $target && $(/usr/bin/readlink "$target") == "$link" ]] ;;
    file) [[ -f $target && ! -L $target && $(mode_of "$target") == "$mode" && $(sha256_file "$target") == "$hash" ]] ;;
    dir)
      [[ -d $target && ! -L $target && $(mode_of "$target") == "$mode" ]] || return 1
      compare=$old/compare.$index
      scratch=$old/tree-scratch.$index
      /bin/mkdir -m 700 "$compare" "$scratch"
      extract_internal_snapshot "$old/item.$index.tar" "$compare"
      tree_metadata_matches "$compare" "$target" "$scratch"
      local result=$?
      /bin/rm -rf "$compare" "$scratch"
      return $result
      ;;
    *) return 1 ;;
  esac
}

tree_metadata_matches() {
  local left=$1 right=$2 scratch=$3 listing_left listing_right rel left_path right_path
  listing_left=$scratch/left
  listing_right=$scratch/right
  (cd "$left" && /usr/bin/find . | LC_ALL=C /usr/bin/sort) >"$listing_left"
  (cd "$right" && /usr/bin/find . | LC_ALL=C /usr/bin/sort) >"$listing_right"
  /usr/bin/cmp -s "$listing_left" "$listing_right" || return 1
  while IFS= read -r rel; do
    [[ $rel == . ]] && continue
    left_path=$left/${rel#./}; right_path=$right/${rel#./}
    if [[ -L $left_path ]]; then
      [[ -L $right_path && $(/usr/bin/readlink "$left_path") == $(/usr/bin/readlink "$right_path") ]] || return 1
    elif [[ -d $left_path ]]; then
      [[ -d $right_path && ! -L $right_path && $(mode_of "$left_path") == $(mode_of "$right_path") ]] || return 1
    elif [[ -f $left_path ]]; then
      [[ -f $right_path && ! -L $right_path && $(mode_of "$left_path") == $(mode_of "$right_path") &&
         $(sha256_file "$left_path") == $(sha256_file "$right_path") ]] || return 1
    else
      return 1
    fi
  done <"$listing_left"
}

restore_old_entry() {
  local old=$1 index=$2 target=$3 record type mode link hash
  record=$(/usr/bin/awk -F '\t' -v i="$index" '$1 == i { print; exit }' "$old/manifest")
  IFS=$'\t' read -r _ _ type mode link hash <<<"$record"
  case $type in
    absent) ;;
    dir)
      /bin/mkdir -p "$target"
      extract_internal_snapshot "$old/item.$index.tar" "$target"
      /bin/chmod "$mode" "$target"
      ;;
    file)
      /bin/mkdir -p "${target%/*}"
      /bin/cp "$old/item.$index" "$target"
      /bin/chmod "$mode" "$target"
      ;;
    link)
      /bin/mkdir -p "${target%/*}"
      /bin/ln -s "$link" "$target"
      ;;
  esac
}
