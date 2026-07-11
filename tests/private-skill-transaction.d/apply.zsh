# Outer apply protocol scenarios.

test_apply_pre_pointer_crash_boundaries() {
  local boundary
  for boundary in apply-before-encryption-kill apply-between-encryption-kill \
    apply-before-pointer-kill apply-after-pointer-kill apply-after-publish-kill; do
    new_fixture
    make_age_fixture
    mkdir -m 700 -p $fixture/bin
    state_db=$fixture/chezmoistate.boltdb
    print -r -- old-db >$state_db
    chmod 600 $state_db
    install_fake_chezmoi empty
    if PRIVATE_SKILL_TX_TEST_FAILURE=$boundary $cli apply --identity $fixture/identity.txt \
      --persistent-state $state_db --chezmoi $fixture/bin/fake-chezmoi -- $HOME/.codex/AGENTS.md >/dev/null 2>&1; then
      fail "$boundary unexpectedly succeeded"
    fi
    assert_eq "$(<$state_db)" old-db
    PRIVATE_SKILL_TX_TEST_FAILURE=apply-before-chezmoi-fail $cli apply --identity $fixture/identity.txt \
      --persistent-state $state_db --chezmoi $fixture/bin/fake-chezmoi -- $HOME/.codex/AGENTS.md >/dev/null 2>&1 || true
    [[ ! -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/apply-recovery ]] ||
      fail "$boundary left unrecovered durable apply state"
    [[ -z $(find $XDG_STATE_HOME/chezmoi/private-skill-transaction -maxdepth 1 -name 'phase.apply.*' -print -quit) ]] ||
      fail "$boundary left an orphan phase root"
    [[ -z $(find ${state_db:h} -maxdepth 1 -name '.chezmoistate.boltdb.private-skill-tx.*' -print -quit) ]] ||
      fail "$boundary left an orphan persistent-state sibling"
    assert_eq "$(<$state_db)" old-db
  done
}

test_outer_apply_protects_persistent_state_and_rolls_back_restore() {
  new_fixture
  make_age_fixture
  encrypt_value alpha $fixture/source/a.path.age
  encrypt_value "$(skill_text alpha new)" $fixture/source/a.md.age
  mkdir -m 700 -p $HOME/.agents/skills/alpha $fixture/bin
  print -r -- old-skill >$HOME/.agents/skills/alpha/SKILL.md
  chmod 600 $HOME/.agents/skills/alpha/SKILL.md
  state_db=$fixture/chezmoistate.boltdb
  print -r -- old-db >$state_db
  chmod 600 $state_db
  install_fake_chezmoi nested-restore
  export PRIVATE_SKILL_TEST_CLI=$cli PRIVATE_SKILL_TEST_IDENTITY=$fixture/identity.txt
  export PRIVATE_SKILL_TEST_PATH=$fixture/source/a.path.age PRIVATE_SKILL_TEST_BODY=$fixture/source/a.md.age
  if PRIVATE_SKILL_TEST_APPLY_STATUS=23 $cli apply --identity $fixture/identity.txt \
    --persistent-state $state_db --chezmoi $fixture/bin/fake-chezmoi -- $HOME/.codex/AGENTS.md >/dev/null 2>&1; then
    fail 'failing outer apply unexpectedly succeeded'
  fi
  assert_eq "$(<$state_db)" old-db
  assert_eq "$(<$HOME/.agents/skills/alpha/SKILL.md)" old-skill
  [[ $(stat -f '%Lp' $state_db) == 600 ]] || fail 'persistent state mode changed'

  $cli apply --identity $fixture/identity.txt --persistent-state $state_db \
    --chezmoi $fixture/bin/fake-chezmoi -- $HOME/.codex/AGENTS.md
  assert_eq "$(<$state_db)" updated-db
  assert_eq "$(<$HOME/.agents/skills/alpha/SKILL.md)" "$(skill_text alpha new)"
  [[ $(stat -f '%Lp' $state_db) == 600 ]] || fail 'replacement persistent state mode is not 0600'
  [[ -z $(find ${state_db:h} -maxdepth 1 -name '.chezmoistate.boltdb.private-skill-tx.*' -print -quit) ]] ||
    fail 'persistent-state sibling staging file leaked'

  print -r -- crash-old-db >$state_db
  print -r -- crash-old-skill >$HOME/.agents/skills/alpha/SKILL.md
  chmod 600 $state_db $HOME/.agents/skills/alpha/SKILL.md
  if PRIVATE_SKILL_TX_TEST_FAILURE=apply-commit-kill $cli apply --identity $fixture/identity.txt \
    --persistent-state $state_db --chezmoi $fixture/bin/fake-chezmoi -- $HOME/.codex/AGENTS.md >/dev/null 2>&1; then
    fail 'apply committed crash injection unexpectedly succeeded'
  fi
  $cli recover --identity $fixture/identity.txt
  assert_eq "$(<$state_db)" updated-db
  assert_eq "$(<$HOME/.agents/skills/alpha/SKILL.md)" "$(skill_text alpha new)"
  [[ ! -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/apply-recovery ]] ||
    fail 'committed apply recovery was not cleaned'
  [[ ! -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/recovery ]] ||
    fail 'committed nested restore recovery was not cleaned'
  [[ -z $(find ${state_db:h} -maxdepth 1 -name '.chezmoistate.boltdb.private-skill-tx.*' -print -quit) ]] ||
    fail 'committed apply left a persistent-state sibling'
}

