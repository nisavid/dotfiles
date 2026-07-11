# Explicit target-set projection, rollback, and conflict scenarios.

assert_outer_target_old_set() {
  assert_eq "$(<$APPLY_REGULAR)" old-file
  [[ -d $APPLY_TRANSITION && ! -L $APPLY_TRANSITION ]] || fail 'directory target type was not restored'
  [[ $(stat -f '%Lp' $APPLY_TRANSITION) == 500 ]] || fail 'restrictive directory target mode was not restored'
  assert_eq "$(<$APPLY_TRANSITION/child)" old-directory
  [[ $(stat -f '%Lp' $APPLY_TRANSITION/child) == 644 ]] || fail 'directory child mode was not restored'
  [[ ! -e $APPLY_ABSENT && ! -L $APPLY_ABSENT ]] || fail 'old-absent target was created'
  assert_eq "$(<$APPLY_NESTED)" old-nested
  [[ ! -e $APPLY_LOGICAL && ! -L $APPLY_LOGICAL ]] || fail 'logical run-script target was created'
}

assert_outer_target_new_set() {
  assert_eq "$(<$APPLY_REGULAR)" new-file
  [[ $(stat -f '%Lp' $APPLY_REGULAR) == 644 ]] || fail 'public file target mode was not retained'
  [[ -L $APPLY_TRANSITION && $(readlink $APPLY_TRANSITION) == $APPLY_LINK_DEST ]] ||
    fail 'directory-to-symlink target was not retained'
  assert_eq "$(<$APPLY_ABSENT)" new-absent
  [[ $(stat -f '%Lp' $APPLY_ABSENT) == 644 ]] || fail 'new public file target mode was not retained'
  assert_eq "$(<$APPLY_NESTED)" new-nested
  [[ $(stat -f '%Lp' $APPLY_NESTED) == 644 ]] || fail 'nested public file target mode was not retained'
  [[ ! -e $APPLY_LOGICAL && ! -L $APPLY_LOGICAL ]] || fail 'logical run-script target became persistent'
}

setup_outer_target_fixture() {
    new_fixture
    make_age_fixture
    mkdir -m 700 -p $fixture/bin $HOME/transition $HOME/ordinary-parent
    export APPLY_REGULAR=$HOME/regular.txt
    export APPLY_TRANSITION=$HOME/transition
    export APPLY_ABSENT=$HOME/absent.txt
    export APPLY_NESTED=$HOME/ordinary-parent/nested.txt
    export APPLY_LOGICAL=$HOME/run_once_restore-private-skills.sh
    export APPLY_LINK_DEST=$fixture/link-destination
    print -r -- old-file >$APPLY_REGULAR
    print -r -- old-directory >$APPLY_TRANSITION/child
    print -r -- old-nested >$APPLY_NESTED
    chmod 600 $APPLY_REGULAR $APPLY_NESTED
    chmod 644 $APPLY_TRANSITION/child
    chmod 500 $APPLY_TRANSITION
    state_db=$fixture/chezmoistate.boltdb
    print -r -- old-db >$state_db
    chmod 600 $state_db
    install_fake_chezmoi target-set
    export APPLY_PROJECTION=$fixture/projection
    targets=(--force $APPLY_REGULAR $APPLY_TRANSITION $APPLY_ABSENT $APPLY_NESTED)
    wrapper=(--ephemeral-target $APPLY_LOGICAL)
}

outer_target_scenario_catchable_failure() {
  setup_outer_target_fixture
    if PRIVATE_SKILL_TEST_APPLY_MODE=fail $cli apply --identity $fixture/identity.txt \
      --persistent-state $state_db --chezmoi $fixture/bin/fake-chezmoi $wrapper -- $targets >/dev/null 2>&1; then
      fail 'catchable whole-target apply failure unexpectedly succeeded'
    fi
    assert_eq "$(<$state_db)" old-db
    assert_outer_target_old_set
    [[ ! -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/apply-recovery ]] ||
      fail 'catchable whole-target rollback retained recovery'
}

