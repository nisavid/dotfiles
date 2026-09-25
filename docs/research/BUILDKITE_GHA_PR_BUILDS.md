# Buildkite `buildkite-gha` pull request builds

Research date: 2026-09-25. Scope: pipeline `nisavid/dotfiles`, which runs this repository's `.github/workflows/*` through the `github-actions` Buildkite plugin and the `buildkite-gha` runtime (v0.90.0).

Evidence tags:

- **[D]**: documented by Buildkite or the upstream project.
- **[S]**: inferred from upstream source.
- **[S+]**: source behavior reproduced by calling the upstream functions locally (see [Evidence base](#evidence-base)).
- **[O]**: observed in this pipeline's builds or in this repository's webhook deliveries.

## Summary

- **Q1: effective event.** In a build created by a native GitHub webhook, `buildkite-gha` reads `GITHUB_EVENT_NAME` first, then `BUILDKITE_GITHUB_EVENT`. It only maps "the build has a PR number" to `pull_request` when neither variable names `push`, `pull_request`, `workflow_dispatch`, or `schedule`. A new commit on a same-repository PR arrives as a `push` delivery. The build therefore carries `BUILDKITE_GITHUB_EVENT=push`, and the runtime classifies it as `push` on purpose. Upstream closed a PR that would have changed this and pointed to server-side dispatch instead. The plugin has no option to override the event. Setting `GITHUB_EVENT_NAME=pull_request` by hand makes the PR workflows fail instead of run. Only a custom importer that passes its own `--event-path` snapshot can declare `pull_request`.
- **Q2: which delivery creates the build.** With both **Build branches** and **Build pull requests** on, Buildkite creates the build for a new PR commit from the `push` delivery and attaches the PR metadata to it. The `synchronize` delivery creates no build, except for PRs from forks. The "PR builds only" branch-filter pattern changes which pushes create builds, not which delivery creates the build, so those builds are still `push`. Natively, only `opened` and the optional PR actions (such as `reopened` and `ready_for_review`) produce builds that `buildkite-gha` treats as `pull_request`. The `filter_condition` test most likely rejected every push because it was evaluated before Buildkite linked the push to its PR. This is unverified.
- **Q3: per-workflow cancellation.** Buildkite has none. Skip Intermediate Builds and Cancel Intermediate Builds work per branch, and their only filter is a branch pattern. The `github_actions` trigger accepts no build or filter options. `buildkite-gha` ignores `cancel-in-progress` with a warning. Neither upstream repository has an issue or PR tracking cancellation. Workflow concurrency groups become ordered gates that queue builds but never cancel them. Per-workflow cancellation is only possible with a DIY pipeline step that calls the REST API.
- **Recommendation.** Return to **server-side dispatch with Skip Intermediate Builds and Cancel Intermediate Builds both off**, which is Buildkite's documented configuration (Option A). It is the only stock setup in which every PR commit runs the PR workflows as `pull_request`. It never runs `privacy-age-integrity` or `phase7-terminal-proofs`, and `main` still builds. Its cost is that superseded builds keep running. If that cost matters, add a small step to the pipeline settings that cancels older builds of the same workflow and ref (Option A+). A+ uses only documented APIs but is untested here, so trial it on one PR first. The current native-webhook setup (Option B) cannot meet goal (b).

## Decision (2026-09-25)

- **`dotfiles` returns to Option A** (server-side dispatch, skip and cancel off) as the known-good compatibility-plugin baseline. The native-webhook probe (Option B) has been rolled back, including its repository webhook.
- **Evaluate Buildkite natively instead of through `buildkite-gha`.** A separate `dotfiles-native` pipeline will run the Platform portability and Zsh deployment portability test battery from a repository-versioned `.buildkite/pipeline.yml`. The battery is split into parallel groups defined once in a shared script, which GitHub Actions can adopt once workflow admission works again. GitHub Actions stays the required gate during the trial.
- **Success metric:** push-to-green time for a PR commit, against the GitHub Actions baseline of 13m24s median and 15m59s p90 (15 PR commits, 2026-09-24/25). Queue wait with several PRs in flight and projected cost are guardrails.
- **Update, later on 2026-09-25: `dotfiles` is paused and the evaluation is Linux-only.** The trial's macOS M4 vCPU minutes ran out. Most were spent by `dotfiles`' `macos-14` Platform portability jobs, each of which ran about 20 minutes into the Homebrew migration timeout before failing. Its GitHub Actions trigger is now disabled, and `dotfiles-native` skips its macOS group until the plan includes macOS minutes again. Before the minutes ran out, all five macOS groups passed natively; the longest ran 256s.

## Evidence base

| Source | Version read |
| --- | --- |
| `buildkite-gha` | tag `v0.90.0` = `c545ebdc069e27d1a597978b3ad04da0218426cb`, which was also `main` HEAD. The event-selection files (`internal/cli/buildkite_event.go`, `effective_event.go`, `plugin.go`, `internal/buildkite/triggers.go`) are unchanged between `v0.89.0` and `v0.90.0`, so builds on either runtime behave alike. |
| `github-actions-buildkite-plugin` | `main` = `d5a37746a19e269a410387de32c857b19769e4fb` (latest tag `v0.13.0` = `98159d5`). The plugin only acquires the runtime and runs `buildkite-gha plugin` ([hooks/command L114–L123][plugin-cmd]). All event logic lives in the runtime. |
| Buildkite docs | `buildkite/docs` at `cca8c5c950a7143269a90e7d8197901260e59240` (2026-09-24). Spot-checked against the live buildkite.com pages, including anchors. |
| Buildkite agent | `buildkite/agent` at `78f4dd9c`, for one log line only. |

Local harness **[S+]**: in a scratch clone of `v0.90.0`, a throwaway Go test called the runtime's own `buildkiteWebhookEventSource`, `buildkiteEventSource`, `newEffectiveEvent`, and `selectWorkflowTrigger` against this repository's three workflow files. The results are quoted under Q1.

Observations **[O]** come from three places:

1. The build facts supplied with the task, including build #96.
2. Read-only REST captures that an earlier session made on 2026-09-24: builds 1–22 and 42, and the pipeline settings before and after 2026-09-24 ≈21:17Z.
3. GitHub webhook delivery lists read with `gh api` on 2026-09-25.

In this session `bk api` returned `401 Unauthorized` (no usable token), so build #96 was **not** re-inspected. Delivery bodies also need the `admin:repo_hook` scope, which the current `gh` token lacks.

## Q1. How the runtime decides the effective event

### Precedence, from source

1. **`--event-path` snapshot.** Only the public `buildkite-gha upload` command for custom importers accepts it ([cli.md L436–L444, L635–L643][cli-635]). The plugin entry point never sets it: `pluginContext` builds `parsedUploadArgs` without an event path ([plugin.go L72–L85][plugin-go-72]). **[S]**
2. **`buildkite:webhook` metadata, when present** ([effective_event.go L38–L51][eff-38]). `buildkiteWebhookEventSource` builds a base snapshot from the environment and replaces its payload with the raw webhook body. It then sets the event from `GITHUB_EVENT_NAME` if that is non-empty, otherwise from `BUILDKITE_GITHUB_EVENT` ([buildkite_event.go L196–L218][bke-196], [L260–L272][bke-260]). **[S]** Buildkite attaches this metadata to any webhook-created build while the body stays cached, typically 7 days ([build meta-data docs][d-metadata]). **[D]**
3. **Environment fallback, when the metadata is unavailable** (for example, rebuilds after the cache expires) ([effective_event.go L52–L61][eff-38]). `buildkiteEventSource` resolves the event in order ([buildkite_event.go L39–L126][bke-39]): **[S]**
   - Start with `push`, or `schedule` if `BUILDKITE_SOURCE=schedule`.
   - If `BUILDKITE_PULL_REQUEST` is a positive integer, switch to `pull_request` with ref `refs/pull/N/head` and a synthesized `action: synchronize` (the Pipeline Trigger's `BUILDKITE_GITHUB_ACTION` is used when present).
   - Then, if `GITHUB_EVENT_NAME` or `BUILDKITE_GITHUB_EVENT` is `push`, `pull_request`, `workflow_dispatch`, or `schedule`, that value **overrides** the result. A `push` override also resets the payload to `{ref: refs/heads/<branch>}`. The source comment reads: "A push may also be associated with an open pull request, so restore its authoritative branch or tag ref" ([L112–L126][bke-112]).

Two layers then turn the chosen event into Buildkite conditions:

- **Event predicate, evaluated live by Buildkite.** For non-`--event-path` sources, the predicate is `LiveEventPredicate`: `build.env("GITHUB_EVENT_NAME")` first, then `build.env("BUILDKITE_GITHUB_EVENT")`. It consults `build.pull_request.id` or `build.source` only when neither names a supported event ([triggers.go L497–L527][trig-497]; [effective_event.go L67–L83][eff-67]). **[S]**
- **Filters, fixed at upload.** Branch, tag, base-branch, and activity filters use literals from the snapshot. The PR activity comes from `payload.action` ([effective_event.go L85–L133][eff-85]). **[S]**

Other inputs:

- **Build metadata:** only `buildkite:webhook` is read.
- **`BUILDKITE_SOURCE`:** used only for `schedule` and the fallback mapping.
- **`BUILDKITE_PULL_REQUEST`:** decides the event only when `BUILDKITE_GITHUB_EVENT` is absent or unsupported.

The runtime's own compatibility guide documents the same order ([compatibility.md L423–L440][compat-423]). It says the fallback "prefers `GITHUB_EVENT_NAME`, then preserves `push`, `pull_request`, `workflow_dispatch`, and `schedule` from `BUILDKITE_GITHUB_EVENT`". Only "Otherwise" does "Pull request build → `pull_request`" apply. **[D]**

### Why PR build #96 was classified as `push`

- Buildkite created #96 from the `push` delivery for PR #328's new commit. For same-repository PRs, "those commits create builds from the `push` event instead. Buildkite Pipelines adds the pull request details to those builds" ([GitHub docs L112–L116][d-gh-pr]). `BUILDKITE_GITHUB_EVENT` is "the GitHub webhook event type that triggered the build" ([env var reference][d-envvars]). **[D]** The task context reports #96 had `BUILDKITE_GITHUB_EVENT=push` and PR 328 attached. **[O]**
- The runtime treats that `push` as authoritative, as described above. `platform-portability` and `zsh-deployment-portability` therefore match only through `push: branches: [main]`. The generated group condition ends in a literal branch test that is false, so Buildkite marks the jobs `broken` ([conditionals: broken state][d-cond-broken]). **[S+]** Harness output for the #96 shape (`BUILDKITE_GITHUB_EVENT=push`, `BUILDKITE_PULL_REQUEST=328`, a push webhook body):

  ```text
  effective event=push ref=refs/heads/ivan/feature
    cocogitto.yml                  applicable=true   (push predicate only)
    platform-portability.yml       applicable=true   cond=… && "ivan/feature" =~ /^main$/
    zsh-deployment-portability.yml applicable=true   cond=… && "ivan/feature" =~ /^main$/
  ```

- Upstream intends this behavior:
  - `TestBuildkiteWebhookPushUsesBranchRefForPullRequestAssociatedBuild` asserts that event `push` with PR 42 yields event `push` ([buildkite_event_test.go L582–L602][bke-test]).
  - The rule arrived in [PR #331][pr331] ("Preserve GitHub workflow events across rebuilds").
  - [PR #355][pr355] ("Model first-party pull request synchronization builds") described exactly this failure: "Buildkite's GitHub integration coalesces first-party `pull_request.synchronize` deliveries into linked push builds … buildkite-gha treated `BUILDKITE_GITHUB_EVENT=push` as authoritative". The maintainer closed it unmerged on 2026-09-10: "With the GitHub Actions pipeline trigger … it'll all act roughly as it should without any change." **[D]**
- Buildkite's own page and the plugin README both say "Pull request builds receive `pull_request`" ([Buildkite docs L189–L197][d-gha-189]; [plugin README L248][plugin-readme-248]). That sentence holds only for PR builds created by a `pull_request` delivery, or for builds that lack `BUILDKITE_GITHUB_EVENT`. The runtime guide above is the precise statement. **[D]**, reconciled with **[S]**
- The importer-log line `Skipping commit verification: pull request build (#328)` comes from the Buildkite agent's checkout phase ([agent commit_verification.go L287–L288][agent-cv]). It shows only that `BUILDKITE_PULL_REQUEST` was set; it says nothing about the effective event. **[S]**

### Ways to force `pull_request`

- **Plugin option: none.** The runtime accepts only `workflow`, `workflows`, `runners`, `oidc`, `version`, `source-ref`, `minimum-release-age`, `experimental-runner-user`, and `private-reusable-workflows` ([plugin.go L115–L121][plugin-go-115]). **[S]**
- **`GITHUB_EVENT_NAME` override: not viable.** The variable wins in both the importer and the live predicate. On a push-created build, though, the webhook body has no `action`, so every `pull_request` trigger fails translation with `pull_request event snapshot requires payload.action` ([triggers.go L644–L649][trig-640]). The affected workflows become failing replacement steps. **[S+]** Harness output with `GITHUB_EVENT_NAME=pull_request` added:

  ```text
  effective event=pull_request ref=refs/pull/328/head action-expr=null
    platform-portability.yml       err=pull_request event snapshot requires payload.action
    zsh-deployment-portability.yml err=pull_request event snapshot requires payload.action
  ```

  `GITHUB_EVENT_NAME` is also documented as part of the server-selected Pipeline Trigger identity, not as a user knob ([cli.md L454–L478][cli-454]). **[D]**
- **Event snapshot: possible only with a custom importer.** Run `buildkite-gha upload --event-path <snapshot>` instead of the plugin ([cli.md L361–L389, L436–L444][cli-361]). An explicit snapshot is authoritative, and its predicate is literal rather than live ([effective_event.go L78–L80][eff-67]). **[D]**/**[S]** The catch is that you then own runtime acquisition, `--runner-queue` mappings, and the macOS runtime: "other platforms have no direct-upload default" ([cli.md L719–L720][cli-719]). Explicit snapshots also can't admit `paths` filters. This is Option D below; it is unverified.
- **Pipeline setting: none.** No native setting makes Buildkite create same-repository PR-commit builds from `synchronize`. The supported route is the `github_actions` Pipeline Trigger. **[D]** Its PR builds carried `GITHUB_EVENT_NAME=pull_request` and `BUILDKITE_GITHUB_ACTION=synchronize` in builds 21, 22, and 42. **[O]**

## Q2. Buildkite's GitHub integration semantics

- **Which delivery creates the build.** With **Build pull requests** on, `opened` creates a build directly. Later commits pushed to a same-repository PR branch create builds from `push`, with PR details attached. The matching `synchronize` "doesn't create a build of its own", except for fork PRs ([GitHub docs L112–L116][d-gh-pr]). **[D]**
- **What this repository's webhook deliveries showed on 2026-09-25 [O].** GitHub lists the native webhook deliveries (all HTTP 200) as:
  - `push` at 05:29:53Z and `synchronize` at 05:29:54Z.
  - `push` at 05:33:47Z and `synchronize` at 05:33:50Z.
  - `synchronize` alone at 05:35:19Z, after the webhook was narrowed to `pull_request` at 05:35:13Z.

  Per the task context, the only build was #96 (event `push`), and the `synchronize`-only delivery created nothing. That matches the documentation. The mapping of deliveries to the filter-on and filter-off phases is inferred from their timing, because GitHub doesn't show delivery bodies without `admin:repo_hook`.
- **`BUILDKITE_GITHUB_EVENT` on such builds.** It is set to the delivery that created the build, so `push` ([env var reference][d-envvars]; [GitHub docs L294–L306][d-gh-env]). **[D]**
- **Does Buildkite ignore `synchronize` in favour of `push`?** Yes, for same-repository PRs, as documented above. **[D]**
- **The "PR builds only" pattern.** The docs pattern sets **Branch Filter Pattern** to a branch that never matches, because "Pull request builds ignore the Branch Filter Pattern" ([GitHub docs L141][d-gh-141]; [branch configuration L13–L15][d-branch]). **[D]** That changes which pushes create builds, not which delivery creates PR-commit builds. Those builds are still created from `push`, so `buildkite-gha` still classifies them as `push`. **[D]** + **[S]**, untested. Builds from `opened`, or from optional actions (`reopened`, `ready_for_review`, `edited`, label changes, and so on), do carry `BUILDKITE_GITHUB_EVENT=pull_request` and an action, and the runtime classifies them as `pull_request`. **[S+]** With **Build branches** on, however, the branch's first push usually builds before the PR exists. **Skip when pull request has existing build for commit and branch**, which is on by default, can then skip the `opened` build ([GitHub docs L132][d-gh-132]). Buildkite's GitHub Actions page advises turning it off for native PR triggers ([L185][d-gha-185]). **[D]**
- **Why `filter_condition` suppressed every build (unverified).** The condition was `build.pull_request.id != null || build.branch == "main" || build.tag != null`.
  - `build.pull_request.id` is typed `String, null`, so `!= null` is an ordinary test ([variables][d-cond-vars]). Null semantics are unlikely to be the cause. **[D]**
  - Pipeline-level conditionals "are evaluated before any other build trigger settings" ([conditionals L13][d-cond-pipe]). The PR association for a push-created build is described only as details that Buildkite "adds" to the build ([GitHub docs L114][d-gh-pr]). The docs never say whether that happens before the filter runs. If the push is evaluated before it is linked to PR 328, the filter sees `build.pull_request.id == null`, a non-`main` branch, and no tag, and rejects it. `synchronize` creates no build regardless. **Inferred.**
  - The task reports that the deliveries in that window were PR-branch pushes, so there is no evidence either way on whether the filter also blocked `main`.

## Q3. Cancelling or skipping superseded builds per workflow

- **Buildkite skip and cancel are branch-scoped.** Skip Intermediate Builds skips builds that are still queued ("*scheduled* and *creating*"). Cancel Intermediate Builds cancels builds that are already running ("*started*, *failing*, and *blocked*"). Both act on earlier builds "on the same branch" when a new build is created. Their only refinement is a branch pattern such as `!main` ([skipping][d-skip]; [canceling][d-cancel]; [REST fields][d-rest-pipe-64]). Nothing scopes them by workflow, environment variable, or trigger. **[D]**
- **The `github_actions` trigger has no knobs.** It "doesn't accept `build` or `filter`" and "creates one build per matching workflow per event" ([pipeline triggers API L446][d-trig-446]; [data model L36][d-trig-36]). Traditional provider filters and duplicate-commit qualification don't apply to its builds ([Buildkite docs L101][d-gha-101]). **[D]**
- **Buildkite's guidance.** For server-side dispatch, turn both settings off, "where they can cancel or skip sibling workflow builds from the same event" ([L101][d-gha-101], [L424][d-gha-concurrency], and the reference JSON at [L49–L81][d-gha-json]). **[D]**
- **What happened here with both on [O].**
  - Every PR event skipped the Platform portability build (builds 3, 9, 16, 18, 21) while the Zsh deployment portability build ran (builds 4, 10, 17, 19, 22).
  - The `cocogitto` push build 20 on the same branch was skipped too.
  - After both settings were turned off (≈21:17Z on 2026-09-24), build 42 ran Platform portability, including its concurrency gates.
- **Cancel on with skip off: a race, not a fix.** Siblings created about 0.4 s apart are usually still `scheduled`, so Cancel Intermediate Builds leaves them alone. It still cancels any sibling that has already *started*, such as a `cocogitto` push build that began before the PR was opened. The docs advise against it. **Inferred.**
- **Concurrency groups queue but never cancel.** Groups are job-level, and "every job in a build inherits that build's creation time", so a gate orders whole builds ([controlling concurrency L22, L69–L99][d-gates]). **[D]**
  - `buildkite-gha` emits an opening and a closing gate, each with `concurrency: 1` ([pipeline.go L588–L599, L1032–L1053][pipe-588]).
  - The group key is a hash of the repository plus the resolved group ([bundle.go L646–L650][bundle-646]). For `${{ github.workflow }}-${{ github.ref }}`, that means one queue per workflow per PR. **[S]**
  - Newer builds of a PR therefore wait behind superseded ones. There is no cancel semantics, and the plugin doesn't expose `concurrency_method`. **[S]**
  - Gate jobs run on the first generated job's queue ([bundle.go L615–L621][bundle-615]). In build 42 both Platform portability gates targeted `queue=macos-14-medium`, and the opening gate ran on a macOS agent. **[O]**
- **Upstream status of `cancel-in-progress`.**
  - A value of `true` emits `W_WORKFLOW_CONCURRENCY_CANCEL_IN_PROGRESS_IGNORED`: "superseded builds keep running … Turn on Cancel Intermediate Builds … on the same branch, rather than per concurrency group" ([compiler.go L554–L561][compiler-554]; [compatibility.md L834–L842][compat-834]). The deferred-matrix slice "does not add `cancel-in-progress` support" ([L1426–L1430][compat-1426]). Job-level `cancel-in-progress` is unsupported. **[D]**
  - Searches of `buildkite/buildkite-gha` and `buildkite-plugins/github-actions-buildkite-plugin` issues and PRs on 2026-09-25 found no open item that tracks cancellation. **No public roadmap.**
- **DIY building blocks, all documented.** Only an in-build DIY step can cancel per workflow, and each piece it needs is documented **[D]**:
  - List a pipeline's builds filtered by `branch`, `state[]`, and `meta_data[…]` ([builds API][d-builds-list]).
  - The build model includes `env` ([builds API data model][d-builds-model]). Dispatch builds carry `GITHUB_WORKFLOW_REF`, for example `…/platform-portability.yml@refs/pull/319/merge`. **[O]**
  - `PUT …/builds/{number}/cancel` works for `scheduled`, `running`, and `failing` builds ([cancel a build][d-builds-cancel]).
  - Step-scoped Buildkite secrets ([secrets][d-secrets]) and `checkout: skip: true` ([command step][d-cmd-checkout]).
  - `buildkite-agent build cancel --build <uuid>` exists ([agent CLI][d-agent-cancel]), but the docs don't say whether a job token can cancel *another* build.

## Q4. Viable configurations

Goals:

- (a) At most one build per PR commit, or at least no sibling suppression.
- (b) The PR workflows run with event `pull_request`.
- (c) Superseded PR builds are cancelled or skipped.
- (d) Pushes to `main` still build.
- (e) `privacy-age-integrity` and `phase7-terminal-proofs` never run.

Key: ✅ met, ❌ not met, 🟡 partial.

| Option | Key settings | a | b | c | d | e | Status | Trade-offs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **A. Server-side dispatch, stock** | Re-enable the existing `github_actions` trigger rather than creating another ([L85–L86][d-gha-json]). `trigger_mode: none`, or **Disable Incoming GitHub Webhook Processing** ([L108][d-gha-migrate]). Delete the native repository webhook created 2026-09-25. Plugin config without `workflow`/`workflows` ([L109][d-gha-migrate]). `skip_queued_branch_builds: false`, `cancel_running_branch_builds: false`, `filter_enabled: false`. | 🟡 One build per matching workflow per event: `cocogitto` from `push`, plus platform and zsh from `synchronize`. No suppression. | ✅ [O] builds 21, 22, 42 | ❌ Superseded builds run to completion, and newer ones queue behind them at the gates. | ✅ The trigger handles `push` with `branches` [D] | ✅ `pull_request_target` isn't among the handled events and `workflow_dispatch` never dispatches ([L95][d-gha-95]; [compat L504][compat-504]); none appeared in builds 1–42 [O] | Documented and recommended ([L105][d-gha-105]) | Three importer jobs per PR commit, plus two macOS gate jobs for each gated workflow. Superseded macOS jobs keep holding agents. Check names end `(pull_request)`. No workflow list to maintain. The GitHub Actions trigger is still a preview feature ([plugin README L252–L253][plugin-readme-250]). |
| **A+. A plus a "cancel superseded" step** | A, plus a second native step in the pipeline settings (sketch below). It cancels older `scheduled`/`running`/`failing` builds on the same branch whose `env.GITHUB_WORKFLOW_REF` matches its own, which mirrors GitHub's `${{ github.workflow }}-${{ github.ref }}` group. | 🟡 As in A | ✅ | ✅ Per workflow and ref, siblings untouched | ✅ | ✅ | Built from documented APIs; **untested** | One extra small Linux job per PR build. Needs an API token with `read_builds` and `write_builds` as a Buildkite secret. Keep the script in pipeline settings, not the repo, so PR code can't change it. Skip rebuilds, because a rebuild gets a higher number and would cancel newer builds. Paging and rate limits are yours. Cancelling a gated build frees its group, since cancelled jobs leave the queue ([concurrency L22][d-gates]). |
| **B. Native webhook + explicit `workflows:` (current)** | `trigger_mode: code`; build branches, PRs, and tags; `workflows:` [cocogitto, platform-portability, zsh-deployment-portability]; skip and cancel on with `!main`; repo webhook for `push` + `pull_request`; no `filter_condition`. | ✅ [O] #96 | ❌ PR commits are `push`; PR workflows broken [O][S+] | 🟡 Branch-level; works because there is one build per commit | ✅ | ✅ Not listed | Documented as still supported ([L118][d-gha-118]) | Doesn't meet (b), so the PR workflows never run on PR commits. The workflow list needs maintenance, though missing paths are only skipped. |
| **C. B plus Buildkite-only `push` wrapper workflows** | Settings as in B, with **Skip when pull request has existing build** kept on so `opened` doesn't duplicate. Add wrappers outside `.github/workflows/`, which GitHub ignores; the plugin accepts any tracked in-repo `.yml` ([plugin README L73][plugin-readme-73]). Each wrapper declares `on: push: branches-ignore: [main]` and calls the real workflow through `uses:`, which needs `workflow_call:` added to it. Alternatively, keep full copies. | ✅ | 🟡 The jobs run, but as `push`: checks end `(push)` and `github.ref` is `refs/heads/<branch>`. Nothing in these workflows branches on the event. | ✅ Branch-level | ✅ The real files still match `push: main` | ✅ | **Unverified.** Local reusable calls are supported [D], but a caller outside `.github/workflows/` isn't confirmed. | One importer per commit, with the cheapest agent use. Wrappers or copies can drift. The semantics differ slightly from GitHub. `opened`-only builds may run nothing. |
| **D. B with a custom importer and a synthesized snapshot** | Replace the plugin step with a script that installs a pinned `buildkite-gha`. The script writes a `pull_request`/`synchronize` snapshot when `BUILDKITE_PULL_REQUEST` is set (base from `BUILDKITE_PULL_REQUEST_BASE_BRANCH`), otherwise a `push` snapshot. It then runs `upload --event-path … --runner-queue … --runtime-distribution darwin/arm64=…`. | ✅ | ✅ In principle; the snapshot is authoritative [D][S] | ✅ Branch-level | ✅ | ✅ | **Unverified.** The pieces are documented public CLI. | You re-implement what the plugin does: checksum-verified runtime acquisition, the macOS counterpart runtime, and runner mapping. No `paths` filters. It bypasses a code path upstream chose deliberately, so expect more maintenance on runtime upgrades. |

### Rejected configurations

- **Dispatch with skip and cancel on (the original setup):** suppresses siblings. **[O]**, and the docs advise against it. **[D]**
- **Dispatch with cancel on and skip off:** races with the push-delivered `cocogitto` build, and the docs advise against it. **Inferred.**
- **Native with a `GITHUB_EVENT_NAME` override:** the PR workflows fail to translate. **[S+]**
- **Native with the `filter_condition` tested:** created no builds. **[O]**
- **Generic `github` Pipeline Trigger with a filter and build env:** its commit and branch are fixed per trigger and "cannot be mapped from fields of the incoming webhook's JSON payload" ([incoming triggers, Limitations][d-incoming-lim]). **[D]**
- **Per-workflow dispatch pipelines:** the trigger has no workflow filter, and pipeline-level filters don't apply to dispatch builds. Every pipeline would receive a build for every matching workflow. **[D]**

### Option A+ sketch (untested)

The sketch goes in the pipeline settings YAML. `$$` defers expansion to runtime.

```yaml
steps:
  - label: ":github: Prepare workflow · ${GITHUB_WORKFLOW}"
    plugin: github-actions
  - label: ":octagonal_sign: Cancel superseded ${GITHUB_WORKFLOW}"
    if: build.pull_request.id != null
    checkout:
      skip: true
    secrets:
      CANCEL_API_TOKEN: dotfiles-cancel-token   # read_builds + write_builds
    command: |
      set -euo pipefail
      # A rebuild gets a higher number, so it would cancel newer builds.
      [ -z "$${BUILDKITE_REBUILT_FROM_BUILD_ID:-}" ] || exit 0
      api="https://api.buildkite.com/v2/organizations/$$BUILDKITE_ORGANIZATION_SLUG/pipelines/$$BUILDKITE_PIPELINE_SLUG/builds"
      builds="$$(curl -fsS -G --oauth2-bearer "$$CANCEL_API_TOKEN" "$$api" \
        --data-urlencode "branch=$$BUILDKITE_BRANCH" \
        -d 'state[]=scheduled' -d 'state[]=running' -d 'state[]=failing' -d exclude_jobs=true)"
      jq -r --arg ref "$$GITHUB_WORKFLOW_REF" --argjson n "$$BUILDKITE_BUILD_NUMBER" \
        '.[] | select(.number < $$n and .env.GITHUB_WORKFLOW_REF == $$ref) | .number' <<<"$$builds" |
        while read -r old; do
          curl -fsS -X PUT --oauth2-bearer "$$CANCEL_API_TOKEN" "$$api/$$old/cancel" >/dev/null
        done
```

The `if:` variable is documented for step conditions ([variables][d-cond-vars]). The rebuild check runs inside the command because Buildkite sets `BUILDKITE_REBUILT_FROM_BUILD_ID` to an empty string, not leaves it unset, on ordinary builds. Capturing the build list before `jq` makes a failed API call fail the step instead of cancelling nothing. The step has no `depends_on`, so it runs beside the importer and never waits on a gate.

## Open questions and unverified points

1. **Build #96 was not re-read.** `bk api` returned 401, so its env and importer log are as reported in the task. Builds 1–22 and 42 were verified from the 2026-09-24 captures.
2. **The `filter_condition` root cause** is a documented-order inference. To confirm it, check the pipeline's webhook delivery view in Buildkite, or GitHub delivery bodies with `admin:repo_hook`.
3. **The "PR builds only" branch-filter pattern** is documented but untested here. The claim that its PR-commit builds stay `push` follows from GitHub docs L114; it isn't observed.
4. **Option A+:**
   - The list endpoint returning `env` is inferred from the build data model; a single-build GET did return it [O].
   - Behavior under near-simultaneous builds, paging, and rate limits is untested.
   - Whether `buildkite-agent build cancel --build` can target another build with a job token is undocumented.
5. **Option C:** it is unconfirmed that a caller outside `.github/workflows/` can use `uses: ./.github/workflows/<file>.yml` under `buildkite-gha`. Also untested whether `opened` builds are skipped as expected with **Skip when pull request has existing build**.
6. **`build.env()` scope:** the docs say it "works with variables you've defined" ([conditionals L296–L299, L470–L471][d-cond-vars]) without saying whether step-level `env` counts. This matters only for override experiments, which are rejected above.
7. **Preview status:** the GitHub Actions Pipeline Trigger is labeled private preview in the plugin README, while Buildkite's page recommends it. Behavior may change. The runtime version was pinned to `latest` during the observations; pin `version:` for stability.

## Sources

`buildkite-gha` @ `c545ebdc069e27d1a597978b3ad04da0218426cb` (v0.90.0):

- [internal/cli/buildkite_event.go][bke-39] (L27–L192 env snapshot; L196–L258 webhook overlay; L260–L272 event-name precedence)
- [internal/cli/effective_event.go][eff-38] (L38–L65 source precedence; L67–L83 live predicate; L85–L133 snapshot literals)
- [internal/buildkite/triggers.go][trig-497] (L221–L239 live expressions; L497–L527 `LiveEventPredicate`; L640–L679 `pull_request` translation)
- [internal/cli/plugin.go][plugin-go-72] (L72–L85, L115–L121, L238–L250)
- [internal/compiler/compiler.go L554–L561][compiler-554]; [internal/compiler/bundle.go L615–L621, L646–L650][bundle-615]; [internal/buildkite/pipeline.go L588–L599][pipe-588]
- [internal/cli/buildkite_event_test.go L582–L602][bke-test]
- [docs/compatibility.md][compat-423] (L321–L323 check names; L423–L440 event precedence; L476–L477; L482; L504; L834–L842; L1426–L1430)
- [docs/cli.md][cli-635] (L361–L389, L436–L444, L454–L478, L635–L656, L719–L720)
- [PR #331][pr331], [PR #355 (closed)][pr355], and the [v0.90.0 release][rel090]

`github-actions-buildkite-plugin` @ `d5a37746a19e269a410387de32c857b19769e4fb`:

- [hooks/command][plugin-cmd]
- [README.md][plugin-readme-248] (L73, L244–L248, L250–L262)

Buildkite docs (`buildkite/docs` @ `cca8c5c950a7143269a90e7d8197901260e59240`, rendered at buildkite.com/docs):

- [Run GitHub Actions workflows in Buildkite][d-gha]: `pages/pipelines/migration/run_github_actions_workflows.md` L49–L81, L85–L86, L91–L101, L105–L112, L118, L185, L189–L197, L414–L424, L478
- [GitHub source control][d-gh-pr]: `pages/pipelines/source_control/github.md` L107–L108, L112–L116, L132–L143, L294–L306
- [Conditionals][d-cond-pipe]: `pages/pipelines/configure/conditionals.md` L7–L18, L148–L150, L296–L339, L358–L416, L470–L471
- [Branch configuration][d-branch] L13–L15; [Skipping][d-skip] L5–L18; [Canceling][d-cancel] L5–L22
- [Controlling concurrency][d-gates] L22, L69–L99
- [Pipelines API][d-rest-pipe-64] L64–L79 and provider settings; [Pipeline triggers API][d-trig-446] L36, L244–L250, L446, L454–L456; [Incoming pipeline triggers][d-incoming-lim] L217–L230
- [Builds API][d-builds-cancel] (list filters, data model, cancel at L1046–L1053); [Build meta-data][d-metadata] L129–L143; [Environment variables][d-envvars] (`data/content/environment_variables.yaml` L322–L336)
- [Buildkite secrets][d-secrets] L76–L117; [Command step `checkout`][d-cmd-checkout]; [`buildkite-agent build cancel`][d-agent-cancel]

`buildkite/agent` @ `78f4dd9cef5abc682f37d77d4cd8968173483b76`:

- [internal/job/commit_verification.go L287–L288][agent-cv]

[bke-39]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/internal/cli/buildkite_event.go#L39-L126
[bke-112]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/internal/cli/buildkite_event.go#L112-L126
[bke-196]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/internal/cli/buildkite_event.go#L196-L218
[bke-260]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/internal/cli/buildkite_event.go#L260-L272
[bke-test]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/internal/cli/buildkite_event_test.go#L582-L602
[eff-38]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/internal/cli/effective_event.go#L38-L65
[eff-67]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/internal/cli/effective_event.go#L67-L83
[eff-85]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/internal/cli/effective_event.go#L85-L133
[trig-497]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/internal/buildkite/triggers.go#L497-L527
[trig-640]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/internal/buildkite/triggers.go#L640-L679
[plugin-go-72]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/internal/cli/plugin.go#L72-L85
[plugin-go-115]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/internal/cli/plugin.go#L115-L121
[compiler-554]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/internal/compiler/compiler.go#L554-L561
[bundle-615]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/internal/compiler/bundle.go#L615-L621
[bundle-646]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/internal/compiler/bundle.go#L646-L650
[pipe-588]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/internal/buildkite/pipeline.go#L588-L599
[compat-423]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/docs/compatibility.md#L423-L440
[compat-504]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/docs/compatibility.md#L504
[compat-834]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/docs/compatibility.md#L834-L842
[compat-1426]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/docs/compatibility.md#L1426-L1430
[cli-361]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/docs/cli.md#L361-L389
[cli-454]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/docs/cli.md#L454-L478
[cli-635]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/docs/cli.md#L635-L656
[cli-719]: https://github.com/buildkite/buildkite-gha/blob/c545ebdc069e27d1a597978b3ad04da0218426cb/docs/cli.md#L719-L720
[pr331]: https://github.com/buildkite/buildkite-gha/pull/331
[pr355]: https://github.com/buildkite/buildkite-gha/pull/355
[rel090]: https://github.com/buildkite/buildkite-gha/releases/tag/v0.90.0
[plugin-cmd]: https://github.com/buildkite-plugins/github-actions-buildkite-plugin/blob/d5a37746a19e269a410387de32c857b19769e4fb/hooks/command#L114-L123
[plugin-readme-73]: https://github.com/buildkite-plugins/github-actions-buildkite-plugin/blob/d5a37746a19e269a410387de32c857b19769e4fb/README.md#L73
[plugin-readme-248]: https://github.com/buildkite-plugins/github-actions-buildkite-plugin/blob/d5a37746a19e269a410387de32c857b19769e4fb/README.md#L244-L248
[plugin-readme-250]: https://github.com/buildkite-plugins/github-actions-buildkite-plugin/blob/d5a37746a19e269a410387de32c857b19769e4fb/README.md#L250-L262
[agent-cv]: https://github.com/buildkite/agent/blob/78f4dd9cef5abc682f37d77d4cd8968173483b76/internal/job/commit_verification.go#L287-L288
[d-gha]: https://buildkite.com/docs/pipelines/migration/run-github-actions-workflows
[d-gha-json]: https://buildkite.com/docs/pipelines/migration/run-github-actions-workflows#add-a-github-actions-workflow-to-a-pipeline-configure-an-equivalent-pipeline-manually
[d-gha-95]: https://buildkite.com/docs/pipelines/migration/run-github-actions-workflows#add-a-github-actions-workflow-to-a-pipeline-trigger-builds-from-workflow-events
[d-gha-101]: https://buildkite.com/docs/pipelines/migration/run-github-actions-workflows#add-a-github-actions-workflow-to-a-pipeline-trigger-builds-from-workflow-events
[d-gha-105]: https://buildkite.com/docs/pipelines/migration/run-github-actions-workflows#migrate-to-server-side-dispatch
[d-gha-migrate]: https://buildkite.com/docs/pipelines/migration/run-github-actions-workflows#migrate-to-server-side-dispatch
[d-gha-118]: https://buildkite.com/docs/pipelines/migration/run-github-actions-workflows#use-explicit-workflows-in-an-existing-build
[d-gha-185]: https://buildkite.com/docs/pipelines/migration/run-github-actions-workflows#use-explicit-workflows-in-an-existing-build-configure-the-plugin-manually
[d-gha-189]: https://buildkite.com/docs/pipelines/migration/run-github-actions-workflows#use-explicit-workflows-in-an-existing-build-configure-the-plugin-manually
[d-gha-concurrency]: https://buildkite.com/docs/pipelines/migration/run-github-actions-workflows#supported-functionality-and-limitations-concurrency
[d-gh-pr]: https://buildkite.com/docs/pipelines/source-control/github#running-builds-on-pull-requests
[d-gh-132]: https://buildkite.com/docs/pipelines/source-control/github#running-builds-on-pull-requests
[d-gh-141]: https://buildkite.com/docs/pipelines/source-control/github#running-builds-on-pull-requests
[d-gh-env]: https://buildkite.com/docs/pipelines/source-control/github#environment-variables
[d-envvars]: https://buildkite.com/docs/pipelines/configure/environment-variables
[d-cond-pipe]: https://buildkite.com/docs/pipelines/configure/conditionals#conditionals-in-pipelines
[d-cond-broken]: https://buildkite.com/docs/pipelines/configure/conditionals#conditionals-and-the-broken-state
[d-cond-vars]: https://buildkite.com/docs/pipelines/configure/conditionals#variable-and-syntax-reference-variables
[d-branch]: https://buildkite.com/docs/pipelines/configure/workflows/branch-configuration#additional-branch-filtering-for-pull-request-builds
[d-skip]: https://buildkite.com/docs/pipelines/configure/skipping#skip-queued-intermediate-builds
[d-cancel]: https://buildkite.com/docs/pipelines/configure/canceling-builds#cancel-running-intermediate-builds
[d-gates]: https://buildkite.com/docs/pipelines/configure/workflows/controlling-concurrency#concurrency-and-parallelism-how-concurrency-gates-work
[d-rest-pipe-64]: https://buildkite.com/docs/apis/rest-api/pipelines#provider-settings-properties
[d-trig-36]: https://buildkite.com/docs/apis/rest-api/pipeline-triggers
[d-trig-446]: https://buildkite.com/docs/apis/rest-api/pipeline-triggers#create-a-pipeline-trigger-create-a-github-actions-pipeline-trigger
[d-incoming-lim]: https://buildkite.com/docs/apis/webhooks/incoming/pipeline-triggers#limitations
[d-builds-list]: https://buildkite.com/docs/apis/rest-api/builds#list-builds-for-a-pipeline
[d-builds-model]: https://buildkite.com/docs/apis/rest-api/builds
[d-builds-cancel]: https://buildkite.com/docs/apis/rest-api/builds#cancel-a-build
[d-metadata]: https://buildkite.com/docs/pipelines/configure/build-meta-data
[d-secrets]: https://buildkite.com/docs/pipelines/security/secrets/buildkite-secrets#use-a-buildkite-secret-in-a-job
[d-cmd-checkout]: https://buildkite.com/docs/pipelines/configure/step-types/command-step
[d-agent-cancel]: https://buildkite.com/docs/agent/cli/reference/build#canceling-a-build