test_outer_apply_post_success_catchable_failures_roll_back_immediately() {
  local failure
  for failure in apply-new-manifest-fail apply-new-encryption-fail apply-ready-pointer-fail; do
    new_fixture
    make_age_fixture
    encrypt_value alpha $fixture/source/a.path.age
    encrypt_value "$(skill_text alpha new)" $fixture/source/a.md.age
    mkdir -m 700 -p $HOME/.agents/skills/alpha $fixture/bin
    print -r -- old-skill >$HOME/.agents/skills/alpha/SKILL.md
    chmod 600 $HOME/.agents/skills/alpha/SKILL.md
    state_db=$fixture/chezmoistate.boltdb
    print -r -- old-db >$state_db
    chmod 600 $state_db
    install_fake_chezmoi nested-restore
    export PRIVATE_SKILL_TEST_CLI=$cli PRIVATE_SKILL_TEST_IDENTITY=$fixture/identity.txt
    export PRIVATE_SKILL_TEST_PATH=$fixture/source/a.path.age PRIVATE_SKILL_TEST_BODY=$fixture/source/a.md.age
    if PRIVATE_SKILL_TX_TEST_FAILURE=$failure $cli apply --identity $fixture/identity.txt \
      --persistent-state $state_db --chezmoi $fixture/bin/fake-chezmoi -- $HOME/.codex/AGENTS.md >/dev/null 2>&1; then
      fail "$failure unexpectedly succeeded"
    fi
    assert_eq "$(<$state_db)" old-db
    assert_eq "$(<$HOME/.agents/skills/alpha/SKILL.md)" old-skill
    [[ ! -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/apply-recovery ]] ||
      fail "$failure retained outer recovery after catchable rollback"
    [[ ! -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/recovery ]] ||
      fail "$failure retained nested recovery after catchable rollback"
    [[ -z $(find $XDG_STATE_HOME/chezmoi/private-skill-transaction -maxdepth 1 -name 'phase.apply.*' -print -quit) ]] ||
      fail "$failure retained an outer phase root"
    [[ -z $(find ${state_db:h} -maxdepth 1 -name '.chezmoistate.boltdb.private-skill-tx.*' -print -quit) ]] ||
      fail "$failure retained the persistent-state sibling"
  done
}

test_outer_apply_signals_roll_back_immediately() {
  local signal expected exit_status state_db
  for signal expected in hup 129 int 130 term 143; do
    new_fixture
    make_age_fixture
    mkdir -m 700 -p $fixture/bin
    state_db=$fixture/chezmoistate.boltdb
    print -r -- old-db >$state_db
    chmod 600 $state_db
    install_fake_chezmoi db-only

    set +e
    PRIVATE_SKILL_TEST_SIGNAL=${signal:u} $cli apply --identity $fixture/identity.txt \
      --persistent-state $state_db --chezmoi $fixture/bin/fake-chezmoi -- $HOME/.codex/AGENTS.md \
      >/dev/null 2>&1
    exit_status=$?
    set -e

    assert_eq "$exit_status" "$expected"
    assert_eq "$(<$state_db)" old-db
    [[ ! -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/apply-recovery ]] ||
      fail "$signal apply retained recovery"
    [[ -z $(find $XDG_STATE_HOME/chezmoi/private-skill-transaction -maxdepth 1 -name 'phase.*' -print -quit) ]] ||
      fail "$signal apply retained plaintext phase state"
    [[ -z $(find ${state_db:h} -maxdepth 1 -name '.chezmoistate.boltdb.private-skill-tx.*' -print -quit) ]] ||
      fail "$signal apply retained the persistent-state sibling"
  done
}

