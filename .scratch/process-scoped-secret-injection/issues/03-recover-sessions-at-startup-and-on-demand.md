Type: grilling
Status: resolved

## Question

When should a managed host establish or repair its Proton provider session?

## Answer

Check proactively at user-session startup for early visibility and recover
lazily in the provider path before a consumer resolves credentials.
