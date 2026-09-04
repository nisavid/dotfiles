# Sigil Bureau and Canon Bureau preliminary name clearance

**Research date:** 2026-09-04

**Status:** Preliminary, primarily U.S.-focused knockout and technical-collision
screen. This is not a legal opinion, a comprehensive trademark clearance, or
authority to provision, rename, publish, or register anything.

## Verdict

The proposed pair is **not cleared for public use**.

- `sigil-bureau` and `canon-bureau` had no exact public GitHub repository-name
  match, and neither compound was present in the package registries screened
  below. That is useful coordinate availability, not name clearance or a
  reservation.
- The bare commands are decisively conflicted. The maintained Sigil EPUB editor
  installs `sigil`; the current Rust package `canon-archive` installs `canon`.
- `SIGIL` also has a live pending U.S. application directly covering security
  tokens for user authentication and security consulting. Wizards currently
  uses Sigil for both a D&D software product and the Planescape setting's City
  of Doors, and a long-running open-source EPUB editor uses it as its exact
  product name.
- `CANON` is Canon Inc.'s long-established, globally registered technology
  brand. `Canon Bureau` keeps that exact term as its dominant first word, and
  “Bureau” is not enough evidence to treat the compound as unrelated.

Changing only the executable names would resolve the command collisions, but
not the adverse product and trademark findings. Before public provisioning,
either change the dominant project names or obtain a professional,
multi-jurisdiction clearance for the intended software and services.

`Writ Bureau` and `writ` remain uncommitted future fog. They were not cleared in
this pass and are not part of the accepted rename set.

## Findings by surface

