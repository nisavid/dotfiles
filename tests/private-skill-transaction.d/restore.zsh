# Standalone restore, recovery, and conflict scenarios.

test_successful_two_skill_restore() {
  new_fixture
  make_age_fixture
  encrypt_value alpha $fixture/source/alpha.path.age
  encrypt_value "$(skill_text alpha 'alpha secret')" $fixture/source/alpha.md.age
  encrypt_value nested/beta $fixture/source/beta.path.age
  encrypt_value "$(skill_text beta 'beta secret')" $fixture/source/beta.md.age

  $cli restore --identity $fixture/identity.txt \
    --pair $fixture/source/alpha.path.age $fixture/source/alpha.md.age \
    --pair $fixture/source/beta.path.age $fixture/source/beta.md.age

  assert_eq "$(<$HOME/.agents/skills/alpha/SKILL.md)" "$(skill_text alpha 'alpha secret')"
  assert_eq "$(<$HOME/.agents/skills/nested/beta/SKILL.md)" "$(skill_text beta 'beta secret')"
  assert_eq "$(readlink $HOME/.claude/skills/alpha)" '../../.agents/skills/alpha'
  assert_eq "$(readlink $HOME/.claude/skills/nested/beta)" '../../../.agents/skills/nested/beta'
  [[ ! -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/recovery ]] ||
    fail 'committed recovery state was not cleaned'
}

test_validation_failures_have_no_partial_update() {
  local scenario
  for scenario in decrypt traversal duplicate ancestor-first descendant-first frontmatter \
    missing-closing post-close-name duplicate-name; do
    new_fixture
    make_age_fixture
    mkdir -m 700 -p $HOME/.agents/skills/alpha
    print -r -- old >$HOME/.agents/skills/alpha/SKILL.md
    chmod 600 $HOME/.agents/skills/alpha/SKILL.md
    encrypt_value alpha $fixture/source/a.path.age
    encrypt_value "$(skill_text alpha new)" $fixture/source/a.md.age
    case $scenario in
      decrypt) print -r -- garbage >$fixture/source/a.md.age ;;
      traversal) encrypt_value ../escape $fixture/source/a.path.age ;;
      frontmatter) encrypt_value 'not frontmatter' $fixture/source/a.md.age ;;
      missing-closing) encrypt_value $'---\nname: alpha\ndescription: never closed' $fixture/source/a.md.age ;;
      post-close-name) encrypt_value $'---\ndescription: no name\n---\nname: alpha' $fixture/source/a.md.age ;;
      duplicate-name) encrypt_value $'---\nname: alpha\nname: alpha\n---\nbody' $fixture/source/a.md.age ;;
      duplicate)
        encrypt_value alpha $fixture/source/b.path.age
        encrypt_value "$(skill_text alpha other)" $fixture/source/b.md.age
        ;;
      ancestor-first)
        encrypt_value alpha/child $fixture/source/b.path.age
        encrypt_value "$(skill_text child other)" $fixture/source/b.md.age
        ;;
      descendant-first)
        encrypt_value alpha/child $fixture/source/a.path.age
        encrypt_value "$(skill_text child new)" $fixture/source/a.md.age
        encrypt_value alpha $fixture/source/b.path.age
        encrypt_value "$(skill_text alpha other)" $fixture/source/b.md.age
        ;;
    esac
    args=(restore --identity $fixture/identity.txt --pair $fixture/source/a.path.age $fixture/source/a.md.age)
    if [[ $scenario == duplicate || $scenario == ancestor-first || $scenario == descendant-first ]]; then
      args+=(--pair $fixture/source/b.path.age $fixture/source/b.md.age)
    fi
    if $cli $args 2>/dev/null; then
      fail "$scenario validation unexpectedly succeeded"
    fi
    assert_eq "$(<$HOME/.agents/skills/alpha/SKILL.md)" old
    [[ ! -e $HOME/escape ]] || fail "$scenario wrote outside the target root"
  done
}

