# Codex modifier TOML dependency

The modifier embeds TOMLKit 0.15.2 and verifies SHA-256 before import under
`python3 -I -S`. No package manager, network, cache, or installed TOMLKit is
used during apply. Python 3.9+ is required. TOMLKit preserves the comments,
formatting and ordering of the live configuration. This pure-Python wheel has
no runtime dependencies or native extensions. MIT licensing is retained.

- Canonical source: https://github.com/sdispater/tomlkit
- Tag: `0.15.2`; commit: `a0b15ebb09167ede584fc36ad5362fc3039b0530`.
- Registry: https://pypi.org/project/tomlkit/0.15.2/
- Artifact: `tomlkit-0.15.2-py3-none-any.whl`.
- SHA-256: `05562412163a3037b94497385fb7f9204c637bc605af7a48199e41cf2272f437`.
- Stored as standard base64 wrapped at 76 columns; decode using
  `python3 -m base64 -d`.

On 2026-10-24, all 13 package files and the MIT license matched the source
commit, and all 16 wheel RECORD hashes passed. Exact-version OSV and upstream
advisory queries returned no published matches. The artifact has no Trusted
Publishing attestation; admission uses registry digest and source equivalence.

Updates require review of the exact source, artifact, license and dependency
closure, plus all modifier compatibility tests. Update the archive and the
modifier digest together. Missing or modified bytes must fail without config
output; never fall back to dynamic resolution or an installed package. This
seals an existing dependency and grants no automatic update authority.
Rollback requires a reviewed safe wheel/digest pair. Retirement requires an
equivalent comment-preserving implementation and passing compatibility tests.