test_unsupported_apply_target_type_is_rejected() {
  new_fixture
  make_age_fixture
  mkdir -m 700 $fixture/bin
  state_db=$fixture/chezmoistate.boltdb
  print -r -- old-db >$state_db
  chmod 600 $state_db
  install_fake_chezmoi empty
  unsupported=$HOME/unsupported.fifo
  mkfifo $unsupported
  if $cli apply --identity $fixture/identity.txt --persistent-state $state_db \
    --chezmoi $fixture/bin/fake-chezmoi -- $unsupported >$fixture/fifo.stdout 2>$fixture/fifo.stderr; then
    fail 'unsupported FIFO target was accepted'
  fi
  grep -q 'unsupported live target type' $fixture/fifo.stderr ||
    fail "unsupported FIFO did not produce a controlled validation error: $(<$fixture/fifo.stderr)"
  [[ -p $unsupported ]] || fail 'unsupported FIFO target was mutated'
  assert_eq "$(<$state_db)" old-db
  [[ ! -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/apply-recovery ]] ||
    fail 'unsupported FIFO target leaked encrypted recovery'
  tx_root=$XDG_STATE_HOME/chezmoi/private-skill-transaction
  [[ -z $(find $tx_root -maxdepth 1 -type d -name 'phase.apply.*' -print -quit) ]] ||
    fail 'unsupported FIFO target leaked a plaintext apply phase'
  [[ -z $(find $tx_root -type f \( -name 'desired.tar' -o -name 'persistent-state' -o -name 'archive-members' \) -print -quit) ]] ||
    fail 'unsupported FIFO target leaked projected or protected plaintext'
}

test_projected_apply_file_modes_are_preserved() {
  new_fixture
  make_age_fixture
  mkdir -m 700 $fixture/bin
  export APPLY_PUBLIC=$HOME/public.txt APPLY_PRIVATE=$HOME/private.txt
  state_db=$fixture/chezmoistate.boltdb
  print -r -- old-db >$state_db
  chmod 600 $state_db
  install_fake_chezmoi projected-modes
  $cli apply --identity $fixture/identity.txt --persistent-state $state_db \
    --chezmoi $fixture/bin/fake-chezmoi -- $APPLY_PUBLIC $APPLY_PRIVATE
  [[ $(stat -f '%Lp' $APPLY_PUBLIC) == 644 ]] || fail 'managed public file mode was not verified'
  [[ $(stat -f '%Lp' $APPLY_PRIVATE) == 600 ]] || fail 'managed private file mode was not verified'
  assert_eq "$(<$state_db)" updated-db
}

test_apply_projection_catchable_failures_cleanup() {
  local scenario tx_root
  for scenario in archive-fail unsafe-member corrupt-archive projected-fifo; do
    new_fixture
    make_age_fixture
    mkdir -m 700 $fixture/bin
    state_db=$fixture/chezmoistate.boltdb
    print -r -- old-db >$state_db
    chmod 600 $state_db
    install_fake_chezmoi archive-scenario
    export APPLY_ARCHIVE_SCENARIO=$scenario
    if $cli apply --identity $fixture/identity.txt --persistent-state $state_db \
      --chezmoi $fixture/bin/fake-chezmoi -- $HOME/managed >$fixture/$scenario.stdout 2>$fixture/$scenario.stderr; then
      fail "$scenario unexpectedly succeeded"
    fi
    assert_eq "$(<$state_db)" old-db
    [[ ! -e $HOME/managed && ! -L $HOME/managed ]] || fail "$scenario mutated the live target"
    [[ ! -e $HOME/escape && ! -L $HOME/escape ]] || fail "$scenario traversed outside projection"
    tx_root=$XDG_STATE_HOME/chezmoi/private-skill-transaction
    [[ ! -d $tx_root/apply-recovery ]] || fail "$scenario published encrypted recovery"
    [[ -z $(find $tx_root -maxdepth 1 -type d -name 'phase.apply.*' -print -quit) ]] ||
      fail "$scenario leaked a plaintext apply phase"
    [[ -z $(find $tx_root -type f \( -name 'desired.tar' -o -name 'persistent-state' -o -name 'archive-members' \) -print -quit) ]] ||
      fail "$scenario leaked projection plaintext"
    [[ -z $(find ${state_db:h} -maxdepth 1 -name '.chezmoistate.boltdb.private-skill-tx.*' -print -quit) ]] ||
      fail "$scenario leaked a staged persistent-state copy"
  done
}