test_control_character_targets_are_rejected() {
  local label value normalized
  for label in tab newline carriage nul soh unit-separator delete; do
    new_fixture
    make_age_fixture
    case $label in
      tab) value=$'alpha\tbeta' ;;
      newline) value=$'alpha\nbeta' ;;
      carriage) value=$'alpha\rbeta' ;;
      nul) value=alpha ;;
      soh) value=$'alpha\x01beta' ;;
      unit-separator) value=$'alpha\x1fbeta' ;;
      delete) value=$'alpha\x7fbeta' ;;
    esac
    normalized=$(printf '%s' "$value" | awk 'BEGIN { ORS="" } { gsub(/^[[:space:]]+|[[:space:]]+$/, ""); printf "%s", $0 }')
    if [[ $label == nul ]]; then
      printf 'alpha\0beta' >$fixture/plain/input
      chmod 600 $fixture/plain/input
      age -r $recipient -o $fixture/source/a.path.age $fixture/plain/input
      rm -f $fixture/plain/input
    else
      encrypt_value "$value" $fixture/source/a.path.age
    fi
    encrypt_value "$(skill_text "$normalized" body)" $fixture/source/a.md.age
    if $cli restore --identity $fixture/identity.txt \
      --pair $fixture/source/a.path.age $fixture/source/a.md.age >/dev/null 2>&1; then
      fail "$label control character was accepted in a target"
    fi
    [[ ! -e $HOME/.agents/skills/alpha && ! -e $HOME/.claude/skills/alpha ]] ||
      fail "$label control-character target caused a partial update"
  done
}

test_restore_prepublication_crash_boundaries() {
  local boundary
  for boundary in restore-encryption-fail restore-before-encryption-kill restore-between-encryption-kill \
    restore-before-pointer-kill restore-after-pointer-kill restore-after-publish-kill; do
    new_fixture
    make_age_fixture
    encrypt_value alpha $fixture/source/a.path.age
    encrypt_value "$(skill_text alpha new)" $fixture/source/a.md.age
    mkdir -m 700 -p $HOME/.agents/skills/alpha
    print -r -- old >$HOME/.agents/skills/alpha/SKILL.md
    chmod 600 $HOME/.agents/skills/alpha/SKILL.md
    if PRIVATE_SKILL_TX_TEST_FAILURE=$boundary $cli restore --identity $fixture/identity.txt \
      --pair $fixture/source/a.path.age $fixture/source/a.md.age >/dev/null 2>&1; then
      fail "$boundary unexpectedly succeeded"
    fi
    $cli recover --identity $fixture/identity.txt
    assert_eq "$(<$HOME/.agents/skills/alpha/SKILL.md)" old
    [[ ! -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/recovery ]] ||
      fail "$boundary left durable recovery after next acquisition"
    [[ -z $(find $XDG_STATE_HOME/chezmoi/private-skill-transaction -maxdepth 1 -name 'phase.restore.*' -print -quit) ]] ||
      fail "$boundary left an orphan restore phase"
  done
}

test_all_public_acquisitions_clean_orphan_prepublication_phases() {
  local entry tx_root
  for entry in with-lock restore recover apply; do
    new_fixture
    make_age_fixture
    tx_root=$XDG_STATE_HOME/chezmoi/private-skill-transaction
    mkdir -m 700 $tx_root
    : >$tx_root/lock
    chmod 600 $tx_root/lock
    mkdir -m 700 $tx_root/phase.restore.orphan $tx_root/phase.apply.orphan
    case $entry in
      with-lock) $cli with-lock /usr/bin/true ;;
      recover) $cli recover --identity $fixture/identity.txt ;;
      restore)
        encrypt_value alpha $fixture/source/a.path.age
        encrypt_value "$(skill_text alpha new)" $fixture/source/a.md.age
        $cli restore --identity $fixture/identity.txt \
          --pair $fixture/source/a.path.age $fixture/source/a.md.age
        ;;
      apply)
        mkdir -m 700 $fixture/bin
        install_fake_chezmoi empty
        print -r -- state >$fixture/state.db
        chmod 600 $fixture/state.db
        $cli apply --identity $fixture/identity.txt --persistent-state $fixture/state.db \
          --chezmoi $fixture/bin/fake-chezmoi -- $HOME/.codex/AGENTS.md
        ;;
    esac
    [[ ! -d $tx_root/phase.restore.orphan && ! -d $tx_root/phase.apply.orphan ]] ||
      fail "$entry did not clean safe orphan prepublication phases"
  done
}

