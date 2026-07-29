Type: grilling
Status: resolved

## Question

Where should canonical secret-injection state live?

## Answer

Proton Pass owns injected values and agent grants. Each native OS credential
store owns only that host agent's bootstrap token. Encrypted chezmoi owns the
reviewable, credential-value-free injection catalog.
