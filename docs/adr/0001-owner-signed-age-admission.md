---
status: accepted
---

# Owner-Signed Admission For Protected Age Transitions

The hosted privacy boundary remains fail-closed for protected source changes and executes only trusted-base code. Local identity-backed ciphertext validation therefore produces a detached SSH-signed receipt bound to the repository, base and candidate commits, protected tree entries, expiry, and nonce; the receipt travels in the pull-request body and is verified from the trusted base. This keeps the age identity and plaintext local, rejects candidate-authored authority, and avoids treating a broad branch-protection bypass as the ordinary rotation path.

Receipt creation is launched by an operator-owned wrapper outside both
checkouts. That wrapper compares the live creator with the raw executable blob
from the trusted base before executing only that blob. The creator then requires
clean exact checkouts, imports its verifier modules only from the materialized
trusted tree, and materializes the candidate commit's Git tree before
identity-backed validation. The signed tree digests therefore describe the same
bytes that local validation inspected. The creator's in-process source check is
defense-in-depth and is not an independent trust root; a compromised operator
host or wrapper remains outside this repository-level guarantee.
The v1 nonce is an identifier rather than a durable one-time claim: exact
base/head replay remains valid until expiry, while any changed commit requires
a new receipt. Expiry is evaluated whenever the trusted boundary workflow runs.
GitHub does not reevaluate a successful check when wall time advances, so the
owner must trigger a fresh trusted run immediately before merging; the signed
receipt's expiry is not, by itself, a merge-time revocation mechanism.

The initial bootstrap is necessarily exceptional because the pre-bootstrap
trusted base cannot know the v1 receipt format, signer, or external launcher
wrapper. It must land through one owner-approved, branch-scoped break-glass
merge with the existing review record intact; protection is restored
immediately afterward. The verifier reports this state explicitly and never
treats a pre-bootstrap base as admitted.

The Actions job name is not an independent provenance root: GitHub identifies
required checks by job name and the shared Actions app, not by the trusted
workflow's event or path. Ordinary protected merges therefore require a
repository-scoped admission GitHub App whose stable context is pinned by App ID
in branch protection. Until that App-backed source is installed and verified,
the owner-controlled merge procedure remains the authoritative residual gate.