test_catchable_and_killed_recovery_with_type_transitions() {
  local failure
  for failure in catch kill; do
    new_fixture
    make_age_fixture
    encrypt_value alpha $fixture/source/a.path.age
    encrypt_value "$(skill_text alpha new)" $fixture/source/a.md.age
    mkdir -m 700 -p $HOME/.agents/skills $HOME/.claude/skills/alpha
    print -r -- old-file >$HOME/.agents/skills/alpha
    chmod 600 $HOME/.agents/skills/alpha
    print -r -- old-child >$HOME/.claude/skills/alpha/child
    chmod 600 $HOME/.claude/skills/alpha/child

    if PRIVATE_SKILL_TX_TEST_FAILURE=$failure $cli restore --identity $fixture/identity.txt \
      --pair $fixture/source/a.path.age $fixture/source/a.md.age >/dev/null 2>&1; then
      fail "$failure failure injection unexpectedly succeeded"
    fi
    if [[ $failure == catch ]]; then
      [[ -f $HOME/.agents/skills/alpha && ! -L $HOME/.agents/skills/alpha ]] ||
        fail 'catchable failure did not roll back immediately'
      assert_eq "$(<$HOME/.agents/skills/alpha)" old-file
    fi
    $cli recover --identity $fixture/identity.txt
    [[ -f $HOME/.agents/skills/alpha && ! -L $HOME/.agents/skills/alpha ]] ||
      fail "$failure recovery did not restore file type"
    assert_eq "$(<$HOME/.agents/skills/alpha)" old-file
    [[ -d $HOME/.claude/skills/alpha && -f $HOME/.claude/skills/alpha/child ]] ||
      fail "$failure recovery did not restore directory type"
    [[ ! -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/recovery ]] ||
      fail "$failure recovery did not clean durable state"
  done
}

test_restore_signals_roll_back_immediately() {
  local signal expected exit_status
  for signal expected in hup 129 int 130 term 143; do
    new_fixture
    make_age_fixture
    encrypt_value alpha $fixture/source/a.path.age
    encrypt_value "$(skill_text alpha new)" $fixture/source/a.md.age
    mkdir -m 700 -p $HOME/.agents/skills/alpha
    print -r -- old >$HOME/.agents/skills/alpha/SKILL.md
    chmod 600 $HOME/.agents/skills/alpha/SKILL.md

    set +e
    PRIVATE_SKILL_TX_TEST_FAILURE=restore-signal-$signal $cli restore --identity $fixture/identity.txt \
      --pair $fixture/source/a.path.age $fixture/source/a.md.age >/dev/null 2>&1
    exit_status=$?
    set -e

    assert_eq "$exit_status" "$expected"
    assert_eq "$(<$HOME/.agents/skills/alpha/SKILL.md)" old
    [[ ! -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/recovery ]] ||
      fail "$signal restore retained recovery"
    [[ -z $(find $XDG_STATE_HOME/chezmoi/private-skill-transaction -maxdepth 1 -name 'phase.*' -print -quit) ]] ||
      fail "$signal restore retained plaintext phase state"
  done
}