test_apply_rejects_uncontained_flags() {
  local flag state_db marker
  for flag in --parent-dirs -P --init --dry-run -n; do
    new_fixture
    make_age_fixture
    install_fake_chezmoi empty
    state_db=$fixture/chezmoistate.boltdb
    print -r -- old-db >$state_db
    chmod 600 $state_db
    marker=$HOME/parent-marker
    print -r -- unchanged >$marker
    invocation=$fixture/fake-invoked
    if PRIVATE_SKILL_TEST_INVOCATION_MARKER=$invocation $cli apply --identity $fixture/identity.txt --persistent-state $state_db \
      --chezmoi $fixture/bin/fake-chezmoi -- $flag $HOME/managed >/dev/null 2>&1; then
      fail "$flag was accepted"
    fi
    assert_eq "$(<$marker)" unchanged
    assert_eq "$(<$state_db)" old-db
    [[ ! -e $HOME/managed && ! -e $HOME/.config/chezmoi ]] || fail "$flag caused an uncontained side effect"
    [[ ! -e $invocation ]] || fail "$flag reached chezmoi before rejection"
    [[ ! -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/apply-recovery ]] || fail "$flag published recovery"
  done
}

test_apply_preserves_concurrent_live_database_edit() {
  new_fixture
  make_age_fixture
  install_fake_chezmoi db-only
  state_db=$fixture/chezmoistate.boltdb
  print -r -- old-db >$state_db
  chmod 600 $state_db
  set +e
  PRIVATE_SKILL_TEST_LIVE_DB=$state_db $cli apply --identity $fixture/identity.txt \
    --persistent-state $state_db --chezmoi $fixture/bin/fake-chezmoi -- $HOME/managed >/dev/null 2>&1
  exit_status=$?
  set -e
  ((exit_status != 0)) || fail 'concurrent live DB edit unexpectedly committed'
  assert_eq "$(<$state_db)" concurrent-live-db
  tx_root=$XDG_STATE_HOME/chezmoi/private-skill-transaction
  [[ -d $tx_root/apply-recovery ]] || fail 'concurrent DB conflict discarded encrypted recovery'
  [[ -z $(find $tx_root -maxdepth 1 -name 'phase.*' -print -quit) ]] || fail 'concurrent DB conflict retained plaintext'
  [[ -z $(find ${state_db:h} -maxdepth 1 -name '.chezmoistate.boltdb.private-skill-tx.*' -print -quit) ]] ||
    fail 'concurrent DB conflict retained a staged database'
}

test_committed_crash_cleanup_and_manifest_binding() {
  new_fixture
  make_age_fixture
  encrypt_value alpha $fixture/source/a.path.age
  encrypt_value "$(skill_text alpha new)" $fixture/source/a.md.age
  if PRIVATE_SKILL_TX_TEST_FAILURE=commit-kill $cli restore --identity $fixture/identity.txt \
    --pair $fixture/source/a.path.age $fixture/source/a.md.age >/dev/null 2>&1; then
    fail 'committed crash injection unexpectedly succeeded'
  fi
  [[ -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/recovery ]] || fail 'committed recovery was not retained'
  cp $XDG_STATE_HOME/chezmoi/private-skill-transaction/recovery/new.age $fixture/new.age.saved
  print -r -- tamper >>$XDG_STATE_HOME/chezmoi/private-skill-transaction/recovery/new.age
  if $cli recover --identity $fixture/identity.txt >/dev/null 2>&1; then
    fail 'tampered finalized manifest was accepted'
  fi
  [[ -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/recovery ]] || fail 'tampered recovery was discarded'
  cp $fixture/new.age.saved $XDG_STATE_HOME/chezmoi/private-skill-transaction/recovery/new.age
  chmod 600 $XDG_STATE_HOME/chezmoi/private-skill-transaction/recovery/new.age
  $cli recover --identity $fixture/identity.txt
  [[ ! -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/recovery ]] || fail 'committed recovery was not cleaned'
  assert_eq "$(<$HOME/.agents/skills/alpha/SKILL.md)" "$(skill_text alpha new)"
}