outer_target_scenario_killed_recovery() {
  setup_outer_target_fixture
    if PRIVATE_SKILL_TEST_APPLY_MODE=kill $cli apply --identity $fixture/identity.txt \
      --persistent-state $state_db --chezmoi $fixture/bin/fake-chezmoi $wrapper -- $targets >/dev/null 2>&1; then
      fail 'killed whole-target apply unexpectedly succeeded'
    fi
    $cli recover --identity $fixture/identity.txt
    assert_eq "$(<$state_db)" old-db
    assert_outer_target_old_set

}

outer_target_scenario_mixed_type_recovery() {
  setup_outer_target_fixture
    if PRIVATE_SKILL_TEST_APPLY_MODE=kill-mixed $cli apply --identity $fixture/identity.txt \
      --persistent-state $state_db --chezmoi $fixture/bin/fake-chezmoi $wrapper -- $targets >/dev/null 2>&1; then
      fail 'mixed killed whole-target apply unexpectedly succeeded'
    fi
    $cli recover --identity $fixture/identity.txt
    assert_outer_target_old_set
}

outer_target_scenario_pending_conflict() {
  setup_outer_target_fixture
    if PRIVATE_SKILL_TEST_APPLY_MODE=kill-mixed $cli apply --identity $fixture/identity.txt \
      --persistent-state $state_db --chezmoi $fixture/bin/fake-chezmoi $wrapper -- $targets >/dev/null 2>&1; then
      fail 'conflicting mixed killed apply unexpectedly succeeded'
    fi
    [[ -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/apply-recovery ]] ||
      fail 'mixed killed apply did not retain outer recovery'
    print -r -- third-party >$APPLY_REGULAR
    if $cli recover --identity $fixture/identity.txt >/dev/null 2>&1; then
      fail 'pending recovery overwrote an unexpected third-party edit'
    fi
    assert_eq "$(<$APPLY_REGULAR)" third-party
    [[ -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/apply-recovery ]] ||
      fail 'pending conflict discarded outer recovery'
    print -r -- new-file >$APPLY_REGULAR
    chmod 644 $APPLY_REGULAR
    $cli recover --identity $fixture/identity.txt
    assert_outer_target_old_set
}

outer_target_scenario_ephemeral_conflict() {
  setup_outer_target_fixture
    if PRIVATE_SKILL_TEST_APPLY_MODE=kill-ephemeral $cli apply --identity $fixture/identity.txt \
      --persistent-state $state_db --chezmoi $fixture/bin/fake-chezmoi $wrapper -- $targets >/dev/null 2>&1; then
      fail 'pending ephemeral-path crash unexpectedly succeeded'
    fi
    if $cli recover --identity $fixture/identity.txt >/dev/null 2>&1; then
      fail 'pending recovery accepted creation of an ephemeral logical path'
    fi
    assert_eq "$(<$APPLY_LOGICAL)" unexpected
    [[ -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/apply-recovery ]] ||
      fail 'ephemeral-path conflict discarded outer recovery'
    rm $APPLY_LOGICAL
    $cli recover --identity $fixture/identity.txt
    assert_outer_target_old_set
}

outer_target_scenario_post_apply_conflict() {
  setup_outer_target_fixture
    if PRIVATE_SKILL_TEST_APPLY_MODE=success-conflict $cli apply --identity $fixture/identity.txt \
      --persistent-state $state_db --chezmoi $fixture/bin/fake-chezmoi $wrapper -- $targets >/dev/null 2>&1; then
      fail 'post-apply concurrent edit was learned as desired state'
    fi
    assert_eq "$(<$APPLY_REGULAR)" concurrent-after-apply
    [[ -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/apply-recovery ]] ||
      fail 'post-apply conflict discarded outer recovery'
    print -r -- new-file >$APPLY_REGULAR
    chmod 644 $APPLY_REGULAR
    $cli recover --identity $fixture/identity.txt
    assert_outer_target_old_set
}

