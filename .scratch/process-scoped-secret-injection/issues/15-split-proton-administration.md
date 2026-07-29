# Split Proton administration between the web app and CLI

Type: grilling
Status: resolved

## Question

Which surface owns host-agent creation, grants, and revocation?

## Answer

Use the Proton Pass web app for privileged agent creation and grant decisions.
Use `secretctl` for secure host enrollment, readiness, verification, expiry
monitoring, and lifecycle operations that the scoped host agent can safely
perform.
