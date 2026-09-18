# Provingkit installation fixtures

`artifacts.json` contains literal clean artifacts emitted by Provingkit's
projector at commit `147e1ddfc969b5119001488ce1556627d3b2449b`. The source was a
new public synthetic Git repository with inert skill text and a small executable
shell file. The captured receipt, inventory, tree digest, target catalogs, and
file modes are independent oracles for the installer tests. Mode manifests use
the upstream `path`, `mode`, `origin` TSV format.

- `a`: three catalog members, all version 1.0.0.
- `b`: the same version strings, with changed Proseweaving skill bytes.
- `six_a`: all six catalog members at the same source commit as `a`.
- `preview`: all six members, including the changed Proseweaving bytes.

The source commits in these receipts identify the synthetic repository. They
are not deployable revisions in the canonical Provingkit repository. Tests
materialize the literal artifacts and package them into temporary `file:` URLs;
no test downloads or installs real plugin content. The default dotfiles profile
is inactive and contains no fixture pins.

To reproduce the artifact oracle with a public checkout containing the frozen
producer commit:

```sh
python3 tests/fixtures/provingkit-installations/regenerate.py \
  --producer-source "$public_provingkit_checkout"
```

`native-probes.json` preserves the native control experiments from 2026-09-18.
Each case records its cleared environment, command arguments, return status,
stdout/stderr, and observations. `${CASE}` replaces its disposable directory;
executable placeholders replace the resolved binaries. The normalization field
states the substitution, and each executable has its SHA-256 digest. The native
binaries were:

| Client | Version | SHA-256 |
| --- | --- | --- |
| Codex | 0.155.0 | `660e159a49e823ac8e5986cb238f73158ce4b957d40d9292f8de90862644b501` |
| Claude Code | 2.1.273 | `6c752e2cc7c110c9df15f26d8d134d438c5ae95dbd610efc1a308bf7f9c5f6c1` |

The cases establish these specific behaviors:

| Case | Observation |
| --- | --- |
| `initial/*` | Fresh install JSON shapes; selected uninstall preserves its sentinel; marketplace removal disrupts the unselected member. Claude removes its cache; Codex stops listing it while the source is absent. |
| `all-selected/*` | Source removal/rebind after scoped selected uninstall recreates same-version changed bytes; Claude preserves persistent data with `--keep-data` and restores explicit disabled state. |
| `stable/*` | Stable source replacement plus selected native reinstall changes bytes without changing unselected registrations/cache contents. Codex rejects local `marketplace upgrade`; Claude accepts directory `marketplace update`. Both repair a deleted fixture cache with install. |
| `same-name-add/*` | Codex rejects a duplicate source name. Claude accepts the rebind, but a three-entry replacement catalog makes the other three installed members report `plugin-not-found`. An update argument names a marketplace, not a replacement directory. |
| `same-name-full-slate/claude` | Rebind to a complete clean catalog and replace only the three selected members. All other registrations, bytes/modes, enablement, scopes, and timestamps remain unchanged, with no native errors. Neither recorded registry entry declares `autoUpdate`. |

Environment redirection isolates ordinary configuration for these public probes;
it is not a hostile-process containment claim. The only permitted outside
symlink was Codex's executable-dispatch alias to its frozen binary. No credentials,
model calls, live installation, account marketplace mutation, or interactive
Cursor session was involved.

`tests/test_provingkit_installations.py` has opt-in real-native tests using two
explicit executable paths. The regular test run skips them. Schema fixtures
verify parsing only; the recorded probes and the opt-in tests provide the
native lifecycle evidence. `tests/test_provingkit_deployment.py` performs fresh
and repeated public-only chezmoi applies, including modes and missing-directory
repair. It does not load the repository's private source.