outer_target_scenario_symlink_ancestor_conflict() {
  setup_outer_target_fixture
    if PRIVATE_SKILL_TEST_APPLY_MODE=kill $cli apply --identity $fixture/identity.txt \
      --persistent-state $state_db --chezmoi $fixture/bin/fake-chezmoi $wrapper -- $targets >/dev/null 2>&1; then
      fail 'symlink-ancestor crash unexpectedly succeeded'
    fi
    mkdir -m 700 $fixture/outside-recovery
    print -r -- outside-safe >$fixture/outside-recovery/nested.txt
    rm -rf $HOME/ordinary-parent
    ln -s $fixture/outside-recovery $HOME/ordinary-parent
    if $cli recover --identity $fixture/identity.txt >/dev/null 2>&1; then
      fail 'recovery traversed a replaced symlink ancestor'
    fi
    assert_eq "$(<$fixture/outside-recovery/nested.txt)" outside-safe
    rm $HOME/ordinary-parent
    mkdir -m 700 $HOME/ordinary-parent
    print -r -- new-nested >$APPLY_NESTED
    chmod 644 $APPLY_NESTED
    $cli recover --identity $fixture/identity.txt
    assert_outer_target_old_set
}

outer_target_scenario_persistent_state_conflict() {
  setup_outer_target_fixture
    if PRIVATE_SKILL_TX_TEST_FAILURE=apply-post-install-db-conflict $cli apply --identity $fixture/identity.txt \
      --persistent-state $state_db --chezmoi $fixture/bin/fake-chezmoi $wrapper -- $targets >/dev/null 2>&1; then
      fail 'post-install persistent-state conflict unexpectedly committed'
    fi
    assert_eq "$(<$state_db)" concurrent-db
    [[ -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/apply-recovery ]] ||
      fail 'post-install persistent-state conflict discarded outer recovery'
    print -r -- updated-db >$state_db
    chmod 600 $state_db
    $cli recover --identity $fixture/identity.txt
    assert_outer_target_new_set
}

outer_target_scenario_committed_recovery() {
  setup_outer_target_fixture
    if PRIVATE_SKILL_TX_TEST_FAILURE=apply-commit-kill $cli apply --identity $fixture/identity.txt \
      --persistent-state $state_db --chezmoi $fixture/bin/fake-chezmoi $wrapper -- $targets >/dev/null 2>&1; then
      fail 'committed whole-target crash unexpectedly succeeded'
    fi
    pointer=$XDG_STATE_HOME/chezmoi/private-skill-transaction/apply-recovery/pointer
    cp $pointer $fixture/apply-pointer.saved
    sed 's/^version=.*/version=2/' $fixture/apply-pointer.saved >$pointer
    chmod 600 $pointer
    if $cli recover --identity $fixture/identity.txt >/dev/null 2>&1; then
      fail 'outer recovery accepted an unknown pointer version'
    fi
    [[ -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/apply-recovery ]] ||
      fail 'unknown pointer version discarded encrypted outer recovery'
    cp $fixture/apply-pointer.saved $pointer
    chmod 600 $pointer
    sed 's/^state=.*/state=bogus/' $fixture/apply-pointer.saved >$pointer
    chmod 600 $pointer
    if $cli recover --identity $fixture/identity.txt >/dev/null 2>&1; then
      fail 'outer recovery accepted an unknown pointer state'
    fi
    [[ -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/apply-recovery ]] ||
      fail 'unknown pointer state discarded encrypted outer recovery'
    cp $fixture/apply-pointer.saved $pointer
    chmod 600 $pointer
    print -r -- concurrent-edit >$APPLY_REGULAR
    if $cli recover --identity $fixture/identity.txt >/dev/null 2>&1; then
      fail 'committed whole-target recovery accepted a visible conflict'
    fi
    assert_eq "$(<$APPLY_REGULAR)" concurrent-edit
    [[ -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/apply-recovery ]] ||
      fail 'committed target conflict discarded recovery'
    [[ -z $(find $XDG_STATE_HOME/chezmoi/private-skill-transaction -maxdepth 1 -name 'phase.apply-recover.*' -print -quit) ]] ||
      fail "committed target conflict retained decrypted recovery state: $(find $XDG_STATE_HOME/chezmoi/private-skill-transaction -maxdepth 1 -name 'phase.apply-recover.*' -print)"
    print -r -- new-file >$APPLY_REGULAR
    chmod 644 $APPLY_REGULAR
    $cli recover --identity $fixture/identity.txt
    assert_eq "$(<$state_db)" updated-db
    assert_outer_target_new_set
    [[ ! -d $XDG_STATE_HOME/chezmoi/private-skill-transaction/apply-recovery ]] ||
      fail 'committed whole-target recovery was not cleaned'
}

