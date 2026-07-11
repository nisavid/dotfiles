# Locking and participant-boundary scenarios.

test_lock_contention_release_and_descendant_lifetime() {
  new_fixture
  mkdir -m 700 -p $XDG_STATE_HOME/chezmoi/private-skill-transaction
  : >$XDG_STATE_HOME/chezmoi/private-skill-transaction/lock
  chmod 600 $XDG_STATE_HOME/chezmoi/private-skill-transaction/lock

  $cli with-lock /bin/sh -c 'sleep 1' &
  holder=$!
  sleep 0.1
  if $cli with-lock /usr/bin/true 2>/dev/null; then
    fail 'contending transaction acquired the lock'
  fi
  wait $holder
  $cli with-lock /usr/bin/true

  $cli with-lock /bin/sh -c 'sleep 1 &' &
  holder=$!
  wait $holder
  if $cli with-lock /usr/bin/true 2>/dev/null; then
    fail 'lock was released while a synchronous descendant still held its inherited descriptor'
  fi
  sleep 1.1
  $cli with-lock /usr/bin/true
}

test_lock_path_validation_and_parent_mode_preservation() {
  local tx_root=$XDG_STATE_HOME/chezmoi/private-skill-transaction lock scenario
  new_fixture
  tx_root=$XDG_STATE_HOME/chezmoi/private-skill-transaction
  mkdir -m 700 $tx_root
  lock=$tx_root/lock
  : >$lock
  chmod 600 $lock
  for scenario in missing replaced symlink; do
    if $cli with-lock /bin/sh -c '
      case "$1" in
        missing) rm "$2" ;;
        replaced) mv "$2" "$2.old"; : >"$2"; chmod 600 "$2" ;;
        symlink) mv "$2" "$2.old"; ln -s "$2.old" "$2" ;;
      esac
      "$3" __participant "$PRIVATE_SKILL_TX_TOKEN" /usr/bin/true
    ' sh $scenario $lock $cli >/dev/null 2>&1; then
      fail "$scenario lock path was accepted by a nested participant"
    fi
    rm -f $lock $lock.old
    : >$lock
    chmod 600 $lock
  done
  chmod 711 $XDG_STATE_HOME/chezmoi
  if $cli with-lock /usr/bin/true >/dev/null 2>&1; then
    fail 'wrong lock-parent mode was accepted'
  fi
  [[ $(stat -f '%Lp' $XDG_STATE_HOME/chezmoi) == 711 ]] || fail 'unrelated parent mode was changed'
}

test_bogus_participant_token() {
  new_fixture
  mkdir -m 700 -p $XDG_STATE_HOME/chezmoi/private-skill-transaction
  : >$XDG_STATE_HOME/chezmoi/private-skill-transaction/lock
  chmod 600 $XDG_STATE_HOME/chezmoi/private-skill-transaction/lock
  if PRIVATE_SKILL_TX_TOKEN=outer $cli __participant bogus /usr/bin/true 9</dev/null 2>/dev/null; then
    fail 'bogus participant token was accepted'
  fi
  if PRIVATE_SKILL_TX_TOKEN=outer $cli __participant outer /usr/bin/true 9</dev/null 2>/dev/null; then
    fail 'participant with a bogus inherited descriptor was accepted'
  fi
}

test_all_validated_phase_names_are_cleaned() {
  local tx_root name
  new_fixture
  tx_root=$XDG_STATE_HOME/chezmoi/private-skill-transaction
  mkdir -m 700 $tx_root
  for name in phase.rollback.x phase.verify.x phase.finalize.x phase.apply-recover.x phase.generic-id; do
    mkdir -m 700 $tx_root/$name
    print -r -- plaintext >$tx_root/$name/material
    chmod 600 $tx_root/$name/material
  done
  $cli with-lock /usr/bin/true
  [[ -z $(find $tx_root -maxdepth 1 -type d -name 'phase.*' -print -quit) ]] ||
    fail 'validated orphan phase directories were not all removed'
}
