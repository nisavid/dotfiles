Type: grilling
Status: resolved

## Question

What interface should the first complete secret control plane provide?

## Answer

Ship a CLI with concise human output and stable JSON for inventory, status,
diagnosis, enrollment, rotation, binding, and addition workflows. Use secure
interactive input only when a credential enters the system. Defer a TUI.