| Surface | Sigil Bureau | Canon Bureau |
| --- | --- | --- |
| Project display name | No exact compound conflict found, but `Sigil` remains the dominant term amid directly relevant software, franchise, and authentication uses. **Not cleared.** | No exact compound conflict found, but `Canon` remains the dominant term and exact Canon Inc. brand. **Not cleared.** |
| GitHub repository slug | The [public repository search](https://api.github.com/search/repositories?q=sigil-bureau%20in:name) returned no exact `sigil-bureau` name. Technically open in the checked namespace, subject to change. | The [public repository search](https://api.github.com/search/repositories?q=canon-bureau%20in:name) returned no exact `canon-bureau` name. Technically open in the checked namespace, subject to change. |
| Package coordinate | The compound was absent from PyPI, npm, crates.io, RubyGems, and NuGet in the checks below. Availability is not reserved. | The compound was absent from PyPI, npm, crates.io, RubyGems, and NuGet in the checks below. Availability is not reserved. |
| Bare executable | **Conflict:** the Sigil EPUB editor installs `/usr/bin/sigil`. | **Conflict:** `canon-archive` installs a `canon` binary. |
| Product/search confusion | High: exact current names include the Sigil EPUB editor and Wizards' D&D Sigil software; Planescape also uses Sigil as a major setting name. | High: the display name can read as an organizational unit or product of Canon Inc.; an unrelated current CLI is also already named Canon. |
| Trademark/IP screen | Adverse: a live pending `SIGIL` application covers authentication-token hardware and security consulting. | Adverse: Canon Inc. claims and actively manages the globally registered `Canon` technology brand; an active U.S. registration covers computers and related components. |

## Technical coordinates and commands

### Repository and package coordinates

GitHub's repository API returned zero exact repository-name matches for both
compound slugs on the research date. Repository names are owner-scoped and can
be claimed later, so these results establish only point-in-time technical
availability.

The first-party registry endpoints produced this point-in-time matrix:

| Registry | `sigil-bureau` | `canon-bureau` | Bare `sigil` | Bare `canon` |
| --- | --- | --- | --- | --- |
| PyPI | [404](https://pypi.org/pypi/sigil-bureau/json) | [404](https://pypi.org/pypi/canon-bureau/json) | [Occupied](https://pypi.org/project/sigil/) | [Occupied](https://pypi.org/project/canon/) |
| npm | [404](https://registry.npmjs.org/sigil-bureau) | [404](https://registry.npmjs.org/canon-bureau) | [Unpublished tombstone](https://registry.npmjs.org/sigil), not a positive availability result | [Occupied](https://registry.npmjs.org/canon) |
| crates.io | [404](https://crates.io/api/v1/crates/sigil-bureau) | [404](https://crates.io/api/v1/crates/canon-bureau) | [Occupied](https://crates.io/crates/sigil) | [Occupied](https://crates.io/crates/canon) |
| RubyGems | [404](https://rubygems.org/api/v1/gems/sigil-bureau.json) | [404](https://rubygems.org/api/v1/gems/canon-bureau.json) | [Occupied](https://rubygems.org/gems/sigil) | [Occupied](https://rubygems.org/gems/canon) |
| NuGet | [404](https://api.nuget.org/v3-flatcontainer/sigil-bureau/index.json) | [404](https://api.nuget.org/v3-flatcontainer/canon-bureau/index.json) | [Occupied](https://www.nuget.org/packages/Sigil) | [404](https://api.nuget.org/v3-flatcontainer/canon/index.json) |

The compound coordinates are therefore viable only as a technical starting
point. The bare package names are unsuitable for a cross-ecosystem release.

### Bare executable conflicts

The upstream Sigil build installs a target named `sigil` into the executable
directory ([upstream CMake](https://github.com/Sigil-Ebook/Sigil/blob/master/src/qt6sigil.cmake#L609-L611)).
Arch Linux's current first-party package file list independently records
`usr/bin/sigil` ([Arch package files API](https://archlinux.org/packages/extra/x86_64/sigil/files/json/)).
This is a direct PATH collision on the target Linux ecosystem, not merely a
search result or package-coordinate reuse.

The maintained [`robklg/canon`](https://github.com/robklg/canon) project is a
media-archive CLI. Its manifest declares a binary named `canon`, and its README
says `cargo install canon-archive` installs that binary
([manifest](https://github.com/robklg/canon/blob/master/Cargo.toml#L18-L20),
[crate](https://crates.io/crates/canon-archive)). This is another direct PATH
collision even though the Rust package coordinate differs.

## Product and trademark evidence

### Sigil

The maintained [Sigil EPUB editor](https://github.com/Sigil-Ebook/Sigil) is an
established open-source desktop application with current releases. Its exact
software and executable name makes plain `Sigil` and `sigil` noisy before any
trademark analysis.

Wizards of the Coast also uses **Sigil** as the exact name of its 3D virtual
tabletop. Development has ended, but Wizards says the service remains available
through October 31, 2026
([official sunset notice](https://www.dndbeyond.com/posts/2086-closing-the-chapter-on-sigil-and-thanking-the),
[support FAQ](https://dndbeyond-support.wizards.com/hc/en-us/articles/42550438974868-Sigil-Sunset-FAQ)).
Its current Planescape source names the setting
[`Sigil, the City of Doors`](https://www.dndbeyond.com/sources/dnd/paitm/sato).
The inference is not that every dictionary use is forbidden; it is that a
fantasy-inflected `Sigil Bureau` can create an avoidable franchise association
while `Sigil` is still a live software product.

The USPTO knockout query `FM:sigil` returned 14 records on the research date.
The directly relevant record is live pending application **serial 99696051**,
owned by Sigil LLC, for `SIGIL` as a standard-character mark covering security
token hardware, security token hardware for user authentication, and computer,
data, internet, and physical security consulting
([official USPTO record](https://tmsearch.uspto.gov/search/search-results/99696051)).
That does not establish infringement or predict the application's outcome. It
does make `Sigil` an adverse choice for a new authentication and cryptographic
software surface.

### Canon

Canon Inc. says it registered `Canon` as its official trademark in 1935. The
same first-party history explicitly acknowledges the ordinary meanings
“holy scripture” and “criterion or standard of judgment”
([Canon logo history](https://global.canon/en/corporate/logo/)). Thus the
intended dictionary meaning does not itself distinguish `Canon Bureau` from
Canon's brand use.

Canon says its logo is registered in more than 190 countries and regions and
that its trademark organization monitors new technology and third-party marks
([Canon IP overview](https://global.canon/en/intellectual-property/future/)).
Its Brand Management Committee reviews trade and product names and use of the
Canon mark ([brand management](https://global.canon/en/sustainability/governance/brand/management/)),
and its terms identify `Canon` and Canon product and service names as Canon
Group trademarks or registered trademarks
([terms](https://global.canon/en/terms/)). Canon's business includes networked
products, cloud-connected services, software, and cybersecurity work, so a new
software project is not safely assumed to occupy an unrelated market.

The USPTO knockout query `FM:canon` returned 45 records on the research date,
many live and owned by Canon Kabushiki Kaisha. One directly relevant live
registration is **serial 72259803**, registration **0844063**, for `CANON` in
International Class 009 covering electronic computers, calculators, and
components including storage, retrieval, reading, and recording units
([official USPTO record](https://tmsearch.uspto.gov/search/search-results/72259803)).
This is an adverse preliminary result, not a legal conclusion about the proposed
compound.

## Limits of this screen

The exact-compound USPTO queries `CM:"sigil bureau"` and
`CM:"canon bureau"` returned no records on 2026-09-04. USPTO calls an exact-word
query only a **knockout search** and instructs searchers to broaden for similar
appearance, sound, meaning, and commercial impression, then assess related
goods and services. It also warns that common-law use can matter even without a
live federal registration
([federal trademark searching](https://www.uspto.gov/trademarks/search/federal-trademark-searching),
[likelihood of confusion](https://www.uspto.gov/trademarks/search/likelihood-confusion)).

This pass did not complete state, non-U.S., common-law, domain, corporate-name,
or paid commercial-database searches. WIPO likewise recommends checking target
national and regional registers and using professional advice when similar or
identical marks exist
([WIPO availability guidance](https://www.wipo.int/en/web/madrid-system/check-availability)).
Those omissions are why the result is “not cleared,” rather than a legal claim
that either compound is unusable.
