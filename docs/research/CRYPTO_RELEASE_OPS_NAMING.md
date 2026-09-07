# Sacrysty and Codiquary naming

Sacrysty is the crypto-operations project. Codiquary is the
release-operations project for authenticated software artifacts.

The [accepted naming decision](https://github.com/nisavid/codiquary/issues/2#issuecomment-5565084063)
selects the project, public operator, and command for each system. Worker and
documentation names remain unassigned until those surfaces need names.

## Naming layers

Projects are institutions; public interfaces are personified operators;
background workers are restrained functionaries; published documentation is
a body of practice. Names apply to the surfaces the projects need.

| Surface | Sacrysty | Codiquary |
| --- | --- | --- |
| Project / institution | Sacrysty | Codiquary |
| Public operator | Sacrystan | Codophylax |
| CLI/TUI command | `sacryd` | `cophax` |

`sacryd` is pronounced “sacred.” `cophax` contracts **CO**do**PH**yl**AX** and
is pronounced “co-fax.” The operator name applies across public interfaces;
the command names the CLI/TUI.

The repository coordinates are `nisavid/sacrysty` and `nisavid/codiquary`.
Codiquary's Cargo package and library coordinate is `codiquary`. Sacrysty's
implementation substrate and package/library coordinates remain open;
selecting `sacryd` does not settle them.

## Domain naming convention

When introducing or revising a domain entity, relationship, or operation for
the current increment, establish its plain technical definition, relationships,
and lifecycle first. Consider terminology consistent with the projects'
techno-ecclesiastical, Ninth World-inspired naming scheme. Select thematic
language when it improves recognition without implying additional behavior
or authority. Create roles, objects, and operations only when the domain
requires them.

Record accepted terms and their technical crosswalk in the owning project's
`CONTEXT.md` before propagating them through the current increment's interfaces,
code, and documentation. Keep unresolved candidates with the relevant design
question, outside the canonical glossary. Settle names as their concepts
become clear; a complete thematic vocabulary is not a project-wide prerequisite.
Preserve established protocol identifiers.

Let the institutional vocabulary express custody, instruments, examination,
records, and practice. Retain precise technical terms and operation verbs where
they communicate the concept better. A named ceremony may be evocative while
its individual steps remain explicit. The naming layers apply to needed
surfaces, not a requirement to fill every role in both projects.

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

Use the selected names in planning and documentation. Repository provisioning
and package publication remain separately scoped steps. Check coordinate
availability when performing those steps; selecting a name neither reserves
coordinates nor guarantees availability.

The [2026-09-05 preliminary screen](CRYPTO_RELEASE_OPS_NAME_CLEARANCE.md) and
[Sigil/Canon screen](SIGIL_CANON_NAME_CLEARANCE.md) record findings about the
names they examined, not comprehensive legal clearance or a new screen of
the selected pair. Historical evidence and existing protocol identifiers
retain their original names.

Revisit Writ Bureau and the `writ` command if a separate authorization, approval,
dispatch, or actuation surface needs an identity. These are candidates for that
future surface, separate from the selected **writ** domain term.