outer_target_scenario_input_validation() {
  setup_outer_target_fixture
    if $cli apply --identity $fixture/identity.txt --persistent-state $state_db \
      --chezmoi $fixture/bin/fake-chezmoi -- relative-target >/dev/null 2>&1; then
      fail 'relative target operand was accepted'
    fi
    if $cli apply --identity $fixture/identity.txt --persistent-state $state_db \
      --chezmoi $fixture/bin/fake-chezmoi -- --output value $APPLY_REGULAR >/dev/null 2>&1; then
      fail 'ambiguous apply flag operand was accepted'
    fi

    invalid_targets=("$HOME/trailing/" "$HOME//double" "$HOME/dot/./file" "$HOME/dot/../file" $'/'$'control\tpath' /)
    for target in $invalid_targets; do
      if $cli apply --identity $fixture/identity.txt --persistent-state $state_db \
        --chezmoi $fixture/bin/fake-chezmoi -- "$target" >/dev/null 2>&1; then
        fail "lexically ambiguous target was accepted: $target"
      fi
    done
    mkdir -m 700 $fixture/outside
    print -r -- outside-old >$fixture/outside/data
    chmod 600 $fixture/outside/data
    ln -s $fixture/outside $HOME/escape
    if $cli apply --identity $fixture/identity.txt --persistent-state $state_db \
      --chezmoi $fixture/bin/fake-chezmoi -- $HOME/escape/data >/dev/null 2>&1; then
      fail 'target through a symlink ancestor was accepted'
    fi
    assert_eq "$(<$fixture/outside/data)" outside-old

    for pair in "$HOME/overlap $HOME/overlap/child" "$HOME/overlap/child $HOME/overlap"; do
      overlap_targets=(${=pair})
      if $cli apply --identity $fixture/identity.txt --persistent-state $state_db \
        --chezmoi $fixture/bin/fake-chezmoi -- $overlap_targets >/dev/null 2>&1; then
        fail "overlapping targets were accepted: $pair"
      fi
    done
}

test_outer_apply_protects_every_explicit_target() {
  outer_target_scenario_catchable_failure
  outer_target_scenario_killed_recovery
  outer_target_scenario_mixed_type_recovery
  outer_target_scenario_pending_conflict
  outer_target_scenario_ephemeral_conflict
  outer_target_scenario_post_apply_conflict
  outer_target_scenario_symlink_ancestor_conflict
  outer_target_scenario_persistent_state_conflict
  outer_target_scenario_committed_recovery
  outer_target_scenario_input_validation
}

assert_git_publication_old_set() {
  [[ -d $APPLY_SKILL && ! -L $APPLY_SKILL ]] || fail 'old skill directory was not restored'
  assert_eq "$(<$APPLY_SKILL/SKILL.md)" old-skill
  [[ -L $APPLY_CLAUDE_LINK ]] || fail 'old Claude symlink was not restored'
  assert_eq "$(readlink $APPLY_CLAUDE_LINK)" ../old-skill
  assert_eq "$(<$APPLY_AGENTS)" old-agents
}

