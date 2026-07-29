# Separate the control plane from the data plane

Type: grilling
Status: resolved

## Question

How should the operator and consumer execution surfaces be divided?

## Answer

Make `secretctl` the single operator control plane. Keep `secret-exec` as the
small credential-bearing data plane. Absorb migration and session helpers
behind those two surfaces rather than exposing peer operator tools.
