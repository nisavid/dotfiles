# Owner-signed age admission result contract

This contract describes the result that the repository-scoped `Owner-signed age
admission` App publishes for each pull-request head. It is separate from the
`privacy-age-admission/v1` owner receipt and from the coordinated agent-equipment
release receipt.

## Result record

Every successful result carries `version: privacy-age-admission-result/v1` and
is bound to the exact `repository`, `base_commit`, and
`head_commit` supplied to the trusted-base verifier. `protected_paths` is the
sorted, all-and-only set of protected paths whose trusted-base tree entries
differ from the candidate tree entries. The result vocabulary is closed:

| `outcome` | `protected_paths` | `receipt_required` | Meaning |
| --- | --- | --- | --- |
| `no_protected_paths_changed` | empty | `false` | The trusted-base computation completed and found no protected transition. This is terminal success; no owner receipt is parsed or required. |
| `owner_admission_verified` | nonempty | `true` | The trusted-base computation found a protected transition and verified one exact owner receipt for it. |

The empty result is not a fallback. Checkout, tree, classifier, repository,
base/head, freshness, or provenance uncertainty must produce a blocking failure,
never `no_protected_paths_changed`. A result with an unknown outcome, an
unsorted or duplicate path list, a mismatched receipt flag, or a changed
base/head is invalid.

## Delivery contract

The App publishes the stable required context for every supported pull-request
head event (`opened`, `reopened`, `synchronize`, `ready_for_review`, and
`edited`). Results are keyed by pull request and exact head commit. Duplicate
and retried deliveries are idempotent; an older or out-of-order delivery cannot
replace a newer head's result. A body edit or new head triggers a fresh trusted
computation, and an expired or ambiguous protected receipt never selects the
empty outcome.

The App-pinned context remains the required branch-protection boundary. The
trusted Actions workflow is advisory evidence for the App, not a replacement
for it, and no branch-protection rule is edited dynamically.
