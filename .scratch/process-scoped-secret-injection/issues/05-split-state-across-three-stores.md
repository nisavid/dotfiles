# Split desired state across three stores

Type: grilling
Status: resolved

## Question

Where should canonical secret-injection state live?

## Answer

Proton Pass owns injected values and agent grants. Within `secretctl`-managed
desired state, each native OS credential store owns only that host agent's
bootstrap token. Proton CLI separately stores its provider-session encryption
key there as provider-managed runtime state. Encrypted chezmoi owns the
reviewable, credential-value-free injection catalog.
