# Define equipment identities and providers

Type: grilling
Status: resolved

## Question

What stable domain model can distinguish logical equipment from its packaging?

## Answer

Each component has a typed, namespaced equipment identity such as
`skill:mattpocock/grilling` or `mcp:context7/server`. A distribution is an
installable bundle. A provider route is one concrete route by which a
distribution supplies an identity to a harness. A distribution's coverage is
the set of equipment identities it supplies. Differently named components are
equivalent or conflicting only through an explicit mapping; similarity is
never inferred.
