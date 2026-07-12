# Raw scenario

Consider these independent cases:

- an absent remote target whose creation is authorized;
- an existing target at the expected commit;
- an explicitly authorized request to delete a present remote ref, even though this planner has no deletion operation;
- a non-fast-forward update of a present target for which one exact `target_only_shas` entry is missing from `removal_authorized_commits`;
- a non-fast-forward update with missing per-SHA removal authorization and an unowned outgoing commit;
- a non-fast-forward update of a present target for which every `target_only_shas` entry appears in `removal_authorized_commits` and no other gate remains;
- a diverged target with remote-only commits that must be preserved and reconciled.

Ordinary publication is authorized. Treat the update and deletion cases as independent.