test_private_skill_ancestor_containment() {
  local surface target_parent outside tx_root
  for surface in agents claude; do
    new_fixture
    make_age_fixture
    encrypt_value nested/alpha $fixture/source/a.path.age
    encrypt_value "$(skill_text alpha new)" $fixture/source/a.md.age
    outside=$fixture/outside
    mkdir -m 700 -p $outside $HOME/.$surface/skills
    print -r -- outside-safe >$outside/marker
    ln -s $outside $HOME/.$surface/skills/nested

    if $cli restore --identity $fixture/identity.txt \
      --pair $fixture/source/a.path.age $fixture/source/a.md.age >/dev/null 2>&1; then
      fail "initial restore accepted a $surface symlink ancestor"
    fi
    assert_eq "$(<$outside/marker)" outside-safe
    [[ ! -e $outside/alpha && ! -L $outside/alpha ]] || fail "initial restore escaped through $surface"
    tx_root=$XDG_STATE_HOME/chezmoi/private-skill-transaction
    [[ ! -d $tx_root/recovery ]] || fail "initial $surface ancestor rejection published recovery"
    [[ -z $(find $tx_root -maxdepth 1 -name 'phase.*' -print -quit) ]] ||
      fail "initial $surface ancestor rejection retained plaintext"
  done

  for surface in agents claude; do
    new_fixture
    make_age_fixture
    encrypt_value nested/alpha $fixture/source/a.path.age
    encrypt_value "$(skill_text alpha new)" $fixture/source/a.md.age
    if PRIVATE_SKILL_TX_TEST_FAILURE=kill $cli restore --identity $fixture/identity.txt \
      --pair $fixture/source/a.path.age $fixture/source/a.md.age >/dev/null 2>&1; then
      fail "recovery ancestor fixture for $surface unexpectedly succeeded"
    fi
    target_parent=$HOME/.$surface/skills/nested
    if [[ -d $target_parent && ! -L $target_parent ]]; then chmod -R u+rwx $target_parent; fi
    rm -rf $target_parent
    outside=$fixture/outside
    mkdir -m 700 $outside
    print -r -- outside-safe >$outside/marker
    ln -s $outside $target_parent

    if $cli recover --identity $fixture/identity.txt >/dev/null 2>&1; then
      fail "recovery accepted a replaced $surface symlink ancestor"
    fi
    assert_eq "$(<$outside/marker)" outside-safe
    [[ ! -e $outside/alpha && ! -L $outside/alpha ]] || fail "recovery escaped through $surface"
    tx_root=$XDG_STATE_HOME/chezmoi/private-skill-transaction
    [[ -d $tx_root/recovery ]] || fail "recovery discarded encrypted state after $surface rejection"
    [[ -z $(find $tx_root -maxdepth 1 -name 'phase.*' -print -quit) ]] ||
      fail "recovery $surface ancestor rejection retained plaintext"
  done
}

test_visible_conflict_and_absent_symlink_transitions() {
  new_fixture
  make_age_fixture
  encrypt_value alpha $fixture/source/a.path.age
  encrypt_value "$(skill_text alpha new)" $fixture/source/a.md.age
  mkdir -m 700 -p $HOME/.agents/skills $HOME/.claude/skills
  ln -s original-target $HOME/.agents/skills/alpha
  if PRIVATE_SKILL_TX_TEST_FAILURE=catch $cli restore --identity $fixture/identity.txt \
    --pair $fixture/source/a.path.age $fixture/source/a.md.age >/dev/null 2>&1; then
    fail 'catchable transition injection unexpectedly succeeded'
  fi
  [[ -L $HOME/.agents/skills/alpha && $(readlink $HOME/.agents/skills/alpha) == original-target ]] ||
    fail 'symlink-to-directory rollback failed'
  [[ ! -e $HOME/.claude/skills/alpha && ! -L $HOME/.claude/skills/alpha ]] ||
    fail 'old-absent target was not restored as absent'

  if PRIVATE_SKILL_TX_TEST_FAILURE=kill $cli restore --identity $fixture/identity.txt \
    --pair $fixture/source/a.path.age $fixture/source/a.md.age >/dev/null 2>&1; then
    fail 'killed transition injection unexpectedly succeeded'
  fi
  rm -rf $HOME/.agents/skills/alpha
  mkdir -m 700 $HOME/.agents/skills/alpha
  print -r -- concurrent >$HOME/.agents/skills/alpha/OTHER
  chmod 600 $HOME/.agents/skills/alpha/OTHER
  if $cli recover --identity $fixture/identity.txt >/dev/null 2>&1; then
    fail 'visible concurrent edit was overwritten'
  fi
  assert_eq "$(<$HOME/.agents/skills/alpha/OTHER)" concurrent
  [[ -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/recovery ]] || fail 'conflicting recovery was discarded'
}

