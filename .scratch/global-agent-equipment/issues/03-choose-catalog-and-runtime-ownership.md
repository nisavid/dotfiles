# Choose catalog and runtime ownership

Type: grilling
Status: resolved

## Question

Which state is authoritative, and what should chezmoi own?

## Answer

A repo-owned chezmoi catalog is the authoritative desired state. It records
distributions, equipment identities, providers, harness outcomes, and explicit
exceptions, preferably by source reference. Native package managers and
harnesses continue to own caches, credentials, timestamps, databases, and
other runtime state. Narrow overlays and adapters reconcile only catalog-owned
fields and installations.
