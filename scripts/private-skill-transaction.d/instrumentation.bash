# Test-only transaction failpoints. Production state machines call checkpoints without branching.

tx_failpoint() {
  local checkpoint=$1 configured=${PRIVATE_SKILL_TX_TEST_FAILURE:-}
  shift
  case $configured:$checkpoint in
    restore-encryption-fail:restore-before-old-encryption) die 'injected restore encryption failure' ;;
    restore-before-encryption-kill:restore-before-old-encryption) /bin/kill -KILL $$ ;;
    restore-between-encryption-kill:restore-after-old-encryption) /bin/kill -KILL $$ ;;
    restore-before-pointer-kill:restore-before-pointer) /bin/kill -KILL $$ ;;
    restore-after-pointer-kill:restore-after-pointer) /bin/kill -KILL $$ ;;
    restore-after-publish-kill:restore-after-publish) /bin/kill -KILL $$ ;;
    catch:restore-after-install) die 'injected catchable failure' ;;
    kill:restore-after-install) /bin/kill -KILL $$ ;;
    restore-signal-hup:restore-after-install) /bin/kill -HUP $$ ;;
    restore-signal-int:restore-after-install) /bin/kill -INT $$ ;;
    restore-signal-term:restore-after-install) /bin/kill -TERM $$ ;;
    final-check-conflict:restore-before-final-check) /bin/chmod 644 "$1" ;;
    commit-kill:restore-after-complete|commit-kill:nested-after-complete) /bin/kill -KILL $$ ;;
    apply-before-encryption-kill:apply-before-old-encryption) /bin/kill -KILL $$ ;;
    apply-between-encryption-kill:apply-after-old-encryption) /bin/kill -KILL $$ ;;
    apply-before-pointer-kill:apply-before-pointer) /bin/kill -KILL $$ ;;
    apply-after-pointer-kill:apply-after-pointer) /bin/kill -KILL $$ ;;
    apply-after-publish-kill:apply-after-publish) /bin/kill -KILL $$ ;;
    apply-before-chezmoi-fail:apply-before-chezmoi) die 'injected failure before chezmoi apply' ;;
    apply-signal-hup:apply-after-chezmoi) /bin/kill -HUP $$ ;;
    apply-signal-int:apply-after-chezmoi) /bin/kill -INT $$ ;;
    apply-signal-term:apply-after-chezmoi) /bin/kill -TERM $$ ;;
    apply-new-manifest-fail:apply-before-new-manifest) die 'injected apply new-manifest creation failure' ;;
    apply-new-encryption-fail:apply-before-new-encryption) die 'injected apply new-manifest encryption failure' ;;
    apply-ready-pointer-fail:apply-before-ready-pointer) die 'injected apply ready-pointer publication failure' ;;
    apply-post-install-db-conflict:apply-after-db-install)
      printf '%s\n' concurrent-db >"$1"
      /bin/chmod 600 "$1"
      ;;
    apply-commit-kill:apply-after-complete) /bin/kill -KILL $$ ;;
    recovery-after-encrypted-removal-kill:recovery-after-encrypted-removal) /bin/kill -KILL $$ ;;
  esac
}