test_directory_metadata_only_conflict() {
  new_fixture
  make_age_fixture
  encrypt_value alpha $fixture/source/a.path.age
  encrypt_value "$(skill_text alpha new)" $fixture/source/a.md.age
  mkdir -m 700 -p $HOME/.claude/skills/alpha
  print -r -- same-content >$HOME/.claude/skills/alpha/child
  chmod 600 $HOME/.claude/skills/alpha/child
  if PRIVATE_SKILL_TX_TEST_FAILURE=kill $cli restore --identity $fixture/identity.txt \
    --pair $fixture/source/a.path.age $fixture/source/a.md.age >/dev/null 2>&1; then
    fail 'metadata conflict crash injection unexpectedly succeeded'
  fi
  rm $HOME/.claude/skills/alpha
  mkdir -m 700 $HOME/.claude/skills/alpha
  print -r -- same-content >$HOME/.claude/skills/alpha/child
  chmod 644 $HOME/.claude/skills/alpha/child
  if $cli recover --identity $fixture/identity.txt >/dev/null 2>&1; then
    fail 'metadata-only directory conflict was accepted'
  fi
  [[ $(stat -f '%Lp' $HOME/.claude/skills/alpha/child) == 644 ]] ||
    fail 'metadata-only concurrent edit was overwritten'
  [[ -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/recovery ]] ||
    fail 'metadata-conflicting recovery was discarded'
}

test_final_desired_state_check_retains_conflict() {
  new_fixture
  make_age_fixture
  encrypt_value alpha $fixture/source/a.path.age
  encrypt_value "$(skill_text alpha new)" $fixture/source/a.md.age
  mkdir -m 700 -p $HOME/.agents/skills/alpha
  print -r -- old >$HOME/.agents/skills/alpha/SKILL.md
  chmod 600 $HOME/.agents/skills/alpha/SKILL.md
  if PRIVATE_SKILL_TX_TEST_FAILURE=final-check-conflict $cli restore --identity $fixture/identity.txt \
    --pair $fixture/source/a.path.age $fixture/source/a.md.age >/dev/null 2>&1; then
    fail 'final-check conflict unexpectedly committed'
  fi
  [[ -f $HOME/.agents/skills/alpha/SKILL.md && $(stat -f '%Lp' $HOME/.agents/skills/alpha/SKILL.md) == 644 ]] ||
    fail 'final-check conflict was overwritten'
  [[ -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/recovery ]] ||
    fail 'final-check conflict discarded durable recovery'
  pointer=$XDG_STATE_HOME/chezmoi/private-skill-transaction/recovery/pointer
  assert_eq "$(awk -F= '$1 == "state" { print $2 }' $pointer)" pending
  assert_eq "$(awk -F= '{ print $1 }' $pointer | paste -sd, -)" version,table,new,state
  [[ -z $(grep -E '^(operation|generation)=' $pointer || true) ]] || fail 'pointer retained inert fields'
}

test_recovery_tears_down_plaintext_before_encrypted_state() {
  new_fixture
  make_age_fixture
  encrypt_value alpha $fixture/source/a.path.age
  encrypt_value "$(skill_text alpha new)" $fixture/source/a.md.age
  if PRIVATE_SKILL_TX_TEST_FAILURE=kill $cli restore --identity $fixture/identity.txt \
    --pair $fixture/source/a.path.age $fixture/source/a.md.age >/dev/null 2>&1; then
    fail 'recovery teardown fixture unexpectedly succeeded'
  fi
  if PRIVATE_SKILL_TX_TEST_FAILURE=recovery-after-encrypted-removal-kill $cli recover \
    --identity $fixture/identity.txt >/dev/null 2>&1; then
    fail 'post-removal crash checkpoint unexpectedly succeeded'
  fi
  tx_root=$XDG_STATE_HOME/chezmoi/private-skill-transaction
  [[ ! -d $tx_root/recovery ]] || fail 'encrypted recovery remained after removal checkpoint'
  [[ -z $(find $tx_root -maxdepth 1 -name 'phase.*' -print -quit) ]] ||
    fail 'plaintext survived until after encrypted recovery removal'
}

