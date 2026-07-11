# Cross-protocol sequencing for apply, rollback, and recovery.

apply_prepublication_exit() {
  local status=$1 phase=$2 stage=${3:-}
  trap - EXIT HUP INT TERM
  [[ -z $stage ]] || /bin/rm -f "$stage"
  /bin/rm -rf "$phase"
  exit "$status"
}

recover_apply_existing() {
  local identity=$1 root recovery phase version table_digest new_digest state db stage kind
  root=$(state_root); recovery=$root/apply-recovery
  [[ -d $recovery ]] || return 0
  [[ -f $recovery/pointer && $(mode_of "$recovery") == 700 ]] || die 'apply recovery metadata is invalid'
  version=$(/usr/bin/awk -F= '$1 == "version" { print $2 }' "$recovery/pointer")
  [[ $version == 1 && $(/usr/bin/awk 'END { print NR }' "$recovery/pointer") == 4 ]] ||
    die 'apply recovery pointer version or shape is invalid'
  table_digest=$(/usr/bin/awk -F= '$1 == "table" { print $2 }' "$recovery/pointer")
  new_digest=$(/usr/bin/awk -F= '$1 == "new" { print $2 }' "$recovery/pointer")
  state=$(/usr/bin/awk -F= '$1 == "state" { print $2 }' "$recovery/pointer")
  case $state in
    pending|ready|complete) ;;
    *) die 'apply recovery pointer state is invalid' ;;
  esac
  [[ $table_digest == $(sha256_file "$recovery/table.age") ]] || die 'apply operation table digest mismatch'
  phase=$root/phase.apply-recover.$(opaque_token)
  /bin/mkdir -m 700 "$phase"
  trap '/bin/rm -rf -- "$phase"' EXIT
  /bin/mkdir -m 700 "$phase/old" "$phase/table"
  age -d -i "$identity" -o "$phase/old.tar" "$recovery/old.age" >/dev/null 2>&1 || die 'cannot decrypt old persistent state'
  age -d -i "$identity" -o "$phase/table.tar" "$recovery/table.age" >/dev/null 2>&1 || die 'cannot decrypt apply operation table'
  /bin/chmod 600 "$phase/old.tar" "$phase/table.tar"
  /usr/bin/tar -xf "$phase/old.tar" -C "$phase/old"
  /usr/bin/tar -xf "$phase/table.tar" -C "$phase/table"
  IFS=$'\t' read -r kind db stage <"$phase/table/operations"
  if [[ $state == pending ]]; then
    old_state_matches "$phase/old" 1 "$db" || die 'visible persistent-state edit conflicts with recovery state'
    if ! apply_targets_are_known "$phase/old" "$phase/table"; then
      /bin/rm -rf "$phase"; trap - EXIT
      die 'visible target edit conflicts with pending recovery state'
    fi
    /bin/rm -f "$stage"
    rollback_apply_targets "$phase/old" "$phase/table"
    rollback_nested_restore "$identity"
  else
    [[ -n $new_digest && $new_digest != - && $new_digest == $(sha256_file "$recovery/new.age") ]] ||
      die 'apply finalized manifest digest mismatch'
    /bin/mkdir -m 700 "$phase/new"
    age -d -i "$identity" -o "$phase/new.tar" "$recovery/new.age" >/dev/null 2>&1 || die 'cannot decrypt new persistent state manifest'
    /bin/chmod 600 "$phase/new.tar"
    /usr/bin/tar -xf "$phase/new.tar" -C "$phase/new"
    if ! apply_targets_are_known "$phase/old" "$phase/table"; then
      /bin/rm -rf "$phase"; trap - EXIT
      die 'visible target edit conflicts with committed recovery state'
    fi
    if apply_set_matches "$phase/new" "$phase/table" "$db"; then
      finalize_nested_restore "$identity"
    elif old_state_matches "$phase/old" 1 "$db" && [[ $state == ready ]]; then
      /bin/rm -f "$stage"
      rollback_apply_targets "$phase/old" "$phase/table"
      rollback_nested_restore "$identity"
    else
      /bin/rm -rf "$phase"; trap - EXIT
      die 'visible persistent-state edit conflicts with committed recovery state'
    fi
  fi
  discard_plaintext_then_recovery "$phase" "$recovery"
  trap - EXIT
}

