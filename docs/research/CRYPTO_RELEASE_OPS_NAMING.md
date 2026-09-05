# Cryptosacristy and Codiquarium naming

Cryptosacristy is the crypto-operations project. Codiquarium is the
release-operations project for authenticated software artifacts.

**Decision date:** 2026-09-04

**Status:** Names selected and retained, including `sacrypt` and `cophax`.
The [2026-09-05 preliminary screen](CRYPTO_RELEASE_OPS_NAME_CLEARANCE.md)
records existing uses and trademark similarities as non-blocking findings for
this naming decision, not comprehensive legal clearance.

## Naming layers

Projects are institutions; public interfaces are personified operators;
background workers are restrained functionaries; published documentation is
a body of practice. Names apply to the surfaces the projects need.

| Surface | Cryptosacristy | Codiquarium |
| --- | --- | --- |
| Project / institution | Cryptosacristy | Codiquarium |
| Public operator | Cryptosacrist | Codophylax |
| CLI/TUI command | `sacrypt` | `cophax` |
| Background/internal workers, when applicable | Cryptostewards | Not yet selected |
| Published documentation | Cryptopraxis | Not yet selected |

`cophax` contracts **CO**do**PH**yl**AX** and is pronounced “co-fax.” The
operator name applies across public interfaces; the command names the CLI/TUI.

## Release vocabulary

**Release writ**, or **writ**:
An authority-issued record establishing or changing a release's standing.
This is the human-facing name for the existing `release-state/v1` concept.

**Admission verdict**, or **verdict**:
The result of evaluating a release's admissibility under the supplied
conditions. This names the existing `admission-result/v1` concept, including
`accepted-current`, `attributed-historical`, `rejected`, and `indeterminate`.

The [existing contract crosswalk](SCITT_CRYPTO_RELEASE_OPS_ADOPTION.md#functional-crosswalk)
retains the distinction between an authority's release-state record and a
consumer's admission result. The selected vocabulary adds no document types;
protocol identifiers and semantics remain unchanged.

## Clearance and adoption

Use the selected names in planning and documentation. The command-name findings
do not hold up adoption. Repository provisioning and package publication remain
separately scoped steps; their coordinates are unreserved.

The [Sigil/Canon screen](SIGIL_CANON_NAME_CLEARANCE.md) records findings about
the earlier candidates, not clearance for this pair. Historical evidence and
existing protocol identifiers retain their original names.

Writ Bureau and the `writ` command remain future possibilities, separate from
the selected **writ** domain term. Codiquarium's worker and documentation
names remain open until needed.
