Type: grilling
Status: resolved

## Question

How should `secretctl` perform multi-store mutations?

## Answer

Compute a credential-free reconciliation plan, require explicit approval,
mutate stores in a recoverable order, and verify convergence. Non-interactive
automation requires an explicit approval flag.