assert_git_publication_new_set() {
  [[ -d $APPLY_SKILL && ! -L $APPLY_SKILL ]] || fail 'new skill directory was not retained'
  assert_eq "$(<$APPLY_SKILL/SKILL.md)" new-skill
  [[ -L $APPLY_CLAUDE_LINK ]] || fail 'new Claude symlink was not retained'
  assert_eq "$(readlink $APPLY_CLAUDE_LINK)" ../../.agents/skills/checkpointing-and-publishing-git-work
  assert_eq "$(<$APPLY_AGENTS)" new-agents
}

assert_git_publication_no_residue() {
  tx_root=$XDG_STATE_HOME/chezmoi/private-skill-transaction
  [[ ! -d $tx_root/apply-recovery ]] || fail 'Git publication activation retained encrypted recovery'
  [[ -z $(find $tx_root -maxdepth 1 -type d -name 'phase.*' -print -quit) ]] ||
    fail 'Git publication activation retained plaintext transaction state'
  [[ -z $(find ${state_db:h} -maxdepth 1 -name '.chezmoistate.boltdb.private-skill-tx.*' -print -quit) ]] ||
    fail 'Git publication activation retained persistent-state staging residue'
}

setup_git_publication_target_fixture() {
  new_fixture
  make_age_fixture
  mkdir -m 700 -p "$fixture/bin" "$HOME/.agents/skills/checkpointing-and-publishing-git-work" \
    "$HOME/.claude/skills" "$HOME/.codex"
  export APPLY_SKILL=$HOME/.agents/skills/checkpointing-and-publishing-git-work
  export APPLY_CLAUDE_LINK=$HOME/.claude/skills/checkpointing-and-publishing-git-work
  export APPLY_AGENTS=$HOME/.codex/AGENTS.md
  printf '%s\n' old-skill >$APPLY_SKILL/SKILL.md
  ln -s ../old-skill $APPLY_CLAUDE_LINK
  printf '%s\n' old-agents >$APPLY_AGENTS
  state_db=$fixture/chezmoistate.boltdb
  printf '%s\n' old-db >$state_db
  chmod 600 $state_db
  install_fake_chezmoi git-publication-target-set
  export APPLY_PROJECTION=$fixture/projection
  targets=(--force $APPLY_SKILL $APPLY_CLAUDE_LINK $APPLY_AGENTS)
}

test_git_publication_activation_target_set() {
  local failure
  for failure in fail-after-skill fail-after-link fail-after-agents fail-state; do
    setup_git_publication_target_fixture
    if PRIVATE_SKILL_TEST_APPLY_MODE=$failure $cli apply --identity $fixture/identity.txt \
      --persistent-state $state_db --chezmoi $fixture/bin/fake-chezmoi -- $targets >/dev/null 2>&1; then
      fail "$failure unexpectedly activated the Git publication target set"
    fi
    assert_eq "$(<$state_db)" old-db
    assert_git_publication_old_set
    assert_git_publication_no_residue
  done

  for failure in apply-new-manifest-fail apply-new-encryption-fail apply-ready-pointer-fail; do
    setup_git_publication_target_fixture
    if PRIVATE_SKILL_TX_TEST_FAILURE=$failure $cli apply --identity $fixture/identity.txt \
      --persistent-state $state_db --chezmoi $fixture/bin/fake-chezmoi -- $targets >/dev/null 2>&1; then
      fail "$failure unexpectedly activated the Git publication target set"
    fi
    assert_eq "$(<$state_db)" old-db
    assert_git_publication_old_set
    assert_git_publication_no_residue
  done

  setup_git_publication_target_fixture
  $cli apply --identity $fixture/identity.txt --persistent-state $state_db \
    --chezmoi $fixture/bin/fake-chezmoi -- $targets
  assert_eq "$(<$state_db)" updated-db
  assert_git_publication_new_set
  assert_git_publication_no_residue
}
