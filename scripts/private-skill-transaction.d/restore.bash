# Private-skill restore protocol state and operations.

restore_exit() {
  local status=$1 identity=$2 recovery=$3 phase=$4 rollback_phase
  trap - EXIT HUP INT TERM
  if ((status != 0)) && [[ -d $recovery && -f $recovery/pointer ]]; then
    rollback_phase=$(state_root)/phase.rollback.$(opaque_token)
    /bin/mkdir -m 700 "$rollback_phase"
    if ! ( recover_existing "$identity" "$recovery" "$rollback_phase" &&
           discard_plaintext_then_recovery "$rollback_phase" "$recovery" ); then
      /bin/rm -rf "$rollback_phase" "$phase"
      die 'catchable failure rollback could not be verified'
    fi
    /bin/rm -rf "$rollback_phase"
  fi
  /bin/rm -rf "$phase"
  exit "$status"
}

relative_link_target() {
  local rel=$1 prefix='../../' rest=$rel
  while [[ $rest == */* ]]; do
    prefix="../$prefix"
    rest=${rest#*/}
  done
  printf '%s.agents/skills/%s\n' "$prefix" "$rel"
}

assert_private_skill_roots_safe() {
  local root
  for root in "$HOME/.agents" "$HOME/.agents/skills" "$HOME/.claude" "$HOME/.claude/skills"; do
    assert_no_symlink_ancestor "$root/.private-skill-root-check"
    [[ ! -e $root || (-d $root && ! -L $root) ]] || die 'private skill root is not a real directory'
  done
}

assert_private_skill_target_safe() {
  assert_private_skill_roots_safe
  assert_no_symlink_ancestor "$1"
}

validate_control_free_file() {
  local file=$1 filtered=$1.control-free result
  LC_ALL=C /usr/bin/tr -d '\000-\037\177' <"$file" >"$filtered"
  /bin/chmod 600 "$filtered"
  /usr/bin/cmp -s "$file" "$filtered"
  result=$?
  /bin/rm -f "$filtered"
  return $result
}

validate_skill() {
  local rel=$1 body=$2 expected found
  expected=${rel##*/}
  [[ -s $body && $(mode_of "$body") == 600 ]] || return 1
  if ! found=$(/usr/bin/awk '
    NR == 1 {
      if ($0 != "---") exit 1
      inside = 1
      next
    }
    inside && $0 == "---" {
      closed = 1
      inside = 0
      next
    }
    inside && $0 ~ /^[[:space:]]*name:[[:space:]]*/ {
      value = $0
      sub(/^[[:space:]]*name:[[:space:]]*/, "", value)
      names++
      name = value
    }
    END {
      if (!closed || names != 1 || name == "") exit 1
      print name
    }
  ' "$body"); then
    return 1
  fi
  [[ $found == "$expected" ]]
}

desired_state_matches() {
  local table=$1 index=$2 target=$3 kind=$4 record rel hash link count
  record=$(/usr/bin/awk -F '\t' -v i="$index" '$1 == i { print; exit }' "$table/operations")
  IFS=$'\t' read -r _ rel hash link <<<"$record"
  if [[ $kind == skill ]]; then
    [[ -d $target && ! -L $target && $(mode_of "$target") == 700 ]] || return 1
    [[ -f $target/SKILL.md && ! -L $target/SKILL.md && $(mode_of "$target/SKILL.md") == 600 ]] || return 1
    [[ $(sha256_file "$target/SKILL.md") == "$hash" ]] || return 1
    count=$(/usr/bin/find "$target" -mindepth 1 -maxdepth 1 | /usr/bin/wc -l | /usr/bin/tr -d ' ')
    [[ $count == 1 ]]
  else
    [[ -L $target && $(/usr/bin/readlink "$target") == "$link" ]]
  fi
}

recover_existing() {
  local identity=$1 recovery=$2 phase=$3 pointer version table_digest new_digest state count i rel skill link
  pointer=$recovery/pointer
  [[ -f $pointer && $(mode_of "$recovery") == 700 && $(mode_of "$pointer") == 600 ]] ||
    die 'recovery metadata is invalid'
  version=$(/usr/bin/awk -F= '$1 == "version" { print $2 }' "$pointer")
  [[ $version == 1 && $(/usr/bin/awk 'END { print NR }' "$pointer") == 4 ]] ||
    die 'recovery pointer version or shape is invalid'
  table_digest=$(/usr/bin/awk -F= '$1 == "table" { print $2 }' "$pointer")
  new_digest=$(/usr/bin/awk -F= '$1 == "new" { print $2 }' "$pointer")
  state=$(/usr/bin/awk -F= '$1 == "state" { print $2 }' "$pointer")
  case $state in pending|complete) ;; *) die 'recovery pointer state is invalid' ;; esac
  [[ -n $table_digest && $table_digest == $(sha256_file "$recovery/table.age") ]] ||
    die 'encrypted operation table digest mismatch'
  /bin/mkdir -m 700 "$phase/recover-old" "$phase/recover-table"
  age -d -i "$identity" -o "$phase/old.tar" "$recovery/old.age" >/dev/null 2>&1 || die 'cannot decrypt old recovery set'
  age -d -i "$identity" -o "$phase/table.tar" "$recovery/table.age" >/dev/null 2>&1 || die 'cannot decrypt recovery operation table'
  /bin/chmod 600 "$phase/old.tar" "$phase/table.tar"
  /usr/bin/tar -xf "$phase/old.tar" -C "$phase/recover-old"
  /usr/bin/tar -xf "$phase/table.tar" -C "$phase/recover-table"
  count=$(/usr/bin/awk 'END { print NR }' "$phase/recover-table/operations")
  # The cooperative lock excludes transaction participants. A noncooperating writer can still
  # race the checks below and the later remove/rename; that check-to-rename TOCTOU is unavoidable.
  for ((i=1; i<=count; i++)); do
    rel=$(/usr/bin/awk -F '\t' -v i="$i" '$1 == i { print $2 }' "$phase/recover-table/operations")
    skill=$HOME/.agents/skills/$rel; link=$HOME/.claude/skills/$rel
    assert_private_skill_target_safe "$skill"
    assert_private_skill_target_safe "$link"
    if ! old_state_matches "$phase/recover-old" "$((i*2-1))" "$skill" &&
       ! desired_state_matches "$phase/recover-table" "$i" "$skill" skill; then
      die 'visible concurrent edit conflicts with encrypted recovery state'
    fi
    if ! old_state_matches "$phase/recover-old" "$((i*2))" "$link" &&
       ! desired_state_matches "$phase/recover-table" "$i" "$link" link; then
      die 'visible concurrent edit conflicts with encrypted recovery state'
    fi
  done
  if [[ $state == complete ]]; then
    [[ -n $new_digest && $new_digest != - && -f $recovery/new.age &&
       $new_digest == $(sha256_file "$recovery/new.age") ]] ||
      die 'encrypted finalized new-set manifest digest mismatch'
    /bin/mkdir -m 700 "$phase/recover-new"
    age -d -i "$identity" -o "$phase/new.tar" "$recovery/new.age" >/dev/null 2>&1 ||
      die 'cannot decrypt finalized new-set manifest'
    /bin/chmod 600 "$phase/new.tar"
    /usr/bin/tar -xf "$phase/new.tar" -C "$phase/recover-new"
    /usr/bin/cmp -s "$phase/recover-new/manifest" "$phase/recover-table/operations" ||
      die 'finalized new-set manifest does not match operation table'
    for ((i=1; i<=count; i++)); do
      rel=$(/usr/bin/awk -F '\t' -v i="$i" '$1 == i { print $2 }' "$phase/recover-table/operations")
      desired_state_matches "$phase/recover-table" "$i" "$HOME/.agents/skills/$rel" skill ||
        die 'committed recovery set does not match live state'
      desired_state_matches "$phase/recover-table" "$i" "$HOME/.claude/skills/$rel" link ||
        die 'committed recovery set does not match live state'
    done
  elif [[ $state == pending ]]; then
    # Remove transaction-produced or old targets deepest-first without following symlinks.
    for ((i=count; i>=1; i--)); do
      rel=$(/usr/bin/awk -F '\t' -v i="$i" '$1 == i { print $2 }' "$phase/recover-table/operations")
      assert_private_skill_target_safe "$HOME/.agents/skills/$rel"
      assert_private_skill_target_safe "$HOME/.claude/skills/$rel"
      /bin/rm -rf "$HOME/.claude/skills/$rel" "$HOME/.agents/skills/$rel"
    done
    # Restore directories/files/symlinks shallowest-first; final modes come from the snapshot.
    for ((i=1; i<=count; i++)); do
      rel=$(/usr/bin/awk -F '\t' -v i="$i" '$1 == i { print $2 }' "$phase/recover-table/operations")
      assert_private_skill_target_safe "$HOME/.agents/skills/$rel"
      assert_private_skill_target_safe "$HOME/.claude/skills/$rel"
      restore_old_entry "$phase/recover-old" "$((i*2-1))" "$HOME/.agents/skills/$rel"
      restore_old_entry "$phase/recover-old" "$((i*2))" "$HOME/.claude/skills/$rel"
    done
    sync_boundary
  else
    die 'unknown recovery state'
  fi
  sync_boundary
}

install_staged_set() {
  local phase=$1 count=$2 i rel skill_target link_target parent
  assert_private_skill_roots_safe
  /bin/mkdir -p "$HOME/.agents/skills" "$HOME/.claude/skills"
  for ((i=1; i<=count; i++)); do
    rel=$(<"$phase/rel.$i")
    skill_target=$HOME/.agents/skills/$rel
    link_target=$HOME/.claude/skills/$rel
    assert_private_skill_target_safe "$skill_target"
    assert_private_skill_target_safe "$link_target"
    parent=${skill_target%/*}; /bin/mkdir -p "$parent"
    parent=${link_target%/*}; /bin/mkdir -p "$parent"
    /bin/rm -rf "$skill_target"
    /bin/mv "$phase/staged.$i" "$skill_target"
    /bin/rm -rf "$link_target"
    /bin/ln -s "$(relative_link_target "$rel")" "$link_target"
  done
}

restore_internal() {
  local identity='' phase recovery recovery_build root recipient op_id table_digest new_digest
  local count=0 path_cipher body_cipher rel body i target
  local -a path_ciphers body_ciphers rels
  while (($#)); do
    case $1 in
      --identity) (($# >= 2)) || die 'missing identity'; identity=$2; shift 2 ;;
      --pair) (($# >= 3)) || die 'missing encrypted pair'; path_ciphers+=("$2"); body_ciphers+=("$3"); shift 3 ;;
      *) die "unknown restore argument: $1" ;;
    esac
  done
  [[ -f $identity && ${#path_ciphers[@]} -gt 0 ]] || die 'identity and at least one pair are required'
  recipient=$(age-keygen -y "$identity") || die 'cannot derive recovery recipient'
  root=$(state_root); recovery=$root/recovery
  op_id=$(opaque_token)
  phase=$root/phase.restore.$op_id
  /bin/mkdir -m 700 "$phase"
  trap 'restore_exit $? "$identity" "$recovery" "$phase"' EXIT
  trap 'restore_exit 129 "$identity" "$recovery" "$phase"' HUP
  trap 'restore_exit 130 "$identity" "$recovery" "$phase"' INT
  trap 'restore_exit 143 "$identity" "$recovery" "$phase"' TERM
  if [[ -e $recovery ]]; then
    recover_existing "$identity" "$recovery" "$phase"
    discard_plaintext_then_recovery "$phase" "$recovery"
    /bin/mkdir -m 700 "$phase"
  fi

  for ((i=1; i<=${#path_ciphers[@]}; i++)); do
    path_cipher=${path_ciphers[i-1]}; body_cipher=${body_ciphers[i-1]}
    age -d -i "$identity" -o "$phase/rel.$i" "$path_cipher" >/dev/null 2>&1 || die 'private skill decryption failed'
    age -d -i "$identity" -o "$phase/body.$i" "$body_cipher" >/dev/null 2>&1 || die 'private skill decryption failed'
    /bin/chmod 600 "$phase/rel.$i" "$phase/body.$i"
    validate_control_free_file "$phase/rel.$i" || die 'private skill target contains an ASCII control character'
    rel=$(/usr/bin/awk 'BEGIN { ORS="" } { gsub(/^[[:space:]]+|[[:space:]]+$/, ""); printf "%s", $0 }' "$phase/rel.$i")
    printf '%s' "$rel" >"$phase/rel.$i"
    validate_relative_target "$rel" || die 'private skill target is not a contained relative path'
    for body in "${rels[@]:-}"; do
      [[ $body != "$rel" && $body != "$rel"/* && $rel != "$body"/* ]] ||
        die 'overlapping private skill target'
    done
    rels+=("$rel")
    validate_skill "$rel" "$phase/body.$i" || die 'private skill frontmatter/name is invalid'
    /bin/mkdir -m 700 "$phase/staged.$i"
    /bin/cp "$phase/body.$i" "$phase/staged.$i/SKILL.md"
    /bin/chmod 600 "$phase/staged.$i/SKILL.md"
    count=$i
  done

  recovery_build=$phase/recovery
  /bin/mkdir -m 700 "$phase/old" "$phase/table" "$recovery_build"
  : >"$phase/old/manifest"
  : >"$phase/table/operations"
  /bin/chmod 600 "$phase/old/manifest" "$phase/table/operations"
  for ((i=1; i<=count; i++)); do
    rel=${rels[i-1]}
    assert_private_skill_target_safe "$HOME/.agents/skills/$rel"
    assert_private_skill_target_safe "$HOME/.claude/skills/$rel"
    snapshot_target "$HOME/.agents/skills/$rel" "$((i*2-1))" "$phase/old"
    snapshot_target "$HOME/.claude/skills/$rel" "$((i*2))" "$phase/old"
    printf '%s\t%s\t%s\t%s\n' "$i" "$rel" "$(sha256_file "$phase/staged.$i/SKILL.md")" "$(relative_link_target "$rel")" >>"$phase/table/operations"
  done
  tx_failpoint restore-before-old-encryption
  encrypt_directory "$phase/old" "$recovery_build/old.age" "$recipient"
  tx_failpoint restore-after-old-encryption
  encrypt_directory "$phase/table" "$recovery_build/table.age" "$recipient"
  tx_failpoint restore-before-pointer
  table_digest=$(sha256_file "$recovery_build/table.age")
  write_pointer "$recovery_build" "$table_digest" pending
  tx_failpoint restore-after-pointer
  /bin/mv "$recovery_build" "$recovery"
  sync_boundary
  tx_failpoint restore-after-publish
  install_staged_set "$phase" "$count"
  write_pointer "$recovery" "$table_digest" pending
  tx_failpoint restore-after-install

  /bin/mkdir -m 700 "$phase/new"
  /bin/cp "$phase/table/operations" "$phase/new/manifest"
  /bin/chmod 600 "$phase/new/manifest"
  encrypt_directory "$phase/new" "$recovery/new.age" "$recipient"
  sync_boundary
  new_digest=$(sha256_file "$recovery/new.age")
  write_pointer "$recovery" "$table_digest" pending "$new_digest"
  if [[ -n ${PRIVATE_SKILL_TX_OUTER_CAPABILITY:-} &&
        ${PRIVATE_SKILL_TX_OUTER_CAPABILITY} == "${PRIVATE_SKILL_TX_TOKEN:-}" ]]; then
    /bin/rm -rf "$phase"
    trap - EXIT HUP INT TERM
    return 0
  fi
  tx_failpoint restore-before-final-check "$HOME/.agents/skills/${rels[0]}/SKILL.md"
  for ((i=1; i<=count; i++)); do
    rel=${rels[i-1]}
    assert_private_skill_target_safe "$HOME/.agents/skills/$rel"
    assert_private_skill_target_safe "$HOME/.claude/skills/$rel"
    desired_state_matches "$phase/table" "$i" "$HOME/.agents/skills/$rel" skill ||
      die 'final desired skill state verification failed'
    desired_state_matches "$phase/table" "$i" "$HOME/.claude/skills/$rel" link ||
      die 'final desired link state verification failed'
  done
  write_pointer "$recovery" "$table_digest" complete "$new_digest"
  tx_failpoint restore-after-complete
  /bin/rm -rf "$recovery" "$phase"
  sync_boundary
  trap - EXIT HUP INT TERM
}

finalize_nested_restore() {
  local identity=$1 recovery root phase table_digest new_digest
  root=$(state_root); recovery=$root/recovery
  [[ -d $recovery ]] || return 0
  table_digest=$(/usr/bin/awk -F= '$1 == "table" { print $2 }' "$recovery/pointer")
  new_digest=$(/usr/bin/awk -F= '$1 == "new" { print $2 }' "$recovery/pointer")
  phase=$root/phase.verify.$(opaque_token)
  /bin/mkdir -m 700 "$phase"
  if ! verify_encrypted_desired_set "$identity" "$recovery" "$phase"; then
    /bin/rm -rf "$phase"
    die 'final nested restore desired-state verification failed'
  fi
  /bin/rm -rf "$phase"
  write_pointer "$recovery" "$table_digest" complete "$new_digest"
  tx_failpoint nested-after-complete
  phase=$root/phase.finalize.$(opaque_token)
  /bin/mkdir -m 700 "$phase"
  recover_existing "$identity" "$recovery" "$phase"
  discard_plaintext_then_recovery "$phase" "$recovery"
}

verify_encrypted_desired_set() {
  local identity=$1 recovery=$2 phase=$3 table_digest count i rel
  table_digest=$(/usr/bin/awk -F= '$1 == "table" { print $2 }' "$recovery/pointer")
  [[ -n $table_digest && $table_digest == $(sha256_file "$recovery/table.age") ]] || return 1
  /bin/mkdir -m 700 "$phase/table"
  age -d -i "$identity" -o "$phase/table.tar" "$recovery/table.age" >/dev/null 2>&1 || return 1
  /bin/chmod 600 "$phase/table.tar"
  /usr/bin/tar -xf "$phase/table.tar" -C "$phase/table" || return 1
  count=$(/usr/bin/awk 'END { print NR }' "$phase/table/operations")
  for ((i=1; i<=count; i++)); do
    rel=$(/usr/bin/awk -F '\t' -v i="$i" '$1 == i { print $2 }' "$phase/table/operations")
    assert_private_skill_target_safe "$HOME/.agents/skills/$rel"
    assert_private_skill_target_safe "$HOME/.claude/skills/$rel"
    desired_state_matches "$phase/table" "$i" "$HOME/.agents/skills/$rel" skill || return 1
    desired_state_matches "$phase/table" "$i" "$HOME/.claude/skills/$rel" link || return 1
  done
}

rollback_nested_restore() {
  local identity=$1 root recovery phase
  root=$(state_root); recovery=$root/recovery
  [[ -d $recovery ]] || return 0
  phase=$root/phase.rollback.$(opaque_token)
  /bin/mkdir -m 700 "$phase"
  recover_existing "$identity" "$recovery" "$phase"
  discard_plaintext_then_recovery "$phase" "$recovery"
}

restore_command() {
  if [[ -n ${PRIVATE_SKILL_TX_TOKEN:-} ]]; then
    participant "$PRIVATE_SKILL_TX_TOKEN" "$0" __restore "$PRIVATE_SKILL_TX_TOKEN" "$@"
  fi
  ensure_lock
  cleanup_orphan_prepublication_phases
  local token
  token=$(opaque_token); export PRIVATE_SKILL_TX_TOKEN=$token
  exec "$0" __restore "$token" "$@"
}

restore_participant() {
  local token=$1
  shift
  [[ ${PRIVATE_SKILL_TX_TOKEN:-} == "$token" ]] || die 'invalid restore participant token'
  local root lock
  root=$(state_root); lock=$root/lock
  [[ -f $lock && $(identity_of "$lock") == $(/usr/bin/stat -Lf '%i' /dev/fd/9) ]] || die 'invalid restore lock descriptor'
  restore_internal "$@"
}
