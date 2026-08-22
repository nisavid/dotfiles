---
status: accepted
---

# Owner-Signed Admission For Protected Age Transitions

The hosted privacy boundary remains fail-closed for protected source changes and executes only trusted-base code. Local identity-backed ciphertext validation therefore produces a detached SSH-signed receipt bound to the repository, base and candidate commits, protected tree entries, expiry, and nonce; the receipt travels in the pull-request body and is verified from the trusted base. This keeps the age identity and plaintext local, rejects candidate-authored authority, and avoids treating a broad branch-protection bypass as the ordinary rotation path.

The initial bootstrap is necessarily exceptional because the pre-bootstrap
trusted base cannot know the v1 receipt format or signer. It must land through
one owner-approved, branch-scoped break-glass merge with the existing review
record intact; protection is restored immediately afterward. The verifier
reports this state explicitly and never treats a pre-bootstrap base as
admitted.
