Type: grilling
Status: resolved

## Question

What happens when provider readiness fails before or during a managed launch?

## Answer

Keep consumer bindings configured, fail the credential-dependent launch with
one actionable error, emit a host-native startup notification, and expose
status and retry through `secretctl`.