apply_exit() {
  local status=$1 identity=$2 recovery=$3 phase=$4 stage=$5
  trap - EXIT HUP INT TERM
  if ((status != 0)) && [[ -d $recovery && -f $recovery/pointer ]]; then
    if ! ( recover_apply_existing "$identity" ); then
      /bin/rm -f "$stage"
      /bin/rm -rf "$phase"
      die 'catchable apply failure rollback could not be verified'
    fi
  fi
  /bin/rm -f "$stage"
  /bin/rm -rf "$phase"
  exit "$status"
}

apply_internal() {
  local identity='' persistent_state='' chezmoi_bin=chezmoi stage protected_state status
  local db_dir db_base arg target existing i rel desired_archive
  local root recovery recovery_build phase recipient op_id table_digest new_digest
  local -a apply_args target_paths ephemeral_targets all_targets validated_targets
  while (($#)); do
    case $1 in
      --identity) (($# >= 2)) || die 'missing identity'; identity=$2; shift 2 ;;
      --persistent-state) (($# >= 2)) || die 'missing persistent state'; persistent_state=$2; shift 2 ;;
      --chezmoi) (($# >= 2)) || die 'missing chezmoi executable'; chezmoi_bin=$2; shift 2 ;;
      --ephemeral-target) (($# >= 2)) || die 'missing ephemeral target'; ephemeral_targets+=("$2"); shift 2 ;;
      --) shift; break ;;
      *) die "unknown apply argument: $1" ;;
    esac
  done
  [[ -f $identity && -n $persistent_state && -x $chezmoi_bin && $# -gt 0 ]] ||
    die 'apply requires identity, persistent state, chezmoi executable, and targets'
  apply_args=("$@")
  for arg in "$@"; do
    case $arg in
      --parent-dirs|-P|--init|--dry-run|-n) die "apply flag is outside the explicit target transaction boundary: $arg" ;;
      --force|--no-tty|--keep-going|--interactive|--less-interactive|--recursive|--verbose|-f|-v|-k|-r) ;;
      --*|-*) die "ambiguous apply flag is not supported by the transaction wrapper: $arg" ;;
      /*) target_paths+=("$arg") ;;
      *) die "apply target operand must be absolute: $arg" ;;
    esac
  done
  [[ ${#target_paths[@]} -gt 0 ]] || die 'apply requires at least one absolute target operand'
  if ((${#ephemeral_targets[@]})); then apply_args+=("${ephemeral_targets[@]}"); fi
  all_targets=("${target_paths[@]}")
  if ((${#ephemeral_targets[@]})); then all_targets+=("${ephemeral_targets[@]}"); fi
  for target in "${all_targets[@]}"; do
    validate_apply_target "$target" || die "apply target operand is not a normalized safe absolute path: $target"
    if [[ -e $target && ! -L $target && ! -f $target && ! -d $target ]]; then
      die 'unsupported live target type'
    fi
    for existing in "${validated_targets[@]:-}"; do
      [[ -z $existing ]] && continue
      [[ $existing != "$target" && $existing != "$target"/* && $target != "$existing"/* ]] ||
        die 'overlapping apply target operands'
    done
    validated_targets+=("$target")
  done
  for target in "${ephemeral_targets[@]:-}"; do
    [[ ! -e $target && ! -L $target ]] || die 'ephemeral apply target must be absent'
  done
  db_dir=${persistent_state%/*}; db_base=${persistent_state##*/}
  [[ -d $db_dir ]] || die 'persistent-state parent does not exist'
  recover_apply_existing "$identity"
  root=$(state_root)
  recovery=$root/apply-recovery; op_id=$(opaque_token)
  phase=$root/phase.apply.$op_id; recovery_build=$phase/recovery
  recipient=$(age-keygen -y "$identity") || die 'cannot derive recovery recipient'
  /bin/mkdir -m 700 "$phase"
  trap 'apply_prepublication_exit $? "$phase" "$stage"' EXIT
  trap 'apply_prepublication_exit 129 "$phase" "$stage"' HUP
  trap 'apply_prepublication_exit 130 "$phase" "$stage"' INT
  trap 'apply_prepublication_exit 143 "$phase" "$stage"' TERM
  /bin/mkdir -m 700 "$phase/old" "$phase/table" "$phase/table/desired" "$phase/projected" "$recovery_build"
  stage=$db_dir/.$db_base.private-skill-tx.$(opaque_token)
  protected_state=$phase/persistent-state
  if [[ -e $persistent_state ]]; then
    [[ -f $persistent_state && ! -L $persistent_state ]] || die 'persistent state must be a regular file'
    /bin/cp -p "$persistent_state" "$protected_state"
  else
    : >"$protected_state"
  fi
  /bin/chmod 600 "$protected_state"
  desired_archive=$phase/desired.tar
  ( umask 022
    exec "$chezmoi_bin" --persistent-state "$protected_state" archive --format tar \
      --output "$desired_archive" "${target_paths[@]}"
  ) || die 'chezmoi desired-state projection failed'
  [[ -f $desired_archive && ! -L $desired_archive ]] || die 'chezmoi desired-state archive is invalid'
  /bin/chmod 600 "$desired_archive"
  validate_archive_members "$desired_archive" "$phase/archive-members" ||
    die 'chezmoi desired-state archive contains an unsafe path'
  (umask 000; /usr/bin/tar -xpf "$desired_archive" -C "$phase/projected")
  /usr/bin/find "$phase/projected" -type l -exec /bin/chmod -h 700 {} +
  : >"$phase/old/manifest"; : >"$phase/table/desired/manifest"
  snapshot_target "$persistent_state" 1 "$phase/old"
  snapshot_target "$protected_state" 1 "$phase/table/desired"
  printf 'db\t%s\t%s\n' "$persistent_state" "$stage" >"$phase/table/operations"
  for ((i=1; i<=${#target_paths[@]}; i++)); do
    target=${target_paths[i-1]}; rel=${target#"$HOME"/}
    snapshot_target "$target" "$((i+1))" "$phase/old"
    snapshot_target "$phase/projected/$rel" "$((i+1))" "$phase/table/desired"
    printf 'target\t%s\t-\n' "$target" >>"$phase/table/operations"
  done
  for ((i=1; i<=${#ephemeral_targets[@]}; i++)); do
    target=${ephemeral_targets[i-1]}
    snapshot_target "$target" "$((${#target_paths[@]}+i+1))" "$phase/old"
    snapshot_target "$target" "$((${#target_paths[@]}+i+1))" "$phase/table/desired"
    printf 'ephemeral\t%s\t-\n' "$target" >>"$phase/table/operations"
  done
  /bin/chmod 600 "$phase/old/manifest" "$phase/table/operations" "$phase/table/desired/manifest"
  tx_failpoint apply-before-old-encryption
  encrypt_directory "$phase/old" "$recovery_build/old.age" "$recipient"
  tx_failpoint apply-after-old-encryption
  encrypt_directory "$phase/table" "$recovery_build/table.age" "$recipient"
  tx_failpoint apply-before-pointer
  table_digest=$(sha256_file "$recovery_build/table.age")
  write_pointer "$recovery_build" "$table_digest" pending
  tx_failpoint apply-after-pointer
  /bin/mv "$recovery_build" "$recovery"; sync_boundary
  trap 'apply_exit $? "$identity" "$recovery" "$phase" "$stage"' EXIT
  trap 'apply_exit 129 "$identity" "$recovery" "$phase" "$stage"' HUP
  trap 'apply_exit 130 "$identity" "$recovery" "$phase" "$stage"' INT
  trap 'apply_exit 143 "$identity" "$recovery" "$phase" "$stage"' TERM
  tx_failpoint apply-after-publish
  tx_failpoint apply-before-chezmoi
  /bin/cp -p "$protected_state" "$stage"; /bin/chmod 600 "$stage"
  set +e
  ( umask 022
    export PRIVATE_SKILL_TX_OUTER_CAPABILITY=${PRIVATE_SKILL_TX_TOKEN:?}
    exec "$chezmoi_bin" --persistent-state "$stage" apply "${apply_args[@]}"
  )
  status=$?
  set -e
  if ((status != 0)); then apply_exit "$status" "$identity" "$recovery" "$phase" "$stage"; fi
  [[ -f $stage && ! -L $stage && $(mode_of "$stage") == 600 ]] ||
    apply_exit 1 "$identity" "$recovery" "$phase" "$stage"
  "$chezmoi_bin" --persistent-state "$stage" state dump >/dev/null 2>&1 ||
    apply_exit 1 "$identity" "$recovery" "$phase" "$stage"
  tx_failpoint apply-after-chezmoi
  apply_targets_match_desired "$phase/table" || die 'final desired target state verification failed'
  tx_failpoint apply-before-new-manifest
  /bin/mkdir -m 700 "$phase/new"; : >"$phase/new/manifest"
  snapshot_target "$stage" 1 "$phase/new"
  tx_failpoint apply-before-new-encryption
  encrypt_directory "$phase/new" "$recovery/new.age" "$recipient"
  new_digest=$(sha256_file "$recovery/new.age")
  tx_failpoint apply-before-ready-pointer
  write_pointer "$recovery" "$table_digest" ready "$new_digest"
  sync_boundary
  old_state_matches "$phase/old" 1 "$persistent_state" ||
    die 'live persistent state changed during apply'
  /bin/mv -f "$stage" "$persistent_state"; sync_boundary
  tx_failpoint apply-after-db-install "$persistent_state"
  apply_set_matches "$phase/new" "$phase/table" "$persistent_state" ||
    die 'committed apply set verification failed'
  write_pointer "$recovery" "$table_digest" complete "$new_digest"
  tx_failpoint apply-after-complete
  finalize_nested_restore "$identity"
  /bin/rm -rf "$recovery" "$phase"; sync_boundary
  trap - EXIT HUP INT TERM
}

apply_command() {
  ensure_lock
  cleanup_orphan_prepublication_phases
  local token
  token=$(opaque_token); export PRIVATE_SKILL_TX_TOKEN=$token
  exec "$0" __apply "$token" "$@"
}

apply_participant() {
  local token=$1
  shift
  [[ ${PRIVATE_SKILL_TX_TOKEN:-} == "$token" ]] || die 'invalid apply participant token'
  participant "$token" "$0" __apply-internal "$token" "$@"
}

apply_internal_participant() {
  local token=$1
  shift
  [[ ${PRIVATE_SKILL_TX_TOKEN:-} == "$token" ]] || die 'invalid apply participant token'
  apply_internal "$@"
}

recover_internal() {
  local identity='' root recovery phase op_id
  while (($#)); do
    case $1 in
      --identity) (($# >= 2)) || die 'missing identity'; identity=$2; shift 2 ;;
      *) die "unknown recover argument: $1" ;;
    esac
  done
  [[ -f $identity ]] || die 'identity is required'
  root=$(state_root); recovery=$root/recovery
  recover_apply_existing "$identity"
  [[ -d $recovery ]] || return 0
  op_id=$(opaque_token); phase=$root/phase.$op_id
  /bin/mkdir -m 700 "$phase"
  trap '/bin/rm -rf -- "$phase"' EXIT HUP INT TERM
  recover_existing "$identity" "$recovery" "$phase"
  discard_plaintext_then_recovery "$phase" "$recovery"
  tx_failpoint recovery-after-encrypted-removal
  trap - EXIT HUP INT TERM
}

recover_command() {
  ensure_lock
  cleanup_orphan_prepublication_phases
  local token
  token=$(opaque_token); export PRIVATE_SKILL_TX_TOKEN=$token
  exec "$0" __recover "$token" "$@"
}

recover_participant() {
  local token=$1 root lock
  shift
  [[ ${PRIVATE_SKILL_TX_TOKEN:-} == "$token" ]] || die 'invalid recover participant token'
  root=$(state_root); lock=$root/lock
  [[ -f $lock && $(identity_of "$lock") == $(/usr/bin/stat -Lf '%i' /dev/fd/9) ]] || die 'invalid recover lock descriptor'
  recover_internal "$@"
}
