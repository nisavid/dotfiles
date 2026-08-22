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
a new receipt.

The initial bootstrap is necessarily exceptional because the pre-bootstrap
trusted base cannot know the v1 receipt format, signer, or external launcher
wrapper. It must land through one owner-approved, branch-scoped break-glass
merge with the existing review record intact; protection is restored
immediately afterward. The verifier reports this state explicitly and never
treats a pre-bootstrap base as admitted.
