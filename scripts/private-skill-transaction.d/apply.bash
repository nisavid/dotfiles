# Outer apply table, projection, matching, and rollback operations.

restore_old_directories() {
  local old=$1 table=$2 count i kind target stage record type mode
  count=$(/usr/bin/awk 'END { print NR }' "$table/operations")
  for ((i=2; i<=count; i++)); do
    IFS=$'\t' read -r kind target stage <<<"$(/usr/bin/awk -F '\t' -v i="$i" 'NR == i { print; exit }' "$table/operations")"
    [[ $kind == target ]] || continue
    record=$(/usr/bin/awk -F '\t' -v i="$i" '$1 == i { print; exit }' "$old/manifest")
    IFS=$'\t' read -r _ _ type mode _ _ <<<"$record"
    [[ $type == dir ]] || continue
    assert_no_symlink_ancestor "$target"
    /bin/mkdir "$target"
    /bin/chmod 700 "$target"
    extract_internal_snapshot "$old/item.$i.tar" "$target"
    /bin/chmod 700 "$target"
  done
}

restore_old_nondirectories() {
  local old=$1 table=$2 count i kind target stage record type
  count=$(/usr/bin/awk 'END { print NR }' "$table/operations")
  for ((i=2; i<=count; i++)); do
    IFS=$'\t' read -r kind target stage <<<"$(/usr/bin/awk -F '\t' -v i="$i" 'NR == i { print; exit }' "$table/operations")"
    [[ $kind == target ]] || continue
    record=$(/usr/bin/awk -F '\t' -v i="$i" '$1 == i { print; exit }' "$old/manifest")
    IFS=$'\t' read -r _ _ type _ _ _ <<<"$record"
    [[ $type == file || $type == link ]] || continue
    assert_no_symlink_ancestor "$target"
    restore_old_entry "$old" "$i" "$target"
  done
}

restore_old_directory_modes() {
  local old=$1 table=$2 count i j selected selected_length kind target stage record type mode
  local -a paths modes used
  count=$(/usr/bin/awk 'END { print NR }' "$table/operations")
  for ((i=2; i<=count; i++)); do
    IFS=$'\t' read -r kind target stage <<<"$(/usr/bin/awk -F '\t' -v i="$i" 'NR == i { print; exit }' "$table/operations")"
    [[ $kind == target ]] || continue
    record=$(/usr/bin/awk -F '\t' -v i="$i" '$1 == i { print; exit }' "$old/manifest")
    IFS=$'\t' read -r _ _ type mode _ _ <<<"$record"
    [[ $type == dir ]] || continue
    paths+=("$target"); modes+=("$mode"); used+=(0)
  done
  for ((i=0; i<${#paths[@]}; i++)); do
    selected=-1; selected_length=-1
    for ((j=0; j<${#paths[@]}; j++)); do
      if [[ ${used[j]} == 0 && ${#paths[j]} -gt $selected_length ]]; then
        selected=$j; selected_length=${#paths[j]}
      fi
    done
    used[selected]=1
    assert_no_symlink_ancestor "${paths[selected]}"
    /bin/chmod "${modes[selected]}" "${paths[selected]}"
  done
}

validate_archive_members() {
  local archive=$1 listing=$2 member normalized
  /usr/bin/tar -tf "$archive" >"$listing" || return 1
  /bin/chmod 600 "$listing"
  while IFS= read -r member || [[ -n $member ]]; do
    normalized=${member#./}; normalized=${normalized%/}
    [[ $normalized == . || -z $normalized ]] && continue
    validate_relative_target "$normalized" || return 1
  done <"$listing"
}

validate_apply_target() {
  local target=$1 current='' part i
  local -a parts
  [[ $target == /* && $target != / && $target != */ && $target != *//* &&
     ! $target =~ [[:cntrl:]] ]] || return 1
  IFS=/ read -r -a parts <<<"$target"
  for ((i=1; i<${#parts[@]}; i++)); do
    part=${parts[i]}
    [[ -n $part && $part != . && $part != .. ]] || return 1
    current=$current/$part
    if ((i < ${#parts[@]} - 1)); then
      [[ ! -L $current ]] || return 1
      [[ ! -e $current || -d $current ]] || return 1
    fi
  done
  [[ $target == "$HOME"/* ]] || return 1
}

apply_set_matches() {
  local new=$1 table=$2 db=$3 count i kind target stage
  old_state_matches "$new" 1 "$db" || return 1
  count=$(/usr/bin/awk 'END { print NR }' "$table/operations")
  for ((i=2; i<=count; i++)); do
    IFS=$'\t' read -r kind target stage <<<"$(/usr/bin/awk -F '\t' -v i="$i" 'NR == i { print; exit }' "$table/operations")"
    old_state_matches "$table/desired" "$i" "$target" || return 1
  done
}

apply_targets_are_known() {
  local old=$1 table=$2 count i kind target stage
  count=$(/usr/bin/awk 'END { print NR }' "$table/operations")
  for ((i=2; i<=count; i++)); do
    IFS=$'\t' read -r kind target stage <<<"$(/usr/bin/awk -F '\t' -v i="$i" 'NR == i { print; exit }' "$table/operations")"
    old_state_matches "$old" "$i" "$target" || old_state_matches "$table/desired" "$i" "$target" || {
      printf 'private-skill-transaction: target operation %s matches neither declared old nor desired state\n' "$i" >&2
      return 1
    }
  done
}

apply_targets_match_desired() {
  local table=$1 count i kind target stage
  count=$(/usr/bin/awk 'END { print NR }' "$table/operations")
  for ((i=2; i<=count; i++)); do
    IFS=$'\t' read -r kind target stage <<<"$(/usr/bin/awk -F '\t' -v i="$i" 'NR == i { print; exit }' "$table/operations")"
    old_state_matches "$table/desired" "$i" "$target" || return 1
  done
}

rollback_apply_targets() {
  local old=$1 table=$2 count i j selected selected_length kind target stage
  local -a paths used
  count=$(/usr/bin/awk 'END { print NR }' "$table/operations")
  for ((i=2; i<=count; i++)); do
    IFS=$'\t' read -r kind target stage <<<"$(/usr/bin/awk -F '\t' -v i="$i" 'NR == i { print; exit }' "$table/operations")"
    paths+=("$target"); used+=(0)
  done
  # Remove deepest targets first without following symlinks.
  for ((i=0; i<${#paths[@]}; i++)); do
    selected=-1; selected_length=-1
    for ((j=0; j<${#paths[@]}; j++)); do
      if [[ ${used[j]} == 0 && ${#paths[j]} -gt $selected_length ]]; then
        selected=$j; selected_length=${#paths[j]}
      fi
    done
    used[selected]=1
    assert_no_symlink_ancestor "${paths[selected]}"
    if [[ -d ${paths[selected]} && ! -L ${paths[selected]} ]]; then /bin/chmod u+rwx "${paths[selected]}"; fi
    /bin/rm -rf "${paths[selected]}"
  done
  # Recreate directory owners with mode 0700, then leaf nodes, then final directory modes.
  restore_old_directories "$old" "$table"
  restore_old_nondirectories "$old" "$table"
  restore_old_directory_modes "$old" "$table"
  sync_boundary
}