test_outer_capability_binds_nested_finalization() {
  local marker state_db
  for marker in legacy stale; do
    new_fixture
    make_age_fixture
    encrypt_value alpha $fixture/source/a.path.age
    encrypt_value "$(skill_text alpha new)" $fixture/source/a.md.age
    if [[ $marker == legacy ]]; then
      PRIVATE_SKILL_TX_OUTER=1 $cli restore --identity $fixture/identity.txt \
        --pair $fixture/source/a.path.age $fixture/source/a.md.age
    else
      PRIVATE_SKILL_TX_OUTER_CAPABILITY=stale-token $cli restore --identity $fixture/identity.txt \
        --pair $fixture/source/a.path.age $fixture/source/a.md.age
    fi
    [[ ! -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/recovery ]] ||
      fail "$marker ambient marker deferred standalone finalization"
    assert_eq "$(<$HOME/.agents/skills/alpha/SKILL.md)" "$(skill_text alpha new)"
  done

  new_fixture
  make_age_fixture
  encrypt_value alpha $fixture/source/a.path.age
  encrypt_value "$(skill_text alpha nested)" $fixture/source/a.md.age
  install_fake_chezmoi nested-restore
  state_db=$fixture/chezmoistate.boltdb
  print -r -- old-db >$state_db
  chmod 600 $state_db
  export PRIVATE_SKILL_TEST_CLI=$cli PRIVATE_SKILL_TEST_IDENTITY=$fixture/identity.txt
  export PRIVATE_SKILL_TEST_PATH=$fixture/source/a.path.age PRIVATE_SKILL_TEST_BODY=$fixture/source/a.md.age
  $cli apply --identity $fixture/identity.txt --persistent-state $state_db \
    --chezmoi $fixture/bin/fake-chezmoi -- $HOME/.codex/AGENTS.md
  assert_eq "$(<$HOME/.agents/skills/alpha/SKILL.md)" "$(skill_text alpha nested)"
  [[ ! -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/recovery ]] ||
    fail 'valid nested outer capability was not finalized by the coordinator'
}

test_directory_snapshot_tree_contract() {
  local tx_root
  new_fixture
  make_age_fixture
  encrypt_value alpha $fixture/source/a.path.age
  encrypt_value "$(skill_text alpha new)" $fixture/source/a.md.age
  mkdir -m 700 -p $HOME/.agents/skills/alpha
  mkfifo $HOME/.agents/skills/alpha/unsupported.fifo
  if $cli restore --identity $fixture/identity.txt \
    --pair $fixture/source/a.path.age $fixture/source/a.md.age >/dev/null 2>&1; then
    fail 'directory snapshot accepted a FIFO descendant'
  fi
  [[ -p $HOME/.agents/skills/alpha/unsupported.fifo ]] || fail 'FIFO rejection mutated the original tree'
  tx_root=$XDG_STATE_HOME/chezmoi/private-skill-transaction
  [[ ! -d $tx_root/recovery ]] || fail 'FIFO snapshot rejection published recovery'
  [[ -z $(find $tx_root -maxdepth 1 -name 'phase.*' -print -quit) ]] || fail 'FIFO rejection retained plaintext'

  new_fixture
  make_age_fixture
  encrypt_value alpha $fixture/source/a.path.age
  encrypt_value "$(skill_text alpha new)" $fixture/source/a.md.age
  mkdir -m 700 -p $HOME/.agents/skills/alpha
  print -r -- ordinary >$HOME/.agents/skills/alpha/.tree-list.fixture
  chmod 600 $HOME/.agents/skills/alpha/.tree-list.fixture
  if PRIVATE_SKILL_TX_TEST_FAILURE=kill $cli restore --identity $fixture/identity.txt \
    --pair $fixture/source/a.path.age $fixture/source/a.md.age >/dev/null 2>&1; then
    fail 'tree-list filename recovery fixture unexpectedly succeeded'
  fi
  rm -rf $HOME/.agents/skills/alpha
  mkdir -m 700 $HOME/.agents/skills/alpha
  print -r -- ordinary >$HOME/.agents/skills/alpha/.tree-list.fixture
  chmod 600 $HOME/.agents/skills/alpha/.tree-list.fixture
  $cli recover --identity $fixture/identity.txt
  assert_eq "$(<$HOME/.agents/skills/alpha/.tree-list.fixture)" ordinary
  [[ $(stat -f '%Lp' $HOME/.agents/skills/alpha/.tree-list.fixture) == 600 ]] ||
    fail 'tree-list filename metadata was not restored'
}
